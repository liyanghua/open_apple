"""Read-only benchmark aggregation and SLA gating for cinematic-fast runs."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from lib.events import read_events
from lib.remotion_runtime import probe_remotion_runtime
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


RUN_TYPES = ("cold", "warm", "audio_only")
SLA_RULES = {
    "cold": {"minimum_runs": 3, "median_seconds": 4 * 3600, "max_seconds": 5 * 3600},
    "warm": {"minimum_runs": 5, "median_seconds": 75 * 60, "max_seconds": 90 * 60},
    "audio_only": {"minimum_runs": 3, "median_seconds": 10 * 60, "max_seconds": 15 * 60},
}
MEDIA_EXTENSIONS = {
    ".aac", ".flac", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".mpeg",
    ".mpg", ".ogg", ".wav", ".webm",
}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _round_seconds(value: float) -> float:
    return round(max(0.0, value), 3)


def _union_seconds(intervals: Iterable[tuple[datetime, datetime]]) -> float:
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    if not ordered:
        return 0.0
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += (current_end - current_start).total_seconds()
        current_start, current_end = start, end
    total += (current_end - current_start).total_seconds()
    return _round_seconds(total)


def _operation_name(event: dict[str, Any]) -> str:
    return str(event.get("operation") or event.get("tool") or "unknown")


def _execution_intervals(events: list[dict[str, Any]]) -> dict[str, list[tuple[datetime, datetime]]]:
    pending: dict[str, deque[datetime]] = defaultdict(deque)
    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    ordered = sorted(
        ((timestamp, event) for event in events if (timestamp := _parse_timestamp(event.get("ts")))),
        key=lambda item: item[0],
    )
    for timestamp, event in ordered:
        operation = _operation_name(event)
        event_type = event.get("event")
        if event_type == "start":
            pending[operation].append(timestamp)
            continue
        if event_type not in {"finish", "error"}:
            continue
        duration = event.get("duration_s")
        if isinstance(duration, (int, float)) and float(duration) >= 0:
            start = timestamp - timedelta(seconds=float(duration))
            if pending[operation]:
                pending[operation].popleft()
        elif pending[operation]:
            start = pending[operation].popleft()
        else:
            continue
        intervals[operation].append((start, timestamp))
    return dict(intervals)


def _cache_counts(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"hits": 0, "misses": 0})
    for event in events:
        event_type = event.get("event")
        cache_status = event.get("cache_status")
        is_hit = event_type == "cache_hit" or cache_status == "hit" or event.get("cache_hit") is True
        is_miss = event_type == "cache_miss" or cache_status == "miss" or event.get("cache_hit") is False
        if is_hit:
            counts[_operation_name(event)]["hits"] += 1
        elif is_miss:
            counts[_operation_name(event)]["misses"] += 1
    return dict(counts)


def _operation_stats(events: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[tuple[datetime, datetime]]]:
    intervals = _execution_intervals(events)
    cache = _cache_counts(events)
    stats: dict[str, dict[str, Any]] = {}
    all_intervals: list[tuple[datetime, datetime]] = []
    for operation in sorted(set(intervals) | set(cache)):
        operation_intervals = intervals.get(operation, [])
        all_intervals.extend(operation_intervals)
        durations = [(end - start).total_seconds() for start, end in operation_intervals]
        cache_hits = cache.get(operation, {}).get("hits", 0)
        cache_misses = cache.get(operation, {}).get("misses", 0)
        cache_total = cache_hits + cache_misses
        recent = durations[-5:]
        stats[operation] = {
            "count": len(durations),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": round(cache_hits / cache_total, 4) if cache_total else None,
            "active_seconds": _union_seconds(operation_intervals),
            "median_seconds": _round_seconds(median(durations)) if durations else None,
            "max_seconds": _round_seconds(max(durations)) if durations else None,
            "rolling_eta_seconds": _round_seconds(median(recent)) if recent else None,
            "estimate_confidence": "high" if len(recent) >= 3 else "low",
        }
    return stats, all_intervals


def _observed_human_wait(checkpoints: list[dict[str, Any]]) -> float:
    pending: dict[str, deque[datetime]] = defaultdict(deque)
    total = 0.0
    ordered = sorted(
        (
            (timestamp, checkpoint)
            for checkpoint in checkpoints
            if (timestamp := _parse_timestamp(checkpoint.get("timestamp")))
        ),
        key=lambda item: item[0],
    )
    for timestamp, checkpoint in ordered:
        gate = str(checkpoint.get("approval_group") or checkpoint.get("stage") or "unknown")
        if checkpoint.get("status") == "awaiting_human":
            pending[gate].append(timestamp)
        elif checkpoint.get("status") == "completed" and pending[gate]:
            total += (timestamp - pending[gate].popleft()).total_seconds()
    return _round_seconds(total)


def aggregate_run(run: dict[str, Any]) -> dict[str, Any]:
    """Aggregate one benchmark run without double-counting parallel work."""
    events = [
        event for event in (run.get("events") or [])
        if _operation_name(event) != "fastline_metrics"
    ]
    checkpoints = list(run.get("checkpoints") or [])
    run_type = str(run.get("run_type") or "observed")
    operations, all_intervals = _operation_stats(events)
    active_seconds = _union_seconds(all_intervals)
    observed_human_wait = _observed_human_wait(checkpoints)
    default_gate_count = 2 if run_type in {"cold", "warm"} else 0
    gate_count = int(run.get("normalized_gate_count", default_gate_count))
    gate_seconds = float(run.get("normalized_gate_seconds", 600))
    human_wait_seconds = _round_seconds(max(0, gate_count) * max(0.0, gate_seconds))
    return {
        "run_id": str(run.get("run_id") or "unknown"),
        "run_type": run_type,
        "environment_fingerprint": run.get("environment_fingerprint"),
        "active_seconds": active_seconds,
        "observed_human_wait_seconds": observed_human_wait,
        "human_wait_seconds": human_wait_seconds,
        "end_to_end_seconds": _round_seconds(active_seconds + human_wait_seconds),
        "normalized_gate_count": max(0, gate_count),
        "operations": operations,
    }


def evaluate_sla(run_summaries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Gate each advertised SLA independently on sample count and thresholds."""
    result: dict[str, dict[str, Any]] = {}
    for run_type, rule in SLA_RULES.items():
        values = [
            float(run["end_to_end_seconds"])
            for run in run_summaries
            if run.get("run_type") == run_type
        ]
        eligible = len(values) >= rule["minimum_runs"]
        measured_median = _round_seconds(median(values)) if values else None
        measured_max = _round_seconds(max(values)) if values else None
        thresholds_passed = bool(
            eligible
            and measured_median is not None
            and measured_median <= rule["median_seconds"]
            and measured_max is not None
            and measured_max <= rule["max_seconds"]
        )
        if not eligible:
            reason = f"requires at least {rule['minimum_runs']} runs"
        elif thresholds_passed:
            reason = "sample floor and thresholds passed"
        else:
            reason = "measured median or slowest run exceeded threshold"
        result[run_type] = {
            "sample_count": len(values),
            "minimum_runs": rule["minimum_runs"],
            "eligible": eligible,
            "median_seconds": measured_median,
            "max_seconds": measured_max,
            "median_limit_seconds": rule["median_seconds"],
            "max_limit_seconds": rule["max_seconds"],
            "publish_sla": thresholds_passed,
            "reason": reason,
        }
    return result


def _merge_operation_stats(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    events_by_operation: dict[str, list[float]] = defaultdict(list)
    active_by_operation: dict[str, float] = defaultdict(float)
    cache_by_operation: dict[str, dict[str, int]] = defaultdict(lambda: {"hits": 0, "misses": 0})
    for run in runs:
        events = [
            event for event in (run.get("events") or [])
            if _operation_name(event) != "fastline_metrics"
        ]
        intervals = _execution_intervals(events)
        cache = _cache_counts(events)
        for operation, operation_intervals in intervals.items():
            events_by_operation[operation].extend(
                (end - start).total_seconds() for start, end in operation_intervals
            )
            active_by_operation[operation] += _union_seconds(operation_intervals)
        for operation, counts in cache.items():
            cache_by_operation[operation]["hits"] += counts["hits"]
            cache_by_operation[operation]["misses"] += counts["misses"]

    merged: dict[str, dict[str, Any]] = {}
    for operation in sorted(set(events_by_operation) | set(cache_by_operation)):
        durations = events_by_operation.get(operation, [])
        recent = durations[-5:]
        hits = cache_by_operation[operation]["hits"]
        misses = cache_by_operation[operation]["misses"]
        cache_total = hits + misses
        merged[operation] = {
            "count": len(durations),
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_hit_rate": round(hits / cache_total, 4) if cache_total else None,
            "active_seconds": _round_seconds(active_by_operation[operation]),
            "median_seconds": _round_seconds(median(durations)) if durations else None,
            "max_seconds": _round_seconds(max(durations)) if durations else None,
            "rolling_eta_seconds": _round_seconds(median(recent)) if recent else None,
            "estimate_confidence": "high" if len(recent) >= 3 else "low",
        }
    return merged


class FastlineMetrics(BaseTool):
    name = "fastline_metrics"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, disk_mb=10)
    capabilities = ["aggregate_fastline_benchmarks", "gate_fastline_sla"]
    best_for = ["measuring cold, warm, and audio-only cinematic-fast runs"]
    not_good_for = ["starting pipelines", "rendering media", "paid generation"]
    side_effects = ["writes one JSON report under analysis/benchmarks"]
    user_visible_verification = ["report contains environment fingerprint and per-workflow SLA gate"]
    input_schema = {
        "type": "object",
        "required": ["project_dir"],
        "properties": {
            "project_dir": {"type": "string"},
            "source_dir": {"type": "string"},
            "run_paths": {"type": "array", "items": {"type": "string"}},
            "run_type": {"type": "string", "enum": ["cold", "warm", "audio_only", "observed"]},
            "timestamp": {"type": "string"},
        },
    }

    @staticmethod
    def _command_version(command: list[str]) -> str | None:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        lines = (result.stdout or result.stderr or "").splitlines()
        return lines[0].strip() if lines else None

    @staticmethod
    def _mac_cpu_model() -> str | None:
        try:
            result = subprocess.run(
                ["system_profiler", "SPHardwareDataType", "-json"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                return None
            payload = json.loads(result.stdout or "{}")
            hardware = payload.get("SPHardwareDataType") or []
            if not hardware or not isinstance(hardware[0], dict):
                return None
            return hardware[0].get("chip_type") or hardware[0].get("machine_name")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return None

    @staticmethod
    def _environment_fingerprint() -> dict[str, Any]:
        runtime = probe_remotion_runtime()
        cpu_model = platform.processor() or platform.machine()
        if platform.system() == "Darwin":
            cpu_model = (
                FastlineMetrics._command_version(["sysctl", "-n", "machdep.cpu.brand_string"])
                or FastlineMetrics._mac_cpu_model()
                or cpu_model
            )
        try:
            ram_bytes = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (AttributeError, OSError, ValueError):
            ram_bytes = 0
        chromium = runtime.get("chromium_executable")
        environment = {
            "cpu_model": cpu_model,
            "cores": os.cpu_count() or 1,
            "ram_bytes": ram_bytes,
            "os": platform.platform(),
            "macos_version": platform.mac_ver()[0] or None,
            "node_version": runtime.get("node_version"),
            "remotion_version": runtime.get("remotion_version"),
            "chromium_executable": chromium,
            "chromium_version": FastlineMetrics._command_version([chromium, "--version"]) if chromium else None,
            "ffmpeg_version": runtime.get("ffmpeg_version"),
        }
        canonical = json.dumps(environment, sort_keys=True, separators=(",", ":"), default=str)
        environment["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
        return environment

    @staticmethod
    def _probe_media_duration(path: Path) -> float:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return 0.0
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return max(0.0, float((result.stdout or "0").strip())) if result.returncode == 0 else 0.0
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0.0

    @staticmethod
    def _media_inventory(source_dir: Path) -> dict[str, Any]:
        if not source_dir.is_dir():
            return {"count": 0, "bytes": 0, "duration_seconds": 0.0, "source_dir": str(source_dir)}
        files = sorted(
            path for path in source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
        )
        return {
            "count": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "duration_seconds": _round_seconds(sum(FastlineMetrics._probe_media_duration(path) for path in files)),
            "source_dir": str(source_dir),
        }

    @staticmethod
    def _read_run_file(path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
            return [run for run in payload["runs"] if isinstance(run, dict)]
        return [payload] if isinstance(payload, dict) else []

    @staticmethod
    def _checkpoint_history(project_dir: Path) -> list[dict[str, Any]]:
        paths = [*project_dir.glob("checkpoint_*.json"), *(project_dir / "history").glob("checkpoint_*.json")]
        checkpoints = []
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                checkpoints.append(payload)
        return checkpoints

    def _load_runs(self, project_dir: Path, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        configured = inputs.get("run_paths")
        paths = [Path(path) for path in configured] if configured else sorted(
            (project_dir / "analysis" / "benchmark_runs").glob("*.json")
        )
        runs: list[dict[str, Any]] = []
        for path in paths:
            runs.extend(self._read_run_file(path))
        if runs:
            return runs
        events = read_events(project_dir)
        if not events:
            return []
        return [{
            "run_id": f"{project_dir.name}-observed",
            "run_type": inputs.get("run_type", "observed"),
            "events": events,
            "checkpoints": self._checkpoint_history(project_dir),
        }]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = Path(inputs["project_dir"])
        if not project_dir.is_dir():
            return ToolResult(success=False, error=f"Project directory not found: {project_dir}")
        try:
            runs = self._load_runs(project_dir, inputs)
            summaries = [aggregate_run(run) for run in runs]
            sample_counts = {run_type: sum(run.get("run_type") == run_type for run in summaries) for run_type in RUN_TYPES}
            source_dir = Path(inputs.get("source_dir") or project_dir / "inputs" / "source")
            environment = self._environment_fingerprint()
            cohort_fingerprint = environment.get("fingerprint")
            cohort_summaries = [
                run for run in summaries
                if run.get("run_type") in RUN_TYPES
                and run.get("environment_fingerprint") == cohort_fingerprint
            ]
            cohort_sample_counts = {
                run_type: sum(run.get("run_type") == run_type for run in cohort_summaries)
                for run_type in RUN_TYPES
            }
            excluded_runs = []
            for run in summaries:
                if run.get("run_type") not in RUN_TYPES:
                    continue
                fingerprint = run.get("environment_fingerprint")
                if fingerprint != cohort_fingerprint:
                    excluded_runs.append({
                        "run_id": run["run_id"],
                        "reason": (
                            "environment fingerprint missing"
                            if not fingerprint
                            else "environment fingerprint does not match current cohort"
                        ),
                    })
            operation_runs = [
                run for run in runs
                if run.get("environment_fingerprint") == cohort_fingerprint
                or (run.get("run_type", "observed") == "observed" and not run.get("environment_fingerprint"))
            ]
            report = {
                "version": "1.0",
                "project_id": project_dir.name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "environment": environment,
                "source_media": self._media_inventory(source_dir),
                "sample_counts": sample_counts,
                "cohort_sample_counts": cohort_sample_counts,
                "excluded_runs": excluded_runs,
                "estimate_confidence": "high" if len(cohort_summaries) >= 3 else "low",
                "operations": _merge_operation_stats(operation_runs),
                "runs": summaries,
                "sla": evaluate_sla(cohort_summaries),
            }
            stamp = inputs.get("timestamp") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output = project_dir / "analysis" / "benchmarks" / f"{stamp}.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return ToolResult(success=True, data=report, artifacts=[str(output)])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=f"Could not aggregate fastline benchmark: {exc}")

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.analysis.fastline_metrics import FastlineMetrics, aggregate_run, evaluate_sla
from tools.tool_registry import ToolRegistry


BASE = datetime(2026, 8, 15, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _ts(seconds: float) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat()


def _event(seconds: float, event: str, tool: str, **extra: object) -> dict:
    return {"ts": _ts(seconds), "event": event, "tool": tool, **extra}


def _run(
    run_id: str,
    run_type: str,
    duration: float,
    environment_fingerprint: str | None = None,
) -> dict:
    run = {
        "run_id": run_id,
        "run_type": run_type,
        "events": [
            _event(0, "start", "pipeline"),
            _event(duration, "finish", "pipeline", duration_s=duration),
        ],
        "checkpoints": [],
    }
    if environment_fingerprint:
        run["environment_fingerprint"] = environment_fingerprint
    return run


def test_parallel_events_use_wall_time_union_and_normalized_gate_wait() -> None:
    run = {
        "run_id": "cold-001",
        "run_type": "cold",
        "events": [
            _event(0, "start", "scene_detect"),
            _event(2, "start", "frame_sampler"),
            _event(5, "finish", "scene_detect", duration_s=5),
            _event(7, "finish", "frame_sampler", duration_s=5),
            _event(8, "cache_hit", "scene_detect", saved_seconds=5),
            _event(9, "cache_miss", "frame_sampler"),
        ],
        "checkpoints": [
            {"stage": "creative_lock", "status": "awaiting_human", "timestamp": _ts(20)},
            {"stage": "creative_lock", "status": "completed", "timestamp": _ts(80)},
            {"stage": "sample", "status": "awaiting_human", "timestamp": _ts(100)},
            {"stage": "sample", "status": "completed", "timestamp": _ts(220)},
        ],
    }

    summary = aggregate_run(run)

    assert summary["active_seconds"] == 7
    assert summary["observed_human_wait_seconds"] == 180
    assert summary["human_wait_seconds"] == 1200
    assert summary["end_to_end_seconds"] == 1207
    assert summary["operations"]["scene_detect"] == {
        "count": 1,
        "cache_hits": 1,
        "cache_misses": 0,
        "cache_hit_rate": 1.0,
        "active_seconds": 5.0,
        "median_seconds": 5.0,
        "max_seconds": 5.0,
        "rolling_eta_seconds": 5.0,
        "estimate_confidence": "low",
    }
    assert summary["operations"]["frame_sampler"]["cache_hit_rate"] == 0.0


def test_operation_eta_uses_last_five_and_is_high_confidence_after_three_samples() -> None:
    events = []
    cursor = 0.0
    for duration in (10, 20, 30, 40, 100, 50):
        events.extend([
            _event(cursor, "start", "video_compose"),
            _event(cursor + duration, "finish", "video_compose", duration_s=duration),
        ])
        cursor += duration + 1

    operation = aggregate_run({
        "run_id": "warm-001",
        "run_type": "warm",
        "events": events,
        "checkpoints": [],
    })["operations"]["video_compose"]

    assert operation["count"] == 6
    assert operation["median_seconds"] == 35.0
    assert operation["max_seconds"] == 100.0
    assert operation["rolling_eta_seconds"] == 40.0
    assert operation["estimate_confidence"] == "high"


def test_sla_gate_requires_sample_floor_and_all_thresholds() -> None:
    passing = [
        *[_run(f"cold-{i}", "cold", value) for i, value in enumerate((10_000, 12_000, 16_000))],
        *[_run(f"warm-{i}", "warm", value) for i, value in enumerate((2_500, 3_000, 3_300, 3_600, 4_000))],
        *[_run(f"audio-{i}", "audio_only", value) for i, value in enumerate((300, 500, 700))],
    ]
    gate = evaluate_sla([aggregate_run(run) for run in passing])

    assert gate["cold"]["publish_sla"] is True
    assert gate["warm"]["publish_sla"] is True
    assert gate["audio_only"]["publish_sla"] is True

    insufficient = evaluate_sla([aggregate_run(_run("cold-only", "cold", 100))])
    assert insufficient["cold"]["eligible"] is False
    assert insufficient["cold"]["publish_sla"] is False
    assert insufficient["cold"]["reason"] == "requires at least 3 runs"

    failed = [aggregate_run(_run(f"audio-{i}", "audio_only", value)) for i, value in enumerate((500, 600, 901))]
    assert evaluate_sla(failed)["audio_only"]["publish_sla"] is False


def test_tool_reads_run_files_writes_report_and_is_registry_discoverable(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "demo"
    run_dir = project / "analysis" / "benchmark_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "cold-001.json").write_text(
        json.dumps(_run("cold-001", "cold", 100)), encoding="utf-8"
    )
    environment = {"cpu_model": "Test CPU", "cores": 8, "fingerprint": "env-1"}
    media = {"count": 2, "bytes": 2048, "duration_seconds": 24.0}
    monkeypatch.setattr(FastlineMetrics, "_environment_fingerprint", staticmethod(lambda: environment))
    monkeypatch.setattr(FastlineMetrics, "_media_inventory", staticmethod(lambda source_dir: media))

    result = FastlineMetrics().execute({
        "project_dir": str(project),
        "timestamp": "20260815T120000Z",
    })

    output = project / "analysis" / "benchmarks" / "20260815T120000Z.json"
    assert result.success is True
    assert result.artifacts == [str(output)]
    assert output.is_file()
    assert result.data["environment"] == environment
    assert result.data["source_media"] == media
    assert result.data["sample_counts"] == {"cold": 1, "warm": 0, "audio_only": 0}
    assert result.data["sla"]["cold"]["publish_sla"] is False

    registry = ToolRegistry()
    registered = registry.discover("tools.analysis")
    assert "fastline_metrics" in registered
    assert registry.get("fastline_metrics").runtime.value == "local"


def test_benchmark_runbook_pins_sample_floor_normalization_and_sla_rules() -> None:
    runbook = (REPO_ROOT / "docs" / "benchmarks" / "cinematic-fast.md").read_text(encoding="utf-8")

    for required in ("3 cold", "5 warm", "3 audio-only", "two 10-minute gates"):
        assert required in runbook
    assert "median <= 4 hours" in runbook
    assert "median <= 75 minutes" in runbook
    assert "median <= 10 minutes" in runbook
    assert "must not be displayed as an SLA" in runbook


def test_make_target_only_invokes_read_only_metrics_aggregation() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("benchmark-fastline:", 1)[1].split("\n\n", 1)[0]

    assert "PROJECT_ID" in target
    assert "FastlineMetrics" in target
    assert "video_compose" not in target
    assert "pipeline" not in target


def test_command_version_ignores_stderr_from_failed_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], returncode=1, stdout="", stderr="Operation not permitted"
        ),
    )

    assert FastlineMetrics._command_version(["sysctl", "-n", "machdep.cpu.brand_string"]) is None


def test_metrics_tool_excludes_its_own_instrumentation_from_active_time() -> None:
    run = _run("observed-001", "observed", 10)
    run["events"].extend([
        _event(20, "start", "fastline_metrics"),
        _event(25, "finish", "fastline_metrics", duration_s=5),
    ])

    summary = aggregate_run(run)

    assert summary["active_seconds"] == 10
    assert "fastline_metrics" not in summary["operations"]


def test_macos_cpu_model_falls_back_to_system_profiler(monkeypatch) -> None:
    payload = json.dumps({"SPHardwareDataType": [{"chip_type": "Apple M4 Pro"}]})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], returncode=0, stdout=payload, stderr=""
        ),
    )

    assert FastlineMetrics._mac_cpu_model() == "Apple M4 Pro"


def test_tool_excludes_other_environment_cohorts_from_sla(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "demo"
    run_dir = project / "analysis" / "benchmark_runs"
    run_dir.mkdir(parents=True)
    for index in range(3):
        (run_dir / f"cold-{index}.json").write_text(
            json.dumps(_run(f"cold-{index}", "cold", 100, "other-environment")),
            encoding="utf-8",
        )
    monkeypatch.setattr(
        FastlineMetrics,
        "_environment_fingerprint",
        staticmethod(lambda: {"fingerprint": "current-environment"}),
    )
    monkeypatch.setattr(
        FastlineMetrics,
        "_media_inventory",
        staticmethod(lambda source_dir: {"count": 0, "bytes": 0, "duration_seconds": 0}),
    )

    report = FastlineMetrics().execute({"project_dir": str(project)}).data

    assert report["sample_counts"]["cold"] == 3
    assert report["cohort_sample_counts"]["cold"] == 0
    assert report["sla"]["cold"]["eligible"] is False
    assert {item["reason"] for item in report["excluded_runs"]} == {
        "environment fingerprint does not match current cohort"
    }

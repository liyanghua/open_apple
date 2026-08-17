"""Backlot event stream — append-only tool-event log per project.

Written by the BaseTool instrumentation layer (tools/base_tool.py) whenever a
tool executes against a project directory; consumed by the Backlot board's
watcher to power live activity and per-scene generating states.

Design rules:
- Observability must never break production: every public function swallows
  its own errors. A failed event write is silently dropped.
- Zero agent burden: project attribution is inferred from the tool's inputs
  (explicit ``project_dir`` or any path argument under ``projects/``).
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from lib.paths import PROJECTS_DIR, REPO_ROOT  # single source of truth

EVENTS_FILENAME = "events.jsonl"

# Versioned orchestration event contract (schema: schemas/events/run_event.schema.json).
# Tool lifecycle events (start/finish/error) keep their legacy loose shape for
# backward compatibility; long-running operations additionally emit schema-valid
# run events with frame/attempt/wait-reason telemetry.
RUN_EVENT_SCHEMA_VERSION = "1.0"

# Thread-level serialization only. Cross-PROCESS appends are unsynchronized
# by design: single-line O_APPEND writes rarely tear, and read_events skips
# malformed lines, so a torn line degrades to one missing activity entry.
_write_lock = threading.Lock()

_RUN_EVENT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "events"
    / "run_event.schema.json"
)


@lru_cache(maxsize=1)
def _load_run_event_schema() -> dict[str, Any]:
    with open(_RUN_EVENT_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)

# Input keys checked (in order) when inferring the project a tool call
# belongs to. Explicit project keys win over path inference.
_EXPLICIT_PROJECT_KEYS = ("project_dir", "project_path")
_PATH_HINT_KEYS = (
    "output_path",
    "output_dir",
    "output_file",
    "input_path",
    "video_path",
    "audio_path",
    "image_path",
    "file_path",
)


def infer_project_dir(inputs: Any) -> Optional[Path]:
    """Best-effort: which project directory does this tool call belong to?

    Returns None when the call can't be attributed — the event is then
    simply not emitted (principle: never guess loudly, never fail).
    """
    if not isinstance(inputs, dict):
        return None
    try:
        # Only paths under the canonical projects root are attributable —
        # an explicit project_dir pointing elsewhere (HyperFrames workspace,
        # arbitrary user dir) must not receive an events.jsonl. Explicit
        # values are normalized to the project ROOT the same way hints are,
        # so project_dir="projects/x/renders/build" attributes to projects/x.
        projects_root = PROJECTS_DIR.resolve()
        for key in _EXPLICIT_PROJECT_KEYS + _PATH_HINT_KEYS:
            value = inputs.get(key)
            if not isinstance(value, (str, Path)) or not str(value):
                continue
            try:
                resolved = Path(value).resolve()
                rel = resolved.relative_to(projects_root)
            except (ValueError, OSError):
                continue
            if rel.parts:
                return PROJECTS_DIR / rel.parts[0]
    except Exception:
        return None
    return None


def emit_event(
    project_dir: Path | str,
    payload: dict[str, Any],
    *,
    preserve_nulls: bool = False,
) -> None:
    """Append one event to the project's events.jsonl. Never raises.

    Writes only into an EXISTING project directory — a typo'd path must not
    spawn a ghost project on the board.
    """
    try:
        project_dir = Path(project_dir)
        if not project_dir.is_dir():
            return
        entry = {"ts": datetime.now(timezone.utc).isoformat()}
        entry.update(
            payload if preserve_nulls else {k: v for k, v in payload.items() if v is not None}
        )
        path = project_dir / EVENTS_FILENAME
        line = json.dumps(entry, default=str)
        with _write_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def read_events(project_dir: Path | str, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Read events for a project (oldest first). Tolerates malformed lines."""
    path = Path(project_dir) / EVENTS_FILENAME
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    if limit is not None:
        return events[-limit:]
    return events


def emit_run_event(
    project_dir: Path | str,
    *,
    run_id: str,
    stage: str,
    operation: str,
    status: str,
    attempt: Optional[int] = None,
    attempt_id: Optional[str] = None,
    unit: Optional[dict[str, Any]] = None,
    wait_reason: Optional[str] = None,
    message: Optional[str] = None,
    machine_ms: Optional[int] = None,
    approval_wait_ms: Optional[int] = None,
    retry_count: Optional[int] = None,
    cost_reservation_id: Optional[str] = None,
    eta_seconds: Optional[int] = None,
) -> None:
    """Append one schema-valid run event (contract v1). Never raises.

    Run events are the P0-1 orchestration contract: every long operation
    (renders, generation batches, uploads) emits queued/running/heartbeat/
    terminal events so the board can show progress, ETA, wait reasons and
    retries instead of a silent stage. Invalid payloads are dropped with a
    warning — observability must never break production.
    """
    try:
        payload: dict[str, Any] = {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "run_id": run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "operation": operation,
            "status": status,
        }
        for key, value in (
            ("attempt", attempt),
            ("attempt_id", attempt_id),
            ("unit", unit),
            ("wait_reason", wait_reason),
            ("message", message),
            ("machine_ms", machine_ms),
            ("approval_wait_ms", approval_wait_ms),
            ("retry_count", retry_count),
            ("cost_reservation_id", cost_reservation_id),
            ("eta_seconds", eta_seconds),
        ):
            if value is not None:
                payload[key] = value
        try:
            import jsonschema
            jsonschema.validate(instance=payload, schema=_load_run_event_schema())
        except Exception as exc:  # jsonschema.ValidationError or missing module
            import logging
            logging.getLogger(__name__).warning(
                "Dropping invalid run event (%s): %s", run_id, exc
            )
            return
        emit_event(project_dir, payload)
    except Exception:
        pass


def emit_heartbeat(
    project_dir: Path | str,
    *,
    run_id: str,
    stage: str,
    operation: str,
    unit: Optional[dict[str, Any]] = None,
    wait_reason: Optional[str] = None,
    message: Optional[str] = None,
    machine_ms: Optional[int] = None,
    attempt: Optional[int] = None,
    attempt_id: Optional[str] = None,
    retry_count: Optional[int] = None,
    cost_reservation_id: Optional[str] = None,
    eta_seconds: Optional[int] = None,
) -> None:
    """Convenience: emit a `running` heartbeat run event (5-10s cadence)."""
    emit_run_event(
        project_dir,
        run_id=run_id,
        stage=stage,
        operation=operation,
        status="running",
        unit=unit,
        wait_reason=wait_reason,
        message=message,
        machine_ms=machine_ms,
        attempt=attempt,
        attempt_id=attempt_id,
        retry_count=retry_count,
        cost_reservation_id=cost_reservation_id,
        eta_seconds=eta_seconds,
    )

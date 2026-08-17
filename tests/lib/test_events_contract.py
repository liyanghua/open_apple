"""Run-event contract v1 tests (B7) — lib/events.py + schemas/events/run_event.schema.json."""

from pathlib import Path

from lib.events import (
    RUN_EVENT_SCHEMA_VERSION,
    emit_heartbeat,
    emit_run_event,
    read_events,
)


def test_run_event_and_heartbeat_are_schema_valid(tmp_path: Path):
    emit_run_event(
        tmp_path, run_id="r-1", stage="compose", operation="remotion_render",
        status="queued",
    )
    emit_heartbeat(
        tmp_path, run_id="r-1", stage="compose", operation="remotion_render",
        unit={"kind": "frame", "current": 315, "total": 900},
        wait_reason="rendering", message="concurrency=1",
        machine_ms=12000, attempt=2, retry_count=1,
    )
    events = read_events(tmp_path)
    assert len(events) == 2
    queued, beat = events
    assert queued["schema_version"] == RUN_EVENT_SCHEMA_VERSION == "1.0"
    assert queued["status"] == "queued" and "ts" in queued
    assert beat["status"] == "running"
    assert beat["unit"] == {"kind": "frame", "current": 315, "total": 900}
    assert beat["wait_reason"] == "rendering"
    assert beat["machine_ms"] == 12000


def test_invalid_run_event_is_dropped_never_raises(tmp_path: Path):
    # Bad status enum + missing required fields must silently drop, not raise.
    emit_run_event(
        tmp_path, run_id="r-x", stage="compose", operation="remotion_render",
        status="bogus",
    )
    emit_heartbeat(
        tmp_path, run_id="r-x", stage="compose", operation="remotion_render",
        unit={"kind": "bogus_kind", "current": 1, "total": 2},
    )
    assert read_events(tmp_path) == []


def test_legacy_emit_event_shape_is_unchanged(tmp_path: Path):
    from lib.events import emit_event

    emit_event(tmp_path, {"tool": "scene_detect", "event": "finish", "duration_s": 0.2})
    events = read_events(tmp_path)
    assert len(events) == 1
    assert events[0]["tool"] == "scene_detect"
    assert events[0]["event"] == "finish"
    assert "schema_version" not in events[0]

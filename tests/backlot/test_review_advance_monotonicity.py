"""P1-④ regression: approval auto-advance must never regress existing checkpoints."""

import json
from datetime import datetime, timezone
from pathlib import Path

from backlot.operator_reviews import ReviewService


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "project.json").write_text(
        json.dumps({"project_id": "proj", "pipeline_type": "cinematic-fast"}),
        encoding="utf-8",
    )
    return project


class _RecordingSink:
    def __init__(self) -> None:
        self.staged: list[str] = []
        self.events: list[dict] = []

    def stage_json(self, rel: str, payload: dict, schema: str) -> None:
        self.staged.append((rel, payload, schema))

    def append_event(self, stream: str, payload: dict) -> None:
        self.events.append((stream, payload))


def test_approval_advance_skips_existing_next_checkpoint(tmp_path: Path):
    project = _project(tmp_path)
    # checkpoint_edit already completed — approving `sample` must NOT regress it.
    (project / "checkpoint_edit.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "project_id": "proj",
                "pipeline_type": "cinematic-fast",
                "stage": "edit",
                "status": "completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    svc = ReviewService(project)
    sink = _RecordingSink()
    svc._stage_next_transition(sink, "review-1", "sample")
    assert sink.staged == []
    assert sink.events == []
    # on-disk edit checkpoint untouched
    assert json.loads((project / "checkpoint_edit.json").read_text())["status"] == "completed"


def test_approval_advance_creates_missing_next_checkpoint(tmp_path: Path):
    project = _project(tmp_path)
    svc = ReviewService(project)
    sink = _RecordingSink()
    svc._stage_next_transition(sink, "review-1", "sample")
    assert len(sink.staged) == 1
    rel, payload, schema = sink.staged[0]
    assert rel == "checkpoint_edit.json" and schema == "checkpoint"
    assert payload["stage"] == "edit" and payload["status"] == "in_progress"
    assert payload["next_action"]["verb"] == "run_stage"
    assert len(sink.events) == 1
    stream, event = sink.events[0]
    assert stream == "events"
    assert event["schema_version"] == "1.0" and event["status"] == "queued"
    assert event["wait_reason"] == "orchestrating"

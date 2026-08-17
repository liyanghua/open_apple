"""Review-notes outbox materializer recovery tests (P1-②)."""

import json
from pathlib import Path

import pytest

from backlot.operator_errors import OperatorError
from backlot.operator_routes import (
    _existing_review_note_for_idempotency_key,
    _review_notes_materializer,
)
from backlot.project_commit import ProjectCommitStore


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_materializer_replay_does_not_duplicate(tmp_path: Path):
    materialize = _review_notes_materializer(tmp_path)
    item = {"outbox_id": "g1:0", "stream": "review_notes", "event": {"note": "n1"}}
    materialize("review_notes", item)
    materialize("review_notes", item)  # crash-replay of the same generation
    notes = _lines(tmp_path / "review_notes.jsonl")
    assert len(notes) == 1
    assert notes[0]["note"] == "n1"
    assert notes[0]["_outbox_id"] == "g1:0"  # delivery id preserved for dedupe


def test_materializer_dedupes_on_idempotency_key(tmp_path: Path):
    materialize = _review_notes_materializer(tmp_path)
    materialize(
        "review_notes",
        {"outbox_id": "g1:0", "stream": "review_notes",
         "event": {"note": "n1", "idempotency_key": "k-1"}},
    )
    materialize(
        "review_notes",
        {"outbox_id": "g2:0", "stream": "review_notes",
         "event": {"note": "n1", "idempotency_key": "k-1"}},
    )
    notes = _lines(tmp_path / "review_notes.jsonl")
    assert len(notes) == 1


def test_precommit_check_rejects_same_idempotency_key_for_different_note(tmp_path: Path):
    materialize = _review_notes_materializer(tmp_path)
    materialize(
        "review_notes",
        {"outbox_id": "g1:0", "event": {
            "note": "first", "stage": "sample", "version_ref": "v1",
            "actor": "u", "idempotency_key": "k-1",
        }},
    )
    with pytest.raises(OperatorError) as conflict:
        _existing_review_note_for_idempotency_key(
            tmp_path,
            {
                "note": "different", "stage": "sample", "version_ref": "v1",
                "actor": "u", "idempotency_key": "k-1",
            },
        )
    assert conflict.value.code == "idempotency_conflict"


def test_materializer_delegates_unknown_streams_to_canonical_targets(tmp_path: Path):
    materialize = _review_notes_materializer(tmp_path)
    event = {
        "schema_version": "1.0", "run_id": "r-1", "ts": "2026-08-17T00:00:00Z",
        "stage": "compose", "operation": "run_stage", "status": "queued",
    }
    materialize("events", {"outbox_id": "g1:0", "stream": "events", "event": event})
    materialize("events", {"outbox_id": "g1:0", "stream": "events", "event": event})  # replay
    events = _lines(tmp_path / "events.jsonl")
    assert len(events) == 1, "undrained events outbox must not be dropped or duplicated"
    assert events[0]["status"] == "queued"

    # a non-events, non-review_notes stream goes to operator/<stream>.jsonl
    materialize("audit", {"outbox_id": "g2:0", "stream": "audit", "event": {"x": 1}})
    assert _lines(tmp_path / "operator" / "audit.jsonl") == [{"x": 1, "_outbox_id": "g2:0"}]


def test_two_transactions_with_same_idempotency_key_append_once(tmp_path: Path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "project.json").write_text(json.dumps({"project_id": "proj"}))

    def run(key: str) -> None:
        store = ProjectCommitStore(
            tmp_path, outbox_materializer=_review_notes_materializer(tmp_path)
        )
        store.initialize()
        with store.transaction(
            action={"action_id": f"note-{key}", "type": "add_review_note"},
            result={"status": "recorded"},
            audit={"event_type": "review_note_added", "actor_id": "user"},
        ) as sink:
            sink.append_event(
                "review_notes",
                {"ts": "2026-08-17T00:00:00Z", "actor": "user",
                 "note": "first", "idempotency_key": key},
            )

    run("k-dup")
    run("k-dup")  # client retry with the same Idempotency-Key
    notes = _lines(tmp_path / "review_notes.jsonl")
    assert len(notes) == 1
    assert notes[0]["note"] == "first"

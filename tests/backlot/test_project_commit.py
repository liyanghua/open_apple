from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "film"
    project.mkdir()
    (project / "project.json").write_text(
        json.dumps({"project_id": "film"}), encoding="utf-8"
    )
    return project


def test_initialize_and_commit_generation_atomically(tmp_path) -> None:
    from backlot.project_commit import ProjectCommitStore

    project = _project(tmp_path)
    store = ProjectCommitStore(project)
    initial = store.initialize()
    assert initial["generation_id"] == "generation-000000"

    with store.transaction(
        action={"action_id": "action-1", "type": "save"},
        result={"status": "committed"},
        audit={"event_type": "draft_committed"},
    ) as sink:
        sink.stage_json("artifacts/script.json", {"title": "新脚本"}, schema="script")
        sink.append_event("actions", {"event_type": "draft_committed", "action_id": "action-1"})

    pointer = json.loads((project / "operator/current-generation.json").read_text())
    assert pointer["generation_id"] != initial["generation_id"]
    assert json.loads((project / "artifacts/script.json").read_text()) == {"title": "新脚本"}

    generation = project / "operator/generations" / pointer["generation_id"]
    assert (generation / "status").read_text() == "committed"
    manifest = json.loads((generation / "manifest.json").read_text())
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/backlot/generation_manifest.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(manifest)
    assert manifest["base_generation_id"] == "generation-000000"
    assert manifest["write_set"][0]["relative_path"] == "artifacts/script.json"
    assert manifest["write_set"][0]["before_missing"] is True
    assert manifest["write_set"][0]["after_sha256"]
    events = (project / "operator/actions.jsonl").read_text().splitlines()
    assert len(events) == 1


def test_sink_rejects_escape_symlink_and_use_outside_transaction(tmp_path) -> None:
    from backlot.operator_errors import OperatorError
    from backlot.project_commit import ProjectCommitStore

    project = _project(tmp_path)
    store = ProjectCommitStore(project)
    store.initialize()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "linked").symlink_to(outside, target_is_directory=True)
    (project / "linked-file.json").symlink_to(outside / "value.json")

    with pytest.raises(OperatorError) as escaped:
        with store.transaction(action={"action_id": "escape"}) as sink:
            sink.stage_json("linked/data.json", {"bad": True}, schema="test")
    assert escaped.value.code == "invalid_write_context"
    with pytest.raises(OperatorError):
        with store.transaction(action={"action_id": "file-escape"}) as linked_sink:
            linked_sink.stage_json("linked-file.json", {"bad": True}, schema="test")

    with store.transaction(action={"action_id": "valid"}) as sink:
        sink.stage_json("artifacts/value.json", {"ok": True}, schema="test")
    with pytest.raises(OperatorError) as stale:
        sink.stage_delete("artifacts/value.json")
    assert stale.value.code == "invalid_write_context"


def test_project_lock_serializes_transactions(tmp_path) -> None:
    import threading
    import time

    from backlot.project_commit import ProjectCommitStore

    project = _project(tmp_path)
    store = ProjectCommitStore(project)
    store.initialize()
    entered: list[str] = []

    def first() -> None:
        with store.transaction(action={"action_id": "first"}):
            entered.append("first")
            time.sleep(0.08)
            entered.append("first-done")

    def second() -> None:
        time.sleep(0.01)
        with ProjectCommitStore(project).transaction(action={"action_id": "second"}):
            entered.append("second")

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    two.start()
    one.join()
    two.join()
    assert entered == ["first", "first-done", "second"]

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _store(tmp_path: Path, fault: str):
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "film"
    project.mkdir()
    (project / "project.json").write_text('{"project_id":"film"}', encoding="utf-8")
    store = ProjectCommitStore(
        project,
        fault_injector=lambda point: (_ for _ in ()).throw(RuntimeError(point))
        if point == fault
        else None,
    )
    store.initialize()
    (project / "artifacts").mkdir()
    (project / "artifacts/script.json").write_text('{"version":"old"}', encoding="utf-8")
    return project, store


@pytest.mark.parametrize("fault", ["after_prepare", "after_apply"])
def test_recovery_rolls_back_when_pointer_was_not_committed(tmp_path, fault) -> None:
    from backlot.project_commit import ProjectCommitStore

    project, store = _store(tmp_path, fault)
    with pytest.raises(RuntimeError, match=fault):
        with store.transaction(action={"action_id": fault}) as sink:
            sink.stage_json("artifacts/script.json", {"version": "new"}, schema="script")

    assert ProjectCommitStore(project).recover() == "recovered"
    assert json.loads((project / "artifacts/script.json").read_text()) == {"version": "old"}
    assert ProjectCommitStore(project).recover() == "clean"


@pytest.mark.parametrize("fault", ["after_pointer", "during_outbox"])
def test_recovery_rolls_forward_and_drains_outbox_once(tmp_path, fault) -> None:
    from backlot.project_commit import ProjectCommitStore

    project, store = _store(tmp_path, fault)
    with pytest.raises(RuntimeError, match=fault):
        with store.transaction(action={"action_id": fault}) as sink:
            sink.stage_json("artifacts/script.json", {"version": "new"}, schema="script")
            sink.append_event("actions", {"event_type": "saved", "action_id": fault})

    recovered = ProjectCommitStore(project)
    assert recovered.recover() == "recovered"
    assert json.loads((project / "artifacts/script.json").read_text()) == {"version": "new"}
    assert recovered.recover() == "clean"
    assert len((project / "operator/actions.jsonl").read_text().splitlines()) == 1


def test_recovery_freezes_on_unrecognized_canonical_content(tmp_path) -> None:
    from backlot.operator_errors import OperatorError
    from backlot.project_commit import ProjectCommitStore

    project, store = _store(tmp_path, "after_apply")
    with pytest.raises(RuntimeError):
        with store.transaction(action={"action_id": "ambiguous"}) as sink:
            sink.stage_json("artifacts/script.json", {"version": "new"}, schema="script")
    (project / "artifacts/script.json").write_text('{"version":"external"}', encoding="utf-8")

    with pytest.raises(OperatorError) as failure:
        ProjectCommitStore(project).recover()
    assert failure.value.code == "recovery_required"
    assert (project / "operator/recovery-required").exists()


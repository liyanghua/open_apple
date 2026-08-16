from __future__ import annotations

import json

import pytest


def _project(tmp_path):
    project = tmp_path / "demo"; project.mkdir()
    (project / "project.json").write_text('{"project_id":"demo"}')
    return project


def test_mutation_contract_requires_all_preconditions() -> None:
    from backlot.operator_actions import MutationRequest
    from backlot.operator_errors import OperatorError

    valid = {
        "schema_version": "1.0", "idempotency_key": "action-1",
        "reason": "调整前三秒钩子", "base_revision": "r" * 64,
    }
    assert MutationRequest.from_values(**valid).reason == "调整前三秒钩子"
    for field in valid:
        broken = dict(valid); broken[field] = ""
        with pytest.raises(OperatorError) as failure:
            MutationRequest.from_values(**broken)
        assert failure.value.code == "validation_failed"


def test_same_idempotency_digest_replays_first_result_and_conflict_is_write_free(tmp_path) -> None:
    from backlot.operator_actions import ActionService
    from backlot.operator_errors import OperatorError
    from backlot.project_commit import ProjectCommitStore

    project = _project(tmp_path)
    service = ActionService(project, store=ProjectCommitStore(project))
    calls = []

    def mutate(sink):
        calls.append("called")
        sink.stage_json("artifacts/value.json", {"value": 1}, schema="test")
        return {"result_revision": "rev-1", "status": "committed", "links": {"project": "/p/demo"}}

    first = service.execute(
        action_type="draft.commit", actor_id="user-a", idempotency_key="same-key",
        request_body={"value": 1}, mutate=mutate,
    )
    replay = service.execute(
        action_type="draft.commit", actor_id="user-a", idempotency_key="same-key",
        request_body={"value": 1}, mutate=mutate,
    )
    assert replay == first
    assert calls == ["called"]
    pointer = (project / "operator/current-generation.json").read_bytes()
    with pytest.raises(OperatorError) as conflict:
        service.execute(
            action_type="draft.commit", actor_id="user-a", idempotency_key="same-key",
            request_body={"value": 2}, mutate=mutate,
        )
    assert conflict.value.code == "idempotency_conflict"
    assert (project / "operator/current-generation.json").read_bytes() == pointer


def test_audit_projection_is_idempotent_and_rebuildable(tmp_path) -> None:
    from backlot.audit import AuditStore

    audit = AuditStore(tmp_path / "backlot.db", tmp_path / "actions.jsonl")
    item = {
        "outbox_id": "generation-1:0", "stream": "audit",
        "event": {"action_id": "a1", "event_type": "draft_committed", "actor_id": "u1", "summary": "脚本已更新"},
    }
    audit.materialize("audit", item)
    audit.materialize("audit", item)
    assert len(audit.list_events()) == 1
    (tmp_path / "actions.jsonl").unlink()
    audit.rebuild_jsonl()
    lines = (tmp_path / "actions.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["summary"] == "脚本已更新"


def test_pointer_commit_before_outbox_recovers_without_reexecuting_action(tmp_path) -> None:
    from backlot.audit import AuditStore
    from backlot.operator_actions import ActionService
    from backlot.project_commit import ProjectCommitStore

    project = _project(tmp_path)
    audit = AuditStore(tmp_path / "backlot.db", project / "operator/audit-query.jsonl")
    crashing_store = ProjectCommitStore(
        project,
        outbox_materializer=audit.materialize,
        fault_injector=lambda point: (_ for _ in ()).throw(RuntimeError(point))
        if point == "during_outbox" else None,
    )
    calls = []

    def mutate(sink):
        calls.append("called")
        sink.stage_json("artifacts/value.json", {"ok": True}, schema="test")
        return {"result_revision": "rev-2", "status": "committed", "links": []}

    with pytest.raises(RuntimeError):
        ActionService(project, store=crashing_store).execute(
            action_type="draft.commit", actor_id="user-a", idempotency_key="crash-key",
            request_body={"value": 1}, mutate=mutate,
        )
    recovered_store = ProjectCommitStore(project, outbox_materializer=audit.materialize)
    assert recovered_store.recover() == "recovered"
    replay = ActionService(project, store=recovered_store).execute(
        action_type="draft.commit", actor_id="user-a", idempotency_key="crash-key",
        request_body={"value": 1}, mutate=mutate,
    )
    assert replay["result_revision"] == "rev-2"
    assert calls == ["called"]
    assert len(audit.list_events()) == 1

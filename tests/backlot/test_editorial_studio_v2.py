from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "candidate"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"project_id": "candidate"}), encoding="utf-8")
    (project / "artifacts/editorial_timeline.json").write_text(
        json.dumps({"version": "1.0", "tracks": [{"id": "video", "kind": "video", "clips": []}]}),
        encoding="utf-8",
    )
    return project


def _service(project: Path, actor: str = "operator-a"):
    from backlot.editorial_sessions import EditorialSessionService

    return EditorialSessionService(project, actor_id=actor)


def _report(project: Path, revision: int, kind: str, **values):
    path = project / "operator/editorial/versions" / str(revision)
    path.mkdir(parents=True, exist_ok=True)
    report = {"revision": revision, **values}
    report_path = path / f"{kind}-execution_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return {"report_path": report_path.relative_to(project).as_posix()}


def test_session_is_owned_by_creator_and_draft_save_is_idempotent(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    service = _service(_project(tmp_path))
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    saved = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    replay = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    assert replay["timeline_hash"] == saved["timeline_hash"]
    assert service.load_session(session["session_id"])["revision"] == 1
    with pytest.raises(OperatorError) as forbidden:
        _service(service.project_dir, "operator-b").load_session(session["session_id"])
    assert forbidden.value.code == "forbidden"


def test_same_idempotency_key_with_different_payload_is_conflict(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    service = _service(_project(tmp_path))
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    with pytest.raises(OperatorError) as conflict:
        service.save_draft(session["session_id"], {"op": "set_caption", "text": "B"}, idempotency_key="delta-1")
    assert conflict.value.code == "idempotency_conflict"


def test_two_deltas_on_same_base_hash_use_generation_cas(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    base_hash, generation = session["timeline_hash"], session["base_generation_id"]
    service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-a", base_timeline_hash=base_hash, expected_generation=generation)
    with pytest.raises(OperatorError) as stale:
        service.save_draft(session["session_id"], {"op": "set_caption", "text": "B"}, idempotency_key="delta-b", base_timeline_hash=base_hash, expected_generation=generation)
    assert stale.value.code == "revision_conflict"


def test_failed_preview_is_retained_and_new_delta_invalidates_approval(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    failed = service.record_preview(session["session_id"], _report(project, session["revision"], "preview", status="failed", error="render failed"))
    assert failed["status"] == "preview_failed"
    assert failed["preview"]["error"] == "render failed"
    session = service.record_preview(session["session_id"], _report(project, session["revision"], "preview", status="pass", output_sha256="a" * 64))
    approved = service.approve_preview(session["session_id"], output_sha256="a" * 64)
    assert approved["status"] == "preview_approved"
    changed = service.save_draft(session["session_id"], {"op": "set_caption", "text": "B"}, idempotency_key="delta-2")
    assert changed["preview"] is None
    with pytest.raises(OperatorError):
        service.request_final(changed["session_id"])


def test_final_requires_current_preview_approval_and_server_pass_report(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    with pytest.raises(OperatorError):
        service.request_final(session["session_id"])
    service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass", output_sha256="a" * 64))
    service.approve_preview(session["session_id"], output_sha256="a" * 64)
    queued = service.request_final(session["session_id"])
    assert queued["status"] == "final_queued"
    failed = service.record_final(session["session_id"], _report(project, 1, "final", status="fail", output_sha256="b" * 64, gates={"alignment": "fail"}))
    assert failed["status"] == "final_failed"
    assert service.current_delivery() is None


def test_generation_advance_during_render_rejects_stale_preview_result(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    store = service.store
    with store.transaction(action={"action_id": "external-render-race", "type": "external_edit"}, result={"status": "committed"}) as sink:
        sink.stage_json("artifacts/external.json", {"changed": True}, schema="operator_state")
    with pytest.raises(OperatorError) as stale:
        service.record_preview(session["session_id"], _report(project, session["revision"], "preview", status="pass", output_sha256="a" * 64))
    assert stale.value.code == "revision_conflict"
    assert service.load_session(session["session_id"])["preview"] is None


def test_generation_advance_before_promote_rejects_stale_delivery_pointer_update(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    session = service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass", output_sha256="a" * 64))
    session = service.approve_preview(session["session_id"], output_sha256="a" * 64)
    session = service.request_final(session["session_id"])
    final = project / "renders/new.mp4"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"new-delivery")
    final_hash = hashlib.sha256(final.read_bytes()).hexdigest()
    session = service.record_final(session["session_id"], _report(project, 1, "final", status="pass", output_sha256=final_hash, output_path="renders/new.mp4", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"}))
    with service.store.transaction(action={"action_id": "external-promote-race", "type": "external_edit"}, result={"status": "committed"}) as sink:
        sink.stage_json("artifacts/external-promote.json", {"changed": True}, schema="operator_state")
    with pytest.raises(OperatorError) as stale:
        service.promote(session["session_id"])
    assert stale.value.code == "revision_conflict"
    assert service.current_delivery() is None


def test_promote_discard_and_restore_prior_delivery_revision(tmp_path: Path) -> None:
    project = _project(tmp_path)
    service = _service(project)
    old = project / "renders/old.mp4"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old-delivery")
    old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
    service.install_delivery_revision("old", output_path=old, qa_report={"status": "pass", "gates": {"alignment": "pass", "l1a": "pass", "final_qa": "pass"}, "server_owned": True})
    session = service.create_session(base_timeline={"clips": []}, idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass", output_sha256="a" * 64))
    service.approve_preview(session["session_id"], output_sha256="a" * 64)
    service.request_final(session["session_id"])
    final = project / "renders/new.mp4"
    final.write_bytes(b"new-delivery")
    final_hash = hashlib.sha256(final.read_bytes()).hexdigest()
    service.record_final(session["session_id"], _report(project, 1, "final", status="pass", output_sha256=final_hash, output_path="renders/new.mp4", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"}))
    promoted = service.promote(session["session_id"])
    assert promoted["status"] == "promoted"
    assert service.current_delivery()["version_id"] != "old"
    discarded = service.create_session(base_timeline={"clips": []}, idempotency_key="open-2")
    assert service.discard(discarded["session_id"])["status"] == "discarded"
    restored = service.restore_delivery_revision("old", actor_id="operator-a", expected_generation=service.store.initialize()["generation_id"], manifest_sha256=service.delivery_manifest_hash("old"), output_sha256=old_hash, idempotency_key="restore-1")
    assert restored["version_id"] == "old"

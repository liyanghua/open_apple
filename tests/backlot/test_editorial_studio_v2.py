from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "candidate"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"project_id": "candidate"}), encoding="utf-8")
    timeline = {
        "version": "1.0", "timeline_id": "timeline-1",
        "profile": {"profile_id": "taobao-detail-3-4", "aspect_ratio": "3:4", "width": 1080, "height": 1440, "fps": 30, "render_runtime": "remotion", "safe_zone": "taobao_detail_3_4"},
        "base_generation_id": "generation-000000", "base_edit_revision": "edit-000000",
        "source_artifact_hashes": {"edit_decisions": "a" * 64, "final_props": "b" * 64, "asset_manifest": "c" * 64, "coverage_matrix": "d" * 64, "product_facts": "e" * 64},
        "tracks": [
            {"id": "video", "kind": "video", "clips": [{"id": "video-1", "asset_id": "asset-1", "source_sha256": "a" * 64, "source_in_seconds": 0, "source_out_seconds": 1, "start_seconds": 0, "fact_scope": {"claim_ids": ["claim-1"], "shot_id": "shot-1", "visual_requirement_id": "visual-1", "allowed_source_classes": ["owned_source"]}}]},
            {"id": "narration", "kind": "narration", "clips": []},
            {"id": "music", "kind": "music", "clips": []},
            {"id": "text", "kind": "text", "clips": [{"id": "text-1", "text": "A", "start_seconds": 0, "end_seconds": 1, "style_token": "taobao_selling_point_v1", "position": "top_center", "claim_ids": ["claim-1"]}]},
            {"id": "subtitle", "kind": "subtitle", "clips": [{"id": "subtitle-1", "text": "A", "start_seconds": 0, "end_seconds": 1, "style_token": "taobao_subtitle_v1", "position": "bottom_center", "claim_ids": ["claim-1"], "original_text_sha256": "a" * 64}]},
        ],
    }
    (project / "artifacts/editorial_timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    from lib.cache_keys import canonical_digest
    catalogue = {
        "version": "1.0",
        "project_id": "candidate",
        "candidate_id": "candidate",
        "timeline_id": timeline["timeline_id"],
        "base_generation_id": timeline["base_generation_id"],
        "base_edit_revision": timeline["base_edit_revision"],
        "timeline_hash": canonical_digest(timeline),
        "source_artifact_hashes": dict(timeline["source_artifact_hashes"]),
        "assets": [],
    }
    catalogue["catalogue_hash"] = canonical_digest(catalogue)
    (project / "operator/editorial").mkdir(parents=True, exist_ok=True)
    (project / "operator/editorial/asset-catalogue.json").write_text(json.dumps(catalogue), encoding="utf-8")
    return project


def _service(project: Path, actor: str = "operator-a"):
    from backlot.editorial_sessions import EditorialSessionService

    return EditorialSessionService(project, actor_id=actor)


def _canonical_timeline(project: Path) -> dict:
    return json.loads((project / "artifacts/editorial_timeline.json").read_text())


def _rebind_catalogue(project: Path, timeline: dict) -> None:
    """Keep the fixture catalogue bound to the exact server artifact snapshot."""
    from lib.cache_keys import canonical_digest

    path = project / "operator/editorial/asset-catalogue.json"
    catalogue = json.loads(path.read_text())
    catalogue.update(
        timeline_id=timeline["timeline_id"],
        base_generation_id=timeline["base_generation_id"],
        base_edit_revision=timeline["base_edit_revision"],
        timeline_hash=canonical_digest(timeline),
        source_artifact_hashes=dict(timeline["source_artifact_hashes"]),
    )
    catalogue.pop("catalogue_hash", None)
    catalogue["catalogue_hash"] = canonical_digest(catalogue)
    path.write_text(json.dumps(catalogue), encoding="utf-8")


def _write_timeline(project: Path, timeline: dict) -> None:
    (project / "artifacts/editorial_timeline.json").write_text(
        json.dumps(timeline), encoding="utf-8"
    )
    _rebind_catalogue(project, timeline)


def _report(project: Path, revision: int, kind: str, **values):
    revision_id = f"edit-{revision:06d}"
    path = project / "operator/editorial/versions" / revision_id
    path.mkdir(parents=True, exist_ok=True)
    failed_without_output = values.pop("_without_output", False)
    output_bytes = values.pop("_output_bytes", f"{kind}-output".encode())
    report = {"version": "editorial-execution-1.0", "revision": revision_id, "kind": kind, **values}
    if not failed_without_output:
        output = path / f"{kind}.mp4"
        output.write_bytes(output_bytes)
        report.update(output_path=output.relative_to(project).as_posix(), output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    report_path = path / f"{kind}-execution_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return {"report_path": report_path.relative_to(project).as_posix()}


def test_session_is_owned_by_creator_and_draft_save_is_idempotent(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    saved = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    replay = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    assert replay["timeline_hash"] == saved["timeline_hash"]
    assert service.load_session(session["session_id"])["revision"] == 1
    with pytest.raises(OperatorError) as forbidden:
        _service(service.project_dir, "operator-b").load_session(session["session_id"])
    assert forbidden.value.code == "forbidden"


def test_same_idempotency_key_with_different_payload_is_conflict(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    with pytest.raises(OperatorError) as conflict:
        service.save_draft(session["session_id"], {"op": "set_caption", "text": "B"}, idempotency_key="delta-1")
    assert conflict.value.code == "idempotency_conflict"


def test_two_deltas_on_same_base_hash_use_generation_cas(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    base_hash, generation = session["timeline_hash"], session["base_generation_id"]
    service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-a", base_timeline_hash=base_hash, expected_generation=generation)
    with pytest.raises(OperatorError) as stale:
        service.save_draft(session["session_id"], {"op": "set_caption", "text": "B"}, idempotency_key="delta-b", base_timeline_hash=base_hash, expected_generation=generation)
    assert stale.value.code == "revision_conflict"


def test_failed_preview_is_retained_and_new_delta_invalidates_approval(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    failed = service.record_preview(session["session_id"], _report(project, session["revision"], "preview", status="failed", error="render failed", _without_output=True))
    assert failed["status"] == "preview_failed"
    assert failed["preview"]["error"] == "render failed"
    session = service.record_preview(session["session_id"], _report(project, session["revision"], "preview", status="pass"))
    approved = service.approve_preview(session["session_id"], output_sha256=session["preview"]["output_sha256"])
    assert approved["status"] == "preview_approved"
    changed = service.save_draft(session["session_id"], {"op": "set_caption", "text": "B"}, idempotency_key="delta-2")
    assert changed["preview"] is None
    with pytest.raises(OperatorError):
        service.request_final(changed["session_id"])


def test_final_requires_current_preview_approval_and_server_pass_report(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    with pytest.raises(OperatorError):
        service.request_final(session["session_id"])
    session = service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass"))
    service.approve_preview(session["session_id"], output_sha256=session["preview"]["output_sha256"])
    queued = service.request_final(session["session_id"])
    assert queued["status"] == "final_queued"
    failed = service.record_final(session["session_id"], _report(project, 1, "final", status="fail", gates={"alignment": "fail"}, _without_output=True))
    assert failed["status"] == "final_failed"
    assert service.current_delivery() is None


def test_generation_advance_during_render_rejects_stale_preview_result(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    store = service.store
    with store.transaction(action={"action_id": "external-render-race", "type": "external_edit"}, result={"status": "committed"}) as sink:
        sink.stage_json("artifacts/external.json", {"changed": True}, schema="operator_state")
    with pytest.raises(OperatorError) as stale:
        service.record_preview(session["session_id"], _report(project, session["revision"], "preview", status="pass"))
    assert stale.value.code == "revision_conflict"
    assert service.load_session(session["session_id"])["preview"] is None


def test_generation_advance_before_promote_rejects_stale_delivery_pointer_update(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    session = service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass"))
    session = service.approve_preview(session["session_id"], output_sha256=session["preview"]["output_sha256"])
    session = service.request_final(session["session_id"])
    session = service.record_final(session["session_id"], _report(project, 1, "final", status="pass", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"}, _output_bytes=b"new-delivery"))
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
    timeline = _canonical_timeline(project)
    timeline["base_generation_id"] = service.store.initialize()["generation_id"]
    _write_timeline(project, timeline)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    session = service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass"))
    service.approve_preview(session["session_id"], output_sha256=session["preview"]["output_sha256"])
    service.request_final(session["session_id"])
    service.record_final(session["session_id"], _report(project, 1, "final", status="pass", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"}, _output_bytes=b"new-delivery"))
    promoted = service.promote(session["session_id"])
    assert promoted["status"] == "promoted"
    assert service.current_delivery()["version_id"] != "old"
    timeline = _canonical_timeline(project)
    timeline["base_generation_id"] = service.store.initialize()["generation_id"]
    _write_timeline(project, timeline)
    discarded = service.create_session(idempotency_key="open-2")
    assert service.discard(discarded["session_id"])["status"] == "discarded"
    restored = service.restore_delivery_revision("old", actor_id="operator-a", expected_generation=service.store.initialize()["generation_id"], manifest_sha256=service.delivery_manifest_hash("old"), output_sha256=old_hash, idempotency_key="restore-1")
    assert restored["version_id"] == "old"


def test_report_path_must_be_canonical_for_current_revision(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    wrong = project / "operator/editorial/versions/edit-000001/not-execution.json"
    wrong.parent.mkdir(parents=True, exist_ok=True)
    wrong.write_text(json.dumps({"revision": 1, "status": "pass"}), encoding="utf-8")
    with pytest.raises(OperatorError) as failure:
        service.record_preview(session["session_id"], {"report_path": wrong.relative_to(project).as_posix()})
    assert failure.value.code == "forbidden"


def test_preview_approval_rehashes_output_and_rejects_replacement(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    session = service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass"))
    output = project / "operator/editorial/versions/edit-000001/preview.mp4"
    output.write_bytes(b"tampered")
    with pytest.raises(OperatorError) as failure:
        service.approve_preview(session["session_id"], output_sha256=session["preview"]["output_sha256"])
    assert failure.value.code == "revision_conflict"


def test_malformed_json_report_is_operator_error(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    report = project / "operator/editorial/versions/edit-000001/preview-execution_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("[]", encoding="utf-8")
    with pytest.raises(OperatorError):
        service.record_preview(session["session_id"], {"report_path": report.relative_to(project).as_posix()})


def test_promote_requires_strict_server_owned_final_report(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-1")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-1")
    session = service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass"))
    session = service.approve_preview(session["session_id"], output_sha256=session["preview"]["output_sha256"])
    session = service.request_final(session["session_id"])
    session = service.record_final(session["session_id"], _report(project, 1, "final", status="pass", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"}))
    path = project / "operator/editorial/sessions" / f"{session['session_id']}.json"
    mutated = json.loads(path.read_text(encoding="utf-8"))
    mutated["final"]["server_owned"] = False
    path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(OperatorError) as failure:
        service.promote(session["session_id"])
    assert failure.value.code == "forbidden"


def test_task5_execution_report_contract_uses_revision_id_for_preview_and_final(tmp_path: Path) -> None:
    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-task5")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-task5")

    preview = service.record_preview(session["session_id"], _report(project, 1, "preview", status="pass", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"}))
    assert preview["preview"]["revision"] == "edit-000001"
    preview = service.approve_preview(session["session_id"], output_sha256=preview["preview"]["output_sha256"])
    service.request_final(session["session_id"])

    final = service.record_final(session["session_id"], _report(project, 1, "final", status="pass", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"}))
    assert final["status"] == "final_review"
    assert final["final"]["report_path"] == "operator/editorial/versions/edit-000001/final-execution_report.json"


def test_execution_report_kind_must_match_record_operation(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    session = service.create_session(idempotency_key="open-kind")
    session = service.save_draft(session["session_id"], {"op": "set_caption", "text": "A"}, idempotency_key="delta-kind")

    final_report = _report(project, 1, "final", status="pass", gates={"alignment": "pass", "l1a": "pass", "final_qa": "pass"})
    with pytest.raises(OperatorError) as failure:
        service.record_preview(session["session_id"], final_report)
    assert failure.value.code == "forbidden"


def test_create_rejects_timeline_generation_mismatch_and_client_catalogue_is_not_accepted(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    timeline = json.loads((project / "artifacts/editorial_timeline.json").read_text())
    timeline["base_generation_id"] = "generation-client-forged"
    with pytest.raises(OperatorError) as mismatch:
        service.create_session(base_timeline=timeline, idempotency_key="bad-generation")
    assert mismatch.value.code == "revision_conflict"

    # The service only reads the server-owned catalogue path.  A client
    # supplied field must not be accepted as an implicit catalogue.
    timeline = json.loads((project / "artifacts/editorial_timeline.json").read_text())
    session = service.create_session(base_timeline=timeline, idempotency_key="server-only-catalogue")
    assert session["asset_catalogue"] == json.loads(
        (project / "operator/editorial/asset-catalogue.json").read_text()
    )


def test_create_fails_closed_when_server_catalogue_is_missing(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    (project / "operator/editorial/asset-catalogue.json").unlink()
    with pytest.raises(OperatorError) as failure:
        _service(project).create_session(idempotency_key="missing-catalogue")
    assert failure.value.code == "recovery_required"


def test_create_fails_closed_when_canonical_timeline_is_schema_invalid(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    timeline = _canonical_timeline(project)
    timeline.pop("tracks")
    _write_timeline(project, timeline)
    with pytest.raises(OperatorError) as failure:
        _service(project).create_session(idempotency_key="invalid-timeline")
    assert failure.value.code == "recovery_required"


def test_create_rejects_requested_candidate_id_not_bound_to_server_catalogue(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    with pytest.raises(OperatorError) as failure:
        _service(project).create_session(
            candidate_id="different-candidate", idempotency_key="candidate-mismatch"
        )
    assert failure.value.code == "validation_failed"


def test_save_draft_rejects_unsupported_or_cross_scope_operation(tmp_path: Path) -> None:
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = _service(project)
    timeline = json.loads((project / "artifacts/editorial_timeline.json").read_text())
    session = service.create_session(base_timeline=timeline, idempotency_key="typed-op")
    with pytest.raises(OperatorError) as failure:
        service.save_draft(session["session_id"], {"operations": [{"op": "replace_clip", "track_id": "video", "clip_id": "video-1", "asset_id": "forged", "source_sha256": "a" * 64, "source_in_seconds": 0, "source_out_seconds": 1}]}, idempotency_key="replace-forged")
    assert failure.value.code == "validation_failed"

import hashlib
import json

import pytest

from backlot.operator_reviews import ReviewService
from scripts import migrate_towel_production_evidence as migration


def imported_project(root, monkeypatch, *, approved=True):
    def put(ref, value):
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    put("project.json", {"project_id": root.name})
    (root / "film.mp4").write_bytes(b"accepted film")
    sha = hashlib.sha256(b"accepted film").hexdigest()
    put("props.json", {"title": "accepted"})
    put("records/A01/production_record.json", {"content_slot_id": "A01",
        "render": {"path": "film.mp4", "sha256": sha},
        "canonical_artifacts": {"final_props": "props.json"}})
    put("artifacts/production_migration_20260924.json", {"version": "1.0"})
    put("records/video_cost.json", {"entries": []})
    service = ReviewService(root)
    review = service.create_final_review(record_path="records/A01/production_record.json", submitted_by="historical-import")
    if approved:
        service.decide(review_id=review["review_id"], decision="approved", actor_id="user:yichen",
            reason="Accepted exact version", expected_version=review["subject_version"], expected_hash=review["subject_hash"])
    monkeypatch.setattr(migration, "PROJECT", root)
    monkeypatch.setattr(migration, "WAVE", "records")
    monkeypatch.setattr(migration, "EXPECTED", {"A01": sha})
    return service, review


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_unchanged_historical_import_replay_does_not_write(tmp_path, monkeypatch):
    imported_project(tmp_path, monkeypatch)
    before = snapshot(tmp_path)
    migration.migrate()
    assert snapshot(tmp_path) == before


def test_historical_import_replay_does_not_approve_changed_dependencies(tmp_path, monkeypatch):
    imported_project(tmp_path, monkeypatch)
    (tmp_path / "props.json").write_text('{"title":"changed"}')
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="Historical approval"):
        migration.migrate()
    assert snapshot(tmp_path) == before


def test_old_marker_without_pinned_approval_cannot_resume_pending_review(tmp_path, monkeypatch):
    imported_project(tmp_path, monkeypatch, approved=False)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="Historical approval"):
        migration.migrate()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("changed", [False, True])
def test_pinned_interrupted_migration_resumes_only_exact_subject(tmp_path, monkeypatch, changed):
    service, review = imported_project(tmp_path, monkeypatch, approved=False)
    (tmp_path / "artifacts/production_migration_20260924.json").write_text(json.dumps({
        "version": "1.0", "approval_subject_hashes": {"A01": review["subject_hash"]}}))
    if changed:
        (tmp_path / "props.json").write_text('{"title":"changed"}')
        before = snapshot(tmp_path)
        with pytest.raises(ValueError, match="Historical approval"):
            migration.migrate()
        assert snapshot(tmp_path) == before
    else:
        migration.migrate()
        assert service.review_state(review["review_id"])["status"] == "approved"
        before = snapshot(tmp_path)
        migration.migrate()
        assert snapshot(tmp_path) == before


def test_accounted_receipt_replay_does_not_rewrite_ledger(tmp_path, monkeypatch):
    imported_project(tmp_path, monkeypatch)
    task = {"id": "provider-task", "status": "succeeded", "usage": {"tokens": 120}}
    estimate = {"amount": 1.5, "currency": "CNY"}
    (tmp_path / "records/video_cost.json").write_text(json.dumps({"entries": [{
        "id": "cost-1", "operation": "A01", "status": "completed", "usage": task["usage"],
        "provider_status": "succeeded", "provider_task_id": task["id"], "catalog_estimate": estimate,
        "actual_cost": None, "provider_billing_status": "unconfirmed"}]}))
    (tmp_path / "records/A01/query_result.json").write_text(json.dumps({"data": {"task": task}}))
    persisted_calls = []

    class OfflineTool:
        def reconcile_task(self, task, inputs):
            if inputs.get("reservation_id"):
                persisted_calls.append(inputs)
            return {"catalog_estimate": estimate}

    monkeypatch.setattr(migration, "SeedanceArkVideo", OfflineTool)
    before = snapshot(tmp_path)
    migration.migrate()
    assert persisted_calls == []
    assert snapshot(tmp_path) == before

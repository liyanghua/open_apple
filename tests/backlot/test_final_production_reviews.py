import hashlib
import json

import pytest

from backlot.operator_errors import OperatorError
from backlot.operator_reviews import ReviewService


def make_record(root, slot="A01"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(json.dumps({"project_id": root.name}))
    (root / f"{slot}.mp4").write_bytes(slot.encode())
    (root / f"{slot}-props.json").write_text("{}")
    record = {"content_slot_id": slot, "provenance": "legacy_import", "render": {
        "path": f"{slot}.mp4", "sha256": hashlib.sha256(slot.encode()).hexdigest()},
        "canonical_artifacts": {"final_props": f"{slot}-props.json"}}
    name = f"{slot}-record.json"
    (root / name).write_text(json.dumps(record))
    return name


def approve(service, review):
    return service.decide(review_id=review["review_id"], decision="approved", actor_id="user",
                          reason="验收通过", expected_version=review["subject_version"], expected_hash=review["subject_hash"])


def test_final_approvals_are_per_item_and_never_advance_legacy_checkpoints(tmp_path):
    root = tmp_path / "film"
    a, b = make_record(root), make_record(root, "A03")
    service = ReviewService(root)
    ra = service.create_final_review(record_path=a, submitted_by="pipeline")
    rb = service.create_final_review(record_path=b, submitted_by="pipeline")
    assert service.create_final_review(record_path=a, submitted_by="pipeline")["review_id"] == ra["review_id"]
    assert all(r["status"] == "awaiting_human" for r in service.list())
    decided = approve(service, ra)
    assert decided["status"] == "approved"
    assert decided["production_subject"]["render"]["path"] == "A01.mp4"
    assert service.review_state(rb["review_id"])["status"] == "awaiting_human"
    assert not list(root.glob("checkpoint_*.json"))
    assert not (root / "operator/current-delivery.json").exists()


@pytest.mark.parametrize("changed", ["A01.mp4", "A01-props.json", "A01-record.json"])
def test_changed_dependency_rejects_approval_and_even_approved_replay(tmp_path, changed):
    root = tmp_path / "film"
    name = make_record(root)
    service = ReviewService(root)
    review = service.create_final_review(record_path=name, submitted_by="pipeline")
    approve(service, review)
    (root / changed).write_bytes(b"changed")
    with pytest.raises(OperatorError) as exc:
        approve(service, review)
    assert exc.value.code == "review_stale"


def test_final_review_requires_actual_snapshot_not_an_arbitrary_hash(tmp_path):
    root = tmp_path / "film"
    make_record(root)
    with pytest.raises(OperatorError):
        ReviewService(root).create(kind="final_review", subject_id="A01", subject_version=1,
                                  subject_hash="a" * 64, submitted_by="pipeline")

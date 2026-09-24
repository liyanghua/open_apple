import hashlib
import json

import pytest

from backlot.delivery_versions import DeliveryVersionService
from backlot.operator_errors import OperatorError
from backlot.operator_reviews import ReviewService
from tests.production_evidence_fixture import create_bound_quality


def prepared_delivery(root, version="v1"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(json.dumps({"project_id": root.name}))
    video = f"final-{version}.mp4"
    (root / video).write_bytes(b"film")
    sha = hashlib.sha256(b"film").hexdigest()
    qa = f"quality-{version}.json"
    record = f"record-{version}.json"
    record_doc = {"content_slot_id": version,
        "render": {"path": video, "sha256": sha, "seconds": 4}, "quality_report_ref": qa}
    quality = create_bound_quality(root, record_doc, prefix=f"evidence-{version}")
    (root / qa).write_text(json.dumps(quality))
    (root / record).write_text(json.dumps(record_doc))
    service = ReviewService(root)
    review = service.create_final_review(record_path=record, submitted_by="pipeline")
    service.decide(review_id=review["review_id"], decision="approved", actor_id="reviewer", reason="已逐项核验",
                   expected_hash=review["subject_hash"], expected_version=review["subject_version"])
    return {"schema_version": "1.0", "project_id": root.name, "version_id": version,
            "created_at": "2026-09-24T00:00:00Z", "review_revision_id": None,
            "video": {"path": video, "poster_path": None, "subtitles_path": None},
            "audio_mix": {}, "qa": {"status": "pass", "issues": []},
            "change_summary": "验收成片", "video_master_sha256": sha,
            "production_record_path": record, "final_review_id": review["review_id"]}


def test_arbitrary_overall_pass_cannot_certify(tmp_path):
    manifest = prepared_delivery(tmp_path)
    manifest.pop("production_record_path")
    manifest.pop("final_review_id")
    with pytest.raises(OperatorError):
        DeliveryVersionService(tmp_path).certify(manifest, actor_id="user")


def test_valid_evidence_and_exact_final_approval_certify(tmp_path):
    manifest = prepared_delivery(tmp_path)
    assert DeliveryVersionService(tmp_path).certify(manifest, actor_id="user")["status"] == "certified"


def test_human_accepted_legacy_without_checks_cannot_certify(tmp_path):
    manifest = prepared_delivery(tmp_path)
    qa = tmp_path / "quality-v1.json"
    report = json.loads(qa.read_text())
    report["checks"] = []
    qa.write_text(json.dumps(report))
    # Fresh human acceptance of the new bundle still does not fill missing QA.
    review = ReviewService(tmp_path).create_final_review(record_path=manifest["production_record_path"], submitted_by="pipeline")
    ReviewService(tmp_path).decide(review_id=review["review_id"], decision="approved", actor_id="user", reason="外观通过",
                                  expected_hash=review["subject_hash"], expected_version=review["subject_version"])
    manifest["final_review_id"] = review["review_id"]
    with pytest.raises(OperatorError) as exc:
        DeliveryVersionService(tmp_path).certify(manifest, actor_id="user")
    assert "检查" in exc.value.message


def test_certification_and_replay_check_live_hashes(tmp_path):
    manifest = prepared_delivery(tmp_path)
    service = DeliveryVersionService(tmp_path)
    service.certify(manifest, actor_id="user")
    (tmp_path / manifest["video"]["path"]).write_bytes(b"changed")
    with pytest.raises(OperatorError):
        service.certify(manifest, actor_id="user")

"""P2-⑥ regression: rejections must produce tagged decision_log entries."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backlot.operator_errors import OperatorError
from backlot.operator_reviews import ReviewService
from lib.artifact_hashing import verify_hashes


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "proj", "pipeline_type": "cinematic-fast"}),
        encoding="utf-8",
    )
    return project


def _review(tmp_path: Path, svc: ReviewService, review_id: str = "r-1") -> dict:
    review = {
        "schema_version": "1.0",
        "review_id": review_id,
        "project_id": "proj",
        "kind": "sample",
        "subject_id": "sample-v1",
        "subject_version": 1,
        "subject_hash": "a" * 64,
        "status": "awaiting_human",
        "submitted_by": "creator",
        "decided_by": None,
        "reason": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": None,
    }
    (svc.review_dir).mkdir(parents=True, exist_ok=True)
    (svc.review_dir / f"{review_id}.json").write_text(json.dumps(review), encoding="utf-8")
    (tmp_path / "proj" / "checkpoint_sample.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "project_id": "proj",
                "pipeline_type": "cinematic-fast",
                "stage": "sample",
                "status": "awaiting_human",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    return review


def test_reject_requires_issue_tags(tmp_path: Path):
    project = _project(tmp_path)
    svc = ReviewService(project)
    _review(tmp_path, svc)
    with pytest.raises(OperatorError, match="issue_tags"):
        svc.decide(
            review_id="r-1", decision="rejected", actor_id="reviewer", reason="不行",
            expected_version=1, expected_hash="a" * 64,
        )
    with pytest.raises(OperatorError, match="issue_tags"):
        svc.decide(
            review_id="r-1", decision="rejected", actor_id="reviewer", reason="不行",
            expected_version=1, expected_hash="a" * 64, issue_tags=["not_a_tag"],
        )


def test_reject_appends_tagged_decision_log_entry(tmp_path: Path):
    project = _project(tmp_path)
    svc = ReviewService(project)
    _review(tmp_path, svc)
    result = svc.decide(
        review_id="r-1", decision="rejected", actor_id="reviewer", reason="CTA 被裁切",
        expected_version=1, expected_hash="a" * 64,
        issue_tags=["crop_mismatch", "late_cta"],
    )
    assert result["status"] == "rejected"
    log_path = project / "artifacts" / "decision_log.json"
    assert log_path.exists()
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert verify_hashes(log).valid
    rejections = [d for d in log["decisions"] if d["category"] == "review_rejection"]
    assert len(rejections) == 1
    entry = rejections[0]
    assert entry["issue_tags"] == ["crop_mismatch", "late_cta"]
    assert entry["rework_round"] == 1
    assert entry["stage"] == "sample"


def test_second_rejection_increments_rework_round(tmp_path: Path):
    project = _project(tmp_path)
    svc = ReviewService(project)
    _review(tmp_path, svc)
    svc.decide(
        review_id="r-1", decision="rejected", actor_id="reviewer", reason="不行",
        expected_version=1, expected_hash="a" * 64, issue_tags=["weak_hook"],
    )
    _review(tmp_path, svc, review_id="r-2")
    (tmp_path / "proj" / "checkpoint_sample.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "project_id": "proj",
                "pipeline_type": "cinematic-fast",
                "stage": "sample",
                "status": "awaiting_human",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    svc.decide(
        review_id="r-2", decision="rejected", actor_id="reviewer", reason="还是不行",
        expected_version=1, expected_hash="a" * 64, issue_tags=["weak_hook"],
    )
    log = json.loads((project / "artifacts" / "decision_log.json").read_text(encoding="utf-8"))
    rejections = [d for d in log["decisions"] if d["category"] == "review_rejection"]
    assert [d["rework_round"] for d in rejections] == [1, 2]

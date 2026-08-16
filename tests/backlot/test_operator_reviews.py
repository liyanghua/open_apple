from __future__ import annotations

import json
from pathlib import Path

import pytest


def _creative(tmp_path: Path):
    from backlot.project_commit import ProjectCommitStore
    from lib.approval_groups import build_approval_bundle

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}')
    for stage in ("script", "assets"):
        (project / f"checkpoint_{stage}.json").write_text(
            json.dumps({"stage": stage, "status": "awaiting_human" if stage == "assets" else "completed", "human_approved": False, "artifacts": {}})
        )
    store = ProjectCommitStore(project); store.initialize()
    manifest = {"approval_groups": {"creative": {"members": ["script", "assets"], "terminal_stage": "assets", "required_artifacts": []}}}
    with store.transaction(action={"action_id": "bundle"}) as sink:
        bundle = build_approval_bundle(project, manifest, "creative", sink=sink)
    return project, store, bundle


def test_creative_approval_is_one_atomic_terminal_transition(tmp_path) -> None:
    from backlot.operator_reviews import ReviewService

    project, store, bundle = _creative(tmp_path)
    service = ReviewService(project, store=store)
    review = service.create(
        kind="creative_lock", subject_id=bundle["bundle_id"],
        subject_version=bundle["bundle_version"], subject_hash=bundle["semantic_sha256"],
        submitted_by="operator",
    )
    approved = service.decide(
        review_id=review["review_id"], decision="approved", actor_id="reviewer",
        reason="卖点与素材匹配", expected_version=bundle["bundle_version"],
        expected_hash=bundle["semantic_sha256"],
    )
    assert approved["status"] == "approved"
    checkpoint = json.loads((project / "checkpoint_assets.json").read_text())
    assert checkpoint["status"] == "completed" and checkpoint["human_approved"] is True
    assert list((project / "artifacts/approvals").glob("*-approved.json"))
    assert service.decide(
        review_id=review["review_id"], decision="approved", actor_id="reviewer",
        reason="重复请求", expected_version=bundle["bundle_version"],
        expected_hash=bundle["semantic_sha256"],
    )["status"] == "approved"
    with pytest.raises(Exception) as race:
        service.decide(
            review_id=review["review_id"], decision="rejected", actor_id="reviewer",
            reason="改为拒绝", expected_version=bundle["bundle_version"],
            expected_hash=bundle["semantic_sha256"],
        )
    assert getattr(race.value, "code", None) == "review_already_decided"


def test_sample_rejection_keeps_media_and_removes_current_checkpoint(tmp_path) -> None:
    from backlot.operator_reviews import ReviewService
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "demo"; (project / "renders").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}')
    (project / "renders/sample.mp4").write_bytes(b"sample")
    (project / "checkpoint_sample.json").write_text(json.dumps({"stage": "sample", "status": "awaiting_human", "human_approved": False, "artifacts": {}}))
    store = ProjectCommitStore(project); store.initialize()
    service = ReviewService(project, store=store)
    review = service.create(
        kind="sample", subject_id="sample-rev-1", subject_version=1,
        subject_hash="a" * 64, submitted_by="operator",
    )
    rejected = service.decide(
        review_id=review["review_id"], decision="rejected", actor_id="reviewer",
        reason="结尾节奏太快", expected_version=1, expected_hash="a" * 64,
    )
    assert rejected["status"] == "rejected"
    assert (project / "renders/sample.mp4").exists()
    assert not (project / "checkpoint_sample.json").exists()


def test_stale_and_reviewer_required_policy_are_enforced(tmp_path) -> None:
    from backlot.operator_reviews import ReviewService
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "demo"; project.mkdir(); (project / "project.json").write_text('{"project_id":"demo"}')
    store = ProjectCommitStore(project); store.initialize()
    service = ReviewService(project, store=store, reviewer_required=True)
    review = service.create(kind="sample", subject_id="sample-1", subject_version=2, subject_hash="b" * 64, submitted_by="same-user")
    with pytest.raises(Exception) as self_review:
        service.decide(review_id=review["review_id"], decision="approved", actor_id="same-user", reason="自审", expected_version=2, expected_hash="b" * 64)
    assert getattr(self_review.value, "code", None) == "forbidden"
    with pytest.raises(Exception) as stale:
        service.decide(review_id=review["review_id"], decision="approved", actor_id="other", reason="旧页面", expected_version=1, expected_hash="b" * 64)
    assert getattr(stale.value, "code", None) == "review_stale"


def test_operator_projection_uses_active_review_and_permission_actions(tmp_path) -> None:
    from backlot.operator_state import load_operator_state
    from backlot.operator_reviews import ReviewService
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "demo"; project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "project_id": "demo", "title": "测试", "pipeline_type": "cinematic-fast",
    }))
    store = ProjectCommitStore(project); store.initialize()
    review = ReviewService(project, store=store).create(
        kind="sample", subject_id="sample-2", subject_version=2,
        subject_hash="c" * 64, submitted_by="operator",
    )
    state = load_operator_state(project, permissions=("view", "review"))
    assert state["pending_review"]["review_id"] == review["review_id"]
    assert state["pending_review"]["actions"] == ["批准", "拒绝"]
    assert state["permissions"] == ["view", "review"]

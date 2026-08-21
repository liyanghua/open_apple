import json
from pathlib import Path

import pytest

from lib.approval_groups import approve_bundle, build_approval_bundle, reject_bundle


def _manifest():
    return {"name": "test", "approval_groups": {"creative": {"members": ["script", "assets"], "terminal_stage": "assets", "required_artifacts": []}}}


def test_bundle_is_immutable_and_approve_keeps_awaiting_history(tmp_path: Path):
    project = tmp_path / "project"; (project / "artifacts").mkdir(parents=True)
    for stage in ("script", "assets"):
        (project / f"checkpoint_{stage}.json").write_text(json.dumps({"stage": stage, "status": "completed", "artifacts": {}}))
    bundle = build_approval_bundle(project, _manifest(), "creative")
    approved = approve_bundle(project, bundle["bundle_id"], approved_by="tester")
    assert approved.exists()
    assert (project / "artifacts" / "approvals" / f"{bundle['bundle_id']}-v1-awaiting_human.json").exists()
    assert json.loads(approved.read_text())["status"] == "approved"


def test_reject_writes_new_state(tmp_path: Path):
    project = tmp_path / "project"; (project / "artifacts").mkdir(parents=True)
    for stage in ("script", "assets"):
        (project / f"checkpoint_{stage}.json").write_text(json.dumps({"stage": stage, "status": "completed", "artifacts": {}}))
    bundle = build_approval_bundle(project, _manifest(), "creative")
    rejected = reject_bundle(project, bundle["bundle_id"], reason="needs revision")
    assert json.loads(rejected.read_text())["status"] == "rejected"


def test_creative_lock_bundle_requires_a_locked_director_control_plan(tmp_path: Path):
    from lib.approval_groups import build_approval_bundle

    project = tmp_path / "project"; (project / "artifacts").mkdir(parents=True)
    for stage in ("proposal", "script", "scene_plan", "assets"):
        (project / f"checkpoint_{stage}.json").write_text(
            json.dumps({
                "stage": stage,
                "status": "awaiting_human" if stage == "assets" else "completed",
                "artifacts": {"creative_control_plan": {"status": "draft"}}
                if stage == "proposal" else {},
            })
        )
    manifest = {
        "approval_groups": {
            "creative_lock": {
                "members": ["proposal", "script", "scene_plan", "assets"],
                "terminal_stage": "assets",
                "required_artifacts": ["proposal_packet", "creative_control_plan"],
            }
        }
    }
    with pytest.raises(ValueError, match="creative_control_plan.*approved"):
        build_approval_bundle(project, manifest, "creative_lock")

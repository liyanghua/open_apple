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
    for stage in ("proposal", "scene_plan", "assets"):
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
                "members": ["proposal", "scene_plan", "assets"],
                "terminal_stage": "assets",
                "required_artifacts": ["proposal_packet", "creative_control_plan"],
            }
        }
    }
    with pytest.raises(ValueError, match="creative_control_plan.*approved"):
        build_approval_bundle(project, manifest, "creative_lock")


def test_single_project_creative_lock_does_not_require_variant_plan(tmp_path: Path):
    project = tmp_path / "single-project"; (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"project_id": "single-project"}))
    for stage in ("proposal", "scene_plan", "assets"):
        (project / f"checkpoint_{stage}.json").write_text(
            json.dumps({"stage": stage, "status": "completed", "artifacts": {}})
        )
    manifest = {
        "approval_groups": {
            "creative_lock": {
                "members": ["proposal", "scene_plan", "assets"],
                "terminal_stage": "assets",
                "required_artifacts": [],
            }
        }
    }
    bundle = build_approval_bundle(project, manifest, "creative_lock")
    assert not any(ref["name"] == "candidate_variant_plan" for ref in bundle["artifact_refs"])


def _minimal_execution_artifacts(project_id: str):
    sep = {
        "version": "1.0", "project_id": project_id, "plan_id": "sep-1", "plan_version": 1,
        "status": "draft", "created_at": "2026-08-24T00:00:00+00:00",
        "creative_control_ref": {"artifact": "creative_control_plan", "version": 1, "artifact_sha256": "0" * 64},
        "script_ref": {"artifact": "script", "version": 1, "artifact_sha256": "0" * 64},
        "scene_plan_ref": {"artifact": "scene_plan", "version": 1, "artifact_sha256": "0" * 64},
        "shots": [{
            "id": "shot-01", "order": 1, "purpose": "test", "duration_seconds": 1.0,
            "narration": "n", "screen_copy": "c", "subject_action": "a", "setting": "s",
            "framing": "f", "camera": "cam", "lighting": "l", "sound": "sd",
            "evidence_type": "real_proof", "coverage_status": "enough",
            "gap_class": "none", "gap_strategy": "none",
            "source_selection": {"media_id": "m1", "path": "inputs/source/video/product/x.mp4", "start_seconds": 0, "end_seconds": 1, "fit_reason": "test"},
            "reference_mechanisms": [], "industry_notes": [],
            "control_rule_refs": [], "generation_proposals": [], "selected_generation_task_id": None,
        }],
    }
    ap = {
        "version": "1.0", "project_id": project_id, "created_at": "2026-08-24T00:00:00+00:00",
        "producer": "test", "input_hashes": {}, "planned_assets": [], "paid_generation_approved": False,
    }
    return sep, ap


def test_approve_bundle_is_pure_state_transition(tmp_path: Path):
    """approve_bundle 不应施加 creative-lock 副作用（锁执行单/授权付费）。"""
    from lib.artifact_io import write_artifact_atomic

    project = tmp_path / "project"; (project / "artifacts").mkdir(parents=True)
    for stage in ("script", "assets"):
        (project / f"checkpoint_{stage}.json").write_text(
            json.dumps({"stage": stage, "status": "completed", "artifacts": {}})
        )
    sep, ap = _minimal_execution_artifacts("project")
    write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan", sep, project_dir=project)
    write_artifact_atomic("artifacts/asset_plan.json", "asset_plan", ap, project_dir=project)

    bundle = build_approval_bundle(project, _manifest(), "creative")
    approve_bundle(project, bundle["bundle_id"], approved_by="tester")

    sep_after = json.loads((project / "artifacts" / "shot_execution_plan.json").read_text())
    ap_after = json.loads((project / "artifacts" / "asset_plan.json").read_text())
    # 纯审批：不锁执行单、不授权付费
    assert sep_after["status"] == "draft"
    assert ap_after["paid_generation_approved"] is False


def test_lock_execution_after_creative_lock_returns_new_envelopes(tmp_path: Path):
    from lib.approval_groups import lock_execution_after_creative_lock
    from lib.artifact_io import write_artifact_atomic

    project = tmp_path / "project"; (project / "artifacts").mkdir(parents=True)
    sep, ap = _minimal_execution_artifacts("project")
    write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan", sep, project_dir=project)
    write_artifact_atomic("artifacts/asset_plan.json", "asset_plan", ap, project_dir=project)

    envelopes = lock_execution_after_creative_lock(project, approved_by="tester")

    sep_after = json.loads((project / "artifacts" / "shot_execution_plan.json").read_text())
    ap_after = json.loads((project / "artifacts" / "asset_plan.json").read_text())
    assert sep_after["status"] == "approved"
    assert ap_after["paid_generation_approved"] is True
    # 返回的新 envelope 与落盘内容一致（供 decide() 刷新 checkpoint）
    assert envelopes["shot_execution_plan"]["semantic_sha256"] == sep_after["semantic_sha256"]
    assert envelopes["asset_plan"]["semantic_sha256"] == ap_after["semantic_sha256"]

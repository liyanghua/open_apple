import json
from pathlib import Path

import pytest

from lib.approval_groups import approve_bundle, build_approval_bundle, reject_bundle
from lib.artifact_hashing import attach_hashes


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


def test_paid_clean_reference_approval_does_not_unlock_image_to_video(tmp_path: Path):
    from lib.approval_groups import lock_execution_after_creative_lock
    from lib.artifact_io import write_artifact_atomic

    project = tmp_path / "product-cleanup"; (project / "artifacts").mkdir(parents=True)
    sep, _ap = _minimal_execution_artifacts("product-cleanup")
    cleanup_hash = "d" * 64
    ap = {
        "version": "1.0", "project_id": "product-cleanup",
        "created_at": "2026-09-07T00:00:00+00:00", "producer": "test",
        "input_hashes": {}, "paid_generation_approved": False,
        "approved_paid_subject_hashes": [],
        "planned_assets": [{
            "id": "clean-reference-main-03", "type": "clean_product_reference",
            "provider": "selection_pending", "model": "selection_pending",
            "cost_estimate_usd": 0.08, "paid": True,
            "output_path": "assets/product_page/derived/main-03-clean-v1.png",
            "source_stage": "assets", "exists": False,
            "visual_route": "generated_from_product_image",
            "approval_subject_hash": cleanup_hash,
            "evidence_role": "visual_expression_reference_only",
            "reference_source": {
                "asset_id": "page-main-03", "local_path": "assets/product_page/raw/main-03.webp",
                "sha256": "a" * 64, "sku_scope": ["sku-1"],
            },
            "cleanup_plan": {
                "operation": "image_edit", "prompt": "只移除文字并保持产品身份",
                "identity_requirements": ["颜色、纹理、结构不变"], "ocr_required": True,
            },
        }],
    }
    write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan", sep, project_dir=project)
    write_artifact_atomic("artifacts/asset_plan.json", "asset_plan", ap, project_dir=project)

    envelopes = lock_execution_after_creative_lock(
        project, approved_by="operator", approval_scope="clean_reference",
        approved_subject_hashes=[cleanup_hash],
    )

    sep_after = json.loads((project / "artifacts/shot_execution_plan.json").read_text())
    ap_after = json.loads((project / "artifacts/asset_plan.json").read_text())
    assert "shot_execution_plan" not in envelopes
    assert sep_after["status"] == "draft"
    assert ap_after["approval_scope"] == "clean_reference"
    assert ap_after["approved_paid_subject_hashes"] == [cleanup_hash]
    assert ap_after["paid_generation_approved"] is False


def test_image_to_video_scope_rejects_unreviewed_clean_reference(tmp_path: Path):
    from lib.approval_groups import lock_execution_after_creative_lock
    from lib.artifact_io import write_artifact_atomic

    project = tmp_path / "unreviewed-reference"; (project / "artifacts").mkdir(parents=True)
    sep, ap = _minimal_execution_artifacts("unreviewed-reference")
    subject_hash = "e" * 64
    reference = {
        "asset_id": "clean-ref", "parent_asset_id": "page-main",
        "local_path": "assets/product_page/derived/clean.png", "sha256": "c" * 64,
        "sku_scope": ["sku-1"],
    }
    ap["planned_assets"] = [{
        "id": "generated-shot-01", "type": "generated_video",
        "provider": "selection_pending", "model": "selection_pending",
        "cost_estimate_usd": 0.2, "paid": True,
        "output_path": "assets/video/shot-01-generated.mp4", "source_stage": "assets",
        "exists": False, "shot_id": "shot-01",
        "visual_route": "generated_from_product_image", "generation_reference": reference,
        "provider_candidates": [{
            "tool": "mock-i2v", "provider": "mock", "model": "v1",
            "estimated_cost_usd": 0.2, "supports_local_reference": True,
            "supports_native_3_4": True,
        }],
        "approval_subject_hash": subject_hash, "evidence_role": "visual_expression_only",
        "generation_plan": {
            "operation": "image_to_video", "prompt": "保持商品身份",
            "duration_seconds": 4, "aspect_ratio": "3:4",
            "required_actions": ["hero"], "required_results": ["identity_visible"],
            "consistency_requirements": ["身份不变"], "prohibitions": ["不得生成文字"],
            "retry_limit": 2, "approval_subject_hash": subject_hash,
            "provider_selection_status": "awaiting_human",
            "selected_provider_candidate": {
                "tool": "mock-i2v", "provider": "mock", "model": "v1",
                "estimated_cost_usd": 0.2, "supports_local_reference": True,
                "supports_native_3_4": True,
            },
        },
    }]
    write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan", sep, project_dir=project)
    write_artifact_atomic("artifacts/asset_plan.json", "asset_plan", ap, project_dir=project)
    (project / "artifacts/product_asset_ledger.json").write_text(json.dumps({
        "assets": [{**reference, "clean_reference_status": "needs_human",
                    "identity_check": {"status": "needs_human"},
                    "ocr_residual_text": [], "generation_eligibility": "blocked"}],
    }))

    with pytest.raises(ValueError, match="纯产品参考图尚未审核通过"):
        lock_execution_after_creative_lock(
            project, approved_by="operator", approval_scope="image_to_video",
            approved_subject_hashes=[subject_hash],
        )


def test_image_to_video_scope_locks_exact_provider_after_reference_review(tmp_path: Path):
    from lib.approval_groups import lock_execution_after_creative_lock
    from lib.artifact_io import write_artifact_atomic

    project = tmp_path / "reviewed-reference"; (project / "artifacts").mkdir(parents=True)
    sep, ap = _minimal_execution_artifacts("reviewed-reference")
    subject_hash = "e" * 64
    candidate = {
        "tool": "mock-i2v", "provider": "mock", "model": "v1",
        "estimated_cost_usd": 0.2, "supports_local_reference": True,
        "supports_native_3_4": True,
    }
    reference = {
        "asset_id": "clean-ref", "parent_asset_id": "page-main",
        "local_path": "assets/product_page/derived/clean.png", "sha256": "c" * 64,
        "sku_scope": ["sku-1"],
    }
    proposal = {
        "id": "generate-shot-01", "operation": "image_to_video", "prompt": "保持身份",
        "duration_seconds": 4, "aspect_ratio": "3:4", "reference_paths": [reference["local_path"]],
        "reference_asset_id": reference["asset_id"], "reference_hash": reference["sha256"],
        "provider_capability": "video_generation", "provider_candidates": [candidate],
        "selected_provider_candidate": candidate, "provider_selection_status": "awaiting_human",
        "required_actions": ["hero"], "required_results": ["identity_visible"],
        "consistency_requirements": ["身份不变"], "prohibitions": ["不得生成文字"],
        "estimated_fast_cost_usd": 0.2, "estimated_standard_cost_usd": 0.2,
        "retry_limit": 2, "approval_subject_hash": subject_hash,
        "evidence_role": "visual_expression_only", "evidence_risk": "high",
    }
    sep["shots"][0].update({
        "visual_route": "generated_from_product_image", "generation_reference": reference,
        "generation_proposals": [proposal], "source_selection": None,
        "evidence_type": "demonstration", "coverage_status": "gap",
        "gap_class": "expressive", "gap_strategy": "generate_from_product_image",
    })
    ap["planned_assets"] = [{
        "id": "generated-shot-01", "type": "generated_video", "provider": "mock", "model": "v1",
        "cost_estimate_usd": 0.2, "paid": True, "output_path": "assets/video/generated.mp4",
        "source_stage": "assets", "exists": False, "shot_id": "shot-01",
        "visual_route": "generated_from_product_image", "generation_reference": reference,
        "provider_candidates": [candidate], "approval_subject_hash": subject_hash,
        "evidence_role": "visual_expression_only",
        "generation_plan": {
            "operation": "image_to_video", "prompt": "保持身份", "duration_seconds": 4,
            "aspect_ratio": "3:4", "required_actions": ["hero"],
            "required_results": ["identity_visible"], "consistency_requirements": ["身份不变"],
            "prohibitions": ["不得生成文字"], "retry_limit": 2,
            "approval_subject_hash": subject_hash, "provider_selection_status": "awaiting_human",
            "selected_provider_candidate": candidate,
        },
    }]
    write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan", sep, project_dir=project)
    write_artifact_atomic("artifacts/asset_plan.json", "asset_plan", ap, project_dir=project)
    (project / "artifacts/product_asset_ledger.json").write_text(json.dumps({"assets": [{
        **reference, "clean_reference_status": "ready", "identity_check": {"status": "pass"},
        "ocr_residual_text": [], "generation_eligibility": "eligible",
    }]}))

    lock_execution_after_creative_lock(
        project, approved_by="operator", approval_scope="image_to_video",
        approved_subject_hashes=[subject_hash],
    )

    locked = json.loads((project / "artifacts/shot_execution_plan.json").read_text())
    assert locked["shots"][0]["generation_proposals"][0]["provider_selection_status"] == "locked"
    assert locked["shots"][0]["generation_proposals"][0]["selected_provider_candidate"] == candidate


def test_approval_bundle_derives_paid_scope_and_exact_subject_hashes(tmp_path: Path):
    project = tmp_path / "scoped-bundle"; (project / "artifacts").mkdir(parents=True)
    cleanup_hash = "f" * 64
    plan = attach_hashes({
        "version": "1.0", "project_id": "scoped-bundle",
        "created_at": "2026-09-07T00:00:00+00:00", "producer": "test",
        "input_hashes": {}, "paid_generation_approved": False,
        "planned_assets": [{
            "id": "cleanup", "type": "clean_product_reference", "provider": "pending",
            "model": "pending", "cost_estimate_usd": 0.1, "paid": True,
            "output_path": "assets/product_page/derived/clean.png", "source_stage": "assets",
            "exists": False, "approval_subject_hash": cleanup_hash,
        }],
    })
    plan_path = project / "artifacts/asset_plan.json"
    plan_path.write_text(json.dumps(plan))
    envelope = {
        "path": "artifacts/asset_plan.json", "semantic_sha256": plan["semantic_sha256"],
        "artifact_sha256": plan["artifact_sha256"],
    }
    (project / "checkpoint_script.json").write_text(json.dumps({"stage": "script", "status": "completed", "artifacts": {}}))
    (project / "checkpoint_assets.json").write_text(json.dumps({
        "stage": "assets", "status": "awaiting_human", "artifacts": {"asset_plan": envelope},
    }))

    bundle = build_approval_bundle(project, _manifest(), "creative")

    assert bundle["approval_scope"] == "clean_reference"
    assert bundle["approval_subject_hashes"] == [cleanup_hash]

    changed = dict(plan)
    changed["planned_assets"] = [dict(plan["planned_assets"][0], cost_estimate_usd=0.2)]
    changed.pop("semantic_sha256", None)
    changed.pop("artifact_sha256", None)
    plan_path.write_text(json.dumps(attach_hashes(changed)))
    with pytest.raises(Exception) as stale:
        approve_bundle(
            project, bundle["bundle_id"], approved_by="operator",
            expected_version=bundle["bundle_version"],
            expected_hash=bundle["semantic_sha256"],
        )
    assert getattr(stale.value, "code", None) == "review_stale"

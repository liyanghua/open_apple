"""Unit tests for lib.template_assets（assets 阶段制品：no-paid 计划 + fail-closed gate）。"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import get_completed_stages, get_next_stage
from lib.template_assets import (
    build_asset_plan,
    build_assets,
    build_production_lock,
    build_shot_execution_plan,
)
from lib.template_fork import fork_template_run
from lib.template_mainline import (
    _assets_approval_summary,
    _template_for_project,
    advance_run_full,
    advance_to_assets,
)
from lib.template_run_plan import create_template_run, check_template_run_plan_ready
from lib.template_source_match import match_run_plan
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]
REAL_SOURCE = ROOT / "projects/table-mat-mix-v8"
PACK = ROOT / "projects/template-pack-library/artifacts/template_pack.json"


def _setup_run(tmp_path: Path, template: dict, facts: dict, *, approved: bool = True) -> str:
    run_id = f"template-run-{template['template_id']}-ast"
    fork_template_run(run_id, source_project_dir=REAL_SOURCE, pipeline_dir=tmp_path,
                      product_facts_path=ROOT / "projects/template-pilot/artifacts/product_facts.json")
    rp = create_template_run(template, template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"},
                             product_facts_ref={"artifact_sha256": facts.get("artifact_sha256", "b" * 64)})
    match_run_plan(template.get("slots") or [], rp)
    if approved:
        rp["status"] = "approved"
        rp["differentiation_plan_ref"] = {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": "d" * 64}
    write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp, project_dir=tmp_path / run_id)
    return run_id


def test_assets_gate_blocks_unapproved_run_plan(tmp_path: Path):
    import pytest
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    run_id = _setup_run(tmp_path, template, facts, approved=False)
    # run_plan 未批准（awaiting_human）→ build_assets 必须 fail-closed 拦住
    with pytest.raises(SystemExit):
        build_assets(tmp_path / run_id, template, pipeline_dir=tmp_path)


def test_assets_gate_requires_authoritative_batch_ref_for_new_source_led_template(tmp_path: Path):
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    run_id = _setup_run(tmp_path, template, facts)
    marker_path = tmp_path / run_id / "project.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["input_mode"] = "source_led_template"
    marker["template_run"]["batch_project_id"] = "batch-root"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(SystemExit, match="differentiation"):
        build_assets(tmp_path / run_id, template, pipeline_dir=tmp_path)


def test_advance_to_assets_writes_awaiting_human_no_paid(tmp_path: Path, monkeypatch):
    from tests.lib._tablemat_pool import install_complete_pool
    install_complete_pool(monkeypatch, tmp_path)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    run_id = _setup_run(tmp_path, template, facts)
    marker_path = tmp_path / run_id / "project.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["product_input"] = {"target_platform": "taobao"}
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    advance_run_full(run_id, pipeline_dir=tmp_path, approve_control_plan=True)
    # 推进到 assets
    next_stage = advance_to_assets(run_id, pipeline_dir=tmp_path, approve_script=True)
    assert next_stage == "assets"  # awaiting_human 不计为 completed
    from lib.checkpoint import read_checkpoint
    cp = read_checkpoint(tmp_path, run_id, "assets")
    assert cp.get("status") == "awaiting_human"
    # 四个制品全部 schema 有效 + 无 paid
    for name in ("shot_execution_plan", "asset_plan", "production_lock", "approval_bundle"):
        _ = json.loads((tmp_path / run_id / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))
    ap = json.loads((tmp_path / run_id / "artifacts" / "asset_plan.json").read_text(encoding="utf-8"))
    assert ap["paid_generation_approved"] is False
    assert all(not a["paid"] for a in ap["planned_assets"])
    assert all(s["gap_strategy"] == "none" for s in json.loads((tmp_path / run_id / "artifacts" / "shot_execution_plan.json").read_text(encoding="utf-8"))["shots"])
    lock = json.loads((tmp_path / run_id / "artifacts" / "production_lock.json").read_text(encoding="utf-8"))
    assert lock["locked_values"]["platform"] == "taobao"
    assert lock["locked_values"]["output"]["profile"] == "social_vertical_3_4_2160p30"
    from backlot.operator_reviews import ReviewService
    review = ReviewService(tmp_path / run_id).pending()
    assert review is not None
    assert review["kind"] == "creative_lock"
    assert review["subject_hash"] == cp["artifacts"]["approval_bundle"]["semantic_sha256"]
    approved = ReviewService(tmp_path / run_id).decide(
        review_id=review["review_id"],
        decision="approved",
        actor_id="test-operator",
        reason="制作准备确认通过",
        expected_version=review["subject_version"],
        expected_hash=review["subject_hash"],
    )
    assert approved["status"] == "approved"
    approved_checkpoint = read_checkpoint(tmp_path, run_id, "assets")
    assert approved_checkpoint["status"] == "completed"
    assert approved_checkpoint["human_approved"] is True


def test_taobao_production_lock_uses_project_platform_master_profile_and_selected_cta(tmp_path: Path):
    project = tmp_path / "template-run-towel"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": project.name,
        "input_mode": "source_led_template",
        "product_input": {"target_platform": "taobao"},
    }), encoding="utf-8")
    (project / "artifacts" / "proposal_packet.json").write_text(json.dumps({
        "selected_concept": {"concept_id": "c1"},
        "concept_options": [
            {"id": "c1", "cta": "查看商品详情", "target_platform": "taobao"},
        ],
    }), encoding="utf-8")

    lock = build_production_lock(
        project,
        {"template_id": "towel-A"},
        {},
        {"artifact_sha256": "a" * 64, "total_duration_seconds": 30.0},
    )

    values = lock["locked_values"]
    assert values["platform"] == "taobao"
    assert values["output"] == {
        "resolution": "2160x2880",
        "fps": 30,
        "format": "mp4",
        "profile": "social_vertical_3_4_2160p30",
    }
    assert values["captions"]["safe_zone"] == "taobao_detail_3_4"
    assert values["cta"]["text"] == "查看商品详情"
    assert "69" not in values["cta"]["text"]


def test_taobao_shot_execution_plan_declares_3_4_framing(tmp_path: Path):
    project = tmp_path / "template-run-towel"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "project_id": project.name,
        "product_input": {"target_platform": "taobao"},
    }), encoding="utf-8")
    template = {
        "template_id": "towel-A",
        "slots": [{"slot_id": "slot-01", "scene": "浴室"}],
    }
    scene_plan = {
        "artifact_sha256": "b" * 64,
        "scenes": [{"id": "scene-001", "description": "连续倒水及湿润结果"}],
        "metadata": {"source_mapping": [{
            "scene_id": "scene-001",
            "template_slot_ref": "slot-01",
            "source_path": "inputs/source/video/pour.mp4",
            "source_hash": "c" * 64,
            "matrix_row_id": "evidence-001",
            "claim_ids": ["claim-001"],
            "action_keys": ["continuous_pour_water"],
            "evidence_row_ids": ["evidence-001"],
            "product_fact_refs": ["product_facts.claims[12]"],
            "product_page_refs": ["product_page_capture.fact_candidates[12]"],
            "page_asset_ids": ["page-asset-main-01"],
            "page_evidence_ids": ["page-detail-sequence"],
            "source_interval": {"start_seconds": 0.0, "end_seconds_exclusive": 3.0},
            "timeline_interval": {"start_seconds": 0.0, "end_seconds_exclusive": 3.0},
        }]},
    }
    script = {
        "artifact_sha256": "d" * 64,
        "sections": [{
            "id": "sec-001",
            "scene_id": "scene-001",
            "narration": "一股水浇下，湿润范围清楚可见",
            "screen_copy": "连续水流落下，毛圈接住水分",
            "claim_ids": ["claim-001"],
            "action_keys": ["continuous_pour_water"],
            "evidence_row_ids": ["evidence-001"],
            "product_fact_refs": ["product_facts.claims[12]"],
            "product_page_refs": ["product_page_capture.fact_candidates[12]"],
            "page_asset_ids": ["page-asset-main-01"],
            "page_evidence_ids": ["page-detail-sequence"],
            "start_seconds": 0.0,
            "end_seconds": 3.0,
        }],
    }

    plan = build_shot_execution_plan(project, template, scene_plan, {}, script)

    assert "3:4" in plan["shots"][0]["framing"]
    assert "主体" in plan["shots"][0]["framing"]
    assert plan["shots"][0]["source_selection"]["path"] == "inputs/source/video/pour.mp4"
    for field in ("product_fact_refs", "product_page_refs", "page_asset_ids", "page_evidence_ids"):
        assert plan["shots"][0][field] == script["sections"][0][field]


def test_asset_plan_keeps_each_proxy_bound_to_source_copy_and_processing_method(tmp_path: Path):
    project = tmp_path / "template-run-towel"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "project_id": project.name,
        "product_input": {"target_platform": "taobao"},
    }), encoding="utf-8")
    shot_plan = {
        "shots": [{
            "id": "shot-01",
            "purpose": "展示连续倒水后的湿润范围",
            "subject_action": "一股水连续倒在毛巾表面",
            "narration": "一股水浇下，湿润范围清楚可见。",
            "screen_copy": "连续水流吸收演示",
            "claim_ids": ["claim-absorbency"],
            "action_keys": ["continuous_pour_water"],
            "evidence_row_ids": ["evidence-pour-01"],
            "product_fact_refs": ["product_facts.claims[12]"],
            "product_page_refs": ["product_page_capture.fact_candidates[12]"],
            "page_asset_ids": ["page-asset-main-01"],
            "page_evidence_ids": ["page-detail-sequence"],
            "source_selection": {
                "media_id": "product-silver-pour",
                "path": "inputs/source/video/product-silver-pour.mp4",
                "start_seconds": 1.25,
                "end_seconds": 4.75,
                "fit_reason": "连续倒水动作与湿润结果都在同一段素材内",
            },
        }],
    }

    plan = build_asset_plan(project, {}, shot_plan)
    item = plan["planned_assets"][0]

    assert item["shot_id"] == "shot-01"
    assert item["source_selection"] == shot_plan["shots"][0]["source_selection"]
    assert item["creative_binding"] == {
        "purpose": "展示连续倒水后的湿润范围",
        "subject_action": "一股水连续倒在毛巾表面",
        "narration": "一股水浇下，湿润范围清楚可见。",
        "screen_copy": "连续水流吸收演示",
        "claim_ids": ["claim-absorbency"],
        "action_keys": ["continuous_pour_water"],
        "evidence_row_ids": ["evidence-pour-01"],
        "product_fact_refs": ["product_facts.claims[12]"],
        "product_page_refs": ["product_page_capture.fact_candidates[12]"],
        "page_asset_ids": ["page-asset-main-01"],
        "page_evidence_ids": ["page-detail-sequence"],
    }
    assert item["processing_plan"] == {
        "operation": "local_proxy_transcode",
        "tool": "media_proxy",
        "aspect_ratio": "3:4",
        "width": 540,
        "height": 720,
        "fit": "cover",
        "crop_strategy": "center_crop_subject_protected",
        "audio_policy": "proxy_muted_mix_added_at_sample",
    }


def test_generated_product_route_builds_reviewable_image_to_video_assets(tmp_path: Path) -> None:
    project = tmp_path / "template-run-generated-towel"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "project_id": project.name,
        "product_input": {"target_platform": "taobao"},
    }), encoding="utf-8")
    generation_reference = {
        "asset_id": "page-asset-main-03-clean-v1",
        "parent_asset_id": "page-asset-main-03",
        "local_path": "assets/product_page/derived/main-03-clean-v1.png",
        "sha256": "e" * 64,
        "sku_scope": ["6276962282892"],
    }
    requirement = {
        "product_fact_ref": "product_facts.claims[0]",
        "claim_id": "ag-product-expression",
        "visualizability": "non_observable",
        "required_subjects": ["target_product"],
        "required_actions": ["product_hero_display"],
        "required_results": ["product_identity_remains_visible"],
        "forbidden_substitutions": ["simulated_antibacterial_proof"],
        "allowed_wording": ["商品页标注10A级抗菌"],
        "prohibited_wording": ["实验证明杀菌"],
        "candidate_page_asset_ids": ["page-asset-main-03"],
        "sku_scope": ["6276962282892"],
        "risk_level": "high",
        "evidence_policy": {
            "fact_basis": "merchant_page_claim",
            "generated_media_role": "visual_expression_only",
            "generated_media_can_prove_claim": False,
        },
    }
    scene_plan = {
        "artifact_sha256": "b" * 64,
        "scenes": [{
            "id": "scene-001",
            "description": "产品英雄镜头，不模拟抗菌实验",
            "visual_route": "generated_from_product_image",
            "claim_visual_requirements": requirement,
            "generation_reference": generation_reference,
        }],
        "metadata": {"source_mapping": [{
            "scene_id": "scene-001",
            "template_slot_ref": "slot-01",
            "matrix_row_id": "evidence-generated-001",
            "visual_route": "generated_from_product_image",
            "claim_visual_requirements": requirement,
            "generation_reference": generation_reference,
            "generation_spec": {
                "operation": "image_to_video",
                "required_actions": ["product_hero_display"],
                "required_results": ["product_identity_remains_visible"],
                "evidence_role": "visual_expression_only",
            },
            "claim_ids": ["ag-product-expression"],
            "action_keys": ["product_hero_display"],
            "evidence_row_ids": ["evidence-generated-001"],
            "product_fact_refs": ["product_facts.claims[0]"],
            "product_page_refs": ["product_page_capture.fact_candidates[0]"],
            "page_asset_ids": ["page-asset-main-03"],
            "page_evidence_ids": ["page-shot-001"],
            "timeline_interval": {"start_seconds": 0.0, "end_seconds_exclusive": 4.0},
        }]},
    }
    script = {
        "artifact_sha256": "d" * 64,
        "sections": [{
            "id": "sec-001",
            "scene_id": "scene-001",
            "narration": "商品页标注10A级抗菌",
            "screen_copy": "商品页标注 · 10A级抗菌",
            "visual_route": "generated_from_product_image",
            "claim_visual_requirements": requirement,
            "generation_reference": generation_reference,
            "claim_ids": ["ag-product-expression"],
            "action_keys": ["product_hero_display"],
            "evidence_row_ids": ["evidence-generated-001"],
            "product_fact_refs": ["product_facts.claims[0]"],
            "product_page_refs": ["product_page_capture.fact_candidates[0]"],
            "page_asset_ids": ["page-asset-main-03"],
            "page_evidence_ids": ["page-shot-001"],
            "start_seconds": 0.0,
            "end_seconds": 4.0,
        }],
    }
    providers = [
        {
            "tool": "mock_i2v",
            "provider": "mock",
            "model": "mock-product-v1",
            "estimated_cost_usd": 0.2,
            "supports_local_reference": True,
            "supports_native_3_4": True,
        },
        {
            "tool": "premium_i2v",
            "provider": "premium",
            "model": "premium-product-v1",
            "estimated_cost_usd": 1.2,
            "supports_local_reference": True,
            "supports_native_3_4": True,
        },
    ]

    shot_plan = build_shot_execution_plan(
        project,
        {"template_id": "towel", "slots": [{"slot_id": "slot-01"}]},
        scene_plan,
        {},
        script,
        provider_candidates=providers,
    )
    shot = shot_plan["shots"][0]
    assert shot["visual_route"] == "generated_from_product_image"
    assert shot["source_selection"] is None
    assert "source_hash" not in shot
    assert "source_interval" not in shot
    assert shot["coverage_status"] == "gap"
    assert shot["gap_strategy"] == "generate_from_product_image"
    assert shot["evidence_type"] == "demonstration"
    proposal = shot["generation_proposals"][0]
    assert proposal["operation"] == "image_to_video"
    assert proposal["reference_asset_id"] == generation_reference["asset_id"]
    assert proposal["reference_hash"] == generation_reference["sha256"]
    assert proposal["aspect_ratio"] == "3:4"
    assert proposal["provider_candidates"] == providers
    assert proposal["selected_provider_candidate"] == providers[0]
    assert proposal["provider_selection_status"] == "awaiting_human"
    assert proposal["evidence_role"] == "visual_expression_only"
    assert len(proposal["approval_subject_hash"]) == 64

    plan = build_asset_plan(project, scene_plan, shot_plan)
    assert plan["paid_generation_approved"] is False
    assert [item["type"] for item in plan["planned_assets"]] == [
        "clean_product_reference", "generated_video"
    ]
    clean_reference, generated = plan["planned_assets"]
    assert clean_reference["exists"] is True
    assert clean_reference["paid"] is False
    assert generated["paid"] is True
    assert generated["exists"] is False
    assert generated["provider"] == "mock"
    assert generated["model"] == "mock-product-v1"
    assert generated["cost_estimate_usd"] == 0.2
    assert generated["generation_reference"] == generation_reference
    assert generated["generation_plan"]["selected_provider_candidate"] == providers[0]
    assert generated["generation_plan"]["approval_subject_hash"] == proposal["approval_subject_hash"]
    assert "source_selection" not in generated
    validate_artifact("shot_execution_plan", shot_plan)
    validate_artifact("asset_plan", attach_hashes(plan))


def test_assets_approval_summary_discloses_generated_and_paid_work() -> None:
    summary = _assets_approval_summary({
        "planned_assets": [
            {"type": "video_proxy", "paid": False},
            {"type": "generated_video", "paid": True, "cost_estimate_usd": 0.202},
        ]
    })

    assert "1 个商品图生成镜头" in summary
    assert "预计付费 $0.20" in summary


def test_shot_execution_plan_keeps_core_evidence_without_product_page(tmp_path: Path):
    project = tmp_path / "source-led-no-url"
    project.mkdir()
    scene_plan = {
        "artifact_sha256": "b" * 64,
        "scenes": [{"id": "scene-001", "description": "展开毛巾"}],
        "metadata": {"source_mapping": [{
            "scene_id": "scene-001", "template_slot_ref": "slot-01",
            "source_path": "inputs/source/towel.mp4", "source_hash": "c" * 64,
            "matrix_row_id": "evidence-001", "claim_ids": ["product-visible"],
            "action_keys": ["unfold_towel"], "evidence_row_ids": ["evidence-001"],
            "product_fact_refs": ["product_facts.claims[0]"],
            "source_interval": {"start_seconds": 0, "end_seconds_exclusive": 2},
            "timeline_interval": {"start_seconds": 0, "end_seconds_exclusive": 2},
        }]},
    }
    script = {"artifact_sha256": "d" * 64, "sections": [{
        "id": "sec-001", "scene_id": "scene-001", "narration": "展开毛巾",
        "screen_copy": "毛巾实拍", "claim_ids": ["product-visible"],
        "action_keys": ["unfold_towel"], "evidence_row_ids": ["evidence-001"],
        "product_fact_refs": ["product_facts.claims[0]"],
    }]}

    plan = build_shot_execution_plan(
        project, {"template_id": "t", "slots": [{"slot_id": "slot-01"}]},
        scene_plan, {}, script,
    )

    assert plan["shots"][0]["claim_ids"] == ["product-visible"]
    assert plan["shots"][0]["product_fact_refs"] == ["product_facts.claims[0]"]


def test_template_resolution_prefers_run_local_pack_for_source_led_pilot(tmp_path: Path):
    project = tmp_path / "template-run-aligned"
    (project / "artifacts").mkdir(parents=True)
    local_template = {
        "template_id": "yinlizi-aligned-A",
        "slots": [{"slot_id": "slot-01", "duration_s": 3.0}],
    }
    (project / "artifacts" / "template_pack.json").write_text(json.dumps({
        "templates": [local_template],
    }), encoding="utf-8")

    assert _template_for_project(project, "yinlizi-aligned-A") == local_template

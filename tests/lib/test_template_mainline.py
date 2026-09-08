"""集成测试：lib.template_mainline 主链路推进（proposal → script → scene_plan）。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import get_completed_stages, get_next_stage
from lib.template_fork import fork_template_run
from lib.template_mainline import (
    advance_run_full,
    load_or_build_edit_decisions,
    build_decision_log,
    build_hook_plan,
    build_proposal,
    build_script,
    rebuild_aligned_run,
    scene_plan_data,
)
from lib.template_run_plan import create_template_run
from lib.template_source_match import match_run_plan
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]
REAL_SOURCE = ROOT / "projects/table-mat-mix-v8"
PACK = ROOT / "projects/template-pack-library/artifacts/template_pack.json"


def test_load_or_build_edit_decisions_reconstructs_missing_canonical_artifact(tmp_path: Path):
    project = tmp_path / "run"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "shot_execution_plan.json").write_text(
        '{"shots":[{"id":"shot-01","duration_seconds":2,"scene_id":"scene-001",'
        '"screen_copy":"吸水","render_asset_path":"assets/video/shot-01.mp4"}]}',
        encoding="utf-8",
    )
    (project / "artifacts" / "scene_plan.json").write_text(
        '{"scenes":[{"id":"scene-001","transition_recipe_intent":"proof"}]}',
        encoding="utf-8",
    )
    edit = load_or_build_edit_decisions(project)
    assert edit["cuts"][0]["id"] == "shot-01"
    assert edit["cuts"][0]["source"] == "assets/video/shot-01.mp4"
    assert edit["caption_render_mode"] == "remotion_overlay"


def _fresh_run(tmp_path: Path, template_id: str, template: dict, facts: dict) -> Path:
    """建一条干净的 template run：fork 共享 research + 写 template_run_plan + product_facts。"""
    run_id = f"template-run-{template_id}-itest"
    fork_template_run(run_id, source_project_dir=REAL_SOURCE, pipeline_dir=tmp_path)
    rp = create_template_run(
        template,
        template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"},
        product_facts_ref={"artifact_sha256": facts.get("artifact_sha256", "b" * 64)},
        adaptation_policy=str(template.get("archetype") or "proof-first"),
    )
    match_run_plan(template.get("slots") or [], rp)
    write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp,
                          project_dir=tmp_path / run_id)
    (tmp_path / run_id / "artifacts" / "product_facts.json").write_text(
        ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    return tmp_path / run_id


def test_advance_run_full_walks_proposal_script_scene_plan(tmp_path: Path, monkeypatch):
    import json
    from tests.lib._tablemat_pool import install_complete_pool
    install_complete_pool(monkeypatch, tmp_path)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    _fresh_run(tmp_path, template["template_id"], template, facts)
    run_id = f"template-run-{template['template_id']}-itest"

    stages = advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack)
    assert stages == ["research", "proposal"]
    proposal_checkpoint = json.loads(
        (tmp_path / run_id / "checkpoint_proposal.json").read_text(encoding="utf-8")
    )
    assert "template_run_plan" in proposal_checkpoint["artifacts"]
    assert get_next_stage(tmp_path, run_id, "cinematic-fast") == "script"
    assert not (tmp_path / run_id / "checkpoint_script.json").exists()
    ccp = json.loads((tmp_path / run_id / "artifacts/creative_control_plan.json").read_text(encoding="utf-8"))
    assert ccp["status"] == "draft"

    stages = advance_run_full(
        run_id, pipeline_dir=tmp_path, pack=pack, approve_control_plan=True
    )
    assert stages == ["research", "proposal"]
    script_cp = json.loads((tmp_path / run_id / "checkpoint_script.json").read_text(encoding="utf-8"))
    assert script_cp["status"] == "awaiting_human"
    assert script_cp["human_approved"] is False
    ccp = json.loads((tmp_path / run_id / "artifacts/creative_control_plan.json").read_text(encoding="utf-8"))
    assert ccp["status"] == "approved"
    proposal = json.loads((tmp_path / run_id / "artifacts/proposal_packet.json").read_text(encoding="utf-8"))
    assert proposal["creative_control_plan"]["status"] == "approved"
    assert proposal["approval"]["status"] == "approved"


def test_advance_run_full_requires_explicit_script_approval_to_continue(tmp_path: Path, monkeypatch):
    import json
    from tests.lib._tablemat_pool import install_complete_pool
    install_complete_pool(monkeypatch, tmp_path)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    _fresh_run(tmp_path, template["template_id"], template, facts)
    run_id = f"template-run-{template['template_id']}-itest"

    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack)
    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack, approve_control_plan=True)
    stages = advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack, approve_script=True)
    assert stages == ["research", "proposal", "script", "scene_plan"]
    assert get_next_stage(tmp_path, run_id, "cinematic-fast") == "assets"

    # 制品全部 schema 有效
    for name in ("proposal_packet", "creative_control_plan", "script", "scene_plan"):
        data = json.loads((tmp_path / run_id / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))
        validate_artifact(name, data)

    # scene_plan 每个 scene 都 ground 到 matrix row
    sp = json.loads((tmp_path / run_id / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    assert len(sp["metadata"]["source_mapping"]) == len(sp["scenes"])
    assert all(m.get("matrix_row_id") for m in sp["metadata"]["source_mapping"])


def test_advance_run_full_uses_version_transactions_for_operator_managed_project(
    tmp_path: Path, monkeypatch
):
    import json
    from backlot.project_commit import ProjectCommitStore
    from backlot.operator_reviews import ReviewService
    from tests.lib._tablemat_pool import install_complete_pool

    install_complete_pool(monkeypatch, tmp_path)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    project = _fresh_run(tmp_path, template["template_id"], template, facts)
    ProjectCommitStore(project).initialize()

    assert advance_run_full(project.name, pipeline_dir=tmp_path, pack=pack) == ["research", "proposal"]
    assert advance_run_full(
        project.name, pipeline_dir=tmp_path, pack=pack, approve_control_plan=True
    ) == ["research", "proposal"]
    assert json.loads((project / "checkpoint_script.json").read_text(encoding="utf-8"))["status"] == "awaiting_human"
    review = ReviewService(project).pending()
    assert review is not None
    assert review["kind"] == "script_lock"
    assert advance_run_full(
        project.name, pipeline_dir=tmp_path, pack=pack, approve_script=True
    ) == ["research", "proposal", "script", "scene_plan"]


def test_rebuild_alignment_reopens_script_gate_and_invalidates_downstream(tmp_path: Path, monkeypatch):
    import json
    from tests.lib._tablemat_pool import install_complete_pool

    install_complete_pool(monkeypatch, tmp_path)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    project = _fresh_run(tmp_path, template["template_id"], template, facts)
    run_id = project.name
    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack)
    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack, approve_control_plan=True)
    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack, approve_script=True)
    assert (project / "checkpoint_scene_plan.json").exists()

    rebuild_aligned_run(run_id, pipeline_dir=tmp_path)

    script = json.loads((project / "artifacts/script.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((project / "checkpoint_script.json").read_text(encoding="utf-8"))
    assert script["status"] == "draft"
    assert checkpoint["status"] == "awaiting_human"
    assert checkpoint["human_approved"] is False
    assert not (project / "checkpoint_scene_plan.json").exists()


def test_rebuild_alignment_replaces_stale_operator_review_with_script_gate(
    tmp_path: Path, monkeypatch
):
    import json
    from backlot.operator_reviews import ReviewService
    from backlot.project_commit import ProjectCommitStore
    from tests.lib._tablemat_pool import install_complete_pool

    install_complete_pool(monkeypatch, tmp_path)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(
        t for t in pack["templates"]
        if t["template_id"] == "sheet-01-video1-aks-zhuodian"
    )
    facts = json.loads(
        ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json")
        .read_text(encoding="utf-8")
    )
    project = _fresh_run(tmp_path, template["template_id"], template, facts)
    ProjectCommitStore(project).initialize()
    run_id = project.name
    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack)
    advance_run_full(
        run_id, pipeline_dir=tmp_path, pack=pack, approve_control_plan=True
    )
    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack, approve_script=True)
    ReviewService(project).create(
        kind="creative_lock",
        subject_id="old-assets",
        subject_version=1,
        subject_hash="c" * 64,
        submitted_by="test",
    )

    rebuild_aligned_run(run_id, pipeline_dir=tmp_path)

    reviews = ReviewService(project).list()
    pending = [review for review in reviews if review["status"] == "awaiting_human"]
    assert len(pending) == 1
    assert pending[0]["kind"] == "script_lock"
    checkpoint = json.loads(
        (project / "checkpoint_script.json").read_text(encoding="utf-8")
    )
    assert pending[0]["subject_hash"] == checkpoint["artifacts"]["script"]["semantic_sha256"]
    stale_assets = [review for review in reviews if review["kind"] == "creative_lock"]
    assert stale_assets[-1]["status"] == "superseded"


def test_source_led_scene_and_script_use_evidence_semantics_not_template_copy(tmp_path: Path):
    import json

    project = tmp_path / "source-led-run"
    artifacts = project / "artifacts"
    artifacts.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": project.name,
        "input_mode": "source_led_template",
        "product_input": {"target_platform": "taobao"},
    }, ensure_ascii=False), encoding="utf-8")
    source_path = "inputs/source/video/product/product_银离子毛巾-吸水演示-2.MP4"
    frame = "analysis/media/absorb/frame_0002.jpg"
    matrix = {
        "matrix_mode": "source_led_template",
        "rows": [{
            "matrix_row_id": "evidence-001-claim-001",
            "source_media_id": "product_银离子毛巾-吸水演示-2",
            "source_time_range": {"start_seconds": 0.0, "end_seconds_exclusive": 7.2},
            "claim_ids": ["visible-water-contact-result"],
            "action_keys": ["continuous_pour_water", "water_contacts_towel"],
            "product_fact_refs": ["product_facts.claims[0]"],
            "product_page_refs": ["product_page_capture.fact_candidates[0]"],
            "page_asset_ids": ["page-asset-selected-sku"],
            "page_evidence_ids": ["page-shot-001"],
            "allowed_wording": ["一股水浇下，湿润范围清楚可见", "连续水流落下，毛圈接住水分"],
            "prohibited_wording": ["水滴一沾上就被吸进去", "滚筒一滚就干"],
            "evidence_class": "dynamic_result",
            "required_evidence_class": "dynamic_result",
            "requires_visible_result": True,
            "temporal_evidence": {
                "before": {"start_seconds": 0.0, "end_seconds_exclusive": 1.7},
                "action": {"start_seconds": 1.7, "end_seconds_exclusive": 4.2},
                "result": {"start_seconds": 4.2, "end_seconds_exclusive": 7.2},
            },
            "evidence_strength": "strong",
            "source_hash": "a" * 64,
            "evidence_frames": [frame],
            "resolution": "accept",
        }],
    }
    source_review = {"files": [{
        "media_id": "product_银离子毛巾-吸水演示-2",
        "path": source_path,
        "media_type": "video",
        "reviewed": True,
        "representative_frames": [frame],
        "technical_probe": {"duration_seconds": 8.0},
    }]}
    (artifacts / "reference_source_matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False), encoding="utf-8"
    )
    (artifacts / "source_media_review.json").write_text(
        json.dumps(source_review, ensure_ascii=False), encoding="utf-8"
    )
    (artifacts / "source_semantic_index.json").write_text(json.dumps({
        "input_mode": "source_led_template",
        "entries": [{
            "media_id": "product_银离子毛巾-吸水演示-2",
            "source_path": source_path,
            "source_hash": "a" * 64,
            "interval": {"start_seconds": 0.0, "end_seconds_exclusive": 7.2},
            "crop_safety": {
                "subject_complete_in_3_4": True,
                "safe_caption_regions": ["top", "bottom"],
            },
        }],
    }, ensure_ascii=False), encoding="utf-8")
    template = {"template_id": "legacy-tablemat-prior", "slots": [{
        "slot_id": "slot-001", "ordinal": 1, "duration_s": 2.5,
        "visual_content": "抗菌标识", "dialogue": "滚筒一滚，吸得干爽。",
        "overlay_text": "滚筒吸水", "caption_treatment": "none",
        "shot_language": {"shot_size": "close_up", "camera_movement": "static"},
    }]}
    run_plan = {
        "template_id": template["template_id"],
        "slot_bindings": [{
            "slot_id": "slot-001", "source": "owned",
            "source_media_id": "product_银离子毛巾-吸水演示-2",
            "evidence_row_ids": ["evidence-001-claim-001"],
        }],
    }
    (artifacts / "template_run_plan.json").write_text(
        json.dumps(run_plan, ensure_ascii=False), encoding="utf-8"
    )
    (artifacts / "research_synthesis.json").write_text(json.dumps({
        "differentiation_directions": [{
            "direction_id": "direction-proof-chain",
            "title": "连续倒水结果链",
            "promise": "连续水流与湿润结果建立可信度",
            "matrix_row_refs": ["evidence-001-claim-001"],
            "tradeoffs": ["动态镜头较长但证据完整"],
            "avoid": ["滚筒一滚就干"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    ccp = {"plan_version": 1, "artifact_sha256": "b" * 64}
    facts = {
        "product_name": "【抗菌防臭】银离子毛巾",
        "params": ["花花公子银离子纯棉毛巾"],
    }

    build_proposal(project, template, facts)
    build_hook_plan(project, template, facts)
    build_decision_log(project, template, facts)
    proposal_text = "\n".join(
        (artifacts / f"{name}.json").read_text(encoding="utf-8")
        for name in ("creative_control_plan", "proposal_packet", "hook_plan", "decision_log")
    )
    assert "连续倒水结果链" in proposal_text
    assert all(token not in proposal_text for token in ("抗菌", "防臭", "0甲醛", "桌垫", "油污一擦"))
    proposal = json.loads((artifacts / "proposal_packet.json").read_text(encoding="utf-8"))
    assert {item["target_platform"] for item in proposal["concept_options"]} == {"taobao"}
    validate_artifact("proposal_packet", proposal)
    control_plan = json.loads((artifacts / "creative_control_plan.json").read_text(encoding="utf-8"))
    assert control_plan["target_platform"] == "taobao"
    validate_artifact("creative_control_plan", control_plan)
    decision_log = json.loads((artifacts / "decision_log.json").read_text(encoding="utf-8"))
    platform_decision = next(
        item for item in decision_log["decisions"] if item["subject"] == "目标发布平台"
    )
    assert platform_decision["selected"] == "taobao"

    scene_plan = scene_plan_data(project, template, run_plan, ccp, facts)
    scene = scene_plan["scenes"][0]
    mapping = scene_plan["metadata"]["source_mapping"][0]
    assert scene["end_seconds"] == 7.2
    assert mapping["source_interval"] == {
        "start_seconds": 0.0, "end_seconds_exclusive": 7.2,
    }
    assert mapping["source_path"] == source_path
    assert mapping["subject_completeness"] == "complete"
    assert mapping["crop_strategy"] == "center crop with protected subject bounds"
    assert mapping["caption_safe_zone"] == "top"
    for owner in (scene, mapping):
        assert owner["product_fact_refs"] == ["product_facts.claims[0]"]
        assert owner["product_page_refs"] == ["product_page_capture.fact_candidates[0]"]
        assert owner["page_asset_ids"] == ["page-asset-selected-sku"]
        assert owner["page_evidence_ids"] == ["page-shot-001"]
    assert "一股水浇下" in scene["description"]
    assert all(token not in json.dumps(scene, ensure_ascii=False) for token in ("滚筒", "抗菌标识", "0甲醛", "桌垫"))

    build_script(project, template, scene_plan, ccp, facts, approved=False)
    script = json.loads((artifacts / "script.json").read_text(encoding="utf-8"))
    assert script["metadata"]["target_platform"] == "taobao"
    section = script["sections"][0]
    assert script["title"] == "花花公子银离子纯棉毛巾"
    assert section["narration"] == "一股水浇下，湿润范围清楚可见"
    assert section["screen_copy"] == "连续水流落下，毛圈接住水分"
    assert section["visual_intent"] == scene["shot_intent"]
    assert section["evidence_requirements"] == ["dynamic_result", "必须看见动作前、动作中和结果态"]
    assert section["product_fact_refs"] == ["product_facts.claims[0]"]
    assert section["product_page_refs"] == ["product_page_capture.fact_candidates[0]"]
    assert section["page_asset_ids"] == ["page-asset-selected-sku"]
    assert section["page_evidence_ids"] == ["page-shot-001"]
    assert all(token not in json.dumps(script, ensure_ascii=False) for token in ("滚筒", "抗菌", "防臭", "0甲醛", "桌垫"))

    three_beat_plan = deepcopy(scene_plan)
    three_beat_plan["scenes"] = []
    three_beat_plan["metadata"]["source_mapping"] = []
    for index in range(3):
        copied_scene = deepcopy(scene_plan["scenes"][0])
        copied_scene.update(
            id=f"scene-{index + 1:03d}",
            script_section_id=f"sec-{index + 1:03d}",
            start_seconds=index * 7.2,
            end_seconds=(index + 1) * 7.2,
        )
        copied_mapping = deepcopy(scene_plan["metadata"]["source_mapping"][0])
        copied_mapping.update(
            scene_id=copied_scene["id"],
            script_section_id=copied_scene["script_section_id"],
            timeline_interval={
                "start_seconds": copied_scene["start_seconds"],
                "end_seconds_exclusive": copied_scene["end_seconds"],
            },
        )
        three_beat_plan["scenes"].append(copied_scene)
        three_beat_plan["metadata"]["source_mapping"].append(copied_mapping)
    build_script(project, template, three_beat_plan, ccp, facts, approved=False)
    three_beat_script = json.loads((artifacts / "script.json").read_text(encoding="utf-8"))
    assert [item["beat_role"] for item in three_beat_script["sections"]] == ["hook", "reveal", "cta"]
    assert all(item["pacing"] and item["control_rule_refs"] for item in three_beat_script["sections"])
    assert all(item["review"] == "pending" and item["feedback"] == "" for item in three_beat_script["sections"])
    assert three_beat_script["metadata"]["beat_map"] == ["hook", "reveal", "cta"]


def test_source_led_generated_route_propagates_without_fake_owned_source(tmp_path: Path) -> None:
    import json

    project = tmp_path / "source-led-generated-run"
    artifacts = project / "artifacts"
    artifacts.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": project.name,
        "input_mode": "source_led_template",
        "product_input": {"target_platform": "taobao"},
    }), encoding="utf-8")
    row_id = "evidence-generated-001"
    generation_reference = {
        "asset_id": "page-asset-main-03-clean-v1",
        "parent_asset_id": "page-asset-main-03",
        "local_path": "assets/product_page/derived/main-03-clean-v1.png",
        "sha256": "d" * 64,
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
    matrix = {
        "matrix_mode": "source_led_template",
        "rows": [{
            "matrix_row_id": row_id,
            "source_media_id": None,
            "source_time_range": None,
            "claim_ids": ["ag-product-expression"],
            "action_keys": ["product_hero_display"],
            "product_fact_refs": ["product_facts.claims[0]"],
            "product_page_refs": ["product_page_capture.fact_candidates[0]"],
            "page_asset_ids": ["page-asset-main-03"],
            "page_evidence_ids": ["page-shot-001"],
            "allowed_wording": ["商品页标注10A级抗菌"],
            "prohibited_wording": ["实验证明杀菌"],
            "evidence_class": "static_feature",
            "required_evidence_class": "static_feature",
            "requires_visible_result": False,
            "temporal_evidence": None,
            "evidence_strength": "weak",
            "evidence_frames": [],
            "resolution": "accept",
            "visual_route": "generated_from_product_image",
            "claim_visual_requirements": requirement,
            "owned_candidates": [],
            "selected_source": None,
            "generation_reference": generation_reference,
            "generation_spec": {
                "operation": "image_to_video",
                "required_actions": ["product_hero_display"],
                "required_results": ["product_identity_remains_visible"],
                "evidence_role": "visual_expression_only",
            },
            "route_reason": "无可证明该不可见功效的实拍，只生成产品氛围表达",
        }],
    }
    for name, value in (
        ("reference_source_matrix", matrix),
        ("source_media_review", {"files": []}),
        ("source_semantic_index", {"entries": []}),
        ("research_synthesis", {"differentiation_directions": [{
            "direction_id": "direction-product-expression",
            "matrix_row_refs": [row_id],
        }]}),
    ):
        (artifacts / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )
    template = {"template_id": "source-led-generation", "slots": [{
        "slot_id": "slot-001",
        "ordinal": 1,
        "duration_s": 4,
        "visual_content": "银离子毛巾产品展示",
        "dialogue": "不得使用模板文案",
        "overlay_text": "不得使用模板花字",
        "caption_treatment": "none",
        "shot_language": {"shot_size": "close_up", "camera_movement": "static"},
    }]}
    run_plan = {
        "template_id": template["template_id"],
        "slot_bindings": [{
            "slot_id": "slot-001",
            "source": "generate",
            "source_media_id": None,
            "asset_type": "generated_video",
            "evidence_row_ids": [row_id],
        }],
    }
    ccp = {"plan_version": 1, "artifact_sha256": "b" * 64}
    facts = {
        "product_name": "花花公子银离子纯棉毛巾",
        "sku": "6276962282892",
        "claims": [{
            "claim": "10A级抗菌",
            "status": "needs_evidence",
            "allowed_wording": ["商品页标注10A级抗菌"],
            "prohibited_wording": ["实验证明杀菌"],
        }],
    }

    scene_plan = scene_plan_data(project, template, run_plan, ccp, facts)
    scene = scene_plan["scenes"][0]
    mapping = scene_plan["metadata"]["source_mapping"][0]
    for owner in (scene, mapping):
        assert owner["visual_route"] == "generated_from_product_image"
        assert owner["generation_reference"] == generation_reference
        assert "source_path" not in owner
        assert "source_interval" not in owner
        assert "source_hash" not in owner

    build_script(project, template, scene_plan, ccp, facts, approved=False)
    script = json.loads((artifacts / "script.json").read_text(encoding="utf-8"))
    section = script["sections"][0]
    assert section["visual_route"] == "generated_from_product_image"
    assert section["claim_visual_requirements"] == requirement
    assert section["generation_reference"] == generation_reference
    assert section["narration"] == "商品页标注10A级抗菌"
    assert section["screen_copy"] == "商品页标注10A级抗菌"
    validate_artifact("scene_plan", scene_plan)
    validate_artifact("script", script)

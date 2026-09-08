from __future__ import annotations

from copy import deepcopy

import pytest

from lib.cinematic_fast_validation import (
    validate_scene_evidence_closure,
    validate_script_evidence_closure,
)
from schemas.artifacts import validate_artifact


HASH = "a" * 64


def _matrix() -> dict:
    return {
        "matrix_mode": "source_led_template",
        "rows": [
            {
                "matrix_row_id": "evidence-001",
                "resolution": "accept",
                "source_media_id": "towel-023",
                "source_hash": HASH,
                "source_time_range": {
                    "start_seconds": 1.2,
                    "end_seconds_exclusive": 4.8,
                },
                "claim_ids": ["absorb-visible"],
                "action_keys": ["pour_water", "absorb"],
                "product_fact_refs": ["product_facts.claims[0]"],
                "product_page_refs": ["product_page_capture.fact_candidates[0]"],
                "page_asset_ids": ["page-asset-selected-sku"],
                "page_evidence_ids": ["page-shot-001"],
                "allowed_wording": ["可见吸水过程", "水分快速被带走"],
                "prohibited_wording": ["吸水率 99%"],
            }
        ],
    }


def _facts() -> dict:
    return {
        "version": "1.0",
        "product_name": "银离子毛巾",
        "claims": [
            {
                "claim": "画面可展示吸水过程",
                "status": "needs_evidence",
                "evidence": "自有素材实拍",
            },
            {
                "claim": "吸水率 99%",
                "status": "forbidden",
                "evidence": "无检测报告",
            },
        ],
    }


def _section() -> dict:
    return {
        "id": "sec-001",
        "scene_id": "scene-001",
        "text": "倒水后，水分快速被带走。",
        "narration": "倒水后，水分快速被带走。",
        "screen_copy": "可见吸水过程",
        "start_seconds": 0,
        "end_seconds": 2,
        "claim_ids": ["absorb-visible"],
        "action_keys": ["pour_water", "absorb"],
        "evidence_row_ids": ["evidence-001"],
        "product_fact_refs": ["product_facts.claims[0]"],
        "product_page_refs": ["product_page_capture.fact_candidates[0]"],
        "page_asset_ids": ["page-asset-selected-sku"],
        "page_evidence_ids": ["page-shot-001"],
        "visual_intent": "展示倒水和吸收结果",
    }


def _script() -> dict:
    return {
        "version": "1.0",
        "title": "银离子毛巾",
        "total_duration_seconds": 2,
        "sections": [_section()],
    }


def _scene_plan() -> dict:
    evidence = {
        "claim_ids": ["absorb-visible"],
        "action_keys": ["pour_water", "absorb"],
        "evidence_row_ids": ["evidence-001"],
        "product_fact_refs": ["product_facts.claims[0]"],
        "product_page_refs": ["product_page_capture.fact_candidates[0]"],
        "page_asset_ids": ["page-asset-selected-sku"],
        "page_evidence_ids": ["page-shot-001"],
    }
    return {
        "version": "1.0",
        "scenes": [
            {
                "id": "scene-001",
                "type": "broll",
                "description": "倒水后展示毛巾吸收结果",
                "start_seconds": 0,
                "end_seconds": 2,
                "script_section_id": "sec-001",
                "shot_intent": "展示可见吸水过程",
                **{key: list(value) for key, value in evidence.items()},
            }
        ],
        "metadata": {
            "reference_media_usage": "not_applicable",
            "source_mapping": [
                {
                    "scene_id": "scene-001",
                    "script_section_id": "sec-001",
                    "source_path": "inputs/source/towel-023.mp4",
                    "source_hash": HASH,
                    "source_interval": {
                        "start_seconds": 1.2,
                        "end_seconds_exclusive": 3.2,
                    },
                    "timeline_interval": {
                        "start_seconds": 0,
                        "end_seconds_exclusive": 2,
                    },
                    "matrix_row_id": "evidence-001",
                    **{key: list(value) for key, value in evidence.items()},
                }
            ],
        },
    }


def test_source_led_script_section_closes_claim_action_and_evidence() -> None:
    script = _script()

    validate_artifact("script", script)
    validate_script_evidence_closure(
        script,
        _matrix(),
        _facts(),
        input_mode="source_led_template",
    )


def test_source_led_matrix_rejects_legacy_noncanonical_row_ids() -> None:
    matrix = _matrix()
    matrix.update({
        "version": "1.0", "project_id": "towel", "created_at": "2026-09-04T00:00:00Z",
        "producer": "test", "input_hashes": {"source": HASH},
        "semantic_sha256": "b" * 64, "artifact_sha256": "c" * 64, "unmatched_gaps": [],
    })
    matrix["rows"][0].update({
        "reference_scene_id": None, "reference_time_range": None,
        "reference_intent": "source-led evidence", "match_reason": "visible",
        "confidence": 0.9, "evidence_frames": ["analysis/frame.jpg"], "unmatched_gap": None,
        "product_fact_refs": ["product_facts.claims[0]"], "prohibited_wording": [],
        "evidence_strength": "strong",
    })
    matrix["rows"][0]["matrix_row_id"] = "matrix-001"

    with pytest.raises(Exception, match="matrix_row_id"):
        validate_artifact("reference_source_matrix", matrix)


def test_source_led_matrix_accepts_generated_route_without_fake_source_interval() -> None:
    matrix = _matrix()
    matrix.update({
        "version": "1.0", "project_id": "towel", "created_at": "2026-09-07T00:00:00Z",
        "producer": "test", "input_hashes": {"product_facts": HASH},
        "semantic_sha256": "b" * 64, "artifact_sha256": "c" * 64, "unmatched_gaps": [],
    })
    matrix["rows"][0].update({
        "reference_scene_id": None,
        "reference_time_range": None,
        "reference_intent": "商品图驱动的吸水动作视觉表达",
        "source_media_id": None,
        "source_time_range": None,
        "match_reason": "无合格自有素材；使用已审核纯产品参考图",
        "confidence": 0.9,
        "evidence_frames": [],
        "unmatched_gap": None,
        "evidence_strength": "weak",
        "evidence_class": "static_feature",
        "required_evidence_class": "dynamic_result",
        "requires_visible_result": True,
        "temporal_evidence": None,
        "visual_route": "generated_from_product_image",
        "claim_visual_requirements": {
            "visualizability": "observable",
            "required_subjects": ["target_product", "water"],
            "required_actions": ["continuous_pour_water", "water_contacts_towel"],
            "required_results": ["visible_water_contact_result"],
            "forbidden_substitutions": ["single_droplet_only", "roller_only"],
            "sku_scope": ["6276962282892"],
            "evidence_policy": {
                "fact_basis": "merchant_page_claim",
                "generated_media_role": "visual_expression_only",
                "generated_media_can_prove_claim": False,
            },
        },
        "owned_candidates": [],
        "selected_source": None,
        "generation_reference": {
            "asset_id": "page-asset-main-03-clean-v1",
            "parent_asset_id": "page-asset-main-03",
            "local_path": "assets/product_page/derived/main-03-clean-v1.png",
            "sha256": "d" * 64,
            "sku_scope": ["6276962282892"],
        },
        "generation_spec": {
            "operation": "image_to_video",
            "required_actions": ["continuous_pour_water", "water_contacts_towel"],
            "required_results": ["visible_water_contact_result"],
            "evidence_role": "visual_expression_only",
        },
        "route_reason": "owned candidates did not cover the required action and result",
    })
    matrix["rows"][0].pop("source_hash", None)

    validate_artifact("reference_source_matrix", matrix)


def test_generated_route_rejects_fabricated_owned_source_fields() -> None:
    matrix = _matrix()
    matrix.update({
        "version": "1.0", "project_id": "towel", "created_at": "2026-09-07T00:00:00Z",
        "producer": "test", "input_hashes": {"product_facts": HASH},
        "semantic_sha256": "b" * 64, "artifact_sha256": "c" * 64, "unmatched_gaps": [],
    })
    row = matrix["rows"][0]
    row["visual_route"] = "generated_from_product_image"

    with pytest.raises(Exception):
        validate_artifact("reference_source_matrix", matrix)


@pytest.mark.parametrize("field", ["claim_ids", "action_keys", "evidence_row_ids", "product_fact_refs"])
def test_source_led_script_requires_explicit_evidence_fields(field: str) -> None:
    script = _script()
    script["sections"][0].pop(field)

    with pytest.raises(ValueError, match=field):
        validate_script_evidence_closure(
            script, _matrix(), _facts(), input_mode="source_led_template"
        )


def test_source_led_script_rejects_claim_or_action_not_owned_by_matrix_rows() -> None:
    script = _script()
    script["sections"][0]["action_keys"] = ["touch_softness"]

    with pytest.raises(ValueError, match="action_keys.*evidence rows"):
        validate_script_evidence_closure(
            script, _matrix(), _facts(), input_mode="source_led_template"
        )


def test_source_led_script_visual_route_must_equal_its_matrix_row() -> None:
    matrix = _matrix()
    matrix["rows"][0]["visual_route"] = "generated_from_product_image"
    matrix["rows"][0]["generation_reference"] = {
        "asset_id": "page-asset-main-03-clean-v1",
        "sha256": "d" * 64,
    }
    script = _script()
    script["sections"][0]["visual_route"] = "owned_source"
    script["sections"][0]["generation_reference"] = None

    with pytest.raises(ValueError, match="visual_route.*evidence row"):
        validate_script_evidence_closure(
            script, matrix, _facts(), input_mode="source_led_template"
        )


@pytest.mark.parametrize(
    "field,text,message",
    [
        ("narration", "吸水率 99%，瞬间全干。", "prohibited_wording"),
        ("screen_copy", "五星酒店同款", "allowed_wording"),
    ],
)
def test_source_led_script_rejects_unlicensed_copy(
    field: str, text: str, message: str
) -> None:
    script = _script()
    script["sections"][0][field] = text

    with pytest.raises(ValueError, match=message):
        validate_script_evidence_closure(
            script, _matrix(), _facts(), input_mode="source_led_template"
        )


def test_reference_driven_script_keeps_legacy_compatibility() -> None:
    legacy = _script()
    for field in ("claim_ids", "action_keys", "evidence_row_ids"):
        legacy["sections"][0].pop(field)

    validate_script_evidence_closure(
        legacy, {"matrix_mode": "reference", "rows": []}, _facts(),
        input_mode="reference_driven",
    )


def test_source_led_scene_and_mapping_equal_the_script_evidence_contract() -> None:
    plan = _scene_plan()

    validate_artifact("scene_plan", plan)
    validate_scene_evidence_closure(
        plan, _script(), _matrix(), input_mode="source_led_template"
    )


def _generated_scene_contract() -> tuple[dict, dict, dict]:
    generation_reference = {
        "asset_id": "page-asset-main-03-clean-v1",
        "parent_asset_id": "page-asset-main-03",
        "local_path": "assets/product_page/derived/main-03-clean-v1.png",
        "sha256": "d" * 64,
        "sku_scope": ["6276962282892"],
    }
    generation_spec = {
        "operation": "image_to_video",
        "required_actions": ["continuous_pour_water", "water_contacts_towel"],
        "required_results": ["visible_water_contact_result"],
        "evidence_role": "visual_expression_only",
    }
    matrix = _matrix()
    matrix["rows"][0].update({
        "visual_route": "generated_from_product_image",
        "generation_reference": deepcopy(generation_reference),
        "generation_spec": deepcopy(generation_spec),
    })
    for field in ("source_media_id", "source_hash", "source_time_range"):
        matrix["rows"][0].pop(field, None)

    script = _script()
    script["sections"][0].update({
        "visual_route": "generated_from_product_image",
        "generation_reference": deepcopy(generation_reference),
    })

    plan = _scene_plan()
    plan["scenes"][0].update({
        "visual_route": "generated_from_product_image",
        "generation_reference": deepcopy(generation_reference),
    })
    mapping = plan["metadata"]["source_mapping"][0]
    mapping.update({
        "visual_route": "generated_from_product_image",
        "generation_reference": deepcopy(generation_reference),
        "generation_spec": deepcopy(generation_spec),
    })
    for field in ("source_path", "source_hash", "source_interval"):
        mapping.pop(field, None)
    return plan, script, matrix


def test_source_led_scene_accepts_generated_route_without_owned_source_interval() -> None:
    plan, script, matrix = _generated_scene_contract()

    validate_artifact("scene_plan", plan)
    validate_scene_evidence_closure(
        plan, script, matrix, input_mode="source_led_template"
    )


@pytest.mark.parametrize("owner", ["scene", "mapping"])
def test_source_led_generated_scene_rejects_route_or_reference_drift(owner: str) -> None:
    plan, script, matrix = _generated_scene_contract()
    target = (
        plan["scenes"][0]
        if owner == "scene"
        else plan["metadata"]["source_mapping"][0]
    )
    target["generation_reference"] = {
        "asset_id": "page-asset-wrong",
        "sha256": "e" * 64,
    }

    with pytest.raises(ValueError, match="generation_reference.*evidence row"):
        validate_scene_evidence_closure(
            plan, script, matrix, input_mode="source_led_template"
        )


def test_source_led_generated_mapping_rejects_fabricated_owned_source_fields() -> None:
    plan, script, matrix = _generated_scene_contract()
    plan["metadata"]["source_mapping"][0]["source_interval"] = {
        "start_seconds": 0,
        "end_seconds_exclusive": 2,
    }

    with pytest.raises(ValueError, match="must not contain owned-source fields"):
        validate_scene_evidence_closure(
            plan, script, matrix, input_mode="source_led_template"
        )


@pytest.mark.parametrize("owner", ["scene", "mapping"])
def test_source_led_scene_rejects_evidence_drift(owner: str) -> None:
    plan = _scene_plan()
    target = (
        plan["scenes"][0]
        if owner == "scene"
        else plan["metadata"]["source_mapping"][0]
    )
    target["claim_ids"] = ["soft-touch"]

    with pytest.raises(ValueError, match="claim_ids.*script section"):
        validate_scene_evidence_closure(
            plan, _script(), _matrix(), input_mode="source_led_template"
        )


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("product_fact_refs", ["product_facts.claims[1]"]),
        ("product_page_refs", []),
        ("page_asset_ids", []),
        ("page_evidence_ids", []),
    ],
)
def test_source_led_scene_rejects_product_fact_or_page_evidence_drift(
    field: str, replacement: list[str]
) -> None:
    plan = _scene_plan()
    plan["metadata"]["source_mapping"][0][field] = replacement

    with pytest.raises(ValueError, match=field):
        validate_scene_evidence_closure(
            plan, _script(), _matrix(), input_mode="source_led_template"
        )


def test_source_led_scene_rejects_source_interval_outside_evidence_row() -> None:
    plan = _scene_plan()
    plan["metadata"]["source_mapping"][0]["source_interval"] = {
        "start_seconds": 0,
        "end_seconds_exclusive": 2,
    }

    with pytest.raises(ValueError, match="approved evidence interval"):
        validate_scene_evidence_closure(
            plan, _script(), _matrix(), input_mode="source_led_template"
        )


def test_source_led_scene_rejects_scene_section_cross_binding() -> None:
    plan = _scene_plan()
    plan["metadata"]["source_mapping"][0]["script_section_id"] = "sec-999"

    with pytest.raises(ValueError, match="script_section_id"):
        validate_scene_evidence_closure(
            plan, _script(), _matrix(), input_mode="source_led_template"
        )


def test_source_led_scene_requires_primary_matrix_row_inside_evidence_rows() -> None:
    plan = _scene_plan()
    plan["metadata"]["source_mapping"][0]["matrix_row_id"] = "evidence-999"

    with pytest.raises(ValueError, match="matrix_row_id.*evidence_row_ids"):
        validate_scene_evidence_closure(
            plan, _script(), _matrix(), input_mode="source_led_template"
        )


def test_source_led_scene_requires_mapping_hash_to_equal_primary_row() -> None:
    plan = _scene_plan()
    plan["metadata"]["source_mapping"][0]["source_hash"] = "b" * 64

    with pytest.raises(ValueError, match="source_hash.*primary evidence row"):
        validate_scene_evidence_closure(
            plan, _script(), _matrix(), input_mode="source_led_template"
        )


def test_source_led_section_rejects_supplemental_evidence_without_its_own_scene() -> None:
    matrix = _matrix()
    matrix["rows"].append({
        "matrix_row_id": "evidence-002", "resolution": "accept",
        "source_media_id": "packaging-007", "source_hash": "b" * 64,
        "source_time_range": {"start_seconds": 8, "end_seconds_exclusive": 10},
        "claim_ids": ["material-label"], "action_keys": ["read_label"],
        "product_fact_refs": ["product_facts.claims[0]"],
        "allowed_wording": ["包装标识可见"], "prohibited_wording": [],
    })
    script = _script()
    plan = _scene_plan()
    for owner in (script["sections"][0], plan["scenes"][0], plan["metadata"]["source_mapping"][0]):
        owner["claim_ids"].append("material-label")
        owner["action_keys"].append("read_label")
        owner["evidence_row_ids"].append("evidence-002")

    with pytest.raises(ValueError, match="exactly one evidence_row_id"):
        validate_script_evidence_closure(
            script, matrix, _facts(), input_mode="source_led_template"
        )


def test_template_mainline_source_led_script_is_derived_from_matrix_wording(
    tmp_path,
) -> None:
    from lib.template_mainline import build_script

    project = tmp_path / "source-led-run"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(
        '{"input_mode":"source_led_template"}', encoding="utf-8"
    )
    (project / "artifacts" / "reference_source_matrix.json").write_text(
        __import__("json").dumps(_matrix(), ensure_ascii=False), encoding="utf-8"
    )
    plan = _scene_plan()
    template = {"template_id": "source-led-test", "slots": []}

    script = build_script(
        project, template, plan, {}, _facts(), approved=False
    )["data"]

    section = script["sections"][0]
    assert section["evidence_row_ids"] == ["evidence-001"]
    assert section["claim_ids"] == ["absorb-visible"]
    assert section["action_keys"] == ["pour_water", "absorb"]
    assert any(wording in section["narration"] for wording in _matrix()["rows"][0]["allowed_wording"])
    assert any(wording in section["screen_copy"] for wording in _matrix()["rows"][0]["allowed_wording"])


def test_shot_execution_plan_carries_evidence_and_content_hashes(tmp_path) -> None:
    from lib.template_assets import build_shot_execution_plan

    project = tmp_path / "source-led-run"
    plan = build_shot_execution_plan(
        project,
        {"template_id": "source-led-test", "slots": []},
        _scene_plan(),
        {},
        _script(),
    )
    shot = plan["shots"][0]

    assert shot["claim_ids"] == ["absorb-visible"]
    assert shot["action_keys"] == ["pour_water", "absorb"]
    assert shot["evidence_row_ids"] == ["evidence-001"]
    assert shot["source_hash"] == HASH
    assert shot["source_interval"] == {
        "start_seconds": 1.2,
        "end_seconds_exclusive": 3.2,
    }
    for field in ("narration_hash", "screen_copy_hash", "caption_timeline_hash"):
        assert len(shot[field]) == 64
    assert shot["tts_asset_hash"] is None
    assert shot["tts_measured_duration"] is None
    validate_artifact("shot_execution_plan", plan)


def test_source_led_script_checkpoint_fails_closed_on_missing_evidence(
    tmp_path,
) -> None:
    import json

    from lib.artifact_io import write_artifact_atomic
    from lib.checkpoint import CheckpointValidationError, init_project, validate_checkpoint
    from lib.source_semantics import build_source_research_artifacts

    project = init_project(
        "script-gate", title="Script gate", pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path, input_mode="source_led", external_reference=False,
    )
    facts = _facts()
    facts_env = write_artifact_atomic(
        "artifacts/product_facts.json", "product_facts", facts, project_dir=project
    )
    research = build_source_research_artifacts(
        project_id="script-gate", input_mode="source_led",
        observations=[{
            "media_id": "towel-023", "source_path": "inputs/source/towel-023.mp4",
            "source_hash": HASH,
            "interval": {"start_seconds": 1.2, "end_seconds_exclusive": 4.8},
            "observed_subject": ["毛巾"], "observed_actions": ["pour_water", "absorb"],
            "observed_results": ["水面减少"],
            "crop_safety": {"subject_complete_in_3_4": True, "safe_caption_regions": ["top"]},
            "quality": {"usable": True, "confidence": 0.9, "risks": []},
            "representative_frames": ["analysis/frame.jpg"],
            "claim_bindings": [{
                "claim_id": "absorb-visible", "product_fact_ref": "product_facts.claims[0]",
                "allowed_wording": ["可见吸水过程", "水分快速被带走"],
                "prohibited_wording": ["吸水率 99%"], "evidence_strength": "strong",
            }],
        }],
        product_facts=facts_env["data"], created_at="2026-09-03T00:00:00Z",
    )
    matrix_env = write_artifact_atomic(
        "artifacts/reference_source_matrix.json", "reference_source_matrix",
        research["reference_source_matrix"], project_dir=project,
    )
    (project / "checkpoint_research.json").write_text(
        json.dumps({"artifacts": {"reference_source_matrix": matrix_env}}),
        encoding="utf-8",
    )
    invalid = _script()
    invalid.update(status="approved", approval={
        "approved_by": "operator", "approved_at": "2026-09-03T00:00:00Z",
    })
    invalid["sections"][0].pop("evidence_row_ids")
    script_env = write_artifact_atomic(
        "artifacts/script.json", "script", invalid, project_dir=project
    )
    checkpoint = {
        "version": "1.0", "project_id": "script-gate",
        "pipeline_type": "cinematic-fast", "input_mode": "source_led",
        "stage": "script", "status": "completed",
        "timestamp": "2026-09-03T00:00:00Z",
        "human_approval_required": True, "human_approved": True,
        "artifacts": {"script": script_env},
    }

    with pytest.raises(CheckpointValidationError, match="evidence_row_ids"):
        validate_checkpoint(checkpoint, project_dir=project)


def test_source_led_script_awaiting_human_fails_before_review_on_missing_evidence(
    tmp_path,
) -> None:
    # Reuse the completed-checkpoint fixture path, but prove the pre-review
    # state is guarded too. The helper test above would otherwise be the only
    # place the closure runs.
    import json
    from lib.artifact_io import write_artifact_atomic
    from lib.checkpoint import CheckpointValidationError, init_project, validate_checkpoint
    from lib.source_semantics import build_source_research_artifacts

    project = init_project(
        "script-review-gate", title="Script review gate",
        pipeline_type="cinematic-fast", pipeline_dir=tmp_path,
        input_mode="source_led", external_reference=False,
    )
    facts_env = write_artifact_atomic(
        "artifacts/product_facts.json", "product_facts", _facts(), project_dir=project
    )
    research = build_source_research_artifacts(
        project_id="script-review-gate", input_mode="source_led",
        observations=[{
            "media_id": "towel-023", "source_path": "inputs/source/towel-023.mp4",
            "source_hash": HASH,
            "interval": {"start_seconds": 1.2, "end_seconds_exclusive": 4.8},
            "observed_subject": ["毛巾"], "observed_actions": ["pour_water", "absorb"],
            "observed_results": ["水面减少"],
            "crop_safety": {"subject_complete_in_3_4": True, "safe_caption_regions": ["top"]},
            "quality": {"usable": True, "confidence": 0.9, "risks": []},
            "representative_frames": ["analysis/frame.jpg"],
            "claim_bindings": [{
                "claim_id": "absorb-visible", "product_fact_ref": "product_facts.claims[0]",
                "allowed_wording": ["可见吸水过程"], "prohibited_wording": ["吸水率 99%"],
                "evidence_strength": "strong",
            }],
        }], product_facts=facts_env["data"], created_at="2026-09-03T00:00:00Z",
    )
    matrix_env = write_artifact_atomic(
        "artifacts/reference_source_matrix.json", "reference_source_matrix",
        research["reference_source_matrix"], project_dir=project,
    )
    (project / "checkpoint_research.json").write_text(
        json.dumps({"artifacts": {"reference_source_matrix": matrix_env}}), encoding="utf-8"
    )
    invalid = _script()
    invalid["sections"][0]["evidence_row_ids"] = [
        research["reference_source_matrix"]["rows"][0]["matrix_row_id"]
    ]
    invalid["sections"][0].pop("claim_ids")
    script_env = write_artifact_atomic(
        "artifacts/script.json", "script", invalid, project_dir=project
    )
    checkpoint = {
        "version": "1.0", "project_id": "script-review-gate",
        "pipeline_type": "cinematic-fast", "input_mode": "source_led",
        "stage": "script", "status": "awaiting_human",
        "timestamp": "2026-09-03T00:00:00Z",
        "human_approval_required": True, "human_approved": False,
        "next_action": {
            "summary": "review", "verb": "review", "context_refs": [],
            "set_at": "2026-09-03T00:00:00Z",
        },
        "artifacts": {"script": script_env},
    }
    with pytest.raises(CheckpointValidationError, match="claim_ids"):
        validate_checkpoint(checkpoint, project_dir=project)

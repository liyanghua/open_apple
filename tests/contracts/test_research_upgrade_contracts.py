from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from lib import research_profiles
from lib.research_profiles import load_analysis_profile, load_industry_prior
from schemas.artifacts import ARTIFACT_NAMES, load_schema, validate_artifact


ROOT = Path(__file__).resolve().parents[2]
HASH = "a" * 64


def common(name: str) -> dict:
    return {
        "version": "1.0",
        "project_id": "demo",
        "created_at": "2026-08-19T10:00:00Z",
        "producer": f"tests.{name}",
        "input_hashes": {"source": HASH},
        "semantic_sha256": HASH,
        "artifact_sha256": HASH,
    }


def valid_research_artifact(name: str) -> dict:
    value = common(name)
    if name == "research_breakdown":
        values = {
            "ordinal": 1,
            "shot_size": "近景",
            "camera_movement": "固定",
            "camera_angle": "俯拍",
            "interval": {"start_seconds": 0, "end_seconds_exclusive": 1.2},
            "visual_content": "刮擦产品",
            "dialogue": None,
            "overlay_text": "防刮",
            "effect_treatment": None,
            "analyst_note": None,
            "evidence_frames": ["analysis/reference/keyframes/frame-1.jpg"],
            "setting": "室内桌面",
            "audio_layers": ["music"],
            "music_profile": "中等能量",
        }
        value.update({
            "profile_ref": research_profiles.analysis_profile_ref("ecommerce-storyboard-cn", "1.0"),
            "reference_shots": [{
                "row_id": "reference-shot-1", "media_id": "reference-1",
                "interval": {"start_seconds": 0, "end_seconds_exclusive": 1.2},
                "values": values,
                "evidence_refs": ["analysis/reference/keyframes/frame-1.jpg"],
                "confidence_by_dimension": {
                    key: (0.92 if item is not None else 0.0)
                    for key, item in values.items()
                },
                "observation_source": "derived", "warnings": [],
            }],
            "source_segments": [],
            "coverage_summary": {"total": 1, "identified": 1, "needs_review": 0, "missing": 0},
            "quality_warnings": [],
        })
    elif name == "reference_source_matrix":
        value.update({
            "rows": [{
                "matrix_row_id": "matrix-1", "reference_scene_id": "reference-1",
                "reference_time_range": {"start_seconds": 0, "end_seconds_exclusive": 1.2},
                "reference_intent": "展示防刮证明", "source_media_id": "source-1",
                "source_time_range": {"start_seconds": 2, "end_seconds_exclusive": 4},
                "match_reason": "都有明确刮擦动作和结果", "confidence": 0.9,
                "evidence_frames": ["analysis/source/source-1/frame-1.jpg"],
                "unmatched_gap": None, "resolution": "accept",
            }],
            "unmatched_gaps": [],
        })
    elif name == "research_synthesis":
        value.update({
            "summary": "保留动作证明，改用自有餐桌场景收束。",
            "differentiation_directions": [{
                "direction_id": "direction-1", "title": "真实餐桌证明",
                "promise": "先让用户看到结果，再解释功能。",
                "keep_from_reference": ["动作与结果成对"],
                "change_for_project": ["使用自有餐桌场景"], "avoid": ["照搬参考字幕"],
                "industry_prior_refs": ["short-video.v1"], "matrix_row_refs": ["matrix-1"],
                "prerequisites": [], "tradeoffs": ["需要更清楚的收尾镜头"],
            }],
            "industry_prior_evaluations": [], "conflicts": [],
        })
    elif name == "research_scorecard":
        value.update({
            "score": 10, "max_score": 10, "status": "pass",
            "checks": [
                {"id": check_id, "label": check_id, "score": 2, "status": "pass", "message": "已确认"}
                for check_id in (
                    "input_coverage", "evidence_traceability", "source_matching",
                    "production_readiness", "execution_discipline",
                )
            ],
            "hard_failures": [], "warnings": [],
        })
    elif name == "research_annotations":
        value.update({
            "revision_id": "revision-1", "base_research_revision": HASH,
            "media_dispositions": {}, "logo_usage": {},
            "claim_boundaries": {}, "reference_methods": {},
            "direction_preferences": {}, "matrix_resolutions": {},
            "local_reanalysis_requests": [], "business_notes": {},
        })
    return value


def test_research_upgrade_schemas_are_registered_and_validate_minimal_fixtures() -> None:
    for name in ("research_breakdown", "reference_source_matrix", "research_synthesis", "research_scorecard", "research_annotations"):
        assert name in ARTIFACT_NAMES
        schema = load_schema(name)
        jsonschema.Draft202012Validator.check_schema(schema)
        validate_artifact(name, valid_research_artifact(name))


@pytest.mark.parametrize("name", ["research_breakdown", "reference_source_matrix"])
def test_research_upgrade_rejects_non_positive_time_ranges(name: str) -> None:
    value = valid_research_artifact(name)
    if name == "research_breakdown":
        value["reference_shots"][0]["interval"] = {"start_seconds": 2, "end_seconds_exclusive": 1}
    else:
        value["rows"][0]["source_time_range"] = {"start_seconds": 2, "end_seconds_exclusive": 1}
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact(name, value)


def test_research_completion_is_blocked_by_hard_failure() -> None:
    from lib.research_validation import validate_research_completion

    scorecard = valid_research_artifact("research_scorecard")
    scorecard.update(status="fail", hard_failures=["核心证明没有可信素材"])
    with pytest.raises(ValueError, match="核心证明没有可信素材"):
        validate_research_completion(scorecard)


def test_proposal_must_reference_research_directions_and_matrix_rows() -> None:
    from lib.research_validation import validate_proposal_research_handoff

    proposal = {"concept_options": [{
        "id": "concept-1", "research_direction_refs": ["direction-1"],
        "matrix_row_refs": ["matrix-1"], "fingerprint_rule_refs": ["proof-pair"],
    }]}
    validate_proposal_research_handoff(
        proposal,
        valid_research_artifact("research_synthesis"),
        valid_research_artifact("reference_source_matrix"),
    )
    proposal["concept_options"][0]["matrix_row_refs"] = ["unknown"]
    with pytest.raises(ValueError, match="unknown research matrix row"):
        validate_proposal_research_handoff(
            proposal,
            valid_research_artifact("research_synthesis"),
            valid_research_artifact("reference_source_matrix"),
        )


def test_analysis_profile_is_the_business_template_with_fourteen_columns() -> None:
    profile = load_analysis_profile("ecommerce-storyboard-cn", "1.0")
    assert profile["profile_id"] == "ecommerce-storyboard-cn"
    assert len(profile["dimensions"]) == 14
    assert [item["key"] for item in profile["dimensions"]] == [
        "ordinal", "shot_size", "camera_movement", "camera_angle", "interval",
        "visual_content", "dialogue", "overlay_text", "effect_treatment",
        "analyst_note", "evidence_frames", "setting", "audio_layers", "music_profile",
    ]


def test_analysis_profile_ref_is_content_addressed_and_projection_key_is_versioned() -> None:
    profile_ref = research_profiles.analysis_profile_ref("ecommerce-storyboard-cn", "1.0")
    assert profile_ref["sha256"] != HASH
    assert len(profile_ref["sha256"]) == 64
    baseline = research_profiles.research_projection_cache_key(
        {"video_analysis_brief": "1" * 64, "source_media_review": "2" * 64},
        profile_ref=profile_ref,
        projector_version="1",
        model_version="local-v1",
        prompt_version="1",
        taxonomy_version="1",
    )
    relocated = research_profiles.research_projection_cache_key(
        {"source_media_review": "2" * 64, "video_analysis_brief": "1" * 64},
        profile_ref=profile_ref,
        projector_version="1",
        model_version="local-v1",
        prompt_version="1",
        taxonomy_version="1",
    )
    upgraded = research_profiles.research_projection_cache_key(
        {"video_analysis_brief": "1" * 64, "source_media_review": "2" * 64},
        profile_ref=profile_ref,
        projector_version="2",
        model_version="local-v1",
        prompt_version="1",
        taxonomy_version="1",
    )
    assert baseline == relocated
    assert baseline != upgraded


def test_research_breakdown_requires_locked_profile_and_all_fourteen_dimensions() -> None:
    value = valid_research_artifact("research_breakdown")
    value["profile_ref"]["sha256"] = HASH
    with pytest.raises(jsonschema.ValidationError, match="profile_ref"):
        validate_artifact("research_breakdown", value)

    value = valid_research_artifact("research_breakdown")
    del value["reference_shots"][0]["values"]["camera_angle"]
    with pytest.raises(jsonschema.ValidationError, match="14 profile dimensions"):
        validate_artifact("research_breakdown", value)


def test_research_breakdown_requires_evidence_and_confidence_for_derived_ocr() -> None:
    value = valid_research_artifact("research_breakdown")
    value["reference_shots"][0]["evidence_refs"] = []
    with pytest.raises(jsonschema.ValidationError, match="derived observations require evidence"):
        validate_artifact("research_breakdown", value)

    value = valid_research_artifact("research_breakdown")
    del value["reference_shots"][0]["confidence_by_dimension"]["overlay_text"]
    with pytest.raises(jsonschema.ValidationError, match="confidence"):
        validate_artifact("research_breakdown", value)


def test_research_scorecard_is_fixed_to_five_checks_and_pass_threshold() -> None:
    from lib.research_validation import validate_research_completion

    value = valid_research_artifact("research_scorecard")
    value.update({
        "score": 10,
        "checks": [
            {"id": check_id, "label": check_id, "score": 2, "status": "pass", "message": "已确认"}
            for check_id in (
                "input_coverage", "evidence_traceability", "source_matching",
                "production_readiness", "execution_discipline",
            )
        ],
    })
    validate_artifact("research_scorecard", value)

    value["checks"] = value["checks"][:-1]
    with pytest.raises(jsonschema.ValidationError, match="five canonical checks"):
        validate_artifact("research_scorecard", value)

    value = valid_research_artifact("research_scorecard")
    value["score"] = 7
    value["checks"][0]["score"] = 0
    value["checks"][0]["status"] = "review"
    value["checks"][1]["score"] = 1
    value["checks"][1]["status"] = "review"
    with pytest.raises(ValueError, match="至少 8/10"):
        validate_research_completion(value)


def test_first_release_industry_rules_only_target_known_dimensions() -> None:
    profile = load_analysis_profile("ecommerce-storyboard-cn", "1.0")
    dimensions = {item["key"] for item in profile["dimensions"]}
    for prior_id in ("short-video", "ecommerce-proof"):
        prior = load_industry_prior(prior_id, "1.0")
        assert prior["rules"]
        for rule in prior["rules"]:
            assert set(rule["target_dimensions"]) <= dimensions
            assert rule["source"]
            assert rule["reviewer"]
            assert rule["expires_at"]


def test_reference_fingerprint_v2_requires_three_levels_and_consistency_contract() -> None:
    value = common("reference_fingerprint")
    value.update({
        "version": "2.0", "content_sha256": HASH, "analysis_depth": "deep",
        "analyzer_version": "2", "canonical_request": {"depth": "deep"},
        "output_digest": HASH, "abstract_structure": {},
        "shot_patterns": [{"shot_id": "reference-1", "evidence_refs": ["frame-1.jpg"]}],
        "beat_patterns": [{"beat_id": "proof", "mechanism": "动作与结果成对"}],
        "whole_video": {"beat_order": ["hook", "proof", "cta"], "pacing_curve": "fast-steady-close"},
        "continuity_contract": [{
            "anchor_id": "product-identity", "category": "subject_identity",
            "scope": "whole_video", "strength": "hard", "source": "owned_asset_fact",
            "evidence_refs": ["source-1"], "allowed_variation": "角度可变，产品型号不可变",
            "conflict_policy": "owned_fact_wins",
        }],
    })
    validate_artifact("reference_fingerprint", value)
    del value["continuity_contract"]
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("reference_fingerprint", value)


def test_cinematic_fast_requires_research_outputs_and_passes_them_downstream() -> None:
    from lib.pipeline_loader import load_pipeline

    stages = {stage["name"]: stage for stage in load_pipeline("cinematic-fast")["stages"]}
    expected = {
        "research_brief", "video_analysis_brief", "source_media_review", "media_index",
        "reference_fingerprint", "research_breakdown", "reference_source_matrix",
        "research_synthesis", "research_scorecard", "caption_style_fingerprint",
    }
    assert set(stages["research"]["produces"]) == expected
    assert {"research_brief", "research_synthesis", "research_scorecard"} <= set(stages["proposal"]["required_artifacts_in"])
    assert {"reference_source_matrix", "research_breakdown", "reference_fingerprint"} <= set(stages["scene_plan"]["required_artifacts_in"])


def test_research_adapter_records_direction_and_matrix_decisions_as_annotations() -> None:
    from backlot.operator_adapters import get_adapter

    adapter = get_adapter("research")
    changed = adapter.apply({}, [
        {"op": "set_direction_preference", "direction_id": "direction-1", "preference": "prefer", "rationale": "更符合产品素材"},
        {"op": "resolve_matrix_row", "matrix_row_id": "matrix-1", "resolution": "bridge", "source_media_id": "source-2", "note": "补一段擦拭结果"},
        {"op": "request_local_reanalysis", "target_type": "shot", "target_id": "reference-1", "dimensions": ["dialogue", "overlay_text"], "reason": "字幕看不清"},
    ])
    annotations = changed["research_annotations"]
    assert annotations["direction_preferences"]["direction-1"]["preference"] == "prefer"
    assert annotations["matrix_resolutions"]["matrix-1"]["resolution"] == "bridge"
    assert annotations["local_reanalysis_requests"][0]["target_id"] == "reference-1"


def test_research_editor_exposes_user_facing_sections_when_new_artifacts_exist() -> None:
    from backlot.operator_state import _research_editor

    board = {
        "project_id": "demo",
        "artifacts": {
            "research_breakdown": valid_research_artifact("research_breakdown"),
            "reference_source_matrix": valid_research_artifact("reference_source_matrix"),
            "research_synthesis": valid_research_artifact("research_synthesis"),
            "research_scorecard": valid_research_artifact("research_scorecard"),
        },
    }
    data = _research_editor(board)["data"]
    assert data["template"]["label"] == "电商产品证明分镜模板"
    assert data["breakdown"]["label"] == "分镜拆解"
    assert data["matching"]["rows"][0]["label"] == "参考镜头 × 我的素材"
    assert data["directions"][0]["title"] == "真实餐桌证明"
    assert data["quality"]["label"] == "研究检查结果"


def test_research_editor_marks_legacy_fingerprint_as_needing_upgrade() -> None:
    from backlot.operator_state import _research_editor

    board = {
        "project_id": "demo",
        "artifacts": {
            "video_analysis_brief": {"source": {"local_path": "projects/demo/reference.mp4"}},
            "reference_fingerprint": {"version": "1.0"},
        },
    }
    reference = _research_editor(board)["data"]["reference"]
    assert reference["fingerprint_upgrade_notice"]


def test_research_workspace_uses_production_language_and_supports_decisions() -> None:
    app = (ROOT / "backlot/ui/operator/app.js").read_text(encoding="utf-8")
    for label in (
        "本次拆解模板", "分镜拆解", "参考镜头 × 我的素材", "可选方向",
        "研究检查结果", "采用这段", "换一段", "需要补拍或补素材",
        "改成别的表达", "删除这一镜", "重新看这一段",
    ):
        assert label in app
    for operation in (
        "set_direction_preference", "resolve_matrix_row", "request_local_reanalysis",
    ):
        assert operation in app
    for label in ("机位", "运镜", "特效", "场景", "声音", "BGM", "画面参考"):
        assert label in app


def test_research_heartbeat_accepts_source_matching_progress(tmp_path: Path) -> None:
    from lib.events import emit_heartbeat, read_events

    emit_heartbeat(
        tmp_path,
        run_id="research-000001",
        stage="research",
        operation="semantic_synthesis",
        unit={"kind": "source_match", "current": 3, "total": 7},
        wait_reason="orchestrating",
        message="正在建立参考镜头到自有素材的匹配证据",
        attempt=1,
    )

    events = read_events(tmp_path)
    assert events[0]["unit"] == {"kind": "source_match", "current": 3, "total": 7}


def test_research_director_requires_orchestration_events_and_terminal_timing() -> None:
    director = (
        ROOT / "skills" / "pipelines" / "cinematic-fast" / "research-director.md"
    ).read_text(encoding="utf-8")

    assert "emit_run_event" in director
    assert "emit_heartbeat" in director
    assert "semantic_synthesis" in director
    assert "machine_ms" in director
    assert "approval_wait_ms" in director


def test_research_director_requires_one_atomic_transaction_for_artifacts_frames_and_checkpoint() -> None:
    director = (
        ROOT / "skills" / "pipelines" / "cinematic-fast" / "research-director.md"
    ).read_text(encoding="utf-8")

    assert "ProjectCommitStore.transaction" in director
    assert "stage_bytes" in director
    assert "all 9 immutable Research artifacts" in director
    assert "checkpoint_research.json" in director

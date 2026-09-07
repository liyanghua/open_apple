from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import jsonschema

from lib.template_alignment import (
    adapt_legacy_alignment_report,
    alignment_checkpoint_gate,
    alignment_report_semantic_checks,
    apply_alignment_to_evaluation,
    build_semantic_alignment,
    route_human_review_channel,
)
from lib.template_assets import _content_hash
from lib.template_render import build_final_props
from schemas.artifacts import validate_artifact


def _artifacts() -> dict:
    script = {
        "semantic_sha256": "1" * 64,
        "sections": [{
            "id": "sec-001", "scene_id": "scene-001",
            "narration": "看水分被带走", "screen_copy": "可见吸水",
            "claim_ids": ["absorb-visible"], "action_keys": ["pour_water", "absorb"],
            "evidence_row_ids": ["evidence-001"], "start_seconds": 0, "end_seconds": 2,
        }],
    }
    scene_plan = {
        "semantic_sha256": "2" * 64,
        "scenes": [{
            "id": "scene-001", "script_section_id": "sec-001",
            "claim_ids": ["absorb-visible"], "action_keys": ["pour_water", "absorb"],
            "evidence_row_ids": ["evidence-001"],
        }],
        "metadata": {"source_mapping": [{
            "scene_id": "scene-001", "script_section_id": "sec-001",
            "claim_ids": ["absorb-visible"], "action_keys": ["pour_water", "absorb"],
            "evidence_row_ids": ["evidence-001"], "source_hash": "a" * 64,
            "source_interval": {"start_seconds": 1, "end_seconds_exclusive": 3},
        }]},
    }
    shot_plan = {
        "semantic_sha256": "3" * 64,
        "shots": [{
            "id": "shot-001", "scene_id": "scene-001", "section_id": "sec-001",
            "duration_seconds": 2.0, "product_id": "towel",
            "claim_ids": ["absorb-visible"], "action_keys": ["pour_water", "absorb"],
            "evidence_row_ids": ["evidence-001"], "source_hash": "a" * 64,
            "source_interval": {"start_seconds": 1, "end_seconds_exclusive": 3},
            "narration": "看水分被带走", "screen_copy": "可见吸水",
            "narration_hash": _content_hash({"section_id": "sec-001", "text": "看水分被带走"}),
            "screen_copy_hash": _content_hash({"section_id": "sec-001", "text": "可见吸水"}),
            "caption_timeline_hash": _content_hash({"section_id": "sec-001", "screen_copy": "可见吸水", "start_seconds": 0, "end_seconds": 2}),
            "tts_asset_hash": None, "tts_measured_duration": None,
        }],
    }
    return {
        "input_mode": "source_led",
        "product_facts": {"product_name": "towel"},
        "script": script, "scene_plan": scene_plan, "shot_execution_plan": shot_plan,
        "final_props": {"semantic_sha256": "4" * 64, "shots": [{
            "id": "shot-001", "product_id": "towel", "action_keys": ["pour_water", "absorb"],
            "screen_copy": "可见吸水", "start_seconds": 0, "end_seconds": 2,
        }]},
        "render": {"sha256": "5" * 64},
        "sample_execution_trace": {"shots": [{"shot_id": "shot-001", "sample_window": {"included": True}}]},
    }


def _generated_artifacts() -> dict:
    artifacts = _artifacts()
    reference = {
        "asset_id": "clean-ref-1", "parent_asset_id": "page-main-1",
        "local_path": "assets/product_page/derived/clean.png",
        "sha256": "6" * 64, "sku_scope": ["towel"],
    }
    requirement = {
        "required_subjects": ["target_product"],
        "required_actions": ["pour_water"],
        "required_results": ["visible_water_contact_result"],
    }
    section = artifacts["script"]["sections"][0]
    scene = artifacts["scene_plan"]["scenes"][0]
    mapping = artifacts["scene_plan"]["metadata"]["source_mapping"][0]
    shot = artifacts["shot_execution_plan"]["shots"][0]
    for owner in (section, scene, mapping, shot):
        owner.update({
            "visual_route": "generated_from_product_image",
            "claim_visual_requirements": requirement,
            "generation_reference": reference,
        })
    mapping.pop("source_hash", None); mapping.pop("source_interval", None)
    shot.pop("source_hash", None); shot.pop("source_interval", None)
    shot.update({"evidence_role": "visual_expression_only", "evidence_type": "demonstration"})
    artifacts["final_props"]["shots"][0].update({
        "visual_route": "generated_from_product_image",
        "reference_hash": reference["sha256"],
    })
    return artifacts


def _generated_check(**overrides) -> dict:
    check = {
        "shot_id": "shot-001", "action_match": "pass", "result_support": "pass",
        "narration_caption_match": "pass", "product_identity_match": "pass",
        "crop_completeness": "pass", "generated_text_integrity": "pass",
        "voice_caption_timing_match": "pass",
    }
    check.update(overrides)
    return check


def test_source_led_alignment_binds_all_hashes_and_passes() -> None:
    report = build_semantic_alignment(
        _artifacts(), scope="sample", expected_product_id="towel",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass",
                          "result_support": "pass", "narration_caption_match": "pass",
                          "product_identity_match": "pass", "crop_completeness": "pass"}],
    )
    assert report["status"] == "pass"
    assert report["input_hashes"] == {
        "script": "1" * 64, "scene_plan": "2" * 64,
        "shot_execution_plan": "3" * 64, "final_props": "4" * 64,
        "render": "5" * 64,
    }


def test_generated_alignment_requires_reference_identity_text_timing_and_crop() -> None:
    passed = build_semantic_alignment(
        _generated_artifacts(), scope="sample",
        semantic_checks=[_generated_check()],
    )
    row = passed["per_shot_results"][0]
    assert passed["status"] == "pass"
    assert row["reference_hash_match"] == "pass"
    assert row["generated_text_integrity"] == "pass"
    assert row["voice_caption_timing_match"] == "pass"
    assert row["generated_media_role"] == "visual_expression_only"

    failed_artifacts = _generated_artifacts()
    failed_artifacts["final_props"]["shots"][0]["reference_hash"] = "7" * 64
    failed = build_semantic_alignment(
        failed_artifacts, scope="sample",
        semantic_checks=[_generated_check(
            generated_text_integrity="fail",
            voice_caption_timing_match="fail",
            product_identity_match="fail",
            crop_completeness="fail",
        )],
    )
    codes = set(failed["per_shot_results"][0]["reason_codes"])
    assert failed["status"] == "fail"
    assert {
        "generated_reference_hash_mismatch", "generated_text_or_logo_corruption",
        "voice_caption_timing_mismatch", "product_identity_mismatch", "crop_incomplete",
    } <= codes


def test_generated_media_cannot_be_promoted_to_real_proof() -> None:
    artifacts = _generated_artifacts()
    artifacts["shot_execution_plan"]["shots"][0]["evidence_type"] = "real_proof"

    report = build_semantic_alignment(
        artifacts, scope="sample", semantic_checks=[_generated_check()],
    )

    assert report["status"] == "fail"
    assert "generated_evidence_escalation" in report["per_shot_results"][0]["reason_codes"]


def test_real_canonical_final_props_builder_preserves_alignment_metadata(tmp_path) -> None:
    artifacts = _artifacts()
    props = build_final_props(tmp_path, artifacts["script"], artifacts["shot_execution_plan"]["shots"])
    scene = props["scenes"][0]
    assert scene["action_keys"] == ["pour_water", "absorb"]
    assert scene["claim_ids"] == ["absorb-visible"]
    assert scene["evidence_row_ids"] == ["evidence-001"]
    assert scene["product_id"] == "towel"

    artifacts["final_props"] = {**props, "semantic_sha256": "4" * 64}
    report = build_semantic_alignment(
        artifacts, scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass", "result_support": "pass",
                          "narration_caption_match": "pass", "product_identity_match": "pass",
                          "crop_completeness": "pass"}],
    )
    assert report["status"] == "pass"


def test_alignment_integrates_lineage_errors_and_missing_actual_shots() -> None:
    artifacts = _artifacts()
    artifacts["shot_execution_plan"]["shots"][0]["narration"] = "漂移口播"
    artifacts["final_props"]["shots"] = []
    report = build_semantic_alignment(artifacts, scope="sample", semantic_checks=[])
    codes = set(report["per_shot_results"][0]["reason_codes"])
    assert report["status"] == "fail"
    assert {"lineage_drift", "actual_shot_missing"} <= codes


def test_result_and_crop_failures_fail_closed() -> None:
    report = build_semantic_alignment(
        _artifacts(), scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass",
                          "result_support": "fail", "narration_caption_match": "pass",
                          "crop_completeness": "fail"}],
    )
    assert report["status"] == "fail"
    assert {"result_unsupported", "crop_incomplete"} <= set(report["per_shot_results"][0]["reason_codes"])


def test_product_identity_comes_from_canonical_facts_not_actual_props() -> None:
    artifacts = _artifacts()
    artifacts["product_facts"] = {"product_name": "silver-towel"}
    artifacts["final_props"]["shots"][0]["product_id"] = "other-towel"
    report = build_semantic_alignment(
        artifacts, scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass",
                          "result_support": "pass", "narration_caption_match": "pass",
                          "product_identity_match": "pass", "crop_completeness": "pass"}],
    )
    assert report["status"] == "fail"
    assert "product_identity_mismatch" in report["per_shot_results"][0]["reason_codes"]


def test_source_led_product_proof_fails_when_canonical_identity_is_missing() -> None:
    artifacts = _artifacts()
    artifacts.pop("product_facts")
    report = build_semantic_alignment(
        artifacts, scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass", "result_support": "pass",
                          "narration_caption_match": "pass", "product_identity_match": "pass",
                          "crop_completeness": "pass"}],
    )
    assert report["status"] == "fail"
    assert "product_identity_unverified" in report["per_shot_results"][0]["reason_codes"]


def test_partial_crop_creates_revise_repair_target() -> None:
    report = build_semantic_alignment(
        _artifacts(), scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass", "result_support": "pass",
                          "narration_caption_match": "pass", "product_identity_match": "pass",
                          "crop_completeness": "partial"}],
    )
    assert report["status"] == "revise"
    assert report["repair_targets"] == [{"shot_id": "shot-001", "reason_codes": ["crop_incomplete"]}]


def test_source_led_alignment_fails_closed_on_missing_action_identity_and_caption_conflict() -> None:
    artifacts = _artifacts()
    artifacts["final_props"]["shots"][0]["action_keys"] = ["fold"]
    report = build_semantic_alignment(
        artifacts, scope="sample", expected_product_id="other-product",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass",
                          "result_support": "pass", "narration_caption_match": "pass",
                          "caption_conflict": True, "crop_completeness": "pass"}],
    )
    assert report["status"] == "fail"
    assert {item["status"] for item in report["per_shot_results"]} == {"fail"}
    reason_codes = {
        code
        for item in report["per_shot_results"]
        for code in item["reason_codes"]
    }
    assert reason_codes >= {"action_missing", "product_identity_mismatch", "caption_conflict"}


def test_source_led_alignment_fails_when_actual_shot_omits_action_keys() -> None:
    artifacts = _artifacts()
    artifacts["final_props"]["shots"][0].pop("action_keys")

    report = build_semantic_alignment(
        artifacts, scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass",
                          "result_support": "pass", "narration_caption_match": "pass",
                          "product_identity_match": "pass", "crop_completeness": "pass"}],
    )

    assert report["status"] == "fail"
    assert "action_missing" in report["per_shot_results"][0]["reason_codes"]


def test_source_led_alignment_accepts_valid_real_tts_binding(tmp_path: Path) -> None:
    artifacts = _artifacts()
    audio_dir = tmp_path / "assets" / "audio"
    audio_dir.mkdir(parents=True)
    audio = audio_dir / "narration-s001.mp3"
    audio.write_bytes(b"bound narration audio")
    narration = artifacts["script"]["sections"][0]["narration"]
    artifacts["shot_execution_plan"]["shots"][0].update({
        "tts_asset_hash": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "tts_measured_duration": 1.25,
    })
    (audio_dir / "narration-s001.mp3.lock.json").write_text(
        json.dumps({"text_sha": hashlib.sha256(narration.encode("utf-8")).hexdigest()}),
        encoding="utf-8",
    )
    (audio_dir / "narration-s001.mp3.json").write_text(
        json.dumps({"data": {"sentences": [{"endTime": 1250}]}}),
        encoding="utf-8",
    )

    report = build_semantic_alignment(
        artifacts, scope="sample", audio_dir=audio_dir,
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass",
                          "result_support": "pass", "narration_caption_match": "pass",
                          "product_identity_match": "pass", "crop_completeness": "pass"}],
    )

    assert report["status"] == "pass"


def test_failed_alignment_becomes_a_fatal_evaluation_gate() -> None:
    evaluation = {
        "hard_gate": {"pass": True, "checks": []},
        "repair_targets": [], "status": "pass", "recommended_action": "proceed",
    }
    alignment = {"status": "fail", "repair_targets": [{"shot_id": "shot-001", "reason_codes": ["action_missing"]}]}

    merged = apply_alignment_to_evaluation(evaluation, alignment)

    assert merged["status"] == "fail"
    assert merged["recommended_action"] == "reject"
    assert merged["hard_gate"]["pass"] is False
    assert merged["hard_gate"]["checks"][-1]["id"] == "semantic_alignment"
    assert merged["hard_gate"]["checks"][-1]["severity"] == "fatal"


def test_revise_alignment_merges_repair_targets_into_evaluation() -> None:
    evaluation = {"hard_gate": {"pass": True, "checks": []}, "repair_targets": [], "status": "pass", "recommended_action": "proceed"}
    alignment = {"status": "revise", "repair_targets": [{"shot_id": "shot-001", "reason_codes": ["crop_incomplete"]}]}
    merged = apply_alignment_to_evaluation(evaluation, alignment)
    assert merged["status"] == "revise"
    assert merged["repair_targets"][0]["check_id"] == "semantic_alignment"
    assert merged["repair_targets"][0]["affected_shots"] == ["shot-001"]


def test_source_led_checkpoint_gate_requires_passing_alignment() -> None:
    current = {"script": "1" * 64, "scene_plan": "2" * 64, "shot_execution_plan": "3" * 64,
               "final_props": "4" * 64, "render": "5" * 64}
    passing = {
        "contract_version": "1.0", "scope": "sample", "status": "pass",
        "input_hashes": current,
        "per_shot_results": [{
            "scene_id": "scene-001", "shot_id": "shot-001",
            "action_match": "pass", "result_support": "pass",
            "narration_caption_match": "pass", "crop_completeness": "pass",
            "product_identity_match": "pass", "status": "pass", "reason_codes": [],
        }],
        "repair_targets": [],
    }
    for stage in ("compose", "publish"):
        for evaluation in (None, {"alignment": {"status": "revise"}}, {"alignment": {"status": "fail"}}):
            assert alignment_checkpoint_gate(evaluation, input_mode="source_led", stage=stage, current_hashes=current)
        expected_scope = "final"
        good = {"alignment": {**passing, "scope": expected_scope}}
        assert alignment_checkpoint_gate(good, input_mode="source_led", stage=stage, current_hashes=current) == []
        stale = {"alignment": {**passing, "scope": expected_scope,
                                "input_hashes": {**current, "render": "9" * 64}}}
        assert alignment_checkpoint_gate(stale, input_mode="source_led", stage=stage, current_hashes=current)
    # 样片门只有 pass 通过；revise 必须退回 edit/reopen，不能靠普通人审覆盖。
    assert alignment_checkpoint_gate(
        {"alignment": passing}, input_mode="source_led", stage="sample",
        current_hashes=current) == []
    sample_revise = {
        **passing,
        "status": "revise",
        "per_shot_results": [{
            "scene_id": "scene-001", "shot_id": "shot-001",
            "action_match": "revise", "result_support": "revise",
            "narration_caption_match": "pass", "crop_completeness": "pass",
            "product_identity_match": "pass", "status": "revise",
            "reason_codes": ["action_support_weak", "result_support_weak"],
        }],
        "repair_targets": [{"shot_id": "shot-001", "reason_codes": ["action_support_weak", "result_support_weak"]}],
    }
    assert alignment_checkpoint_gate(
        {"alignment": sample_revise}, input_mode="source_led", stage="sample",
        current_hashes=current)
    # 硬性冲突（产品身份）在样片门也拒绝
    hard = {
        **passing,
        "status": "fail",
        "per_shot_results": [{
            "scene_id": "scene-001", "shot_id": "shot-001",
            "action_match": "pass", "result_support": "pass",
            "narration_caption_match": "pass", "crop_completeness": "pass",
            "product_identity_match": "fail", "status": "fail",
            "reason_codes": ["product_identity_mismatch"],
        }],
        "repair_targets": [{"shot_id": "shot-001", "reason_codes": ["product_identity_mismatch"]}],
    }
    assert alignment_checkpoint_gate(
        {"alignment": hard}, input_mode="source_led", stage="sample",
        current_hashes=current)
    assert alignment_checkpoint_gate(None, input_mode="reference_driven", stage="sample") == []
    assert alignment_checkpoint_gate({"alignment": {"status": "fail"}}, input_mode="reference_driven", stage="sample") == []


def test_route_human_review_channel_preserves_known_semantic_failures() -> None:
    alignment = {
        "contract_version": "1.0", "scope": "sample", "status": "fail",
        "input_hashes": {},
        "per_shot_results": [
            {
                "scene_id": "scene-001", "shot_id": "shot-001",
                "action_match": "fail", "result_support": "fail",
                "narration_caption_match": "pass", "crop_completeness": "pass",
                "product_identity_match": "pass", "status": "fail",
                "reason_codes": ["action_missing", "result_unsupported"],
            },
            {
                "scene_id": "scene-002", "shot_id": "shot-002",
                "action_match": "pass", "result_support": "pass",
                "narration_caption_match": "pass", "crop_completeness": "pass",
                "product_identity_match": "fail", "status": "fail",
                "reason_codes": ["product_identity_mismatch"],
            },
        ],
        "repair_targets": [
            {"shot_id": "shot-001", "reason_codes": ["action_missing", "result_unsupported"]},
            {"shot_id": "shot-002", "reason_codes": ["product_identity_mismatch"]},
        ],
    }

    routed = route_human_review_channel(alignment)

    assert routed["status"] == "fail"  # shot-002 硬冲突 → 保持 fail
    shot_001 = next(item for item in routed["per_shot_results"] if item["shot_id"] == "shot-001")
    assert shot_001["status"] == "fail"
    assert shot_001["action_match"] == "fail"


def test_route_human_review_channel_cannot_make_known_failures_approvable() -> None:
    current = {"script": "1" * 64, "scene_plan": "2" * 64, "shot_execution_plan": "3" * 64,
               "final_props": "4" * 64, "render": "5" * 64}
    alignment = {
        "contract_version": "1.0", "scope": "sample", "status": "fail",
        "input_hashes": current,
        "per_shot_results": [{
            "scene_id": "scene-001", "shot_id": "shot-001",
            "action_match": "fail", "result_support": "fail",
            "narration_caption_match": "pass", "crop_completeness": "fail",
            "product_identity_match": "pass", "status": "fail",
            "reason_codes": ["action_missing", "result_unsupported", "crop_incomplete"],
        }],
        "repair_targets": [{"shot_id": "shot-001",
                            "reason_codes": ["action_missing", "result_unsupported", "crop_incomplete"]}],
    }
    routed = route_human_review_channel(alignment)
    assert routed["status"] == "fail"
    assert alignment_checkpoint_gate(
        {"alignment": routed}, input_mode="source_led", stage="sample",
        current_hashes=current)


def test_source_led_checkpoint_rejects_crafted_minimal_alignment_bypass() -> None:
    current = {"script": "1" * 64, "scene_plan": "2" * 64,
               "shot_execution_plan": "3" * 64, "final_props": "4" * 64,
               "render": "5" * 64}
    crafted = {"alignment": {
        "contract_version": "1.0", "status": "pass", "input_hashes": current,
    }}

    errors = alignment_checkpoint_gate(
        crafted, input_mode="source_led_template", stage="sample",
        current_hashes=current,
    )

    assert errors
    assert any("canonical" in error or "per_shot" in error for error in errors)


def test_checkpoint_validation_wires_source_led_alignment_gate(tmp_path, monkeypatch) -> None:
    import json
    from lib.checkpoint import CheckpointValidationError, _validate_artifacts_for_stage
    import lib.pipeline_loader as pipeline_loader

    (tmp_path / "project.json").write_text(json.dumps({"input_mode": "source_led"}), encoding="utf-8")
    monkeypatch.setattr(pipeline_loader, "load_pipeline_readonly", lambda _name: {"artifact_contract_version": 1})
    sample = {
        "version": "1.0", "project_id": "towel", "created_at": "2026-09-04T00:00:00Z",
        "producer": "test", "input_hashes": {}, "semantic_sha256": "1" * 64,
        "artifact_sha256": "2" * 64, "final_props_hash": "3" * 64,
        "render_plan_hash": "4" * 64, "window": {"startFrame": 0, "endFrameExclusive": 30, "scale": 0.5},
        "output_path": "renders/sample.mp4", "probe": {"width": 540, "height": 720, "fps": 30, "frame_count": 30},
        "qa": {}, "status": "pass",
    }
    with pytest.raises(CheckpointValidationError, match="alignment"):
        _validate_artifacts_for_stage("sample", "awaiting_human", {"sample_report": sample}, "cinematic-fast", tmp_path)


def test_sample_alignment_only_reviews_shots_in_sample_window() -> None:
    artifacts = _artifacts()
    first = artifacts["shot_execution_plan"]["shots"][0]
    second = dict(first, id="shot-002", scene_id="scene-002", section_id="sec-002")
    artifacts["shot_execution_plan"]["shots"].append(second)
    artifacts["script"]["sections"].append(dict(artifacts["script"]["sections"][0], id="sec-002", scene_id="scene-002"))
    artifacts["scene_plan"]["scenes"].append(dict(artifacts["scene_plan"]["scenes"][0], id="scene-002", script_section_id="sec-002"))
    artifacts["scene_plan"]["metadata"]["source_mapping"].append(dict(artifacts["scene_plan"]["metadata"]["source_mapping"][0], scene_id="scene-002", script_section_id="sec-002"))
    artifacts["sample_execution_trace"] = {"shots": [
        {"shot_id": "shot-001", "sample_window": {"included": True}},
        {"shot_id": "shot-002", "sample_window": {"included": False}},
    ]}
    report = build_semantic_alignment(
        artifacts, scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass", "result_support": "pass",
                          "narration_caption_match": "pass", "crop_completeness": "pass"}],
    )
    assert [item["shot_id"] for item in report["per_shot_results"]] == ["shot-001"]


def test_source_led_dimensions_and_exact_coverage_are_mandatory() -> None:
    artifacts = _artifacts()
    missing = build_semantic_alignment(artifacts, scope="sample", semantic_checks=[{"shot_id": "shot-001", "action_match": "pass"}])
    assert missing["status"] == "fail"
    assert "semantic_dimensions_missing" in missing["per_shot_results"][0]["reason_codes"]
    extra = build_semantic_alignment(
        artifacts, scope="sample", semantic_checks=[
            {"shot_id": "shot-001", "action_match": "pass", "result_support": "pass", "narration_caption_match": "pass", "product_identity_match": "pass", "crop_completeness": "pass"},
            {"shot_id": "shot-extra", "action_match": "pass", "result_support": "pass", "narration_caption_match": "pass", "product_identity_match": "pass", "crop_completeness": "pass"},
        ])
    assert extra["status"] == "fail"
    assert "semantic_coverage_mismatch" in extra["per_shot_results"][0]["reason_codes"]


def test_empty_selected_sample_is_fail_closed() -> None:
    artifacts = _artifacts()
    artifacts["sample_execution_trace"] = {"shots": [{"shot_id": "shot-001", "sample_window": {"included": False}}]}
    report = build_semantic_alignment(artifacts, scope="sample", semantic_checks=[])
    assert report["status"] == "fail"
    assert report["per_shot_results"]
    assert "sample_proof_missing" in report["per_shot_results"][0]["reason_codes"]


def test_custom_validator_rejects_dimension_status_contradiction() -> None:
    alignment = build_semantic_alignment(
        _artifacts(), scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass", "result_support": "pass", "narration_caption_match": "pass", "product_identity_match": "pass", "crop_completeness": "pass"}],
    )
    alignment["per_shot_results"][0]["action_match"] = "fail"
    with pytest.raises(jsonschema.ValidationError, match="per-shot status"):
        validate_artifact("evaluation_report", apply_alignment_to_evaluation({
            "version": "1.0", "project_id": "towel", "scope": "sample", "created_at": "2026-09-04T00:00:00Z",
            "judge_version": "test", "rubric_version": "test", "subject_ref": {"name": "sample", "path": "sample.mp4"},
            "subject_version": "1", "subject_hash": "5" * 64, "hard_gate": {"pass": True, "checks": []},
            "creative_advisory": {"scored": False, "dimensions": [], "summary": "none"}, "repair_targets": [],
            "status": "pass", "recommended_action": "proceed"}, alignment))


def test_legacy_adapter_does_not_fan_out_coarse_match() -> None:
    report = {"sample_sha256": "5" * 64, "script_sha256": "1" * 64,
              "checks": [{"section_id": "sec-001", "match": "yes"}]}
    checks = adapt_legacy_alignment_report(report, sample_sha256="5" * 64, script_sha256="1" * 64)
    assert checks == [{"section_id": "sec-001", "legacy_match": "yes"}]


def test_apply_alignment_is_idempotent() -> None:
    alignment = build_semantic_alignment(
        _artifacts(), scope="sample",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "partial", "result_support": "pass", "narration_caption_match": "pass", "product_identity_match": "pass", "crop_completeness": "pass"}],
    )
    base = {"hard_gate": {"pass": True, "checks": []}, "repair_targets": [], "status": "pass", "recommended_action": "proceed"}
    twice = apply_alignment_to_evaluation(apply_alignment_to_evaluation(base, alignment), alignment)
    assert [c["id"] for c in twice["hard_gate"]["checks"]].count("semantic_alignment") == 1
    assert [r["check_id"] for r in twice["repair_targets"]].count("semantic_alignment") == 1


def test_finish_sample_resolves_taobao_review_output_from_l1a(tmp_path) -> None:
    from scripts.finish_template_sample import _resolve_review_output

    target = tmp_path / "renders" / "sample-v1.mp4"
    target.parent.mkdir()
    target.write_bytes(b"video")
    resolved = _resolve_review_output(
        tmp_path,
        {"output_path": "renders/full.mp4", "profile": "social_vertical_3_4_1080p30"},
        {"subject_ref": {"path": "renders/sample-v1.mp4"}},
    )
    assert resolved == "renders/sample-v1.mp4"


def test_source_led_alignment_requires_semantic_review_for_proof_shots() -> None:
    report = build_semantic_alignment(_artifacts(), scope="sample", semantic_checks=[])
    assert report["status"] == "fail"
    assert "semantic_review_missing" in report["per_shot_results"][0]["reason_codes"]


def test_evaluation_schema_accepts_canonical_alignment() -> None:
    alignment = build_semantic_alignment(
        _artifacts(), scope="sample", expected_product_id="towel",
        semantic_checks=[{"shot_id": "shot-001", "action_match": "pass",
                          "result_support": "pass", "narration_caption_match": "pass",
                          "crop_completeness": "pass"}],
    )
    report = apply_alignment_to_evaluation({
        "version": "1.0", "project_id": "towel", "scope": "sample",
        "created_at": "2026-09-04T00:00:00Z", "judge_version": "test",
        "rubric_version": "l1a-v1.0", "subject_ref": {"name": "sample", "path": "renders/sample.mp4"},
        "subject_version": "1.0", "subject_hash": "5" * 64,
        "hard_gate": {"pass": True, "checks": [], "coverage": {"executed": 1, "total": 1, "minimum": 1, "sufficient": True}},
        "creative_advisory": {"scored": False, "dimensions": [], "summary": "not run"},
        "repair_targets": [], "status": "pass", "recommended_action": "proceed",
    }, alignment)
    validate_artifact("evaluation_report", report)


def test_stage51_dimensions_flow_into_canonical_alignment_and_missing_dimension_fails() -> None:
    from scripts.towel_batch_2026_09_02.stage51_verify_alignment import canonicalize_vlm_check

    raw = {
        "shot_id": "shot-001", "section_id": "sec-001",
        "action_match": "pass", "result_support": "pass",
        "narration_caption_match": "pass", "product_identity_match": "pass",
        "crop_completeness": "pass", "reason": "动作和商品均清晰",
    }
    check = canonicalize_vlm_check(
        raw, expected_shot_id="shot-001", expected_section_id="sec-001",
    )
    report = {
        "sample_sha256": "5" * 64, "script_sha256": "1" * 64,
        "checks": [check],
    }
    semantic_checks = alignment_report_semantic_checks(
        report, sample_sha256="5" * 64, script_sha256="1" * 64,
        input_mode="source_led_template",
    )
    passed = build_semantic_alignment(
        _artifacts(), scope="sample", semantic_checks=semantic_checks,
    )
    assert passed["status"] == "pass"

    report["checks"][0].pop("crop_completeness")
    incomplete = alignment_report_semantic_checks(
        report, sample_sha256="5" * 64, script_sha256="1" * 64,
        input_mode="source_led_template",
    )
    failed = build_semantic_alignment(
        _artifacts(), scope="sample", semantic_checks=incomplete,
    )
    assert failed["status"] == "fail"
    assert "semantic_dimensions_missing" in failed["per_shot_results"][0]["reason_codes"]


def test_stage51_rejects_invalid_dimension_enum() -> None:
    from scripts.towel_batch_2026_09_02.stage51_verify_alignment import canonicalize_vlm_check

    with pytest.raises(ValueError, match="action_match"):
        canonicalize_vlm_check({
            "shot_id": "shot-001", "section_id": "sec-001",
            "action_match": "yes", "result_support": "pass",
            "narration_caption_match": "pass", "product_identity_match": "pass",
            "crop_completeness": "pass", "reason": "ok",
        }, expected_shot_id="shot-001", expected_section_id="sec-001")

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import ValidationError

from lib.artifact_hashing import attach_hashes
from lib.campaign_contracts import (
    build_content_recipe_from_slot,
    create_campaign_plan,
    create_fact_snapshot,
    validate_campaign_bundle,
    validate_content_recipe_semantics,
    validate_production_record_semantics,
)
from lib.category_profile import (
    bundled_towel_profile_ref,
    load_category_profile_ref,
    load_legacy_towel_profile,
)
from schemas.artifacts import validate_artifact


def _mat_profile(project: Path) -> tuple[dict, dict]:
    profile = deepcopy(load_legacy_towel_profile())
    profile.update({
        "profile_id": "tablemat-v1",
        "category_id": "tablemat",
        "action_keys": ["wipe_mat"],
        "action_visible_results": {"wipe_mat": "擦拭前后桌垫表面状态可见"},
        "action_labels": {"wipe_mat": "擦拭桌垫"},
        "evidence_action_map": {"wipe_clip": "wipe_mat"},
        "evidence_requirements": {"wipe_clip": {
            "source_types": ["owned_video"], "visible_result": "擦拭前后变化可见",
            "sku_bound": True,
        }},
        "allowed_structures": ["P1"],
        "default_action": "wipe_mat",
        "direction_action_rules": {"test_selection": {"any_of": ["wipe_mat"]}},
        "forbidden_wording_defaults": [],
        "identity_checks": ["桌垫边缘与颜色一致"],
        "review_guidance": {
            "product_identity": "核对桌垫边缘与颜色。",
            "opening_motion": "检查擦拭动作是否完整。",
            "opening_preview_fact": "仅展示有证据的清洁效果。",
        },
    })
    profile = attach_hashes(profile)
    path = project / "artifacts/category_profile.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    ref = {
        "path": "artifacts/category_profile.json",
        "profile_id": profile["profile_id"],
        "category_id": profile["category_id"],
        "version": profile["version"],
        "artifact_sha256": profile["artifact_sha256"],
    }
    return profile, ref


def _mat_slot() -> dict:
    return {
        "content_slot_id": "mat-A01", "week": 1, "direction_id": "test_selection",
        "structure_id": "P1", "support_type": "experiment", "sku": "mat-1",
        "fact_snapshot_ref": "fact-mat", "recipe_id": "mat-r1", "status": "planned",
    }


def _mat_recipe(project: Path, ref: dict) -> dict:
    return build_content_recipe_from_slot({
        **_mat_slot(), "required_evidence": ["wipe_clip"],
        "changed_variable": "camera_angle",
    }, fact_snapshot_ref="fact-mat", version="1.1",
        category_profile_ref=ref, project_dir=project)


def _record(ref: dict) -> dict:
    return {
        "version": "1.1", "provenance": "canonical",
        "content_slot_id": "mat-A01", "sku": "mat-1",
        "run_id": "mat-run", "work_id": "mat-work",
        "campaign_role": "pilot", "production_route": "ai_assisted",
        "content_version_id": "mat-A01-v1", "fact_version": "fact-mat",
        "brand_version": "mat-brand-v1", "timing": {}, "costs": {},
        "quality_report_ref": "artifacts/quality_report.json",
        "canonical_artifacts": {},
        "render": {"path": "renders/final.mp4", "sha256": "a" * 64},
        "category_profile_ref": ref,
        "brand_profile_ref": {"path": "artifacts/brand_profile.json", "sha256": "b" * 64},
        "fact_snapshot_ref": {"path": "artifacts/fact_snapshot.json", "sha256": "c" * 64},
    }


def test_bundled_towel_profile_is_hash_pinned_and_legacy_readable():
    ref = bundled_towel_profile_ref()
    profile = load_category_profile_ref(Path.cwd(), ref)
    assert profile == load_legacy_towel_profile()
    assert profile["evidence_action_map"]["fold_storage"] == "fold_fall"
    assert profile["review_guidance"]["product_identity"]


def test_resolver_rejects_tampering_wrong_hash_and_unsafe_paths(tmp_path: Path):
    profile, ref = _mat_profile(tmp_path)
    assert load_category_profile_ref(tmp_path, ref) == profile
    with pytest.raises(ValueError, match="does not match"):
        load_category_profile_ref(tmp_path, {**ref, "artifact_sha256": "0" * 64})
    with pytest.raises(ValueError, match="safe relative"):
        load_category_profile_ref(tmp_path, {**ref, "path": "../outside.json"})

    path = tmp_path / ref["path"]
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["identity_checks"].append("changed after approval")
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity hashes"):
        load_category_profile_ref(tmp_path, ref)


def test_resolver_requires_complete_action_results_and_evidence_requirements(tmp_path: Path):
    profile, ref = _mat_profile(tmp_path)
    path = tmp_path / ref["path"]
    missing_action = deepcopy(profile)
    missing_action["action_keys"].append("edge_align")
    missing_action = attach_hashes(missing_action)
    path.write_text(json.dumps(missing_action), encoding="utf-8")
    with pytest.raises(ValueError, match="action_visible_results must cover"):
        load_category_profile_ref(tmp_path, {**ref, "artifact_sha256": missing_action["artifact_sha256"]})

    missing_evidence = deepcopy(profile)
    missing_evidence["evidence_action_map"]["edge_clip"] = "wipe_mat"
    missing_evidence = attach_hashes(missing_evidence)
    path.write_text(json.dumps(missing_evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence_requirements must cover"):
        load_category_profile_ref(tmp_path, {**ref, "artifact_sha256": missing_evidence["artifact_sha256"]})


def test_v11_campaign_recipe_and_record_bind_same_non_towel_profile(tmp_path: Path):
    _, ref = _mat_profile(tmp_path)
    recipe = _mat_recipe(tmp_path, ref)
    assert recipe["asset_slots"] == ["wipe_mat"]
    assert recipe["forbidden_wording"] == []
    validate_artifact("content_recipe", recipe, project_dir=tmp_path)
    plan = create_campaign_plan(
        "mat-campaign", slots=[_mat_slot()], target_count=1, pilot_count=1,
        version="1.1", category_profile_ref=ref, project_dir=tmp_path,
    )
    snapshot = create_fact_snapshot(
        product_id="mat-product", sku="mat-1", source_hash="page-hash",
        claims=[], snapshot_id="fact-mat",
    )
    admission = validate_campaign_bundle(
        plan, {"fact-mat": snapshot}, {"mat-r1": recipe}, project_dir=tmp_path,
    )
    assert admission["ready"] is True

    record = _record(ref)
    validate_production_record_semantics(
        record, project_dir=tmp_path, campaign_plan=plan, recipe=recipe,
    )
    with pytest.raises(ValueError, match="category_profile_ref does not match"):
        validate_production_record_semantics(
            {**record, "category_profile_ref": bundled_towel_profile_ref()},
            project_dir=tmp_path, campaign_plan=plan, recipe=recipe,
        )


def test_v11_rejects_cross_profile_recipe_and_towel_action(tmp_path: Path):
    _, ref = _mat_profile(tmp_path)
    plan = create_campaign_plan(
        "mat-campaign", slots=[_mat_slot()], target_count=1, pilot_count=1,
        version="1.1", category_profile_ref=ref, project_dir=tmp_path,
    )
    recipe = _mat_recipe(tmp_path, ref)
    bad_action = {**recipe, "asset_slots": ["touch_brush"]}
    with pytest.raises(ValueError, match="unknown asset action"):
        validate_content_recipe_semantics(bad_action, project_dir=tmp_path)

    snapshot = create_fact_snapshot(
        product_id="mat-product", sku="mat-1", source_hash="page-hash",
        claims=[], snapshot_id="fact-mat",
    )
    mismatched_recipe = {**recipe, "category_profile_ref": bundled_towel_profile_ref()}
    admission = validate_campaign_bundle(
        plan, {"fact-mat": snapshot}, {"mat-r1": mismatched_recipe},
        project_dir=tmp_path,
    )
    assert admission["ready"] is False
    assert any("category_profile_ref does not match" in item for item in admission["blockers"])


def test_v11_plan_and_recipe_reject_structures_outside_profile(tmp_path: Path):
    _, ref = _mat_profile(tmp_path)
    bad_slot = {**_mat_slot(), "direction_id": "relationship_story", "structure_id": "P3"}
    with pytest.raises(ValueError, match="not allowed by category profile"):
        create_campaign_plan(
            "mat-campaign", slots=[bad_slot], target_count=1, pilot_count=1,
            version="1.1", category_profile_ref=ref, project_dir=tmp_path,
        )
    recipe = _mat_recipe(tmp_path, ref)
    bad_recipe = {**recipe, "direction_id": "relationship_story",
                  "structure_id": "P3", "content_role": "life_context"}
    with pytest.raises(ValueError, match="not allowed by category profile"):
        validate_content_recipe_semantics(bad_recipe, project_dir=tmp_path)


def test_v11_unknown_evidence_and_unapproved_wording_fail_closed(tmp_path: Path):
    _, ref = _mat_profile(tmp_path)
    with pytest.raises(ValueError, match="unknown category evidence"):
        build_content_recipe_from_slot(
            {**_mat_slot(), "required_evidence": ["towel_weave"]},
            fact_snapshot_ref="fact-mat", version="1.1",
            category_profile_ref=ref, project_dir=tmp_path,
        )
    recipe = _mat_recipe(tmp_path, ref)
    with pytest.raises(ValueError, match="unknown category evidence"):
        validate_content_recipe_semantics(
            {**recipe, "evidence_ids": ["towel_weave"]}, project_dir=tmp_path,
        )
    plan = create_campaign_plan(
        "mat-campaign", slots=[_mat_slot()], target_count=1, pilot_count=1,
        version="1.1", category_profile_ref=ref, project_dir=tmp_path,
    )
    claim = {"claim_id": "size", "claim": "桌垫尺寸", "status": "authorized",
             "evidence_status": "page_claim", "allowed_wording": ["尺寸以商品页为准"],
             "forbidden_wording": [], "evidence_ids": ["wipe_clip"]}
    snapshot = create_fact_snapshot(
        product_id="mat-product", sku="mat-1", source_hash="page-hash",
        claims=[claim], snapshot_id="fact-mat", status="approved", approved_by="reviewer",
    )
    bad_recipe = {**recipe, "claim_ids": ["size"], "allowed_wording": ["保证永不磨损"]}
    admission = validate_campaign_bundle(
        plan, {"fact-mat": snapshot}, {"mat-r1": bad_recipe}, paid=True, project_dir=tmp_path,
    )
    assert not admission["ready"]
    assert any("wording not supported" in item for item in admission["blockers"])
    claim["status"] = "forbidden"
    claim["allowed_wording"] = []
    forbidden_snapshot = create_fact_snapshot(
        product_id="mat-product", sku="mat-1", source_hash="page-hash",
        claims=[claim], snapshot_id="fact-mat", status="approved", approved_by="reviewer",
    )
    admission = validate_campaign_bundle(
        plan, {"fact-mat": forbidden_snapshot}, {"mat-r1": {**recipe, "claim_ids": ["size"]}},
        paid=True, project_dir=tmp_path,
    )
    assert not admission["ready"]
    assert any("not authorized" in item for item in admission["blockers"])


def test_v11_schemas_require_category_and_record_fact_brand_refs(tmp_path: Path):
    _, ref = _mat_profile(tmp_path)
    plan = create_campaign_plan(
        "mat-campaign", slots=[_mat_slot()], target_count=1, pilot_count=1,
        version="1.1", category_profile_ref=ref, project_dir=tmp_path,
    )
    recipe = _mat_recipe(tmp_path, ref)
    for artifact_name, artifact in (("campaign_plan", plan), ("content_recipe", recipe)):
        without_ref = {key: value for key, value in artifact.items() if key != "category_profile_ref"}
        with pytest.raises(ValidationError):
            validate_artifact(artifact_name, without_ref, project_dir=tmp_path)
    record = _record(ref)
    validate_artifact("production_record", record)
    with pytest.raises(ValidationError):
        validate_artifact("production_record", {**record, "provenance": "legacy_import"})
    for field in ("category_profile_ref", "brand_profile_ref", "fact_snapshot_ref"):
        with pytest.raises(ValidationError):
            validate_artifact("production_record", {key: value for key, value in record.items() if key != field})

    legacy = {key: value for key, value in record.items()
              if key not in {"category_profile_ref", "brand_profile_ref", "fact_snapshot_ref"}}
    legacy["version"] = "1.0"
    validate_artifact("production_record", legacy)

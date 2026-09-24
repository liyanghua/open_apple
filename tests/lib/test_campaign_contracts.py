from __future__ import annotations

import pytest

from lib.campaign_contracts import (
    affected_content_versions,
    campaign_content_ref_blockers,
    create_campaign_plan,
    create_content_link,
    create_fact_snapshot,
    migrate_legacy_batch_plan,
    validate_content_recipe_semantics,
    validate_motion_task_semantics,
    validate_sample_shot_plan_semantics,
)
from lib.template_batch import create_template_batch
from lib.template_run_plan import create_template_run
from schemas.artifacts import validate_artifact


def _claim(claim_id: str = "P2-C01") -> dict:
    return {
        "claim_id": claim_id,
        "claim": "长绒棉材质",
        "status": "authorized",
        "evidence_status": "page_claim",
        "allowed_wording": ["长绒棉材质"],
        "forbidden_wording": [],
        "evidence_ids": ["P2-E01"],
    }


def _slot(slot_id: str = "P2-W1-A01") -> dict:
    return {
        "content_slot_id": slot_id,
        "week": 1,
        "direction_id": "test_selection",
        "structure_id": "P1",
        "support_type": "experiment",
        "sku": "yb-bb-12",
        "recipe_id": "P1-weave-v1",
        "content_version_id": None,
        "status": "planned",
    }


def test_campaign_plan_counts_pilot_inside_target():
    plan = create_campaign_plan("playboy-300", slots=[_slot()], target_count=300, pilot_count=60)
    assert plan["target_count"] == 300
    assert plan["pilot_count"] == 60
    assert plan["artifact_sha256"]
    validate_artifact("campaign_plan", plan)


def test_legacy_p1p2_batch_plan_maps_to_campaign_directions():
    plan = migrate_legacy_batch_plan({
        "campaign_id": "playboy-towel-p1p2-v1",
        "products": [{"fact_version": "P1_fact_v1"}, {"fact_version": "P2_fact_v1"}],
        "slots": [
            {"slot_id": "P1-A01", "product_key": "P1", "content_group": "A", "week": "W1"},
            {"slot_id": "P2-B01", "item_code": "yb-bb-12", "content_group": "B", "week": "W2"},
            {"slot_id": "P2-C01", "item_code": "yb-bb-12", "content_group": "C", "week": "W2"},
        ],
    })
    assert plan["target_count"] == 300
    assert plan["pilot_count"] == 60
    assert [slot["direction_id"] for slot in plan["slots"]] == [
        "test_selection", "healing_ritual", "comment_faq"
    ]
    assert plan["fact_snapshot_refs"] == ["P1_fact_v1", "P2_fact_v1"]


def test_campaign_plan_rejects_duplicate_slots():
    with pytest.raises(ValueError, match="unique"):
        create_campaign_plan("playboy-300", slots=[_slot(), _slot()], target_count=300)


def test_campaign_plan_rejects_wrong_structure_for_direction():
    bad = _slot()
    bad["structure_id"] = "P3"
    with pytest.raises(ValueError, match="not valid"):
        create_campaign_plan("playboy-300", slots=[bad])


def test_fact_snapshot_requires_approver_when_approved():
    with pytest.raises(ValueError, match="approved_by"):
        create_fact_snapshot(
            product_id="1072643655403",
            sku="yb-bb-12",
            source_hash="page-hash",
            claims=[_claim()],
            status="approved",
        )


def test_fact_snapshot_has_stable_claim_ids_and_hash():
    snapshot = create_fact_snapshot(
        product_id="1072643655403",
        sku="yb-bb-12",
        source_hash="page-hash",
        claims=[_claim()],
    )
    assert snapshot["snapshot_id"].startswith("fact-")
    assert snapshot["semantic_sha256"]
    validate_artifact("fact_snapshot", snapshot)


def test_recipe_does_not_allow_a_variable_to_be_fixed_and_variable():
    recipe = {
        "version": "1.0",
        "recipe_id": "r1",
        "sku": "yb-bb-12",
        "direction_id": "healing_ritual",
        "structure_id": "P2",
        "support_type": "experiment",
        "content_role": "life_context",
        "need_id": "D01",
        "fact_snapshot_ref": "fact-p2-v1",
        "claim_ids": [],
        "evidence_ids": ["E1"],
        "asset_slots": ["touch_brush"],
        "control_variables": {"fixed": ["sku"], "variable": ["sku"]},
    }
    with pytest.raises(ValueError, match="both fixed and variable"):
        validate_content_recipe_semantics(recipe)


def test_motion_task_failed_requires_classification():
    task = {
        "version": "1.0",
        "task_id": "motion-1",
        "content_version_id": "P2-W1-A01-v1",
        "asset_slot_id": "touch_brush",
        "reference_asset_id": "img-1",
        "fact_snapshot_id": "fact-p2-v1",
        "prompt_version": "v1",
        "provider": "seedance",
        "model": "seedance-2.5",
        "duration_seconds": 4,
        "width": 1080,
        "height": 1920,
        "aspect_ratio": "9:16",
        "status": "failed",
        "attempts": 1,
        "pool_status": "not_admitted",
        "failure_class": None,
    }
    with pytest.raises(ValueError, match="failure_class"):
        validate_motion_task_semantics(task)


def test_sample_shot_plan_enforces_three_to_five_second_motion_clips():
    plan = {
        "samples": [{
            "sample_id": "P2-S01",
            "motion_shots": [{"duration_seconds": 4}],
            "shots": [
                {"id": "s1", "timecode": "0-2"},
                {"id": "s2", "timecode": "2-5"},
            ],
        }]
    }
    validate_sample_shot_plan_semantics(plan)
    plan["samples"][0]["motion_shots"][0]["duration_seconds"] = 12
    with pytest.raises(ValueError, match="outside 3–5s"):
        validate_sample_shot_plan_semantics(plan)


def test_approved_motion_task_requires_scores():
    task = {
        "version": "1.0",
        "task_id": "motion-1",
        "content_version_id": "P2-W1-A01-v1",
        "asset_slot_id": "touch_brush",
        "reference_asset_id": "img-1",
        "fact_snapshot_id": "fact-p2-v1",
        "prompt_version": "v1",
        "provider": "seedance",
        "model": "seedance-2.5",
        "duration_seconds": 4,
        "width": 1080,
        "height": 1920,
        "aspect_ratio": "9:16",
        "status": "succeeded",
        "attempts": 1,
        "pool_status": "approved",
        "failure_class": None,
        "identity_score": None,
        "action_score": None,
    }
    with pytest.raises(ValueError, match="identity_score"):
        validate_motion_task_semantics(task)


def test_content_link_tracks_only_current_versions_for_snapshot_impact():
    link = create_content_link(
        campaign_id="playboy-300",
        content_slot_id="P2-W1-A01",
        content_version_id="P2-W1-A01-v1",
        direction_id="healing_ritual",
        structure_id="P2",
        support_type="experiment",
        recipe_id="r1",
        sku="yb-bb-12",
        fact_snapshot_ref="fact-p2-v1",
    )
    links = [link, {**link, "content_version_id": "old", "status": "superseded"}]
    assert affected_content_versions(links, changed_snapshot_ref="fact-p2-v1") == ["P2-W1-A01-v1"]


def test_template_batch_carries_campaign_ref_without_changing_legacy_runs():
    pack = {
        "version": "1.0",
        "artifact_sha256": "a" * 64,
        "templates": [{"template_id": "t1", "slots": []}],
    }
    batch = create_template_batch(
        pack,
        product_facts_ref={"artifact_sha256": "b" * 64},
        campaign_ref={
            "campaign_id": "playboy-300",
            "production_wave_id": "P2-W1",
            "plan_revision": 1,
            "fact_snapshot_id": "fact-p2-v1",
        },
    )
    validate_artifact("template_batch", batch)
    assert batch["campaign_ref"]["campaign_id"] == "playboy-300"


def test_template_run_carries_campaign_content_ref():
    run = create_template_run(
        {"template_id": "t1", "slots": []},
        template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"},
        product_facts_ref={"artifact_sha256": "b" * 64},
        campaign_content_ref={
            "campaign_id": "playboy-300",
            "content_slot_id": "P2-W1-A01",
            "content_version_id": "P2-W1-A01-v1",
            "direction_id": "healing_ritual",
            "structure_id": "P2",
            "support_type": "experiment",
            "recipe_id": "r1",
        },
    )
    validate_artifact("template_run_plan", run)
    assert run["campaign_content_ref"]["content_slot_id"] == "P2-W1-A01"


def test_campaign_run_ref_is_checked_before_paid_assets():
    run = {"campaign_content_ref": {
        "campaign_id": "playboy-300",
        "content_slot_id": "P2-W1-A01",
        "content_version_id": "P2-W1-A01-v1",
        "direction_id": "healing_ritual",
        "structure_id": "P3",
        "support_type": "experiment",
        "recipe_id": "r1",
    }}
    blockers = campaign_content_ref_blockers(run)
    assert blockers and "not valid" in blockers[0]


def test_relationship_recipe_requires_real_use_context_action():
    recipe = {
        "version": "1.0",
        "recipe_id": "r-relationship",
        "sku": "yb-bb-12",
        "direction_id": "relationship_story",
        "structure_id": "P3",
        "support_type": "experiment",
        "content_role": "life_context",
        "need_id": "D03",
        "fact_snapshot_ref": "fact-p2-v1",
        "claim_ids": [],
        "evidence_ids": ["E1"],
        "asset_slots": ["product_full_view"],
        "control_variables": {"fixed": ["sku"], "variable": ["opening"]},
    }
    with pytest.raises(ValueError, match="use_context"):
        validate_content_recipe_semantics(recipe)


def test_transaction_recipe_requires_cta_and_product_identity_action():
    recipe = {
        "version": "1.0",
        "recipe_id": "r-transaction",
        "sku": "yb-bb-12",
        "direction_id": "transaction",
        "structure_id": "P6",
        "support_type": "transaction",
        "content_role": "product_evidence",
        "need_id": "D10",
        "fact_snapshot_ref": "fact-p2-v1",
        "claim_ids": ["P2-C01"],
        "evidence_ids": ["E1"],
        "asset_slots": ["weave_macro"],
        "control_variables": {"fixed": ["sku"], "variable": ["opening"]},
        "cta": None,
    }
    with pytest.raises(ValueError, match="CTA"):
        validate_content_recipe_semantics(recipe)

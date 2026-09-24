"""Original campaign projections never manufacture production or approval evidence."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest

from lib.campaign_panorama import build_campaign_panorama, normalize_original_campaign_plan, summarize_path_costs
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def plan():
    raw = json.loads((ROOT / "花花公子毛巾_300条_V2/300条周度实验排期.json").read_text())
    return normalize_original_campaign_plan(raw, campaign_id="towel-original-300")


def record(slot="W1-001", run="run-1", media="a" * 64, work="work-1"):
    return {"content_slot_id": slot, "run_id": run, "content_version_id": "v1",
            "sku": "S01", "production_route": "manual" if slot in {"W4-001", "W4-003"} else "ai_assisted",
            "work_id": work, "media_sha256": media, "dependency_sha256": "d" * 64,
            "status": "approved", "quality_status": "pass", "review_url": f"/runs/{run}/review"}


def proof(row):
    return {k: row[k] for k in ("run_id", "content_version_id", "media_sha256", "dependency_sha256", "content_slot_id", "sku", "production_route", "work_id")} | {
        "media_verified": True, "quality_passed": True, "approval_valid": True,
        "approval_id": "approval-1", "quality_report_ref": "artifacts/quality.json"}


def test_actual_original_plan_preserves_all_quotas_and_route_pairs(plan):
    validate_artifact("campaign_plan", plan)
    rows = plan["slots"]
    assert Counter(r["week"] for r in rows) == {1: 75, 2: 75, 3: 75, 4: 75}
    assert Counter(r["sku"] for r in rows) == {"S01": 100, "S08": 120, "S04": 80}
    assert Counter(r["direction_id"] for r in rows) == {
        "test_selection": 90, "healing_ritual": 75, "relationship_story": 60,
        "space_play": 45, "comment_faq": 15, "transaction": 15}
    assert sum(r["support_type"] == "experiment" for r in rows) == 240
    assert Counter(r["production_route"] for r in rows if r["week"] == 4) == {
        "manual": 30, "ai_assisted": 30, "support": 15}
    assert len({r["matched_brief_id"] for r in rows if r["week"] == 4 and r["support_type"] == "experiment"}) == 30
    assert all(r["product_id"] is None for r in rows)
    assert plan["pilot_count"] == 0


def test_w1_coverage_does_not_claim_story_or_comedy_calibration(plan):
    view = build_campaign_panorama(plan, [])
    week = view["coverage"]["weeks"]["W1"]
    assert "relationship_story" not in week["directions"]
    assert "space_play" not in week["directions"]
    assert set(week["structures"]) == {"P1", "P2", "P6"}
    assert view["coverage"]["calibration"]["does_not_cover_all_structures"] is True
    assert view["summary"]["approved_unique"] == 0
    assert view["summary"]["status_counts"]["planned"] == 300


def test_raw_approved_string_and_hashes_are_not_approval(plan):
    row = record()
    view = build_campaign_panorama(plan, [row])
    assert view["slots"][0]["status"] == "awaiting_review"
    assert view["slots"][0]["verification_status"] == "unverified"
    assert view["summary"]["approved_unique"] == 0


@pytest.mark.parametrize("field", ["media_sha256", "dependency_sha256", "content_version_id"])
def test_changed_version_or_hash_invalidates_old_approval(plan, field):
    row = record()
    attestation = proof(row)
    row[field] = "b" * 64
    view = build_campaign_panorama(plan, [row], verification_reports={row["run_id"]: attestation})
    assert view["summary"]["approved_unique"] == 0
    assert "stale_verification" in view["slots"][0]["counting_exclusions"]


def test_unique_work_and_media_count_only_once_across_both_routes(plan):
    manual = record("W4-001", "manual")
    ai = record("W4-002", "ai", work="work-2")
    recoded = record("W4-003", "recoded", media="b" * 64)
    rows = [manual, ai, recoded]
    view = build_campaign_panorama(plan, rows, verification_reports={r["run_id"]: proof(r) for r in rows})
    assert view["summary"]["approved_unique"] == 1
    assert sum(r["counted"] for r in view["slots"]) == 1
    assert "duplicate_media" in view["slots"][226]["counting_exclusions"]
    assert "duplicate_work" in view["slots"][227]["counting_exclusions"]


def test_reference_only_and_pilot_without_original_slot_never_count(plan):
    old = record("W2-001", "old") | {"reference_only": True}
    pilot = record("P1-001", "pilot", media="b" * 64)
    view = build_campaign_panorama(plan, [old, pilot], verification_reports={r["run_id"]: proof(r) for r in [old, pilot]})
    assert view["summary"]["approved_unique"] == 0
    assert view["excluded_records"][0]["run_id"] == "pilot"
    assert "reference_only" in view["slots"][75]["counting_exclusions"]


def test_verified_reference_identity_cannot_be_relabelled_as_new_work(plan):
    baseline = record("W2-001", "baseline") | {"reference_only": True}
    reused = record("W3-001", "reused", work="renamed-work")
    records = [baseline, reused]
    view = build_campaign_panorama(plan, records, verification_reports={r["run_id"]: proof(r) for r in records})
    assert view["summary"]["approved_unique"] == 0
    assert "duplicate_media" in view["slots"][150]["counting_exclusions"]


def test_release_requires_real_budget_and_week_approval(plan):
    context = {"fact_versions": {"S01": "fact-v1"}, "brand_version": "brand-v1",
               "recipe_first_articles": {"P1": "review-pass"}, "approved_weeks": [1]}
    view = build_campaign_panorama(plan, [], release_context=context)
    assert view["slots"][0]["release"]["ready"] is False
    assert "production_budget_not_approved" in view["slots"][0]["release"]["blockers"]
    assert "week_not_approved" in view["slots"][75]["release"]["blockers"]


def test_zero_budget_never_releases_paid_production(plan):
    plan["slots"][0]["structure_id"] = "P1"
    context = {"fact_versions": {"S01": "fact-v1"}, "brand_version": "brand-v1",
               "recipe_first_articles": {"P1": "review-pass"}, "approved_weeks": [1],
               "production_budget": {"approved": True, "cap_cny": 0, "approval_ref": "zero-cap"}}
    release = build_campaign_panorama(plan, [], release_context=context)["slots"][0]["release"]
    assert release["ready"] is False
    assert "production_budget_not_approved" in release["blockers"]


def test_unknown_costs_and_timing_remain_null_and_projection_is_read_only(plan):
    row = record() | {"costs": {"estimated_cny": 6.111, "paid_cny": None}, "timing": {"generation_ms": 150000}}
    before = deepcopy((plan, row))
    view = build_campaign_panorama(plan, [row])
    assert view["slots"][0]["costs"] == {"estimated_cny": 6.111, "paid_cny": None}
    assert view["summary"]["costs"]["paid_cny"] is None
    assert view["summary"]["costs"]["estimated_cny"] is None
    assert view["summary"]["costs"]["known_estimated_cny"] == 6.111
    assert view["slots"][0]["timing"]["human_work_ms"] is None
    assert (plan, row) == before
    assert build_campaign_panorama(plan, [row]) == view


def test_record_order_does_not_choose_arbitrary_current_version(plan):
    old = record(run="old") | {"content_version_id": "v1"}
    new = record(run="new", media="b" * 64, work="work-2") | {"content_version_id": "v2"}
    rows = [old, new]
    proofs = {r["run_id"]: proof(r) for r in rows}
    view = build_campaign_panorama(plan, rows, verification_reports=proofs)
    assert view == build_campaign_panorama(plan, list(reversed(rows)), verification_reports=proofs)
    assert view["slots"][0]["counted"] is False
    assert "ambiguous_current_version" in view["slots"][0]["counting_exclusions"]
    plan["slots"][0]["content_version_id"] = "v2"
    assert build_campaign_panorama(plan, rows, verification_reports=proofs)["slots"][0]["canonical_run_id"] == "new"


def test_projection_schema(plan):
    validate_artifact("campaign_panorama", build_campaign_panorama(plan, []))


def test_embedded_fake_evidence_cannot_self_approve(plan):
    row = record() | {"verification_report": proof(record()), "media_verified": True,
                      "quality_passed": True, "approval_valid": True}
    view = build_campaign_panorama(plan, [row])
    assert view["summary"]["approved_unique"] == 0
    assert "verification_missing" in view["slots"][0]["counting_exclusions"]


@pytest.mark.parametrize("field,value", [("content_slot_id", "W4-001"), ("sku", "S08"),
                                          ("production_route", "manual"), ("work_id", "renamed")])
def test_proof_binds_original_slot_sku_route_and_work_identity(plan, field, value):
    row = record()
    attestation = proof(row)
    row[field] = value
    view = build_campaign_panorama(plan, [row], verification_reports={row["run_id"]: attestation})
    assert view["summary"]["approved_unique"] == 0


def test_record_and_proof_identity_must_also_match_plan_slot(plan):
    row = record() | {"sku": "S08", "production_route": "manual"}
    view = build_campaign_panorama(plan, [row], verification_reports={row["run_id"]: proof(row)})
    assert view["summary"]["approved_unique"] == 0
    assert "plan_identity_mismatch" in view["slots"][0]["counting_exclusions"]


def test_shared_cost_is_counted_once_and_split_evenly_for_route_comparison():
    shared = {"cost_id": "shared-1", "category": "shared_preparation", "estimated_cny": 100, "paid_cny": 80}
    manual = {"cost_id": "manual-1", "category": "path_increment", "production_route": "manual", "estimated_cny": 20, "paid_cny": 20}
    ai = {"cost_id": "ai-1", "category": "path_increment", "production_route": "ai_assisted", "estimated_cny": 10, "paid_cny": 12}
    view = summarize_path_costs([shared, ai, shared, manual])
    assert view["shared_preparation"]["paid_cny"] == 80
    assert view["routes"]["manual"]["incremental"]["paid_cny"] == 20
    assert view["routes"]["manual"]["full_cost"]["paid_cny"] == 60
    assert view["routes"]["ai_assisted"]["full_cost"]["paid_cny"] == 52
    assert view["project_total"]["paid_cny"] == 112
    assert view["complete"] is True
    assert view == summarize_path_costs([manual, shared, ai])


def test_path_comparison_does_not_zero_missing_or_conflicting_costs():
    shared = {"cost_id": "shared", "category": "shared_preparation", "estimated_cny": 100, "paid_cny": None}
    ai = {"cost_id": "ai", "category": "path_increment", "production_route": "ai_assisted", "estimated_cny": 10, "paid_cny": 5}
    view = summarize_path_costs([shared, ai])
    assert view["complete"] is False
    assert view["routes"]["manual"]["incremental"]["paid_cny"] is None
    assert view["routes"]["ai_assisted"]["full_cost"]["paid_cny"] is None
    assert view["project_total"]["paid_cny"] is None
    conflict = summarize_path_costs([shared, shared | {"paid_cny": 999}, ai])
    assert conflict["shared_preparation"]["paid_cny"] is None
    assert "conflicting_cost_entry:shared" in conflict["warnings"]


def test_conflicting_cost_routes_do_not_depend_on_entry_order():
    manual = {"cost_id": "same", "category": "path_increment", "production_route": "manual", "estimated_cny": 10, "paid_cny": 10}
    ai = manual | {"production_route": "ai_assisted"}
    assert summarize_path_costs([manual, ai]) == summarize_path_costs([ai, manual])


def test_unallocated_cost_marks_both_full_route_costs_unknown():
    entries = [
        {"cost_id": "shared", "category": "shared_preparation", "estimated_cny": 100, "paid_cny": 100},
        {"cost_id": "manual", "category": "path_increment", "production_route": "manual", "estimated_cny": 20, "paid_cny": 20},
        {"cost_id": "ai", "category": "path_increment", "production_route": "ai_assisted", "estimated_cny": 10, "paid_cny": 10},
        {"cost_id": "unknown-route", "category": "path_increment", "estimated_cny": 400, "paid_cny": 400},
    ]
    view = summarize_path_costs(entries)
    assert view["routes"]["manual"]["full_cost"]["paid_cny"] is None
    assert view["routes"]["ai_assisted"]["full_cost"]["paid_cny"] is None


def test_documented_adapter_fixture_is_schema_valid_and_can_release_selected_recipe(plan):
    fixture = json.loads((ROOT / "tests/fixtures/campaign_projection_inputs.json").read_text())
    row = fixture["record"]
    view = build_campaign_panorama(plan, [row], verification_reports={row["run_id"]: fixture["verification_report"]},
                                   release_context=fixture["release_context"], cost_entries=fixture["cost_entries"])
    validate_artifact("campaign_panorama", view)
    assert view["summary"]["approved_unique"] == 1
    assert view["slots"][0]["release"]["ready"] is True
    assert view["path_cost_comparison"]["complete"] is False

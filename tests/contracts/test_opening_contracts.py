"""Versioned opening contracts keep plans, observations and approval separate."""
import copy

import pytest
from jsonschema import ValidationError

from lib.hook_plan import build_hook_plan
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


def ref(path="asset.mp4"):
    return {"path": path, "sha256": "a" * 64}


def hook_v2():
    plan = build_hook_plan("opening", overrides={"first_frame_visual": "bag opens", "first_audio": "Easy access"})
    plan.update(version="2.0", hook_window_seconds=[0, 3], sku="bag-01", promise="Visible access to contents",
        source={"kind": "creative_hypothesis", "verification_status": "pending", "gap": "No original customer audio supplied"},
        purchase_question="Can I reach the contents?",
        motion_policy={"mode": "subject_motion_required", "rationale": "Opening promises visible access"},
        promise_fulfillment={"section_id": "proof", "interval_seconds": [4, 6], "evidence_ref": ref("facts.json")},
        beats=[{"interval_seconds": [0, 1], "visual": "closed", "audio": "Easy"},
               {"interval_seconds": [1, 2], "visual": "opens", "audio": "access"},
               {"interval_seconds": [2, 3], "visual": "contents visible", "audio": "sound"}],
        voice_keywords=[{"text": "access", "interval_seconds": [1, 2], "sound": "spoken emphasis"}],
        shots=[{"shot_id": "s1", "interval_seconds": [0, 3],
            "source_mapping": {"source_interval_seconds": [0.25, 3.25], "source_duration_seconds": 4, "playback_rate": 1, "output_interval_seconds": [0, 3]},
            "asset_identity": {"kind": "generated", "sku": "bag-01", "source": ref(), "reference_images": [ref("reference.png")],
                "model_task": {"provider": "test", "model": "test-model", "task_id": "task-1"}},
            "motion": {"motion_required": True, "subject": "bag lid", "verb": "opens", "start_state": "closed", "end_state": "open",
                "interval_seconds": [0.5, 2.5], "visible_result": "contents visible", "forbidden_changes": ["logo"]},
            "framing": {"source_aspect_ratio": "16:9", "output_aspect_ratio": "9:16", "fit": "contain",
                "action_safe_box": [0.1, 0.1, 0.8, 0.8], "critical_parts": ["lid", "bag edge"]}}])
    return plan


def experiment():
    return {"version": "2.0", "experiment_id": "exp-1", "motion_requirement": "subject_motion_required", "sku": "bag-01", "window_seconds": [0, 3],
        "master_ref": {**ref("master.json"), "sku": "bag-01"},
        "baseline_ref": {**ref("baseline.json"), "sku": "bag-01"},
        "facts_ref": {**ref("facts.json"), "sku": "bag-01"}, "brand_ref": ref("brand.json"),
        "frozen_body_ref": ref("body.json"), "budget_ref": ref("budget.json"),
        "candidates": [{"candidate_id": "A", "hook_plan_ref": {**ref("hook.json"), "version": "2.0"}}]}


def test_v1_default_and_roundtrip_remain_v1():
    plan = build_hook_plan("old", overrides={"first_frame_visual": "visual", "first_audio": "audio"})
    before = copy.deepcopy(plan)
    validate_artifact("hook_plan", plan)
    assert plan == before
    assert plan["version"] == "1.0" and plan["hook_window_seconds"] == [0, 1.5]


def test_v2_three_second_plan_and_explicit_builder():
    data = hook_v2()
    validate_artifact("hook_plan", data)
    built = build_hook_plan("opening", version="2.0", overrides={k: v for k, v in data.items() if k not in {"version", "created_at", "project_id"}})
    assert built["version"] == "2.0" and built["hook_window_seconds"] == [0, 3]


@pytest.mark.parametrize("remove", ["source", "purchase_question", "promise_fulfillment", "beats", "voice_keywords"])
def test_v2_requires_complete_opening_package(remove):
    data = hook_v2()
    del data[remove]
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


@pytest.mark.parametrize("field", ["subject", "verb", "start_state", "end_state", "interval_seconds", "visible_result", "forbidden_changes"])
def test_v2_requires_each_motion_field(field):
    data = hook_v2()
    del data["shots"][0]["motion"][field]
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


@pytest.mark.parametrize("field", ["source_aspect_ratio", "output_aspect_ratio", "fit", "action_safe_box", "critical_parts"])
def test_v2_requires_each_framing_field(field):
    data = hook_v2()
    del data["shots"][0]["framing"][field]
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


@pytest.mark.parametrize("interval", [[2, 1], [0, float("nan")], [0, float("inf")], [-1, 1], [2, 4]])
def test_invalid_motion_intervals_rejected(interval):
    data = hook_v2()
    data["shots"][0]["motion"]["interval_seconds"] = interval
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


def test_experiment_registered_and_sku_bound_to_master():
    assert {"opening_experiment", "opening_validation_report"} <= set(ARTIFACT_NAMES)
    validate_artifact("opening_experiment", experiment())
    data = experiment()
    data["master_ref"]["sku"] = "other"
    with pytest.raises(ValidationError):
        validate_artifact("opening_experiment", data)


@pytest.mark.parametrize("field", ["master_ref", "baseline_ref", "facts_ref", "brand_ref", "frozen_body_ref", "budget_ref"])
def test_experiment_requires_reference(field):
    data = experiment()
    del data[field]
    with pytest.raises(ValidationError):
        validate_artifact("opening_experiment", data)


@pytest.mark.parametrize("path", ["../hook.json", "/tmp/hook.json", "nested/../../hook.json", "..\\hook.json"])
def test_reference_paths_cannot_escape(path):
    data = experiment()
    data["candidates"][0]["hook_plan_ref"]["path"] = path
    with pytest.raises(ValidationError):
        validate_artifact("opening_experiment", data)


def test_experiment_refuses_v1_or_mismatched_candidate():
    from lib.opening_contracts import validate_opening_experiment
    data = experiment()
    old = build_hook_plan("old", overrides={"first_frame_visual": "visual", "first_audio": "audio"})
    with pytest.raises(ValidationError):
        validate_opening_experiment(data, hook_plans={"A": old})
    candidate = hook_v2()
    candidate["sku"] = "other"
    with pytest.raises(ValidationError):
        validate_opening_experiment(data, hook_plans={"A": candidate})


@pytest.mark.parametrize("kind", ["document_excerpt", "problem_rewrite", "creative_hypothesis"])
def test_pending_source_gap_is_honest_and_allowed(kind):
    data = hook_v2()
    data["source"] = {"kind": kind, "verification_status": "pending", "gap": "Original reference unavailable"}
    validate_artifact("hook_plan", data)


@pytest.mark.parametrize("kind", ["document_excerpt", "problem_rewrite", "creative_hypothesis"])
def test_verified_source_cannot_have_only_gap(kind):
    data = hook_v2()
    data["source"] = {"kind": kind, "verification_status": "verified", "gap": "Missing original"}
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


def test_rewrite_is_linked_to_parent_and_excerpt_to_original():
    data = hook_v2()
    for kind, field in [("problem_rewrite", "parent_ref"), ("document_excerpt", "ref")]:
        data["source"] = {"kind": kind, "verification_status": "verified", field: ref("customer-source.json"), "excerpt": "Difficult to reach inside"}
        validate_artifact("hook_plan", data)


@pytest.mark.parametrize("window", [[0, 1.5], [0, 4], [1, 4]])
def test_v2_only_allows_three_second_opening(window):
    data = hook_v2()
    data["hook_window_seconds"] = window
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


@pytest.mark.parametrize("mutation", ["source_sku", "gap_in_beats", "safe_box", "fulfilled_inside_opening", "duplicate_shot"])
def test_plan_rejects_inconsistent_structure(mutation):
    data = hook_v2()
    if mutation == "source_sku":
        data["shots"][0]["asset_identity"]["sku"] = "other"
    elif mutation == "gap_in_beats":
        data["beats"][1]["interval_seconds"][0] = 1.2
    elif mutation == "safe_box":
        data["shots"][0]["framing"]["action_safe_box"] = [0.5, 0.5, 0.8, 0.8]
    elif mutation == "fulfilled_inside_opening":
        data["promise_fulfillment"]["interval_seconds"] = [2, 4]
    else:
        data["shots"].append(copy.deepcopy(data["shots"][0]))
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


def test_v1_integrity_envelope_keeps_existing_type_validation():
    data = build_hook_plan("old", overrides={"first_frame_visual": "visual", "first_audio": "audio"})
    data["semantic_sha256"] = 17
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


@pytest.mark.parametrize("mutation", ["missing_mapping", "missing_motion_required", "duration", "rate", "output", "source_range", "nan"])
def test_strict_source_to_output_mapping(mutation):
    data = hook_v2()
    shot = data["shots"][0]
    if mutation == "missing_mapping":
        del shot["source_mapping"]
    elif mutation == "missing_motion_required":
        del shot["motion"]["motion_required"]
    elif mutation == "duration":
        shot["source_mapping"]["source_duration_seconds"] = 3
    elif mutation == "rate":
        shot["source_mapping"]["playback_rate"] = 0.5
    elif mutation == "output":
        shot["source_mapping"]["output_interval_seconds"] = [0, 2]
    elif mutation == "source_range":
        shot["source_mapping"]["source_interval_seconds"] = [0, 4]
    else:
        shot["source_mapping"]["playback_rate"] = float("nan")
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


@pytest.mark.parametrize("kind", ["real", "imported"])
def test_real_source_has_origin_without_fake_model_task(kind):
    data = hook_v2()
    identity = data["shots"][0]["asset_identity"]
    identity.update(kind=kind, origin={"description": "Customer supplied filmed product demonstration", "ref": ref("source-record.json")})
    del identity["model_task"]
    validate_artifact("hook_plan", data)
    del identity["origin"]
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


def test_generated_source_requires_actual_model_task():
    data = hook_v2()
    del data["shots"][0]["asset_identity"]["model_task"]
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


def test_motion_optional_needs_explicit_creative_purpose():
    data = hook_v2()
    data["motion_policy"] = {"mode": "optional", "rationale": "Static detail shot supports the question"}
    data["shots"][0]["motion"].update(motion_required=False, verb="none", end_state="closed", exemption_reason="Static logo detail provides identity")
    validate_artifact("hook_plan", data)
    del data["shots"][0]["motion"]["exemption_reason"]
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)


def test_declared_motion_experiment_cannot_downgrade_to_all_static():
    from lib.opening_contracts import validate_opening_experiment
    data = hook_v2()
    data["motion_policy"] = {"mode": "optional", "rationale": "Static alternate"}
    data["shots"][0]["motion"].update(motion_required=False, exemption_reason="Still detail")
    with pytest.raises(ValidationError):
        validate_opening_experiment(experiment(), hook_plans={"A": data})


def test_motion_exemption_cannot_still_declare_an_opening_action():
    data = hook_v2()
    data["motion_policy"] = {"mode": "optional", "rationale": "Static shot"}
    data["shots"][0]["motion"].update(motion_required=False, exemption_reason="Static shot")
    with pytest.raises(ValidationError):
        validate_artifact("hook_plan", data)

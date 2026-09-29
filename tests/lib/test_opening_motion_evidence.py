"""A planned action, camera movement or unbound pass is not observed motion."""
import copy
import hashlib
import json

import pytest

from lib.production_quality import collect_production_quality
from lib.production_evidence import REQUIRED_CHECKS, quality_summary
from tests.contracts.test_opening_contracts import hook_v2, experiment


def write(root, path, data):
    raw = json.dumps(data).encode() if isinstance(data, dict) else data
    (root / path).write_bytes(raw)
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}


def fixture(root, *, method="independent_semantic_review", scope="preview", plan=None):
    plan = copy.deepcopy(plan) if plan is not None else hook_v2()
    plan["shots"][0]["asset_identity"]["source"] = write(root, "asset.mp4", b"source")
    if plan["shots"][0]["asset_identity"]["kind"] != "generated":
        plan["shots"][0]["asset_identity"]["origin"]["ref"] = plan["shots"][0]["asset_identity"]["source"]
    plan["shots"][0]["asset_identity"]["reference_images"] = [write(root, "reference.png", b"reference")]
    facts = write(root, "facts.json", {"sku": "bag-01"})
    plan["promise_fulfillment"]["evidence_ref"] = facts
    plan_ref = write(root, "hook.json", plan)
    exp = experiment()
    exp["motion_requirement"] = plan["motion_policy"]["mode"]
    for name in ("master", "baseline", "brand", "body", "budget"):
        item = write(root, f"{name}.json", {"sku": "bag-01"})
        exp[{"body": "frozen_body_ref"}.get(name, f"{name}_ref")] = {**item, **({"sku": "bag-01"} if name in {"master", "baseline"} else {})}
    exp["facts_ref"] = {**facts, "sku": "bag-01"}
    exp["candidates"][0]["hook_plan_ref"] = {**plan_ref, "version": "2.0"}
    exp_ref = write(root, "experiment.json", exp)
    render = write(root, "final.mp4", b"render")
    observation = {"version": "1.0", "scope": scope, "shot_id": "s1", "method": method,
        "render_sha256": render["sha256"], "hook_plan_sha256": plan_ref["sha256"],
        "reviewer": {"kind": "semantic_verifier", "id": "independent-model-run-7", "reviewed_at": "2026-09-29T10:00:00Z"},
        "evidence_interval_seconds": [0.5, 2.5],
        "actual_action": {"source_interval_seconds": [0.75, 2.75], "output_interval_seconds": [0.5, 2.5]},
        "evidence": {"frames": [], "segments": [{"ref": render, "output_interval_seconds": [0.5, 2.5]}]},
        "motion": {"subject": "bag lid", "verb": "opens", "start_state": "closed", "end_state": "open",
            "visible_result": "contents visible", "subject_motion": True, "still_image_transform": False,
            "camera_only": False, "background_only": False, "forbidden_changes": []},
        "framing": {"fit": "contain", "output_aspect_ratio": "9:16", "visible_parts": ["lid", "bag edge"],
            "clipped_parts": [], "subject_within_safe_area": True,
            "subject_box": [0.2, 0.2, 0.6, 0.6], "action_box": [0.25, 0.25, 0.5, 0.5]}}
    observation_ref = write(root, "observation.json", observation)
    report = {"version": "2.0", "scope": scope, "render": render,
        "dependencies": {"hook_plan": plan_ref, "experiment": exp_ref, "source:s1": plan["shots"][0]["asset_identity"]["source"],
                         "reference:s1:0": plan["shots"][0]["asset_identity"]["reference_images"][0]},
        "checks": [{"id": name, "shot_id": "s1", "status": "pass", "method": method,
                    "evidence_interval_seconds": [0.5, 2.5], "reviewer": observation["reviewer"], "observation_ref": observation_ref}
                   for name in ("opening_motion", "opening_framing")]}
    report_ref = write(root, "opening-report.json", report)
    record = {"sku": "bag-01", "render": render, "canonical_artifacts": {},
        "opening": {"scope": scope, "candidate_id": "A", "experiment_ref": exp_ref,
                    "hook_plan_ref": {**plan_ref, "version": "2.0"}, "validation_report_ref": report_ref}}
    return record, report, observation


def collect(root, record):
    return {item["id"]: item for item in collect_production_quality(root, record, {})["checks"]}


def update_observation(root, record, report, observation):
    bound = write(root, "observation.json", observation)
    for check in report["checks"]:
        check["observation_ref"] = bound
    record["opening"]["validation_report_ref"] = write(root, "opening-report.json", report)


def test_independent_bound_observations_can_pass_without_approval(tmp_path):
    record, _, _ = fixture(tmp_path)
    checks = collect(tmp_path, record)
    assert checks["opening_motion"]["status"] == "pass"
    assert checks["opening_framing"]["status"] == "pass"
    assert "approved" not in checks["opening_motion"]


@pytest.mark.parametrize("mutation", ["still", "camera", "background", "late", "clipped"])
def test_motion_counterexamples_cannot_pass(tmp_path, mutation):
    record, report, observation = fixture(tmp_path)
    if mutation in {"still", "camera", "background"}:
        key = {"still": "still_image_transform", "camera": "camera_only", "background": "background_only"}[mutation]
        observation["motion"][key] = True
        observation["motion"]["subject_motion"] = False
    elif mutation == "late":
        observation["evidence_interval_seconds"] = [3, 4]
    else:
        observation["framing"]["clipped_parts"] = ["bag edge"]
    update_observation(tmp_path, record, report, observation)
    checks = collect(tmp_path, record)
    assert checks["opening_motion"]["status"] != "pass"
    if mutation == "clipped":
        assert checks["opening_framing"]["status"] == "fail"


@pytest.mark.parametrize("path", ["asset.mp4", "reference.png", "hook.json", "observation.json"])
def test_stale_dependency_hash_cannot_pass(tmp_path, path):
    record, _, _ = fixture(tmp_path)
    (tmp_path / path).write_bytes(b"changed")
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


@pytest.mark.parametrize("method", ["optical_flow", "agent_observation"])
def test_advisory_observation_never_becomes_independent_pass(tmp_path, method):
    record, _, _ = fixture(tmp_path, method=method)
    checks = collect(tmp_path, record)
    assert checks["opening_motion"]["status"] == "not_run"
    assert checks["opening_framing"]["status"] == "not_run"


def test_unnamed_human_and_agent_cannot_forge_user_review(tmp_path):
    record, report, observation = fixture(tmp_path, method="human_review")
    observation["reviewer"].update(kind="agent", id="assistant")
    for check in report["checks"]:
        check["reviewer"] = observation["reviewer"]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "not_run"


@pytest.mark.parametrize("status", ["not_run", "error", "fail"])
def test_raw_nonpassing_status_preserved(tmp_path, status):
    record, report, observation = fixture(tmp_path)
    for check in report["checks"]:
        check["status"] = status
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == status


def test_preview_cannot_be_inherited_by_full_variant(tmp_path):
    record, _, _ = fixture(tmp_path)
    record["opening"]["scope"] = "full_variant"
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


def test_report_pass_without_observation_is_not_a_measurement(tmp_path):
    record, report, observation = fixture(tmp_path)
    observation.pop("motion")
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] != "pass"


def test_missing_report_and_old_required_list_cannot_hide_opening_gate(tmp_path):
    record, _, _ = fixture(tmp_path)
    report = {"render_sha256": record["render"]["sha256"], "required_checks": list(REQUIRED_CHECKS),
              "checks": [], "source_refs": {}}
    write(tmp_path, "quality.json", report)
    record["quality_report_ref"] = "quality.json"
    result = quality_summary(tmp_path, record)
    assert {"opening_motion", "opening_framing"} <= set(result["blocking_checks"])


def test_reference_path_escape_is_an_error(tmp_path):
    record, _, _ = fixture(tmp_path)
    record["opening"]["hook_plan_ref"]["path"] = "../hook.json"
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


def test_null_opening_fails_closed_in_quality_collection(tmp_path):
    record, _, _ = fixture(tmp_path)
    record["opening"] = None
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


@pytest.mark.parametrize("mutation", ["unknown_shot", "duplicate_check", "missing_source", "render", "actual_sku"])
def test_invalid_binding_is_rejected(tmp_path, mutation):
    record, report, observation = fixture(tmp_path)
    if mutation == "unknown_shot":
        report["checks"][0]["shot_id"] = "invented"
    elif mutation == "duplicate_check":
        report["checks"].append(copy.deepcopy(report["checks"][0]))
    elif mutation == "missing_source":
        del report["dependencies"]["source:s1"]
    elif mutation == "render":
        report["render"]["sha256"] = "b" * 64
    else:
        exp = json.loads((tmp_path / "experiment.json").read_text())
        exp["master_ref"] = {**write(tmp_path, "master.json", {"sku": "other"}), "sku": "bag-01"}
        bound = write(tmp_path, "experiment.json", exp)
        record["opening"]["experiment_ref"] = bound
        report["dependencies"]["experiment"] = bound
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


def test_named_human_observation_is_evidence_without_approval(tmp_path):
    record, report, observation = fixture(tmp_path, method="human_review")
    observation["reviewer"].update(kind="human", id="reviewer-chen")
    for check in report["checks"]:
        check["reviewer"] = observation["reviewer"]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "pass"
    assert not any("approv" in key for key in collect(tmp_path, record)["opening_motion"])


def test_empty_reviewer_stays_not_run(tmp_path):
    record, report, observation = fixture(tmp_path, method="human_review")
    observation["reviewer"].update(kind="human", id="")
    for check in report["checks"]:
        check["reviewer"] = observation["reviewer"]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "not_run"


def test_summary_reprojects_stale_opening_observation(tmp_path):
    record, _, _ = fixture(tmp_path)
    qa = collect_production_quality(tmp_path, record, {})
    write(tmp_path, "quality.json", qa)
    record["quality_report_ref"] = "quality.json"
    assert quality_summary(tmp_path, record)["checks"]["opening_motion"]["effective_status"] == "pass"
    (tmp_path / "reference.png").write_bytes(b"replaced")
    summary = quality_summary(tmp_path, record)
    assert summary["checks"]["opening_motion"]["effective_status"] != "pass"
    assert "opening_motion" in summary["blocking_checks"]


def test_legacy_record_has_no_opening_checks(tmp_path):
    record, _, _ = fixture(tmp_path)
    record.pop("opening")
    assert "opening_motion" not in collect(tmp_path, record)


def test_missing_actual_action_observation_is_not_run(tmp_path):
    record, report, observation = fixture(tmp_path)
    del observation["actual_action"]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "not_run"


def test_actual_action_outside_selected_source_cannot_pass(tmp_path):
    record, report, observation = fixture(tmp_path)
    observation["actual_action"] = {"source_interval_seconds": [3.3, 3.9], "output_interval_seconds": [0.5, 2.5]}
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] != "pass"


def test_source_and_output_action_must_follow_playback_mapping(tmp_path):
    record, report, observation = fixture(tmp_path)
    observation["actual_action"]["source_interval_seconds"] = [1, 2]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


@pytest.mark.parametrize("kind", ["frame", "segment"])
def test_nested_observation_evidence_hash_is_rechecked(tmp_path, kind):
    record, report, observation = fixture(tmp_path)
    evidence = write(tmp_path, "proof.bin", b"evidence")
    if kind == "frame":
        observation["evidence"]["frames"] = [{"ref": evidence, "output_seconds": 1}]
    else:
        observation["evidence"]["segments"] = [{"ref": evidence, "output_interval_seconds": [0.5, 2.5]}]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "pass"
    assert "proof.bin" in collect(tmp_path, record)["opening_motion"]["evidence_refs"]
    (tmp_path / "proof.bin").write_bytes(b"tampered")
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


def test_static_keyframe_is_not_motion_proof(tmp_path):
    record, report, observation = fixture(tmp_path)
    observation["evidence"] = {"frames": [{"ref": write(tmp_path, "frame.png", b"frame"), "output_seconds": 1}], "segments": []}
    update_observation(tmp_path, record, report, observation)
    checks = collect(tmp_path, record)
    assert checks["opening_motion"]["status"] == "not_run"
    assert checks["opening_framing"]["status"] == "pass"


def test_segment_must_cover_whole_actual_action(tmp_path):
    record, report, observation = fixture(tmp_path)
    observation["evidence"]["segments"][0]["output_interval_seconds"] = [1, 2]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] != "pass"


@pytest.mark.parametrize("field", ["subject_box", "action_box"])
def test_observed_boxes_must_fit_safe_area_even_when_boolean_says_true(tmp_path, field):
    record, report, observation = fixture(tmp_path)
    observation["framing"][field] = [0, 0, 1, 1]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_framing"]["status"] == "fail"
    assert collect(tmp_path, record)["opening_motion"]["status"] != "pass"


@pytest.mark.parametrize("box", [[0, 0, float("nan"), 1], [0.8, 0, 0.5, 1], [0, 0, 0, 1]])
def test_observed_boxes_reject_invalid_coordinates(tmp_path, box):
    record, report, observation = fixture(tmp_path)
    observation["framing"]["action_box"] = box
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_framing"]["status"] == "error"


@pytest.mark.parametrize("field", ["interval_seconds", "segment_ref", "frame_refs"])
def test_undefined_observation_fields_cannot_hide_conflicting_evidence(tmp_path, field):
    record, report, observation = fixture(tmp_path)
    observation["motion"][field] = [3.25, 4]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "error"


def test_four_second_source_selects_only_point25_to_3point25(tmp_path):
    record, _, _ = fixture(tmp_path)
    plan = json.loads((tmp_path / "hook.json").read_text())
    assert plan["shots"][0]["source_mapping"] == {
        "source_interval_seconds": [0.25, 3.25], "source_duration_seconds": 4,
        "playback_rate": 1, "output_interval_seconds": [0, 3]}
    assert collect(tmp_path, record)["opening_motion"]["status"] == "pass"


def test_playback_rate_maps_actual_action_to_output(tmp_path):
    plan = hook_v2()
    plan["shots"][0]["source_mapping"].update(source_interval_seconds=[0.25, 6.25], source_duration_seconds=7, playback_rate=2)
    record, report, observation = fixture(tmp_path, plan=plan)
    observation["actual_action"]["source_interval_seconds"] = [1.25, 5.25]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "pass"


def test_static_plan_does_not_require_subject_motion_but_requires_framing(tmp_path):
    plan = hook_v2()
    plan["motion_policy"] = {"mode": "optional", "rationale": "Static identity detail"}
    plan["shots"][0]["motion"].update(motion_required=False, verb="none", end_state="closed", exemption_reason="Static logo detail")
    record, report, observation = fixture(tmp_path, plan=plan)
    observation.pop("actual_action")
    observation.pop("motion")
    observation["evidence"] = {"frames": [{"ref": write(tmp_path, "frame.png", b"frame"), "output_seconds": 1}], "segments": []}
    report["checks"] = [row for row in report["checks"] if row["id"] == "opening_framing"]
    update_observation(tmp_path, record, report, observation)
    checks = collect(tmp_path, record)
    assert checks["opening_motion"]["status"] == "pass"
    assert checks["opening_motion"]["observations"][0]["basis"] == "motion_not_required"
    assert checks["opening_framing"]["status"] == "pass"
    observation["framing"]["action_box"] = [0, 0, 1, 1]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_framing"]["status"] == "fail"


def test_collected_checks_keep_named_human_method_and_raw_result(tmp_path):
    record, report, observation = fixture(tmp_path, method="human_review")
    observation["reviewer"].update(kind="human", id="reviewer-chen")
    for check in report["checks"]:
        check["reviewer"] = observation["reviewer"]
    update_observation(tmp_path, record, report, observation)
    collected = collect(tmp_path, record)["opening_motion"]
    assert collected["observations"][0]["method"] == "human_review"
    assert collected["observations"][0]["reviewer"]["id"] == "reviewer-chen"
    report["checks"][0]["status"] = "not_run"
    update_observation(tmp_path, record, report, observation)
    collected = collect(tmp_path, record)["opening_motion"]
    assert collected["status"] == "not_run"
    assert collected["observations"][0]["status"] == "not_run"


def test_frame_at_half_open_window_end_is_outside(tmp_path):
    record, report, observation = fixture(tmp_path)
    observation["evidence_interval_seconds"] = [0, 3]
    observation["evidence"]["frames"] = [{"ref": write(tmp_path, "frame.png", b"frame"), "output_seconds": 3}]
    for check in report["checks"]:
        check["evidence_interval_seconds"] = [0, 3]
    update_observation(tmp_path, record, report, observation)
    assert collect(tmp_path, record)["opening_framing"]["status"] == "error"


@pytest.mark.parametrize("kind", ["real", "imported"])
def test_observed_real_source_can_pass_without_model_task(tmp_path, kind):
    plan = hook_v2()
    identity = plan["shots"][0]["asset_identity"]
    identity.update(kind=kind, origin={"description": "Customer supplied filmed demonstration", "ref": identity["source"]})
    del identity["model_task"]
    record, _, _ = fixture(tmp_path, plan=plan)
    assert collect(tmp_path, record)["opening_motion"]["status"] == "pass"

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


def fixture(root, *, method="independent_semantic_review", scope="preview"):
    plan = hook_v2()
    plan["shots"][0]["asset_identity"]["source"] = write(root, "asset.mp4", b"source")
    plan["shots"][0]["asset_identity"]["reference_images"] = [write(root, "reference.png", b"reference")]
    facts = write(root, "facts.json", {"sku": "bag-01"})
    plan["promise_fulfillment"]["evidence_ref"] = facts
    plan_ref = write(root, "hook.json", plan)
    exp = experiment()
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
        "motion": {"subject": "bag lid", "verb": "opens", "start_state": "closed", "end_state": "open",
            "visible_result": "contents visible", "subject_motion": True, "still_image_transform": False,
            "camera_only": False, "background_only": False, "forbidden_changes": []},
        "framing": {"fit": "contain", "output_aspect_ratio": "9:16", "visible_parts": ["lid", "bag edge"],
            "clipped_parts": [], "subject_within_safe_area": True}}
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

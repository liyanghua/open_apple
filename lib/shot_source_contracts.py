"""Evidence contracts for one source clip, revision and proposed use.

No semantic inference happens here: observations are supplied by reviewers.
This module verifies their bindings, coverage and declared timing constraints.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _file(root, path):
    _require(isinstance(path, str) and path and not Path(path).is_absolute()
             and ".." not in Path(path).parts and "\\" not in path, "Expected project-relative file path")
    root = Path(root).resolve()
    result = (root / path).resolve()
    _require(root in result.parents and result.is_file(), f"Missing or uncontained source dependency: {path}")
    return result


def _ref(root, value):
    path = _file(root, value.get("path"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _require(digest == value.get("sha256"), f"Source dependency hash mismatch: {value.get('path')}")
    return path


def _refs(value):
    if isinstance(value, Mapping):
        if "path" in value and "sha256" in value:
            yield dict(value)
        for item in value.values():
            yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def _read(root, ref):
    result = json.loads(_ref(root, ref).read_text())
    _require(isinstance(result, dict), "Source dependency must contain a JSON object")
    return result


def _interval(value, duration=None):
    _require(isinstance(value, list) and len(value) == 2
             and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
             and 0 <= value[0] < value[1], "Invalid source interval")
    if duration is not None:
        _require(value[1] <= duration, "Source interval exceeds duration")


def source_artifact_path(shot_id, revision, filename):
    for identifier in (shot_id, revision):
        _require(isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", identifier)
                 and identifier not in {".", ".."}, "Invalid source shot/revision identity")
    return f"artifacts/shot_sources/{shot_id}/{revision}/{filename}.json"


def validate_source_plan_semantics(plan):
    source_artifact_path(plan["shot_id"], plan["revision"], "plan")
    requirements = plan["requirements"]
    ids = [item["id"] for item in requirements]
    _require(len(ids) == len(set(ids)), "Duplicate source requirement id")
    uses = plan["uses"]
    purposes = [item["purpose_id"] for item in uses]
    _require(len(purposes) == len(set(purposes)), "Duplicate source purpose")
    _require(plan["original_purpose_id"] in purposes, "Missing original source purpose")
    required = {item["id"] for item in requirements if item["required"]}
    global_ids = set(plan["global_requirement_ids"])
    _require(global_ids <= required, "Global source requirements must reference known required requirements")
    for use in uses:
        selected = set(use["required_requirement_ids"])
        _require(selected <= set(ids), "Source use references unknown requirement")
        if use["purpose_id"] == plan["original_purpose_id"]:
            _require(required <= selected, "Original purpose must include all required requirements")
            _require(global_ids <= selected, "Original purpose must include global requirements")
        if use.get("interval") is not None:
            _interval(use["interval"])
    for item in requirements:
        if item.get("interval") is not None:
            _interval(item["interval"])


def validate_source_evaluation_semantics(evaluation):
    review = evaluation["source_review"]
    _require(evaluation.get("alignment") is None, "source_clip must not create sample/final alignment")
    _require(evaluation["subject_hash"] == review["source_sha256"], "Source review media hash mismatch")
    _require(evaluation["subject_version"] == review["revision"], "Source review revision mismatch")
    ids = [item["id"] for item in review["observations"]]
    _require(len(ids) == len(set(ids)), "Duplicate source observation id")
    for reviewer in review["reviewers"]:
        coverage = reviewer["coverage"]
        if coverage["method"] == "full_playback":
            _require("video" in reviewer["input_modalities"], "Full playback requires actual video input")
            _interval(coverage.get("interval"))


def validate_source_plan(root, plan):
    _validate("shot_source_plan", plan)
    for ref in _refs(plan):
        _ref(root, ref)


def _validate(name, data):
    from schemas.artifacts import validate_artifact
    from jsonschema import ValidationError
    try:
        validate_artifact(name, data)
    except ValidationError as exc:
        raise ValueError(exc.message) from exc


def _observation_status(requirement, observation, reviewers, duration):
    if observation is None:
        return "not_run"
    status = observation["status"]
    applicability = observation.get("applicability") or {}
    if applicability.get("applies") is False:
        return "error" if requirement.get("required", True) else "not_applicable"
    if status not in {"pass", "fail"}:
        return "error" if status == "not_applicable" else status
    if not observation.get("observed", "").strip() or not observation.get("evidence"):
        return "error"
    method = observation["method"]
    if method != requirement["method"]:
        return "error"
    if method in {"frame_sampling", "human_observation"}:
        times = [ref.get("time_seconds") for ref in observation["evidence"]]
        if not any(isinstance(t, (int, float)) and not isinstance(t, bool) and 0 <= t <= duration for t in times):
            return "error"
        if not any(set(r["input_modalities"]) & {"image", "video"} for r in reviewers):
            return "error"
    if method == "full_playback":
        needed = requirement.get("interval") or [0, duration]
        if not any(r["coverage"]["method"] == "full_playback"
                   and r["coverage"]["interval"][0] <= needed[0]
                   and r["coverage"]["interval"][1] >= needed[1]
                   for r in reviewers):
            return "error"
    if status == "fail":
        return status
    start, end = observation.get("actual_start"), observation.get("actual_end")
    if start is not None or end is not None:
        if start is None or end is None or not 0 <= start <= end <= duration:
            return "error"
    if requirement.get("deadline_seconds") is not None:
        if end is None:
            return "error"
        if end > requirement["deadline_seconds"]:
            return "fail"
    if requirement.get("min_hold_seconds") is not None:
        hold = observation.get("result_hold_seconds")
        if hold is None:
            return "error"
        if hold < requirement["min_hold_seconds"]:
            return "fail"
    if requirement.get("interval") is not None and (start is None or end is None
            or start > requirement["interval"][0] or end < requirement["interval"][1]):
        return "fail"
    return "pass"


def _aggregate(statuses):
    for status in ("error", "fail", "not_run"):
        if status in statuses:
            return status
    return "pass" if statuses else "not_run"


def _use_requirements(plan, use):
    return list(dict.fromkeys([*plan["global_requirement_ids"], *use["required_requirement_ids"]]))


def _verify_generation_bindings(root, record, plan):
    """Bind adapter output to its saved original request without inventing history."""
    from lib.generation_attempts import GenerationAttempts

    inputs = _read(root, record["generation_inputs_ref"])
    envelope = _read(root, record["generation_receipt_ref"])
    receipt = envelope.get("data", envelope)
    _require(isinstance(receipt, dict), "Source generation receipt must be a JSON object")
    _require(envelope.get("success") is not False and receipt.get("success") is not False
             and (envelope.get("success") is True or receipt.get("status") == "succeeded")
             and receipt.get("status", "succeeded") == "succeeded", "Source generation receipt does not report success")
    identity = record["generation_identity"]
    expected = {**identity, **{key: record[key] for key in ("project_id", "shot_id", "revision")},
                "media_sha256": record["source"]["sha256"],
                "source_inputs_fingerprint": GenerationAttempts.fingerprint(inputs)}
    for key, value in expected.items():
        _require(receipt.get(key) is not None and receipt[key] != "", f"Source generation receipt {key} not recorded")
        _require(receipt[key] == value, f"Source generation receipt {key} mismatch")
    if inputs.get("model"):
        _require(receipt.get("model"), "Source generation receipt model not recorded")
        _require(receipt["model"] == inputs["model"], "Source generation receipt model differs from fixed input model")
    for key in ("parent_budget_id", "lineage_id"):
        _require(identity[key] == plan[key], f"Source generation {key} does not match source plan")
    input_expected = {**{key: record[key] for key in ("project_id", "shot_id")},
                      **{key: identity[key] for key in ("request_id", "parent_budget_id", "lineage_id")}}
    for key, value in input_expected.items():
        _require(inputs.get(key) is not None and inputs[key] != "", f"Source generation input {key} not recorded")
        _require(inputs[key] == value, f"Source generation input {key} mismatch")
    revision = inputs.get("revision_id", inputs.get("revision"))
    _require(revision is not None, "Source generation input revision not recorded")
    _require(revision == record["revision"], "Source generation input revision mismatch")
    if "revision" in inputs:
        _require(inputs["revision"] == record["revision"], "Source generation input revision mismatch")
    if "plan_ref" in inputs:
        _require(inputs["plan_ref"] == record["plan_ref"], "Source generation input plan_ref mismatch")
    elif "shot_source_plan" in inputs:
        omit = {"semantic_sha256", "artifact_sha256"}
        supplied = inputs["shot_source_plan"]
        _require(isinstance(supplied, dict) and {k: v for k, v in supplied.items() if k not in omit}
                 == {k: v for k, v in plan.items() if k not in omit}, "Source generation input shot_source_plan mismatch")
    elif "shot_source_plan_fingerprint" in inputs:
        _require(inputs["shot_source_plan_fingerprint"] == GenerationAttempts.fingerprint(plan),
                 "Source generation input plan fingerprint mismatch")
    else:
        raise ValueError("Source generation input source plan binding not recorded")


def validate_source_record(root, record):
    for key in ("generation_inputs_ref", "generation_identity", "generation_receipt_ref"):
        _require(record.get(key), f"Source generation {key} not recorded")
    _validate("shot_source_record", record)
    for key, filename in (("plan_ref", "plan"), ("evaluation_ref", "evaluation")):
        _require(record[key]["path"] == source_artifact_path(record["shot_id"], record["revision"], filename),
                 f"Source {key} must use canonical shot_sources path")
    for ref in _refs(record):
        _ref(root, ref)
    plan = _read(root, record["plan_ref"])
    validate_source_plan(root, plan)
    _verify_generation_bindings(root, record, plan)
    evaluation = _read(root, record["evaluation_ref"])
    _validate("evaluation_report", evaluation)
    _require(evaluation["scope"] == "source_clip", "Source record needs source_clip evaluation")
    review = evaluation["source_review"]
    for key in ("project_id", "shot_id", "revision"):
        _require(plan[key] == record[key], f"Source plan {key} mismatch")
        if key != "project_id":
            _require(review[key] == record[key], f"Source review {key} mismatch")
    _require(evaluation["project_id"] == record["project_id"], "Source evaluation project mismatch")
    marker = Path(root) / "project.json"
    if marker.is_file():
        project = json.loads(marker.read_text())
        project_id = project.get("project_id") or project.get("id")
        _require(project_id == record["project_id"], "Source record project does not match project root identity")
    _require(evaluation["subject_ref"]["path"] == record["source"]["path"], "Source evaluation path mismatch")
    _require(review["source_sha256"] == record["source"]["sha256"], "Source review media binding mismatch")
    _require(review["plan_sha256"] == record["plan_ref"]["sha256"], "Source review plan binding mismatch")
    duration = record["source"]["duration_seconds"]
    for ref in _refs(review):
        _ref(root, ref)
    for reviewer in review["reviewers"]:
        if reviewer["coverage"].get("interval") is not None:
            _interval(reviewer["coverage"]["interval"], duration)
    observations = {item["id"]: item for item in review["observations"]}
    _require(set(observations) <= {item["id"] for item in plan["requirements"]}, "Unknown source observation id")
    statuses = {item["id"]: _observation_status(item, observations.get(item["id"]), review["reviewers"], duration)
                for item in plan["requirements"]}
    technical_checks = review["technical"]["checks"]
    _require(any(item["id"] == "decode" for item in technical_checks), "Source technical decode check required")
    _require(all(item["method"] == "decode" for item in technical_checks if item["id"] == "decode"),
             "Source technical decode check must use decode method")
    _require(len({item["id"] for item in technical_checks}) == len(technical_checks), "Duplicate technical check")
    technical_statuses = []
    for check in technical_checks:
        if (check.get("applicability") or {}).get("applies") is False:
            _require(check["id"] != "decode" and (check.get("applicability") or {}).get("reason"),
                     "Source decode cannot be not applicable")
            continue
        technical_statuses.append(_observation_status({"method": check["method"]}, check, review["reviewers"], duration))
    technical_status = _aggregate(technical_statuses)
    _require(review["technical"]["status"] == technical_status, "Source technical status contradicts actual checks")
    unresolved_fatal = any(check["severity"] == "fatal" and check["status"] in {"fail", "error", "not_run"}
                           for check in evaluation["hard_gate"]["checks"])
    _require(technical_status != "pass" or (evaluation["hard_gate"]["pass"] and not unresolved_fatal),
             "Source technical pass contradicts unresolved hard gate")
    purposes = {use["purpose_id"]: {"status": _aggregate([statuses[key] for key in _use_requirements(plan, use)]),
                                        "approval_status": "pending"} for use in plan["uses"]}
    return {"technical_status": technical_status,
            "original_purpose_status": purposes[plan["original_purpose_id"]]["status"],
            "original_purpose_id": plan["original_purpose_id"], "purposes": purposes,
            "observations": [{**observations.get(key, {"id": key, "status": "not_run"}), "effective_status": status}
                             for key, status in statuses.items()]}


def build_source_subject(root, record_path, purpose_id, interval=None):
    path = _file(root, record_path)
    record = json.loads(path.read_text())
    _require(record_path == source_artifact_path(record["shot_id"], record["revision"], "record"),
             "Source record must use canonical shot_sources path")
    summary = validate_source_record(root, record)
    _require(summary["technical_status"] == "pass", "Source technical checks must pass before review")
    _require(summary["purposes"].get(purpose_id, {}).get("status") == "pass", "Selected source purpose is not eligible")
    plan = _read(root, record["plan_ref"])
    use = next(item for item in plan["uses"] if item["purpose_id"] == purpose_id)
    selected_interval = interval if interval is not None else use.get("interval") or [0, record["source"]["duration_seconds"]]
    _interval(selected_interval, record["source"]["duration_seconds"])
    allowed = use.get("interval") or [0, record["source"]["duration_seconds"]]
    _require(allowed[0] <= selected_interval[0] and selected_interval[1] <= allowed[1], "Source interval outside selected purpose")
    observations = {item["id"]: item for item in summary["observations"]}
    for requirement_id in _use_requirements(plan, use):
        observed = observations[requirement_id]
        if observed.get("actual_start") is not None:
            _require(selected_interval[0] <= observed["actual_start"]
                     and observed["actual_end"] + observed.get("result_hold_seconds", 0) <= selected_interval[1],
                     "Selected source interval excludes required action evidence")
        if observed["method"] in {"frame_sampling", "human_observation"}:
            times = [ref.get("time_seconds") for ref in observed["evidence"]]
            _require(any(isinstance(t, (int, float)) and not isinstance(t, bool)
                         and selected_interval[0] <= t <= selected_interval[1] for t in times),
                     "Selected source interval excludes required frame evidence")
    evaluation = _read(root, record["evaluation_ref"])
    all_refs = [*list(_refs(record)), *list(_refs(plan)), *list(_refs(evaluation["source_review"])),
                {"path": record_path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
    dependencies = {ref["path"]: {"path": ref["path"], "sha256": ref["sha256"]} for ref in all_refs}
    return {"kind": "source_clip", "record_path": record_path, "project_id": record["project_id"],
            "shot_id": record["shot_id"], "revision": record["revision"], "purpose_id": purpose_id,
            "content_slot_id": f"{record['shot_id']}:{record['revision']}:{purpose_id}",
            "interval": selected_interval, "source": record["source"], "dependencies": dependencies,
            "summary": {**summary, "eligible": True, "original_use_eligible": summary["original_purpose_status"] == "pass",
                        "selected_use_eligible": True, "requirements": plan["requirements"],
                        "checks": summary["observations"], "purpose_label": use.get("label", purpose_id)}}


def source_subject_hash(subject):
    return hashlib.sha256(json.dumps(subject, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def verify_source_subject(root, subject):
    try:
        fresh = build_source_subject(root, subject["record_path"], subject["purpose_id"], subject.get("interval"))
        return fresh == subject
    except (ValueError, KeyError, TypeError, OSError):
        return False

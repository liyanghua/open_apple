"""Opening contracts and file-bound observations, without generation or approval.

The hook plan is the sole creative fact source. Experiments lock its bytes;
validation reports describe observations of a specific render and scope.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import ValidationError

from lib.production_evidence import file_sha256, project_file, read_object

OPENING_CHECKS = ("opening_motion", "opening_framing")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _walk(value: Any):
    yield value
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _interval(value: list, outer=None) -> None:
    _require(len(value) == 2 and value[0] < value[1], "Interval must be half-open with end > start")
    if outer is not None:
        _require(outer[0] <= value[0] < value[1] <= outer[1], "Interval escapes its containing window")


def _box(value: list) -> None:
    x, y, width, height = value
    _require(width > 0 and height > 0 and x + width <= 1 and y + height <= 1,
             "Invalid normalized subject/action box")


def _inside_box(value: list, safe: list) -> bool:
    x, y, width, height = value
    sx, sy, sw, sh = safe
    return x >= sx and y >= sy and x + width <= sx + sw + 1e-6 and y + height <= sy + sh + 1e-6


def validate_opening_semantics(name: str, data: Mapping) -> None:
    """Semantic supplement to registered JSON schemas; does not touch files."""
    for value in _walk(data):
        if isinstance(value, float):
            _require(math.isfinite(value), "Opening contracts require finite numbers")
        if isinstance(value, Mapping):
            if "path" in value:
                path = value["path"]
                _require(isinstance(path, str) and bool(path) and not PurePosixPath(path).is_absolute()
                         and ".." not in PurePosixPath(path).parts and "\\" not in path and ":" not in path,
                         "Reference must be a project-relative path without traversal")
            for key in ("interval_seconds", "evidence_interval_seconds", "source_interval_seconds", "output_interval_seconds"):
                if key in value:
                    _interval(value[key])
            for key in ("action_safe_box", "subject_box", "action_box"):
                if key in value:
                    _box(value[key])
    if name == "hook_plan":
        source = data["source"]
        kind, status = source["kind"], source["verification_status"]
        if kind == "document_excerpt":
            _require(bool(source.get("ref") or source.get("gap")), "Document source needs a ref or explicit pending gap")
            _require(status != "verified" or bool(source.get("ref")), "Verified excerpt requires source ref")
        elif kind == "problem_rewrite":
            _require(bool(source.get("parent_ref") or source.get("gap")), "Problem rewrite requires parent_ref or gap")
            _require(status != "verified" or bool(source.get("parent_ref")), "Verified rewrite requires parent source")
        else:
            _require(status == "pending" and bool(source.get("gap")), "Creative hypothesis must declare its source gap")
        window = data["hook_window_seconds"]
        _require(data["promise_fulfillment"]["interval_seconds"][0] >= window[1], "Promise fulfillment must be after opening")
        beats = data["beats"]
        cursor = window[0]
        for beat in beats:
            _interval(beat["interval_seconds"], window)
            _require(beat["interval_seconds"][0] == cursor, "Beats must cover the opening without gaps or overlap")
            cursor = beat["interval_seconds"][1]
        _require(cursor == window[1], "Beats must cover all three seconds")
        for keyword in data["voice_keywords"]:
            _interval(keyword["interval_seconds"], window)
        ids = [shot["shot_id"] for shot in data["shots"]]
        _require(len(ids) == len(set(ids)), "Duplicate shot identity")
        if data["motion_policy"]["mode"] == "subject_motion_required":
            _require(any(shot["motion"]["motion_required"] for shot in data["shots"]),
                     "Subject-motion policy requires at least one required action")
        for shot in data["shots"]:
            _require(shot["asset_identity"]["sku"] == data["sku"], "Shot SKU mismatch")
            _interval(shot["interval_seconds"], window)
            _interval(shot["motion"]["interval_seconds"], shot["interval_seconds"])
            if not shot["motion"]["motion_required"]:
                _require(shot["motion"]["verb"] == "none"
                         and shot["motion"]["start_state"] == shot["motion"]["end_state"],
                         "Motion exemption cannot declare a subject action or state change")
            mapping = shot["source_mapping"]
            selected, output = mapping["source_interval_seconds"], mapping["output_interval_seconds"]
            _interval(selected, [0, mapping["source_duration_seconds"]])
            _require(output == shot["interval_seconds"], "Mapping output must equal the shot interval")
            _require(abs((selected[1] - selected[0]) / mapping["playback_rate"] - (output[1] - output[0])) <= 1e-6,
                     "Source selection and playback rate do not match output duration")
    elif name == "opening_experiment":
        for key in ("master_ref", "baseline_ref", "facts_ref"):
            _require(data[key]["sku"] == data["sku"], f"{key} SKU mismatch")
        ids = [candidate["candidate_id"] for candidate in data["candidates"]]
        _require(len(ids) == len(set(ids)), "Duplicate candidate identity")
    elif name == "opening_validation_report":
        ids = [(check["id"], check["shot_id"]) for check in data["checks"]]
        _require(len(ids) == len(set(ids)), "Duplicate opening check")
        for check in data["checks"]:
            _interval(check["evidence_interval_seconds"], [0, 3])


def validate_opening_experiment(data: Mapping, *, hook_plans: Mapping[str, Mapping], baseline: Mapping | None = None) -> None:
    """Validate supplied candidate documents; filesystem binding is separate."""
    from schemas.artifacts import validate_artifact

    validate_artifact("opening_experiment", data)
    if baseline is not None:
        _require(baseline.get("sku") == data["sku"], "Baseline SKU mismatch")
    for candidate in data["candidates"]:
        plan = hook_plans.get(candidate["candidate_id"])
        _require(isinstance(plan, Mapping) and plan.get("version") == "2.0", "New experiments require a v2 hook plan")
        validate_artifact("hook_plan", plan)
        _require(plan["sku"] == data["sku"], "Candidate SKU mismatch")
        _require(plan["hook_window_seconds"] == data["window_seconds"], "Candidate window mismatch")
        if data.get("motion_requirement") == "subject_motion_required":
            _require(plan["motion_policy"]["mode"] == "subject_motion_required",
                     "Declared motion experiment cannot silently become static")


def validate_opening_validation_report(data: Mapping, *, expected_scope: str | None = None) -> None:
    from schemas.artifacts import validate_artifact

    validate_artifact("opening_validation_report", data)
    if expected_scope is not None:
        _require(data["scope"] == expected_scope, "Preview results cannot be inherited by a full variant")


def _verify_ref(root: Path, ref: Mapping) -> str:
    path = project_file(root, ref.get("path"))
    _require(file_sha256(path) == ref.get("sha256"), f"Opening dependency hash mismatch: {ref.get('path')}")
    return ref["path"]


def _verify_refs(root: Path, value: Mapping) -> list[str]:
    return [_verify_ref(root, item) for item in _walk(value)
            if isinstance(item, Mapping) and "path" in item and "sha256" in item]


def _identified_observer(check: Mapping) -> bool:
    reviewer = check.get("reviewer", {})
    kind = {"independent_semantic_review": "semantic_verifier", "human_review": "human"}.get(check.get("method"))
    if kind is None or reviewer.get("kind") != kind or not reviewer.get("id", "").strip():
        return False
    try:
        return datetime.fromisoformat(reviewer["reviewed_at"].replace("Z", "+00:00")).tzinfo is not None
    except (ValueError, KeyError, TypeError):
        return False


def _observe(root: Path, check: Mapping, shot: Mapping, report: Mapping, refs: list[str]) -> tuple[str, list[str]]:
    """Interpret explicit independent observations, never caller pass dictionaries."""
    if check["status"] != "pass":
        return check["status"], list(check.get("issues", []))
    if not _identified_observer(check) or not check.get("observation_ref"):
        return "not_run", ["independent_observation_required"]
    from jsonschema import validate
    from schemas.artifacts import load_schema

    observed = read_object(root, _verify_ref(root, check["observation_ref"]))
    validate(observed, load_schema("opening_validation_report")["$defs"]["observation"])
    refs.extend(_verify_refs(root, observed))
    for key in ("method", "reviewer", "shot_id", "evidence_interval_seconds"):
        _require(observed.get(key) == check[key], f"Observation {key} mismatch")
    _require(observed.get("scope") == report["scope"], "Observation scope mismatch")
    _require(observed.get("render_sha256") == report["render"]["sha256"], "Observation render mismatch")
    _require(observed.get("hook_plan_sha256") == report["dependencies"]["hook_plan"]["sha256"], "Observation plan mismatch")
    validate_opening_semantics("observation", observed)
    interval = observed["evidence_interval_seconds"]
    _interval(interval, shot["interval_seconds"])
    expected = shot["motion"]
    framing = observed.get("framing", {})
    constraint = shot["framing"]
    evidence = observed.get("evidence", {})
    frames, segments = evidence.get("frames", []), evidence.get("segments", [])
    if not frames and not segments:
        return "not_run", ["frame_or_continuous_segment_evidence_required"]
    for frame in frames:
        _require(interval[0] <= frame["output_seconds"] <= interval[1]
                 and frame["output_seconds"] < shot["interval_seconds"][1], "Frame evidence escapes half-open reviewed interval")
    for segment in segments:
        _require(segment["ref"] == report["render"], "Continuous evidence must reference the current render")
        _interval(segment["output_interval_seconds"], interval)
    # P0 accepts the original rendered video plus an exact reviewed interval.
    # Supplemental frames do not establish provenance or temporal coverage.
    if not any(segment["output_interval_seconds"][0] <= interval[0]
               and segment["output_interval_seconds"][1] >= interval[1] for segment in segments):
        return "not_run", ["current_render_segment_must_cover_reviewed_interval"]
    if expected["motion_required"]:
        actual = observed.get("actual_action")
        if not actual:
            return "not_run", ["actual_action_timing_required"]
        mapping = shot["source_mapping"]
        selected, output = mapping["source_interval_seconds"], mapping["output_interval_seconds"]
        source_action, output_action = actual["source_interval_seconds"], actual["output_interval_seconds"]
        _interval(source_action, selected)
        _interval(output_action, output)
        _interval(output_action, interval)
        mapped = [output[0] + (point - selected[0]) / mapping["playback_rate"] for point in source_action]
        _require(all(abs(left - right) <= 1e-6 for left, right in zip(mapped, output_action)),
                 "Actual action source/output timing does not follow selection and playback rate")
        _require(output_action[0] <= expected["interval_seconds"][0] and output_action[1] >= expected["interval_seconds"][1],
                 "Actual action does not cover planned key interval")
    framing_keys = {"fit", "output_aspect_ratio", "visible_parts", "clipped_parts", "subject_within_safe_area", "subject_box", "action_box"}
    if not framing_keys <= framing.keys():
        return "not_run", ["framing_observation_incomplete"]
    visible, clipped = framing["visible_parts"], framing["clipped_parts"]
    _require(isinstance(visible, list) and isinstance(clipped, list), "Invalid observed parts")
    frame_ok = (framing["fit"] == constraint["fit"] and framing["output_aspect_ratio"] == constraint["output_aspect_ratio"]
                and framing["subject_within_safe_area"] is True
                and all(_inside_box(framing[key], constraint["action_safe_box"]) for key in ("subject_box", "action_box"))
                and set(constraint["critical_parts"]) <= set(visible)
                and not set(constraint["critical_parts"]) & set(clipped))
    if not frame_ok:
        return "fail", ["required_action_or_product_parts_not_visible"]
    if check["id"] == "opening_framing":
        return "pass", []
    motion = observed.get("motion", {})
    keys = {"subject", "verb", "start_state", "end_state", "visible_result", "subject_motion",
            "still_image_transform", "camera_only", "background_only", "forbidden_changes"}
    if not keys <= motion.keys():
        return "not_run", ["motion_observation_incomplete"]
    _require(isinstance(motion["forbidden_changes"], list), "Invalid observed changes")
    correct = (all(motion[key] == expected[key] for key in ("subject", "verb", "start_state", "end_state", "visible_result"))
               and motion["subject_motion"] is True
               and all(motion[key] is False for key in ("still_image_transform", "camera_only", "background_only"))
               and not set(expected["forbidden_changes"]) & set(motion["forbidden_changes"]))
    return ("pass", []) if correct else ("fail", ["required_subject_action_not_observed"])


def evaluate_opening_checks(root: Path, record: Mapping) -> dict[str, dict]:
    """Revalidate actual bytes and observations for a record with opening refs.

    Optical flow and agent observations are advisory. Even a human observation
    is evidence only: this function never creates or implies user approval.
    """
    opening = record.get("opening")
    if "opening" not in record:
        return {}
    method = "opening_file_bound_observation"
    def results(status, refs=(), issues=()):
        return {name: {"id": name, "status": status, "method": method,
                       "evidence_refs": sorted(set(refs)), "issues": list(issues)} for name in OPENING_CHECKS}
    try:
        from schemas.artifacts import load_schema, validate_artifact
        import jsonschema

        jsonschema.validate(opening, load_schema("production_record")["properties"]["opening"])
        validate_opening_semantics("production_record", {"opening": opening})
        refs = _verify_refs(root, opening)
        plan = read_object(root, opening["hook_plan_ref"]["path"])
        validate_artifact("hook_plan", plan)
        _require(plan.get("version") == "2.0", "Opening record requires v2 plan")
        experiment = read_object(root, opening["experiment_ref"]["path"])
        validate_artifact("opening_experiment", experiment)
        refs += _verify_refs(root, experiment)
        candidates = {row["candidate_id"]: row["hook_plan_ref"] for row in experiment["candidates"]}
        _require(candidates.get(opening["candidate_id"]) == opening["hook_plan_ref"], "Candidate plan lock mismatch")
        plans = {key: read_object(root, ref["path"]) for key, ref in candidates.items()}
        validate_opening_experiment(experiment, hook_plans=plans,
                                    baseline=read_object(root, experiment["baseline_ref"]["path"]))
        for key in ("master_ref", "facts_ref"):
            _require(read_object(root, experiment[key]["path"]).get("sku") == experiment["sku"], f"Actual {key} SKU mismatch")
        _require(record.get("sku") == plan["sku"] == experiment["sku"], "Record SKU mismatch")
        refs += _verify_refs(root, plan)
        if not opening.get("validation_report_ref"):
            return results("not_run", refs, ["opening_report_missing"])
        report = read_object(root, opening["validation_report_ref"]["path"])
        validate_opening_validation_report(report, expected_scope=opening["scope"])
        _require(report["render"] == {key: record["render"][key] for key in ("path", "sha256")}, "Report render mismatch")
        refs += _verify_refs(root, report)
        dependencies = report["dependencies"]
        _require(dependencies.get("hook_plan") == {key: opening["hook_plan_ref"][key] for key in ("path", "sha256")}, "Report plan dependency mismatch")
        _require(dependencies.get("experiment") == opening["experiment_ref"], "Report experiment dependency mismatch")
        bound = {(item["path"], item["sha256"]) for item in dependencies.values()}
        for shot in plan["shots"]:
            for item in _walk(shot["asset_identity"]):
                if isinstance(item, Mapping) and "path" in item:
                    _require((item["path"], item["sha256"]) in bound, "Report missing material dependency")
        shots = {shot["shot_id"]: shot for shot in plan["shots"]}
        _require(all(check["shot_id"] in shots for check in report["checks"]), "Report references unknown shot")
        output = results("not_run", refs)
        for name in OPENING_CHECKS:
            rows = {check["shot_id"]: check for check in report["checks"] if check["id"] == name}
            states, issues, observations = [], [], []
            for shot_id, shot in shots.items():
                if name == "opening_motion" and not shot["motion"]["motion_required"]:
                    observations.append({**rows.get(shot_id, {}), "shot_id": shot_id, "evaluated_status": "pass",
                                         "basis": "motion_not_required", "reason": shot["motion"]["exemption_reason"]})
                    continue
                if shot_id not in rows:
                    states.append("not_run")
                    issues.append("shot_observation_missing")
                    continue
                status, row_issues = _observe(root, rows[shot_id], shot, report, refs)
                observations.append({**rows[shot_id], "evaluated_status": status})
                states.append(status)
                issues.extend(row_issues)
            output[name]["status"] = next((value for value in ("error", "fail", "not_run", "pass") if value in states), "pass")
            output[name]["issues"] = sorted(set(issues))
            output[name]["observations"] = observations
        for check in output.values():
            check["evidence_refs"] = sorted(set(refs))
        return output
    except (ValidationError, ValueError, OSError, KeyError, TypeError) as exc:
        return results("error", issues=[str(exc).splitlines()[0]])

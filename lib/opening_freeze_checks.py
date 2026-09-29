"""Cheap read-side projection of current frozen-body and measured join files.

No FFmpeg is started here. A producer must persist verify_opening_join output.
Semantic/manual continuity is deliberately a separate gate.
"""
from __future__ import annotations

from jsonschema import ValidationError

import re
from lib.opening_freeze import _load, _require, _walk_refs, verify_frozen_body


def evaluate_join_measurement(root, *, measurement_ref, media_ref, duration_frames):
    refs = [measurement_ref.get("path"), media_ref.get("path")]
    check = {"id": "opening_join", "status": "not_run", "method": "file_bound_actual_join_decode",
             "evidence_refs": refs, "issues": [], "semantic_continuity_status": "not_run"}
    try:
        document = _load(root, measurement_ref)
        _walk_refs(root, document)
        _require(document.get("media_ref") == media_ref, "Join media lock mismatch")
        _require(document.get("version") == "1.0" and document.get("method") == "actual_opening_join_decode", "Unsupported join measurement")
        measurement = document["measurement"]
        _require(document["duration_frames"] == measurement["total_video_frames"] == duration_frames,
                 "Join full duration mismatch")
        _require(measurement["method"] == "ffmpeg_native_interval_v1" and measurement["media_sha256"] == media_ref["sha256"]
                 and measurement["fps"] == 30 and measurement["interval_frames"] == [75, 105], "Join measured scope mismatch")
        _require(abs(measurement["duration_seconds"] - duration_frames / 30) <= 1 / 30, "Join media duration mismatch")
        frames = []
        for line in measurement["video"]["raw_framemd5"].splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = [part.strip() for part in line.split(",")]
            _require(len(parts) == 6 and re.fullmatch(r"[a-f0-9]{32}", parts[5]), "Malformed raw frame evidence")
            frames.append({"frame": 75 + len(frames), "pts": int(parts[2]), "size": int(parts[4]), "md5": parts[5]})
        _require(frames == measurement["video"]["frames"] and len(frames) == 30
                 and all(row["pts"] == row["frame"] and row["size"] > 0 for row in frames), "Join decoded frame evidence mismatch")
        pts = measurement["video"]["timestamps_seconds"]
        _require(len(pts) == 30 and all(abs(t - (75 + i) / 30) < 1e-5 for i, t in enumerate(pts)), "Join PTS mismatch")
        audio = measurement["audio"]
        _require(0 < audio["sample_rate"] <= 192000 and 0 < audio["channels"] <= 8
                 and audio["samples"] == audio["sample_rate"] and re.fullmatch(r"[a-f0-9]{64}", audio["decoded_pcm_sha256"]), "Incomplete join audio decode")
        return {**check, "status": "pass", "observations": [measurement], "continuous_audibility_verified": False}
    except (ValidationError, ValueError, OSError, KeyError, TypeError) as exc:
        return {**check, "status": "error", "issues": [exc.message if isinstance(exc, ValidationError) else str(exc)]}


def evaluate_freeze_checks(root, record):
    opening = record.get("opening")
    if not opening or opening.get("scope") != "full_variant":
        return {}
    def results(status, issues=(), refs=()):
        return {name: {"id": name, "status": status, "method": "file_bound_frozen_body_and_join",
                "issues": list(issues), "evidence_refs": list(refs)} for name in ("frozen_body", "opening_join")}
    try:
        if not opening.get("validation_report_ref"):
            return results("not_run", ["opening_report_missing"])
        report = _load(root, opening["validation_report_ref"])
        _require(report.get("scope") == "full_variant" and report.get("render") == {k: record["render"][k] for k in ("path", "sha256")}, "Full report render binding mismatch")
        ref = report.get("dependencies", {}).get("freeze_evidence")
        if not ref:
            return results("not_run", ["freeze_evidence_missing"])
        evidence = _load(root, ref)
        _walk_refs(root, evidence)
        _require(evidence.get("version") == "1.0" and evidence.get("candidate_id") == opening["candidate_id"], "Freeze evidence identity mismatch")
        _require(evidence["experiment_ref"] == opening["experiment_ref"] and evidence["hook_plan_ref"] == opening["hook_plan_ref"], "Freeze evidence registration mismatch")
        from lib.opening_contracts import verify_opening_experiment_files
        experiment, bound = verify_opening_experiment_files(root, opening["experiment_ref"])
        candidate = next(row for row in experiment["candidates"] if row["candidate_id"] == opening["candidate_id"])
        _require(candidate["hook_plan_ref"] == opening["hook_plan_ref"] and evidence["freeze_ref"] == experiment["frozen_body_ref"], "Freeze experiment lock mismatch")
        _require(record.get("sku") == experiment["sku"] and record["canonical_artifacts"]["final_props"] == evidence["candidate_props_ref"]["path"]
                 and evidence["media_ref"] == {k: record["render"][k] for k in ("path", "sha256")}, "Freeze current props/render binding mismatch")
        proof = verify_frozen_body(root, descriptor_ref=evidence["freeze_ref"], candidate_props_ref=evidence["candidate_props_ref"],
                                   candidate_mix_plan_ref=evidence["candidate_mix_plan_ref"])
        descriptor = _load(root, evidence["freeze_ref"])
        _require(descriptor["identity"]["sku"] == experiment["sku"], "Freeze identity SKU mismatch")
        for role, key in (("facts", "facts_ref"), ("brand", "brand_ref")):
            _require(all(descriptor["dependencies"][role][k] == experiment[key][k] for k in ("path", "sha256")), "Freeze identity lock mismatch")
        output = results("not_run", ["join_measurement_missing"], [ref["path"], *bound])
        output["frozen_body"] = {"id": "frozen_body", **proof}
        if evidence.get("join_measurement_ref"):
            props = _load(root, evidence["candidate_props_ref"])
            output["opening_join"] = evaluate_join_measurement(root, measurement_ref=evidence["join_measurement_ref"],
                media_ref=evidence["media_ref"], duration_frames=props["durationInFrames"])
        return output
    except (ValidationError, ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
        return results("error", [exc.message if isinstance(exc, ValidationError) else str(exc)])

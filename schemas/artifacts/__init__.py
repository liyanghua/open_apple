"""Artifact schema loading and validation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_DIR = Path(__file__).parent

ARTIFACT_NAMES = [
    "research_brief",
    "proposal_packet",
    "brief",
    "script",
    "character_design",
    "rig_plan",
    "pose_library",
    "scene_plan",
    "action_timeline",
    "asset_manifest",
    "edit_decisions",
    "render_report",
    "publish_log",
    "review",
    "cost_log",
    "decision_log",
    "source_media_review",
    "final_review",
    "evaluation_report",
    "delivery_review",
    "character_qa_report",
    "video_analysis_brief",
    # Fastline artifacts.  They are registered here so checkpoint validation
    # and the Backlot can treat them like the original stage artifacts.
    "media_index",
    "reference_fingerprint",
    "research_breakdown",
    "reference_source_matrix",
    "research_synthesis",
    "research_scorecard",
    "research_annotations",
    "production_lock",
    "approval_bundle",
    "asset_plan",
    "change_impact",
    "render_plan",
    "final_props",
    "sample_report",
    "sample_execution_trace",
    "caption_policy_revision",
    "brand_profile",
    "creative_control_plan",
    "shot_execution_plan",
    "hook_plan",
    "caption_style_fingerprint",
    "candidate_batch",
    "repair",
    "gold_sample",
    "optimization_policy",
    "optimization_run",
    "rerun_plan",
    "rerun_run",
]


def load_schema(name: str) -> dict:
    """Load a JSON schema by artifact name."""
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_artifact(name: str, data: dict[str, Any]) -> None:
    """Validate artifact data against its schema. Raises on failure."""
    schema = load_schema(name)
    properties = schema.get("properties", {})
    # Contract-v2 envelopes attach integrity hashes to every artifact.  Older
    # business schemas predate those common fields and often use
    # additionalProperties=false, so validate their business payload without
    # the envelope-only hashes.  New fastline schemas declare and validate the
    # fields directly.
    instance = data
    if "semantic_sha256" not in properties:
        instance = {
            key: value
            for key, value in data.items()
            if key not in {"semantic_sha256", "artifact_sha256"}
        }
    jsonschema.validate(instance=instance, schema=schema)
    if name == "media_index":
        ranges = (
            item
            for entry in data.get("entries", [])
            for item in entry.get("best_ranges", [])
        )
        for item in ranges:
            if item["end_seconds"] <= item["start_seconds"]:
                raise jsonschema.ValidationError(
                    "best_ranges end_seconds must be greater than start_seconds"
                )
    elif name == "render_plan" and "sample" in data:
        sample = data["sample"]
        if sample["endFrameExclusive"] <= sample["startFrame"]:
            raise jsonschema.ValidationError(
                "sample endFrameExclusive must be greater than startFrame"
            )
    elif name == "sample_report":
        window = data["window"]
        if window["endFrameExclusive"] <= window["startFrame"]:
            raise jsonschema.ValidationError(
                "window endFrameExclusive must be greater than startFrame"
            )
    elif name == "research_breakdown":
        from lib.research_profiles import (
            load_analysis_profile,
            validate_analysis_profile_ref,
        )

        try:
            validate_analysis_profile_ref(data["profile_ref"])
        except (FileNotFoundError, ValueError) as exc:
            raise jsonschema.ValidationError(f"profile_ref: {exc}") from exc
        profile = load_analysis_profile(
            data["profile_ref"]["profile_id"], data["profile_ref"]["version"]
        )
        dimension_keys = {item["key"] for item in profile["dimensions"]}
        observations = [*data.get("reference_shots", []), *data.get("source_segments", [])]
        for item in observations:
            interval = item["interval"]
            if interval["end_seconds_exclusive"] <= interval["start_seconds"]:
                raise jsonschema.ValidationError(
                    "research breakdown interval end must be greater than start"
                )
            if set(item["values"]) != dimension_keys:
                raise jsonschema.ValidationError(
                    "research breakdown observations require all 14 profile dimensions"
                )
            if set(item["confidence_by_dimension"]) != dimension_keys:
                raise jsonschema.ValidationError(
                    "research breakdown observations require confidence for all 14 profile dimensions"
                )
            if item["values"]["interval"] != interval:
                raise jsonschema.ValidationError(
                    "research breakdown interval dimension must match the row interval"
                )
            if item["observation_source"] == "derived" and not item["evidence_refs"]:
                raise jsonschema.ValidationError(
                    "derived observations require evidence"
                )
            if item["values"].get("overlay_text") and not item["evidence_refs"]:
                raise jsonschema.ValidationError(
                    "OCR observations require evidence"
                )
        coverage = data["coverage_summary"]
        if coverage["identified"] + coverage["needs_review"] + coverage["missing"] != coverage["total"]:
            raise jsonschema.ValidationError(
                "research breakdown coverage counts must add up to total"
            )
    elif name == "reference_source_matrix":
        for row in data.get("rows", []):
            intervals = [row["reference_time_range"]]
            if row.get("source_time_range") is not None:
                intervals.append(row["source_time_range"])
            for interval in intervals:
                if interval["end_seconds_exclusive"] <= interval["start_seconds"]:
                    raise jsonschema.ValidationError(
                        "reference/source matrix interval end must be greater than start"
                    )
            if row["resolution"] in {"accept", "replace_source"} and (
                not row.get("source_media_id") or row.get("source_time_range") is None
            ):
                raise jsonschema.ValidationError(
                    "accepted matrix rows require an owned source and interval"
                )
    elif name == "research_scorecard":
        expected_checks = {
            "input_coverage",
            "evidence_traceability",
            "source_matching",
            "production_readiness",
            "execution_discipline",
        }
        checks = data["checks"]
        if len(checks) != 5 or {item["id"] for item in checks} != expected_checks:
            raise jsonschema.ValidationError(
                "research scorecard requires the five canonical checks"
            )
        if data["max_score"] != 10:
            raise jsonschema.ValidationError("research scorecard max_score must be 10")
        if data["score"] != sum(item["score"] for item in checks):
            raise jsonschema.ValidationError(
                "research score must equal the sum of its checks"
            )
        if data["score"] > data["max_score"]:
            raise jsonschema.ValidationError("research score cannot exceed max_score")
        if data["hard_failures"] and data["status"] != "fail":
            raise jsonschema.ValidationError(
                "research scorecard with hard failures must have fail status"
            )
        if data["status"] == "pass" and (
            data["score"] < 8 or any(item["status"] != "pass" for item in checks)
        ):
            raise jsonschema.ValidationError(
                "research scorecard cannot pass below 8/10 or with unresolved checks"
            )
    elif name == "evaluation_report":
        hard_gate = data["hard_gate"]
        status = data["status"]
        fatal_failures = [
            item
            for item in hard_gate.get("checks", [])
            if item["status"] == "fail" and item["severity"] == "fatal"
        ]
        if hard_gate["pass"] and fatal_failures:
            raise jsonschema.ValidationError(
                "evaluation_report hard_gate cannot pass with fatal check failures"
            )
        if status == "pass" and not hard_gate["pass"]:
            raise jsonschema.ValidationError(
                "evaluation_report status pass requires hard_gate.pass=true"
            )
        if status == "fail" and not fatal_failures:
            raise jsonschema.ValidationError(
                "evaluation_report status fail requires at least one fatal check failure"
            )
        expected_action = {
            "pass": "proceed",
            "revise": "repair",
            "fail": "reject",
        }
        if data["recommended_action"] != expected_action[status]:
            raise jsonschema.ValidationError(
                f"evaluation_report recommended_action must be {expected_action[status]!r} for status {status!r}"
            )
        coverage = hard_gate.get("coverage")
        if isinstance(coverage, dict) and coverage.get("sufficient") is False:
            if status == "pass":
                raise jsonschema.ValidationError(
                    "evaluation_report: L1a coverage insufficient 时 status 不得为 pass"
                )
            if hard_gate["pass"]:
                raise jsonschema.ValidationError(
                    "evaluation_report: L1a coverage insufficient 时 hard_gate.pass 不得为 true"
                )
    elif name == "production_lock":
        # Design_Review_2026-08-22.md P0-3: 口播必须是"已选择 TTS"或"无音频且有原因"。
        locked = data.get("locked_values") or {}
        narration = locked.get("narration")
        script = locked.get("script")
        has_spoken_copy = (isinstance(narration, str) and narration.strip()) or (
            isinstance(script, str) and script.strip()
        )
        tts = locked.get("tts") if isinstance(locked.get("tts"), dict) else {}
        tts_selected = bool(tts.get("provider") or tts.get("voice") or tts.get("selected"))
        mix = locked.get("mix") if isinstance(locked.get("mix"), dict) else {}
        explicit_no_audio_reason = any(
            mix.get(key) for key in ("reason", "no_audio_reason", "note")
        )
        if has_spoken_copy and not tts_selected and not explicit_no_audio_reason:
            raise jsonschema.ValidationError(
                "production_lock: 存在口播文案但未选择 TTS，且 mix 未记录无音频理由"
                "（reason / no_audio_reason / note）"
            )
    elif name == "hook_plan":
        window = data["hook_window_seconds"]
        if len(window) != 2 or window[1] <= window[0]:
            raise jsonschema.ValidationError(
                "hook_plan hook_window_seconds must be [start, end] with end > start"
            )
        if window[1] - window[0] > 5:
            raise jsonschema.ValidationError(
                "hook_plan hook window must not exceed 5 seconds"
            )
        if not data["first_frame_visual"].strip() or not data["first_audio"].strip():
            raise jsonschema.ValidationError(
                "hook_plan first_frame_visual and first_audio must be non-empty"
            )
    elif name == "caption_style_fingerprint":
        applicability = data["applicability"]
        style = data["style"]
        if applicability in {"extracted", "needs_review"}:
            if not str(style.get("font_family") or "").strip():
                raise jsonschema.ValidationError(
                    "caption_style_fingerprint: extracted/needs_review 必须提供 font_family"
                )
            if not style.get("size_hierarchy"):
                raise jsonschema.ValidationError(
                    "caption_style_fingerprint: extracted/needs_review 必须提供 size_hierarchy"
                )
    elif name == "candidate_batch":
        max_candidates = data["concurrency"]["max_candidates"]
        if len(data["candidates"]) > max_candidates:
            raise jsonschema.ValidationError(
                "candidate_batch candidate count exceeds concurrency.max_candidates"
            )
        ids = [item["candidate_id"] for item in data["candidates"]]
        if len(set(ids)) != len(ids):
            raise jsonschema.ValidationError("candidate_batch candidate ids must be unique")
        selected = data["selection"]["selected_candidate_ids"]
        by_status = {item["candidate_id"]: item["status"] for item in data["candidates"]}
        for candidate_id in selected:
            if candidate_id not in by_status:
                raise jsonschema.ValidationError(
                    f"candidate_batch selection references unknown candidate {candidate_id!r}"
                )
            if by_status[candidate_id] not in {"evaluated", "selected_for_edit"}:
                raise jsonschema.ValidationError(
                    f"candidate_batch selection requires evaluated candidates; {candidate_id!r} is {by_status[candidate_id]!r}"
                )
    elif name == "repair":
        if not data["lock_compliant"]:
            raise jsonschema.ValidationError(
                "repair must not change the production lock; lock_violating changes require re-approval"
            )
        if data["action"] == "shorten_shot" and data["render_route"] != "full_render":
            raise jsonschema.ValidationError(
                "repair shorten_shot shifts the timeline and must use full_render"
            )
    elif name == "gold_sample":
        ids = [item["sample_id"] for item in data["samples"]]
        if len(set(ids)) != len(ids):
            raise jsonschema.ValidationError("gold_sample sample ids must be unique")
        for item in data["samples"]:
            if item["tier"] == "hard_negative" and not item["labels"]["failure_tags"]:
                raise jsonschema.ValidationError(
                    f"gold_sample hard_negative {item['sample_id']!r} must carry failure_tags"
                )
    elif name == "optimization_policy":
        weights = data.get("weights") or {}
        if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-6:
            raise jsonschema.ValidationError(
                "optimization_policy weights must sum to 1.0"
            )
        required = set(data.get("required_dimensions") or [])
        missing_weights = required - set(weights)
        if missing_weights:
            raise jsonschema.ValidationError(
                f"optimization_policy required_dimensions missing weights: {sorted(missing_weights)}"
            )
        if data["per_dimension_min"] > data["weighted_total_min"]:
            raise jsonschema.ValidationError(
                "optimization_policy per_dimension_min must not exceed weighted_total_min"
            )
    elif name == "optimization_run":
        status = data["status"]
        confirmation = data["confirmation"]
        terminal = {"passed", "exhausted", "blocked", "failed"}
        if status in terminal and not data.get("stop_reason"):
            raise jsonschema.ValidationError(
                "optimization_run terminal status requires stop_reason"
            )
        if status not in terminal and data.get("stop_reason"):
            raise jsonschema.ValidationError(
                "optimization_run stop_reason is only allowed for terminal statuses"
            )
        if confirmation["completed_runs"] != len(confirmation["runs"]):
            raise jsonschema.ValidationError(
                "optimization_run confirmation.completed_runs must equal len(runs)"
            )
        if confirmation["passed"] and confirmation["completed_runs"] < confirmation["required_runs"]:
            raise jsonschema.ValidationError(
                "optimization_run confirmation cannot pass before required runs complete"
            )
        if status == "passed" and not confirmation["passed"]:
            raise jsonschema.ValidationError(
                "optimization_run status passed requires confirmation.passed"
            )


def list_schemas() -> list[str]:
    """List all available artifact schema names."""
    return [p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")]

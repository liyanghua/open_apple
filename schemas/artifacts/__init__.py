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


def list_schemas() -> list[str]:
    """List all available artifact schema names."""
    return [p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")]

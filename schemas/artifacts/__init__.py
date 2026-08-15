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
    "character_qa_report",
    "video_analysis_brief",
    # Fastline artifacts.  They are registered here so checkpoint validation
    # and the Backlot can treat them like the original stage artifacts.
    "media_index",
    "reference_fingerprint",
    "production_lock",
    "approval_bundle",
    "asset_plan",
    "change_impact",
    "render_plan",
    "final_props",
    "sample_report",
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
    jsonschema.validate(instance=data, schema=schema)
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


def list_schemas() -> list[str]:
    """List all available artifact schema names."""
    return [p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")]

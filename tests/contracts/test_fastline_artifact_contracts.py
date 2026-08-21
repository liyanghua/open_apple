from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from lib.research_profiles import analysis_profile_ref
from schemas.artifacts import ARTIFACT_NAMES, load_schema, validate_artifact


FASTLINE_ARTIFACTS = [
    "media_index",
    "reference_fingerprint",
    "research_breakdown",
    "reference_source_matrix",
    "research_synthesis",
    "research_scorecard",
    "production_lock",
    "approval_bundle",
    "asset_plan",
    "change_impact",
    "render_plan",
    "final_props",
    "sample_report",
]
HASH = "a" * 64
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "artifacts"


def _common() -> dict:
    return {
        "version": "1.0",
        "project_id": "demo",
        "created_at": "2026-08-14T10:00:00Z",
        "producer": "tests",
        "input_hashes": {"source": HASH},
        "semantic_sha256": HASH,
        "artifact_sha256": HASH,
    }


def valid_artifact(name: str) -> dict:
    value = _common()
    breakdown_values = {
        "ordinal": 1,
        "shot_size": "近景",
        "camera_movement": "固定",
        "camera_angle": "俯拍",
        "interval": {"start_seconds": 0, "end_seconds_exclusive": 1},
        "visual_content": "product proof",
        "dialogue": None,
        "overlay_text": None,
        "effect_treatment": None,
        "analyst_note": None,
        "evidence_frames": ["artifacts/reference-frames/frame-001.jpg"],
        "setting": None,
        "audio_layers": [],
        "music_profile": None,
    }
    business = {
        "media_index": {
            "analysis_version": "1",
            "entries": [{
                "path": "source/clip.mp4",
                "media_type": "video",
                "fingerprint": {"content_sha256": HASH, "size_bytes": 10, "mtime_ns": 1},
                "probe": {"duration": 1.0},
                "scenes": [],
                "representative_frames": [],
                "audio": {"has_track": True, "usable": True},
                "best_ranges": [{"start_seconds": 0, "end_seconds": 1}],
                "quality_risks": [],
            }],
        },
        "reference_fingerprint": {
            "content_sha256": HASH,
            "analysis_depth": "standard",
            "analyzer_version": "1",
            "canonical_request": {"depth": "standard"},
            "output_digest": HASH,
            "abstract_structure": {"beats": 3},
        },
        "research_breakdown": {
            "profile_ref": analysis_profile_ref("ecommerce-storyboard-cn", "1.0"),
            "reference_shots": [{
                "row_id": "reference-shot-1", "media_id": "reference-1",
                "interval": {"start_seconds": 0, "end_seconds_exclusive": 1},
                "values": breakdown_values,
                "evidence_refs": ["artifacts/reference-frames/frame-001.jpg"],
                "confidence_by_dimension": {
                    key: (0.9 if item is not None else 0.0)
                    for key, item in breakdown_values.items()
                },
                "observation_source": "derived", "warnings": [],
            }],
            "source_segments": [],
            "coverage_summary": {"total": 1, "identified": 1, "needs_review": 0, "missing": 0},
            "quality_warnings": [],
        },
        "reference_source_matrix": {
            "rows": [{
                "matrix_row_id": "matrix-1", "reference_scene_id": "reference-1",
                "reference_time_range": {"start_seconds": 0, "end_seconds_exclusive": 2.5},
                "reference_intent": "product proof", "source_media_id": "source-1",
                "source_time_range": {"start_seconds": 1, "end_seconds_exclusive": 3},
                "match_reason": "owned clip shows the same proof action", "confidence": 0.9,
                "evidence_frames": ["artifacts/source-frames/product-a.jpg"],
                "unmatched_gap": None, "resolution": "accept",
            }],
            "unmatched_gaps": [],
        },
        "research_synthesis": {
            "summary": "Keep the proof mechanism and use owned footage.",
            "differentiation_directions": [{
                "direction_id": "direction-1", "title": "Owned proof",
                "promise": "Show the result before explaining the feature.",
                "keep_from_reference": ["action and result"],
                "change_for_project": ["owned footage"], "avoid": ["reference copy"],
                "industry_prior_refs": [], "matrix_row_refs": ["matrix-1"],
                "prerequisites": [], "tradeoffs": [],
            }],
            "industry_prior_evaluations": [], "conflicts": [],
        },
        "research_scorecard": {
            "score": 10, "max_score": 10, "status": "pass",
            "checks": [
                {"id": check_id, "label": check_id, "score": 2, "status": "pass", "message": "Confirmed"}
                for check_id in (
                    "input_coverage", "evidence_traceability", "source_matching",
                    "production_readiness", "execution_discipline",
                )
            ],
            "hard_failures": [], "warnings": [],
        },
        "production_lock": {
            "lock_version": 1,
            "locked_values": {
                "script": {}, "narration": {}, "tts": {}, "bgm": {}, "mix": {},
                "font": {}, "captions": {}, "cta": {}, "platform": {}, "output": {},
                "render_runtime": "remotion", "composition_mode": "atelier",
            },
            "decision_revision_ids": ["decision-1"],
        },
        "approval_bundle": {
            "bundle_id": "creative-1",
            "bundle_version": 1,
            "group": "creative_lock",
            "terminal_stage": "assets",
            "members": ["proposal", "scene_plan", "assets"],
            "artifact_refs": [{
                "name": "asset_plan", "path": "artifacts/asset_plan.json",
                "semantic_sha256": HASH, "artifact_sha256": HASH,
            }],
            "status": "awaiting_human",
        },
        "asset_plan": {
            "planned_assets": [{
                "id": "voice", "type": "audio", "provider": "local", "model": "v1",
                "cost_estimate_usd": 0, "paid": False,
                "output_path": "assets/audio/voice.wav", "source_stage": "assets",
            }],
            "paid_generation_approved": False,
        },
        "change_impact": {
            "previous_lock_hash": HASH,
            "current_lock_hash": HASH,
            "route": "no_render",
            "reasons": ["metadata only"],
            "dirty_scene_ids": [],
            "reopen_creative_lock": False,
            "reopen_sample": False,
        },
        "render_plan": {
            "mode": "sample",
            "profile": "youtube_shorts",
            "previous_timeline_hash": HASH,
            "current_timeline_hash": HASH,
            "audio": {"path": "assets/audio/mix.wav", "sha256": HASH},
            "sample": {"startFrame": 0, "endFrameExclusive": 300, "scale": 0.5, "qaMode": "quick"},
        },
        "final_props": {
            "compositionId": "Cinematic",
            "fps": 30, "width": 1080, "height": 1920, "durationInFrames": 300,
            "footage": {"clip": "assets/video/clip.mp4"},
            "scenes": [{
                "id": "s1", "assetId": "clip-1", "footageKey": "clip",
                "fromFrame": 0, "toFrameExclusive": 300, "durationInFrames": 300,
                "sourceInSeconds": 0, "sourceOutSeconds": 10,
                "playbackRate": 1, "playbackMode": "normal",
            }],
            "captions": [{"text": "Hello", "startMs": 0, "endMs": 1000, "timestampMs": 0, "confidence": 1}],
            "audio": {"mix": {"narration": 1}, "assetId": "mix-1"},
        },
        "sample_report": {
            "final_props_hash": HASH,
            "render_plan_hash": HASH,
            "window": {"startFrame": 0, "endFrameExclusive": 300, "scale": 0.5},
            "output_path": "renders/sample.mp4",
            "probe": {"width": 540, "height": 960, "fps": 30, "frame_count": 300},
            "qa": {"black_frames": 0},
            "status": "pass",
        },
    }[name]
    value.update(business)
    return value


@pytest.mark.parametrize("name", FASTLINE_ARTIFACTS)
def test_fastline_schema_exists_is_registered_and_accepts_minimal_fixture(name) -> None:
    assert (SCHEMA_DIR / f"{name}.schema.json").exists()
    assert name in ARTIFACT_NAMES
    jsonschema.Draft202012Validator.check_schema(load_schema(name))
    validate_artifact(name, valid_artifact(name))


@pytest.mark.parametrize("name", FASTLINE_ARTIFACTS)
@pytest.mark.parametrize(
    "field",
    ["version", "project_id", "created_at", "producer", "input_hashes", "semantic_sha256", "artifact_sha256"],
)
def test_fastline_schemas_require_common_provenance_fields(name, field) -> None:
    value = valid_artifact(name)
    del value[field]
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact(name, value)


def test_checkpoint_envelope_requires_every_v2_field() -> None:
    schema_path = SCHEMA_DIR.parent / "checkpoints" / "checkpoint.schema.json"
    checkpoint_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    artifact_value_schema = checkpoint_schema["properties"]["artifacts"]["additionalProperties"]
    envelope = {
        "name": "media_index", "path": "artifacts/media_index.json",
        "semantic_sha256": HASH, "artifact_sha256": HASH,
        "data": valid_artifact("media_index"),
    }
    for field in tuple(envelope):
        invalid = copy.deepcopy(envelope)
        del invalid[field]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, artifact_value_schema)


def test_pipeline_manifest_accepts_artifact_contract_version_2() -> None:
    schema_path = SCHEMA_DIR.parent / "pipelines" / "pipeline_manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = {
        "name": "fastline-test",
        "version": "1.0",
        "artifact_contract_version": 2,
        "stages": [{"name": "sample", "produces": ["sample_report"]}],
    }
    jsonschema.validate(manifest, schema)


def test_pipeline_manifest_rejects_unknown_artifact_contract_version() -> None:
    schema_path = SCHEMA_DIR.parent / "pipelines" / "pipeline_manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = {
        "name": "fastline-test",
        "version": "1.0",
        "artifact_contract_version": 3,
        "stages": [{"name": "sample", "produces": ["sample_report"]}],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("media_index", lambda x: x["entries"][0].update(best_ranges=[{"start_seconds": 2, "end_seconds": 1}])),
        ("render_plan", lambda x: x["sample"].update(startFrame=301, endFrameExclusive=300)),
        ("sample_report", lambda x: x["window"].update(startFrame=301, endFrameExclusive=300)),
    ],
)
def test_half_open_ranges_require_end_after_start(name, mutate) -> None:
    value = valid_artifact(name)
    mutate(value)
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact(name, value)


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("media_index", lambda x: x["entries"][0].update(media_type="document")),
        ("reference_fingerprint", lambda x: x.update(analysis_depth="shallow")),
        ("production_lock", lambda x: x["locked_values"].update(render_runtime="unknown")),
        ("approval_bundle", lambda x: x.update(members=["script", "script"])),
        ("asset_plan", lambda x: x["planned_assets"][0].update(cost_estimate_usd=-1)),
        ("change_impact", lambda x: x.update(reasons=[])),
        ("render_plan", lambda x: (x.update(mode="mux_only"), x.pop("sample"))),
        ("final_props", lambda x: x.update(fps=24)),
        ("sample_report", lambda x: x["probe"].update(width=541)),
    ],
)
def test_business_field_mutations_are_rejected(name, mutate) -> None:
    value = valid_artifact(name)
    mutate(value)
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact(name, value)


def test_asset_plan_rejects_realized_paid_asset_before_approval() -> None:
    value = valid_artifact("asset_plan")
    value["planned_assets"][0].update(paid=True, exists=True)
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("asset_plan", value)

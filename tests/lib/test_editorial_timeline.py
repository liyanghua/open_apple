"""Contracts for the source-led EditorialTimeline v1 edit surface."""

from __future__ import annotations

from copy import deepcopy

import jsonschema
import pytest

from schemas.artifacts import load_schema


HASH = "a" * 64


def _timeline() -> dict:
    return {
        "version": "1.0",
        "timeline_id": "editorial-timeline-001",
        "profile": {
            "profile_id": "taobao-detail-3-4",
            "aspect_ratio": "3:4",
            "width": 2160,
            "height": 2880,
            "fps": 30,
            "render_runtime": "remotion",
            "safe_zone": "taobao_detail_3_4",
        },
        "base_generation_id": "generation-001",
        "base_edit_revision": "revision-001",
        "source_artifact_hashes": {
            "final_props": HASH,
            "source_semantic_index": HASH,
            "reference_source_matrix": HASH,
            "product_facts": HASH,
        },
        "tracks": [
            {
                "id": "video-main",
                "kind": "video",
                "clips": [
                    {
                        "id": "video-001",
                        "asset_id": "asset-server-video-001",
                        "source_sha256": HASH,
                        "source_in_seconds": 0,
                        "source_out_seconds": 3.2,
                        "start_seconds": 0,
                        "fact_scope": {
                            "claim_ids": ["claim-absorb-visible"],
                            "shot_id": "shot-001",
                            "visual_requirement_id": "visual-absorb-result",
                            "allowed_source_classes": ["owned_source"],
                        },
                    }
                ],
            },
            {
                "id": "narration-main",
                "kind": "narration",
                "clips": [
                    {
                        "id": "narration-001",
                        "asset_id": "asset-server-narration-001",
                        "source_sha256": HASH,
                        "start_seconds": 0,
                        "end_seconds": 3.2,
                        "claim_ids": ["claim-absorb-visible"],
                        "original_text_sha256": HASH,
                    }
                ],
            },
            {
                "id": "music-main",
                "kind": "music",
                "clips": [
                    {
                        "id": "music-001",
                        "asset_id": "asset-server-music-001",
                        "source_sha256": HASH,
                        "start_seconds": 0,
                        "end_seconds": 3.2,
                        "gain_db": -14,
                    }
                ],
            },
            {
                "id": "text-main",
                "kind": "text",
                "clips": [
                    {
                        "id": "text-001",
                        "text": "吸水过程清晰可见",
                        "start_seconds": 0.4,
                        "end_seconds": 2.4,
                        "style_token": "taobao_selling_point_v1",
                        "position": "top_center",
                        "claim_ids": ["claim-absorb-visible"],
                    }
                ],
            },
            {
                "id": "subtitle-main",
                "kind": "subtitle",
                "clips": [
                    {
                        "id": "subtitle-001",
                        "text": "水分被毛巾带走",
                        "start_seconds": 0.8,
                        "end_seconds": 2.8,
                        "style_token": "taobao_subtitle_v1",
                        "position": "bottom_center",
                        "claim_ids": ["claim-absorb-visible"],
                        "original_text_sha256": HASH,
                    }
                ],
            },
        ],
    }


def _delta() -> dict:
    return {
        "version": "1.0",
        "delta_id": "delta-001",
        "session_id": "editorial-session-001",
        "base_generation_id": "generation-001",
        "base_timeline_hash": HASH,
        "operation_sequence": 1,
        "idempotency_key": "request-001",
        "operations": [
            {
                "op": "replace_clip",
                "track_id": "video-main",
                "clip_id": "video-001",
                "asset_id": "asset-server-video-002",
                "source_sha256": HASH,
                "source_in_seconds": 1.0,
                "source_out_seconds": 3.0,
            }
        ],
    }


def test_editorial_timeline_accepts_all_supported_tracks_and_fact_bound_video_clip() -> None:
    schema = load_schema("editorial_timeline")

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_timeline(), schema)


def test_editorial_timeline_requires_fact_binding_for_video_clip() -> None:
    schema = load_schema("editorial_timeline")
    timeline = _timeline()
    del timeline["tracks"][0]["clips"][0]["fact_scope"]

    with pytest.raises(jsonschema.ValidationError, match="fact_scope"):
        jsonschema.validate(timeline, schema)


def test_editorial_timeline_rejects_unapproved_text_style_and_extra_fields() -> None:
    schema = load_schema("editorial_timeline")
    timeline = _timeline()
    timeline["tracks"][3]["clips"][0]["style_token"] = "arbitrary_css"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(timeline, schema)

    timeline = _timeline()
    timeline["tracks"][0]["clips"][0]["custom_filter"] = "url(https://example.test)"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(timeline, schema)


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "add_clip", "track_id": "video-main", "clip": _timeline()["tracks"][0]["clips"][0]},
        {"op": "remove_clip", "track_id": "video-main", "clip_id": "video-001"},
        {"op": "move_clip", "track_id": "video-main", "clip_id": "video-001", "start_seconds": 1.0},
        {"op": "split_clip", "track_id": "video-main", "clip_id": "video-001", "at_seconds": 1.0},
        {"op": "trim_clip", "track_id": "video-main", "clip_id": "video-001", "source_in_seconds": 0.2, "source_out_seconds": 2.8},
        _delta()["operations"][0],
        {"op": "set_gain", "track_id": "music-main", "clip_id": "music-001", "gain_db": -12},
        {"op": "set_fade", "track_id": "music-main", "clip_id": "music-001", "fade_in_seconds": 0.2, "fade_out_seconds": 0.5},
        {"op": "set_ducking", "track_id": "music-main", "clip_id": "music-001", "enabled": True, "reduction_db": -8},
        {"op": "set_caption_text", "track_id": "subtitle-main", "clip_id": "subtitle-001", "text": "水分被毛巾带走"},
        {"op": "set_caption_timing", "track_id": "subtitle-main", "clip_id": "subtitle-001", "start_seconds": 1.0, "end_seconds": 2.6},
        {"op": "set_text_style", "track_id": "text-main", "clip_id": "text-001", "style_token": "taobao_selling_point_v1", "position": "top_center"},
        {"op": "set_text_timing", "track_id": "text-main", "clip_id": "text-001", "start_seconds": 0.5, "end_seconds": 2.5},
    ],
)
def test_editorial_edit_delta_accepts_only_declared_typed_operations(operation: dict) -> None:
    schema = load_schema("editorial_edit_delta")
    delta = _delta()
    delta["operations"] = [deepcopy(operation)]

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(delta, schema)

    delta["operations"][0]["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(delta, schema)


def test_editorial_edit_delta_rejects_unknown_operation_discriminator() -> None:
    schema = load_schema("editorial_edit_delta")
    delta = _delta()
    delta["operations"] = [{"op": "apply_color_grade", "preset": "cinematic"}]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(delta, schema)

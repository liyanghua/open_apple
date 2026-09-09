"""Contracts for the source-led EditorialTimeline v1 edit surface."""

from __future__ import annotations

from copy import deepcopy

import jsonschema
import pytest

from schemas.artifacts import ARTIFACT_NAMES, load_schema, validate_artifact


HASH = "a" * 64


def _delta_for(timeline: dict, operation: dict) -> dict:
    from lib.cache_keys import canonical_digest

    return {
        "version": "1.0",
        "delta_id": "delta-runtime-001",
        "session_id": "editorial-session-001",
        "base_generation_id": timeline["base_generation_id"],
        "base_timeline_hash": canonical_digest(timeline),
        "operation_sequence": 1,
        "idempotency_key": "request-runtime-001",
        "operations": [deepcopy(operation)],
    }


def _catalogue_for(timeline: dict) -> dict:
    from lib.cache_keys import canonical_digest

    video = timeline["tracks"][0]["clips"][0]
    scope = deepcopy(video["fact_scope"])
    catalogue = {
        "version": "1.0",
        "candidate_id": "candidate-001",
        "project_id": "project-001",
        "timeline_id": timeline["timeline_id"],
        "base_generation_id": timeline["base_generation_id"],
        "base_edit_revision": timeline["base_edit_revision"],
        "timeline_hash": canonical_digest(timeline),
        "source_artifact_hashes": deepcopy(timeline["source_artifact_hashes"]),
        "assets": [{
            "asset_id": video["asset_id"],
            "candidate_id": "candidate-001",
            "project_id": "project-001",
            "source_asset_id": "source-001",
            "source_sha256": video["source_sha256"],
            "source_class": "owned_source",
            "valid_range": {"start_seconds": 0.0, "end_seconds": 8.0},
            "claim_ids": scope["claim_ids"],
            "fact_scope": scope,
            "visual_requirement_id": scope["visual_requirement_id"],
            "matrix_row_id": "matrix-001",
            "shot_id": scope["shot_id"],
        }],
    }
    catalogue["catalogue_hash"] = canonical_digest(catalogue)
    return catalogue


def _rehash_catalogue(catalogue: dict) -> dict:
    from lib.cache_keys import canonical_digest

    catalogue = deepcopy(catalogue)
    catalogue.pop("catalogue_hash", None)
    catalogue["catalogue_hash"] = canonical_digest(catalogue)
    return catalogue


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
            "edit_decisions": HASH,
            "final_props": HASH,
            "asset_manifest": HASH,
            "coverage_matrix": HASH,
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


def test_editorial_contracts_are_registered_for_artifact_validation() -> None:
    assert {"editorial_timeline", "editorial_edit_delta"}.issubset(ARTIFACT_NAMES)

    validate_artifact("editorial_timeline", _timeline())
    validate_artifact("editorial_edit_delta", _delta())


def test_editorial_timeline_requires_fact_binding_for_video_clip() -> None:
    schema = load_schema("editorial_timeline")
    timeline = _timeline()
    del timeline["tracks"][0]["clips"][0]["fact_scope"]

    with pytest.raises(jsonschema.ValidationError, match="fact_scope"):
        jsonschema.validate(timeline, schema)


def test_editorial_timeline_requires_exact_source_led_input_hashes() -> None:
    schema = load_schema("editorial_timeline")

    jsonschema.validate(_timeline(), schema)

    missing_required_hash = _timeline()
    del missing_required_hash["source_artifact_hashes"]["coverage_matrix"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(missing_required_hash, schema)

    arbitrary_hash = _timeline()
    arbitrary_hash["source_artifact_hashes"]["invented_input"] = HASH
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(arbitrary_hash, schema)


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
    ("track_index", "clip_field", "start", "end"),
    [
        (0, "source_in_seconds", 2.0, 1.0),
        (1, "start_seconds", 2.0, 1.0),
        (2, "start_seconds", 2.0, 1.0),
        (3, "start_seconds", 2.0, 1.0),
        (4, "start_seconds", 2.0, 1.0),
    ],
)
def test_editorial_timeline_rejects_reversed_clip_ranges(
    track_index: int, clip_field: str, start: float, end: float
) -> None:
    timeline = _timeline()
    clip = timeline["tracks"][track_index]["clips"][0]
    clip[clip_field] = start
    clip["source_out_seconds" if track_index == 0 else "end_seconds"] = end

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("editorial_timeline", timeline)


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "trim_clip", "track_id": "video-main", "clip_id": "video-001", "source_in_seconds": 2.0, "source_out_seconds": 1.0},
        {"op": "set_caption_timing", "track_id": "subtitle-main", "clip_id": "subtitle-001", "start_seconds": 2.0, "end_seconds": 1.0},
        {"op": "set_text_timing", "track_id": "text-main", "clip_id": "text-001", "start_seconds": 2.0, "end_seconds": 1.0},
    ],
)
def test_editorial_edit_delta_rejects_reversed_ranges(operation: dict) -> None:
    delta = _delta()
    delta["operations"] = [operation]

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("editorial_edit_delta", delta)


def test_editorial_timeline_rejects_duplicate_track_ids() -> None:
    timeline = _timeline()
    duplicate_track = deepcopy(timeline["tracks"][1])
    duplicate_track["id"] = timeline["tracks"][0]["id"]
    timeline["tracks"].append(duplicate_track)

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("editorial_timeline", timeline)


def test_editorial_timeline_rejects_duplicate_clip_ids_within_track() -> None:
    timeline = _timeline()
    timeline["tracks"][0]["clips"].append(deepcopy(timeline["tracks"][0]["clips"][0]))

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("editorial_timeline", timeline)


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "add_clip", "track_id": "video-main", "clip": _timeline()["tracks"][0]["clips"][0]},
        {"op": "remove_clip", "track_id": "video-main", "clip_id": "video-001"},
        {"op": "move_clip", "track_id": "video-main", "clip_id": "video-001", "start_seconds": 1.0},
        {"op": "split_clip", "track_id": "video-main", "clip_id": "video-001", "at_seconds": 1.0},
        {"op": "trim_clip", "track_id": "video-main", "clip_id": "video-001", "source_in_seconds": 0.2, "source_out_seconds": 2.8},
        _delta()["operations"][0],
        {"op": "set_speed", "track_id": "video-main", "clip_id": "video-001", "speed": 1.15},
        {"op": "set_transition", "track_id": "video-main", "clip_id": "video-001", "transition": "crossfade"},
        {"op": "move_audio", "track_id": "narration-main", "clip_id": "narration-001", "start_seconds": 0.4},
        {"op": "set_gain", "track_id": "music-main", "clip_id": "music-001", "gain_db": -12},
        {"op": "set_fade", "track_id": "music-main", "clip_id": "music-001", "fade_in_seconds": 0.2, "fade_out_seconds": 0.5},
        {"op": "set_ducking", "track_id": "music-main", "clip_id": "music-001", "enabled": True, "reduction_db": -8},
        {"op": "replace_narration", "track_id": "narration-main", "clip_id": "narration-001", "asset_id": "asset-server-narration-002", "source_sha256": HASH},
        {"op": "replace_music", "track_id": "music-main", "clip_id": "music-001", "asset_id": "asset-server-music-002", "source_sha256": HASH},
        {"op": "set_caption_text", "track_id": "subtitle-main", "clip_id": "subtitle-001", "text": "水分被毛巾带走"},
        {"op": "set_caption_timing", "track_id": "subtitle-main", "clip_id": "subtitle-001", "start_seconds": 1.0, "end_seconds": 2.6},
        {"op": "set_text_style", "track_id": "text-main", "clip_id": "text-001", "style_token": "taobao_selling_point_v1", "position": "top_center"},
        {"op": "set_text_timing", "track_id": "text-main", "clip_id": "text-001", "start_seconds": 0.5, "end_seconds": 2.5},
        {"op": "set_enabled", "track_id": "text-main", "clip_id": "text-001", "enabled": False},
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


def _source_led_materialization_inputs() -> dict:
    source_hash = "b" * 64
    narration_hash = "c" * 64
    music_hash = "d" * 64
    return {
        "candidate_id": "candidate-001",
        "project_id": "project-001",
        "base_generation_id": "generation-001",
        "base_edit_revision": "revision-001",
        "edit_decisions": {
            "semantic_sha256": "e" * 64,
            "render_runtime": "remotion",
            "safe_zone_profile": "taobao_detail_3_4",
            "cuts": [{
                "id": "shot-001", "source": "assets/video/shot-001.mp4",
                "in_seconds": 0.0, "out_seconds": 2.0,
            }],
        },
        "final_props": {
            "semantic_sha256": "f" * 64,
            "fps": 30,
            "width": 2160,
            "height": 2880,
            "scenes": [{
                "id": "shot-001", "assetId": "source-video-001",
                "fromFrame": 0, "toFrameExclusive": 60,
                "sourceInSeconds": 1.0, "sourceOutSeconds": 3.0,
                "claim_ids": ["claim-absorb-visible"],
                "evidence_row_ids": ["matrix-001"],
                "screen_copy": "吸水过程清晰可见",
            }],
            "captions": [{"text": "水分被毛巾带走", "startMs": 0, "endMs": 2000}],
        },
        "asset_manifest": {
            "semantic_sha256": "1" * 64,
            "metadata": {
                "candidate_id": "candidate-001", "project_id": "project-001",
            },
            "assets": [
            {
                "id": "source-video-001", "type": "video",
                "path": "assets/video/shot-001.mp4", "sha256": source_hash,
                "duration_seconds": 8.0, "approved": True,
            },
            {
                "id": "narration-mix-001", "type": "audio",
                "role": "narration", "path": "assets/audio/narration.mp3",
                "sha256": narration_hash, "duration_seconds": 2.0, "approved": True,
            },
            {
                "id": "bgm-001", "type": "audio", "role": "music",
                "path": "assets/music/bgm.mp3", "sha256": music_hash,
                "duration_seconds": 2.0, "approved": True,
            },
        ]},
        "coverage_matrix": {
            "semantic_sha256": "2" * 64,
            "project_id": "project-001",
            "matrix_mode": "source_led",
            "rows": [{
                "matrix_row_id": "matrix-001", "resolution": "accept",
                "source_media_id": "source-video-001", "source_hash": source_hash,
                "source_time_range": {"start_seconds": 1.0, "end_seconds_exclusive": 3.0},
                "claim_ids": ["claim-absorb-visible"],
                "visual_requirement_id": "visual-absorb-result",
            }],
        },
        "product_facts": {
            "semantic_sha256": "3" * 64,
            "claims": [{
                "id": "claim-absorb-visible",
                "visual_requirement_id": "visual-absorb-result",
            }],
        },
        "source_media_evidence": {"files": [{
            "media_id": "source-video-001", "reviewed": True,
            "media_type": "video", "sha256": source_hash,
            "technical_probe": {"duration_seconds": 8.0},
        }]},
        "source_videos": {"source-video-001": {
            "sha256": source_hash, "duration_seconds": 8.0,
        }},
        "shot_execution_plan": {
            "project_id": "project-001", "status": "approved", "shots": [{
            "id": "shot-001", "evidence_row_ids": ["matrix-001"],
            "visual_route": "owned_source", "source_media_id": "source-video-001",
            "source_selection": {
                "media_id": "source-video-001", "start_seconds": 1.0,
                "end_seconds": 3.0,
            },
        }]},
        "generation_tasks": [],
        "narration": {
            "asset_id": "narration-mix-001", "text": "水分被毛巾带走",
            "claim_ids": ["claim-absorb-visible"], "start_seconds": 0.0,
            "end_seconds": 2.0,
        },
        "bgm": {"asset_id": "bgm-001", "start_seconds": 0.0, "end_seconds": 2.0},
    }


def test_materialize_source_led_timeline() -> None:
    from lib.artifact_hashing import semantic_sha256
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    snapshot = materialize_editorial_timeline(**inputs)

    timeline = snapshot["timeline"]
    catalogue = snapshot["asset_catalogue"]
    assert [track["kind"] for track in timeline["tracks"]] == [
        "video", "narration", "music", "text", "subtitle",
    ]
    video_clip = timeline["tracks"][0]["clips"][0]
    assert video_clip["source_sha256"] == "b" * 64
    assert video_clip["fact_scope"] == {
        "claim_ids": ["claim-absorb-visible"],
        "shot_id": "shot-001",
        "visual_requirement_id": "visual-absorb-result",
        "allowed_source_classes": ["owned_source"],
    }
    assert timeline["source_artifact_hashes"] == {
        name: semantic_sha256(inputs[name])
        for name in (
            "edit_decisions", "final_props", "asset_manifest",
            "coverage_matrix", "product_facts",
        )
    }
    approved_asset = catalogue["assets"][0]
    assert approved_asset["asset_id"].startswith("editorial-")
    assert approved_asset["candidate_id"] == "candidate-001"
    assert approved_asset["project_id"] == "project-001"
    assert approved_asset["source_sha256"] == "b" * 64
    assert approved_asset["valid_range"] == {"start_seconds": 1.0, "end_seconds": 3.0}
    assert approved_asset["claim_ids"] == ["claim-absorb-visible"]
    assert approved_asset["visual_requirement_id"] == "visual-absorb-result"


def test_materialized_catalogue_includes_bound_narration_and_music_assets() -> None:
    from lib.cache_keys import canonical_digest
    from lib.editorial_timeline import materialize_editorial_timeline

    snapshot = materialize_editorial_timeline(**_source_led_materialization_inputs())
    catalogue = snapshot["asset_catalogue"]
    timeline = snapshot["timeline"]
    audio = {item["role"]: item for item in catalogue["assets"] if item.get("media_kind") == "audio"}

    assert set(audio) == {"narration", "music"}
    assert audio["narration"]["source_asset_id"] == "narration-mix-001"
    assert audio["music"]["source_asset_id"] == "bgm-001"
    assert audio["narration"]["provenance"] == {
        "source": "asset_manifest", "asset_id": "narration-mix-001",
    }
    assert catalogue["timeline_id"] == timeline["timeline_id"]
    assert catalogue["timeline_hash"] == canonical_digest(timeline)
    unsigned = deepcopy(catalogue)
    assert unsigned.pop("catalogue_hash") == canonical_digest(unsigned)


def test_materialize_source_led_timeline_rejects_missing_accepted_coverage() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    inputs["coverage_matrix"]["rows"][0]["resolution"] = "reject"

    with pytest.raises(ValueError, match="accepted coverage"):
        materialize_editorial_timeline(**inputs)


def test_owned_asset_requires_shot_execution_plan_binding() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    inputs.pop("shot_execution_plan")

    with pytest.raises(ValueError, match="shot execution plan"):
        materialize_editorial_timeline(**inputs)


def test_shot_execution_plan_completed_status_cannot_authorize_materialization() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    inputs["shot_execution_plan"]["status"] = "completed"

    with pytest.raises(ValueError, match="approved"):
        materialize_editorial_timeline(**inputs)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: plan.update(status="draft"),
        lambda plan: plan["shots"][0].update(id="other-shot"),
        lambda plan: plan["shots"][0]["source_selection"].update(media_id="other-media"),
        lambda plan: plan["shots"][0]["source_selection"].update(end_seconds=2.5),
    ],
)
def test_owned_asset_rejects_mismatched_shot_plan_binding(mutation) -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    mutation(inputs["shot_execution_plan"])

    with pytest.raises(ValueError, match="shot execution plan"):
        materialize_editorial_timeline(**inputs)


def _generated_materialization_inputs() -> dict:
    inputs = deepcopy(_source_led_materialization_inputs())
    generated_hash = "6" * 64
    inputs["final_props"]["scenes"][0].update({
        "assetId": "generated-video-001",
        "sourceInSeconds": 0.0,
        "sourceOutSeconds": 2.0,
    })
    inputs["asset_manifest"]["assets"][0] = {
        "id": "generated-video-001", "type": "video", "approved": True,
        "path": "assets/video/generated-shot-001.mp4", "sha256": generated_hash,
        "duration_seconds": 2.0,
        "provenance": {
            "generation_task_id": "generation-task-001", "shot_id": "shot-001",
        },
    }
    row = inputs["coverage_matrix"]["rows"][0]
    row.pop("source_media_id")
    row.update({
        "visual_route": "approved_generated_asset",
        "approved_asset_id": "generated-video-001",
        "shot_id": "shot-001",
        "source_hash": generated_hash,
        "source_time_range": {"start_seconds": 0.0, "end_seconds_exclusive": 2.0},
    })
    inputs["shot_execution_plan"] = {
        "project_id": "project-001", "status": "approved", "shots": [{
        "id": "shot-001", "evidence_row_ids": ["matrix-001"],
        "visual_route": "approved_generated_asset",
        "selected_generation_task_id": "generation-task-001",
        "generated_asset_id": "generated-video-001",
    }]}
    inputs["generation_tasks"] = [{
        "task_id": "generation-task-001", "shot_id": "shot-001",
        "candidate_id": "candidate-001",
        "project_id": "project-001",
        "status": "approved", "approved": True,
        "output": {
            "asset_id": "generated-video-001", "sha256": generated_hash,
            "valid_range": {"start_seconds": 0.0, "end_seconds": 2.0},
        },
    }]
    return inputs


def test_generated_catalogue_asset_requires_shot_task_provenance_and_range() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    snapshot = materialize_editorial_timeline(**_generated_materialization_inputs())

    generated = snapshot["asset_catalogue"]["assets"][0]
    assert generated["source_class"] == "approved_generated_asset"
    assert generated["valid_range"] == {"start_seconds": 0.0, "end_seconds": 2.0}


def test_generated_catalogue_rejects_unrelated_merely_approved_asset() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _generated_materialization_inputs()
    unrelated = deepcopy(inputs["asset_manifest"]["assets"][0])
    unrelated.update({"id": "unrelated-generated", "sha256": "7" * 64})
    unrelated["provenance"] = {
        "generation_task_id": "other-task", "shot_id": "other-shot",
    }
    inputs["asset_manifest"]["assets"].append(unrelated)
    inputs["coverage_matrix"]["rows"][0].update({
        "approved_asset_id": "unrelated-generated", "source_hash": "7" * 64,
    })

    with pytest.raises(ValueError, match="generation provenance"):
        materialize_editorial_timeline(**inputs)


def test_materialization_rejects_narration_claim_outside_product_facts() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    inputs["narration"]["claim_ids"] = ["invented-claim"]

    with pytest.raises(ValueError, match="narration claim"):
        materialize_editorial_timeline(**inputs)


def test_template_render_builds_editorial_snapshot_from_source_led_artifacts() -> None:
    from lib.template_render import build_editorial_snapshot

    inputs = _source_led_materialization_inputs()
    narration = inputs.pop("narration")
    bgm = inputs.pop("bgm")
    candidate_id = inputs.pop("candidate_id")
    project_id = inputs.pop("project_id")
    base_generation_id = inputs.pop("base_generation_id")
    base_edit_revision = inputs.pop("base_edit_revision")
    coverage_matrix = inputs.pop("coverage_matrix")
    source_media_evidence = inputs.pop("source_media_evidence")
    source_videos = inputs.pop("source_videos")
    artifacts = {
        **inputs,
        "reference_source_matrix": coverage_matrix,
        "source_media_review": source_media_evidence,
        "source_semantic_index": {
            "entries": [
                {"media_id": media_id, **metadata}
                for media_id, metadata in source_videos.items()
            ],
        },
    }

    snapshot = build_editorial_snapshot(
        candidate_id=candidate_id,
        project_id=project_id,
        base_generation_id=base_generation_id,
        base_edit_revision=base_edit_revision,
        artifacts=artifacts,
        narration=narration,
        bgm=bgm,
    )

    assert len(snapshot["timeline"]["tracks"]) == 5
    assert snapshot["asset_catalogue"]["candidate_id"] == candidate_id
    assert snapshot["asset_catalogue"]["project_id"] == project_id


def _verified_materialization_inputs() -> dict:
    from lib.artifact_hashing import attach_hashes

    inputs = _source_led_materialization_inputs()
    for name in (
        "edit_decisions", "final_props", "asset_manifest", "coverage_matrix", "product_facts",
    ):
        inputs[name] = attach_hashes(inputs[name])
    return inputs


def test_materialization_rejects_mutated_verified_artifact_hash() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _verified_materialization_inputs()
    inputs["edit_decisions"]["cuts"][0]["out_seconds"] = 1.5

    with pytest.raises(ValueError, match="hash"):
        materialize_editorial_timeline(**inputs)


@pytest.mark.parametrize("artifact_name", ["asset_manifest", "generation_tasks"])
def test_materialization_rejects_candidate_id_mismatch(artifact_name: str) -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    if artifact_name == "asset_manifest":
        inputs[artifact_name]["metadata"]["candidate_id"] = "other-candidate"
    else:
        inputs[artifact_name] = [{
            "task_id": "generation-task-001", "candidate_id": "other-candidate",
            "project_id": "project-001",
        }]

    with pytest.raises(ValueError, match="candidate"):
        materialize_editorial_timeline(**inputs)


@pytest.mark.parametrize("artifact_name", [
    "asset_manifest", "coverage_matrix", "shot_execution_plan", "generation_tasks",
])
def test_materialization_rejects_project_id_mismatch(artifact_name: str) -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    if artifact_name == "asset_manifest":
        inputs[artifact_name]["metadata"]["project_id"] = "other-project"
    elif artifact_name in {"coverage_matrix", "shot_execution_plan"}:
        inputs[artifact_name]["project_id"] = "other-project"
    else:
        inputs[artifact_name] = [{
            "task_id": "generation-task-001", "candidate_id": "candidate-001",
            "project_id": "other-project",
        }]

    with pytest.raises(ValueError, match="project"):
        materialize_editorial_timeline(**inputs)


def test_candidate_and_project_are_distinct_matching_ownership_scopes() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    snapshot = materialize_editorial_timeline(**inputs)

    catalogue = snapshot["asset_catalogue"]
    assert catalogue["candidate_id"] == "candidate-001"
    assert catalogue["project_id"] == "project-001"


def test_caption_end_must_stay_inside_one_fact_bound_video_clip() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    inputs["final_props"]["captions"][0]["endMs"] = 2500

    with pytest.raises(ValueError, match="caption.*video clip"):
        materialize_editorial_timeline(**inputs)


def test_generated_source_range_must_fit_generated_media_duration() -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _generated_materialization_inputs()
    inputs["asset_manifest"]["assets"][0]["duration_seconds"] = 1.0

    with pytest.raises(ValueError, match="generated media duration"):
        materialize_editorial_timeline(**inputs)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_materialization_rejects_nonfinite_source_numbers(bad_value: float) -> None:
    from lib.editorial_timeline import materialize_editorial_timeline

    inputs = _source_led_materialization_inputs()
    inputs["coverage_matrix"]["rows"][0]["source_time_range"]["end_seconds_exclusive"] = bad_value
    with pytest.raises(ValueError, match="finite|non-negative"):
        materialize_editorial_timeline(**inputs)


def test_apply_delta_trim_preserves_clip_id_and_returns_new_timeline() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    original = deepcopy(timeline)
    result = apply_delta(
        timeline,
        _delta_for(timeline, {
            "op": "trim_clip", "track_id": "video-main", "clip_id": "video-001",
            "source_in_seconds": 0.4, "source_out_seconds": 3.2,
        }),
        asset_catalogue=_catalogue_for(timeline),
    )

    assert result["timeline"] is not timeline
    assert timeline == original
    clip = result["timeline"]["tracks"][0]["clips"][0]
    assert clip["id"] == "video-001"
    assert (clip["source_in_seconds"], clip["source_out_seconds"]) == (0.4, 3.2)
    assert result["timeline_hash"] != _delta_for(timeline, {"op": "noop"})["base_timeline_hash"]


def test_apply_delta_split_creates_child_ids_and_preserves_track_order() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    timeline["tracks"][3]["clips"][0].update({"start_seconds": 0.1, "end_seconds": 0.8})
    timeline["tracks"][4]["clips"][0].update({"start_seconds": 0.1, "end_seconds": 0.8})
    result = apply_delta(
        timeline,
        _delta_for(timeline, {
            "op": "split_clip", "track_id": "video-main", "clip_id": "video-001",
            "at_seconds": 1.0,
        }),
        asset_catalogue=_catalogue_for(timeline),
    )
    clips = result["timeline"]["tracks"][0]["clips"]

    assert [clip["id"] for clip in clips] == ["video-001", "video-001-split-1"]
    assert clips[0]["source_out_seconds"] == 1.0
    assert clips[1]["source_in_seconds"] == 1.0
    assert clips[1]["start_seconds"] == 1.0
    assert clips[1]["fact_scope"] == clips[0]["fact_scope"]


def test_apply_delta_non_ripple_move_only_changes_named_video_track() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    untouched = {
        track["id"]: deepcopy(track["clips"])
        for track in timeline["tracks"] if track["id"] != "video-main"
    }
    result = apply_delta(timeline, _delta_for(timeline, {
        "op": "move_clip", "track_id": "video-main", "clip_id": "video-001",
        "start_seconds": 0.25,
    }))

    assert result["timeline"]["tracks"][0]["clips"][0]["start_seconds"] == 0.25
    for track in result["timeline"]["tracks"][1:]:
        assert track["clips"] == untouched[track["id"]]


def test_apply_delta_replace_clip_requires_catalogued_same_scope_asset() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    replacement = deepcopy(catalogue["assets"][0])
    replacement.update({"asset_id": "asset-server-video-002", "source_sha256": "b" * 64})
    catalogue["assets"].append(replacement)
    catalogue = _rehash_catalogue(catalogue)
    result = apply_delta(
        timeline,
        _delta_for(timeline, {
            "op": "replace_clip", "track_id": "video-main", "clip_id": "video-001",
            "asset_id": "asset-server-video-002", "source_sha256": "b" * 64,
            "source_in_seconds": 1.0, "source_out_seconds": 4.2,
        }),
        asset_catalogue=catalogue,
    )
    clip = result["timeline"]["tracks"][0]["clips"][0]
    assert clip["id"] == "video-001"
    assert clip["asset_id"] == "asset-server-video-002"
    assert clip["source_sha256"] == "b" * 64
    assert clip["fact_scope"] == timeline["tracks"][0]["clips"][0]["fact_scope"]


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "set_caption_timing", "track_id": "subtitle-main", "clip_id": "subtitle-001", "start_seconds": 1.1, "end_seconds": 2.2},
        {"op": "set_gain", "track_id": "music-main", "clip_id": "music-001", "gain_db": -8.0},
        {"op": "set_fade", "track_id": "music-main", "clip_id": "music-001", "fade_in_seconds": 0.25, "fade_out_seconds": 0.4},
    ],
)
def test_apply_delta_updates_caption_and_bgm_controls(operation: dict) -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    result = apply_delta(timeline, _delta_for(timeline, operation))
    track = next(item for item in result["timeline"]["tracks"] if item["id"] == operation["track_id"])
    clip = next(item for item in track["clips"] if item["id"] == operation["clip_id"])
    for key, value in operation.items():
        if key not in {"op", "track_id", "clip_id"}:
            assert clip[key] == value


def test_apply_delta_replaces_narration_asset_and_hash() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    catalogue["assets"].extend([
        {"asset_id": "asset-server-narration-002", "candidate_id": "candidate-001", "project_id": "project-001", "source_sha256": "b" * 64, "media_kind": "audio", "role": "narration"},
    ])
    catalogue = _rehash_catalogue(catalogue)
    result = apply_delta(
        timeline,
        _delta_for(timeline, {
            "op": "replace_narration", "track_id": "narration-main", "clip_id": "narration-001",
            "asset_id": "asset-server-narration-002", "source_sha256": "b" * 64,
        }),
        asset_catalogue=catalogue,
    )
    clip = result["timeline"]["tracks"][1]["clips"][0]
    assert clip["asset_id"] == "asset-server-narration-002"
    assert clip["source_sha256"] == "b" * 64


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({"op": "replace_clip", "track_id": "video-main", "clip_id": "video-001", "asset_id": "forged", "source_sha256": HASH, "source_in_seconds": 0, "source_out_seconds": 1}, "asset_not_approved"),
        ({"op": "replace_clip", "track_id": "video-main", "clip_id": "video-001", "asset_id": "cross-candidate", "source_sha256": HASH, "source_in_seconds": 0, "source_out_seconds": 1}, "asset_scope_violation"),
        ({"op": "trim_clip", "track_id": "video-main", "clip_id": "video-001", "source_in_seconds": 0, "source_out_seconds": 99}, "source_range_overflow"),
        ({"op": "set_speed", "track_id": "video-main", "clip_id": "video-001", "speed": 0}, "invalid_speed"),
    ],
)
def test_apply_delta_rejects_unsafe_operations(operation: dict, message: str) -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    catalogue["assets"].append({
        "asset_id": "cross-candidate", "candidate_id": "other-candidate", "project_id": "project-001",
        "source_sha256": HASH, "source_class": "owned_source", "valid_range": {"start_seconds": 0, "end_seconds": 3},
        "fact_scope": deepcopy(timeline["tracks"][0]["clips"][0]["fact_scope"]),
    })
    catalogue = _rehash_catalogue(catalogue)
    with pytest.raises(EditorialDeltaError, match=message):
        apply_delta(timeline, _delta_for(timeline, operation), asset_catalogue=catalogue)


def test_apply_delta_rejects_same_claim_different_visual_requirement() -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    alternate = deepcopy(catalogue["assets"][0])
    alternate.update({"asset_id": "asset-different-requirement", "visual_requirement_id": "visual-dry-result"})
    alternate["fact_scope"]["visual_requirement_id"] = "visual-dry-result"
    catalogue["assets"].append(alternate)
    catalogue = _rehash_catalogue(catalogue)
    operation = {"op": "replace_clip", "track_id": "video-main", "clip_id": "video-001", "asset_id": "asset-different-requirement", "source_sha256": HASH, "source_in_seconds": 0, "source_out_seconds": 1}

    with pytest.raises(EditorialDeltaError, match="fact_scope_violation"):
        apply_delta(timeline, _delta_for(timeline, operation), asset_catalogue=catalogue)


def test_apply_delta_rejects_replacement_with_different_fact_scope() -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    alternate = deepcopy(catalogue["assets"][0])
    alternate.update({"asset_id": "asset-different-fact", "claim_ids": ["claim-softness"]})
    alternate["fact_scope"].update({
        "claim_ids": ["claim-softness"], "shot_id": "shot-softness",
    })
    catalogue["assets"].append(alternate)
    catalogue = _rehash_catalogue(catalogue)
    operation = {"op": "replace_clip", "track_id": "video-main", "clip_id": "video-001", "asset_id": "asset-different-fact", "source_sha256": HASH, "source_in_seconds": 0, "source_out_seconds": 1}

    with pytest.raises(EditorialDeltaError) as rejected:
        apply_delta(timeline, _delta_for(timeline, operation), asset_catalogue=catalogue)

    assert rejected.value.code == "fact_scope_violation"
    assert rejected.value.details["asset_id"] == "asset-different-fact"


def test_apply_delta_rejects_overlapping_primary_video_clips() -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    second = deepcopy(timeline["tracks"][0]["clips"][0])
    second.update({"id": "video-002", "start_seconds": 4.0})
    timeline["tracks"][0]["clips"].append(second)
    operation = {"op": "move_clip", "track_id": "video-main", "clip_id": "video-002", "start_seconds": 1.0}

    with pytest.raises(EditorialDeltaError, match="overlapping_primary_clips"):
        apply_delta(timeline, _delta_for(timeline, operation))


def test_apply_delta_supports_trim_then_remove_sequence() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    timeline["tracks"][3]["clips"] = []
    timeline["tracks"][4]["clips"] = []
    delta = _delta_for(timeline, {
        "op": "trim_clip", "track_id": "video-main", "clip_id": "video-001",
        "source_in_seconds": 0.4, "source_out_seconds": 3.2,
    })
    delta["operations"].append({"op": "remove_clip", "track_id": "video-main", "clip_id": "video-001"})
    result = apply_delta(timeline, delta, asset_catalogue=_catalogue_for(timeline))

    assert result["timeline"]["tracks"][0]["clips"] == []


def test_apply_delta_supports_split_then_remove_child_sequence() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    timeline["tracks"][3]["clips"][0].update({"start_seconds": 0.1, "end_seconds": 0.8})
    timeline["tracks"][4]["clips"][0].update({"start_seconds": 0.1, "end_seconds": 0.8})
    delta = _delta_for(timeline, {
        "op": "split_clip", "track_id": "video-main", "clip_id": "video-001",
        "at_seconds": 1.0,
    })
    delta["operations"].append({"op": "remove_clip", "track_id": "video-main", "clip_id": "video-001-split-1"})
    result = apply_delta(timeline, delta, asset_catalogue=_catalogue_for(timeline))

    clips = result["timeline"]["tracks"][0]["clips"]
    assert len(clips) == 1
    assert clips[0]["source_out_seconds"] == 1.0


@pytest.mark.parametrize(
    ("operation", "field"),
    [
        ({"op": "move_clip", "track_id": "video-main", "clip_id": "video-001", "start_seconds": float("nan")}, "start_seconds"),
        ({"op": "move_audio", "track_id": "narration-main", "clip_id": "narration-001", "start_seconds": float("inf")}, "start_seconds"),
        ({"op": "set_gain", "track_id": "music-main", "clip_id": "music-001", "gain_db": float("nan")}, "gain_db"),
        ({"op": "set_fade", "track_id": "music-main", "clip_id": "music-001", "fade_in_seconds": float("inf")}, "fade_in_seconds"),
        ({"op": "set_caption_timing", "track_id": "subtitle-main", "clip_id": "subtitle-001", "start_seconds": float("nan"), "end_seconds": 2.0}, "start_seconds"),
        ({"op": "set_text_timing", "track_id": "text-main", "clip_id": "text-001", "start_seconds": 0.0, "end_seconds": float("inf")}, "end_seconds"),
    ],
)
def test_apply_delta_rejects_non_finite_changed_numbers(operation: dict, field: str) -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    with pytest.raises(EditorialDeltaError, match="invalid_numeric"):
        apply_delta(_timeline(), _delta_for(_timeline(), operation), asset_catalogue=_catalogue_for(_timeline()))


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "trim_clip", "track_id": "video-main", "clip_id": "video-001", "source_out_seconds": 2.0},
        {"op": "move_clip", "track_id": "video-main", "clip_id": "video-001"},
        {"op": "set_caption_timing", "track_id": "subtitle-main", "clip_id": "subtitle-001", "start_seconds": 1.0},
    ],
)
def test_apply_delta_malformed_numeric_fields_are_structured_errors(operation: dict) -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    with pytest.raises(EditorialDeltaError, match="invalid_numeric"):
        apply_delta(_timeline(), _delta_for(_timeline(), operation), asset_catalogue=_catalogue_for(_timeline()))


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "set_caption_timing", "track_id": "subtitle-main", "clip_id": "subtitle-001", "start_seconds": 2.5, "end_seconds": 3.5},
        {"op": "set_text_timing", "track_id": "text-main", "clip_id": "text-001", "start_seconds": 2.5, "end_seconds": 3.5},
    ],
)
def test_apply_delta_claim_bound_text_timing_stays_inside_video_clip(operation: dict) -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    with pytest.raises(EditorialDeltaError, match="fact_bound_timing_violation"):
        apply_delta(_timeline(), _delta_for(_timeline(), operation), asset_catalogue=_catalogue_for(_timeline()))


def test_apply_delta_rejects_split_id_collision_across_timeline() -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    other_track = timeline["tracks"][3]
    other_track["clips"].append({"id": "video-001-split-1", "text": "collision", "start_seconds": 0.0, "end_seconds": 1.0, "style_token": "taobao_selling_point_v1", "position": "top_center", "claim_ids": ["claim-absorb-visible"]})
    with pytest.raises(EditorialDeltaError, match="duplicate_clip_id"):
        apply_delta(timeline, _delta_for(timeline, {"op": "split_clip", "track_id": "video-main", "clip_id": "video-001", "at_seconds": 1.0}), asset_catalogue=_catalogue_for(timeline))


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        ({"op": "replace_narration", "track_id": "narration-main", "clip_id": "narration-001", "asset_id": "wrong-kind", "source_sha256": HASH}, "asset_media_kind_violation"),
        ({"op": "replace_music", "track_id": "music-main", "clip_id": "music-001", "asset_id": "wrong-role", "source_sha256": HASH}, "asset_role_violation"),
    ],
)
def test_apply_delta_audio_replacement_requires_catalogue_media_kind_and_role(operation: dict, code: str) -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    catalogue = _catalogue_for(_timeline())
    catalogue["assets"].append({
        "asset_id": operation["asset_id"], "candidate_id": "candidate-001",
        "project_id": "project-001", "source_sha256": HASH,
        "media_kind": "video" if operation["op"] == "replace_narration" else "audio",
        "role": "music" if operation["op"] == "replace_narration" else "narration",
    })
    catalogue = _rehash_catalogue(catalogue)
    with pytest.raises(EditorialDeltaError, match=code):
        apply_delta(_timeline(), _delta_for(_timeline(), operation), asset_catalogue=catalogue)


@pytest.mark.parametrize("mutation", [
    lambda asset: asset.update({"claim_ids": ["claim-other"]}),
    lambda asset: asset.update({"visual_requirement_id": "visual-other"}),
    lambda asset: asset["fact_scope"].update({"claim_ids": ["claim-other"]}),
])
def test_apply_delta_replace_compares_all_fact_scope_fields(mutation) -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    replacement = deepcopy(catalogue["assets"][0])
    replacement["asset_id"] = "asset-fact-mismatch"
    mutation(replacement)
    catalogue["assets"].append(replacement)
    catalogue = _rehash_catalogue(catalogue)
    operation = {"op": "replace_clip", "track_id": "video-main", "clip_id": "video-001", "asset_id": "asset-fact-mismatch", "source_sha256": HASH, "source_in_seconds": 0, "source_out_seconds": 1}
    with pytest.raises(EditorialDeltaError, match="fact_scope_violation"):
        apply_delta(timeline, _delta_for(timeline, operation), asset_catalogue=catalogue)


def test_apply_delta_rejects_forged_or_stale_catalogue_hash_and_binding() -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    catalogue["assets"].append(deepcopy(catalogue["assets"][0]) | {"asset_id": "forged-injected"})
    with pytest.raises(EditorialDeltaError, match="catalogue_hash_mismatch"):
        apply_delta(timeline, _delta_for(timeline, {"op": "replace_clip", "track_id": "video-main", "clip_id": "video-001", "asset_id": "forged-injected", "source_sha256": HASH, "source_in_seconds": 0, "source_out_seconds": 1}), asset_catalogue=catalogue)

    stale = _catalogue_for(timeline)
    stale["timeline_hash"] = "f" * 64
    stale = _rehash_catalogue(stale)
    with pytest.raises(EditorialDeltaError, match="catalogue_binding_mismatch"):
        apply_delta(timeline, _delta_for(timeline, {"op": "replace_clip", "track_id": "video-main", "clip_id": "video-001", "asset_id": timeline["tracks"][0]["clips"][0]["asset_id"], "source_sha256": HASH, "source_in_seconds": 0, "source_out_seconds": 1}), asset_catalogue=stale)


def test_apply_delta_rejects_video_move_that_orphans_existing_claim_text() -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    operation = {"op": "move_clip", "track_id": "video-main", "clip_id": "video-001", "start_seconds": 1.25}
    with pytest.raises(EditorialDeltaError, match="fact_bound_timing_violation"):
        apply_delta(timeline, _delta_for(timeline, operation))


def test_apply_delta_allows_video_move_when_existing_claim_text_remains_covered() -> None:
    from lib.editorial_timeline import apply_delta

    timeline = _timeline()
    operation = {"op": "move_clip", "track_id": "video-main", "clip_id": "video-001", "start_seconds": 0.25}
    result = apply_delta(timeline, _delta_for(timeline, operation))
    assert result["timeline"]["tracks"][0]["clips"][0]["start_seconds"] == 0.25


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_apply_delta_rejects_nonfinite_catalogue_valid_range(bad_value: float) -> None:
    from lib.editorial_timeline import EditorialDeltaError, apply_delta

    timeline = _timeline()
    catalogue = _catalogue_for(timeline)
    catalogue["assets"][0]["valid_range"]["end_seconds"] = bad_value
    catalogue = _rehash_catalogue(catalogue)
    operation = {"op": "trim_clip", "track_id": "video-main", "clip_id": "video-001", "source_in_seconds": 0.4, "source_out_seconds": 2.6}
    with pytest.raises(EditorialDeltaError, match="invalid_numeric"):
        apply_delta(timeline, _delta_for(timeline, operation), asset_catalogue=catalogue)

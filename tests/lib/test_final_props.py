from __future__ import annotations

import pytest

from lib.final_props import FinalPropsError, validate_final_props


@pytest.fixture
def valid_props() -> dict:
    return {
        "compositionId": "Test",
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "durationInFrames": 69,
        "footage": {"main": "footage/main.mp4"},
        "scenes": [{
            "id": "s1", "assetId": "a1", "footageKey": "main",
            "fromFrame": 0, "toFrameExclusive": 69, "durationInFrames": 69,
            "sourceInSeconds": 0.4, "sourceOutSeconds": 2.7,
            "playbackRate": 1.0, "playbackMode": "normal",
        }],
        "captions": [], "audio": {"mix": "audio/mix.wav"},
    }


def test_normal_scene_obeys_half_open_and_source_duration_math(valid_props):
    validate_final_props(valid_props)


def test_boundary_or_source_math_drift_is_rejected(valid_props):
    valid_props["scenes"][0]["durationInFrames"] += 2
    with pytest.raises(FinalPropsError):
        validate_final_props(valid_props)


def test_gap_overlap_and_caption_overflow_are_rejected(valid_props):
    valid_props["scenes"][0]["fromFrame"] = 1
    with pytest.raises(FinalPropsError):
        validate_final_props(valid_props)
    valid_props["scenes"][0]["fromFrame"] = 0
    valid_props["captions"] = [{"text": "x", "startMs": 0, "endMs": 3000}]
    with pytest.raises(FinalPropsError):
        validate_final_props(valid_props)


def test_hold_scene_is_explicit(valid_props):
    scene = valid_props["scenes"][0]
    scene.pop("sourceInSeconds")
    scene.pop("sourceOutSeconds")
    scene["playbackMode"] = "hold"
    validate_final_props(valid_props)


def test_opening_uses_only_bound_external_mix_in_canonical_props(valid_props):
    valid_props["durationInFrames"] = 90
    valid_props["scenes"][0].update(toFrameExclusive=90, durationInFrames=90, sourceOutSeconds=3.4)
    valid_props["opening"] = {"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5}
    valid_props.pop("audio")
    valid_props["finalMix"] = {"path": "assets/audio/mix.wav", "sha256": "a" * 64, "mode": "external_mux"}
    validate_final_props(valid_props)
    valid_props["audio"] = {"mix": "other.wav"}
    with pytest.raises(FinalPropsError, match="one external"):
        validate_final_props(valid_props)


def test_opening_final_props_schema_accepts_single_mix_and_rejects_duplicate_audio(valid_props):
    valid_props["durationInFrames"] = 90
    valid_props["scenes"][0].update(toFrameExclusive=90, durationInFrames=90, sourceOutSeconds=3.4)
    valid_props["scenes"][0].update(sourceFps=24, framing={"source": {"width": 960, "height": 960},
        "viewport": {"x": 0, "y": 350, "width": 1080, "height": 1080}, "fit": "contain",
        "position": {"x": .5, "y": .5}, "actionCoverage": "whole_shot_envelope", "actionRegions": [{"x": 0, "y": 0, "width": 960, "height": 960}]})
    from schemas.artifacts import validate_artifact
    valid_props.update(version="1.0", project_id="test", created_at="2026-09-29T00:00:00Z", producer="test",
        input_hashes={}, semantic_sha256="a" * 64, artifact_sha256="b" * 64,
        opening={"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5},
        finalMix={"path": "assets/audio/mix.wav", "sha256": "a" * 64, "mode": "external_mux"})
    valid_props.pop("audio")
    validate_artifact("final_props", valid_props)
    valid_props["scenes"][0]["framing"]["fit"] = "guess"
    with pytest.raises(Exception): validate_artifact("final_props", valid_props)
    valid_props["scenes"][0]["framing"]["fit"] = "contain"
    valid_props["audio"] = {"mix": "other.wav"}
    with pytest.raises(Exception): validate_artifact("final_props", valid_props)

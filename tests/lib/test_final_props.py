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

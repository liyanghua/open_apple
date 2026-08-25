from __future__ import annotations

import pytest

from lib.sample_payload import build_sample_render_payload


def test_sample_payload_derives_sequential_cuts_without_losing_source_trim() -> None:
    result = build_sample_render_payload({
        "final_props": {
            "fps": 30,
            "durationInFrames": 300,
            "scenes": [
                {
                    "id": "shot-01", "assetId": "proxy-01", "footageKey": "opening",
                    "fromFrame": 0, "toFrameExclusive": 69,
                    "sourceInSeconds": 12.5, "sourceOutSeconds": 14.8,
                },
                {
                    "id": "shot-02", "assetId": "proxy-02", "footageKey": "proof",
                    "fromFrame": 69, "toFrameExclusive": 141,
                    "sourceInSeconds": 4.0, "sourceOutSeconds": 6.4,
                },
            ],
            "footage": {"opening": "assets/video/opening.mp4", "proof": "assets/video/proof.mp4"},
            "captions": [{"text": "透明也能保护", "startMs": 0, "endMs": 2300}],
            "audio": {"narration": {"src": "assets/audio/mix.mp3"}},
        },
        "asset_manifest": {
            "assets": [
                {"id": "proxy-01", "path": "assets/video/opening.mp4", "duration_seconds": 20},
                {"id": "proxy-02", "path": "assets/video/proof.mp4", "duration_seconds": 20},
            ],
        },
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
    })

    assert result["cuts"] == [
        {
            "id": "shot-01", "source": "assets/video/opening.mp4",
            "in_seconds": 0.0, "out_seconds": 2.3,
            "source_in_seconds": 12.5, "source_out_seconds": 14.8,
        },
        {
            "id": "shot-02", "source": "assets/video/proof.mp4",
            "in_seconds": 2.3, "out_seconds": 4.7,
            "source_in_seconds": 4.0, "source_out_seconds": 6.4,
        },
    ]
    assert result["captions"] == [{"word": "透明也能保护", "startMs": 0, "endMs": 2300}]
    assert result["audio"] == {"narration": {"src": "assets/audio/mix.mp3"}}


def test_sample_payload_rejects_overlap_and_source_shortfall() -> None:
    base = {
        "final_props": {
            "fps": 30,
            "durationInFrames": 300,
            "scenes": [
                {"id": "shot-01", "assetId": "proxy-01", "fromFrame": 0, "toFrameExclusive": 90,
                 "sourceInSeconds": 6.0, "sourceOutSeconds": 9.0},
                {"id": "shot-02", "assetId": "proxy-02", "fromFrame": 60, "toFrameExclusive": 120,
                 "sourceInSeconds": 0.0, "sourceOutSeconds": 2.0},
            ],
        },
        "asset_manifest": {"assets": [
            {"id": "proxy-01", "path": "a.mp4", "source_duration_seconds": 10},
            {"id": "proxy-02", "path": "b.mp4", "duration_seconds": 10},
        ]},
    }

    with pytest.raises(ValueError, match="overlap"):
        build_sample_render_payload(base)


def test_sample_payload_prefers_derived_mix_assets_over_raw_music() -> None:
    # final_props.audio.mix.music.path points at the raw SUNO source
    # (assets/music/bgm.mp3), but the approved render muxes the derived
    # bgm-ducked.mp3 from asset_manifest. A reuse-assets render must reuse the
    # approved mix, so music.src must resolve to the derived asset and stay at
    # natural volume (already ducked), not the raw source at 0.1.
    result = build_sample_render_payload({
        "final_props": {
            "fps": 30,
            "durationInFrames": 300,
            "scenes": [
                {"id": "shot-01", "assetId": "proxy-01", "footageKey": "opening",
                 "fromFrame": 0, "toFrameExclusive": 69,
                 "sourceInSeconds": 0.0, "sourceOutSeconds": 2.3},
            ],
            "footage": {"opening": "assets/video/opening.mp4"},
            "audio": {
                "mix": {
                    "narration": {"path": "assets/audio/narration-mix.mp3", "provider": "doubao"},
                    "music": {"path": "assets/music/bgm.mp3", "provider": "suno"},
                }
            },
        },
        "asset_manifest": {
            "assets": [
                {"id": "proxy-01", "path": "assets/video/opening.mp4", "duration_seconds": 20},
                {"id": "narration-mix", "type": "audio", "path": "assets/audio/narration-mix.mp3"},
                {"id": "bgm-ducked", "type": "audio", "path": "assets/audio/bgm-ducked.mp3"},
            ],
        },
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
    })

    assert result["audio"] == {
        "narration": {"src": "assets/audio/narration-mix.mp3"},
        "music": {"src": "assets/audio/bgm-ducked.mp3"},
    }


def test_sample_payload_clamps_source_seek_to_scene_length_proxy() -> None:
    # sourceInSeconds here is recorded in ORIGINAL-source coordinates (1.2s),
    # but the render asset is a scene-length proxy (duration == timeline, 2.4s).
    # Seeking the proxy to 1.2s and playing 2.4s would run past its end, so the
    # source seek must be clamped to the proxy's valid range (0 here).
    result = build_sample_render_payload({
        "final_props": {
            "fps": 30,
            "durationInFrames": 300,
            "scenes": [
                {"id": "shot-01", "assetId": "proxy-02", "footageKey": "proof",
                 "fromFrame": 0, "toFrameExclusive": 72,
                 "sourceInSeconds": 1.2, "sourceOutSeconds": 3.6},
            ],
            "footage": {"proof": "assets/video/shot-02-proxy.mp4"},
        },
        "asset_manifest": {"assets": [
            {"id": "proxy-02", "path": "assets/video/shot-02-proxy.mp4", "duration_seconds": 2.4},
        ]},
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
    })

    assert result["cuts"][0]["source_in_seconds"] == 0.0
    assert result["cuts"][0]["source_out_seconds"] == 2.4


def test_sample_payload_normalizes_captions_to_word_shape() -> None:
    # Canonical final_props.captions are phrase entries {text, startMs, endMs};
    # the Explainer's CaptionOverlay renders WordCaption [{word, startMs, endMs}].
    # A `text`-shaped caption must be normalized so the render never emits a
    # literal "undefined", and each phrase is shown on its own page.
    result = build_sample_render_payload({
        "final_props": {
            "fps": 30,
            "durationInFrames": 300,
            "scenes": [
                {"id": "shot-01", "assetId": "proxy-01", "fromFrame": 0,
                 "toFrameExclusive": 69, "sourceInSeconds": 0.0, "sourceOutSeconds": 2.3},
            ],
            "captions": [
                {"text": "一铺即护", "startMs": 0, "endMs": 2300},
                {"text": "贴合桌角", "startMs": 2300, "endMs": 4700},
            ],
        },
        "asset_manifest": {"assets": [
            {"id": "proxy-01", "path": "a.mp4", "duration_seconds": 2.3},
        ]},
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
    })

    assert result["captions"] == [
        {"word": "一铺即护", "startMs": 0, "endMs": 2300},
        {"word": "贴合桌角", "startMs": 2300, "endMs": 4700},
    ]
    assert result["captionWordsPerPage"] == 1


def test_caption_style_passthrough_and_recipe_from_scene_plan() -> None:
    from lib.sample_payload import build_sample_render_payload
    from lib.caption_style import to_overlay_spec

    payload = build_sample_render_payload({
        "final_props": {
            "fps": 30, "durationInFrames": 300,
            "scenes": [
                {"id": "shot-01", "assetId": "proxy-01", "fromFrame": 0,
                 "toFrameExclusive": 69, "sourceInSeconds": 0.0, "sourceOutSeconds": 2.3},
            ],
        },
        "asset_manifest": {"assets": [
            {"id": "proxy-01", "path": "a.mp4", "duration_seconds": 2.3},
        ]},
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
        "scene_plan": {"scenes": [{"id": "shot-01", "caption_recipe_intent": "hook"}]},
        "captionStyle": to_overlay_spec({
            "font_family": "Long Cang", "vertical": True,
            "stroke": {"color": "#000000", "width_px": 8},
        }),
    })
    assert payload["captionStyle"]["fontFamily"] == "Long Cang"
    assert payload["captionStyle"]["vertical"] is True
    assert payload["captionStyle"]["strokeWidthPx"] == 8
    assert payload["captionRecipes"]["shot-01"]["recipe_id"] == "keyword-highlight"

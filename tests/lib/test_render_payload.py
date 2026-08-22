"""render_payload assembler 测试（固化债：render_payload assembler）。"""

from __future__ import annotations

from lib.caption_style import build_caption_style_fingerprint
from lib.render_payload import build_render_payload


def test_payload_starts_from_final_props():
    payload = build_render_payload(final_props={"fps": 30, "scenes": []})
    assert payload == {"fps": 30, "scenes": []}


def test_caption_style_derived_from_fingerprint():
    research = {
        "reference_shots": [
            {"values": {"overlay_text": "透明桌垫", "evidence_frames": [], "effect_treatment": "硬切"}},
        ],
        "source_segments": [],
    }
    fingerprint = build_caption_style_fingerprint("p", research)  # needs_review
    payload = build_render_payload(
        final_props={"fps": 30},
        caption_fingerprint=fingerprint,
    )
    assert payload["captionStyle"]["bottomOffsetPx"] == 120
    assert payload["captionStyle"]["position"] == "bottom"
    assert payload["captionStyle"]["entranceAnimation"] == "none"  # 硬切


def test_not_applicable_fingerprint_omits_caption_style():
    fingerprint = build_caption_style_fingerprint("p", None)  # not_applicable
    payload = build_render_payload(
        final_props={"fps": 30},
        caption_fingerprint=fingerprint,
    )
    assert "captionStyle" not in payload


def test_audio_mix_and_words_per_page_passthrough():
    payload = build_render_payload(
        final_props={"fps": 30, "audio": {"source": "none"}},
        audio_mix={"gain": 0, "lufs": -16},
        edit_decisions={"caption_words_per_page": 1},
    )
    assert payload["audio"]["mix"] == {"gain": 0, "lufs": -16}
    assert payload["captionWordsPerPage"] == 1

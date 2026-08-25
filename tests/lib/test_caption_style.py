"""Unit tests for lib.caption_style (竖排楷书花字 profile，非全局默认)."""

from __future__ import annotations

from lib.caption_style import DEFAULT_STYLE, CAPTION_PROFILES, to_overlay_spec


def test_generic_default_is_neutral_not_calligraphy():
    s = to_overlay_spec(DEFAULT_STYLE)
    assert s["position"] == "bottom"  # 默认中下，不是左上花字
    assert s["vertical"] is False
    assert s["fontFamily"] != "Ma Shan Zheng"


def test_calligraphy_profile_is_vertical_white_topleft():
    s = to_overlay_spec(CAPTION_PROFILES["calligraphy"])
    assert s["fontFamily"] == "Ma Shan Zheng"
    assert s["fillColor"] == "#FFFFFF"
    assert s["strokeWidthPx"] == 0  # 纯白无黑描边
    assert s["vertical"] is True
    assert s["position"] == "topleft"
    assert s["fontSize"] == 104


def test_build_fingerprint_accepts_profile():
    from lib.caption_style import build_caption_style_fingerprint

    research = {"reference_shots": [
        {"values": {"overlay_text": "贴合桌面", "evidence_frames": [], "effect_treatment": "硬切"}},
    ], "source_segments": []}
    fp = build_caption_style_fingerprint("p", research, profile="calligraphy")
    assert fp["profile"] == "calligraphy"
    assert fp["style"]["vertical"] is True
    # 默认 generic 不受影响
    fp_generic = build_caption_style_fingerprint("p", research)
    assert fp_generic["profile"] == "generic"
    assert fp_generic["style"]["vertical"] is False


def test_unknown_profile_raises():
    from lib.caption_style import build_caption_style_fingerprint

    try:
        build_caption_style_fingerprint("p", None, profile="nope")
        assert False, "should raise"
    except ValueError:
        pass

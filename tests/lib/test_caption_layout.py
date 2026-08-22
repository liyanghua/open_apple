import json
from pathlib import Path

from lib.caption_layout import (
    boxes_in_social_safe_zone,
    caption_box_for_cue,
    fit_cjk_font_size,
    is_inside_safe_zone,
    layout_captions,
    strip_trailing_punctuation,
)


FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "caption_layout" / "social_v1_cases.json")
    .read_text(encoding="utf-8")
)


def test_cjk_layout_stays_inside_social_safe_zone():
    boxes = layout_captions([{"text": "透明桌垫让日常打理更轻松"}])
    assert boxes_in_social_safe_zone(boxes)
    assert boxes[0]["line_count"] >= 1


def test_caption_layout_matches_shared_social_v1_fixture():
    for case in FIXTURE["strip_cases"]:
        assert strip_trailing_punctuation(case["input"]) == case["expected"]

    for case in FIXTURE["layout_cases"]:
        box = caption_box_for_cue({"text": case["text"]})
        expected = case["expected"]
        assert fit_cjk_font_size(case["text"]) == expected["font_size"]
        assert {
            "font_size": box["font_size"],
            "line_count": box["line_count"],
            "left": box["left"],
            "right": box["right"],
            "top": box["top"],
            "bottom": box["bottom"],
        } == expected
        assert is_inside_safe_zone(box)


def test_scale_emphasis_that_crosses_safe_zone_is_rejected():
    term = "透明桌垫透明桌垫透明桌垫透明桌垫透明"
    box = caption_box_for_cue(
        {"text": term},
        font_min=52,
        font_max=52,
        emphasis_rules=[{"term": term, "color": "#D9A441", "effect": "scale"}],
    )
    assert box["emphasis_boxes"]
    assert not is_inside_safe_zone(box["emphasis_boxes"][0])


def test_requested_width_is_clamped_to_the_social_v1_profile():
    box = caption_box_for_cue(
        {"text": "透明桌垫守住餐桌日常油污刮擦也能轻松打理"},
        max_width=936,
    )

    assert box["width"] <= 864
    assert is_inside_safe_zone(box)


def test_caption_box_respects_declared_bottom_offset():
    """评审 #9b：bottom_margin_px 覆盖平台安全区，盒底边 = height - offset。"""
    box = caption_box_for_cue({"text": "透明桌垫"}, bottom_margin_px=120)
    assert box["bottom"] == 1920 - 120
    default_box = caption_box_for_cue({"text": "透明桌垫"})
    assert default_box["bottom"] == 1920 - 300


def test_safe_zone_check_uses_declared_bottom_offset():
    """评审 #9b：同一盒子在平台默认区（300）越界、在声明偏移（120）下通过。"""
    box = {
        "text": "透明桌垫",
        "left": 100, "right": 964, "top": 1740, "bottom": 1800,
        "width": 864, "height": 60, "line_count": 1,
    }
    assert not boxes_in_social_safe_zone([box])
    assert boxes_in_social_safe_zone([box], bottom_margin_px=120)


def test_layout_captions_threads_bottom_margin():
    boxes = layout_captions([{"text": "透明桌垫"}], bottom_margin=120)
    assert boxes[0]["bottom"] == 1920 - 120

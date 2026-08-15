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

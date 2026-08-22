"""Deterministic social-v1 CJK caption layout used by QA and compositions."""

from __future__ import annotations

import math
import re
from typing import Any


SAFE_ZONE_PROFILES = {
    name: {
        "left": 72, "right": 72, "top": 120, "bottom": 300,
        "max_width": 864, "max_lines": 2, "line_height": 1.24,
    }
    for name in ("douyin_9_16", "wechat_9_16", "xiaohongshu_9_16")
}

_TRAILING_PUNCTUATION = re.compile(r"[\s，。！？；：、,.!?;:…]+$")


def strip_trailing_punctuation(text: str) -> str:
    return _TRAILING_PUNCTUATION.sub("", str(text)).rstrip()


def _character_units(text: str) -> float:
    units = 0.0
    for char in text:
        code = ord(char)
        if char.isspace():
            units += 0.32
        elif (
            0x2E80 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF
            or 0xFF00 <= code <= 0xFFEF
        ):
            units += 1.0
        elif char.isupper() or char.isdigit():
            units += 0.62
        elif char.islower():
            units += 0.56
        else:
            units += 0.5
    return max(units, 1.0)


def fit_cjk_font_size(
    text: str,
    *,
    font_min: int = 44,
    font_max: int = 52,
    max_width: int = 864,
    max_lines: int = 2,
    width_multiplier: float = 1.0,
) -> int:
    if font_min > font_max:
        raise ValueError("font_min must be <= font_max")
    fitted = math.floor(
        (max_width * max_lines) / (_character_units(text) * max(width_multiplier, 0.01))
    )
    return max(font_min, min(font_max, fitted))


def caption_box_for_cue(
    cue: dict[str, Any],
    *,
    width: int = 1080,
    height: int = 1920,
    safe_zone_profile: str = "douyin_9_16",
    font_min: int = 44,
    font_max: int = 52,
    max_width: int = 864,
    strip_punctuation: bool = True,
    emphasis_rules: list[dict[str, Any]] | None = None,
    bottom_margin_px: int | None = None,
) -> dict[str, Any]:
    profile = SAFE_ZONE_PROFILES[safe_zone_profile]
    # 评审 #9b：bottom_margin_px 是渲染偏移的单一数据源（来自
    # caption_style_fingerprint.style.bottom_offset_px）；缺省回退平台安全区。
    bottom_margin = int(bottom_margin_px) if bottom_margin_px is not None else profile["bottom"]
    max_width = max(
        1,
        min(max_width, profile["max_width"], width - profile["left"] - profile["right"]),
    )
    text = str(cue.get("text", "")).strip()
    if strip_punctuation:
        text = strip_trailing_punctuation(text)
    rules = emphasis_rules or []
    scale_multiplier = 1.08 if any(
        rule.get("effect") == "scale" and str(rule.get("term", "")) in text
        for rule in rules
    ) else 1.0
    font_size = fit_cjk_font_size(
        text,
        font_min=font_min,
        font_max=font_max,
        max_width=max_width,
        max_lines=profile["max_lines"],
        width_multiplier=scale_multiplier,
    )
    text_width = round(_character_units(text) * font_size)
    line_count = max(1, math.ceil(text_width / max_width))
    box_width = min(max_width, text_width) if line_count == 1 else max_width
    left = round((width - box_width) / 2)
    bottom = height - bottom_margin
    box_height = round(font_size * profile["line_height"] * line_count)
    top = bottom - box_height

    emphasis_boxes = []
    for rule in rules:
        term = str(rule.get("term", ""))
        if not term or term not in text:
            continue
        multiplier = 1.08 if rule.get("effect") == "scale" else 1.0
        term_width = round(_character_units(term) * font_size * multiplier)
        term_height = round(font_size * profile["line_height"] * multiplier)
        term_left = round((width - term_width) / 2)
        emphasis_boxes.append({
            "term": term,
            "left": term_left,
            "right": term_left + term_width,
            "top": top,
            "bottom": top + term_height,
            "width": term_width,
            "height": term_height,
            "line_count": 1,
        })

    return {
        "text": text,
        "left": left,
        "right": left + box_width,
        "top": top,
        "bottom": bottom,
        "width": box_width,
        "height": box_height,
        "font_size": font_size,
        "line_count": line_count,
        "line_height": profile["line_height"],
        "emphasis_boxes": emphasis_boxes,
    }


def is_inside_safe_zone(
    box: dict[str, Any],
    *,
    width: int = 1080,
    height: int = 1920,
    safe_zone_profile: str = "douyin_9_16",
    bottom_margin_px: int | None = None,
) -> bool:
    profile = SAFE_ZONE_PROFILES[safe_zone_profile]
    bottom_margin = int(bottom_margin_px) if bottom_margin_px is not None else profile["bottom"]
    return (
        box.get("left", -1) >= profile["left"]
        and box.get("right", width + 1) <= width - profile["right"]
        and box.get("top", -1) >= profile["top"]
        and box.get("bottom", height + 1) <= height - bottom_margin
        and box.get("width", width + 1) <= profile["max_width"]
        and box.get("line_count", 1) <= profile["max_lines"]
    )


def layout_captions(
    captions: list[dict[str, Any]],
    *,
    width: int = 1080,
    height: int = 1920,
    font_size: int | None = None,
    side_margin: int = 72,
    bottom_margin: int = 300,
) -> list[dict[str, Any]]:
    max_width = min(864, width - side_margin * 2)
    boxes = []
    for index, caption in enumerate(captions):
        box = caption_box_for_cue(
            caption,
            width=width,
            height=height,
            font_min=font_size or 44,
            font_max=font_size or 52,
            max_width=max_width,
            bottom_margin_px=bottom_margin,
        )
        box["cue_index"] = index
        boxes.append(box)
    return boxes


def boxes_in_social_safe_zone(
    boxes: list[dict[str, Any]],
    *,
    width: int = 1080,
    height: int = 1920,
    bottom_margin_px: int | None = None,
) -> bool:
    return all(
        is_inside_safe_zone(
            box,
            width=width,
            height=height,
            bottom_margin_px=bottom_margin_px,
        )
        for box in boxes
    )

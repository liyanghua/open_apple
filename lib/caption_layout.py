"""Deterministic social-v1 CJK caption layout used by QA and compositions."""

from __future__ import annotations

import math
from typing import Any


def layout_captions(captions: list[dict[str, Any]], *, width: int = 1080, height: int = 1920, font_size: int = 64, side_margin: int = 72, bottom_margin: int = 300) -> list[dict[str, Any]]:
    max_width = width - side_margin * 2
    char_width = font_size
    chars_per_line = max(1, max_width // char_width)
    boxes = []
    for index, caption in enumerate(captions):
        text = str(caption.get("text", "")).strip()
        lines = max(1, math.ceil(len(text) / chars_per_line))
        box_height = lines * round(font_size * 1.25) + 32
        boxes.append({
            "cue_index": index, "text": text, "left": side_margin,
            "right": width - side_margin, "top": height - bottom_margin - box_height,
            "bottom": height - bottom_margin, "font_size": font_size,
            "line_count": lines, "chars_per_line": chars_per_line,
        })
    return boxes


def boxes_in_social_safe_zone(boxes: list[dict[str, Any]], *, width: int = 1080, height: int = 1920) -> bool:
    return all(box["left"] >= 72 and box["right"] <= width - 72 and box["top"] >= 120 and box["bottom"] <= height - 300 for box in boxes)

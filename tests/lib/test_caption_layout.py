from lib.caption_layout import boxes_in_social_safe_zone, layout_captions


def test_cjk_layout_stays_inside_social_safe_zone():
    boxes = layout_captions([{"text": "透明桌垫让日常打理更轻松"}])
    assert boxes_in_social_safe_zone(boxes)
    assert boxes[0]["line_count"] >= 1

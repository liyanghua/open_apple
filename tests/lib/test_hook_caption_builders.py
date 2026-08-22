"""Builder tests for hook_plan and caption_style_fingerprint (P1-1)."""

from __future__ import annotations

import pytest

from lib.caption_style import build_caption_style_fingerprint, to_overlay_spec
from lib.hook_plan import build_hook_plan


def _creative_plan() -> dict:
    return {
        "sections": {
            "content_direction": {
                "title": "内容方向",
                "summary": "用真实动作证明透明保护",
                "rules": ["主信息固定"],
                "evidence_refs": ["research_synthesis:direction-proof-chain"],
            },
        }
    }


def _script() -> dict:
    return {
        "sections": [
            {
                "id": "s01",
                "narration": "桌面想保护，木纹也别遮住。",
                "visual_intent": "桌垫自动铺开落在餐桌上",
                "section_goal": "前两秒交代产品",
            }
        ]
    }


def test_hook_plan_derives_from_creative_plan_and_script():
    plan = build_hook_plan("p-test", creative_control_plan=_creative_plan(), script=_script())

    assert plan["first_audio"] == "桌面想保护，木纹也别遮住。"
    assert plan["first_frame_visual"] == "桌垫自动铺开落在餐桌上"
    assert plan["promise"] == "用真实动作证明透明保护"
    assert "direction-proof-chain" in plan["proof_evidence"]
    assert plan["hook_window_seconds"] == [0.0, 1.5]


def test_hook_plan_overrides_win():
    plan = build_hook_plan(
        "p-test",
        creative_control_plan=_creative_plan(),
        script=_script(),
        overrides={"hook_pattern": "contrast", "hook_window_seconds": [0.0, 2.0]},
    )

    assert plan["hook_pattern"] == "contrast"
    assert plan["hook_window_seconds"] == [0.0, 2.0]


def test_hook_plan_rejects_unknown_pattern():
    with pytest.raises(ValueError):
        build_hook_plan("p-test", overrides={"hook_pattern": "not_a_pattern"})


def test_caption_fingerprint_without_overlay_is_not_applicable():
    fp = build_caption_style_fingerprint("p-test", {"reference_shots": []})

    assert fp["applicability"] == "not_applicable"
    assert fp["source"]["overlay_text_samples"] == []


def test_caption_fingerprint_seeds_from_research():
    breakdown = {
        "reference_shots": [
            {
                "values": {
                    "overlay_text": "贴合桌面",
                    "effect_treatment": "硬切；动作先行",
                    "evidence_frames": ["analysis/reference/keyframes/frame_0000.jpg"],
                },
            }
        ]
    }
    fp = build_caption_style_fingerprint("p-test", breakdown)

    assert fp["applicability"] == "needs_review"
    assert fp["source"]["overlay_text_samples"] == ["贴合桌面"]
    assert fp["source"]["evidence_frames"] == ["analysis/reference/keyframes/frame_0000.jpg"]
    assert fp["style"]["entrance_animation"] == "硬切；动作先行"


def test_caption_fingerprint_overrides_merge():
    breakdown = {"reference_shots": [{"values": {"overlay_text": "贴合桌面"}}]}
    fp = build_caption_style_fingerprint(
        "p-test",
        breakdown,
        overrides={
            "style": {"font_family": "Alibaba PuHuiTi", "size_hierarchy": [52]},
            "binding": {"brand_required_rules": ["白色填充必须保留"]},
        },
    )

    assert fp["style"]["font_family"] == "Alibaba PuHuiTi"
    assert fp["style"]["size_hierarchy"] == [52]
    assert fp["binding"]["brand_required_rules"] == ["白色填充必须保留"]


def test_to_overlay_spec_maps_fingerprint_style():
    style = {
        "font_family": "Noto Sans CJK SC",
        "size_hierarchy": [48, 60],
        "weight": "semibold",
        "fill_color": "#FFFFFF",
        "stroke": {"color": "#000000", "width_px": 3},
        "background_bar": {"color": "rgba(0,0,0,0.6)"},
        "opacity": 0.95,
        "position": "中下 1/3",
        "entrance_animation": "整句淡入",
    }
    spec = to_overlay_spec(style)

    assert spec["fontFamily"] == "Noto Sans CJK SC"
    assert spec["fontSize"] == 48.0
    assert spec["emphasizeFontSize"] == 60.0
    assert spec["fontWeight"] == 600
    assert spec["strokeColor"] == "#000000" and spec["strokeWidthPx"] == 3.0
    assert spec["position"] == "bottom"
    assert spec["entranceAnimation"] == "fade"
    assert spec["opacity"] == 0.95
    assert spec["bottomOffsetPx"] == 120


def test_to_overlay_spec_carries_declared_bottom_offset():
    """评审 #9b：指纹声明的 bottom_offset_px 进入渲染规格。"""
    spec = to_overlay_spec({"bottom_offset_px": 90})
    assert spec["bottomOffsetPx"] == 90.0


def test_to_overlay_spec_handles_minimal_style():
    spec = to_overlay_spec({})

    assert spec["fontSize"] is None
    assert spec["fontWeight"] == 700
    assert spec["position"] == "bottom"
    assert spec["entranceAnimation"] == "none"
    assert spec["backgroundColor"] is None
    assert spec["bottomOffsetPx"] == 120

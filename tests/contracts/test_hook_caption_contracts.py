"""Contract tests for hook_plan and caption_style_fingerprint (Design_Review P1-1)."""

from __future__ import annotations

import pytest

from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


def _hook(**overrides):
    base = {
        "version": "1.0",
        "project_id": "p-test",
        "created_at": "2026-08-22T00:00:00+00:00",
        "hook_window_seconds": [0.0, 1.5],
        "first_frame_visual": "桌垫自动铺开，木纹可见",
        "first_audio": "口播：桌面想保护，木纹也别遮住。",
        "promise": "透明保护不遮木纹",
        "proof_evidence": "matrix-01 自动铺开实录",
        "hook_pattern": "result_first",
        "candidate_variants": [{"candidate_id": "B", "difference": "B 用痛点先行"}],
    }
    base.update(overrides)
    return base


def test_hook_plan_registered_and_valid():
    assert "hook_plan" in ARTIFACT_NAMES
    validate_artifact("hook_plan", _hook())


def test_hook_plan_rejects_reversed_window():
    with pytest.raises(Exception):
        validate_artifact("hook_plan", _hook(hook_window_seconds=[1.5, 0.0]))


def test_hook_plan_rejects_window_over_five_seconds():
    with pytest.raises(Exception):
        validate_artifact("hook_plan", _hook(hook_window_seconds=[0.0, 6.0]))


def test_hook_plan_rejects_empty_visual():
    with pytest.raises(Exception):
        validate_artifact("hook_plan", _hook(first_frame_visual=""))


def _fingerprint(applicability="needs_review", **style_overrides):
    style = {
        "font_family": "Source Han Sans（近似，待人工确认）",
        "size_hierarchy": [48, 60],
        "weight": "bold",
        "fill_color": "#FFFFFF",
        "stroke": {"color": "#000000", "width_px": 3},
        "position": "中下 1/3",
        "safe_zone_profile": "douyin_9_16",
        "max_chars_per_line": 12,
        "entrance_animation": "整句淡入",
        "sync_mode": "follow_visual",
    }
    style.update(style_overrides)
    return {
        "version": "1.0",
        "project_id": "p-test",
        "created_at": "2026-08-22T00:00:00+00:00",
        "applicability": applicability,
        "source": {"research_breakdown_ref": None, "evidence_frames": [], "overlay_text_samples": ["贴合桌面"]},
        "style": style,
        "binding": {"brand_required_rules": [], "reference_only_rules": []},
        "notes": "待人工确认",
    }


def test_caption_style_fingerprint_registered_and_valid():
    assert "caption_style_fingerprint" in ARTIFACT_NAMES
    validate_artifact("caption_style_fingerprint", _fingerprint())


def test_caption_style_not_applicable_is_valid():
    validate_artifact("caption_style_fingerprint", _fingerprint("not_applicable", font_family=""))


def test_caption_style_needs_review_requires_font_family():
    with pytest.raises(Exception):
        validate_artifact("caption_style_fingerprint", _fingerprint("needs_review", font_family=""))


def test_caption_style_extracted_requires_size_hierarchy():
    with pytest.raises(Exception):
        validate_artifact("caption_style_fingerprint", _fingerprint("extracted", size_hierarchy=[]))

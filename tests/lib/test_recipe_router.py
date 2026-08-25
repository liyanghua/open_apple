"""Unit tests for lib.recipe_router (runtime-agnostic caption/transition recipes)."""

from __future__ import annotations

import pytest

from lib.recipe_router import (
    caption_render_spec,
    recipe_capabilities,
    route_caption,
    route_transition,
    transition_render_spec,
)


def test_route_caption_prefers_best_supported_recipe():
    res = route_caption("proof", "remotion")
    assert res["recipe_id"] == "proof-punch"
    assert res["fallback_used"] is False


def test_route_caption_falls_back_when_runtime_unsupported():
    # proof 首选 proof-punch（不支持 ffmpeg）→ 回退 reveal-pop-soft（支持 ffmpeg）
    res = route_caption("proof", "ffmpeg")
    assert res["recipe_id"] == "reveal-pop-soft"
    assert res["fallback_used"] is True


def test_route_caption_ultimate_fallback():
    # hook 首选 keyword-highlight（仅 remotion）→ proof-punch（无 ffmpeg）→ clean-minimal-label
    res = route_caption("hook", "ffmpeg")
    assert res["recipe_id"] == "clean-minimal-label"
    assert res["fallback_used"] is True


def test_route_transition_prefers_best():
    res = route_transition("impact", "hyperframes")
    assert res["recipe_id"] == "impact-cut"


def test_route_transition_ffmpeg_fallback():
    # proof 首选 flash-proof（无 ffmpeg）→ impact-cut（无 ffmpeg）→ hard-cut-clean
    res = route_transition("proof", "ffmpeg")
    assert res["recipe_id"] == "hard-cut-clean"
    assert res["fallback_used"] is True


def test_unknown_runtime_and_intent_raise():
    with pytest.raises(ValueError):
        route_caption("proof", "nope")
    with pytest.raises(ValueError):
        route_transition("nope", "remotion")


def test_recipe_capabilities_lists_runtime_support():
    caps = recipe_capabilities("ffmpeg")
    assert "clean-minimal-label" in caps["caption_recipes"]
    assert "hard-cut-clean" in caps["transition_recipes"]
    assert "keyword-highlight" not in caps["caption_recipes"]  # remotion-only


def test_caption_render_spec_resolves_recipe():
    spec = caption_render_spec("proof", "remotion")
    assert spec["recipe_id"] == "proof-punch"
    assert spec["entrance"] == "pop"
    assert spec["emphasis"] == "scale"


def test_caption_render_spec_fallback():
    # ffmpeg 不支持 proof-punch → reveal-pop-soft（fade / none / low）
    spec = caption_render_spec("proof", "ffmpeg")
    assert spec["recipe_id"] == "reveal-pop-soft"
    assert spec["entrance"] == "fade"
    assert spec["fallback_used"] is True


def test_transition_render_spec_resolves_recipe():
    spec = transition_render_spec("proof", "remotion")
    assert spec["recipe_id"] == "flash-proof"
    assert spec["type"] == "flash"


def test_transition_render_spec_ffmpeg_fallback():
    spec = transition_render_spec("impact", "ffmpeg")
    assert spec["recipe_id"] == "hard-cut-clean"
    assert spec["type"] == "cut"


def test_recipe_outputs_are_json_serializable():
    import json
    from lib.recipe_router import route_caption, route_transition, scene_recipe_specs

    for x in [route_caption("proof", "remotion"), route_transition("impact", "remotion")]:
        json.dumps(x)  # 不抛异常即通过
    specs = scene_recipe_specs(
        {"scenes": [{"id": "s1", "caption_recipe_intent": "proof", "transition_recipe_intent": "impact"}]},
        "remotion",
    )
    json.dumps(specs)

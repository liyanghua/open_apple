"""Unit tests for lib.caption_treatment (逐镜花字 treatment → recipe intent 应用层)."""

from __future__ import annotations

from lib.caption_treatment import (
    CAPTION_RECIPE_INTENTS,
    CAPTION_TREATMENTS,
    caption_treatment_to_intent,
    resolve_caption_recipe_intent,
)


def test_treatment_to_intent_mapping():
    assert caption_treatment_to_intent("animated") == "hook"
    assert caption_treatment_to_intent("fade_in") == "reveal"
    assert caption_treatment_to_intent("subtitle") == "label"
    assert caption_treatment_to_intent("static") == "label"
    assert caption_treatment_to_intent("fade_out") == "label"
    assert caption_treatment_to_intent("none") == "label"
    assert caption_treatment_to_intent("unknown") == "label"
    assert caption_treatment_to_intent("garbage") == "label"  # 未识别回退
    assert caption_treatment_to_intent("") == "label"


def test_resolve_prefers_own_shot_intent():
    r = resolve_caption_recipe_intent("hook", "subtitle")
    assert r == {"recipe_intent": "hook", "derived_from": "shot_intent", "fallback_used": False}


def test_resolve_falls_back_to_template_treatment():
    r = resolve_caption_recipe_intent(None, "animated")
    assert r == {"recipe_intent": "hook", "derived_from": "template_treatment", "fallback_used": True}


def test_resolve_invalid_own_intent_uses_treatment_fallback():
    r = resolve_caption_recipe_intent("garbage", "subtitle")
    assert r["fallback_used"] is True
    assert r["derived_from"] == "template_treatment"
    assert r["recipe_intent"] == "label"


def test_enums_are_exhaustive_lists():
    assert CAPTION_TREATMENTS == ("fade_in", "subtitle", "animated", "static", "fade_out", "none", "unknown")
    assert CAPTION_RECIPE_INTENTS == ("hook", "proof", "label", "reveal")


def test_scene_plan_accepts_caption_treatment_fields():
    from schemas.artifacts import validate_artifact

    d = {
        "version": "1.0",
        "scenes": [{
            "id": "shot-01", "type": "broll", "description": "产品铺开",
            "start_seconds": 0.0, "end_seconds": 2.0,
            "caption_recipe_intent": "hook", "caption_treatment": "animated",
            "caption_intent_derived_from": "template_treatment", "caption_fallback_used": True,
        }],
    }
    validate_artifact("scene_plan", d)  # 不抛异常即通过

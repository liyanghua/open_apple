"""Schema contract for reusable, user-approved brand defaults."""

from __future__ import annotations

import copy
from pathlib import Path

import jsonschema
import pytest

from schemas.artifacts import ARTIFACT_NAMES, load_schema, validate_artifact


def valid_brand_profile() -> dict:
    return {
        "version": "1.0",
        "profile_id": "warm-home-product",
        "voice": {
            "provider": "doubao",
            "resource": "seed-tts-2.0",
            "voice": "zh_female_vv_uranus_bigtts",
            "rate": 0.96,
        },
        "bgm": {"family": "warm-light-acoustic"},
        "font": {"family": "Songti SC", "fallbacks": ["STSong", "serif"]},
        "caption_profile": {
            "safe_zone_profile": "douyin_9_16",
            "font_min": 44,
            "font_max": 52,
            "max_width": 864,
            "strip_trailing_punctuation": True,
        },
        "emphasis_rules": [
            {"term": "透明桌垫", "color": "#D9A441", "effect": "underline"}
        ],
        "cta_pattern": "把从容铺在餐桌上",
        "platform_defaults": {
            "douyin": {"aspect_ratio": "9:16", "resolution": "1080x1920", "fps": 30}
        },
    }


def test_brand_profile_schema_is_registered_and_accepts_all_supported_fields() -> None:
    assert "brand_profile" in ARTIFACT_NAMES
    schema = load_schema("brand_profile")
    jsonschema.Draft202012Validator.check_schema(schema)
    validate_artifact("brand_profile", valid_brand_profile())


def test_brand_profile_rejects_unregistered_defaults() -> None:
    profile = copy.deepcopy(valid_brand_profile())
    profile["logo_animation"] = "surprise"

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("brand_profile", profile)


def test_brand_profile_rejects_caption_width_outside_social_v1_safe_zone() -> None:
    profile = valid_brand_profile()
    profile["caption_profile"]["max_width"] = 865

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("brand_profile", profile)


@pytest.mark.parametrize("effect", ["scale", "underline", "color"])
def test_brand_profile_accepts_only_supported_emphasis_effects(effect: str) -> None:
    profile = valid_brand_profile()
    profile["emphasis_rules"][0]["effect"] = effect
    validate_artifact("brand_profile", profile)

    profile["emphasis_rules"][0]["effect"] = "sparkles"
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("brand_profile", profile)


def test_real_transparent_mat_edit_decisions_validate_with_caption_facts() -> None:
    project_artifact = (
        Path(__file__).resolve().parents[2]
        / "projects"
        / "transparent-table-mat-remix-01"
        / "artifacts"
        / "edit_decisions.json"
    )
    if not project_artifact.exists():
        pytest.skip("local transparent-mat production artifact is not present")
    validate_artifact("edit_decisions", __import__("json").loads(project_artifact.read_text(encoding="utf-8")))

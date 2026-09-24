"""Production brand preflight contracts; no provider calls or generated assets."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
from pathlib import Path

import pytest
from PIL import Image, ImageFont

from lib.brand_profile import merge_brand_defaults


def module():
    assert importlib.util.find_spec("lib.production_brand"), "production brand preflight is missing"
    return importlib.import_module("lib.production_brand")


def test_production_preflight_exposes_callable_contract():
    assert callable(module().preflight_production_brand)


@pytest.fixture
def valid(tmp_path):
    candidates = [
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    paths = next((pair for pair in candidates if all(Path(p).exists() for p in pair)), None)
    if paths is None:
        pytest.skip("real regular/bold font fixture unavailable")
    files = []
    for path, weight in zip(paths, [400, 700]):
        data = Path(path).read_bytes()
        name = f"font-{weight}.ttf"
        (tmp_path / name).write_bytes(data)
        files.append({"path": name, "src": name, "weight": weight, "sha256": hashlib.sha256(data).hexdigest()})
    family = ImageFont.truetype(paths[0], 38).getname()[0]
    profile = module().make_towel_brand_profile(font_files=files, font_family=family)
    # A portable test face cannot certify Chinese glyphs; use its real supported text.
    profile["production"]["slogan"] = "PLAYBOY, Better everyday."
    Image.new("RGBA", (240, 120), "black").save(tmp_path / "logo.png")
    props = {
        "fps": 30, "width": 1080, "height": 1920, "durationInFrames": 240,
        "logoSrc": "logo.png", "footage": {"clip": "clip.mp4"},
        "scenes": [
            {"id": f"s{i}", "footageKey": "clip", "fromFrame": i * 60,
             "durationInFrames": 60, "sourceInSeconds": 0, "sourceDurationSeconds": 4,
             "playbackRate": 1, "cropScale": 1, "role": "body"}
            for i in range(4)
        ],
        "titles": [{"fromFrame": 0, "text": "Soft"}, {"fromFrame": 120, "text": "Dry"}],
        "captions": [{"text": "PLAYBOY, Better everyday.", "startMs": 4000, "endMs": 7000}],
        "words": [{"text": "PLAYBOY, ", "startMs": 4000, "endMs": 4600},
                  {"text": "Better everyday.", "startMs": 4600, "endMs": 7000}],
        "timingSource": "measured_word_timestamps",
    }
    return profile, props, tmp_path


def report(valid):
    profile, props, directory = valid
    return module().preflight_production_brand(profile, props, project_dir=directory)


def check(result, name):
    return next(c for c in result["checks"] if c["check_id"] == name)


def test_profile_extends_existing_defaults_and_preserves_approved_geometry(valid):
    profile, _, _ = valid
    merged = merge_brand_defaults(profile, {})["merged"]
    assert merged["production"]["logo"] == {"right": 72, "top": 96, "width": 120, "clear_space": 16}
    assert merged["production"]["title"]["font_size"] == 64
    assert merged["production"]["caption"]["top"] == 1470
    assert merged["production"]["transition"] == {"frames": 5, "rule": "incoming_only"}


def test_valid_strict_profile_has_machine_evidence(valid):
    result = report(valid)
    assert result["status"] == "passed"
    assert result["strict_ready"] is True
    assert check(result, "font_identity")["status"] == "pass"
    assert check(result, "text_geometry")["evidence"]["measurement"] == "font_file_preflight"
    assert all(c["evidence"] for c in result["checks"])


def test_missing_font_blocks_strict(valid):
    (valid[2] / "font-400.ttf").unlink()
    assert report(valid)["status"] == "blocked"
    assert check(report(valid), "font_files")["status"] == "fail"


def test_hash_drift_blocks_even_when_font_still_decodes(valid):
    valid[0]["font"]["files"][0]["sha256"] = "0" * 64
    assert check(report(valid), "font_files")["status"] == "fail"


def test_actual_family_cannot_be_relabeled_microsoft_yahei(valid):
    valid[0]["font"]["family"] = "Microsoft YaHei"
    assert check(report(valid), "font_identity")["status"] == "fail"


def test_regular_file_cannot_be_labeled_bold(valid):
    valid[0]["font"]["files"][1].update(valid[0]["font"]["files"][0], weight=700)
    assert check(report(valid), "font_identity")["status"] == "fail"


def test_missing_strict_font_configuration_is_blocked(valid):
    profile = module().make_towel_brand_profile()
    result = module().preflight_production_brand(profile, valid[1], project_dir=valid[2])
    assert result["status"] == "blocked"
    assert check(result, "font_files")["status"] == "fail"


def test_legacy_appearance_is_preserved_without_false_font_certification(valid):
    profile = module().make_towel_brand_profile(strict=False)
    profile["production"]["slogan"] = valid[0]["production"]["slogan"]
    result = module().preflight_production_brand(profile, valid[1], project_dir=valid[2])
    assert result["status"] == "degraded"
    assert result["strict_ready"] is False
    assert check(result, "font_identity")["status"] == "not_run"
    assert profile["production"]["legacy_font_stack"] == 'Arial, "Microsoft YaHei", STHeiti, sans-serif'


@pytest.mark.parametrize("change", ["overlap", "overflow", "logo_clearance"])
def test_geometry_defects_are_localized(valid, change):
    if change == "overlap":
        valid[0]["production"]["caption"]["top"] = 220
        valid[0]["production"]["title"]["left"] = 350
    elif change == "overflow":
        valid[1]["captions"][0]["text"] = "超长字幕" * 40
    else:
        valid[0]["production"]["title"].update(left=880, top=100)
    result = report(valid)
    assert result["status"] == "blocked"
    assert check(result, "text_geometry")["status"] == "fail"
    assert check(result, "text_geometry")["evidence"]["issues"]


def test_low_resolution_logo_fails_clear_zone_check(valid):
    Image.new("RGBA", (30, 15), "black").save(valid[2] / "logo.png")
    assert check(report(valid), "logo_asset")["status"] == "fail"


def test_truncated_slogan_is_rejected_even_if_caption_contains_full_slogan(valid):
    valid[1]["words"][-1]["text"] = "让日常更有"
    assert check(report(valid), "slogan")["status"] == "fail"


def test_tail_is_based_on_last_measured_word_not_caption_end(valid):
    valid[1]["words"][-1]["endMs"] = 7750
    assert check(report(valid), "speech_tail")["status"] == "fail"
    valid[1]["words"][-1]["endMs"] = 7600
    assert check(report(valid), "speech_tail")["status"] == "pass"


def test_guessed_timing_does_not_pass_measured_tail_gate(valid):
    valid[1]["timingSource"] = "estimated"
    assert check(report(valid), "speech_timeline")["status"] == "fail"


def test_display_recipe_rejects_long_body_cut(valid):
    valid[1]["scenes"][0]["durationInFrames"] = 90
    assert check(report(valid), "shot_rhythm")["status"] == "fail"


def test_custom_story_recipe_keeps_long_structure_instead_of_eight_second_cap(valid):
    valid[1]["recipe"] = {"id": "relationship_story", "raw_action_seconds": [6, 12], "body_cut_seconds": [5, 9]}
    valid[1]["durationInFrames"] = 960
    for i, scene in enumerate(valid[1]["scenes"]):
        scene.update(fromFrame=i * 240, durationInFrames=240, sourceDurationSeconds=10)
    assert report(valid)["status"] == "passed"


def test_source_must_cover_the_opaque_outgoing_transition_handles(valid):
    valid[1]["scenes"][0]["sourceInSeconds"] = 2
    assert check(report(valid), "shot_timeline")["status"] == "fail"


def test_invalid_timeline_returns_structured_failure_instead_of_crashing(valid):
    valid[1]["fps"] = 0
    assert report(valid)["status"] == "blocked"
    assert check(report(valid), "input_contract")["status"] == "fail"


def test_missing_glyphs_cannot_silently_use_an_uncertified_browser_fallback(valid):
    valid[1]["titles"][0]["text"] = "\U0010ffff\U0010ffff"
    assert check(report(valid), "text_geometry")["status"] == "fail"


def test_font_section_is_required_for_production_profiles(valid):
    del valid[0]["font"]
    assert check(report(valid), "input_contract")["status"] == "fail"


def test_caption_with_correct_text_but_wrong_audio_window_is_rejected(valid):
    valid[1]["captions"][0].update(startMs=0, endMs=1000)
    assert check(report(valid), "speech_timeline")["status"] == "fail"


def test_caption_cannot_disappear_before_its_measured_last_word(valid):
    valid[1]["captions"][0]["endMs"] = 6500
    assert check(report(valid), "speech_timeline")["status"] == "fail"


def test_italic_font_cannot_masquerade_as_regular_normal_face(valid):
    italic = Path("/System/Library/Fonts/Supplemental/Arial Italic.ttf")
    if not italic.exists():
        pytest.skip("actual italic font fixture unavailable")
    data = italic.read_bytes()
    (valid[2] / "italic.ttf").write_bytes(data)
    valid[0]["font"]["files"][0].update(path="italic.ttf", src="italic.ttf", sha256=hashlib.sha256(data).hexdigest())
    assert check(report(valid), "font_identity")["status"] == "fail"


@pytest.mark.parametrize("field", ["width", "height", "durationInFrames"])
def test_render_metadata_requires_integer_pixel_and_frame_dimensions(valid, field):
    valid[1][field] += 0.5
    assert check(report(valid), "input_contract")["status"] == "fail"

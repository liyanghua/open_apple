from __future__ import annotations

import json
from pathlib import Path

from lib.template_render import build_edit_decisions, build_final_props
from lib.media_profiles import get_profile
from lib.template_assets import build_production_lock
from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact


def test_template_render_supports_canonical_taobao_3_4_profile(tmp_path: Path) -> None:
    props = build_final_props(
        tmp_path,
        {"sections": []},
        [{"id": "shot-01", "duration_seconds": 2.0, "screen_copy": "吸水", "scene_id": "scene-001"}],
        profile="social_vertical_3_4_1080p30",
    )
    assert (props["width"], props["height"]) == (1080, 1440)

    edit = build_edit_decisions(
        tmp_path,
        [{"id": "shot-01", "duration_seconds": 2.0, "scene_id": "scene-001"}],
        safe_zone_profile="taobao_detail_3_4",
    )
    assert edit["safe_zone_profile"] == "taobao_detail_3_4"
    validate_artifact("edit_decisions", attach_hashes(edit))
    assert (get_profile("social_vertical_3_4_sample_540p30").width,
            get_profile("social_vertical_3_4_sample_540p30").height) == (540, 720)
    assert (get_profile("social_vertical_3_4_2160p30").width,
            get_profile("social_vertical_3_4_2160p30").height) == (2160, 2880)
    lock = build_production_lock(
        tmp_path, {"template_id": "towel"}, {}, {},
        output_profile="social_vertical_3_4_2160p30",
    )
    assert lock["locked_values"]["output"]["resolution"] == "2160x2880"


def test_prep_media_resolves_run_local_aligned_template_before_global_pack(tmp_path: Path) -> None:
    import json
    from scripts.prep_template_media import resolve_template

    project = tmp_path / "run"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "template_pack.json").write_text(
        json.dumps({"templates": [{"template_id": "aligned-local", "slots": []}]}),
        encoding="utf-8",
    )
    template = resolve_template(project, "aligned-local", global_pack={"templates": []})
    assert template["template_id"] == "aligned-local"


def test_prep_media_resolves_project_relative_source_path(tmp_path: Path) -> None:
    from scripts.prep_template_media import resolve_source_path

    project = tmp_path / "run"
    source = project / "inputs" / "source" / "clip.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    assert resolve_source_path(project, "inputs/source/clip.mp4") == source


def test_prep_media_reuses_realized_generated_video_for_generated_mapping(tmp_path: Path) -> None:
    import json
    from scripts.prep_template_media import resolve_generated_video

    project = tmp_path / "run"
    generated = project / "assets" / "video" / "generated" / "task" / "clip.mp4"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"video")
    (project / "artifacts").mkdir()
    (project / "artifacts" / "asset_manifest.json").write_text(json.dumps({
        "assets": [{"id": "proxy-shot-09", "scene_id": "shot-09", "type": "video",
                    "path": "assets/video/generated/task/clip.mp4"}]
    }), encoding="utf-8")
    assert resolve_generated_video(project, scene_id="scene-009", shot_id="shot-09") == generated


def test_prep_media_finds_generated_video_after_manifest_was_rebuilt(tmp_path: Path) -> None:
    from scripts.prep_template_media import resolve_generated_video

    project = tmp_path / "run"
    generated = project / "assets" / "video" / "generated" / "task" / "clip.mp4"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"video")
    assert resolve_generated_video(project, scene_id="scene-009", shot_id="shot-09") == generated


def test_prep_media_binds_generated_mapping_to_realized_clip(tmp_path: Path) -> None:
    from scripts.prep_template_media import render_asset_path_for_mapping

    project = tmp_path / "run"
    generated = project / "assets" / "video" / "generated" / "task" / "clip.mp4"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"video")
    mapping = {"scene_id": "scene-009", "visual_route": "generated_from_product_image"}
    assert render_asset_path_for_mapping(project, 9, mapping) == "assets/video/generated/task/clip.mp4"


def test_qa_profile_follows_locked_taobao_output_profile(tmp_path: Path) -> None:
    from scripts.qa_template_render import resolve_qa_profile

    project = tmp_path / "run"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "production_lock.json").write_text(
        json.dumps({"locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"},
                                       "platform": "taobao"}}), encoding="utf-8")
    assert resolve_qa_profile(project) == ("social_vertical_3_4_2160p30", "taobao_detail_3_4")


def test_final_review_schema_accepts_taobao_caption_safe_zone() -> None:
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/artifacts/final_review.schema.json")
        .read_text(encoding="utf-8")
    )
    allowed = schema["properties"]["checks"]["properties"]["caption_render"]["properties"]["safe_zone_profile"]["enum"]
    assert "taobao_detail_3_4" in allowed


def test_final_props_preserves_alignment_actions_and_generated_reference() -> None:
    from lib.template_render import build_final_props

    props = build_final_props(Path("projects/x"), {}, [{
        "id": "shot-09", "duration_seconds": 2, "scene_id": "scene-009",
        "action_keys": ["slow_product_reveal"], "visual_route": "generated_from_product_image",
        "generation_reference": {"sha256": "b" * 64},
    }], profile="social_vertical_3_4_1080p30")
    scene = props["scenes"][0]
    assert scene["action_keys"] == ["slow_product_reveal"]
    assert scene["reference_hash"] == "b" * 64


def test_compose_alignment_prefers_current_report_when_final_report_absent(tmp_path: Path) -> None:
    from scripts.finish_template_compose import resolve_alignment_report

    (tmp_path / "analysis").mkdir(parents=True)
    (tmp_path / "analysis" / "alignment_check.json").write_text('{"sample_sha256":"x"}', encoding="utf-8")
    assert resolve_alignment_report(tmp_path)["sample_sha256"] == "x"


def test_compose_uses_source_led_semantic_checks_with_generated_integrity_fields() -> None:
    from lib.template_alignment import alignment_report_semantic_checks

    report = {"sample_sha256": "a", "script_sha256": "b", "checks": [{
        "shot_id": "shot-09", "section_id": "sec-009",
        "action_match": "pass", "result_support": "pass",
        "narration_caption_match": "pass", "product_identity_match": "pass",
        "crop_completeness": "pass", "generated_text_integrity": "pass",
        "voice_caption_timing_match": "pass",
    }]}
    checks = alignment_report_semantic_checks(report, sample_sha256="a", script_sha256="b", input_mode="source_led_template")
    assert checks[0]["generated_text_integrity"] == "pass"


def test_material_reuse_report_accepts_generated_mapping_without_source_interval() -> None:
    from lib.template_source_match import material_reuse_report

    report = material_reuse_report({
        "scenes": [{"start_seconds": 0, "end_seconds": 2}],
        "metadata": {"source_mapping": [{
            "visual_route": "generated_from_product_image",
            "scene_id": "scene-009",
            "timeline_interval": {"start_seconds": 0, "end_seconds_exclusive": 2},
        }]},
    })
    assert report["counts"] == {"": 1}
    assert "H2" in report["findings"][0]

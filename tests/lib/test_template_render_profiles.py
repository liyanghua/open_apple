from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    from scripts.qa_template_render import resolve_qa_profile, resolve_sample_qa_profile

    project = tmp_path / "run"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "production_lock.json").write_text(
        json.dumps({"locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"},
                                       "platform": "taobao"}}), encoding="utf-8")
    assert resolve_qa_profile(project) == ("social_vertical_3_4_2160p30", "taobao_detail_3_4")
    assert resolve_sample_qa_profile("social_vertical_3_4_2160p30") == "social_vertical_3_4_sample_540p30"


def test_sample_qa_profile_maps_standard_vertical_to_sample_profile() -> None:
    from scripts.qa_template_render import resolve_sample_qa_profile

    assert resolve_sample_qa_profile("social_vertical_1080p30") == "social_vertical_sample_540p30"


def test_sample_profile_contract_maps_full_profiles_and_preserves_sample_profiles() -> None:
    import scripts.render_template_sample as sample_render

    resolve = getattr(sample_render, "resolve_sample_profile", None)
    assert resolve is not None, "quick sample profile resolver is missing"
    assert resolve("social_vertical_3_4_2160p30") == "social_vertical_3_4_sample_540p30"
    assert resolve("social_vertical_3_4_1080p30") == "social_vertical_3_4_sample_540p30"
    assert resolve("social_vertical_3_4_sample_540p30") == "social_vertical_3_4_sample_540p30"
    assert resolve("social_vertical_1080p30") == "social_vertical_sample_540p30"
    assert resolve("social_vertical_sample_540p30") == "social_vertical_sample_540p30"


def test_quick_sample_uses_locked_profile_and_dimensioned_canonical_name(
    tmp_path: Path, monkeypatch,
) -> None:
    import scripts.render_template_sample as sample_render
    from tools.tool_registry import registry

    run = "taobao-sample"
    project = tmp_path / "projects" / run
    (project / "artifacts").mkdir(parents=True)
    (project / "renders").mkdir()
    (project / "artifacts" / "production_lock.json").write_text(json.dumps({
        "locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"}},
    }), encoding="utf-8")
    staged = project / "assets" / "sample" / "staged.mp4"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"sample")
    seen: dict = {}

    class FakeCompose:
        def execute(self, inputs: dict) -> SimpleNamespace:
            seen.update(inputs)
            return SimpleNamespace(success=True, error=None, data={"output": str(staged)})

    monkeypatch.setattr(sample_render, "ROOT", tmp_path)
    monkeypatch.setattr(sample_render, "build_payload", lambda _project: {
        "final_props": {"durationInFrames": 450}, "asset_manifest": {},
    })
    monkeypatch.setattr(registry, "discover", lambda: None)
    monkeypatch.setitem(registry._tools, "video_compose", FakeCompose())

    result = sample_render.render(run, "quick")

    assert result["success"] is True
    assert result["profile"] == "social_vertical_3_4_sample_540p30"
    assert result["output_path"] == "renders/sample-v1-540x720.mp4"
    assert seen["render_plan"]["profile"] == "social_vertical_3_4_sample_540p30"
    assert (project / "renders" / "sample-v1-540x720.mp4").read_bytes() == b"sample"


def test_quick_sample_fails_closed_when_compose_returns_no_readable_output(
    tmp_path: Path, monkeypatch,
) -> None:
    import scripts.render_template_sample as sample_render
    from tools.tool_registry import registry

    run = "taobao-missing-output"
    project = tmp_path / "projects" / run
    (project / "artifacts").mkdir(parents=True)
    canonical = project / "renders" / "sample-v1-540x720.mp4"
    canonical.parent.mkdir()
    canonical.write_bytes(b"old-sample")
    (project / "artifacts" / "production_lock.json").write_text(json.dumps({
        "locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"}},
    }), encoding="utf-8")

    class FakeCompose:
        def execute(self, _inputs: dict) -> SimpleNamespace:
            return SimpleNamespace(success=True, error=None, data={})

    monkeypatch.setattr(sample_render, "ROOT", tmp_path)
    monkeypatch.setattr(sample_render, "build_payload", lambda _project: {
        "final_props": {"durationInFrames": 450}, "asset_manifest": {},
    })
    monkeypatch.setattr(registry, "discover", lambda: None)
    monkeypatch.setitem(registry._tools, "video_compose", FakeCompose())

    result = sample_render.render(run, "quick")

    assert result["success"] is False
    assert "readable output" in result["error"]
    assert result["output_path"] is None
    assert canonical.read_bytes() == b"old-sample"


@pytest.mark.parametrize("profile", ["social_vertical_typo", "tiktok"])
def test_sample_profile_contract_rejects_unknown_or_unmapped_profiles(profile: str) -> None:
    from lib.sample_contract import resolve_sample_profile

    with pytest.raises(ValueError, match=profile):
        resolve_sample_profile(profile)


def test_qa_resolves_canonical_sample_path_for_locked_profile(tmp_path: Path) -> None:
    import scripts.qa_template_render as template_qa

    sample = tmp_path / "renders" / "sample-v1-540x720.mp4"
    sample.parent.mkdir()
    sample.write_bytes(b"sample")
    resolve = getattr(template_qa, "resolve_sample_review_path", None)
    assert resolve is not None, "sample QA path resolver is missing"
    assert resolve(tmp_path, "social_vertical_3_4_2160p30") == sample


def test_sample_qa_uses_canonical_profile_and_never_creates_final(
    tmp_path: Path, monkeypatch,
) -> None:
    import scripts.qa_template_render as template_qa
    from tools.tool_registry import registry

    run = "sample-only-qa"
    project = tmp_path / "projects" / run
    artifacts = project / "artifacts"
    canonical = project / "renders" / "sample-v1-540x720.mp4"
    artifacts.mkdir(parents=True)
    canonical.parent.mkdir()
    canonical.write_bytes(b"canonical-sample")
    (project / "renders" / "sample-v1.mp4").write_bytes(b"legacy-sample")
    (artifacts / "production_lock.json").write_text(json.dumps({
        "locked_values": {
            "output": {"profile": "social_vertical_3_4_2160p30"},
            "platform": "taobao",
        },
    }), encoding="utf-8")
    (artifacts / "script.json").write_text(json.dumps({"total_duration_seconds": 20}), encoding="utf-8")
    (artifacts / "shot_execution_plan.json").write_text(json.dumps({"shots": []}), encoding="utf-8")
    (artifacts / "final_props.json").write_text(json.dumps({"captions": []}), encoding="utf-8")
    calls: list[dict] = []

    class FakeFinalQA:
        def execute(self, inputs: dict) -> SimpleNamespace:
            calls.append({"tool": "final_qa", **inputs})
            Path(inputs["output_path"]).write_text('{"status":"pass"}', encoding="utf-8")
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    class FakeValidator:
        def execute(self, inputs: dict) -> SimpleNamespace:
            calls.append({"tool": "technical_validator", **inputs})
            Path(inputs["output_path"]).write_text(json.dumps({
                "status": "pass",
                "subject_ref": inputs["subject_ref"],
                "subject_hash": inputs["subject_hash"],
            }), encoding="utf-8")
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    monkeypatch.setattr(template_qa, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "discover", lambda: None)
    monkeypatch.setitem(registry._tools, "final_qa", FakeFinalQA())
    monkeypatch.setitem(registry._tools, "technical_validator", FakeValidator())
    monkeypatch.setattr(template_qa, "_media_duration", lambda _path: 15.0)
    monkeypatch.setattr("lib.sample_payload.build_sample_render_payload", lambda _payload: {})
    monkeypatch.setattr("scripts.render_template_sample.build_payload", lambda _project: {})

    result = template_qa.qa_sample(run)

    final_qa_call, validator_call = calls
    assert result["scope"] == "sample"
    assert result["sample_path"] == "renders/sample-v1-540x720.mp4"
    assert final_qa_call["mode"] == "quick"
    assert final_qa_call["input_path"] == str(canonical)
    assert final_qa_call["expected_profile"] == "social_vertical_3_4_sample_540p30"
    assert final_qa_call["caption_declaration"]["safe_zone_profile"] == "taobao_detail_3_4"
    assert validator_call["scope"] == "sample"
    assert validator_call["input_path"] == str(canonical)
    assert validator_call["expected_profile"] == "social_vertical_3_4_sample_540p30"
    assert validator_call["expected_duration_s"] == 15.0
    assert validator_call["subject_ref"]["path"] == "renders/sample-v1-540x720.mp4"
    assert validator_call["subject_hash"] == template_qa._sha256(canonical)
    assert validator_call["caption_spec"]["computed_boxes"] == []
    assert (artifacts / "final_qa_sample.json").is_file()
    assert (artifacts / "l1a_sample.json").is_file()
    assert not (project / "renders" / "final.mp4").exists()
    assert not (artifacts / "final_qa_full.json").exists()
    assert not (artifacts / "l1a_final.json").exists()


def test_sample_qa_fails_closed_when_canonical_sample_is_missing(
    tmp_path: Path, monkeypatch,
) -> None:
    import scripts.qa_template_render as template_qa
    from tools.tool_registry import registry

    run = "missing-canonical-sample"
    project = tmp_path / "projects" / run
    artifacts = project / "artifacts"
    artifacts.mkdir(parents=True)
    (project / "renders").mkdir()
    (project / "renders" / "sample-v1.mp4").write_bytes(b"legacy-sample")
    (artifacts / "production_lock.json").write_text(json.dumps({
        "locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"}},
    }), encoding="utf-8")
    invoked = False

    class UnexpectedTool:
        def execute(self, _inputs: dict) -> SimpleNamespace:
            nonlocal invoked
            invoked = True
            raise AssertionError("sample QA must fail before tool invocation")

    monkeypatch.setattr(template_qa, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "discover", lambda: None)
    monkeypatch.setitem(registry._tools, "final_qa", UnexpectedTool())
    monkeypatch.setitem(registry._tools, "technical_validator", UnexpectedTool())

    with pytest.raises(SystemExit, match="canonical sample"):
        template_qa.qa_sample(run)

    assert invoked is False
    assert not (project / "renders" / "final.mp4").exists()


def test_sample_qa_requires_l1a_sample_artifact_before_returning_success(
    tmp_path: Path, monkeypatch,
) -> None:
    import scripts.qa_template_render as template_qa
    from tools.tool_registry import registry

    run = "missing-l1a-artifact"
    project = tmp_path / "projects" / run
    artifacts = project / "artifacts"
    canonical = project / "renders" / "sample-v1-540x720.mp4"
    artifacts.mkdir(parents=True)
    canonical.parent.mkdir()
    canonical.write_bytes(b"canonical-sample")
    (artifacts / "production_lock.json").write_text(json.dumps({
        "locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"}},
    }), encoding="utf-8")

    class FakeFinalQA:
        def execute(self, inputs: dict) -> SimpleNamespace:
            Path(inputs["output_path"]).write_text('{"status":"pass"}', encoding="utf-8")
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    class ValidatorWithoutArtifact:
        def execute(self, _inputs: dict) -> SimpleNamespace:
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    monkeypatch.setattr(template_qa, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "discover", lambda: None)
    monkeypatch.setitem(registry._tools, "final_qa", FakeFinalQA())
    monkeypatch.setitem(registry._tools, "technical_validator", ValidatorWithoutArtifact())
    monkeypatch.setattr(template_qa, "_media_duration", lambda _path: 15.0)
    monkeypatch.setattr("lib.sample_payload.build_sample_render_payload", lambda _payload: {})
    monkeypatch.setattr("scripts.render_template_sample.build_payload", lambda _project: {})

    with pytest.raises(SystemExit, match="l1a_sample"):
        template_qa.qa_sample(run)


def test_sample_qa_rejects_stale_l1a_pass_that_validator_did_not_overwrite(
    tmp_path: Path, monkeypatch,
) -> None:
    import scripts.qa_template_render as template_qa
    from tools.tool_registry import registry

    run = "stale-l1a-artifact"
    project = tmp_path / "projects" / run
    artifacts = project / "artifacts"
    canonical = project / "renders" / "sample-v1-540x720.mp4"
    artifacts.mkdir(parents=True)
    canonical.parent.mkdir()
    canonical.write_bytes(b"canonical-sample")
    (artifacts / "production_lock.json").write_text(json.dumps({
        "locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"}},
    }), encoding="utf-8")
    stale_report = {
        "status": "pass",
        "subject_ref": {"name": "sample_video", "path": "renders/sample-v1-540x720.mp4"},
        "subject_hash": template_qa._sha256(canonical),
    }
    (artifacts / "l1a_sample.json").write_text(json.dumps(stale_report), encoding="utf-8")

    class FakeFinalQA:
        def execute(self, inputs: dict) -> SimpleNamespace:
            Path(inputs["output_path"]).write_text('{"status":"pass"}', encoding="utf-8")
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    class ValidatorWithoutArtifact:
        def execute(self, _inputs: dict) -> SimpleNamespace:
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    monkeypatch.setattr(template_qa, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "discover", lambda: None)
    monkeypatch.setitem(registry._tools, "final_qa", FakeFinalQA())
    monkeypatch.setitem(registry._tools, "technical_validator", ValidatorWithoutArtifact())
    monkeypatch.setattr(template_qa, "_media_duration", lambda _path: 15.0)
    monkeypatch.setattr("lib.sample_payload.build_sample_render_payload", lambda _payload: {})
    monkeypatch.setattr("scripts.render_template_sample.build_payload", lambda _project: {})

    with pytest.raises(SystemExit, match="l1a_sample"):
        template_qa.qa_sample(run)

    assert not (artifacts / "l1a_sample.json").exists()


def test_sample_qa_rejects_l1a_bound_before_canonical_sample_changes(
    tmp_path: Path, monkeypatch,
) -> None:
    import scripts.qa_template_render as template_qa
    from tools.tool_registry import registry

    run = "sample-changed-during-validation"
    project = tmp_path / "projects" / run
    artifacts = project / "artifacts"
    canonical = project / "renders" / "sample-v1-540x720.mp4"
    artifacts.mkdir(parents=True)
    canonical.parent.mkdir()
    canonical.write_bytes(b"sample-before-validation")
    (artifacts / "production_lock.json").write_text(json.dumps({
        "locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"}},
    }), encoding="utf-8")

    class FakeFinalQA:
        def execute(self, inputs: dict) -> SimpleNamespace:
            Path(inputs["output_path"]).write_text('{"status":"pass"}', encoding="utf-8")
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    class ValidatorThatChangesSample:
        def execute(self, inputs: dict) -> SimpleNamespace:
            Path(inputs["output_path"]).write_text(json.dumps({
                "status": "pass",
                "subject_ref": inputs["subject_ref"],
                "subject_hash": inputs["subject_hash"],
            }), encoding="utf-8")
            canonical.write_bytes(b"sample-after-validation")
            return SimpleNamespace(success=True, error=None, data={"status": "pass"})

    monkeypatch.setattr(template_qa, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "discover", lambda: None)
    monkeypatch.setitem(registry._tools, "final_qa", FakeFinalQA())
    monkeypatch.setitem(registry._tools, "technical_validator", ValidatorThatChangesSample())
    monkeypatch.setattr(template_qa, "_media_duration", lambda _path: 15.0)
    monkeypatch.setattr("lib.sample_payload.build_sample_render_payload", lambda _payload: {})
    monkeypatch.setattr("scripts.render_template_sample.build_payload", lambda _project: {})

    with pytest.raises(SystemExit, match="l1a_sample"):
        template_qa.qa_sample(run)


def test_finish_sample_falls_back_to_profile_matched_canonical_path(tmp_path: Path) -> None:
    from scripts.finish_template_sample import _resolve_review_output

    sample = tmp_path / "renders" / "sample-v1-540x720.mp4"
    sample.parent.mkdir()
    sample.write_bytes(b"sample")
    (tmp_path / "renders" / "sample-v1.mp4").write_bytes(b"legacy")

    assert _resolve_review_output(
        tmp_path,
        {"profile": "social_vertical_3_4_1080p30", "output_path": "renders/sample-v1.mp4"},
        {"subject_ref": {"path": "renders/sample-v1.mp4"}},
    ) == "renders/sample-v1-540x720.mp4"


def test_finish_sample_rejects_legacy_l1a_when_locked_canonical_sample_is_missing(tmp_path: Path) -> None:
    from scripts.finish_template_sample import _resolve_review_output

    legacy = tmp_path / "renders" / "sample-v1.mp4"
    legacy.parent.mkdir()
    legacy.write_bytes(b"legacy")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "production_lock.json").write_text(json.dumps({
        "locked_values": {"output": {"profile": "social_vertical_3_4_2160p30"}},
    }), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="canonical sample"):
        _resolve_review_output(
            tmp_path,
            {"profile": "social_vertical_3_4_2160p30"},
            {"subject_ref": {"path": "renders/sample-v1.mp4"}},
        )


def test_finish_sample_rejects_l1a_bound_to_a_stale_review_output(tmp_path: Path) -> None:
    from scripts.finish_template_sample import validate_l1a_subject

    canonical = tmp_path / "renders" / "sample-v1-540x720.mp4"
    legacy = tmp_path / "renders" / "sample-v1.mp4"
    canonical.parent.mkdir()
    canonical.write_bytes(b"current")
    legacy.write_bytes(b"stale")

    with pytest.raises(ValueError, match="does not match current review output"):
        validate_l1a_subject(
            {"subject_ref": {"path": "renders/sample-v1.mp4"},
             "subject_hash": "f" * 64},
            "renders/sample-v1-540x720.mp4",
            canonical,
        )


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


def test_finish_compose_targets_certified_final_render() -> None:
    from scripts.finish_template_compose import FINAL

    assert FINAL == "renders/final.mp4"


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

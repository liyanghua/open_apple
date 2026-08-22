from pathlib import Path

from lib.pipeline_loader import get_stage_order, load_pipeline


ROOT = Path(__file__).resolve().parents[2]


def test_cinematic_fast_has_fixed_stage_order_and_script_execution_sample_gates():
    manifest = load_pipeline("cinematic-fast")
    assert get_stage_order(manifest) == [
        "research", "proposal", "script", "scene_plan", "assets",
        "sample", "edit", "compose", "publish",
    ]
    gated = [
        stage["name"]
        for stage in manifest["stages"]
        if stage.get("human_approval_default")
    ]
    assert gated == ["script", "assets", "sample"]
    script_group = manifest["approval_groups"]["script_lock"]
    assert script_group["members"] == ["script"]
    assert script_group["terminal_stage"] == "script"
    group = manifest["approval_groups"]["creative_lock"]
    assert group["members"] == ["proposal", "scene_plan", "assets"]
    assert group["terminal_stage"] == "assets"
    assert manifest["stages"][2]["approval_group_terminal"] is True
    assert manifest["stages"][4]["approval_group_terminal"] is True


def test_cinematic_fast_sample_and_compose_contracts():
    manifest = load_pipeline("cinematic-fast")
    stages = {stage["name"]: stage for stage in manifest["stages"]}
    assert stages["assets"]["produces"] == ["shot_execution_plan", "asset_plan", "production_lock", "approval_bundle"]
    assert stages["sample"]["produces"] == [
        "asset_manifest", "final_props", "render_plan", "sample_report",
        "sample_execution_trace", "caption_policy_revision", "evaluation_report",
    ]
    assert "caption_policy_revision" in stages["edit"]["required_artifacts_in"]
    assert "caption_policy_revision" in stages["compose"]["required_artifacts_in"]
    assert "evaluation_report" in stages["compose"]["produces"]
    assert "evaluation_report" in stages["publish"]["required_artifacts_in"]
    assert "technical_validator" in stages["sample"]["required_tools"]
    assert "technical_validator" in stages["compose"]["required_tools"]
    assert "video_judge" in stages["sample"]["required_tools"]
    assert "video_judge" in stages["compose"]["required_tools"]
    assert "caption_style_fingerprint" in stages["research"]["produces"]
    assert "caption_style_fingerprint" in stages["sample"]["required_artifacts_in"]
    assert "caption_style_fingerprint" in stages["compose"]["required_artifacts_in"]
    assert "hook_plan" in stages["proposal"]["produces"]
    assert {"tts_selector", "audio_mixer", "subtitle_gen", "media_proxy", "video_compose", "final_qa"} <= set(stages["sample"]["tools_available"])
    assert {"video_compose", "final_qa"} <= set(stages["compose"]["tools_available"])
    assert "asset_manifest" not in stages["assets"]["produces"]


def test_cinematic_fast_required_skill_wrappers_exist():
    manifest = load_pipeline("cinematic-fast")
    for skill in manifest["required_skills"]:
        assert (ROOT / "skills" / f"{skill}.md").exists(), skill


def test_cinematic_fast_is_reference_aware_and_beta():
    manifest = load_pipeline("cinematic-fast")
    assert manifest["stability"] == "beta"
    assert manifest["reference_input"]["supported"] is True
    assert manifest["reference_input"]["analysis_depth"] == "deep"
    assert {"video_analyzer", "scene_detect", "frame_sampler"} <= set(manifest["reference_input"]["analysis_tools"])


def test_scene_mapping_requires_reference_and_source_evidence() -> None:
    manifest = load_pipeline("cinematic-fast")
    scene_stage = next(stage for stage in manifest["stages"] if stage["name"] == "scene_plan")
    director = (ROOT / "skills/pipelines/cinematic-fast/scene-director.md").read_text(encoding="utf-8")

    for field in ("reference_basis", "source_fit", "mapping_reason", "originality_note"):
        assert field in director
    for field in ("reference_evidence", "direct_segment", "structural_only"):
        assert field in director
    assert "metadata.source_mapping" in director
    assert "reference_media_usage" in director
    assert "shot_intent" in director
    assert {"source_media_review", "video_analysis_brief", "reference_fingerprint"} <= set(
        scene_stage["required_artifacts_in"]
    )
    assert any("explainable mapping" in criterion for criterion in scene_stage["success_criteria"])
    assert any("reference" in criterion and "source_path" in criterion for criterion in scene_stage["success_criteria"])

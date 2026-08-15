from pathlib import Path

from lib.pipeline_loader import get_stage_order, load_pipeline


ROOT = Path(__file__).resolve().parents[2]


def test_cinematic_fast_has_fixed_stage_order_and_two_gates():
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
    assert gated == ["assets", "sample"]
    group = manifest["approval_groups"]["creative_lock"]
    assert group["members"] == ["proposal", "script", "scene_plan", "assets"]
    assert group["terminal_stage"] == "assets"
    assert manifest["stages"][4]["approval_group_terminal"] is True


def test_cinematic_fast_sample_and_compose_contracts():
    manifest = load_pipeline("cinematic-fast")
    stages = {stage["name"]: stage for stage in manifest["stages"]}
    assert stages["assets"]["produces"] == ["asset_plan", "production_lock", "approval_bundle"]
    assert stages["sample"]["produces"] == [
        "asset_manifest", "final_props", "render_plan", "sample_report"
    ]
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


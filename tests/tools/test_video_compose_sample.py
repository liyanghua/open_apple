from pathlib import Path

from lib.render_plan import validate_sample_window
from tools.video.video_compose import VideoCompose
from tools.base_tool import ToolResult


def test_sample_window_is_half_open_and_bounded():
    assert validate_sample_window(180, 540) == (180, 540)


def test_sample_window_rejects_short_or_long_ranges():
    import pytest
    with pytest.raises(ValueError):
        validate_sample_window(0, 299)
    with pytest.raises(ValueError):
        validate_sample_window(0, 451)


def test_sample_adapter_preserves_source_timeline_frames(tmp_path: Path, monkeypatch):
    seen = {}
    def fake_render(self, inputs):
        seen.update(inputs)
        output = Path(inputs["output_path"]); output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b"sample")
        return ToolResult(success=True, data={"output": str(output)}, artifacts=[str(output)])
    monkeypatch.setattr(VideoCompose, "_remotion_render", fake_render)
    result = VideoCompose()._render_sample({"project_dir": str(tmp_path), "edit_decisions": {}, "render_runtime": "remotion"}, {"mode": "sample", "final_props_hash": "a" * 64, "sample": {"startFrame": 180, "endFrameExclusive": 540}})
    assert result.success
    assert seen["sample_frames"] == "180-539"
    assert seen["remotion_width"] == 540 and seen["remotion_height"] == 960


def test_sample_adapter_preserves_atelier_runtime_and_forces_half_scale(
    tmp_path: Path, monkeypatch
):
    seen = {}
    edit_decisions = {
        "render_runtime": "remotion",
        "composition_mode": "atelier",
        "bespoke": {
            "entry": "project/index.tsx", "composition_id": "Product", "scale": 1,
        },
    }

    def fake_render(self, inputs, decisions):
        seen["inputs"] = inputs
        seen["decisions"] = decisions
        output = Path(inputs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"sample")
        return ToolResult(success=True, data={"output": str(output)}, artifacts=[str(output)])

    monkeypatch.setattr(VideoCompose, "_render_via_atelier", fake_render)
    result = VideoCompose()._render_sample(
        {"project_dir": str(tmp_path), "edit_decisions": edit_decisions},
        {
            "mode": "sample",
            "final_props_hash": "a" * 64,
            "sample": {"startFrame": 300, "endFrameExclusive": 750},
        },
    )

    assert result.success
    assert seen["inputs"]["sample_frames"] == "300-749"
    assert seen["decisions"]["bespoke"]["scale"] == 0.5
    assert edit_decisions["bespoke"]["scale"] == 1


def test_atelier_renderer_forwards_sample_frame_window(tmp_path: Path, monkeypatch):
    entry = tmp_path / "index.tsx"
    entry.write_text("export {};", encoding="utf-8")
    output = tmp_path / "sample.mp4"
    seen = {}
    tool = VideoCompose()

    def fake_run(cmd, *, timeout, cwd):
        seen["cmd"] = cmd
        output.write_bytes(b"sample")

    monkeypatch.setattr(tool, "run_command", fake_run)
    monkeypatch.setattr(
        tool, "_stage_atelier_project", lambda entry_path, composer_dir: entry_path
    )
    monkeypatch.setattr(
        tool, "_run_final_review",
        lambda **kwargs: {"status": "pass", "checks": {}, "issues_found": []},
    )
    monkeypatch.setattr(
        tool, "_run_atelier_checks",
        lambda *args: {"stock_reuse_detected": False, "issues": []},
    )

    result = tool._render_via_atelier(
        {"output_path": str(output), "sample_frames": "300-749"},
        {
            "render_runtime": "remotion",
            "composition_mode": "atelier",
            "bespoke": {"entry": str(entry), "composition_id": "Product", "scale": 0.5},
        },
    )

    assert result.success
    assert "--frames=300-749" in seen["cmd"]


def test_atelier_staging_copies_local_json_modules_but_not_media(tmp_path: Path):
    project = tmp_path / "projects" / "product"
    artifacts = project / "artifacts"
    composer = tmp_path / "remotion-composer"
    artifacts.mkdir(parents=True)
    (project / "index.tsx").write_text(
        'import props from "./artifacts/final_props.json";', encoding="utf-8"
    )
    (artifacts / "final_props.json").write_text(
        '{"durationInFrames": 360}', encoding="utf-8"
    )
    (project / "source.mp4").write_bytes(b"media")

    staged_entry = VideoCompose()._stage_atelier_project(project / "index.tsx", composer)

    assert staged_entry.is_file()
    assert (staged_entry.parent / "artifacts" / "final_props.json").is_file()
    assert not (staged_entry.parent / "source.mp4").exists()

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
    result = VideoCompose()._render_framed_window({"project_dir": str(tmp_path), "edit_decisions": {}, "render_runtime": "remotion"}, {"mode": "sample", "final_props_hash": "a" * 64, "sample": {"startFrame": 180, "endFrameExclusive": 540}}, mode="sample")
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

    def fake_render(self, inputs, decisions, *, skip_final_review=False):
        seen["inputs"] = inputs
        seen["decisions"] = decisions
        output = Path(inputs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"sample")
        return ToolResult(success=True, data={"output": str(output)}, artifacts=[str(output)])

    monkeypatch.setattr(VideoCompose, "_render_via_atelier", fake_render)
    result = VideoCompose()._render_framed_window(
        {"project_dir": str(tmp_path), "edit_decisions": edit_decisions},
        {
            "mode": "sample",
            "final_props_hash": "a" * 64,
            "sample": {"startFrame": 300, "endFrameExclusive": 750},
        },
        mode="sample",
    )

    assert result.success
    assert seen["inputs"]["sample_frames"] == "300-749"
    assert seen["decisions"]["bespoke"]["scale"] == 0.5
    assert edit_decisions["bespoke"]["scale"] == 1


def test_window_mode_uses_window_validator_and_half_scale(tmp_path: Path, monkeypatch):
    seen = {}
    def fake_render(self, inputs):
        seen.update(inputs)
        output = Path(inputs["output_path"]); output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b"w")
        return ToolResult(success=True, data={"output": str(output)}, artifacts=[str(output)])
    monkeypatch.setattr(VideoCompose, "_remotion_render", fake_render)
    result = VideoCompose()._render_framed_window(
        {"project_dir": str(tmp_path), "edit_decisions": {}, "render_runtime": "remotion"},
        {"mode": "window", "final_props_hash": "a" * 64, "window": {"startFrame": 0, "endFrameExclusive": 60}},
        mode="window",
    )
    assert result.success
    assert result.data["render_mode"] == "window"
    assert seen["sample_frames"] == "0-59"
    # window validator bounds: 30-90 frames only — surfaced as a failed ToolResult
    invalid = VideoCompose()._render_framed_window(
        {"project_dir": str(tmp_path), "edit_decisions": {}},
        {"mode": "window", "window": {"startFrame": 0, "endFrameExclusive": 120}},
        mode="window",
    )
    assert not invalid.success


def test_explicit_sample_output_is_not_reused_for_a_different_cache_key(
    tmp_path: Path, monkeypatch
):
    calls = []

    def fake_render(self, inputs):
        calls.append(inputs["sample_frames"])
        output = Path(inputs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"sample-{len(calls)}".encode())
        return ToolResult(success=True, data={"output": str(output)}, artifacts=[str(output)])

    monkeypatch.setattr(VideoCompose, "_remotion_render", fake_render)
    output = tmp_path / "sample.mp4"
    base = {
        "mode": "sample",
        "output_path": str(output),
        "sample": {"startFrame": 0, "endFrameExclusive": 300},
    }
    first = VideoCompose()._render_framed_window(
        {"project_dir": str(tmp_path), "edit_decisions": {}},
        {**base, "final_props_hash": "a" * 64},
        mode="sample",
    )
    second = VideoCompose()._render_framed_window(
        {"project_dir": str(tmp_path), "edit_decisions": {}},
        {**base, "final_props_hash": "b" * 64},
        mode="sample",
    )
    assert first.success and second.success
    assert len(calls) == 2
    assert second.data["cache_status"] == "miss"


def test_atelier_renderer_forwards_sample_frame_window(tmp_path: Path, monkeypatch):
    entry = tmp_path / "index.tsx"
    entry.write_text("export {};", encoding="utf-8")
    output = tmp_path / "sample.mp4"
    seen = {}
    tool = VideoCompose()

    def fake_run(cmd, *, cwd, timeout, project_dir, run_id, operation, unit_total=None):
        seen["cmd"] = cmd
        output.write_bytes(b"sample")

    monkeypatch.setattr(tool, "_run_remotion_command", fake_run)
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


def test_render_gradient_validators():
    import pytest
    from lib.render_plan import validate_still_frames, validate_range_render, validate_window

    assert validate_window(0, 30) == (0, 30)
    with pytest.raises(ValueError):
        validate_window(0, 29)
    with pytest.raises(ValueError):
        validate_window(0, 91)

    assert validate_still_frames([0, 449, 899], 900) == [0, 449, 899]
    with pytest.raises(ValueError):
        validate_still_frames([], 900)
    with pytest.raises(ValueError):
        validate_still_frames([0, 1, 2, 3], 900)
    with pytest.raises(ValueError):
        validate_still_frames([900], 900)

    assert validate_range_render(840, 900, timeline_stable=True) == (840, 900)
    with pytest.raises(ValueError):
        validate_range_render(840, 900, timeline_stable=False)
    with pytest.raises(ValueError):
        validate_range_render(0, 900, timeline_stable=True)
    with pytest.raises(ValueError):
        validate_range_render(900, 900, timeline_stable=True)


def test_atelier_still_forces_half_scale_regardless_of_bespoke_scale(tmp_path: Path, monkeypatch):
    """P2-⑦: still route must never inherit production bespoke.scale=1.0."""
    seen = {}
    tool = VideoCompose()

    def fake_run(cmd, *, cwd, timeout, project_dir, run_id, operation, unit_total=None):
        seen.update(cmd=cmd)
        out_png = Path(cmd[5])
        out_png.parent.mkdir(parents=True, exist_ok=True)
        out_png.write_bytes(b"png")

    monkeypatch.setattr(tool, "_run_remotion_command", fake_run)
    monkeypatch.setattr(tool, "_stage_atelier_project", lambda entry_path, composer_dir: entry_path)
    edit_decisions = {
        "render_runtime": "remotion",
        "composition_mode": "atelier",
        "bespoke": {
            "entry": str(tmp_path / "index.tsx"),
            "composition_id": "Product",
            "scale": 1.0,
        },
    }
    (tmp_path / "index.tsx").write_text("export {};", encoding="utf-8")
    plan = {"mode": "still", "still": {"frames": [0], "totalFrames": 900, "scale": 0.5}}
    result = tool._render_stills(
        {"project_dir": str(tmp_path), "edit_decisions": edit_decisions, "render_plan": plan},
        plan,
    )
    assert result.success, result.error
    assert "--scale=0.5" in seen["cmd"]
    assert "--scale=1" not in seen["cmd"]

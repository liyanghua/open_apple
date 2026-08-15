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

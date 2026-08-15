from pathlib import Path

from tools.analysis.frame_sampler import FrameSampler


def _inputs(path: Path, output: Path) -> dict:
    return {
        "input_path": str(path),
        "strategy": "count",
        "count": 4,
        "format": "jpg",
        "quality": 2,
        "output_dir": str(output),
        "analysis_version": "media-v1",
    }


def test_frame_sampler_key_follows_content_and_parameters_not_paths(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    copy = tmp_path / "copy.mp4"
    first.write_bytes(b"aaaa")
    copy.write_bytes(b"aaaa")
    tool = FrameSampler()

    baseline = tool.idempotency_key(_inputs(first, tmp_path / "out-a"))
    assert baseline == tool.idempotency_key(_inputs(copy, tmp_path / "out-b"))

    changed = _inputs(copy, tmp_path / "out-b")
    changed["count"] = 5
    assert baseline != tool.idempotency_key(changed)

    copy.write_bytes(b"bbbb")
    assert baseline != tool.idempotency_key(_inputs(copy, tmp_path / "out-b"))


def test_frame_sampler_key_includes_scene_guided_inputs_and_versions(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    tool = FrameSampler()
    values = {
        "input_path": str(media),
        "strategy": "scene_guided",
        "scene_boundaries": [{"start_seconds": 0.0, "end_seconds": 2.0}],
        "max_frames": 10,
        "format": "jpg",
        "quality": 2,
        "analysis_version": "v1",
    }
    baseline = tool.idempotency_key(values)
    assert baseline != tool.idempotency_key({**values, "max_frames": 11})
    assert baseline != tool.idempotency_key({**values, "analysis_version": "v2"})

    tool.version = "0.2.0"
    assert baseline != tool.idempotency_key(values)


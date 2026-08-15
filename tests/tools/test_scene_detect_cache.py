from pathlib import Path

from tools.analysis.scene_detect import SceneDetect


def test_scene_detect_key_uses_content_normalized_params_and_versions(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    copy = tmp_path / "copy.mp4"
    first.write_bytes(b"same")
    copy.write_bytes(b"same")
    tool = SceneDetect()
    inputs = {
        "input_path": str(first),
        "method": "content",
        "threshold": 0.3,
        "min_scene_length_seconds": 1.0,
        "output_path": str(tmp_path / "a.json"),
        "analysis_version": "v1",
    }
    baseline = tool.idempotency_key(inputs)
    relocated = {**inputs, "input_path": str(copy), "output_path": str(tmp_path / "b.json")}
    assert baseline == tool.idempotency_key(relocated)
    assert baseline != tool.idempotency_key({**inputs, "threshold": 0.4})
    assert baseline != tool.idempotency_key({**inputs, "min_scene_length_seconds": 2.0})
    assert baseline != tool.idempotency_key({**inputs, "analysis_version": "v2"})

    copy.write_bytes(b"else")
    assert baseline != tool.idempotency_key(relocated)


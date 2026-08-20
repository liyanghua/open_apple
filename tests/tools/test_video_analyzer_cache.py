import json
from pathlib import Path

from lib.artifact_hashing import verify_hashes
from tools.analysis.video_analyzer import VideoAnalyzer


def test_video_analyzer_key_reuses_relocated_content_and_hashes_all_analysis_inputs(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    copy = tmp_path / "copy.mp4"
    first.write_bytes(b"same")
    copy.write_bytes(b"same")
    tool = VideoAnalyzer()
    inputs = {
        "source": str(first),
        "analysis_depth": "deep",
        "max_keyframes": 20,
        "output_dir": str(tmp_path / "out-a"),
        "analysis_version": "v1",
    }
    baseline = tool.idempotency_key(inputs)
    relocated = {**inputs, "source": str(copy), "output_dir": str(tmp_path / "out-b")}
    assert baseline == tool.idempotency_key(relocated)
    assert baseline != tool.idempotency_key({**inputs, "analysis_depth": "standard"})
    assert baseline != tool.idempotency_key({**inputs, "max_keyframes": 10})
    assert baseline != tool.idempotency_key({**inputs, "analysis_version": "v2"})

    copy.write_bytes(b"else")
    assert baseline != tool.idempotency_key(relocated)


def test_deep_analysis_writes_hashed_fingerprint_sidecar_without_claiming_final_artifact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"reference")
    project = tmp_path / "project"
    output_dir = project / "analysis" / "reference"
    output_dir.mkdir(parents=True)
    tool = VideoAnalyzer()
    brief = {
        "structure_analysis": {"total_scenes": 2, "pacing_profile": {"average_scene_duration": 1.2}},
        "style_profile": {"transition_types": ["cut"]},
    }

    sidecar = tool._write_analysis_fingerprint_sidecar(
        source=source,
        depth="deep",
        max_keyframes=20,
        analysis_version="v1",
        project_dir=project,
        output_dir=output_dir,
        brief=brief,
    )

    persisted = json.loads(
        (output_dir / "reference_analysis_fingerprint.json").read_text()
    )
    assert sidecar == persisted
    assert sidecar["canonical_request"]["max_keyframes"] == 20
    assert sidecar["abstract_structure"]["total_scenes"] == 2
    assert verify_hashes(sidecar).valid
    assert not (project / "artifacts" / "reference_fingerprint.json").exists()

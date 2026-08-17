"""Range route provenance tests (P1-②/③/④) with synthetic media."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose


def _synthetic_master(tmp_path: Path) -> tuple[Path, str]:
    master = tmp_path / "master.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "testsrc=duration=2:size=320x180:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(master),
        ],
        check=True, capture_output=True,
    )
    return master, hashlib.sha256(master.read_bytes()).hexdigest()


def _plan(master: Path, sha: str, output: Path, *, profile: str | None = "social_vertical_1080p30") -> dict:
    return {
        "mode": "range",
        "profile": profile,
        "durationInFrames": 60,
        "previous_timeline_hash": "e" * 64,
        "range": {
            "fromFrame": 40,
            "totalFrames": 60,
            "timeline_stable": True,
            "master": {
                "path": str(master), "sha256": sha,
                "profile_hash": "b" * 64, "visual_timeline_hash": "e" * 64,
            },
        },
        "output_path": str(output),
    }


def _fake_tail_render(inputs):
    path = Path(inputs["output_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "testsrc2=duration=0.666:size=320x180:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(path),
        ],
        check=True, capture_output=True,
    )
    return ToolResult(success=True, data={"output": str(path)}, artifacts=[str(path)])


def _fake_short_tail_render(inputs):
    path = Path(inputs["output_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "testsrc2=duration=0.5:size=320x180:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(path),
        ],
        check=True, capture_output=True,
    )
    return ToolResult(success=True, data={"output": str(path)}, artifacts=[str(path)])


def _tool(tmp_path: Path) -> VideoCompose:
    tool = VideoCompose()
    tool._render_via_atelier = lambda inputs, decisions, skip_final_review=False: _fake_tail_render(inputs)
    tool._run_final_review = lambda **kw: {"status": "pass", "checks": {}, "issues_found": []}
    return tool


def _atelier_inputs(tmp_path: Path) -> dict:
    return {
        "project_dir": str(tmp_path),
        "edit_decisions": {
            "render_runtime": "remotion",
            "composition_mode": "atelier",
            "bespoke": {"entry": "x.tsx", "composition_id": "C"},
        },
    }


def test_range_rejects_sha_mismatched_master(tmp_path: Path):
    master, sha = _synthetic_master(tmp_path)
    plan = _plan(master, "0" * 64, tmp_path / "out.mp4")
    result = _tool(tmp_path)._render_range(_atelier_inputs(tmp_path), plan)
    assert not result.success
    assert "sha256 mismatch" in result.error


def test_range_rejects_profile_mismatched_master_and_stale_output(tmp_path: Path):
    master, sha = _synthetic_master(tmp_path)
    out = tmp_path / "out.mp4"
    out.write_bytes(b"stale")
    result = _tool(tmp_path)._render_range(_atelier_inputs(tmp_path), _plan(master, sha, out))
    assert not result.success
    assert "profile mismatch" in result.error


def test_range_pipeline_writes_provenance_and_caches(tmp_path: Path):
    master, sha = _synthetic_master(tmp_path)
    out = tmp_path / "out.mp4"
    tool = _tool(tmp_path)
    result = tool._render_range(_atelier_inputs(tmp_path), _plan(master, sha, out, profile=None))
    assert result.success, result.error

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(out)],
        capture_output=True, text=True,
    )
    data = json.loads(probe.stdout)
    assert abs(float(data["format"]["duration"]) - 2.0) < 0.15

    sidecar = out.with_name(out.stem + ".range_provenance.json")
    assert sidecar.is_file()
    provenance = json.loads(sidecar.read_text())
    assert provenance["output_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert provenance["output_probe"]["duration_seconds"] == round(
        float(data["format"]["duration"]), 3
    )

    # untouched output -> authenticated cache hit
    hit = tool._render_range(_atelier_inputs(tmp_path), _plan(master, sha, out, profile=None))
    assert hit.success and hit.data["cache_status"] == "hit"


def test_range_cache_miss_when_output_tampered(tmp_path: Path):
    master, sha = _synthetic_master(tmp_path)
    out = tmp_path / "out.mp4"
    tool = _tool(tmp_path)
    first = tool._render_range(_atelier_inputs(tmp_path), _plan(master, sha, out, profile=None))
    assert first.success

    # tamper the output file (sidecar untouched)
    out.write_bytes(b"tampered!")
    second = tool._render_range(_atelier_inputs(tmp_path), _plan(master, sha, out, profile=None))
    assert second.success
    assert second.data["cache_status"] == "miss", "tampered output must never be a cache hit"
    # and the re-render repaired the artifact
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(out)],
        capture_output=True, text=True,
    )
    assert json.loads(probe.stdout)["format"]["duration"]


def test_range_rejects_unstable_timeline_plan(tmp_path: Path):
    from lib.render_plan import validate_range_render

    with pytest.raises(ValueError):
        validate_range_render(40, 60, timeline_stable=False)


def test_range_rejects_missing_declared_audio(tmp_path: Path):
    master, sha = _synthetic_master(tmp_path)
    plan = _plan(master, sha, tmp_path / "out.mp4", profile=None)
    plan["audio"] = {"path": str(tmp_path / "missing.wav"), "sha256": "f" * 64}
    result = _tool(tmp_path)._render_range(_atelier_inputs(tmp_path), plan)
    assert not result.success
    assert "audio" in result.error.lower() and "missing" in result.error.lower()


def test_range_rejects_declared_audio_sha_mismatch(tmp_path: Path):
    master, sha = _synthetic_master(tmp_path)
    audio = tmp_path / "mix.wav"
    audio.write_bytes(b"not-the-approved-mix")
    plan = _plan(master, sha, tmp_path / "out.mp4", profile=None)
    plan["audio"] = {"path": str(audio), "sha256": "f" * 64}
    result = _tool(tmp_path)._render_range(_atelier_inputs(tmp_path), plan)
    assert not result.success
    assert "audio sha256 mismatch" in result.error.lower()


def test_range_rejects_output_with_wrong_exact_frame_count(tmp_path: Path):
    master, sha = _synthetic_master(tmp_path)
    plan = _plan(master, sha, tmp_path / "out.mp4", profile=None)
    plan.pop("audio", None)
    tool = _tool(tmp_path)
    tool._render_via_atelier = (
        lambda inputs, decisions, skip_final_review=False: _fake_short_tail_render(inputs)
    )
    result = tool._render_range(_atelier_inputs(tmp_path), plan)
    assert not result.success
    assert "frame count" in result.error.lower()

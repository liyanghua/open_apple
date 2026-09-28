"""Contract tests for the bounded temporal caption diagnostic adapter."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tools.tool_registry import ToolRegistry


def test_registry_discovers_temporal_caption_repair():
    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("temporal_caption_repair")
    assert tool is not None
    assert tool.capability == "video_post"
    assert tool.provider == "local"
    assert tool.estimate_cost({}) == 0.0
    assert "python:cv2" in tool.dependencies


@pytest.fixture
def video_fixture(tmp_path):
    height, width, count = 96, 128, 5
    rng = np.random.default_rng(19)
    texture = rng.integers(0, 256, (height, width + 20, 3), dtype=np.uint8)
    clean = np.stack([texture[:, i * 2:i * 2 + width] for i in range(count)])
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[64:72, 49:66] = 255
    burned = clean.copy()
    burned[:, mask != 0] = 16
    input_path = tmp_path / "source.mkv"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", "25", "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0",
        str(input_path),
    ], input=burned.tobytes(), check=True, timeout=20)
    mask_path = tmp_path / "mask.pgm"
    mask_path.write_bytes(f"P5\n{width} {height}\n255\n".encode() + mask.tobytes())
    return input_path, mask_path, clean, burned, mask


def _args(video_fixture, output_dir):
    input_path, mask_path, *_ = video_fixture
    return dict(input_path=str(input_path), mask_path=str(mask_path), start_frame=0,
                end_frame_exclusive=5, output_dir=str(output_dir), single_shot_verified=True)


@pytest.mark.parametrize("change", [
    {"single_shot_verified": False}, {"single_shot_verified": 1},
    {"start_frame": True}, {"start_frame": -1}, {"start_frame": 5},
    {"end_frame_exclusive": 121}, {"max_donors": 13}, {"min_coverage": 1.1},
])
def test_rejects_bad_request_before_creating_output(video_fixture, tmp_path, change):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    output = tmp_path / "output"
    args = _args(video_fixture, output)
    args.update(change)
    result = TemporalCaptionRepair().execute(args)
    assert not result.success
    assert not output.exists()


def test_rejects_existing_or_alias_output(video_fixture, tmp_path):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    tool = TemporalCaptionRepair()
    existing = tmp_path / "existing"
    existing.mkdir()
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    for destination in [existing, tmp_path, tmp_path / "alias" / "out"]:
        result = tool.execute(_args(video_fixture, destination))
        assert not result.success
    assert sorted(p.name for p in existing.iterdir()) == []


def test_rejects_nonbinary_or_wrong_geometry_mask(video_fixture, tmp_path):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    input_path, mask_path, _, _, mask = video_fixture
    for payload in [mask.copy(), np.zeros((95, 128), dtype=np.uint8)]:
        if payload.shape == mask.shape:
            payload[65, 50] = 128
        mask_path.write_bytes(f"P5\n{payload.shape[1]} {payload.shape[0]}\n255\n".encode() + payload.tobytes())
        output = tmp_path / "out"
        result = TemporalCaptionRepair().execute(_args(video_fixture, output))
        assert not result.success
        assert not output.exists()


def test_rejects_vfr_by_timestamps(video_fixture, tmp_path):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    source, *_ = video_fixture
    vfr = tmp_path / "vfr.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-vf", "setpts=if(eq(N\\,2)\\,PTS+0.04/TB\\,PTS)", "-fps_mode", "vfr",
                    "-c:v", "ffv1", str(vfr)], check=True, timeout=20)
    args = _args(video_fixture, tmp_path / "out")
    args["input_path"] = str(vfr)
    result = TemporalCaptionRepair().execute(args)
    assert not result.success
    assert not (tmp_path / "out").exists()


def test_end_to_end_outputs_diagnostic_only_and_lossless_master(video_fixture, tmp_path):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    source, mask_path, _, burned, mask = video_fixture
    output = tmp_path / "repair"
    result = TemporalCaptionRepair().execute(_args(video_fixture, output))
    assert result.success, result.error
    report = json.loads((output / "report.json").read_text())
    assert report["accepted_for_production"] is False
    assert report["human_review_required"] is True
    assert report["source"]["frame_interval"] == [0, 5]
    assert report["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["mask"]["sha256"] == hashlib.sha256(mask_path.read_bytes()).hexdigest()
    assert report["verification"]["master_outside_mask_exact"] is True
    assert report["preview"]["lossy_not_verified_exact"] is True
    assert report["preview"]["audio"] == "absent"
    assert (output / "master.mkv").is_file()
    assert (output / "review.mp4").is_file()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                            "-of", "json", str(output / "review.mp4")], capture_output=True, text=True, check=True)
    assert [s["codec_type"] for s in json.loads(probe.stdout)["streams"]] == ["video"]
    decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output / "master.mkv"),
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True)
    master = np.frombuffer(decoded.stdout, np.uint8).reshape(burned.shape)
    assert np.array_equal(master[:, mask == 0], burned[:, mask == 0])


def test_exact_half_open_interval(video_fixture, tmp_path):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    args = _args(video_fixture, tmp_path / "subclip")
    args.update(start_frame=1, end_frame_exclusive=4)
    result = TemporalCaptionRepair().execute(args)
    assert result.success, result.error
    assert result.data["source"]["frame_interval"] == [1, 4]
    assert result.data["verification"]["verified_frames"] == 3


def test_rejects_combined_memory_bound_before_decode(video_fixture, tmp_path, monkeypatch):
    from tools.video import temporal_caption_repair as adapter
    monkeypatch.setattr(adapter, "_probe_metadata", lambda path: (1440, 1440, __import__("fractions").Fraction(25), "1/1000"))
    monkeypatch.setattr(adapter, "_probe_timestamps", lambda *a: pytest.fail("timestamp probe ran before resource gate"))
    args = _args(video_fixture, tmp_path / "too-large")
    args["end_frame_exclusive"] = 19
    result = adapter.TemporalCaptionRepair().execute(args)
    assert not result.success
    assert "memory" in result.error
    assert not (tmp_path / "too-large").exists()


def test_raced_output_directory_is_never_modified(video_fixture, tmp_path, monkeypatch):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    output = tmp_path / "race-output"
    original_mkdir = Path.mkdir

    def race_mkdir(path, *args, **kwargs):
        if path == output:
            original_mkdir(path, *args, **kwargs)
            (path / "error.json").write_text("owner's sentinel")
            raise FileExistsError("raced creation")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", race_mkdir)
    result = TemporalCaptionRepair().execute(_args(video_fixture, output))
    assert not result.success
    assert (output / "error.json").read_text() == "owner's sentinel"


def test_rejects_changing_frame_geometry(video_fixture, monkeypatch):
    from tools.video import temporal_caption_repair as adapter
    from fractions import Fraction
    fake = {"streams": [{"width": 128, "height": 96, "avg_frame_rate": "25/1",
                         "r_frame_rate": "25/1", "time_base": "1/1000"}],
            "frames": [{"best_effort_timestamp": i * 40, "width": 128 if i < 2 else 120,
                        "height": 96} for i in range(5)]}
    monkeypatch.setattr(adapter, "_capture", lambda *a, **k: json.dumps(fake).encode())
    with pytest.raises(ValueError, match="geometry"):
        adapter._probe_timestamps(video_fixture[0], 128, 96, Fraction(25), "1/1000")


def test_rejects_real_video_display_rotation_before_core(video_fixture, tmp_path, monkeypatch):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    from lib import temporal_caption_repair as core
    source, *_ = video_fixture
    encoded = tmp_path / "encoded.mp4"
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(encoded)], check=True, timeout=20)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-display_rotation:v:0", "90",
                    "-i", str(encoded), "-c", "copy", str(rotated)], check=True, timeout=20)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(rotated)],
                           capture_output=True, text=True, check=True)
    assert json.loads(probe.stdout)["streams"][0]["side_data_list"][0]["rotation"] == 90
    monkeypatch.setattr(core, "repair_frames", lambda *a, **k: pytest.fail("core ran on rotated source"))
    output = tmp_path / "rotated-output"
    args = _args(video_fixture, output)
    args["input_path"] = str(rotated)
    result = TemporalCaptionRepair().execute(args)
    assert not result.success
    assert "rotation" in result.error.lower() or "display transform" in result.error.lower()
    assert not output.exists()


@pytest.mark.parametrize("width,height", [(129, 96), (128, 97)])
def test_rejects_odd_source_geometry_before_output(tmp_path, width, height):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    frames = np.zeros((3, height, width, 3), dtype=np.uint8)
    source = tmp_path / "odd.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{width}x{height}", "-r", "25", "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0",
                    str(source)], input=frames.tobytes(), check=True, timeout=20)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[20:22, 20:22] = 255
    mask_path = tmp_path / "mask.pgm"
    mask_path.write_bytes(f"P5\n{width} {height}\n255\n".encode() + mask.tobytes())
    output = tmp_path / "odd-output"
    result = TemporalCaptionRepair().execute(dict(input_path=str(source), mask_path=str(mask_path),
        start_frame=0, end_frame_exclusive=3, output_dir=str(output), single_shot_verified=True))
    assert not result.success
    assert "even" in result.error.lower()
    assert not output.exists()


def test_capture_enforces_byte_and_time_limits():
    from tools.video.temporal_caption_repair import _capture
    with pytest.raises(ValueError, match="bounded output limit"):
        _capture([sys.executable, "-c", "print('x' * 1000)"], limit=16, timeout=5)
    with pytest.raises(ValueError, match="timed out"):
        _capture([sys.executable, "-c", "import time;time.sleep(3)"], limit=16, timeout=1)


def test_audio_source_produces_video_only_review(video_fixture, tmp_path):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    source, *_ = video_fixture
    with_audio = tmp_path / "with-audio.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000", "-shortest",
                    "-c:v", "copy", "-c:a", "pcm_s16le", str(with_audio)], check=True, timeout=20)
    args = _args(video_fixture, tmp_path / "no-audio-review")
    args["input_path"] = str(with_audio)
    result = TemporalCaptionRepair().execute(args)
    assert result.success, result.error
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                            "-of", "json", str(tmp_path / "no-audio-review" / "review.mp4")],
                           capture_output=True, text=True, check=True)
    assert [s["codec_type"] for s in json.loads(probe.stdout)["streams"]] == ["video"]
    assert result.data["preview"]["audio"] == "absent"


def test_stationary_caption_reports_insufficient_evidence(video_fixture, tmp_path):
    from tools.video.temporal_caption_repair import TemporalCaptionRepair
    _, _, _, burned, _ = video_fixture
    source = tmp_path / "stationary.mkv"
    stationary = np.repeat(burned[:1], 5, axis=0)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", "128x96", "-r", "25", "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0",
                    str(source)], input=stationary.tobytes(), check=True, timeout=20)
    args = _args(video_fixture, tmp_path / "stationary-review")
    args["input_path"] = str(source)
    result = TemporalCaptionRepair().execute(args)
    assert result.success, result.error
    assert result.data["status"] == "insufficient_evidence"
    assert result.data["coverage_gate_passed"] is False
    assert result.data["accepted_for_production"] is False

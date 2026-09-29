"""Local FFmpeg fixtures: decode evidence never implies semantic continuity."""
import hashlib
import importlib
import json
import shutil
import subprocess

import pytest

from lib import media_fingerprint


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")


def generate(path, *, fps=30, crf=18, opening="red", frames=120):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color={opening}:s=64x64:r={fps}",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-vf", "drawbox=enable='gte(t,3)':color=blue:t=fill",
        "-frames:v", str(frames), "-c:v", "libx264", "-crf", str(crf), "-c:a", "aac", "-shortest", "-y", str(path)],
        check=True, capture_output=True, timeout=30)
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_actual_join_decode_checks_frame90_pts_and_audio(tmp_path):
    from lib import opening_freeze
    media = generate(tmp_path / "join.mp4")
    result = opening_freeze.verify_opening_join(tmp_path, media_ref=media, duration_frames=120)
    assert result["status"] == "pass"
    assert result["measurement"]["interval_frames"] == [75, 105]
    assert len(result["measurement"]["video"]["frames"]) == 30
    assert result["measurement"]["video"]["frames"][15]["frame"] == 90
    assert result["measurement"]["audio"]["samples"] == 48000
    assert result["semantic_continuity_status"] == "not_run"


def test_encoding_bytes_do_not_gate_body_match(tmp_path):
    a = generate(tmp_path / "a.mp4", crf=15)
    b = generate(tmp_path / "b.mp4", crf=35, opening="green")
    assert a["sha256"] != b["sha256"]
    result = media_fingerprint.compare_decoded_intervals(tmp_path / "a.mp4", tmp_path / "b.mp4", start_frame=90, end_frame=120)
    assert result["status"] == "pass"
    assert result["advisory_only"] is True
    assert result["freeze_verified"] is False


def test_wrong_fps_and_truncated_join_fail(tmp_path):
    from lib import opening_freeze
    media = generate(tmp_path / "short.mp4", fps=24, frames=84)
    result = opening_freeze.verify_opening_join(tmp_path, media_ref=media, duration_frames=120)
    assert result["status"] == "fail"


def test_changed_media_hash_errors_before_decode(tmp_path):
    from lib import opening_freeze
    media = generate(tmp_path / "join.mp4")
    media["sha256"] = "a" * 64
    assert opening_freeze.verify_opening_join(tmp_path, media_ref=media, duration_frames=120)["status"] == "error"


def test_join_read_adapter_rechecks_measurements_and_current_media(tmp_path):
    from lib import opening_freeze
    from lib.opening_freeze_checks import evaluate_join_measurement
    media = generate(tmp_path / "join.mp4")
    measurement = opening_freeze.verify_opening_join(tmp_path, media_ref=media, duration_frames=120)
    path = tmp_path / "measured.json"
    path.write_text(json.dumps(measurement))
    ref = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert evaluate_join_measurement(tmp_path, measurement_ref=ref, media_ref=media, duration_frames=120)["status"] == "pass"
    measurement["measurement"]["video"]["frames"][15]["pts"] = 89
    measurement["status"] = "pass"
    path.write_text(json.dumps(measurement))
    ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert evaluate_join_measurement(tmp_path, measurement_ref=ref, media_ref=media, duration_frames=120)["status"] == "error"
    (tmp_path / "join.mp4").write_bytes(b"changed")
    assert evaluate_join_measurement(tmp_path, measurement_ref=ref, media_ref=media, duration_frames=120)["status"] == "error"


def test_frame90_decoded_difference_is_observed_separately(tmp_path):
    generate(tmp_path / "a.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp_path / "a.mp4"), "-vf", "drawbox=enable='eq(n,90)':color=yellow:t=fill",
        "-c:v", "libx264", "-c:a", "copy", "-y", str(tmp_path / "b.mp4")], check=True, capture_output=True, timeout=30)
    observation = media_fingerprint.compare_decoded_intervals(tmp_path / "a.mp4", tmp_path / "b.mp4", start_frame=90, end_frame=120)
    assert observation["decoded_body_match"] is False
    assert observation["freeze_verified"] is False

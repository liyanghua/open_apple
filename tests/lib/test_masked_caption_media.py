"""Media invariants for the fixed s01 masked-caption trial."""

import subprocess
import json

import numpy as np
import pytest

from lib.masked_caption_media import composite_frame, padding_map, stream_rgb, encode_rgb, verify_video


def test_padding_map_preserves_all_38_source_frames():
    mapping = padding_map()
    assert len(mapping) == 81
    assert mapping[:21] == [0] * 21
    assert mapping[21:59] == list(range(38))
    assert mapping[59:] == [37] * 22


def test_composite_only_changes_exact_glyph_pixels():
    source = np.arange(12 * 16 * 3, dtype=np.uint8).reshape(12, 16, 3)
    candidate = np.full_like(source, 245)
    mask = np.zeros((12, 16), dtype=bool)
    mask[4, 4] = True
    mask[6, 9] = True
    result = composite_frame(source, candidate, mask)
    assert np.array_equal(result[~mask], source[~mask])
    assert np.array_equal(result[mask], candidate[mask])
    assert np.array_equal(source[~mask], np.arange(12 * 16 * 3, dtype=np.uint8).reshape(12, 16, 3)[~mask])


def test_streaming_lossless_round_trip_and_frame_contract(tmp_path):
    width, height = 16, 12
    frames = [np.full((height, width, 3), i * 23, dtype=np.uint8) for i in range(4)]
    path = tmp_path / "candidate.mkv"
    encode_rgb(path, iter(frames), width, height, 30, codec="ffv1")
    assert verify_video(path, width, height, 30, 4) == 4
    decoded = list(stream_rgb(path, width, height, expected_frames=4))
    assert all(np.array_equal(a, b) for a, b in zip(frames, decoded))
    with pytest.raises(ValueError, match="frame count"):
        verify_video(path, width, height, 30, 5)
    with pytest.raises(ValueError, match="geometry"):
        verify_video(path, width + 2, height, 30, 4)
    with pytest.raises(ValueError, match="frame rate"):
        verify_video(path, width, height, 25, 4)


def test_rejects_vfr_and_corrupt_video(tmp_path):
    width, height = 16, 12
    path = tmp_path / "base.mkv"
    encode_rgb(path, (np.full((height, width, 3), i, dtype=np.uint8) for i in range(4)), width, height, 30, codec="ffv1")
    vfr = tmp_path / "vfr.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                    "setpts=if(eq(N\\,2)\\,PTS+0.04/TB\\,PTS)", "-fps_mode", "vfr",
                    "-c:v", "ffv1", str(vfr)], check=True, timeout=20)
    with pytest.raises(ValueError, match="VFR"):
        verify_video(vfr, width, height, 30, 4)
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    with pytest.raises(ValueError):
        verify_video(broken, width, height, 30, 4)


def test_lossless_upload_encoding_and_rotation_rejection(tmp_path):
    width, height = 16, 12
    random = np.random.default_rng(7)
    frames = [random.integers(0, 256, (height, width, 3), dtype=np.uint8) for _ in range(4)]
    video = tmp_path / "upload.mp4"
    encode_rgb(video, iter(frames), width, height, 30, codec="h264rgb")
    assert verify_video(video, width, height, 30, 4) == 4
    assert all(np.array_equal(a, b) for a, b in zip(frames, stream_rgb(video, width, height, expected_frames=4)))
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(video),
                    "-c", "copy", str(rotated)], check=True, timeout=20)
    with pytest.raises(ValueError, match="rotation"):
        verify_video(rotated, width, height, 30, 4)


def test_contract_cannot_change_fixed_settings(tmp_path):
    from lib.masked_caption_media import PILOT_SOURCE_SHA256, PILOT_MASK_SHA256, validate_contract
    path = tmp_path / "repair_contract.json"
    path.write_text(json.dumps({"version": 1, "frame_map": padding_map(),
        "source": {"sha256": PILOT_SOURCE_SHA256, "path": "missing", "frame_interval": [0, 38]},
        "mask": {"sha256": PILOT_MASK_SHA256, "path": "missing", "polarity": "255=replace"},
        "geometry": [720, 1280], "fps": 16, "padded_frames": 81,
        "encoding": "libx264rgb-crf0", "audio": "absent", "pilot": "s01_wan_vace14b_once"}))
    with pytest.raises(ValueError, match="settings"):
        validate_contract(path)


def test_prepared_video_cannot_include_audio(tmp_path):
    video = tmp_path / "video.mkv"
    encode_rgb(video, (np.zeros((12, 16, 3), dtype=np.uint8) for _ in range(4)), 16, 12, 30, codec="ffv1")
    audio_video = tmp_path / "audio.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=mono", "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "pcm_s16le", "-t", "0.134", str(audio_video)], check=True, timeout=20)
    with pytest.raises(ValueError, match="silent"):
        verify_video(audio_video, 16, 12, 30, 4)

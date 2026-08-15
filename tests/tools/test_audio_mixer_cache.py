from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.audio.audio_mixer import AudioMixer
from tools.base_tool import ToolResult


def _inputs(speech: Path, music: Path) -> dict:
    return {
        "operation": "full_mix",
        "tracks": [
            {"path": str(speech), "role": "speech", "volume": 1.0,
             "start_seconds": 0.0, "fade_in_seconds": 0.1, "fade_out_seconds": 0.2},
            {"path": str(music), "role": "music", "volume": 0.2, "start_seconds": 0.0},
        ],
        "ducking": {"enabled": True, "music_volume_during_speech": 0.15,
                    "attack_ms": 200, "release_ms": 500},
        "normalize": True, "loudnorm_target": -14, "target_duration": 30.0,
        "segments": [{"start": 0.0, "end": 10.0}], "fade_duration": 0.5,
        "output_path": "/tmp/mix.wav",
    }


def test_mixer_key_uses_track_bytes_not_paths(tmp_path: Path) -> None:
    speech, music, copied = tmp_path / "speech.wav", tmp_path / "music.wav", tmp_path / "copied.wav"
    speech.write_bytes(b"speech")
    music.write_bytes(b"music")
    shutil.copyfile(speech, copied)
    tool = AudioMixer()
    baseline = tool.idempotency_key(_inputs(speech, music))
    relocated = _inputs(copied, music)
    relocated["output_path"] = "/tmp/other.wav"
    assert baseline == tool.idempotency_key(relocated)
    copied.write_bytes(b"change")
    assert baseline != tool.idempotency_key(relocated)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["tracks"][0].update(volume=0.8),
        lambda value: value["tracks"][0].update(start_seconds=1.0),
        lambda value: value["tracks"][0].update(fade_in_seconds=0.3),
        lambda value: value["tracks"][0].update(fade_out_seconds=0.4),
        lambda value: value["ducking"].update(attack_ms=300),
        lambda value: value.update(normalize=False),
        lambda value: value.update(loudnorm_target=-16),
        lambda value: value.update(target_duration=29.0),
        lambda value: value.update(segments=[{"start": 1.0, "end": 9.0}]),
        lambda value: value.update(fade_duration=1.0),
    ],
)
def test_mixer_key_covers_every_output_affecting_setting(tmp_path: Path, mutate) -> None:
    speech, music = tmp_path / "speech.wav", tmp_path / "music.wav"
    speech.write_bytes(b"speech")
    music.write_bytes(b"music")
    baseline, changed = _inputs(speech, music), _inputs(speech, music)
    mutate(changed)
    tool = AudioMixer()
    assert tool.idempotency_key(baseline) != tool.idempotency_key(changed)


def test_mixer_key_includes_tool_and_ffmpeg_revision(tmp_path: Path, monkeypatch) -> None:
    speech, music = tmp_path / "speech.wav", tmp_path / "music.wav"
    speech.write_bytes(b"speech")
    music.write_bytes(b"music")
    tool = AudioMixer()
    monkeypatch.setattr(tool, "_ffmpeg_revision", lambda: "ffmpeg-a")
    baseline = tool.idempotency_key(_inputs(speech, music))
    monkeypatch.setattr(tool, "_ffmpeg_revision", lambda: "ffmpeg-b")
    assert baseline != tool.idempotency_key(_inputs(speech, music))
    monkeypatch.setattr(tool, "_ffmpeg_revision", lambda: "ffmpeg-a")
    tool.version = "next"
    assert baseline != tool.idempotency_key(_inputs(speech, music))


def test_mixer_execute_reuses_cache_and_rebuilds_after_corruption(tmp_path: Path, monkeypatch) -> None:
    speech, music = tmp_path / "speech.wav", tmp_path / "music.wav"
    speech.write_bytes(b"speech")
    music.write_bytes(b"music")
    calls = {"count": 0}

    def fake_mix(inputs):
        calls["count"] += 1
        output = Path(inputs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mixed")
        return ToolResult(success=True, data={"output": str(output)}, artifacts=[str(output)])

    monkeypatch.setattr(AudioMixer, "_full_mix", staticmethod(fake_mix))
    inputs = _inputs(speech, music)
    inputs["project_dir"] = str(tmp_path / "project")
    first = AudioMixer().execute(inputs)
    second = AudioMixer().execute(inputs)
    assert first.success and second.success
    assert second.data["cache_status"] == "hit"
    assert calls["count"] == 1

    key = AudioMixer().idempotency_key(inputs)
    (tmp_path / "project" / ".cache" / "audio" / key / "output.wav").write_bytes(b"corrupt")
    third = AudioMixer().execute(inputs)
    assert third.data["cache_status"] == "miss"
    assert calls["count"] == 2

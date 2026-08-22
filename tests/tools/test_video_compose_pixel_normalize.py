"""Pixel-format normalization tests (评审 P2 B2 固化债)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import lib.render_plan
from tools.video.video_compose import VideoCompose


def _probe(pix_fmt: str):
    return {"streams": [{"codec_type": "video", "pix_fmt": pix_fmt}]}


class _FakeCompleted:
    returncode = 0


def test_normalize_reencodes_yuvj420p_output(monkeypatch, tmp_path: Path):
    output = tmp_path / "render.mp4"
    output.write_bytes(b"video")

    def fake_probe(path):
        assert Path(path) == output
        return _probe("yuvj420p")

    def fake_run(cmd, capture_output):
        temp = Path(cmd[-1])
        temp.write_bytes(b"normalized")
        return _FakeCompleted()

    monkeypatch.setattr(lib.render_plan, "probe_media", fake_probe)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert VideoCompose()._normalize_to_yuv420p(output) is True
    assert output.read_bytes() == b"normalized"


def test_normalize_is_noop_for_yuv420p(monkeypatch, tmp_path: Path):
    output = tmp_path / "render.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(lib.render_plan, "probe_media", lambda path: _probe("yuv420p"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ffmpeg must not run")))
    assert VideoCompose()._normalize_to_yuv420p(output) is False
    assert output.read_bytes() == b"video"


def test_normalize_swallows_ffmpeg_failure(monkeypatch, tmp_path: Path):
    output = tmp_path / "render.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(lib.render_plan, "probe_media", lambda path: _probe("yuvj420p"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no ffmpeg")))
    assert VideoCompose()._normalize_to_yuv420p(output) is False
    assert output.read_bytes() == b"video"

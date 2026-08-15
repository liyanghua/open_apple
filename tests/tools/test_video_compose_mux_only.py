from pathlib import Path

from tools.video.video_compose import VideoCompose


def test_master_validation_rejects_hash_mismatch(tmp_path: Path):
    from lib.render_plan import validate_video_master
    master = tmp_path / "master.mp4"; master.write_bytes(b"master")
    result = validate_video_master({"profile": "social_vertical_1080p30", "video_master": {"path": str(master), "sha256": "0" * 64}}, probe={"streams": [], "format": {}})
    assert result.ok is False
    assert "sha256" in " ".join(result.reasons)


def test_video_compose_has_mux_only_route():
    source = Path("tools/video/video_compose.py").read_text()
    assert "render_plan" in source and "mux_only" in source


def test_encode_applies_complete_media_profile(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    seen = {}
    tool = VideoCompose()

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd

    monkeypatch.setattr(tool, "run_command", fake_run)
    result = tool._encode({
        "input_path": str(source),
        "output_path": str(tmp_path / "master.mp4"),
        "profile": "social_vertical_1080p30",
    })

    assert result.success
    assert seen["cmd"][seen["cmd"].index("-pix_fmt") + 1] == "yuv420p"
    assert "out_range=tv" in seen["cmd"][seen["cmd"].index("-vf") + 1]
    assert seen["cmd"][seen["cmd"].index("-color_range") + 1] == "tv"
    assert seen["cmd"][seen["cmd"].index("-ar") + 1] == "48000"
    assert seen["cmd"][seen["cmd"].index("-ac") + 1] == "2"


def test_mux_only_normalizes_audio_to_delivery_profile(tmp_path: Path, monkeypatch):
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    seen = {}
    tool = VideoCompose()

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"muxed")

    monkeypatch.setattr(tool, "run_command", fake_run)
    monkeypatch.setattr(
        "lib.render_plan.probe_media",
        lambda path: {"streams": [{"codec_type": "video"}], "format": {"duration": "30"}},
    )

    result = tool._mux_external_audio(video, audio)

    assert result.success
    assert seen["cmd"][seen["cmd"].index("-ar") + 1] == "48000"
    assert seen["cmd"][seen["cmd"].index("-ac") + 1] == "2"

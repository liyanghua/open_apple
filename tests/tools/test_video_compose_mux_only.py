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

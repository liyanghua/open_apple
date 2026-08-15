from pathlib import Path

from tools.video.final_qa import FinalQA


def test_quick_qa_accepts_social_profile(tmp_path: Path, monkeypatch):
    video = tmp_path / "final.mp4"; video.write_bytes(b"video")
    monkeypatch.setattr(FinalQA, "_probe", staticmethod(lambda path: {"streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1080, "height": 1920}, {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2}], "format": {"duration": "30"}}))
    monkeypatch.setattr(FinalQA, "_decode", staticmethod(lambda path: True))
    result = FinalQA().execute({"mode": "quick", "input_path": str(video), "expected_profile": "social_vertical_1080p30"})
    assert result.success and result.data["status"] == "pass"
    assert result.data["checks"]["media_integrity"]["decode_ok"]

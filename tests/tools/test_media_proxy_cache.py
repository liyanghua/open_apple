from pathlib import Path

from tools.video.media_proxy import MediaProxy
from tools.base_tool import ToolResult


def test_proxy_key_uses_content_and_profile_not_path(tmp_path: Path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    a.write_bytes(b"same"); b.write_bytes(b"same")
    tool = MediaProxy()
    base = {"input_path": str(a), "output_path": "/tmp/a.mp4", "profile": "social_vertical_1080p30"}
    moved = {**base, "input_path": str(b), "output_path": "/tmp/b.mp4"}
    assert tool.idempotency_key(base) == tool.idempotency_key(moved)
    assert tool.idempotency_key({**base, "fit": "contain"}) != tool.idempotency_key(base)


def test_proxy_reuses_cache_and_rebuilds_corruption(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"; source.write_bytes(b"source")
    calls = {"count": 0}
    def fake_run(self, src, out, profile):
        calls["count"] += 1; out.write_bytes(b"proxy")
    monkeypatch.setattr(MediaProxy, "_run_ffmpeg", fake_run)
    monkeypatch.setattr(MediaProxy, "_probe", staticmethod(lambda path: {"streams": [{"codec_type": "video"}]}))
    inputs = {"input_path": str(source), "output_path": str(tmp_path / "out.mp4"), "project_dir": str(tmp_path / "project"), "profile": "social_vertical_1080p30"}
    assert MediaProxy().execute(inputs).success
    assert MediaProxy().execute(inputs).data["cache_status"] == "hit"
    assert calls["count"] == 1

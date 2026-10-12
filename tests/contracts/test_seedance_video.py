from __future__ import annotations

import requests

from tools.video.seedance_video import SeedanceVideo


class _Response:
    def __init__(self, payload=None, content: bytes = b"") -> None:
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_reference_to_video_uses_current_fal_schema(monkeypatch, tmp_path):
    posted = {}

    def fake_post(url, *, headers, json, timeout):  # noqa: ANN001
        posted.update(json)
        return _Response({"status_url": "https://status", "response_url": "https://result"})

    def fake_get(url, *, headers=None, timeout):  # noqa: ANN001
        if url == "https://status":
            return _Response({"status": "COMPLETED"})
        if url == "https://result":
            return _Response({"video": {"url": "https://video"}, "seed": 7})
        return _Response(content=b"video")

    monkeypatch.setenv("FAL_KEY", "test-key")
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("tools.video._shared.upload_image_fal", lambda path: f"https://files/{path}")
    monkeypatch.setattr("tools.video._shared.probe_output", lambda path: {"duration_seconds": 12.0})

    result = SeedanceVideo().execute(
        {
            "prompt": "Use @Image1 and @Image2.",
            "operation": "reference_to_video",
            "reference_image_paths": ["one.webp", "two.jpg"],
            "duration": "12",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "generate_audio": False,
            "output_path": str(tmp_path / "out.mp4"),
        }
    )

    assert result.success is True
    assert posted["image_urls"] == ["https://files/one.webp", "https://files/two.jpg"]
    assert "reference_image_urls" not in posted


def test_reference_to_video_uses_current_video_and_audio_keys(monkeypatch, tmp_path):
    posted = {}

    def fake_post(url, *, headers, json, timeout):  # noqa: ANN001
        posted.update(json)
        return _Response({"status_url": "https://status", "response_url": "https://result"})

    def fake_get(url, *, headers=None, timeout):  # noqa: ANN001
        if url == "https://status":
            return _Response({"status": "COMPLETED"})
        if url == "https://result":
            return _Response({"video": {"url": "https://video"}})
        return _Response(content=b"video")

    monkeypatch.setenv("FAL_KEY", "test-key")
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("tools.video._shared.probe_output", lambda path: {})

    result = SeedanceVideo().execute(
        {
            "prompt": "Use @Video1 and @Audio1.",
            "operation": "reference_to_video",
            "reference_video_urls": ["https://files/ref.mp4"],
            "reference_audio_urls": ["https://files/ref.wav"],
            "output_path": str(tmp_path / "out.mp4"),
        }
    )

    assert result.success is True
    assert posted["video_urls"] == ["https://files/ref.mp4"]
    assert posted["audio_urls"] == ["https://files/ref.wav"]
    assert "reference_video_urls" not in posted
    assert "reference_audio_urls" not in posted


def test_queue_poll_retries_transient_read_timeout_without_resubmitting(monkeypatch, tmp_path):
    calls = {"post": 0, "status": 0}

    def fake_post(url, *, headers, json, timeout):  # noqa: ANN001
        calls["post"] += 1
        return _Response({"status_url": "https://status", "response_url": "https://result"})

    def fake_get(url, *, headers=None, timeout):  # noqa: ANN001
        if url == "https://status":
            calls["status"] += 1
            if calls["status"] == 1:
                raise requests.ReadTimeout("temporary poll timeout")
            return _Response({"status": "COMPLETED"})
        if url == "https://result":
            return _Response({"video": {"url": "https://video"}})
        return _Response(content=b"video")

    monkeypatch.setenv("FAL_KEY", "test-key")
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("tools.video._shared.probe_output", lambda path: {})
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    result = SeedanceVideo().execute(
        {
            "prompt": "A product shot.",
            "operation": "text_to_video",
            "output_path": str(tmp_path / "out.mp4"),
        }
    )

    assert result.success is True
    assert calls == {"post": 1, "status": 2}

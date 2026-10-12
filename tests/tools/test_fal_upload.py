from __future__ import annotations

import requests

from tools.video._shared import upload_image_fal


class _Response:
    def __init__(self, payload=None) -> None:
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_upload_image_fal_retries_transient_ssl_error(monkeypatch, tmp_path):
    image = tmp_path / "clean.jpg"
    image.write_bytes(b"image")
    calls = {"post": 0, "put": 0}

    def fake_post(*args, **kwargs):  # noqa: ANN002, ANN003
        calls["post"] += 1
        if calls["post"] == 1:
            raise requests.exceptions.SSLError("temporary EOF")
        return _Response({"upload_url": "https://upload", "file_url": "https://file"})

    def fake_put(*args, **kwargs):  # noqa: ANN002, ANN003
        calls["put"] += 1
        return _Response()

    monkeypatch.setenv("FAL_KEY", "test-key")
    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.put", fake_put)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    assert upload_image_fal(str(image)) == "https://file"
    assert calls == {"post": 2, "put": 1}

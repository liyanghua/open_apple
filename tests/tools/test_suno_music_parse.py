"""Unit tests for the SUNO response parsing fixes (defensive shapes)."""

from tools.audio.suno_music import SunoMusic


def _tool() -> SunoMusic:
    return SunoMusic()


def test_extract_tracks_from_data_list():
    t = _tool()
    result = {"code": 200, "data": {"status": "SUCCESS", "data": [
        {"id": "t1", "audio_url": "https://x/t1.mp3"},
        {"id": "t2", "audio_url": "https://x/t2.mp3"},
    ]}}
    tracks = t._extract_tracks(result)
    assert [tr["id"] for tr in tracks] == ["t1", "t2"]


def test_extract_tracks_from_response_suno_data():
    t = _tool()
    result = {"code": 200, "data": {"status": "SUCCESS", "response": {"sunoData": [
        {"id": "t1", "audio_url": "https://x/t1.mp3"},
    ]}}}
    assert [tr["id"] for tr in t._extract_tracks(result)] == ["t1"]


def test_extract_tracks_handles_null_data():
    t = _tool()
    assert t._extract_tracks({"code": 400, "data": None}) == []
    assert t._extract_tracks(None) == []
    assert t._extract_tracks([{"id": "t1"}]) == [{"id": "t1"}]


def test_submit_uses_configured_callback_url(monkeypatch):
    """评审 #10：callBackUrl 由 SUNO_CALLBACK_URL 配置，不再硬编码占位符。"""
    import requests

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"taskId": "task-1"}}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("SUNO_CALLBACK_URL", "https://callbacks.example.com/suno")
    tool = SunoMusic()
    task_id = tool._submit({"prompt": "warm acoustic"}, api_key="k")
    assert task_id == "task-1"
    assert captured["json"]["callBackUrl"] == "https://callbacks.example.com/suno"


def test_submit_falls_back_to_placeholder_callback(monkeypatch):
    import requests

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"taskId": "task-1"}}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.delenv("SUNO_CALLBACK_URL", raising=False)
    task_id = SunoMusic()._submit({"prompt": "warm acoustic"}, api_key="k")
    assert task_id == "task-1"
    assert "suno-callback.invalid" in captured["json"]["callBackUrl"]

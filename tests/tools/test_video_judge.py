"""Unit tests for the L3 video_judge advisory tool."""

from __future__ import annotations

from pathlib import Path

from tools.analysis.video_judge import VideoJudge


def _patch(monkeypatch, parsed):
    monkeypatch.setattr(VideoJudge, "_sample_frames", lambda self, path, count, workdir: [Path("/tmp/f.jpg")])
    monkeypatch.setattr(VideoJudge, "_call_vlm", lambda self, frames, audio_facts, model: parsed)


def test_video_judge_parses_and_clamps_scores(tmp_path: Path, monkeypatch):
    _patch(monkeypatch, {
        "dimensions": [
            {"id": "hook_clarity", "score": 8.5, "note": "前三秒动作直接"},
            {"id": "rhythm", "score": 12, "note": "偏快"},
            {"id": "audio_quality", "score": -1, "note": "x"},
            {"id": "not_a_dim", "score": 7, "note": "忽略"},
        ],
        "summary": "整体紧凑",
    })
    video = tmp_path / "f.mp4"
    video.write_bytes(b"v")
    result = VideoJudge().execute({"input_path": str(video)})
    assert result.success
    ids = [d["id"] for d in result.data["dimensions"]]
    assert ids == ["hook_clarity", "rhythm", "audio_quality"]
    scores = {d["id"]: d["score"] for d in result.data["dimensions"]}
    assert scores["hook_clarity"] == 8.5
    assert scores["rhythm"] == 10.0
    assert scores["audio_quality"] == 0.0
    assert result.data["scored"] is True


def test_video_judge_writes_output(tmp_path: Path, monkeypatch):
    _patch(monkeypatch, {"dimensions": [{"id": "shot_quality", "score": 7.2, "note": "构图稳"}], "summary": "ok"})
    (tmp_path / "f.mp4").write_bytes(b"v")
    out = tmp_path / "advisory.json"
    result = VideoJudge().execute({"input_path": str(tmp_path / "f.mp4"), "output_path": str(out)})
    assert result.success and out.exists()


def test_video_judge_reports_non_json_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(VideoJudge, "_sample_frames", lambda self, path, count, workdir: [])
    def boom(frames, audio_facts, model):
        raise RuntimeError("VLM 未返回 JSON: 不是JSON")
    monkeypatch.setattr(VideoJudge, "_call_vlm", boom)
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({"input_path": str(tmp_path / "f.mp4")})
    assert result.success is False
    assert "video_judge failed" in result.error

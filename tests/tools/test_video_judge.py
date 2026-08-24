"""Unit tests for the L3 video_judge tool (fail-closed, rubric-aware)."""

from __future__ import annotations

from pathlib import Path

from tools.analysis.video_judge import L3_DIMENSIONS, REMIX_DIMENSIONS, VideoJudge


def _patch(monkeypatch, parsed):
    monkeypatch.setattr(VideoJudge, "_sample_frames", lambda self, path, count, workdir: [Path("/tmp/f.jpg")])
    monkeypatch.setattr(
        VideoJudge,
        "_call_vlm",
        lambda self, frames, audio_facts, model, rubric_version, seed: parsed,
    )


def _full_scores(rubric):
    return {dim_id: 8.5 for dim_id, _, _ in rubric}


def test_video_judge_parses_full_rubric_and_ignores_extras(tmp_path: Path, monkeypatch):
    dimensions = [{"id": dim_id, "score": 8.5, "note": "ok"} for dim_id, _, _ in L3_DIMENSIONS]
    parsed = {
        "dimensions": dimensions + [{"id": "not_a_dim", "score": 7, "note": "忽略"}],
        "summary": "整体紧凑",
    }
    _patch(monkeypatch, parsed)
    video = tmp_path / "f.mp4"
    video.write_bytes(b"v")
    result = VideoJudge().execute({"input_path": str(video)})
    assert result.success
    ids = [d["id"] for d in result.data["dimensions"]]
    assert ids == [dim_id for dim_id, _, _ in L3_DIMENSIONS]
    assert result.data["scored"] is True
    assert result.data["rubric_version"] == "l3-v1.0"
    assert result.data["judge_version"] == "video_judge-0.2.0"


def test_out_of_range_score_is_rejected_not_clamped(tmp_path: Path, monkeypatch):
    scores = _full_scores(L3_DIMENSIONS)
    scores["rhythm"] = 12
    _patch(monkeypatch, {
        "dimensions": [{"id": dim_id, "score": score, "note": ""} for dim_id, score in scores.items()],
        "summary": "x",
    })
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({"input_path": str(tmp_path / "f.mp4")})
    assert result.success is False
    assert "超出 [0, 10]" in result.error
    assert "fail-closed" in result.error


def test_non_numeric_score_is_rejected(tmp_path: Path, monkeypatch):
    scores = _full_scores(L3_DIMENSIONS)
    scores["hook_clarity"] = "8.5"
    _patch(monkeypatch, {
        "dimensions": [{"id": dim_id, "score": score, "note": ""} for dim_id, score in scores.items()],
        "summary": "x",
    })
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({"input_path": str(tmp_path / "f.mp4")})
    assert result.success is False
    assert "分数非法" in result.error


def test_missing_required_dimension_fails_closed(tmp_path: Path, monkeypatch):
    scores = _full_scores(L3_DIMENSIONS)
    del scores["audio_quality"]
    _patch(monkeypatch, {
        "dimensions": [{"id": dim_id, "score": score, "note": ""} for dim_id, score in scores.items()],
        "summary": "x",
    })
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({"input_path": str(tmp_path / "f.mp4")})
    assert result.success is False
    assert "缺少必评维度" in result.error
    assert "audio_quality" in result.error


def test_remix_rubric_has_own_dimension_set(tmp_path: Path, monkeypatch):
    remix = {dim_id: 8.5 for dim_id, _, _ in REMIX_DIMENSIONS}
    _patch(monkeypatch, {
        "dimensions": [{"id": dim_id, "score": score, "note": ""} for dim_id, score in remix.items()],
        "summary": "x",
    })
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({
        "input_path": str(tmp_path / "f.mp4"),
        "rubric_version": "ecommerce-remix-v1.0",
    })
    assert result.success
    assert result.data["rubric_version"] == "ecommerce-remix-v1.0"
    ids = {d["id"] for d in result.data["dimensions"]}
    assert ids == {dim_id for dim_id, _, _ in REMIX_DIMENSIONS}


def test_l3_scores_do_not_satisfy_remix_rubric(tmp_path: Path, monkeypatch):
    l3 = {dim_id: 8.5 for dim_id, _, _ in L3_DIMENSIONS}
    _patch(monkeypatch, {
        "dimensions": [{"id": dim_id, "score": score, "note": ""} for dim_id, score in l3.items()],
        "summary": "x",
    })
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({
        "input_path": str(tmp_path / "f.mp4"),
        "rubric_version": "ecommerce-remix-v1.0",
    })
    assert result.success is False
    assert "product_evidence" in result.error  # remix 必评维度缺失


def test_unknown_rubric_rejected(tmp_path: Path, monkeypatch):
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({
        "input_path": str(tmp_path / "f.mp4"),
        "rubric_version": "made-up-v9",
    })
    assert result.success is False
    assert "未知 rubric_version" in result.error


def test_video_judge_writes_output(tmp_path: Path, monkeypatch):
    scores = _full_scores(L3_DIMENSIONS)
    _patch(monkeypatch, {
        "dimensions": [{"id": dim_id, "score": score, "note": ""} for dim_id, score in scores.items()],
        "summary": "ok",
    })
    (tmp_path / "f.mp4").write_bytes(b"v")
    out = tmp_path / "advisory.json"
    result = VideoJudge().execute({"input_path": str(tmp_path / "f.mp4"), "output_path": str(out)})
    assert result.success and out.exists()


def test_video_judge_reports_non_json_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(VideoJudge, "_sample_frames", lambda self, path, count, workdir: [])

    def boom(frames, audio_facts, model, rubric_version, seed):
        raise RuntimeError("VLM 未返回 JSON: 不是JSON")

    monkeypatch.setattr(VideoJudge, "_call_vlm", boom)
    (tmp_path / "f.mp4").write_bytes(b"v")
    result = VideoJudge().execute({"input_path": str(tmp_path / "f.mp4")})
    assert result.success is False
    assert "video_judge failed" in result.error


def test_default_model_env_override(monkeypatch):
    from tools.analysis.video_judge import default_model

    monkeypatch.setenv("VIDEO_JUDGE_MODEL", "qwen3-vl-plus")
    assert default_model() == "qwen3-vl-plus"
    monkeypatch.delenv("VIDEO_JUDGE_MODEL", raising=False)
    assert default_model() == "qwen-vl-max"


def test_judge_with_average_averages_runs(tmp_path: Path, monkeypatch):
    from tools.analysis.video_judge import judge_with_average
    from tools.base_tool import ToolResult

    video = tmp_path / "f.mp4"; video.write_bytes(b"v")
    hook_scores = iter([7.0, 9.0, 8.0])

    def fake_execute(self, inputs):
        h = next(hook_scores)
        dims = [
            {"id": dim_id, "name": dim_id, "score": h if dim_id == "hook_clarity" else 8.0, "note": "n"}
            for dim_id, _, _ in L3_DIMENSIONS
        ]
        return ToolResult(success=True, data={
            "scored": True, "summary": "s", "dimensions": dims,
            "rubric_version": "l3-v1.0", "model": "qwen3-vl-plus", "judge_version": "video_judge-0.2.0",
        })

    monkeypatch.setattr(VideoJudge, "execute", fake_execute)
    result = judge_with_average({"input_path": str(video)}, runs=3)
    assert result.success
    hook = next(d for d in result.data["dimensions"] if d["id"] == "hook_clarity")
    assert hook["score"] == 8.0  # (7+9+8)/3
    assert result.data["run_count"] == 3
    assert len(result.data["runs"]) == 3

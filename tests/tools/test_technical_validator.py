"""Unit tests for the L1a technical_validator tool (Design_Review P0-1)."""

from __future__ import annotations

import json
from pathlib import Path

from lib import qa_checks
from tools.analysis.technical_validator import TechnicalValidator


def _patch_media(monkeypatch, *, has_audio=True, loudness=(-20.0, -3.0), black=None, freeze=None):
    def fake_probe(path):
        streams = [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"}]
        if has_audio:
            streams.append({"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2})
        return {"streams": streams, "format": {"duration": "15.0"}}

    monkeypatch.setattr(qa_checks, "probe_media", fake_probe)
    monkeypatch.setattr(qa_checks, "decode_smoke", lambda path: True)
    monkeypatch.setattr(qa_checks, "detect_black", lambda path: black or [])
    monkeypatch.setattr(qa_checks, "detect_freeze", lambda path: freeze or [])
    monkeypatch.setattr(qa_checks, "measure_loudness", lambda path: {"integrated_lufs": loudness[0], "true_peak_dbtp": loudness[1], "lra": 4.0})


def _base_inputs(tmp_path: Path, **overrides):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    inputs = {
        "input_path": str(video),
        "project_id": "p-test",
        "scope": "final",
        "subject_hash": "a" * 64,
        "expected_duration_s": 15.0,
        "duration_tolerance_s": 1.0,
        "text_sources": [{"source": "captions", "text": "透明桌垫 29.9元 一铺一按", "shot_id": "shot-01"}],
        "expected_facts": {"sku": "TM-8888", "price": "29.9", "params": ["3mm加厚"]},
        "caption_declaration": {
            "caption_render_mode": "remotion_overlay",
            "caption_source": "artifacts/final_props.json#captions",
            "safe_zone_profile": "douyin_9_16",
        },
        "caption_spec": {
            "props_hash": "a" * 64,
            "captions": [{"text": "透明桌垫", "startMs": 0, "endMs": 1000}],
        },
        "shot_map": [{"shot_id": "shot-01", "start_s": 0, "end_s": 5}],
    }
    inputs.update(overrides)
    return inputs


def test_all_pass(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch)
    result = TechnicalValidator().execute(_base_inputs(tmp_path))
    assert result.success
    assert result.data["status"] == "pass"
    assert result.data["hard_gate"]["pass"] is True
    assert result.data["recommended_action"] == "proceed"
    assert all(c["status"] in {"pass", "skip"} for c in result.data["hard_gate"]["checks"])
    assert result.data["hard_gate"]["coverage"]["sufficient"] is True


def test_missing_subject_hash_is_rejected(tmp_path: Path, monkeypatch):
    """评审 #12：subject_hash 缺失/为空时直接失败，不产出无版本报告。"""
    _patch_media(monkeypatch)
    inputs = _base_inputs(tmp_path)
    inputs.pop("subject_hash")
    result = TechnicalValidator().execute(inputs)
    assert result.success is False
    assert "subject_hash is required" in result.error
    assert not result.data

    inputs["subject_hash"] = "not-a-sha"
    result = TechnicalValidator().execute(inputs)
    assert result.success is False
    assert "subject_hash is required" in result.error


def test_skip_heavy_report_cannot_pass(tmp_path: Path, monkeypatch):
    """评审 #5：大量 skip 仍判 pass 的洞——证据不足必须 revise。"""
    _patch_media(monkeypatch)
    inputs = _base_inputs(tmp_path)
    inputs["expected_facts"] = {}
    inputs["caption_declaration"] = {}
    inputs["caption_spec"] = {}
    inputs.pop("expected_duration_s")
    result = TechnicalValidator().execute(inputs)
    report = result.data
    assert report["status"] == "revise"
    assert report["recommended_action"] == "repair"
    assert report["hard_gate"]["pass"] is False
    coverage = report["hard_gate"]["coverage"]
    assert coverage["sufficient"] is False
    check = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_coverage")
    assert check["status"] == "fail" and check["fixable"] is True


def test_sku_conflict_is_fatal(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch)
    inputs = _base_inputs(tmp_path)
    inputs["text_sources"] = [{"source": "captions", "text": "型号 TM-9999 透明桌垫", "shot_id": "shot-01"}]
    result = TechnicalValidator().execute(inputs)
    assert result.success is False
    report = result.data
    assert report["status"] == "fail"
    assert report["recommended_action"] == "reject"
    sku = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_sku")
    assert sku["status"] == "fail" and sku["severity"] == "fatal" and sku["fixable"] is False


def test_price_conflict_is_fatal(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch)
    inputs = _base_inputs(tmp_path)
    inputs["text_sources"] = [{"source": "captions", "text": "只要 19.9 元", "shot_id": "shot-01"}]
    report = TechnicalValidator().execute(inputs).data
    assert report["status"] == "fail"
    assert next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_price")["status"] == "fail"


def test_sensitive_word_is_fatal(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch)
    inputs = _base_inputs(tmp_path)
    inputs["text_sources"] = [{"source": "captions", "text": "全网最低价 透明桌垫", "shot_id": "shot-01"}]
    report = TechnicalValidator().execute(inputs).data
    assert report["status"] == "fail"
    check = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_sensitive")
    assert check["status"] == "fail" and "最低价" in check["message"]


def test_duration_out_of_bounds_is_fixable_revise(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch)
    inputs = _base_inputs(tmp_path, expected_duration_s=10.0)
    result = TechnicalValidator().execute(inputs)
    assert result.success  # revise is not a fatal failure
    report = result.data
    assert report["status"] == "revise"
    assert report["recommended_action"] == "repair"
    assert any(t["action"] == "shorten_shot" for t in report["repair_targets"])


def test_missing_audio_is_fixable_revise(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch, has_audio=False)
    result = TechnicalValidator().execute(_base_inputs(tmp_path))
    report = result.data
    assert report["status"] == "revise"
    check = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_media_missing")
    assert check["status"] == "fail" and check["fixable"] is True
    assert "无音频决策" in check["message"]


def test_black_frames_are_fixable_and_attributed(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch, black=[{"black_start": 1.0, "black_end": 1.5}])
    report = TechnicalValidator().execute(_base_inputs(tmp_path)).data
    assert report["status"] == "revise"
    check = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_black_frames")
    assert check["status"] == "fail" and check["affected_shots"] == ["shot-01"]


def test_writes_valid_report_file(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch)
    output = tmp_path / "report.json"
    TechnicalValidator().execute(_base_inputs(tmp_path, output_path=str(output)))
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["project_id"] == "p-test"
    assert data["semantic_sha256"] and data["artifact_sha256"]
    from schemas.artifacts import validate_artifact
    validate_artifact("evaluation_report", data)


def test_resolution_mismatch_is_fixable_revise(tmp_path: Path, monkeypatch):
    """评审缺口 #5：分辨率进入 hard_gate。"""
    _patch_media(monkeypatch)

    def fake_probe(path):
        return {"streams": [
            {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
             "width": 720, "height": 1280, "avg_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
        ], "format": {"duration": "15.0"}}

    monkeypatch.setattr(qa_checks, "probe_media", fake_probe)
    report = TechnicalValidator().execute(_base_inputs(tmp_path)).data
    check = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_resolution")
    assert check["status"] == "fail" and check["fixable"] is True
    assert "720x1280" in check["message"]
    assert report["status"] == "revise"


def test_fps_mismatch_is_fixable_revise(tmp_path: Path, monkeypatch):
    _patch_media(monkeypatch)

    def fake_probe(path):
        return {"streams": [
            {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
             "width": 1080, "height": 1920, "avg_frame_rate": "24/1"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
        ], "format": {"duration": "15.0"}}

    monkeypatch.setattr(qa_checks, "probe_media", fake_probe)
    report = TechnicalValidator().execute(_base_inputs(tmp_path)).data
    check = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_fps")
    assert check["status"] == "fail" and check["fixable"] is True
    assert report["status"] == "revise"


def test_subtitle_bounds_respect_declared_bottom_offset(tmp_path: Path, monkeypatch):
    """评审 #9b：L1a 字幕越界检查与渲染器共用声明的底部偏移。"""
    _patch_media(monkeypatch)
    boxes = [{
        "text": "透明桌垫", "left": 100, "right": 964, "top": 1740,
        "bottom": 1800, "width": 864, "height": 60, "line_count": 1,
    }]
    inputs = _base_inputs(tmp_path)
    inputs["caption_declaration"]["bottom_offset_px"] = 120
    inputs["caption_spec"] = {"props_hash": "a" * 64, "computed_boxes": boxes}
    report = TechnicalValidator().execute(inputs).data
    check = next(c for c in report["hard_gate"]["checks"] if c["id"] == "l1a_subtitle_bounds")
    assert check["status"] == "pass"

    without_offset = _base_inputs(tmp_path)
    without_offset["caption_spec"] = {"props_hash": "a" * 64, "computed_boxes": boxes}
    report2 = TechnicalValidator().execute(without_offset).data
    check2 = next(c for c in report2["hard_gate"]["checks"] if c["id"] == "l1a_subtitle_bounds")
    assert check2["status"] == "fail"

from pathlib import Path

import jsonschema

from schemas.artifacts import load_schema, validate_artifact
from tools.video.final_qa import FinalQA


def _patch_valid_media(monkeypatch):
    monkeypatch.setattr(FinalQA, "_probe", staticmethod(lambda path: {"streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1080, "height": 1920}, {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2}], "format": {"duration": "30"}}))
    monkeypatch.setattr(FinalQA, "_decode", staticmethod(lambda path: True))


def test_quick_qa_accepts_social_profile(tmp_path: Path, monkeypatch):
    video = tmp_path / "final.mp4"; video.write_bytes(b"video")
    _patch_valid_media(monkeypatch)
    result = FinalQA().execute({"mode": "quick", "input_path": str(video), "expected_profile": "social_vertical_1080p30"})
    assert result.success and result.data["status"] == "pass"
    assert result.data["checks"]["media_integrity"]["decode_ok"]


def test_quick_qa_accepts_half_scale_remotion_sample_profile(
    tmp_path: Path, monkeypatch
):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(FinalQA, "_probe", staticmethod(lambda path: {
        "streams": [
            {
                "codec_type": "video", "codec_name": "h264",
                "pix_fmt": "yuvj420p", "width": 540, "height": 960,
                "r_frame_rate": "30/1",
            },
            {
                "codec_type": "audio", "codec_name": "aac",
                "sample_rate": "48000", "channels": 2,
            },
        ],
        "format": {"duration": "12"},
    }))
    monkeypatch.setattr(FinalQA, "_decode", staticmethod(lambda path: True))

    result = FinalQA().execute({
        "mode": "quick",
        "input_path": str(video),
        "expected_profile": "social_vertical_sample_540p30",
    })

    assert result.success and result.data["status"] == "pass"


def test_caption_source_file_without_render_declaration_does_not_prove_pixels(tmp_path: Path, monkeypatch):
    video = tmp_path / "final.mp4"; video.write_bytes(b"video")
    subtitle = tmp_path / "captions.srt"; subtitle.write_text("caption", encoding="utf-8")
    _patch_valid_media(monkeypatch)

    result = FinalQA().execute({
        "mode": "quick",
        "input_path": str(video),
        "expected_profile": "social_vertical_1080p30",
        "caption_spec": {
            "source_path": str(subtitle),
            "props_hash": "a" * 64,
            "captions": [{"text": "透明桌垫", "startMs": 0, "endMs": 1000}],
        },
    })

    assert result.data["status"] == "revise"
    assert "caption render declaration missing" in result.data["issues_found"]
    assert result.data["checks"]["caption_render"]["declared"] is False
    assert result.data["checks"]["caption_render"]["pixels_rendered"] is False


def test_remotion_caption_declaration_requires_and_accepts_safe_pixel_evidence(tmp_path: Path, monkeypatch):
    video = tmp_path / "final.mp4"; video.write_bytes(b"video")
    _patch_valid_media(monkeypatch)
    result = FinalQA().execute({
        "mode": "quick",
        "input_path": str(video),
        "expected_profile": "social_vertical_1080p30",
        "caption_declaration": {
            "caption_render_mode": "remotion_overlay",
            "caption_source": "artifacts/final_props.json#captions",
            "safe_zone_profile": "douyin_9_16",
        },
        "caption_spec": {
            "props_hash": "a" * 64,
            "captions": [{"text": "透明桌垫", "startMs": 0, "endMs": 1000}],
        },
    })

    caption_render = result.data["checks"]["caption_render"]
    assert result.data["status"] == "pass"
    assert caption_render["declared"] is True
    assert caption_render["pixels_rendered"] is True
    assert caption_render["safe_zone_passed"] is True
    caption_schema = load_schema("final_review")["properties"]["checks"]["properties"]["caption_render"]
    jsonschema.validate(caption_render, caption_schema)
    validate_artifact("final_review", result.data)


def test_subtitle_stream_declared_but_missing_from_render_revises(tmp_path: Path, monkeypatch):
    video = tmp_path / "final.mp4"; video.write_bytes(b"video")
    _patch_valid_media(monkeypatch)
    result = FinalQA().execute({
        "mode": "quick",
        "input_path": str(video),
        "expected_profile": "social_vertical_1080p30",
        "caption_declaration": {
            "caption_render_mode": "subtitle_stream",
            "caption_source": "assets/subtitles.srt",
            "safe_zone_profile": "douyin_9_16",
        },
    })

    caption_render = result.data["checks"]["caption_render"]
    assert result.data["status"] == "revise"
    assert not result.success
    assert "subtitles declared but not present in render" in result.data["issues_found"]
    assert caption_render["declared"] is True
    assert caption_render["pixels_rendered"] is False
    assert caption_render["safe_zone_passed"] is None
    assert result.data["checks"]["subtitle_check"]["subtitles_present"] is False


def _bottom_offset_case(tmp_path: Path) -> dict:
    return {
        "mode": "quick",
        "input_path": str(tmp_path / "final.mp4"),
        "expected_profile": "social_vertical_1080p30",
        "caption_declaration": {
            "caption_render_mode": "remotion_overlay",
            "caption_source": "artifacts/final_props.json#captions",
            "safe_zone_profile": "douyin_9_16",
            "bottom_offset_px": 120,
        },
        "caption_spec": {
            "props_hash": "a" * 64,
            "computed_boxes": [{
                "text": "透明桌垫", "left": 100, "right": 964, "top": 1740,
                "bottom": 1800, "width": 864, "height": 60, "line_count": 1,
            }],
        },
    }


def test_caption_bottom_offset_declaration_is_the_single_source(tmp_path: Path, monkeypatch):
    """评审 #9b：声明的底部偏移让 QA 与渲染器使用同一安全区数值。"""
    video = tmp_path / "final.mp4"; video.write_bytes(b"video")
    _patch_valid_media(monkeypatch)
    result = FinalQA().execute(_bottom_offset_case(tmp_path))
    caption_render = result.data["checks"]["caption_render"]
    assert result.data["status"] == "pass"
    assert caption_render["safe_zone_passed"] is True
    assert caption_render["bottom_offset_px"] == 120

    # 同一盒子、缺省声明偏移 → 平台默认安全区（300）判定越界 → revise
    without_offset = _bottom_offset_case(tmp_path)
    without_offset["caption_declaration"].pop("bottom_offset_px")
    result2 = FinalQA().execute(without_offset)
    assert result2.data["status"] == "revise"
    assert result2.data["checks"]["caption_render"]["safe_zone_passed"] is False

from __future__ import annotations

import pytest

from tools.subtitle.subtitle_gen import SubtitleGen


def _inputs() -> dict:
    return {
        "segments": [{"text": "透明桌垫", "start": 0.0, "end": 1.0}],
        "format": "srt", "max_words_per_cue": 8, "max_chars_per_line": 12,
        "language": "zh-CN", "strip_trailing_punctuation": True,
        "safe_zone": {"bottom_percent": 18, "side_percent": 8},
        "emphasis_rules": [{"pattern": "透明桌垫", "style": "accent"}],
        "highlight_style": "none", "corrections": {}, "output_path": "/tmp/a.srt",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("segments", [{"text": "changed", "start": 0.0, "end": 1.0}]),
        ("format", "vtt"), ("max_words_per_cue", 4),
        ("max_chars_per_line", 8), ("language", "en"),
        ("strip_trailing_punctuation", False),
        ("safe_zone", {"bottom_percent": 20, "side_percent": 8}),
        ("emphasis_rules", []), ("highlight_style", "karaoke"),
        ("corrections", {"桌垫": "桌面保护垫"}),
    ],
)
def test_subtitle_key_covers_all_rendering_rules(field: str, value) -> None:
    tool = SubtitleGen()
    assert tool.idempotency_key(_inputs()) != tool.idempotency_key({**_inputs(), field: value})


def test_subtitle_output_path_does_not_change_key() -> None:
    tool = SubtitleGen()
    assert tool.idempotency_key(_inputs()) == tool.idempotency_key({**_inputs(), "output_path": "/tmp/b.srt"})


def test_subtitle_tool_version_changes_key() -> None:
    tool = SubtitleGen()
    baseline = tool.idempotency_key(_inputs())
    tool.version = "next"
    assert baseline != tool.idempotency_key(_inputs())


def test_subtitle_execute_reuses_cache_and_rebuilds_after_corruption(tmp_path, monkeypatch) -> None:
    tool = SubtitleGen()
    inputs = _inputs()
    inputs["output_path"] = str(tmp_path / "subtitles.srt")
    inputs["project_dir"] = str(tmp_path / "project")
    first = tool.execute(inputs)
    second = tool.execute(inputs)
    assert first.success and second.success
    assert second.data["cache_status"] == "hit"

    key = tool.idempotency_key(inputs)
    (tmp_path / "project" / ".cache" / "subtitles" / key / "output.srt").write_text("broken")
    original_build_cues = tool._build_cues
    calls = {"count": 0}

    def counted_build_cues(*args):
        calls["count"] += 1
        return original_build_cues(*args)

    monkeypatch.setattr(tool, "_build_cues", counted_build_cues)
    rebuilt = tool.execute(inputs)
    assert rebuilt.success is True
    assert rebuilt.data["cache_status"] == "miss"
    assert calls["count"] == 1

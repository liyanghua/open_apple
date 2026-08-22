"""Unit tests for the shared lib/qa_checks primitives."""

from __future__ import annotations

from lib.qa_checks import fps_of, parse_ffmpeg_ranges


def test_parse_blackdetect_ranges():
    log = (
        "[Parsed_blackdetect_0 @ 0x1] black_start:1.0 black_end:1.5 black_duration:0.5\n"
        "frame=30 fps=30 q=-0.0 Lsize=N/A time=00:00:01.00 bitrate=N/A speed=2x\n"
        "[Parsed_blackdetect_0 @ 0x1] black_start:3.2 black_end:3.9 black_duration:0.7\n"
    )
    ranges = parse_ffmpeg_ranges(log, "black_start")
    assert len(ranges) == 2
    assert ranges[0]["black_start"] == 1.0
    assert ranges[1]["black_end"] == 3.9


def test_parse_ranges_ignores_non_matching_lines():
    log = "frame=10 fps=30 q=-0.0\n[buffer @ 0x1] w=1080 h=1920\n"
    assert parse_ffmpeg_ranges(log, "freeze_start") == []


def test_parse_ranges_skips_unparseable_tokens():
    log = "[x] freeze_start:2.0 freeze_duration:abc noise=1\n"
    ranges = parse_ffmpeg_ranges(log, "freeze_start")
    assert ranges == [{"freeze_start": 2.0, "noise": 1.0}]


def test_fps_of_valid_and_invalid():
    assert fps_of({"avg_frame_rate": "30000/1001"}) == 29.97
    assert fps_of({"avg_frame_rate": "0/0"}) == 0.0
    assert fps_of({}) == 0.0
    assert fps_of({"avg_frame_rate": "garbage"}) == 0.0

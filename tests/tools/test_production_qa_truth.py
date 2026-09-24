import json
from pathlib import Path
from unittest.mock import patch

from tools.video.video_compose import VideoCompose


def test_chinese_transcript_is_checked_not_just_english_brand(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps({"word_timestamps": [{"word": "PLAYBOY"}]}))
    result = VideoCompose._compare_transcript_to_script(path, "素色毛巾，看清织纹。PLAYBOY，让日常更有质感。")
    assert result["status"] == "fail"
    assert result["script_word_count"] > 10
    assert result["word_accuracy"] < 0.2


def test_missing_and_invalid_transcripts_are_distinct_states(tmp_path):
    missing = VideoCompose._compare_transcript_to_script(None, "你好")
    assert missing["status"] == "not_run"
    path = tmp_path / "bad.json"
    path.write_text("invalid json")
    assert VideoCompose._compare_transcript_to_script(path, "你好")["status"] == "error"


def test_correct_chinese_transcript_passes(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps({"word_timestamps": [{"word": "看清织纹"}, {"word": "PLAYBOY"}, {"word": "让日常更有质感"}]}))
    assert VideoCompose._compare_transcript_to_script(path, "看清织纹。PLAYBOY，让日常更有质感。")["status"] == "pass"


def test_final_review_never_passes_skipped_narration_check(tmp_path):
    output = tmp_path / "film.mp4"
    output.write_bytes(b"fixture")
    probe = {"format": {"duration": "9", "size": "1000000"}, "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
        {"codec_type": "audio", "codec_name": "aac"}]}
    class Result:
        returncode = 0
        stdout = json.dumps(probe)
        stderr = "mean_volume: -16.0 dB\nmax_volume: -2.0 dB"
    with patch("tools.video.video_compose.subprocess.run", return_value=Result()):
        result = VideoCompose()._run_final_review(output, script_text="PLAYBOY，让日常更有质感。")
    assert result["checks"]["transcript_comparison"]["status"] == "not_run"
    assert result["status"] != "pass"

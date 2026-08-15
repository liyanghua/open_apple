from __future__ import annotations

from pathlib import Path

from lib.source_media_review import review_source_media
from tools.base_tool import ToolResult


class FailingTranscriber:
    def get_status(self):
        raise AssertionError("transcriber status must not be queried for media without audio")

    def execute(self, inputs: dict) -> ToolResult:
        raise AssertionError(f"transcriber must not run: {inputs}")


class Registry:
    def get(self, name: str):
        return FailingTranscriber() if name == "transcriber" else None


def test_review_reuses_media_index_and_skips_transcriber_without_audio(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    media_index = {
        "analysis_version": "v1",
        "entries": [{
            "path": str(media),
            "media_type": "video",
            "fingerprint": {"content_sha256": "a" * 64, "size_bytes": 5, "mtime_ns": 1},
            "probe": {
                "duration_seconds": 8.0,
                "resolution": "1080x1920",
                "fps": 30.0,
                "codec": "h264",
                "audio_codec": "",
                "sample_rate": 0,
                "channels": 0,
                "file_size_bytes": 5,
                "bitrate_kbps": 8000.0,
            },
            "scenes": [],
            "representative_frames": [],
            "audio": {"has_track": False, "usable": False},
            "best_ranges": [{"start_seconds": 0.0, "end_seconds": 8.0}],
            "quality_risks": [],
        }],
    }

    result = review_source_media(
        [media], {}, tool_registry=Registry(), media_index=media_index
    )

    reviewed = result["files"][0]
    assert reviewed["technical_probe"]["duration_seconds"] == 8.0
    assert reviewed["best_ranges"] == [{"start_seconds": 0.0, "end_seconds": 8.0}]
    assert reviewed["usable_audio"] is False
    assert reviewed["transcription_skipped_reason"] == "no_audio_track"


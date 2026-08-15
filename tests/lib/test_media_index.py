from __future__ import annotations

import os
import shutil
from pathlib import Path

from tools.base_tool import ToolResult


class RecordingTool:
    def __init__(self, name: str, response_factory):
        self.name = name
        self.version = "test-1"
        self.calls: list[dict] = []
        self._response_factory = response_factory

    def execute(self, inputs: dict) -> ToolResult:
        self.calls.append(dict(inputs))
        return self._response_factory(inputs)


class Registry:
    def __init__(self, tools: dict[str, RecordingTool]):
        self.tools = tools

    def get(self, name: str):
        return self.tools.get(name)


def _registry() -> Registry:
    def probe(_inputs: dict) -> ToolResult:
        return ToolResult(success=True, data={
            "duration_seconds": 8.0,
            "resolution": "1080x1920",
            "fps": 30.0,
            "codec": "h264",
            "audio_codec": "aac",
            "sample_rate": 48000,
            "channels": 2,
            "file_size_bytes": 4,
            "bitrate_kbps": 8000.0,
        })

    def scenes(_inputs: dict) -> ToolResult:
        return ToolResult(success=True, data={
            "scenes": [{
                "index": 0,
                "start_seconds": 0.0,
                "end_seconds": 8.0,
                "duration_seconds": 8.0,
            }],
        })

    def frames(inputs: dict) -> ToolResult:
        output_dir = Path(inputs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frame = output_dir / "frame_0000.jpg"
        frame.write_bytes(b"valid-jpeg-placeholder")
        return ToolResult(success=True, data={
            "frames": [{"path": str(frame), "timestamp_seconds": 2.0, "index": 0}],
        })

    return Registry({
        "audio_probe": RecordingTool("audio_probe", probe),
        "scene_detect": RecordingTool("scene_detect", scenes),
        "frame_sampler": RecordingTool("frame_sampler", frames),
    })


def test_fingerprint_uses_bytes_not_path_or_mtime(tmp_path: Path) -> None:
    from lib.media_index import fingerprint_media

    first = tmp_path / "first.mp4"
    copy = tmp_path / "copy.mp4"
    first.write_bytes(b"aaaa")
    shutil.copyfile(first, copy)
    os.utime(copy, ns=(first.stat().st_atime_ns, first.stat().st_mtime_ns + 10_000))

    original = fingerprint_media(first)
    relocated = fingerprint_media(copy)
    assert original.content_sha256 == relocated.content_sha256
    assert original.mtime_ns != relocated.mtime_ns


def test_fingerprint_detects_same_size_same_mtime_content_change(tmp_path: Path) -> None:
    from lib.media_index import fingerprint_media

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"aaaa")
    original_mtime = media.stat().st_mtime_ns
    before = fingerprint_media(media)

    media.write_bytes(b"bbbb")
    os.utime(media, ns=(media.stat().st_atime_ns, original_mtime))
    after = fingerprint_media(media)

    assert before.size_bytes == after.size_bytes
    assert before.mtime_ns == after.mtime_ns
    assert before.content_sha256 != after.content_sha256


def test_build_media_index_reuses_identical_content_at_new_path(tmp_path: Path) -> None:
    from lib.media_index import build_media_index

    project = tmp_path / "demo"
    first = tmp_path / "first.mp4"
    relocated = tmp_path / "relocated.mp4"
    first.write_bytes(b"aaaa")
    shutil.copyfile(first, relocated)
    registry = _registry()

    build_media_index([first], project_dir=project, registry=registry, analysis_version="v1")
    second = build_media_index(
        [relocated], project_dir=project, registry=registry, analysis_version="v1"
    )

    assert len(registry.get("audio_probe").calls) == 1
    assert len(registry.get("scene_detect").calls) == 1
    assert len(registry.get("frame_sampler").calls) == 1
    assert second["entries"][0]["path"] == str(relocated)


def test_analysis_version_change_and_corrupt_frame_force_reanalysis(tmp_path: Path) -> None:
    from lib.media_index import build_media_index

    project = tmp_path / "demo"
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"aaaa")
    registry = _registry()

    first = build_media_index([media], project_dir=project, registry=registry, analysis_version="v1")
    frame = Path(first["entries"][0]["representative_frames"][0])
    frame.write_bytes(b"corrupt")
    build_media_index([media], project_dir=project, registry=registry, analysis_version="v1")
    build_media_index([media], project_dir=project, registry=registry, analysis_version="v2")

    assert len(registry.get("frame_sampler").calls) == 3
    assert len(registry.get("audio_probe").calls) == 3
    assert len(registry.get("scene_detect").calls) == 3


def test_frame_sampler_uses_supported_count_strategy(tmp_path: Path) -> None:
    from lib.media_index import build_media_index

    project = tmp_path / "demo"
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"aaaa")
    registry = _registry()

    build_media_index([media], project_dir=project, registry=registry, analysis_version="v1")

    call = registry.get("frame_sampler").calls[0]
    assert call["strategy"] == "count"
    assert call["count"] == 4
    assert "/analysis/media/" in call["output_dir"]


def test_audio_probe_native_shape_is_normalized(tmp_path: Path) -> None:
    from lib.media_index import build_media_index

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"aaaa")
    registry = _registry()
    registry.tools["audio_probe"] = RecordingTool(
        "audio_probe",
        lambda _inputs: ToolResult(success=True, data={
            "duration_seconds": 3.0,
            "resolution": "1080x1920",
            "size_bytes": 4,
            "bit_rate": 900_000,
            "audio": {"codec": "aac", "sample_rate": 48000, "channels": 2},
        }),
    )

    result = build_media_index(
        [media], project_dir=tmp_path / "demo", registry=registry, analysis_version="v1"
    )

    probe = result["entries"][0]["probe"]
    assert probe["audio_codec"] == "aac"
    assert probe["sample_rate"] == 48000
    assert probe["channels"] == 2
    assert probe["file_size_bytes"] == 4
    assert probe["bitrate_kbps"] == 900.0
    assert result["entries"][0]["audio"] == {"has_track": True, "usable": True}


def test_missing_sampled_frame_never_becomes_cache_hit(tmp_path: Path) -> None:
    from lib.media_index import build_media_index

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"aaaa")
    registry = _registry()
    sampler = registry.get("frame_sampler")

    def missing(inputs: dict) -> ToolResult:
        path = Path(inputs["output_dir"]) / "missing.jpg"
        return ToolResult(success=True, data={"frames": [{"path": str(path)}]})

    sampler._response_factory = missing
    build_media_index(
        [media], project_dir=tmp_path / "demo", registry=registry, analysis_version="v1"
    )
    build_media_index(
        [media], project_dir=tmp_path / "demo", registry=registry, analysis_version="v1"
    )

    assert len(sampler.calls) == 2

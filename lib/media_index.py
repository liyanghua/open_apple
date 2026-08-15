"""Content-addressed inspection index for source media."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.artifact_io import write_artifact_atomic
from lib.cache_io import atomic_write_json

_VERSION_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class MediaFingerprint:
    content_sha256: str
    size_bytes: int
    mtime_ns: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_media(path: Path) -> MediaFingerprint:
    """Fingerprint media bytes on every run; metadata is diagnostic only."""
    path = Path(path)
    stat = path.stat()
    return MediaFingerprint(_sha256(path), stat.st_size, stat.st_mtime_ns)


def analysis_cache_key(
    *,
    tool_name: str,
    tool_version: str,
    source: str,
    parameters: dict[str, Any],
) -> str:
    """Build a stable key from source bytes and normalized analysis inputs."""
    source_path = Path(source)
    source_identity = (
        fingerprint_media(source_path).content_sha256
        if source_path.is_file()
        else hashlib.sha256(source.encode("utf-8")).hexdigest()
    )
    payload = {
        "tool": tool_name,
        "tool_version": tool_version,
        "source_sha256": source_identity,
        "parameters": parameters,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tool(registry: Any, name: str) -> Any:
    return registry.get(name) if registry is not None else None


def _tool_versions(registry: Any) -> dict[str, str]:
    return {
        name: str(getattr(_tool(registry, name), "version", "unavailable"))
        for name in ("audio_probe", "scene_detect", "frame_sampler")
    }


def _probe_with_ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return {}
    payload = json.loads(proc.stdout)
    fmt = payload.get("format", {})
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    rate = video.get("r_frame_rate", "0/1").split("/", 1)
    fps = float(rate[0]) / max(float(rate[1]), 1.0) if len(rate) == 2 else 0.0
    return {
        "duration_seconds": float(fmt.get("duration", 0) or 0),
        "resolution": f"{video.get('width', '?')}x{video.get('height', '?')}" if video else "",
        "fps": round(fps, 3),
        "codec": video.get("codec_name", "") or audio.get("codec_name", "unknown"),
        "audio_codec": audio.get("codec_name", ""),
        "sample_rate": int(audio.get("sample_rate", 0) or 0),
        "channels": int(audio.get("channels", 0) or 0),
        "file_size_bytes": int(fmt.get("size", 0) or 0),
        "bitrate_kbps": round(int(fmt.get("bit_rate", 0) or 0) / 1000, 1),
    }


def _normalize_probe(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    audio = normalized.get("audio")
    if isinstance(audio, dict):
        normalized.setdefault("audio_codec", audio.get("codec", ""))
        normalized.setdefault("sample_rate", int(audio.get("sample_rate", 0) or 0))
        normalized.setdefault("channels", int(audio.get("channels", 0) or 0))
    normalized.setdefault("audio_codec", "")
    normalized.setdefault("sample_rate", 0)
    normalized.setdefault("channels", 0)
    if "file_size_bytes" not in normalized and "size_bytes" in normalized:
        normalized["file_size_bytes"] = int(normalized["size_bytes"] or 0)
    if "bitrate_kbps" not in normalized and "bit_rate" in normalized:
        normalized["bitrate_kbps"] = round(int(normalized["bit_rate"] or 0) / 1000, 1)
    return normalized


def _probe_image(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return {
                "resolution": f"{image.width}x{image.height}",
                "codec": image.format or "unknown",
                "file_size_bytes": path.stat().st_size,
                "audio_codec": "",
                "sample_rate": 0,
                "channels": 0,
            }
    except Exception:
        return {"file_size_bytes": path.stat().st_size}


def _probe(path: Path, registry: Any, media_type: str) -> dict[str, Any]:
    if media_type == "image":
        return _probe_image(path)
    probe_tool = _tool(registry, "audio_probe")
    if probe_tool is not None:
        result = probe_tool.execute({"input_path": str(path)})
        if result.success:
            normalized = _normalize_probe(result.data)
            if media_type != "video" or normalized.get("resolution"):
                return normalized
            return {**normalized, **_probe_with_ffprobe(path)}
    return _probe_with_ffprobe(path)


def _media_type(path: Path) -> str | None:
    from lib.source_media_review import detect_media_type
    return detect_media_type(path)


def _quality_risks(media_type: str, probe: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if media_type == "video":
        resolution = probe.get("resolution", "")
        try:
            width, height = (int(value) for value in resolution.split("x", 1))
            if width < 720 or height < 480:
                risks.append(f"Low resolution ({resolution})")
        except (TypeError, ValueError):
            pass
        if 0 < float(probe.get("duration_seconds", 0) or 0) < 3:
            risks.append("Very short clip (<3s)")
    if int(probe.get("channels", 0) or 0) == 1:
        risks.append("Mono audio")
    return risks


def _frame_paths(data: dict[str, Any]) -> list[str]:
    frames = data.get("frames", data.get("frame_paths", []))
    paths: list[str] = []
    for frame in frames:
        value = frame.get("path") if isinstance(frame, dict) else frame
        if value:
            paths.append(str(value))
    return paths


def _record_valid(record_path: Path, expected: dict[str, Any]) -> dict[str, Any] | None:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("schema_version") != 1 or record.get("cache_identity") != expected:
            return None
        validated_paths = []
        for frame in record.get("frames", []):
            path = Path(frame["path"])
            if not path.is_file() or path.stat().st_size != frame["size_bytes"]:
                return None
            if _sha256(path) != frame["sha256"]:
                return None
            validated_paths.append(str(path))
        entry = record["entry"]
        if not isinstance(entry, dict):
            return None
        if entry.get("representative_frames", []) != validated_paths:
            return None
        return entry
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _analyze_content(
    path: Path,
    fingerprint: MediaFingerprint,
    *,
    project_dir: Path,
    registry: Any,
    analysis_version: str,
) -> dict[str, Any]:
    media_type = _media_type(path)
    if media_type is None:
        raise ValueError(f"Unsupported media type: {path}")

    root = project_dir / "analysis" / "media" / fingerprint.content_sha256 / analysis_version
    frames_dir = root / "frames"
    record_path = root / "record.json"
    cache_identity = {
        "content_sha256": fingerprint.content_sha256,
        "analysis_version": analysis_version,
        "tool_versions": _tool_versions(registry),
        "scene_request": {"method": "content", "min_scene_length_seconds": 1.0},
        "frame_request": {"strategy": "count", "count": 4, "format": "jpg", "quality": 2},
    }
    cached = _record_valid(record_path, cache_identity)
    if cached is not None:
        return cached

    root.mkdir(parents=True, exist_ok=True)
    probe = _probe(path, registry, media_type)
    scenes: list[dict[str, Any]] = []
    frame_paths: list[str] = []
    if media_type == "video":
        scene_tool = _tool(registry, "scene_detect")
        if scene_tool is not None:
            scene_result = scene_tool.execute({
                "input_path": str(path),
                "method": "content",
                "min_scene_length_seconds": 1.0,
                "analysis_version": analysis_version,
                "output_path": str(root / "scenes.json"),
            })
            if scene_result.success:
                scenes = list(scene_result.data.get("scenes", []))

        frame_tool = _tool(registry, "frame_sampler")
        if frame_tool is not None:
            frame_result = frame_tool.execute({
                "input_path": str(path),
                "strategy": "count",
                "count": 4,
                "format": "jpg",
                "quality": 2,
                "analysis_version": analysis_version,
                "output_dir": str(frames_dir),
            })
            if frame_result.success:
                frame_paths = _frame_paths(frame_result.data)

    has_track = bool(probe.get("audio_codec") or int(probe.get("channels", 0) or 0))
    duration = float(probe.get("duration_seconds", 0) or 0)
    best_ranges = [
        {"start_seconds": float(scene.get("start_seconds", 0)),
         "end_seconds": float(scene.get("end_seconds", 0))}
        for scene in scenes
        if float(scene.get("end_seconds", 0)) > float(scene.get("start_seconds", 0))
    ]
    if not best_ranges and duration > 0:
        best_ranges = [{"start_seconds": 0.0, "end_seconds": duration}]

    entry = {
        "media_type": media_type,
        "probe": probe,
        "scenes": scenes,
        "representative_frames": frame_paths,
        "audio": {"has_track": has_track, "usable": has_track},
        "best_ranges": best_ranges,
        "quality_risks": _quality_risks(media_type, probe),
    }
    frames = [
        {"path": value, "size_bytes": Path(value).stat().st_size, "sha256": _sha256(Path(value))}
        for value in frame_paths
        if Path(value).is_file()
    ]
    atomic_write_json(record_path, {
        "schema_version": 1,
        "cache_identity": cache_identity,
        "entry": entry,
        "frames": frames,
    })
    return entry


def build_media_index(
    files: list[Path],
    *,
    project_dir: Path,
    registry: Any,
    analysis_version: str,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Inspect unique media content in bounded parallel workers and persist an index."""
    if not _VERSION_SEGMENT.fullmatch(analysis_version):
        raise ValueError("analysis_version must be a safe path segment")
    project_dir = Path(project_dir)
    candidates = [Path(path) for path in files if Path(path).is_file() and _media_type(Path(path))]
    fingerprints = [fingerprint_media(path) for path in candidates]

    unique: dict[str, tuple[Path, MediaFingerprint]] = {}
    for path, fingerprint in zip(candidates, fingerprints):
        unique.setdefault(fingerprint.content_sha256, (path, fingerprint))

    analyses: dict[str, dict[str, Any]] = {}
    if unique:
        bounded = min(4, max(1, (os.cpu_count() or 2) // 2), len(unique))
        worker_count = min(bounded, max_workers) if max_workers is not None else bounded
        with ThreadPoolExecutor(max_workers=max(1, worker_count)) as executor:
            futures = {
                digest: executor.submit(
                    _analyze_content,
                    path,
                    fingerprint,
                    project_dir=project_dir,
                    registry=registry,
                    analysis_version=analysis_version,
                )
                for digest, (path, fingerprint) in unique.items()
            }
            analyses = {digest: future.result() for digest, future in futures.items()}

    entries = []
    for path, fingerprint in zip(candidates, fingerprints):
        entry = dict(analyses[fingerprint.content_sha256])
        entry["path"] = str(path)
        entry["fingerprint"] = asdict(fingerprint)
        entry["fingerprint"]["mtime_ns"] = str(fingerprint.mtime_ns)
        entries.append(entry)

    raw = {
        "version": "1.0",
        "project_id": project_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "producer": "lib.media_index",
        "input_hashes": {
            f"media_{index}": fingerprint.content_sha256
            for index, fingerprint in enumerate(fingerprints)
        },
        "analysis_version": analysis_version,
        "entries": entries,
    }
    envelope = write_artifact_atomic(
        "artifacts/media_index.json",
        "media_index",
        raw,
        project_dir=project_dir,
    )
    return envelope["data"]

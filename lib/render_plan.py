"""Render-plan validation and master provenance checks."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MasterValidation:
    ok: bool
    reasons: tuple[str, ...] = ()
    probe: dict[str, Any] = field(default_factory=dict)


def validate_sample_window(start_frame: int, end_frame_exclusive: int) -> tuple[int, int]:
    start, end = int(start_frame), int(end_frame_exclusive)
    duration = end - start
    if start < 0 or duration < 300 or duration > 450:
        raise ValueError("sample window must contain 300-450 frames")
    if end <= start:
        raise ValueError("sample window must be half-open with endFrameExclusive > startFrame")
    return start, end


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_media(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found")
    result = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], capture_output=True, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout)


def validate_video_master(render_plan: dict[str, Any], *, probe: dict[str, Any] | None = None) -> MasterValidation:
    master = render_plan.get("video_master") or {}
    path = Path(master.get("path", ""))
    reasons: list[str] = []
    if not path.is_file():
        return MasterValidation(False, ("video master is missing",))
    actual_sha = _sha256(path)
    if master.get("sha256") and master["sha256"] != actual_sha:
        reasons.append("video master sha256 mismatch")
    try:
        probe = probe or probe_media(path)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return MasterValidation(False, (f"video master probe failed: {exc}",))
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    profile_name = render_plan.get("profile", "social_vertical_1080p30")
    try:
        from lib.media_profiles import get_profile
        profile = get_profile(profile_name)
    except ValueError:
        return MasterValidation(False, (f"unknown render profile: {profile_name}",), probe)
    if video.get("codec_name") not in {"h264", "avc1"}:
        reasons.append("master must use H.264")
    if video.get("pix_fmt") != profile.pixel_format:
        reasons.append(f"master pixel format must be {profile.pixel_format}")
    if int(video.get("width", 0)) != profile.width or int(video.get("height", 0)) != profile.height:
        reasons.append("master dimensions do not match profile")
    rate = video.get("r_frame_rate", "0/1")
    try:
        numerator, denominator = rate.split("/")
        if abs(float(numerator) / float(denominator) - profile.fps) > 0.01:
            reasons.append("master fps does not match profile")
    except (ValueError, ZeroDivisionError):
        reasons.append("master fps is invalid")
    expected_duration = render_plan.get("duration_seconds")
    actual_duration = float((probe.get("format") or {}).get("duration", 0) or 0)
    if expected_duration is not None and abs(actual_duration - float(expected_duration)) > 1 / profile.fps:
        reasons.append("master duration drift exceeds one frame")
    return MasterValidation(not reasons, tuple(reasons), probe)

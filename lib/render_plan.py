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


def validate_window(start_frame: int, end_frame_exclusive: int) -> tuple[int, int]:
    """Window route (render-gradient layer 2): 30-90 frames for transitions,
    blank frames and motion continuity. Cheaper than a sample; agent-internal."""
    start, end = int(start_frame), int(end_frame_exclusive)
    duration = end - start
    if start < 0 or duration < 30 or duration > 90:
        raise ValueError("window must contain 30-90 frames")
    if end <= start:
        raise ValueError("window must be half-open with endFrameExclusive > startFrame")
    return start, end


def validate_still_frames(frames: list[int], total_frames: int) -> list[int]:
    """Still route (render-gradient layer 1): 1-3 target frames for CTA, crop
    and source-caption inspection. Each frame must land inside [0, total)."""
    total = int(total_frames)
    if total <= 0:
        raise ValueError("total_frames must be positive for still validation")
    cleaned: list[int] = []
    for raw in frames:
        frame = int(raw)
        if frame < 0 or frame >= total:
            raise ValueError(f"still frame {frame} outside [0, {total})")
        if frame not in cleaned:
            cleaned.append(frame)
    if not 1 <= len(cleaned) <= 3:
        raise ValueError("still route requires 1-3 distinct frames")
    return cleaned


def validate_range_render(
    from_frame: int, total_frames: int, *, timeline_stable: bool
) -> tuple[int, int]:
    """Range route (B4): re-render frames [from_frame, total) and reuse the
    prefix [0, from_frame) of the previous master.

    Requires `timeline_stable` — the change must be confined to frames >=
    from_frame with NO duration shift before from_frame (a moved cut invalidates
    the prefix reuse). Also requires an existing master to splice from.
    """
    start = int(from_frame)
    total = int(total_frames)
    if not timeline_stable:
        raise ValueError(
            "range render requires timeline_stable=true (change confined to "
            "frames >= from_frame, no duration shift)"
        )
    if start <= 0 or start >= total:
        raise ValueError(f"range from_frame must satisfy 0 < from_frame < total ({start} vs {total})")
    if total - start < 1:
        raise ValueError("range must contain at least one frame")
    return start, total


# Render-gradient ladder (cheapest first). Agent contract: a local visual
# change (CTA text, crop, captions) starts at `still`; transitions/blank-frame
# checks use `window`; the user only ever reviews `sample` or `full`. Layers
# below the user-facing layer are agent-internal self-gates.
RENDER_GRADIENT = ("still", "window", "sample", "full", "range", "mux_only")


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

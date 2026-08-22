"""Shared deterministic media QA primitives.

Single source of truth for probe / decode / anomaly / loudness checks used by
`final_qa` (post-render technical health) and `technical_validator` (L1a
business gate). Both tools keep their own responsibility boundary but share
these pure functions so the checks cannot drift apart.

Design_Review_2026-08-22.md P0-1: "把公共检查抽到 lib/qa_checks.py".
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any


def probe_media(path: Path | str) -> dict[str, Any]:
    """ffprobe the media file and return the parsed JSON (streams + format)."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout)


def decode_smoke(path: Path | str) -> bool:
    """Full-decode smoke test: return True when ffmpeg can decode to null."""
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=300, check=False,
    ).returncode == 0


def run_filter_log(path: Path | str, filter_graph: str) -> str:
    """Run an ffmpeg video filter and return its stderr log (detector output)."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-vf", filter_graph, "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300, check=False,
    )
    return result.stderr or ""


def parse_ffmpeg_ranges(log: str, marker: str) -> list[dict[str, float]]:
    """Parse detector lines (blackdetect/freezedetect) from ffmpeg stderr.

    Detector tokens use ``key:value`` (e.g. ``black_start:1.0``) while some
    metadata tokens use ``key=value``; accept both.
    """
    ranges: list[dict[str, float]] = []
    for line in log.splitlines():
        if marker not in line:
            continue
        values: dict[str, float] = {}
        for token in line.split():
            key, value = None, None
            for sep in ("=", ":"):
                if sep in token:
                    key, _, value = token.partition(sep)
                    break
            if key is None:
                continue
            try:
                values[key] = float(value)
            except ValueError:
                pass
        if values:
            ranges.append(values)
    return ranges


def detect_black(path: Path | str) -> list[dict[str, float]]:
    """Black-frame ranges (seconds) using the standard delivery detector settings."""
    return parse_ffmpeg_ranges(
        run_filter_log(path, "blackdetect=d=0.15:pix_th=0.10:pic_th=0.98"), "black_start"
    )


def detect_freeze(path: Path | str) -> list[dict[str, float]]:
    """Freeze-frame ranges (seconds) using the standard delivery detector settings."""
    return parse_ffmpeg_ranges(
        run_filter_log(path, "freezedetect=n=-50dB:d=1.00"), "freeze_start"
    )


def measure_loudness(path: Path | str) -> dict[str, Any]:
    """EBU R128 loudness: integrated LUFS, true peak dBTP and LRA where available.

    Non-finite values (e.g. -inf LUFS on a silent track) are normalized to
    None so downstream hashing/serialization stays JCS-safe.
    """
    loudness: dict[str, Any] = {"integrated_lufs": None, "true_peak_dbtp": None, "lra": None}

    def _fin(value: str) -> float | None:
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300, check=False,
    )
    for line in (result.stderr or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("I:"):
            loudness["integrated_lufs"] = _fin(stripped.split()[1]) if len(stripped.split()) > 1 else None
        if stripped.startswith("Peak:"):
            loudness["true_peak_dbtp"] = _fin(stripped.split()[1]) if len(stripped.split()) > 1 else None
        if stripped.startswith("LRA:"):
            loudness["lra"] = _fin(stripped.split()[1]) if len(stripped.split()) > 1 else None
    return loudness


def first_stream(probe: dict[str, Any], codec_type: str) -> dict[str, Any]:
    """First stream of the given codec_type, or an empty dict."""
    return next((s for s in probe.get("streams", []) if s.get("codec_type") == codec_type), {})


def fps_of(stream: dict[str, Any]) -> float:
    """Best-effort fps from ffprobe frame-rate fields."""
    fps_text = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        num, den = fps_text.split("/", 1)
        return round(float(num) / max(float(den), 1.0), 2)
    except (AttributeError, TypeError, ValueError):
        return 0.0

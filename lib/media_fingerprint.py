"""Measured, advisory media fingerprints; never an independent-work verdict."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from lib.production_evidence import file_sha256


def fingerprint_media(path: Path) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Missing media")
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                       "-of", "json", str(path)], check=True, capture_output=True, timeout=30).stdout)
    duration = float(probe["format"]["duration"])
    if not 0 < duration <= 600:
        raise ValueError("Fingerprint accepts films up to 600 seconds")

    def decoded(limit, rate, size):
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-t", str(limit), "-an",
                               "-vf", f"fps={rate},scale={size}:flags=area", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
                              check=True, capture_output=True, timeout=120).stdout

    opening = decoded(min(3, duration), 10, "64:64")
    frames = decoded(duration, 1, "9:8")
    if not opening or len(frames) < 72:
        raise ValueError("No decodable fingerprint frames")
    dhashes, hashes = [], []
    for offset in range(0, len(frames) - 71, 72):
        frame = frames[offset:offset + 72]
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | int(frame[y * 9 + x] > frame[y * 9 + x + 1])
        dhashes.append(f"{bits:016x}")
        hashes.append(hashlib.sha256(frame).hexdigest())
    return {"version": "1.0", "method": "decoded_pixels_gray_v1", "media_sha256": file_sha256(path),
            "duration_seconds": duration, "first_three_seconds_sha256": hashlib.sha256(opening).hexdigest(),
            "keyframe_sha256s": hashes, "keyframe_dhashes": dhashes,
            "sample_interval_seconds": 1, "semantic_uniqueness_verified": False}


def compare_media(left: dict, right: dict) -> dict:
    if left.get("method") != "decoded_pixels_gray_v1" or right.get("method") != left.get("method"):
        raise ValueError("Incompatible fingerprint methods")
    a, b = left["keyframe_dhashes"], right["keyframe_dhashes"]
    near = sum(any((int(x, 16) ^ int(y, 16)).bit_count() <= 8 for y in b) for x in a)
    return {"method": "decoded_pixels_gray_v1", "left_sha256": left["media_sha256"], "right_sha256": right["media_sha256"],
            "exact_same_media": left["media_sha256"] == right["media_sha256"],
            "first_three_seconds_repeated": left["first_three_seconds_sha256"] == right["first_three_seconds_sha256"],
            "near_frame_fraction": near / len(a) if a else None,
            "human_review_required": True,
            "limitations": "1 fps grayscale dHash is an advisory screen: flat backgrounds and brand overlays may match; no automatic duplicate rejection."}

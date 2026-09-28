"""Bounded streaming media primitives for the fixed s01 caption trial."""

from __future__ import annotations

import json
import subprocess
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np

from tools.video.temporal_caption_repair import (
    _capture, _encode_raw, _file_path, _pgm_mask, _probe_metadata,
    _probe_timestamps, _source_hash, _stderr_reader, _timer,
    _MEDIA_TIMEOUT,
)

PILOT_SOURCE_SHA256 = "163a97e1536698d5dff1a61b075b60de7acfdf0500cde661c29664a45a8d0a61"
PILOT_MASK_SHA256 = "e4cdd2fa8c772889b2766ec5e3583893fd4642a921566297c600d51bbc9ba6d8"
WIDTH, HEIGHT, FPS, SOURCE_FRAMES, PADDED_FRAMES = 720, 1280, 30, 38, 81
MAX_CANDIDATE_BYTES = 100 * 1024 * 1024


def padding_map() -> list[int]:
    return [min(37, max(0, j - 21)) for j in range(PADDED_FRAMES)]


def precondition_frame(source: np.ndarray, mask: np.ndarray, mode: str) -> np.ndarray:
    """Prepare model conditioning without changing the immutable source frame."""
    if mode not in {"source_rgb", "vace_gray127"}:
        raise ValueError("unsupported input preprocessing")
    if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("conditioning requires uint8 RGB source")
    if mask.dtype != np.bool_ or mask.shape != source.shape[:2]:
        raise ValueError("conditioning mask geometry/dtype differs from source")
    result = source.copy()
    if mode == "vace_gray127":
        result[mask] = 127
    return result


def composite_frame(source: np.ndarray, candidate: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if source.shape != candidate.shape or source.ndim != 3 or source.shape[2] != 3 or mask.shape != source.shape[:2]:
        raise ValueError("source, candidate, and mask geometry must match")
    if source.dtype != np.uint8 or candidate.dtype != np.uint8 or mask.dtype != np.bool_:
        raise ValueError("composite inputs must be uint8 RGB and boolean mask")
    result = source.copy()
    result[mask] = candidate[mask]
    return result


def stream_rgb(path: Path, width: int, height: int, *, expected_frames: int, limit_frames: int | None = None):
    """Yield one RGB frame at a time; reject short, extra, or failed decode."""
    path = _file_path(path, "video")
    size = width * height * 3
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe",
               "-noautorotate", "-i", str(path), "-map", "0:v:0", "-an", "-sn",
               "-vsync", "0"]
    if limit_frames is not None:
        if limit_frames != expected_frames:
            raise ValueError("limit_frames must match expected_frames")
        command += ["-frames:v", str(limit_frames)]
    command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stderr = bytearray()
    overflow = threading.Event()
    reader = threading.Thread(target=_stderr_reader, args=(process, stderr, overflow), daemon=True)
    reader.start()
    timer, timed_out = _timer(process, _MEDIA_TIMEOUT)
    try:
        for index in range(expected_frames):
            raw = bytearray()
            while len(raw) < size:
                part = process.stdout.read(size - len(raw))
                if not part:
                    raise ValueError(f"decoded frame count ended at {index}; expected {expected_frames}")
                raw.extend(part)
            yield np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
        if process.stdout.read(1):
            raise ValueError("decoded frame count exceeds expected frames")
        process.wait()
        if timed_out.is_set() or overflow.is_set() or process.returncode:
            raise ValueError("video decode timed out or failed: " + stderr.decode("utf-8", "replace")[-500:])
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        reader.join(timeout=2)


def encode_rgb(path: Path, frames, width: int, height: int, fps: int, *, codec: str) -> None:
    if codec not in {"ffv1", "h264rgb"}:
        raise ValueError("unsupported codec")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-map", "0:v:0",
               "-an", "-sn", "-fps_mode", "cfr"]
    if codec == "ffv1":
        command += ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0"]
    else:
        command += ["-c:v", "libx264rgb", "-preset", "veryfast", "-crf", "0", "-pix_fmt", "rgb24"]
    _encode_raw(command + [str(path)], frames)


def verify_video(path: Path, width: int, height: int, fps: int, count: int) -> int:
    path = _file_path(path, "video")
    stream_info = json.loads(_capture(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                                     "-show_entries", "stream=codec_type", "-of", "json", str(path)],
                                    limit=16384, timeout=30))
    if [stream.get("codec_type") for stream in stream_info.get("streams", [])] != ["video"]:
        raise ValueError("contract video must contain one silent video stream only")
    actual_width, actual_height, actual_fps, time_base = _probe_metadata(path)
    if (actual_width, actual_height) != (width, height):
        raise ValueError("video geometry differs from contract")
    if actual_fps != Fraction(fps):
        raise ValueError("video frame rate differs from contract")
    actual_count = _probe_timestamps(path, width, height, actual_fps, time_base)
    if actual_count != count:
        raise ValueError("video frame count differs from contract")
    return actual_count


def verify_pilot_source(source: Path, mask_path: Path):
    source, mask_path = _file_path(source, "input_path"), _file_path(mask_path, "mask_path")
    if _source_hash(source) != PILOT_SOURCE_SHA256 or _source_hash(mask_path) != PILOT_MASK_SHA256:
        raise ValueError("source or mask hash is outside approved s01 pilot")
    width, height, fps, time_base = _probe_metadata(source)
    if (width, height, fps) != (WIDTH, HEIGHT, Fraction(FPS)):
        raise ValueError("source geometry or frame rate is outside approved s01 pilot")
    if _probe_timestamps(source, width, height, fps, time_base) < SOURCE_FRAMES:
        raise ValueError("source frame count is shorter than approved interval")
    mask, marked = _pgm_mask(mask_path, WIDTH, HEIGHT)
    if marked != 12869:
        raise ValueError("glyph mask pixel count differs from approved pilot")
    return mask


def validate_contract(path: Path) -> dict:
    path = _file_path(path, "contract_path")
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("version") not in {1, 2} or contract.get("frame_map") != padding_map():
        raise ValueError("repair contract mapping differs from fixed pilot")
    mode = contract.get("input_preprocessing", "source_rgb")
    if (contract["version"] == 1 and mode != "source_rgb") or (contract["version"] == 2 and mode != "vace_gray127"):
        raise ValueError("repair contract preprocessing differs from version")
    if contract.get("source", {}).get("sha256") != PILOT_SOURCE_SHA256 or contract.get("mask", {}).get("sha256") != PILOT_MASK_SHA256:
        raise ValueError("repair contract hashes differ from fixed pilot")
    if (contract.get("pilot") != "s01_wan_vace14b_once" or contract.get("geometry") != [WIDTH, HEIGHT]
            or contract.get("fps") != FPS or contract.get("padded_frames") != PADDED_FRAMES
            or contract.get("audio") != "absent" or contract.get("encoding") != "libx264rgb-crf0"
            or contract["source"].get("frame_interval") != [0, SOURCE_FRAMES]
            or contract["mask"].get("polarity") != "255=replace"):
        raise ValueError("repair contract settings differ from fixed pilot")
    source = _file_path(contract["source"]["path"], "source")
    mask = _file_path(contract["mask"]["path"], "mask")
    approved_mask = verify_pilot_source(source, mask)
    for key in ("input_video", "mask_video"):
        item = contract[key]
        media = _file_path(item["path"], key)
        if media.parent != path.parent or _source_hash(media) != item["sha256"]:
            raise ValueError(f"{key} path/hash differs from immutable contract")
        verify_video(media, WIDTH, HEIGHT, FPS, PADDED_FRAMES)
    original = stream_rgb(source, WIDTH, HEIGHT, expected_frames=SOURCE_FRAMES, limit_frames=SOURCE_FRAMES)
    prepared = stream_rgb(Path(contract["input_video"]["path"]), WIDTH, HEIGHT, expected_frames=PADDED_FRAMES)
    mask_video = stream_rgb(Path(contract["mask_video"]["path"]), WIDTH, HEIGHT, expected_frames=PADDED_FRAMES)
    try:
        first = next(original)
        last = first
        for index in range(PADDED_FRAMES):
            if index <= 21:
                expected = first
            elif index <= 58:
                expected = next(original)
                last = expected
            else:
                expected = last
            if not np.array_equal(next(prepared), precondition_frame(expected, approved_mask, mode)):
                raise ValueError(f"prepared input frame {index} differs from approved source mapping")
            rendered_mask = next(mask_video)
            if any(not np.array_equal(rendered_mask[:, :, channel] >= 128, approved_mask) for channel in range(3)):
                raise ValueError(f"prepared mask frame {index} differs from approved glyph mask")
        for decoder in (original, prepared, mask_video):
            if next(decoder, None) is not None:
                raise ValueError("prepared artifact has extra frames")
    finally:
        original.close()
        prepared.close()
        mask_video.close()
    return contract

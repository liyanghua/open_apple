"""Bounded, local source-pixel caption repair diagnostic.

Outputs are review evidence only. This adapter never approves production use.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, ResourceProfile, ToolResult, ToolStability, ToolTier


_PROBE_LIMIT = 2 * 1024 * 1024
_STDERR_LIMIT = 256 * 1024
_PROBE_TIMEOUT = 30
_MEDIA_TIMEOUT = 120


def _read_pipe(pipe, cap: int, sink: bytearray, over_limit: threading.Event, process):
    try:
        while chunk := pipe.read(65536):
            if len(sink) + len(chunk) > cap:
                over_limit.set()
                process.kill()
                break
            sink.extend(chunk)
    finally:
        pipe.close()


def _capture(command: list[str], *, limit: int, timeout: int) -> bytearray:
    """Capture both pipes with hard byte and wall-clock bounds."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    stdout, stderr = bytearray(), bytearray()
    overflow = threading.Event()
    readers = [threading.Thread(target=_read_pipe, args=(pipe, cap, sink, overflow, process), daemon=True)
               for pipe, cap, sink in ((process.stdout, limit, stdout),
                                       (process.stderr, _STDERR_LIMIT, stderr))]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise ValueError(f"media command timed out after {timeout}s") from exc
    finally:
        for reader in readers:
            reader.join(timeout=2)
    if overflow.is_set():
        raise ValueError("media command exceeded bounded output limit")
    if process.returncode:
        raise ValueError(f"media command failed: {stderr.decode('utf-8', 'replace')[-1000:]}")
    return stdout


def _stderr_reader(process, sink: bytearray, overflow: threading.Event):
    _read_pipe(process.stderr, _STDERR_LIMIT, sink, overflow, process)


def _timer(process, seconds: int):
    timed_out = threading.Event()

    def expire():
        timed_out.set()
        process.kill()

    timer = threading.Timer(seconds, expire)
    timer.daemon = True
    timer.start()
    return timer, timed_out


def _encode_raw(command: list[str], frames) -> None:
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    stderr = bytearray()
    overflow = threading.Event()
    reader = threading.Thread(target=_stderr_reader, args=(process, stderr, overflow), daemon=True)
    reader.start()
    timer, timed_out = _timer(process, _MEDIA_TIMEOUT)
    try:
        for frame in frames:
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        process.wait()
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        timer.cancel()
        reader.join(timeout=2)
    if timed_out.is_set():
        raise ValueError("media encode timed out")
    if overflow.is_set():
        raise ValueError("media encode stderr exceeded limit")
    if process.returncode:
        raise ValueError(f"media encode failed: {stderr.decode('utf-8', 'replace')[-1000:]}")


def _verify_master(master: Path, originals, mask) -> int:
    """Decode one FFV1 frame at a time; assert RGB identity outside the mask."""
    import numpy as np

    count, height, width, _ = originals.shape
    frame_bytes = height * width * 3
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe",
               "-i", str(master), "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    stderr = bytearray()
    overflow = threading.Event()
    reader = threading.Thread(target=_stderr_reader, args=(process, stderr, overflow), daemon=True)
    reader.start()
    timer, timed_out = _timer(process, _MEDIA_TIMEOUT)
    verified = 0
    try:
        for index in range(count):
            chunks = bytearray()
            while len(chunks) < frame_bytes:
                chunk = process.stdout.read(frame_bytes - len(chunks))
                if not chunk:
                    raise ValueError("lossless master ended before expected frame count")
                chunks.extend(chunk)
            frame = np.frombuffer(chunks, np.uint8).reshape(height, width, 3)
            if not np.array_equal(frame[~mask], originals[index, ~mask]):
                raise ValueError(f"lossless master changed pixels outside mask in frame {index}")
            verified += 1
        if process.stdout.read(1):
            raise ValueError("lossless master has extra decoded frames")
        process.wait()
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        timer.cancel()
        process.stdout.close()
        reader.join(timeout=2)
    if timed_out.is_set():
        raise ValueError("lossless master verification timed out")
    if overflow.is_set() or process.returncode:
        raise ValueError(f"lossless master decode failed: {stderr.decode('utf-8', 'replace')[-1000:]}")
    return verified


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_path(raw: Any, label: str) -> Path:
    if not isinstance(raw, (str, os.PathLike)):
        raise ValueError(f"{label} must be a local file path")
    path = Path(raw).absolute()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be an existing regular file, not a symlink")
    return path


def _output_path(raw: Any, source: Path, mask: Path) -> Path:
    if not isinstance(raw, (str, os.PathLike)):
        raise ValueError("output_dir must be a local path")
    path = Path(raw).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("output_dir already exists; overwrite is forbidden")
    if not path.parent.is_dir():
        raise ValueError("output_dir parent must already exist")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError("output_dir must not have symlink ancestors")
    if path == Path(path.anchor) or path in (source, mask, source.parent, mask.parent):
        raise ValueError("output_dir aliases an input or input directory")
    return path


def _pgm_mask(path: Path, width: int, height: int):
    """Accept only compact P5 8-bit 0/255 masks with exact geometry."""
    import numpy as np

    with path.open("rb") as stream:
        header = bytearray()
        tokens = []
        while len(tokens) < 4 and len(header) < 4096:
            byte = stream.read(1)
            if not byte:
                break
            header.extend(byte)
            if byte in b" \t\r\n":
                words = bytes(header).split()
                tokens = words[:4]
        if len(tokens) != 4 or tokens[0] != b"P5":
            raise ValueError("mask must be binary P5 PGM")
        try:
            mask_width, mask_height, maximum = map(int, tokens[1:])
        except ValueError as exc:
            raise ValueError("invalid PGM mask header") from exc
        if (mask_width, mask_height, maximum) != (width, height, 255):
            raise ValueError("mask geometry/maxval must match source and use 8-bit PGM")
        payload = stream.read(width * height + 1)
        if len(payload) != width * height or stream.read(1):
            raise ValueError("mask payload size mismatch")
    pixels = np.frombuffer(payload, np.uint8).reshape(height, width)
    if not np.all((pixels == 0) | (pixels == 255)):
        raise ValueError("mask must contain only 0 or 255")
    marked = int(np.count_nonzero(pixels))
    if marked == 0 or marked > 0.1 * width * height:
        raise ValueError("mask must be nonempty and cover at most 10% of frame")
    return pixels != 0, marked


def _probe_metadata(path: Path):
    command = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
               "-select_streams", "v:0", "-show_entries",
               "stream=width,height,avg_frame_rate,r_frame_rate,time_base",
               "-show_streams", "-of", "json", str(path)]
    info = json.loads(_capture(command, limit=_PROBE_LIMIT, timeout=_PROBE_TIMEOUT))
    streams = info.get("streams", [])
    if len(streams) != 1:
        raise ValueError("source requires a decodable video stream")
    stream = streams[0]
    width, height = int(stream["width"]), int(stream["height"])
    fps = Fraction(stream["avg_frame_rate"])
    nominal = Fraction(stream["r_frame_rate"])
    time_base = Fraction(stream["time_base"])
    if fps <= 0 or nominal <= 0 or fps != nominal or time_base <= 0:
        raise ValueError("source frame rate is missing or inconsistent")
    return width, height, fps, str(time_base)


def _probe_timestamps(path: Path, width: int, height: int, fps: Fraction, time_base_str: str):
    """Require frame timestamps and geometry after the resource gate is known safe."""
    command = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
               "-select_streams", "v:0", "-show_entries",
               "stream=nb_frames:frame=best_effort_timestamp,width,height",
               "-show_streams", "-show_frames", "-of", "json", str(path)]
    info = json.loads(_capture(command, limit=_PROBE_LIMIT, timeout=_PROBE_TIMEOUT))
    frames = info.get("frames", [])
    if not frames:
        raise ValueError("source lacks frame timestamp proof")
    streams = info.get("streams", [])
    declared = streams[0].get("nb_frames") if len(streams) == 1 else None
    if declared is not None and int(declared) != len(frames):
        raise ValueError("source frame count disagrees with frame timestamps")
    try:
        if any(int(frame["width"]) != width or int(frame["height"]) != height for frame in frames):
            raise ValueError("source frame geometry changes within video")
        ticks = [int(frame["best_effort_timestamp"]) for frame in frames]
    except (KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, ValueError) and "geometry" in str(exc):
            raise
        raise ValueError("source is missing per-frame timestamp proof") from exc
    time_base = Fraction(time_base_str)
    origin = Fraction(ticks[0]) * time_base
    tolerance = time_base / 2 + Fraction(1, 1_000_000)
    for index, tick in enumerate(ticks):
        actual = Fraction(tick) * time_base
        expected = origin + Fraction(index, 1) / fps
        if abs(actual - expected) > tolerance:
            raise ValueError("source has variable frame timestamps (VFR)")
    return len(frames)


class TemporalCaptionRepair(BaseTool):
    name = "temporal_caption_repair"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "local"
    stability = ToolStability.EXPERIMENTAL
    dependencies = ["python:cv2", "python:numpy", "cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "Install OpenCV and NumPy in this Python environment, plus FFmpeg/ffprobe on PATH."
    capabilities = ["source_pixel_caption_reconstruction", "diagnostic_review_proxy"]
    best_for = ["One verified continuous shot with sparse burned-in caption pixels and clean temporal donors"]
    not_good_for = ["Never-observed backgrounds", "shot cuts", "parallax or occlusion", "audio replacement"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, disk_mb=1000, network_required=False)
    side_effects = ["creates a new output directory with diagnostic media and report"]
    user_visible_verification = ["Inspect repaired region frame by frame and at normal speed before any use"]
    input_schema = {"type": "object", "required": ["input_path", "mask_path", "start_frame",
                    "end_frame_exclusive", "output_dir", "single_shot_verified"],
                    "properties": {"input_path": {"type": "string"}, "mask_path": {"type": "string"},
                                   "start_frame": {"type": "integer", "minimum": 0},
                                   "end_frame_exclusive": {"type": "integer", "minimum": 1},
                                   "output_dir": {"type": "string"},
                                   "single_shot_verified": {"const": True},
                                   "min_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                                   "max_donors": {"type": "integer", "minimum": 1, "maximum": 12}}}

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.monotonic()
        output = None
        owns_output = False
        try:
            self.check_dependencies()
            from lib.temporal_caption_repair import repair_frames, validate_resource_bounds
            import numpy as np

            if not isinstance(inputs, dict):
                raise ValueError("inputs must be a dictionary")
            if inputs.get("single_shot_verified") is not True:
                raise ValueError("single_shot_verified must be literal true for this interval")
            start, end = inputs.get("start_frame"), inputs.get("end_frame_exclusive")
            if any(type(value) is not int for value in (start, end)) or start < 0 or end <= start:
                raise ValueError("frame interval must use nonnegative integer [start,end) bounds")
            count = end - start
            if count > 120:
                raise ValueError("frame interval exceeds 120-frame limit")
            min_coverage = inputs.get("min_coverage", 0.98)
            max_donors = inputs.get("max_donors", 12)
            if type(min_coverage) not in (float, int) or not 0 <= min_coverage <= 1:
                raise ValueError("min_coverage must be a number from 0 to 1")
            if type(max_donors) is not int or not 1 <= max_donors <= 12:
                raise ValueError("max_donors must be an integer from 1 to 12")
            source = _file_path(inputs.get("input_path"), "input_path")
            mask_path = _file_path(inputs.get("mask_path"), "mask_path")
            output = _output_path(inputs.get("output_dir"), source, mask_path)
            t0 = time.monotonic()
            width, height, fps, time_base = _probe_metadata(source)
            estimated_bytes = validate_resource_bounds(count, height, width)
            available = _probe_timestamps(source, width, height, fps, time_base)
            if end > available:
                raise ValueError("requested interval exceeds verified source frame count")
            mask, marked = _pgm_mask(mask_path, width, height)
            probe_seconds = time.monotonic() - t0
            frame_bytes = width * height * 3
            t0 = time.monotonic()
            select = f"select=between(n\\,{start}\\,{end-1})"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe",
                       "-i", str(source), "-map", "0:v:0", "-vf", select, "-vsync", "0",
                       "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
            raw = _capture(command, limit=(count + 1) * frame_bytes, timeout=_MEDIA_TIMEOUT)
            if len(raw) != count * frame_bytes:
                raise ValueError("decoded frame count does not equal requested interval")
            frames = np.frombuffer(raw, np.uint8).reshape(count, height, width, 3)
            decode_seconds = time.monotonic() - t0
            t0 = time.monotonic()
            candidate, evidence = repair_frames(frames, mask, min_coverage=min_coverage, max_donors=max_donors)
            repair_seconds = time.monotonic() - t0
            output.mkdir(exist_ok=False)
            owns_output = True
            master = output / "master.mkv"
            preview = output / "review.mp4"
            rate = f"{fps.numerator}/{fps.denominator}"
            t0 = time.monotonic()
            _encode_raw(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                         "-s", f"{width}x{height}", "-r", rate, "-i", "pipe:0", "-map", "0:v:0",
                         "-an", "-sn", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0", str(master)], candidate)
            encode_seconds = time.monotonic() - t0
            t0 = time.monotonic()
            verified = _verify_master(master, frames, mask)
            verify_seconds = time.monotonic() - t0
            _capture(["ffmpeg", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe",
                      "-i", str(master), "-map", "0:v:0", "-an", "-sn", "-c:v", "libx264", "-crf", "18",
                      "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(preview)],
                     limit=1024, timeout=_MEDIA_TIMEOUT)
            report = {"schema_version": 1, "tool": self.name, "provider": "local", "model": "none",
                      "status": evidence["status"], "diagnostic_only": True,
                      "accepted_for_production": False, "human_review_required": True,
                      "coverage_gate_passed": bool(evidence["coverage_gate_passed"]),
                      "source": {"path": str(source), "sha256": _source_hash(source),
                                 "frame_interval": [start, end], "source_frame_count": available,
                                 "decoded_frame_count": count, "width": width, "height": height,
                                 "fps": rate, "time_base": time_base, "single_shot_verified_by_caller": True},
                      "mask": {"path": str(mask_path), "sha256": _source_hash(mask_path),
                               "masked_pixels_per_frame": marked, "format": "P5 PGM 0/255"},
                      "master": {"path": str(master), "codec": "FFV1", "audio": "absent"},
                      "preview": {"path": str(preview), "codec": "H.264", "audio": "absent",
                                  "purpose": "diagnostic review only; unresolved source pixels remain",
                                  "lossy_not_verified_exact": True},
                      "verification": {"master_outside_mask_exact": True, "verified_frames": verified,
                                       "preview_exactness_checked": False},
                      "limits": {"estimated_peak_working_bytes": estimated_bytes,
                                 "working_memory_target_bytes": 1024**3},
                      "elapsed_seconds": {"probe": probe_seconds, "decode": decode_seconds,
                                          "repair": repair_seconds, "master_encode": encode_seconds,
                                          "master_verify": verify_seconds,
                                          "total": time.monotonic() - started},
                      "core_evidence": evidence}
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            return ToolResult(success=True, data=report,
                              artifacts=[str(master), str(preview), str(output / "report.json")],
                              cost_usd=0.0, duration_seconds=time.monotonic() - started, model="none")
        except Exception as exc:
            if owns_output and output is not None:
                try:
                    (output / "error.json").write_text(json.dumps({"error": str(exc),
                                                                   "accepted_for_production": False,
                                                                   "human_review_required": True}, indent=2),
                                                       encoding="utf-8")
                except OSError:
                    pass
            return ToolResult(success=False, error=str(exc), cost_usd=0.0,
                              duration_seconds=time.monotonic() - started, model="none")

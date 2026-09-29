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


def _stream_command(command, *, maximum_bytes, digest_only=False, timeout=120):
    """Bound output and wall time while draining FFmpeg incrementally."""
    import tempfile
    import threading
    digest, chunks, count = hashlib.sha256(), [], 0
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        expired = threading.Event()
        def stop():
            expired.set()
            process.kill()
        timer = threading.Timer(timeout, stop)
        timer.start()
        try:
            while chunk := process.stdout.read(65536):
                count += len(chunk)
                if count > maximum_bytes:
                    process.kill()
                    raise ValueError("Decoded evidence exceeds bounded output limit")
                digest.update(chunk)
                if not digest_only:
                    chunks.append(chunk)
            code = process.wait(timeout=5)
            if expired.is_set():
                raise ValueError("Decode evidence timed out")
            if code:
                errors.seek(0)
                raise ValueError("Decode failed: " + errors.read(2048).decode(errors="replace"))
        finally:
            timer.cancel()
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    return {"sha256": digest.hexdigest(), "bytes": count} if digest_only else b"".join(chunks)


def decoded_interval_evidence(path: Path, *, start_frame: int, end_frame: int, fps=30, audio=False) -> dict:
    """Explicit measurement producer, never invoked by a dashboard read.

    Frame PTS are checked over the actual complete video. Interval frame MD5s
    retain native resolution and timestamps. Audio is decoded only for the
    requested interval and remains an observation of the compressed film.
    """
    from fractions import Fraction
    if (isinstance(start_frame, bool) or isinstance(end_frame, bool) or not isinstance(start_frame, int)
            or not isinstance(end_frame, int) or not 0 <= start_frame < end_frame <= 18000 or fps != 30):
        raise ValueError("Expected a bounded integer 30fps interval")
    path = Path(path).resolve()
    probe = json.loads(_stream_command(["ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels:format=duration", "-of", "json", str(path)], maximum_bytes=16384))
    duration = float(probe["format"]["duration"])
    if not 0 < duration <= 600:
        raise ValueError("Interval evidence accepts films up to 600 seconds")
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if Fraction(video["avg_frame_rate"]) != 30 or Fraction(video["r_frame_rate"]) != 30:
        raise ValueError("Video must have actual 30fps cadence")
    if video["width"] * video["height"] > 3840 * 2160:
        raise ValueError("Video dimensions exceed decode evidence limit")
    raw_pts = _stream_command(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(path)], maximum_bytes=2 * 1024 * 1024)
    pts = [float(line.split(",")[0]) for line in raw_pts.decode().splitlines() if line.split(",")[0].strip()]
    if not end_frame <= len(pts) <= 18000 or any(abs(t - i / fps) > 1e-5 for i, t in enumerate(pts)):
        raise ValueError("Video frame count or actual timestamps disagree with 30fps boundary")
    raw_frames = _stream_command(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-an",
        "-vf", f"select=gte(n\\,{start_frame})*lt(n\\,{end_frame})", "-vsync", "0", "-f", "framemd5", "pipe:1"], maximum_bytes=4 * 1024 * 1024)
    frames = []
    for line in raw_frames.decode().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        fields = [part.strip() for part in line.split(",")]
        frames.append({"frame": start_frame + len(frames), "pts": int(fields[2]), "size": int(fields[4]), "md5": fields[5]})
    if len(frames) != end_frame - start_frame or any(row["pts"] != row["frame"] for row in frames):
        raise ValueError("Interval decode has missing frames or incorrect timestamps")
    result = {"version": "1.0", "method": "ffmpeg_native_interval_v1", "media_sha256": file_sha256(path),
        "interval_frames": [start_frame, end_frame], "fps": fps, "duration_seconds": duration,
        "total_video_frames": len(pts), "video": {"width": video["width"], "height": video["height"],
        "frames": frames, "timestamps_seconds": pts[start_frame:end_frame], "raw_framemd5": raw_frames.decode()},
        "semantic_continuity_verified": False}
    if audio:
        stream = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
        if not stream:
            raise ValueError("Full film has no audio stream")
        rate, channels = int(stream["sample_rate"]), int(stream["channels"])
        if not 0 < rate <= 192000 or not 0 < channels <= 8:
            raise ValueError("Audio profile outside measurement limits")
        start, end = start_frame / fps, end_frame / fps
        decoded = _stream_command(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-vn",
            "-af", f"atrim=start={start}:end={end}", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
            maximum_bytes=int((end - start) * rate * channels * 2 + rate * channels * 2), digest_only=True)
        samples = decoded["bytes"] // (channels * 2)
        if samples != round((end - start) * rate):
            raise ValueError("Decoded audio does not cover the complete join interval")
        result["audio"] = {"sample_rate": rate, "channels": channels, "samples": samples,
                           "decoded_pcm_sha256": decoded["sha256"]}
    return result


def compare_decoded_intervals(left: Path, right: Path, *, start_frame: int, end_frame: int) -> dict:
    """Decoded match/difference is advisory, even when encoded bytes differ."""
    a = decoded_interval_evidence(left, start_frame=start_frame, end_frame=end_frame)
    b = decoded_interval_evidence(right, start_frame=start_frame, end_frame=end_frame)
    return {"status": "pass", "method": a["method"], "interval_frames": a["interval_frames"],
            "decoded_body_match": a["video"] == b["video"], "left_sha256": a["media_sha256"],
            "right_sha256": b["media_sha256"], "advisory_only": True, "freeze_verified": False,
            "semantic_continuity_verified": False}

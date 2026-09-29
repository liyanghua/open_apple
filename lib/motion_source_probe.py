"""Bounded, streaming verification of actual decoded presentation timestamps."""
from __future__ import annotations

from fractions import Fraction
import math
from pathlib import Path
import shutil
import subprocess
import threading


def probe_motion_source_cadence(path: Path, probe: dict, *, max_frames: int = 4096,
                               max_duration_seconds: float = 120, timeout_seconds: float = 30) -> dict:
    """Read every frame PTS, keeping only count and cadence extrema in memory.

    Fractional frame periods permit floor/ceil time-base ticks and at most one
    tick of cumulative rounding. Integral periods require exactly that cadence.
    No source normalization or metadata-only CFR certification is performed.
    """
    try:
        videos = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
        if len(videos) != 1:
            raise ValueError("exactly one video stream is required")
        video = videos[0]
        expected_count = int(video["nb_frames"])
        duration = float(video["duration"])
        if expected_count < 2 or expected_count > max_frames or not 0 < duration <= max_duration_seconds:
            raise ValueError("source exceeds bounded frame-count/duration limits or has no cadence interval")
        rate = Fraction(video.get("avg_frame_rate") or video["r_frame_rate"])
        time_base = Fraction(video["time_base"])
        if rate <= 0 or time_base <= 0 or timeout_seconds <= 0:
            raise ValueError("rate, time base and timeout must be positive")
        period = 1 / (rate * time_base)
        if period < 1:
            raise ValueError("source time base cannot resolve the declared frame cadence")
        allowed = {math.floor(period), math.ceil(period)}
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise ValueError("ffprobe is unavailable")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"motion source PTS cadence: {exc}") from exc

    command = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
               "-show_entries", "frame=pts:frame_side_data=", "-of", "csv=p=0", str(path)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    timed_out = threading.Event()
    def expire():
        if process.poll() is None:
            timed_out.set()
            try:
                process.kill()
            except ProcessLookupError:
                pass
    timer = threading.Timer(timeout_seconds, expire)
    timer.daemon = True
    timer.start()
    count, lines, first, previous, smallest, largest = 0, 0, None, None, None, None
    try:
        assert process.stdout is not None
        while True:
            line = process.stdout.readline(4097)
            if not line:
                break
            lines += 1
            if len(line) > 4096 or lines > 2 * max_frames + 16:
                raise ValueError("decoded output exceeds bounded line/frame limits")
            if not line.strip():
                continue
            pts = int(line.split(",", 1)[0].strip())
            count += 1
            if count > expected_count or count > max_frames:
                raise ValueError("decoded frame count exceeds declared/bounded frame count")
            if first is None:
                first = pts
            if previous is not None:
                delta = pts - previous
                if delta <= 0 or delta not in allowed or abs(Fraction(pts - first) - (count - 1) * period) > 1:
                    raise ValueError(f"variable PTS cadence at frame {count - 1}: delta {delta} ticks; allowed {sorted(allowed)}")
                smallest = delta if smallest is None else min(smallest, delta)
                largest = delta if largest is None else max(largest, delta)
            previous = pts
        return_code = process.wait(timeout=1)
        if timed_out.is_set():
            raise ValueError("ffprobe decoded PTS timeout")
        if return_code != 0:
            raise ValueError(f"ffprobe decoded PTS failed with exit {return_code}")
        if count != expected_count:
            raise ValueError(f"decoded frame count {count} differs from declared {expected_count}")
        return {"frame_count": count, "first_pts": first, "last_pts": previous, "time_base": str(time_base),
                "expected_period_ticks": str(period), "allowed_delta_ticks": sorted(allowed),
                "min_delta_ticks": smallest, "max_delta_ticks": largest, "measurement": "all_decoded_frame_pts"}
    except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"motion source PTS cadence: {exc}") from exc
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        if process.stdout is not None:
            process.stdout.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

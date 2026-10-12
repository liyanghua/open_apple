"""Pure validation helpers for strict reference timelines."""
from __future__ import annotations

from typing import Any, Iterable


def validate_intervals(intervals: Iterable[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    previous_end = -1.0
    for index, item in enumerate(intervals):
        start = item.get("start_seconds")
        end = item.get("end_seconds_exclusive")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            errors.append(f"interval {index} must contain numeric bounds")
            continue
        if start < 0 or end <= start:
            errors.append(f"interval {index} must use a positive half-open range")
        if start < previous_end:
            errors.append(f"interval {index} overlaps the previous interval")
        previous_end = max(previous_end, end)
    return errors


def duration_drift_ms(reference_seconds: float, target_seconds: float) -> int:
    return round((target_seconds - reference_seconds) * 1000)


def build_reference_timeline(*, project_id: str, fps: float, duration_seconds: float, shots: list[dict[str, Any]], **metadata: Any) -> dict[str, Any]:
    if fps <= 0:
        raise ValueError("fps must be positive")
    errors = validate_intervals(shots)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "version": "1.0",
        "project_id": project_id,
        "fps": fps,
        "duration_seconds": duration_seconds,
        "shots": shots,
        **metadata,
    }

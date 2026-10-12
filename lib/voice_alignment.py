"""Small, deterministic timing checks for segmented narration."""
from __future__ import annotations


def segment_drift_ms(reference_start: float, reference_end: float, target_start: float, target_end: float) -> tuple[int, int]:
    return round((target_start - reference_start) * 1000), round((target_end - reference_end) * 1000)


def within_tolerance(drift_ms: int, tolerance_ms: int) -> bool:
    return abs(drift_ms) <= tolerance_ms

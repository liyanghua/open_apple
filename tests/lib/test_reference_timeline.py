import pytest

from lib.reference_timeline import build_reference_timeline, duration_drift_ms


def test_builds_half_open_reference_timeline():
    result = build_reference_timeline(project_id="demo", fps=30, duration_seconds=2, shots=[
        {"reference_shot_id": "s1", "start_seconds": 0, "end_seconds_exclusive": 1},
        {"reference_shot_id": "s2", "start_seconds": 1, "end_seconds_exclusive": 2},
    ])
    assert result["shots"][1]["start_seconds"] == 1


def test_rejects_overlapping_shots():
    with pytest.raises(ValueError, match="overlaps"):
        build_reference_timeline(project_id="demo", fps=30, duration_seconds=2, shots=[
            {"reference_shot_id": "s1", "start_seconds": 0, "end_seconds_exclusive": 1.2},
            {"reference_shot_id": "s2", "start_seconds": 1, "end_seconds_exclusive": 2},
        ])


def test_duration_drift_is_signed_milliseconds():
    assert duration_drift_ms(12.434, 12.042) == -392

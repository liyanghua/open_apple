from __future__ import annotations

from lib.sample_preflight import validate_sample_inputs


def test_sample_preflight_accepts_valid_window_and_timeline() -> None:
    result = validate_sample_inputs({
        "shot_execution_plan": {"shots": [{"id": "shot-01"}]},
        "final_props": {"fps": 30, "scenes": [{"id": "shot-01"}]},
        "sample_report": {"window": {"startFrame": 0, "endFrameExclusive": 300}},
    })

    assert result == {"ok": True, "issues": []}


def test_sample_preflight_reports_invalid_window_before_render() -> None:
    result = validate_sample_inputs({
        "shot_execution_plan": {"shots": [{"id": "shot-01"}]},
        "final_props": {"fps": 30, "scenes": [{"id": "shot-01"}]},
        "sample_report": {"window": {"startFrame": 0, "endFrameExclusive": 90}},
    })

    assert result["ok"] is False
    assert "样片窗口应为 10-15 秒" in result["issues"]

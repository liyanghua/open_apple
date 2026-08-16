from __future__ import annotations

import json


def test_operator_does_not_publish_efficiency_promise_without_cohort(tmp_path) -> None:
    from backlot.operator_state import _performance_summary

    assert _performance_summary(tmp_path) == {
        "promise": None,
        "message": "实测数据不足，暂不展示效率承诺",
    }


def test_operator_publishes_promise_only_after_benchmark_gate(tmp_path) -> None:
    from backlot.operator_state import _performance_summary

    reports = tmp_path / "analysis/benchmarks"
    reports.mkdir(parents=True)
    (reports / "latest.json").write_text(json.dumps({
        "sla": {"cold": {"sample_count": 3, "publish_sla": True}},
    }), encoding="utf-8")
    assert _performance_summary(tmp_path)["promise"] == "完整制作通常可在 3-5 小时内完成"

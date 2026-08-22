"""Cheap, deterministic checks that run before a sample render starts."""

from __future__ import annotations

from typing import Any, Mapping


def validate_sample_inputs(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    """Return business-readable preflight issues without invoking render tools."""
    issues: list[str] = []
    for name in ("shot_execution_plan", "final_props", "sample_report"):
        if not isinstance(artifacts.get(name), Mapping):
            issues.append(f"缺少{name}产物")

    report = artifacts.get("sample_report") if isinstance(artifacts.get("sample_report"), Mapping) else {}
    window = report.get("window") if isinstance(report.get("window"), Mapping) else {}
    start = window.get("startFrame")
    end = window.get("endFrameExclusive")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        issues.append("样片窗口无效")
    elif end - start < 300 or end - start > 450:
        issues.append("样片窗口应为 10-15 秒")

    props = artifacts.get("final_props") if isinstance(artifacts.get("final_props"), Mapping) else {}
    fps = props.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        issues.append("时间轴缺少有效帧率")
    scenes = props.get("scenes") or props.get("shots") or props.get("timeline")
    if not isinstance(scenes, list) or not scenes:
        issues.append("时间轴没有可执行镜头")

    return {"ok": not issues, "issues": issues}

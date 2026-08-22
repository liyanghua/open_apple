"""Build the business-facing trace from the locked plan and sample timeline."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping


STATUS_LABELS = {
    "executed": "已按方案执行",
    "partial": "部分执行",
    "added": "新增内容",
    "not_in_sample": "尚未进入样片",
}


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_selection(shot: Mapping[str, Any]) -> Mapping[str, Any]:
    value = shot.get("source_selection")
    return value if isinstance(value, Mapping) else {}


def _actual_shots(final_props: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("shots", "timeline", "segments"):
        value = final_props.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    scenes = final_props.get("scenes")
    footage = final_props.get("footage") if isinstance(final_props.get("footage"), Mapping) else {}
    if isinstance(scenes, list):
        fps = _number(final_props.get("fps")) or 30.0
        captions = final_props.get("captions") if isinstance(final_props.get("captions"), list) else []
        normalized: list[dict[str, Any]] = []
        for scene in scenes:
            if not isinstance(scene, Mapping):
                continue
            from_frame = _number(scene.get("fromFrame")) or 0.0
            to_frame = _number(scene.get("toFrameExclusive"))
            start = from_frame / fps
            end = (to_frame / fps) if to_frame is not None else start + (_number(scene.get("durationInFrames")) or 0) / fps
            footage_key = str(scene.get("footageKey") or "")
            source_path = footage.get(footage_key) or footage.get(str(scene.get("assetId") or "")) or ""
            screen_copy = ""
            for caption in captions:
                if not isinstance(caption, Mapping):
                    continue
                cap_start = (_number(caption.get("startMs")) or 0.0) / 1000
                cap_end = (_number(caption.get("endMs")) or 0.0) / 1000
                if cap_end > start and cap_start < end:
                    screen_copy = str(caption.get("text") or "")
                    break
            normalized.append({
                "id": scene.get("id") or scene.get("shotId"),
                "start_seconds": start,
                "end_seconds": end,
                "source_path": source_path,
                "source_in_seconds": scene.get("sourceInSeconds"),
                "source_out_seconds": scene.get("sourceOutSeconds"),
                "screen_copy": screen_copy,
            })
        return normalized
    return []


def _window(sample_report: Mapping[str, Any], fps: float) -> tuple[float, float]:
    raw = sample_report.get("window") or {}
    start = _number(raw.get("startFrame")) or 0.0
    end = _number(raw.get("endFrameExclusive"))
    if end is None or end <= start:
        return 0.0, float("inf")
    return start / fps, end / fps


def _interval(shot: Mapping[str, Any], fallback_start: float = 0.0) -> tuple[float, float]:
    start = next(
        (value for key in ("start_seconds", "timeline_start_seconds", "timeline_in_seconds")
         if (value := _number(shot.get(key))) is not None),
        fallback_start,
    )
    end = next(
        (value for key in ("end_seconds", "timeline_end_seconds", "timeline_out_seconds")
         if (value := _number(shot.get(key))) is not None),
        start + (_number(shot.get("duration_seconds")) or 0.0),
    )
    return start, max(start, end)


def _overlaps(start: float, end: float, window_start: float, window_end: float) -> bool:
    return end > window_start and start < window_end


def _actual_execution(actual: Mapping[str, Any]) -> dict[str, Any]:
    start, end = _interval(actual)
    return {
        "timeline_start_seconds": start,
        "timeline_end_seconds": end,
        "source_path": actual.get("source_path") or actual.get("path") or "",
        "source_in_seconds": _number(actual.get("source_in_seconds")),
        "source_out_seconds": _number(actual.get("source_out_seconds")),
        "screen_copy": actual.get("screen_copy") or actual.get("caption") or "",
        "narration": actual.get("narration") or "",
    }


def _planned_basis(planned: Mapping[str, Any]) -> dict[str, Any]:
    selection = _source_selection(planned)
    return {
        "purpose": planned.get("purpose") or "",
        "subject_action": planned.get("subject_action") or "",
        "screen_copy": planned.get("screen_copy") or "",
        "duration_seconds": _number(planned.get("duration_seconds")),
        "reference_rules": [str(item) for item in planned.get("reference_mechanisms") or []],
        "source_path": selection.get("path") or "",
        "source_in_seconds": _number(selection.get("start_seconds")),
        "source_out_seconds": _number(selection.get("end_seconds")),
    }


def _matches_plan(planned: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    selection = _source_selection(planned)
    expected_path = str(selection.get("path") or "")
    actual_path = str(actual.get("source_path") or actual.get("path") or "")
    if expected_path and actual_path and expected_path != actual_path:
        shot_id = str(planned.get("id") or planned.get("shot_id") or "")
        proxy_marker = shot_id.replace("_", "-") if shot_id else ""
        if not proxy_marker or proxy_marker not in actual_path or "proxy" not in actual_path.lower():
            return False
    for expected_key, actual_key in (("start_seconds", "source_in_seconds"), ("end_seconds", "source_out_seconds")):
        expected = _number(selection.get(expected_key))
        observed = _number(actual.get(actual_key))
        if expected is not None and observed is not None and abs(expected - observed) > 0.01:
            return False
    expected_copy = str(planned.get("screen_copy") or "")
    actual_copy = str(actual.get("screen_copy") or actual.get("caption") or "")
    return not expected_copy or not actual_copy or expected_copy == actual_copy


def build_sample_execution_trace(project_id: str, artifacts: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic, user-facing plan-to-sample comparison."""
    plan = artifacts.get("shot_execution_plan") if isinstance(artifacts.get("shot_execution_plan"), Mapping) else {}
    sample_report = artifacts.get("sample_report") if isinstance(artifacts.get("sample_report"), Mapping) else {}
    final_props = artifacts.get("final_props") if isinstance(artifacts.get("final_props"), Mapping) else {}
    planned = [item for item in plan.get("shots") or [] if isinstance(item, Mapping)]
    actual = _actual_shots(final_props)
    actual_by_id = {str(item.get("id") or item.get("shot_id")): item for item in actual if item.get("id") or item.get("shot_id")}
    fps = _number(final_props.get("fps")) or 30.0
    window_start, window_end = _window(sample_report, fps)
    trace_shots: list[dict[str, Any]] = []
    planned_ids: set[str] = set()
    cursor = 0.0

    for item in sorted(planned, key=lambda value: (_number(value.get("order")) or 0, str(value.get("id") or ""))):
        shot_id = str(item.get("id") or item.get("shot_id") or "")
        if not shot_id:
            continue
        planned_ids.add(shot_id)
        observed = actual_by_id.get(shot_id)
        if observed is not None:
            start, end = _interval(observed, cursor)
            cursor = end
        else:
            duration = _number(item.get("duration_seconds")) or 0.0
            start, end = cursor, cursor + duration
            cursor = end
        included = _overlaps(start, end, window_start, window_end)
        status = "not_in_sample" if not included else "executed" if observed is not None and _matches_plan(item, observed) else "partial"
        deviation = None
        if status == "partial":
            deviation = {"reason": "实际画面与锁定镜头方案存在差异"}
        trace_shots.append({
            "shot_id": shot_id,
            "status": status,
            "status_label": STATUS_LABELS[status],
            "planned_basis": _planned_basis(item),
            "actual_execution": _actual_execution(observed) if observed is not None else None,
            "deviation": deviation,
            "sample_window": {"included": included, "start_seconds": start, "end_seconds": end},
        })

    for item in actual:
        shot_id = str(item.get("id") or item.get("shot_id") or "")
        if not shot_id or shot_id in planned_ids:
            continue
        start, end = _interval(item)
        if _overlaps(start, end, window_start, window_end):
            trace_shots.append({
                "shot_id": shot_id,
                "status": "added",
                "status_label": STATUS_LABELS["added"],
                "planned_basis": None,
                "actual_execution": _actual_execution(item),
                "deviation": {"reason": "样片中出现了锁定方案之外的镜头"},
                "sample_window": {"included": True, "start_seconds": start, "end_seconds": end},
            })

    counts = {status: sum(item["status"] == status for item in trace_shots) for status in STATUS_LABELS}
    inputs = {
        name: _stable_hash(artifacts.get(name))
        for name in ("reference_fingerprint", "creative_control_plan", "script", "shot_execution_plan", "final_props", "render_plan", "sample_report")
        if artifacts.get(name) is not None
    }
    payload = {"project_id": project_id, "plan_version": plan.get("plan_version"), "window": [window_start, window_end], "shots": trace_shots}
    return {
        "version": "1.0",
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_hashes": inputs,
        "semantic_sha256": _stable_hash(payload),
        "summary": {
            "planned_shot_count": len(planned),
            "included_shot_count": sum(1 for item in trace_shots if item["sample_window"]["included"]),
            "status_counts": counts,
            "new_content_count": counts["added"],
        },
        "shots": trace_shots,
    }


def write_sample_execution_trace(
    project_dir: str,
    artifacts: Mapping[str, Any],
    *,
    sink: Any = None,
) -> dict[str, Any]:
    """Build and atomically persist the trace as a canonical project artifact."""
    from lib.artifact_io import write_artifact_atomic

    project_id = str(artifacts.get("project_id") or project_dir.rstrip("/").split("/")[-1])
    trace = build_sample_execution_trace(project_id, artifacts)
    write_artifact_atomic(
        "artifacts/sample_execution_trace.json",
        "sample_execution_trace",
        trace,
        project_dir=project_dir,
        sink=sink,
    )
    return trace

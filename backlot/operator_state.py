"""Business-safe, Chinese projection of Backlot's read-only BoardState."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

import jsonschema

from backlot.operator_language import (
    LEGACY_STAGE_LABELS,
    PLATFORM_LABELS,
    PUBLISH_STATUS_LABELS,
    STAGE_LABELS,
    STATUS_LABELS,
)
from backlot.state import load_board_state


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "backlot"
    / "operator_state.schema.json"
)

EDITOR_BY_STAGE = {
    "research": "research_review",
    "proposal": "proposal_choice",
    "idea": "proposal_choice",
    "script": "script_editor",
    "scene_plan": "shot_mapping",
    "assets": "asset_review",
    "sample": "sample_review",
    "edit": "edit_review",
    "compose": "delivery_review",
    "publish": "delivery_review",
}

ROUTE_LABELS = {
    "no_render": "无需重新生成视频",
    "mux_only": "保留画面，仅更新声音",
    "full_render": "重新生成完整画面",
    "sample": "生成样片",
    "full": "生成完整视频",
}

ASSET_TYPE_LABELS = {
    "video_proxy": "源素材代理",
    "narration": "口播",
    "subtitles": "字幕",
    "music": "背景音乐",
    "composition": "合成工程",
    "sample_render": "样片",
    "cost_contingency": "费用预留",
}

ASSET_STAGE_LABELS = {
    "assets": "制作准备阶段",
    "sample": "样片阶段",
    "edit": "精剪阶段",
    "compose": "成片阶段",
}

RESEARCH_CHECK_LABELS = {
    "input_coverage": "输入素材检查",
    "evidence_traceability": "结论依据",
    "source_matching": "素材匹配",
    "production_readiness": "制作可行性",
    "execution_discipline": "执行完整性",
}

_ABSOLUTE_PATH = re.compile(r"^(?:/|[A-Za-z]:[\\/])")


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_operator_state(value: Mapping[str, Any]) -> None:
    """Validate the public operator projection before it reaches the API."""
    jsonschema.validate(dict(value), _schema())


def _safe_text(value: Any, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if not text:
        return fallback
    if _ABSOLUTE_PATH.match(text) or "/Users/" in text or "/private/" in text:
        return Path(text).stem
    return text.replace(".json", "")


def _research_check_message(value: Any) -> str:
    message = _safe_text(value)
    if message.casefold() in {"confirmed", "ok", "pass", "passed"}:
        return "已检查，未发现问题"
    return message


def _number(value: Any) -> float | int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _media_url(project_id: str, relative_path: Any) -> str | None:
    if not isinstance(relative_path, str) or not relative_path or _ABSOLUTE_PATH.match(relative_path):
        return None
    raw_parts = [part for part in relative_path.replace("\\", "/").split("/") if part not in {"", "."}]
    if ".." in raw_parts:
        return None
    prefix = ["projects", project_id]
    parts = raw_parts[len(prefix):] if raw_parts[:len(prefix)] == prefix else raw_parts
    if not parts:
        return None
    encoded_path = "/".join(quote(part, safe="") for part in parts)
    return f"/media/{quote(project_id, safe='')}/{encoded_path}"


def _project_relative_path(project_id: str, value: Any) -> str:
    """Normalize a project-local artifact path without exposing host paths."""
    if not isinstance(value, str):
        return ""
    text = value.strip().replace("\\", "/")
    if not text or _ABSOLUTE_PATH.match(text):
        return ""
    prefix = f"projects/{project_id}/"
    if text.startswith(prefix):
        text = text[len(prefix):]
    parts = [part for part in text.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        return ""
    return "/".join(parts)


def _delivery_file_kind(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".srt", ".vtt", ".ass"}:
        return "subtitle"
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return "thumbnail"
    if suffix in {".txt", ".json", ".csv"}:
        return "metadata"
    return "other"


def _delivery_url(project_id: str, relative_path: str) -> str | None:
    normalized = f"/{relative_path.strip('/').lower()}/"
    if "/inputs/reference/" in normalized:
        return None
    return _media_url(project_id, relative_path)


def _delivery_package_files(
    board: Mapping[str, Any], project_id: str, package_path: str,
) -> list[dict[str, Any]]:
    """List files in a publish package, constrained to the project directory."""
    if not package_path:
        return []
    project_dir = board.get("_project_dir")
    if not isinstance(project_dir, Path):
        return [{
            "relative_path": package_path,
            "label": Path(package_path).name,
            "kind": _delivery_file_kind(package_path),
            "download_url": None,
        }]
    root = project_dir.resolve()
    target = (root / package_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return []
    if target.is_file():
        candidates = [target]
    elif target.is_dir():
        candidates = sorted(path for path in target.rglob("*") if path.is_file())
    else:
        candidates = []
    files = []
    for path in candidates[:200]:
        relative = path.relative_to(root).as_posix()
        files.append({
            "relative_path": relative,
            "label": path.name,
            "kind": _delivery_file_kind(relative),
            "download_url": _delivery_url(project_id, relative),
            "size_bytes": path.stat().st_size,
        })
    return files


def _thumb_url(
    project_id: str, relative_path: Any, *, width: int = 640, time_seconds: float | int | None = None,
) -> str | None:
    media_url = _media_url(project_id, relative_path)
    if media_url is None:
        return None
    url = media_url.replace("/media/", "/thumb/", 1) + f"?w={width}"
    if time_seconds is not None:
        url += f"&t={float(time_seconds):g}"
    return url


def _artifact(board: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = (board.get("artifacts") or {}).get(name)
    if not isinstance(value, Mapping):
        return {}
    data = value.get("data")
    if value.get("name") == name and isinstance(data, Mapping):
        return data
    return value


def _owned_media_path(value: Any) -> str:
    """Normalize project-prefixed owned media paths for catalog lookups."""
    if not isinstance(value, str):
        return ""
    parts = [part for part in value.replace("\\", "/").split("/") if part]
    try:
        start = parts.index("inputs")
    except ValueError:
        return "/".join(parts)
    return "/".join(parts[start:])


_CONTROL_SECTION_LABELS = {
    "content_direction": "内容方向",
    "story_pacing": "故事和节奏",
    "visual_rules": "视觉规则",
    "fact_continuity": "事实和连续性",
    "originality_boundary": "原创边界",
}
_CONTROL_RULE_REF = re.compile(r"^(?P<section>[a-z_]+)\.rules\[(?P<index>\d+)\]$")


def _director_rules_for_display(
    control_plan: Mapping[str, Any], refs: Any,
) -> list[str]:
    """Resolve internal control-plan pointers into operator-facing instructions."""
    raw_sections = control_plan.get("sections")
    sections = raw_sections if isinstance(raw_sections, Mapping) else {}
    rules: list[str] = []
    for ref in refs if isinstance(refs, list) else []:
        match = _CONTROL_RULE_REF.match(ref) if isinstance(ref, str) else None
        if match is None:
            continue
        section_id = match.group("section")
        section = sections.get(section_id)
        section_rules = section.get("rules") if isinstance(section, Mapping) else []
        index = int(match.group("index"))
        if not isinstance(section_rules, list) or index >= len(section_rules):
            continue
        rule = _safe_text(section_rules[index])
        if rule:
            rules.append(f"{_CONTROL_SECTION_LABELS.get(section_id, '导演总控单')}：{rule}")
    return rules


def _generation_tasks_for_operator(project_dir: Path, project_id: str) -> list[dict[str, Any]]:
    tasks = []
    directory = project_dir / "operator" / "shot-generation" / "tasks"
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(task, Mapping) or not isinstance(task.get("task_id"), str):
            continue
        output = task.get("output_path")
        tasks.append({
            "task_id": task["task_id"],
            "shot_id": _safe_text(task.get("shot_id")),
            "proposal_id": _safe_text(task.get("proposal_id")),
            "quality": _safe_text(task.get("quality")),
            "status": _safe_text(task.get("status")),
            "seed": task.get("seed") if isinstance(task.get("seed"), int) else None,
            "output_url": _media_url(project_id, output),
            "actual_cost_usd": _number(task.get("actual_cost_usd")),
            "error": _safe_text(task.get("error")),
        })
    return tasks


def _research_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    research = _artifact(board, "research_brief")
    analysis = _artifact(board, "video_analysis_brief")
    fingerprint = _artifact(board, "reference_fingerprint")
    source = _artifact(board, "source_media_review")
    breakdown = _artifact(board, "research_breakdown")
    matrix = _artifact(board, "reference_source_matrix")
    synthesis = _artifact(board, "research_synthesis")
    scorecard = _artifact(board, "research_scorecard")
    annotations = _artifact(board, "research_annotations")
    files = source.get("files") if isinstance(source.get("files"), list) else []
    risks: list[str] = []
    sources: list[dict[str, Any]] = []
    usable = 0
    project_id = str(board.get("project_id") or "project")
    for item in files:
        if not isinstance(item, Mapping):
            continue
        if item.get("usable_for"):
            usable += 1
        for risk in item.get("quality_risks") or []:
            safe = _safe_text(risk)
            if safe:
                risks.append(safe)
        probe = item.get("technical_probe") if isinstance(item.get("technical_probe"), Mapping) else {}
        ranges = item.get("best_ranges") if isinstance(item.get("best_ranges"), list) else []
        best = next((value for value in ranges if isinstance(value, Mapping)), {})
        best_in = _number(best.get("start_seconds"))
        best_out = _number(best.get("end_seconds"))
        frames = item.get("representative_frames") if isinstance(item.get("representative_frames"), list) else []
        frame = next((value for value in frames if isinstance(value, str)), None)
        path = item.get("path")
        media_type = _safe_text(item.get("media_type"), "unknown")
        # 素材名优先用原始文件名（业务可读），media_id 哈希只留在 id/制作记录。
        label = Path(path).stem if isinstance(path, str) and path else ""
        if not label:
            label = _safe_text(item.get("media_id"))
        item_risks = [_safe_text(value) for value in item.get("quality_risks") or []]
        sources.append({
            "id": _safe_text(item.get("media_id"), f"source-{len(sources) + 1}"),
            "label": label or f"素材 {len(sources) + 1}",
            "media_type": media_type,
            "summary": _safe_text(item.get("content_summary")),
            "reviewed": item.get("reviewed") is True,
            "usable_for": [_safe_text(value) for value in item.get("usable_for") or [] if _safe_text(value)],
            "risks": [value for value in item_risks if value],
            "duration_seconds": _number(probe.get("duration_seconds")),
            "resolution": _safe_text(probe.get("resolution")),
            "fps": _number(probe.get("fps")),
            "best_in_seconds": best_in,
            "best_out_seconds": best_out,
            "preview_url": _media_url(project_id, path),
            "poster_url": (
                _thumb_url(project_id, frame) if frame else
                _thumb_url(project_id, path) if media_type == "image" else
                _thumb_url(
                    project_id, path,
                    time_seconds=(float(best_in) + float(best_out)) / 2
                    if best_in is not None and best_out is not None else 1.5,
                ) if media_type == "video" else None
            ),
        })
    content = analysis.get("content_analysis") if isinstance(analysis.get("content_analysis"), Mapping) else {}
    structure = analysis.get("structure_analysis") if isinstance(analysis.get("structure_analysis"), Mapping) else {}
    style = analysis.get("style_profile") if isinstance(analysis.get("style_profile"), Mapping) else {}
    guidance = analysis.get("replication_guidance") if isinstance(analysis.get("replication_guidance"), Mapping) else {}
    reference_source = analysis.get("source") if isinstance(analysis.get("source"), Mapping) else {}
    abstract = fingerprint.get("abstract_structure") if isinstance(fingerprint.get("abstract_structure"), Mapping) else {}
    keyframes = analysis.get("keyframes") if isinstance(analysis.get("keyframes"), list) else []
    frame_by_scene = {}
    for frame in keyframes:
        if isinstance(frame, Mapping) and isinstance(frame.get("scene_index"), int):
            frame_by_scene.setdefault(frame["scene_index"], frame.get("path"))
    reference_scenes = []
    for index, scene in enumerate(structure.get("scenes") or []):
        if not isinstance(scene, Mapping):
            continue
        scene_index = scene.get("scene_index") if isinstance(scene.get("scene_index"), int) else index
        reference_scenes.append({
            "id": f"reference-{scene_index + 1}",
            "description": _safe_text(scene.get("description")),
            "screen_copy": _safe_text(scene.get("on_screen_text")),
            "energy": _safe_text(scene.get("energy_level")),
            "start_seconds": _number(scene.get("start_time")) or 0,
            "end_seconds": _number(scene.get("end_time")) or 0,
            "poster_url": _thumb_url(project_id, frame_by_scene.get(scene_index)),
        })
    summary = (
        _safe_text(content.get("summary"))
        or _safe_text(research.get("research_summary"))
        or _safe_text(research.get("summary"))
    )
    if not summary:
        summary = _safe_text(research.get("topic"), "该步骤暂无结构化内容")
    risks = list(dict.fromkeys(risks))
    reference_path = reference_source.get("local_path")
    first_frame = next((value for value in frame_by_scene.values() if isinstance(value, str)), None)
    has_reference = bool(reference_path or reference_scenes or fingerprint or analysis)
    profile_ref = breakdown.get("profile_ref") if isinstance(breakdown.get("profile_ref"), Mapping) else {}
    coverage = breakdown.get("coverage_summary") if isinstance(breakdown.get("coverage_summary"), Mapping) else {}
    breakdown_rows = []
    for origin, values in (
        ("参考片", breakdown.get("reference_shots")),
        ("我的素材", breakdown.get("source_segments")),
    ):
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, Mapping):
                continue
            interval = item.get("interval") if isinstance(item.get("interval"), Mapping) else {}
            observations = item.get("values") if isinstance(item.get("values"), Mapping) else {}
            breakdown_rows.append({
                "id": _safe_text(item.get("row_id"), f"breakdown-{len(breakdown_rows) + 1}"),
                "origin": origin,
                "media_id": _safe_text(item.get("media_id")),
                "start_seconds": _number(interval.get("start_seconds")) or 0,
                "end_seconds": _number(interval.get("end_seconds_exclusive")) or 0,
                "shot_size": _safe_text(observations.get("shot_size")),
                "camera_movement": _safe_text(observations.get("camera_movement")),
                "camera_angle": _safe_text(observations.get("camera_angle")),
                "visual_content": _safe_text(observations.get("visual_content")),
                "dialogue": _safe_text(observations.get("dialogue")),
                "overlay_text": _safe_text(observations.get("overlay_text")),
                "effect_treatment": _safe_text(observations.get("effect_treatment")),
                "analyst_note": _safe_text(observations.get("analyst_note")),
                "evidence_frames": [
                    _safe_text(frame) for frame in observations.get("evidence_frames") or []
                    if _safe_text(frame)
                ],
                "setting": _safe_text(observations.get("setting")),
                "audio_layers": [
                    _safe_text(layer) for layer in observations.get("audio_layers") or []
                    if _safe_text(layer)
                ],
                "music_profile": _safe_text(observations.get("music_profile")),
                "needs_review": bool(item.get("warnings")) or item.get("observation_source") == "missing",
            })
    matrix_rows = []
    for item in matrix.get("rows") if isinstance(matrix.get("rows"), list) else []:
        if not isinstance(item, Mapping):
            continue
        confidence = _number(item.get("confidence"))
        resolution = _safe_text(item.get("resolution"), "pending")
        matrix_rows.append({
            "id": _safe_text(item.get("matrix_row_id"), f"matrix-{len(matrix_rows) + 1}"),
            "label": "参考镜头 × 我的素材",
            "reference_intent": _safe_text(item.get("reference_intent")),
            "source_media_id": _safe_text(item.get("source_media_id")),
            "match_reason": _safe_text(item.get("match_reason")),
            "confidence": confidence,
            "status": {
                "pending": "需要确认", "accept": "采用这段", "replace_source": "换一段",
                "bridge": "需要补拍或补素材", "rewrite": "改成别的表达", "omit": "删除这一镜",
            }.get(resolution, "需要确认"),
            "gap": _safe_text(item.get("unmatched_gap")),
        })
    directions = []
    for item in synthesis.get("differentiation_directions") if isinstance(synthesis.get("differentiation_directions"), list) else []:
        if not isinstance(item, Mapping):
            continue
        directions.append({
            "id": _safe_text(item.get("direction_id"), f"direction-{len(directions) + 1}"),
            "title": _safe_text(item.get("title"), "可选方向"),
            "promise": _safe_text(item.get("promise")),
            "keep": [_safe_text(value) for value in item.get("keep_from_reference") or [] if _safe_text(value)],
            "change": [_safe_text(value) for value in item.get("change_for_project") or [] if _safe_text(value)],
            "avoid": [_safe_text(value) for value in item.get("avoid") or [] if _safe_text(value)],
            "tradeoffs": [_safe_text(value) for value in item.get("tradeoffs") or [] if _safe_text(value)],
        })
    matrix_decisions = annotations.get("matrix_resolutions") if isinstance(annotations.get("matrix_resolutions"), Mapping) else {}
    direction_decisions = annotations.get("direction_preferences") if isinstance(annotations.get("direction_preferences"), Mapping) else {}
    decision_inbox = []
    for row in matrix_rows:
        is_blocking_gap = row["status"] in {"需要补拍或补素材", "改成别的表达", "删除这一镜"} and bool(row["gap"])
        if is_blocking_gap and row["id"] not in matrix_decisions:
            decision_inbox.append({
                "id": f"matrix-{row['id']}", "kind": "material_gap", "title": row["reference_intent"] or "这个卖点怎么处理",
                "message": row["gap"],
                "impact": "会影响这一镜的素材选择、卖点表达，以及后续脚本和分镜",
                "matrix_row_id": row["id"], "source_media_id": row["source_media_id"] or None,
                "choices": ["需要补拍或补素材", "改成别的表达", "删除这一镜"],
            })
    if directions and not any(
        isinstance(value, Mapping) and value.get("preference") == "prefer"
        for value in direction_decisions.values()
    ):
        decision_inbox.append({
            "id": "direction", "kind": "direction", "title": "这条片准备怎么做",
            "message": "请先选定一个可选方向，创意方案会据此确定开头、卖点顺序和原创表达。",
            "impact": "会影响创意方案的范围、参考机制取舍和原创边界",
            "matrix_row_id": None, "source_media_id": None,
            "choices": ["保留这个方向", "暂不采用"],
        })
    quality_checks = []
    for item in scorecard.get("checks") if isinstance(scorecard.get("checks"), list) else []:
        if isinstance(item, Mapping):
            check_id = _safe_text(item.get("id"))
            quality_checks.append({
                "label": RESEARCH_CHECK_LABELS.get(
                    check_id, _safe_text(item.get("label"), check_id)
                ),
                "status": {"pass": "已确认", "review": "需要确认", "fail": "需要处理"}.get(_safe_text(item.get("status")), "需要确认"),
                "message": _research_check_message(item.get("message")),
            })
    substage_state = lambda has_content: "completed" if has_content else "pending"
    substages = [
        {
            "id": "reference", "label": "参考片怎么拍",
            "state": substage_state(has_reference) if has_reference else "not_needed",
            "message": "已拆出参考片的拍法、节奏和可借鉴机制" if has_reference else "本项目没有参考片，这一步不需要处理",
        },
        {
            "id": "sources", "label": "我的素材能不能接上",
            "state": substage_state(bool(files or breakdown_rows)),
            "message": "已检查自有素材可用区间和证明能力" if files or breakdown_rows else "正在等待素材体检结果",
        },
        {
            "id": "matching", "label": "参考镜头和我的素材怎么对应",
            "state": substage_state(bool(matrix_rows)),
            "message": "已给出每个需要保留、改写或补足的镜头处理" if matrix_rows else "暂时没有需要逐镜头匹配的内容",
        },
        {
            "id": "direction", "label": "这条片准备怎么做",
            "state": substage_state(bool(directions)),
            "message": "已整理可采用的表达方向和不要照搬的部分" if directions else "正在整理适合本项目的表达方向",
        },
        {
            "id": "quality", "label": "还有什么没看清",
            "state": "awaiting_human" if decision_inbox else substage_state(bool(scorecard)),
            "message": f"还有 {len(decision_inbox)} 项需要你确认" if decision_inbox else (
                "已检查关键卖点、素材和下一步制作条件" if scorecard else "正在汇总需要确认的风险"
            ),
        },
    ]
    selected_direction_ids = [
        direction_id for direction_id, value in direction_decisions.items()
        if isinstance(value, Mapping) and value.get("preference") == "prefer"
    ]
    scorecard_passed = _safe_text(scorecard.get("status")) == "pass"
    proposal_handoff = {
        "state": "ready" if scorecard_passed and not decision_inbox else ("needs_decision" if decision_inbox else "checking"),
        "message": (
            "研究检查已通过，可以进入创意方案"
            if scorecard_passed and not decision_inbox
            else (f"还有 {len(decision_inbox)} 项需要你确认，确认后即可进入创意方案" if decision_inbox else "研究检查完成后即可进入创意方案")
        ),
        "selected_direction_ids": selected_direction_ids,
        "resolved_matrix_row_ids": sorted(matrix_decisions),
    }
    return {
        "type": "research_review",
        "data": {
            "reference_summary": summary,
            "source_count": len(files),
            "usable_count": usable,
            "substages": substages,
            "decision_inbox": decision_inbox,
            "proposal_handoff": proposal_handoff,
            "risks": risks,
            "sources": sources,
            "template": {
                "label": "电商产品证明分镜模板",
                "version": _safe_text(profile_ref.get("version"), "1.0"),
                "status": "已启用" if profile_ref else "等待拆解",
            },
            "breakdown": {
                "label": "分镜拆解",
                "identified": int(coverage.get("identified") or 0),
                "needs_review": int(coverage.get("needs_review") or 0),
                "missing": int(coverage.get("missing") or 0),
                "rows": breakdown_rows,
            },
            "matching": {"label": "参考镜头 × 我的素材", "rows": matrix_rows},
            "directions": directions,
            "quality": {
                "label": "研究检查结果",
                "score": _number(scorecard.get("score")),
                "max_score": _number(scorecard.get("max_score")),
                "status": {"pass": "可以进入方案", "review": "需要确认", "fail": "需要处理"}.get(_safe_text(scorecard.get("status")), "等待检查"),
                "checks": quality_checks,
                "warnings": [_safe_text(value) for value in scorecard.get("warnings") or [] if _safe_text(value)],
            },
            "reference": {
                "title": _safe_text(reference_source.get("title"), "参考视频"),
                "summary": summary,
                "duration_seconds": _number(reference_source.get("duration_seconds")),
                "hook": _safe_text(content.get("hook_technique")),
                "beat_order": [_safe_text(value) for value in abstract.get("beat_order") or [] if _safe_text(value)],
                "proof_method": _safe_text(abstract.get("proof_method")),
                "avg_evidence_seconds": _number(abstract.get("avg_evidence_unit_seconds")),
                "camera_method": _safe_text(abstract.get("camera_method")),
                "caption_method": _safe_text(abstract.get("caption_method")),
                "typography": _safe_text(style.get("typography_observed")),
                "transitions": [_safe_text(value) for value in style.get("transition_types") or [] if _safe_text(value)],
                "replicate": [_safe_text(value) for value in guidance.get("key_elements_to_replicate") or [] if _safe_text(value)],
                "differentiate": [_safe_text(value) for value in guidance.get("creative_differentiation_seeds") or [] if _safe_text(value)],
                "preview_url": _media_url(project_id, reference_path),
                "poster_url": _thumb_url(project_id, first_frame or reference_path, time_seconds=None if first_frame else 1.5),
                "scenes": reference_scenes,
                "fingerprint_version": _safe_text(fingerprint.get("version"), "1.0"),
                "fingerprint_upgrade_notice": (
                    "这条参考片还在旧版拆解格式，当前页面先显示已有结论；重新研究后可补齐拍法、节奏和一致性检查"
                    if _safe_text(fingerprint.get("version"), "1.0") != "2.0"
                    else ""
                ),
            },
        },
    }


def _proposal_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    proposal = _artifact(board, "proposal_packet")
    options = proposal.get("concept_options") if isinstance(proposal.get("concept_options"), list) else []
    concepts = []
    for index, option in enumerate(options):
        if not isinstance(option, Mapping):
            continue
        concepts.append({
            "id": _safe_text(option.get("id"), f"concept-{index + 1}"),
            "title": _safe_text(option.get("title")),
            "hook": _safe_text(option.get("hook")),
            "duration_seconds": _number(option.get("target_duration_seconds")),
            "core_message": _safe_text(option.get("core_message")),
            "target_audience": _safe_text(option.get("target_audience")),
            "tone": _safe_text(option.get("tone")),
            "visual_approach": _safe_text(option.get("visual_approach")),
            "why_this_works": _safe_text(option.get("why_this_works")),
            "key_points": [
                _safe_text(value) for value in option.get("key_points") or [] if _safe_text(value)
            ],
            "cta": _safe_text(option.get("cta")),
            "narrative_structure": _safe_text(option.get("narrative_structure")),
            "target_platform": _safe_text(option.get("target_platform")),
        })
    selected = proposal.get("selected_concept")
    selected_id = _safe_text(selected.get("concept_id")) if isinstance(selected, Mapping) else ""
    raw_plan = proposal.get("creative_control_plan")
    if not isinstance(raw_plan, Mapping):
        candidate_plan = _artifact(board, "creative_control_plan")
        raw_plan = candidate_plan if isinstance(candidate_plan, Mapping) and candidate_plan.get("sections") else None
    control_plan = None
    if isinstance(raw_plan, Mapping):
        labels = {
            "content_direction": "内容方向",
            "story_pacing": "故事和节奏",
            "visual_rules": "视觉规则",
            "fact_continuity": "事实和连续性",
            "originality_boundary": "原创边界",
        }
        sections = []
        raw_sections = raw_plan.get("sections") if isinstance(raw_plan.get("sections"), Mapping) else {}
        reviews = raw_plan.get("section_reviews") if isinstance(raw_plan.get("section_reviews"), Mapping) else {}
        feedback = raw_plan.get("feedback") if isinstance(raw_plan.get("feedback"), Mapping) else {}
        for section_id, label in labels.items():
            section = raw_sections.get(section_id) if isinstance(raw_sections.get(section_id), Mapping) else {}
            sections.append({
                "id": section_id, "label": label,
                "summary": _safe_text(section.get("summary")),
                "rules": [_safe_text(item) for item in section.get("rules") or [] if _safe_text(item)],
                "evidence_refs": [_safe_text(item) for item in section.get("evidence_refs") or [] if _safe_text(item)],
                "industry_notes": [_safe_text(item) for item in section.get("industry_notes") or [] if _safe_text(item)],
                "review": _safe_text(reviews.get(section_id), "pending"),
                "feedback": _safe_text(feedback.get(section_id)),
            })
        control_plan = {
            "plan_id": _safe_text(raw_plan.get("plan_id")),
            "plan_version": int(raw_plan.get("plan_version") or 1),
            "status": _safe_text(raw_plan.get("status"), "draft"),
            "selected_direction_id": _safe_text(raw_plan.get("selected_direction_id"), selected_id),
            "sections": sections,
        }
    return {
        "type": "proposal_choice",
        "data": {
            "concepts": concepts,
            "selected_id": selected_id or None,
            "estimated_cost_usd": _number((proposal.get("cost_estimate") or {}).get("total_estimated_usd")),
            "control_plan": control_plan,
        },
    }


def _script_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    script = _artifact(board, "script")
    control_plan = _artifact(board, "creative_control_plan")
    raw_sections = script.get("sections") if isinstance(script.get("sections"), list) else []
    sections = []
    for index, section in enumerate(raw_sections):
        if not isinstance(section, Mapping):
            continue
        sections.append({
            "id": _safe_text(section.get("id"), f"section-{index + 1}"),
            "label": _safe_text(section.get("label"), "内容"),
            "text": _safe_text(section.get("narration")) or _safe_text(section.get("text")),
            "screen_copy": _safe_text(section.get("screen_copy")),
            "start_seconds": _number(section.get("start_seconds")) or 0,
            "end_seconds": _number(section.get("end_seconds")) or 0,
            "section_goal": _safe_text(section.get("section_goal")),
            "pacing": _safe_text(section.get("pacing")),
            "visual_intent": _safe_text(section.get("visual_intent")),
            "evidence_requirements": [
                _safe_text(value) for value in section.get("evidence_requirements") or []
                if _safe_text(value)
            ],
            "control_rule_refs": [
                _safe_text(value) for value in section.get("control_rule_refs") or []
                if _safe_text(value)
            ],
            "director_rules": _director_rules_for_display(
                control_plan, section.get("control_rule_refs")
            ),
            "review": _safe_text(section.get("review"), "pending"),
            "feedback": _safe_text(section.get("feedback")),
        })
    return {
        "type": "script_editor",
        "data": {
            "script_id": _safe_text(script.get("script_id")),
            "script_version": int(script.get("script_version") or 1),
            "status": _safe_text(script.get("status"), "draft"),
            "duration_seconds": _number(script.get("total_duration_seconds")),
            "sections": sections,
        },
    }


def _source_label(scene: Mapping[str, Any]) -> str:
    for asset in scene.get("required_assets") or []:
        if not isinstance(asset, Mapping):
            continue
        raw = asset.get("path") or asset.get("description")
        if isinstance(raw, str) and raw:
            if _ABSOLUTE_PATH.match(raw) or "/" in raw or "\\" in raw:
                return Path(raw).stem
            return _safe_text(raw)
    return ""


def _shot_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    scene_plan = _artifact(board, "scene_plan")
    source_review = _artifact(board, "source_media_review")
    fingerprint = _artifact(board, "reference_fingerprint")
    analysis = _artifact(board, "video_analysis_brief")
    raw_scenes = scene_plan.get("scenes") if isinstance(scene_plan.get("scenes"), list) else []
    shots = []
    project_id = str(board.get("project_id") or "project")
    metadata = scene_plan.get("metadata") if isinstance(scene_plan.get("metadata"), Mapping) else {}
    mappings = metadata.get("source_mapping") if isinstance(metadata.get("source_mapping"), list) else []
    mapping_by_scene = {
        value.get("scene_id"): value for value in mappings
        if isinstance(value, Mapping) and isinstance(value.get("scene_id"), str)
    }
    source_by_path = {
        str(value.get("path")).replace("\\", "/"): value
        for value in source_review.get("files") or []
        if isinstance(value, Mapping) and isinstance(value.get("path"), str)
    }
    asset_manifest = _artifact(board, "asset_manifest")
    proxy_by_scene = {
        str(asset.get("scene_id")): str(asset.get("path"))
        for asset in asset_manifest.get("assets") or []
        if isinstance(asset, Mapping)
        and isinstance(asset.get("scene_id"), str)
        and isinstance(asset.get("path"), str)
        and (
            asset.get("source_tool") == "media_proxy"
            or asset.get("subtype") == "source_proxy"
            or str(asset.get("id") or "").startswith("proxy-")
        )
    }
    abstract = fingerprint.get("abstract_structure") if isinstance(fingerprint.get("abstract_structure"), Mapping) else {}
    content = analysis.get("content_analysis") if isinstance(analysis.get("content_analysis"), Mapping) else {}
    structure = analysis.get("structure_analysis") if isinstance(analysis.get("structure_analysis"), Mapping) else {}
    reference_source = analysis.get("source") if isinstance(analysis.get("source"), Mapping) else {}
    reference_path = reference_source.get("local_path")
    keyframes = analysis.get("keyframes") if isinstance(analysis.get("keyframes"), list) else []
    frame_by_scene = {
        frame["scene_index"]: frame.get("path")
        for frame in keyframes
        if isinstance(frame, Mapping) and isinstance(frame.get("scene_index"), int)
    }
    reference_scene_by_id = {}
    for reference_index, reference_scene in enumerate(structure.get("scenes") or []):
        if not isinstance(reference_scene, Mapping):
            continue
        scene_index = (
            reference_scene.get("scene_index")
            if isinstance(reference_scene.get("scene_index"), int)
            else reference_index
        )
        reference_scene_by_id[f"reference-{scene_index + 1}"] = {
            "description": _safe_text(reference_scene.get("description")),
            "start_seconds": _number(reference_scene.get("start_time")),
            "end_seconds": _number(reference_scene.get("end_time")),
            "poster_path": frame_by_scene.get(scene_index),
        }
    reference_basis = {
        "summary": _safe_text(content.get("summary")),
        "beat_order": [_safe_text(value) for value in abstract.get("beat_order") or [] if _safe_text(value)],
        "proof_method": _safe_text(abstract.get("proof_method")),
        "avg_evidence_seconds": _number(abstract.get("avg_evidence_unit_seconds")),
    }
    for index, scene in enumerate(raw_scenes):
        if not isinstance(scene, Mapping):
            continue
        mapping = mapping_by_scene.get(scene.get("id"), {})
        source_interval = mapping.get("source_interval") if isinstance(mapping.get("source_interval"), Mapping) else {}
        timeline_interval = mapping.get("timeline_interval") if isinstance(mapping.get("timeline_interval"), Mapping) else {}
        source_in = _number(source_interval.get("start_seconds"))
        source_out = _number(source_interval.get("end_seconds_exclusive"))
        timeline_in = _number(timeline_interval.get("start_seconds"))
        timeline_out = _number(timeline_interval.get("end_seconds_exclusive"))
        source_path = mapping.get("source_path")
        source_preview_path = proxy_by_scene.get(str(scene.get("id") or "")) or source_path
        source_item = source_by_path.get(str(source_path).replace("\\", "/"), {})
        source_summary = _safe_text(source_item.get("content_summary"))
        source_usable_for = [
            _safe_text(value) for value in source_item.get("usable_for") or [] if _safe_text(value)
        ]
        overlays = scene.get("overlay_layers") if isinstance(scene.get("overlay_layers"), list) else []
        overlay = next((value for value in overlays if isinstance(value, Mapping)), {})
        intent = _safe_text(scene.get("shot_intent"))
        raw_reference = mapping.get("reference_evidence") if isinstance(mapping.get("reference_evidence"), Mapping) else {}
        reference_mode = _safe_text(raw_reference.get("mode"))
        reference_scene_id = _safe_text(raw_reference.get("reference_scene_id"))
        reference_scene = reference_scene_by_id.get(reference_scene_id, {})
        reference_interval = (
            raw_reference.get("reference_interval")
            if isinstance(raw_reference.get("reference_interval"), Mapping)
            else {}
        )
        reference_in = _number(reference_interval.get("start_seconds"))
        reference_out = _number(reference_interval.get("end_seconds_exclusive"))
        direct_reference = (
            reference_mode == "direct_segment"
            and reference_scene
            and reference_in is not None
            and reference_out is not None
            and reference_out > reference_in
            and isinstance(reference_path, str)
        )
        if direct_reference:
            projected_reference_mode = "direct_segment"
        elif reference_mode == "none" and not reference_basis["proof_method"]:
            projected_reference_mode = "none"
        elif reference_basis["proof_method"] or _safe_text(raw_reference.get("mechanism")):
            projected_reference_mode = "structural_only"
        else:
            projected_reference_mode = "none"
        reference_evidence = {
            "mode": projected_reference_mode,
            "reference_scene_id": reference_scene_id if direct_reference else "",
            "description": _safe_text(reference_scene.get("description")) if direct_reference else "",
            "mechanism": (
                _safe_text(raw_reference.get("mechanism"))
                or reference_basis["proof_method"]
            ),
            "rationale": (
                _safe_text(raw_reference.get("rationale"))
                or (
                    "沿用参考视频的整体结构机制，未建立直接片段对应"
                    if projected_reference_mode == "structural_only" else ""
                )
            ),
            "start_seconds": reference_in if direct_reference else None,
            "end_seconds": reference_out if direct_reference else None,
            "preview_url": _media_url(project_id, reference_path) if direct_reference else None,
            "poster_url": (
                _thumb_url(
                    project_id,
                    reference_scene.get("poster_path") or reference_path,
                    time_seconds=None if reference_scene.get("poster_path") else (reference_in + reference_out) / 2,
                )
                if direct_reference else None
            ),
        }
        reason_parts = []
        if reference_basis["proof_method"]:
            reason_parts.append(f"参考机制要求“{reference_basis['proof_method']}”")
        if source_summary:
            reason_parts.append(f"自有素材呈现“{source_summary}”")
        if source_usable_for:
            reason_parts.append(f"可承担{'、'.join(source_usable_for)}")
        if intent:
            reason_parts.append(f"用于完成镜头意图“{intent}”")
        shots.append({
            "id": _safe_text(scene.get("id"), f"shot-{index + 1}"),
            "beat": _safe_text(scene.get("description")),
            "screen_copy": _safe_text(overlay.get("text")) or _safe_text(scene.get("overlay_notes")),
            "source_label": Path(source_path).stem if isinstance(source_path, str) else _source_label(scene),
            "in_seconds": timeline_in if timeline_in is not None else (_number(scene.get("start_seconds")) or 0),
            "out_seconds": timeline_out if timeline_out is not None else (_number(scene.get("end_seconds")) or 0),
            "timeline_in_seconds": timeline_in if timeline_in is not None else (_number(scene.get("start_seconds")) or 0),
            "timeline_out_seconds": timeline_out if timeline_out is not None else (_number(scene.get("end_seconds")) or 0),
            "source_in_seconds": source_in,
            "source_out_seconds": source_out,
            "preview_url": _media_url(project_id, source_preview_path),
            "poster_url": _thumb_url(
                project_id, source_preview_path,
                time_seconds=(float(source_in) + float(source_out)) / 2
                if source_in is not None and source_out is not None else None,
            ),
            "intent": intent,
            "framing": _safe_text(scene.get("framing")),
            "movement": _safe_text(scene.get("movement")),
            "narrative_role": _safe_text(scene.get("narrative_role")),
            "source_summary": source_summary,
            "source_usable_for": source_usable_for,
            "mapping_reason": "；".join(reason_parts) + ("。" if reason_parts else ""),
            "reference_evidence": reference_evidence,
        })
    duration = _number((scene_plan.get("metadata") or {}).get("total_duration_seconds"))
    if duration is None and shots:
        duration = max(shot["out_seconds"] for shot in shots)
    return {
        "type": "shot_mapping",
        "data": {"duration_seconds": duration, "reference_basis": reference_basis, "shots": shots},
    }


def _asset_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = board.get("artifacts") or {}
    plan = _artifact(board, "asset_plan")
    manifest = _artifact(board, "asset_manifest")
    source_review = _artifact(board, "source_media_review")
    source_files = source_review.get("files") if isinstance(source_review.get("files"), list) else []
    source_by_id = {
        str(item.get("media_id")): item
        for item in source_files
        if isinstance(item, Mapping) and item.get("media_id")
    }
    media_index = _artifact(board, "media_index")
    media_by_path = {
        _owned_media_path(item.get("path")): item
        for item in media_index.get("entries") or []
        if isinstance(item, Mapping) and _owned_media_path(item.get("path"))
    }
    planned_assets = plan.get("planned_assets") if isinstance(plan.get("planned_assets"), list) else []
    realized_assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
    realized_ids = {
        str(item.get("id")) for item in realized_assets
        if isinstance(item, Mapping) and item.get("id")
    }
    realized_paths = {
        str(item.get("path") or item.get("output_path")) for item in realized_assets
        if isinstance(item, Mapping) and (item.get("path") or item.get("output_path"))
    }
    paid_approved = bool(plan.get("paid_generation_approved"))
    projected = []
    for item in planned_assets:
        if not isinstance(item, Mapping):
            continue
        asset_id = _safe_text(item.get("id"), "planned-asset")
        output_path = _safe_text(item.get("output_path"))
        prepared = bool(item.get("exists")) or asset_id in realized_ids or output_path in realized_paths
        paid = bool(item.get("paid"))
        source_stage = _safe_text(item.get("source_stage"), "assets")
        if prepared:
            status = "已准备"
            reason = "文件已经生成并登记"
        elif paid and not paid_approved:
            status = "等待确认"
            reason = "付费生成尚未获得批准，不会自动调用模型"
        elif source_stage == "sample":
            status = "后续生成"
            reason = "制作方案已锁定，将在样片阶段生成"
        else:
            status = "待生成"
            reason = "已列入制作清单，尚未执行"
        asset_type = _safe_text(item.get("type"), "asset")
        source_item = source_by_id.get(asset_id.removeprefix("proxy-"), {})
        source_path = source_item.get("path") if isinstance(source_item, Mapping) else None
        source_label = Path(str(source_path)).stem if source_path else ""
        best_ranges = source_item.get("best_ranges") if isinstance(source_item, Mapping) else []
        best_range = best_ranges[0] if best_ranges and isinstance(best_ranges[0], Mapping) else {}
        source_range = (
            f"建议 {float(best_range['start_seconds']):g}-{float(best_range['end_seconds']):g} 秒"
            if best_range.get("start_seconds") is not None and best_range.get("end_seconds") is not None
            else ""
        )
        source_summary = _safe_text(source_item.get("content_summary")) if isinstance(source_item, Mapping) else ""
        quality_risks = source_item.get("quality_risks") if isinstance(source_item, Mapping) else []
        if asset_type == "video_proxy" and quality_risks:
            reason = f"{'; '.join(str(risk) for risk in quality_risks)}；将先生成可剪辑代理。"
        projected.append({
            "id": asset_id,
            "label": f"源素材代理 · {source_label}" if source_label else ASSET_TYPE_LABELS.get(asset_type, "制作素材"),
            "type": asset_type,
            "provider": _safe_text(item.get("provider"), "待确定"),
            "stage_label": ASSET_STAGE_LABELS.get(source_stage, "后续阶段"),
            "status": status,
            "reason": reason,
            "source_summary": source_summary,
            "source_range": source_range,
            "paid": paid,
            "cost_estimate_usd": _number(item.get("cost_estimate_usd")),
        })

    def category_status(asset_type: str, fallback: str) -> str:
        items = [asset for asset in projected if asset["type"] == asset_type]
        if any(item["status"] == "已准备" for item in items):
            return "已准备"
        if any(item["status"] == "等待确认" for item in items):
            return "方案已锁定，等待付费确认"
        if items:
            return "方案已锁定，将在样片阶段生成"
        return fallback

    prepared_count = sum(item["status"] == "已准备" for item in projected)
    waiting_confirmation_count = sum(item["status"] == "等待确认" for item in projected)
    spent = _number((board.get("cost") or {}).get("total_spent_usd"))
    estimated_total = sum(
        float(item.get("cost_estimate_usd") or 0)
        for item in planned_assets
        if isinstance(item, Mapping) and isinstance(item.get("cost_estimate_usd"), (int, float))
    )
    execution = _artifact(board, "shot_execution_plan")
    execution_shots = []
    for index, shot in enumerate(execution.get("shots") or []):
        if not isinstance(shot, Mapping):
            continue
        source = shot.get("source_selection") if isinstance(shot.get("source_selection"), Mapping) else None
        source_in = _number(source.get("start_seconds")) if source else None
        source_out = _number(source.get("end_seconds")) if source else None
        source_media = media_by_path.get(_owned_media_path(source.get("path"))) if source else None
        source_probe = source_media.get("probe") if isinstance(source_media, Mapping) else {}
        source_duration = _number(source_probe.get("duration_seconds")) if isinstance(source_probe, Mapping) else None
        selected_duration = source_out - source_in if source_in is not None and source_out is not None else None
        shot_duration = _number(shot.get("duration_seconds"))
        source_coverage = "等待核对"
        if source_media is not None:
            source_coverage = "需要调整"
        if (
            source_duration is not None
            and source_in is not None
            and source_out is not None
            and source_out > source_in
            and source_out <= source_duration + 0.001
            and shot_duration is not None
            and selected_duration is not None
            and selected_duration + 0.001 >= shot_duration
        ):
            source_coverage = "素材已覆盖"
        proposals = []
        for proposal in shot.get("generation_proposals") or []:
            if not isinstance(proposal, Mapping):
                continue
            proposals.append({
                "id": _safe_text(proposal.get("id")),
                "operation": _safe_text(proposal.get("operation")),
                "model_family": _safe_text(proposal.get("model_family"), "seedance"),
                "duration_seconds": _number(proposal.get("duration_seconds")),
                "aspect_ratio": _safe_text(proposal.get("aspect_ratio")),
                "estimated_fast_cost_usd": _number(proposal.get("estimated_fast_cost_usd")),
                "estimated_standard_cost_usd": _number(proposal.get("estimated_standard_cost_usd")),
                "evidence_risk": _safe_text(proposal.get("evidence_risk")),
            })
        execution_shots.append({
            "id": _safe_text(shot.get("id"), f"shot-{index + 1}"),
            "order": int(shot.get("order") or index + 1),
            "purpose": _safe_text(shot.get("purpose")),
            "duration_seconds": _number(shot.get("duration_seconds")),
            "narration": _safe_text(shot.get("narration")),
            "screen_copy": _safe_text(shot.get("screen_copy")),
            "subject_action": _safe_text(shot.get("subject_action")),
            "setting": _safe_text(shot.get("setting")),
            "framing": _safe_text(shot.get("framing")),
            "camera": _safe_text(shot.get("camera")),
            "lighting": _safe_text(shot.get("lighting")),
            "sound": _safe_text(shot.get("sound")),
            "evidence_type": _safe_text(shot.get("evidence_type")),
            "coverage_status": _safe_text(shot.get("coverage_status")),
            "gap_class": _safe_text(shot.get("gap_class")),
            "gap_strategy": _safe_text(shot.get("gap_strategy")),
            "source_label": Path(str(source.get("path"))).stem if source else "",
            "source_reason": _safe_text(source.get("fit_reason")) if source else "",
            "source_in_seconds": source_in,
            "source_out_seconds": source_out,
            "source_duration_seconds": source_duration,
            "source_coverage": source_coverage,
            "reference_mechanisms": [str(value) for value in shot.get("reference_mechanisms") or []],
            "industry_notes": [str(value) for value in shot.get("industry_notes") or []],
            "control_rule_refs": [str(value) for value in shot.get("control_rule_refs") or []],
            "generation_proposals": proposals,
            "selected_generation_task_id": shot.get("selected_generation_task_id"),
        })
    return {
        "type": "asset_review",
        "data": {
            "narration_status": category_status("narration", "未安排口播"),
            "subtitle_status": category_status("subtitles", "未安排字幕"),
            "music_status": category_status("music", "未安排背景音乐"),
            "estimated_cost_usd": round(estimated_total, 4) if estimated_total else None,
            "spent_cost_usd": spent,
            "planned_count": len(projected),
            "prepared_count": prepared_count,
            "waiting_confirmation_count": waiting_confirmation_count,
            "paid_generation_approved": paid_approved,
            "items": projected,
            "execution_plan": {
                "plan_id": _safe_text(execution.get("plan_id")),
                "plan_version": int(execution.get("plan_version") or 1),
                "status": _safe_text(execution.get("status"), "draft"),
                "locked": execution.get("status") == "approved",
                "handoff_ready": execution.get("status") == "approved",
                "shots": execution_shots,
            } if execution else None,
        },
    }


def _evaluation_summary(eval_report: Mapping[str, Any]) -> dict[str, Any] | None:
    """把 evaluation_report 投影为审核台评价卡 payload（delivery_evaluation 形状）。"""
    if not (isinstance(eval_report, Mapping) and eval_report.get("scope") in {"sample", "final"}):
        return None
    advisory = eval_report.get("creative_advisory") if isinstance(eval_report.get("creative_advisory"), Mapping) else {}
    return {
        "status": _safe_text(eval_report.get("status")),
        "recommended_action": _safe_text(eval_report.get("recommended_action")),
        "judge_version": _safe_text(eval_report.get("judge_version")),
        "hard_gate_fails": [
            {"name": _safe_text(c.get("name")), "message": _safe_text(c.get("message")), "fixable": c.get("fixable") is True}
            for c in (eval_report.get("hard_gate") or {}).get("checks", [])
            if isinstance(c, Mapping) and c.get("status") == "fail"
        ],
        "advisory": {
            "scored": bool(advisory.get("scored")),
            "summary": _safe_text(advisory.get("summary"), "尚未运行 VLM 创意评审"),
            "dimensions": [
                {"name": _safe_text(d.get("name")), "score": d.get("score"), "note": _safe_text(d.get("note"))}
                for d in (advisory.get("dimensions") or [])
                if isinstance(d, Mapping)
            ],
        },
    }


def _sample_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    report = _artifact(board, "sample_report")
    raw_trace = _artifact(board, "sample_execution_trace")
    if not raw_trace and report and _artifact(board, "final_props") and _artifact(board, "shot_execution_plan"):
        from lib.sample_execution_trace import build_sample_execution_trace

        raw_trace = build_sample_execution_trace(
            str(board.get("project_id") or "project"),
            {name: _artifact(board, name) for name in (
                "reference_fingerprint", "creative_control_plan", "script",
                "shot_execution_plan", "final_props", "render_plan", "sample_report",
            )},
        )
    render = next(
        (
            item for item in (board.get("media") or {}).get("renders", [])
            if isinstance(item, Mapping) and "sample" in str(item.get("path", "")).lower()
        ),
        None,
    )
    project_id = str(board.get("project_id") or "project")
    status = report.get("status")
    execution_trace = None
    if raw_trace:
        summary = raw_trace.get("summary") if isinstance(raw_trace.get("summary"), Mapping) else {}
        narration_by_shot: dict[str, str] = {}
        execution_plan = _artifact(board, "shot_execution_plan")
        for plan_shot in execution_plan.get("shots") or []:
            if isinstance(plan_shot, Mapping) and plan_shot.get("id"):
                narration_by_shot[str(plan_shot.get("id"))] = _safe_text(plan_shot.get("narration"))
        trace_shots = []
        for shot in raw_trace.get("shots") or []:
            if not isinstance(shot, Mapping):
                continue
            planned = shot.get("planned_basis") if isinstance(shot.get("planned_basis"), Mapping) else {}
            actual = shot.get("actual_execution") if isinstance(shot.get("actual_execution"), Mapping) else None
            actual_view = None
            if actual is not None:
                source_path = str(actual.get("source_path") or "")
                actual_view = {
                    "source_label": Path(source_path).stem if source_path else "",
                    "source_in_seconds": actual.get("source_in_seconds"),
                    "source_out_seconds": actual.get("source_out_seconds"),
                    "timeline_start_seconds": actual.get("timeline_start_seconds"),
                    "timeline_end_seconds": actual.get("timeline_end_seconds"),
                    "screen_copy": _safe_text(actual.get("screen_copy")),
                    "narration": _safe_text(actual.get("narration")),
                }
            trace_shots.append({
                "shot_id": _safe_text(shot.get("shot_id")),
                "status": _safe_text(shot.get("status")),
                "status_label": _safe_text(shot.get("status_label")),
                "planned": {
                    "purpose": _safe_text(planned.get("purpose")),
                    "subject_action": _safe_text(planned.get("subject_action")),
                    "screen_copy": _safe_text(planned.get("screen_copy")),
                    "narration": narration_by_shot.get(_safe_text(shot.get("shot_id")), ""),
                    "reference_rules": [_safe_text(item) for item in planned.get("reference_rules") or []],
                },
                "actual": actual_view,
                "deviation": shot.get("deviation"),
                "sample_window": shot.get("sample_window") if isinstance(shot.get("sample_window"), Mapping) else None,
            })
        execution_trace = {"summary": summary, "shots": trace_shots}
    caption_diff = (
        raw_trace.get("caption_diff")
        if isinstance(raw_trace, Mapping) and isinstance(raw_trace.get("caption_diff"), Mapping)
        else None
    )
    creative_rule_diff = (
        raw_trace.get("creative_rule_diff")
        if isinstance(raw_trace, Mapping) and isinstance(raw_trace.get("creative_rule_diff"), Mapping)
        else None
    )
    # 评审缺口 #4：样片页补齐评价卡 + 三轨音频（口播/BGM/原声）。
    evaluation = None
    eval_report = _artifact(board, "evaluation_report.sample") or _artifact(board, "evaluation_report")
    if isinstance(eval_report, Mapping) and eval_report.get("scope") == "sample":
        evaluation = _evaluation_summary(eval_report)
    audio_tracks = _audio_tracks(raw_trace)
    qa_status = _merge_qa_with_evaluation(status, evaluation)
    return {
        "type": "sample_review",
        "data": {
            "duration_seconds": _number(render.get("duration_seconds")) if render else None,
            "preview_url": _media_url(project_id, render.get("path")) if render else None,
            "qa_status": qa_status,
            "review_summary": "等待确认样片效果" if qa_status == "检查通过" else "样片尚有需要调整的检查项",
            "execution_trace": execution_trace,
            "evaluation": evaluation,
            "audio_tracks": audio_tracks,
            "caption_diff": caption_diff,
            "creative_rule_diff": creative_rule_diff,
        },
    }


def _merge_qa_with_evaluation(file_status: Any, evaluation: Mapping[str, Any] | None, pending_label: str = "等待检查") -> str:
    """文件/渲染检查与内容质量评价合并为唯一结论：更严格的评价结果优先。

    避免页面同时呈现「检查通过，可以交付」与 revise/repair、硬门失败。
    evaluation.status: pass/revise/fail；recommended_action: proceed/repair/reject。
    """
    if file_status is None or str(file_status) not in {"pass", "fail"}:
        return pending_label
    if str(file_status) == "fail":
        return "需要调整"
    # 文件检查 pass：再按内容质量评价归约
    if isinstance(evaluation, Mapping):
        if str(evaluation.get("status") or "") in {"revise", "fail"}:
            return "需要调整"
        if str(evaluation.get("recommended_action") or "") in {"repair", "reject"}:
            return "需要调整"
        hard_fails = evaluation.get("hard_gate_fails")
        if isinstance(hard_fails, list) and hard_fails:
            return "需要调整"
    return "检查通过"


def _audio_tracks(raw_trace: Any) -> list[dict[str, Any]]:
    """口播/BGM/原声三轨状态（来自 sample_execution_trace.audio_diff）。"""
    diff = raw_trace.get("audio_diff") if isinstance(raw_trace, Mapping) else None
    diff = diff if isinstance(diff, Mapping) else {}
    plan = diff.get("plan") if isinstance(diff.get("plan"), Mapping) else {}
    actual = diff.get("actual") if isinstance(diff.get("actual"), Mapping) else {}

    def track(kind: str, label: str, planned: bool, present: bool, presence_only: bool = False) -> dict[str, Any]:
        if presence_only:
            # 原声没有「计划」语义：只表达实际存在与否；缺失信号表达为 unknown，不默认成 True。
            state = "present" if present else ("unknown" if present is None else "not_planned")
        else:
            state = "present" if planned and present else ("missing" if planned else "not_planned")
        return {
            "kind": kind,
            "label": label,
            "planned": bool(planned),
            "present": bool(present) if present is not None else False,
            "state": state,
        }

    original_sound = actual.get("original_sound")
    return [
        track("narration", "口播", plan.get("narration_planned"), actual.get("narration_present")),
        track("bgm", "BGM", plan.get("music_planned"), actual.get("music_present")),
        track("original", "原声", False, None if original_sound is None else bool(original_sound), presence_only=True),
    ]


def _edit_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    impact = _artifact(board, "change_impact")
    decisions = _artifact(board, "edit_decisions")
    scene_plan = _artifact(board, "scene_plan")
    script = _artifact(board, "script")
    route = impact.get("route")
    reasons = [_safe_text(reason) for reason in impact.get("reasons") or []]
    reasons = [reason for reason in reasons if reason]
    dirty = impact.get("dirty_scene_ids") if isinstance(impact.get("dirty_scene_ids"), list) else []
    project_id = str(board.get("project_id") or "project")
    sample = _sample_editor(board)["data"]
    scenes = {
        str(scene.get("id")): scene
        for scene in scene_plan.get("scenes") or []
        if isinstance(scene, Mapping) and scene.get("id")
    }
    sections = {
        str(section.get("id")): section
        for section in script.get("sections") or []
        if isinstance(section, Mapping) and section.get("id")
    }
    overrides = {
        str(item.get("shot_id")): _safe_text(item.get("text"))
        for item in decisions.get("caption_overrides") or []
        if isinstance(item, Mapping) and item.get("shot_id")
    }
    shots = []
    for index, cut in enumerate(decisions.get("cuts") or []):
        if not isinstance(cut, Mapping):
            continue
        shot_id = _safe_text(cut.get("id"), f"sc{index + 1:02d}")
        scene = scenes.get(shot_id, {})
        section = sections.get(str(scene.get("script_section_id")), {})
        source = cut.get("source")
        source_in = _number(cut.get("in_seconds"))
        source_out = _number(cut.get("out_seconds"))
        overlay = next(
            (item for item in scene.get("overlay_layers") or [] if isinstance(item, Mapping)),
            {},
        )
        caption = overrides.get(shot_id) or _safe_text(overlay.get("text"))
        shots.append({
            "id": shot_id,
            "title": _safe_text(scene.get("description"), f"第 {index + 1} 个镜头"),
            "source_label": Path(str(source)).stem if source else "尚未指定素材",
            "source_in_seconds": source_in,
            "source_out_seconds": source_out,
            "duration_seconds": round(max(0.0, (source_out or 0) - (source_in or 0)), 2),
            "enabled": cut.get("enabled", True) is not False,
            "speed": _number(cut.get("speed")) or 1,
            "caption": caption,
            "narration": _safe_text(section.get("narration")) or _safe_text(section.get("text")),
            "reason": _safe_text(cut.get("reason")) or _safe_text(scene.get("shot_intent")),
            "preview_url": _media_url(project_id, source),
            "poster_url": _thumb_url(
                project_id,
                source,
                time_seconds=(float(source_in) + float(source_out)) / 2
                if source_in is not None and source_out is not None else None,
            ),
        })
    audio = decisions.get("audio") if isinstance(decisions.get("audio"), Mapping) else {}
    music = audio.get("music") if isinstance(audio.get("music"), Mapping) else {}
    sfx_items = audio.get("sfx") if isinstance(audio.get("sfx"), list) else []
    first_sfx = sfx_items[0] if sfx_items and isinstance(sfx_items[0], Mapping) else {}
    narration = audio.get("narration") if isinstance(audio.get("narration"), Mapping) else {}
    return {
        "type": "edit_review",
        "data": {
            "change_scope": ROUTE_LABELS.get(str(route), "尚未确定修改范围"),
            "reasons": reasons,
            "affected_shot_count": len(dirty),
            "summary": "样片已验收。这里可以删减镜头、调整节奏、修改字幕和声音；每次修改先看影响预览，确认后才生成新版样片。",
            "preview_url": sample.get("preview_url"),
            "preview_duration_seconds": sample.get("duration_seconds"),
            "shots": shots,
            "audio": {
                "music_volume": _number(music.get("volume")) or 0,
                "sfx_volume": _number(first_sfx.get("volume")) or 0,
                "narration_enabled": narration.get("enabled", True) is not False,
            },
            "capabilities": ["删减镜头", "调整镜头时长和速度", "修改字幕与口播", "调整背景音乐和音效"],
        },
    }


def _delivery_editor(
    board: Mapping[str, Any], stage_name: str = "compose"
) -> dict[str, Any]:
    report = _artifact(board, "render_report")
    final_review = _artifact(board, "final_review")
    decisions = _artifact(board, "edit_decisions")
    scene_plan = _artifact(board, "scene_plan")
    script = _artifact(board, "script")
    delivery_review = _artifact(board, "delivery_review")
    outputs = report.get("outputs") if isinstance(report.get("outputs"), list) else []
    output = next((item for item in outputs if isinstance(item, Mapping)), None)
    render = next(
        (
            item for item in (board.get("media") or {}).get("renders", [])
            if isinstance(item, Mapping) and "final" in str(item.get("path", "")).lower()
        ),
        None,
    )
    source = output or render
    project_id = str(board.get("project_id") or "project")
    source_path = source.get("path") if source else None
    video_url = _media_url(project_id, source_path)
    duration = _number(source.get("duration_seconds")) if source else None
    if duration is None:
        duration = _number(script.get("total_duration_seconds"))
    poster_time = min(1.0, float(duration or 1) / 2)
    poster_url = _thumb_url(project_id, source_path, time_seconds=poster_time)

    raw_scenes = scene_plan.get("scenes") if isinstance(scene_plan.get("scenes"), list) else []
    scenes = {
        str(item.get("id")): item
        for item in raw_scenes
        if isinstance(item, Mapping) and item.get("id")
    }
    cuts = decisions.get("cuts") if isinstance(decisions.get("cuts"), list) else []
    cut_by_id = {
        str(item.get("id")): item
        for item in cuts
        if isinstance(item, Mapping) and item.get("id")
    }

    video_segments = []
    for index, scene in enumerate(raw_scenes):
        if not isinstance(scene, Mapping):
            continue
        shot_id = _safe_text(scene.get("id"), f"shot-{index + 1}")
        start = _number(scene.get("start_seconds")) or 0
        end = _number(scene.get("end_seconds")) or start
        if end < start:
            continue
        cut = cut_by_id.get(shot_id, {})
        media_path = cut.get("source")
        normalized = str(media_path or "").replace("\\", "/").lower()
        if "/inputs/reference/" in f"/{normalized.strip('/')}":
            media_path = None
        source_in = _number(cut.get("in_seconds"))
        source_out = _number(cut.get("out_seconds"))
        video_segments.append({
            "id": shot_id,
            "label": _safe_text(scene.get("description"), f"第 {index + 1} 个镜头"),
            "start_seconds": start,
            "end_seconds": end,
            "shot_ids": [shot_id],
            "preview_url": _media_url(project_id, media_path),
            "poster_url": _thumb_url(
                project_id,
                media_path,
                time_seconds=(float(source_in) + float(source_out)) / 2
                if source_in is not None and source_out is not None else None,
            ),
            "source_label": Path(str(media_path)).stem if media_path else "素材待确认",
            "editable": False,
            "sync_narration": False,
        })

    raw_sections = script.get("sections") if isinstance(script.get("sections"), list) else []
    sentence_segments = []
    narration_segments = []
    for index, section in enumerate(raw_sections):
        if not isinstance(section, Mapping):
            continue
        section_id = _safe_text(section.get("id"), f"sentence-{index + 1}")
        start = _number(section.get("start_seconds")) or 0
        end = _number(section.get("end_seconds")) or start
        text = _safe_text(section.get("narration")) or _safe_text(section.get("text"))
        shot_ids = [
            str(scene.get("id"))
            for scene in raw_scenes
            if isinstance(scene, Mapping)
            and scene.get("id")
            and (
                str(scene.get("script_section_id") or "") == section_id
                or (
                    (_number(scene.get("start_seconds")) or 0) < end
                    and (_number(scene.get("end_seconds")) or 0) > start
                )
            )
        ]
        segment = {
            "id": section_id,
            "label": text or _safe_text(section.get("label"), "文案"),
            "start_seconds": start,
            "end_seconds": end,
            "shot_ids": list(dict.fromkeys(shot_ids)),
            "editable": True,
            "sync_narration": True,
        }
        sentence_segments.append(segment)
        narration_segments.append(dict(segment, editable=False))

    audio = decisions.get("audio") if isinstance(decisions.get("audio"), Mapping) else {}
    music = audio.get("music") if isinstance(audio.get("music"), Mapping) else {}
    sfx_items = audio.get("sfx") if isinstance(audio.get("sfx"), list) else []
    audio_segments = []
    music_id = _safe_text(music.get("asset_id"))
    if music_id:
        audio_segments.append({
            "id": music_id,
            "label": "当前背景音乐",
            "start_seconds": 0,
            "end_seconds": duration or 0,
            "shot_ids": [],
            "editable": False,
            "sync_narration": False,
        })
    for index, item in enumerate(sfx_items):
        if not isinstance(item, Mapping):
            continue
        start = _number(item.get("start_seconds")) or 0
        audio_segments.append({
            "id": _safe_text(item.get("asset_id"), f"sfx-{index + 1}"),
            "label": "音效",
            "start_seconds": start,
            "end_seconds": start,
            "shot_ids": [],
            "editable": False,
            "sync_narration": False,
        })

    tracks = [
        {"kind": "video", "label": "画面", "empty_message": None if video_segments else "当前成片没有可识别的画面分镜", "segments": video_segments},
        {"kind": "narration", "label": "口播", "empty_message": None if narration_segments else "当前成片未配置口播", "segments": narration_segments},
        {"kind": "copy", "label": "文案", "empty_message": None if sentence_segments else "当前成片未配置字幕文案", "segments": sentence_segments},
        {"kind": "audio", "label": "背景音乐与音效", "empty_message": None if audio_segments else "当前成片未配置背景音乐", "segments": audio_segments},
    ]

    version_seed = _safe_text(report.get("video_master_sha256")) or _safe_text(source_path) or project_id

    def candidate_id(kind: str, value: Any) -> str:
        digest = hashlib.sha256(
            json.dumps([version_seed, kind, value], ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        return f"{kind}-{digest}"

    first_segment = video_segments[0] if video_segments else None
    last_segment = video_segments[-1] if video_segments else None
    selected_cover = _safe_text(delivery_review.get("selected_cover_id"))
    selected_hook = _safe_text(delivery_review.get("selected_hook_id"))
    selected_bgm = _safe_text(delivery_review.get("selected_bgm_id"))
    selected_ending = _safe_text(delivery_review.get("selected_ending_id"))
    cover_specs = [
        ("产品清晰帧", poster_time, "产品主体清晰，适合作为默认发布封面"),
        ("中段效果帧", max(1.0, float(duration or 2) / 2), "突出产品使用过程和效果证据"),
        ("结尾场景帧", max(1.0, float(duration or 2) - 1), "展示完整使用场景，适合稳妥收束"),
    ] if poster_url else []
    cover_candidates = []
    for label, timestamp, summary in cover_specs:
        item_id = candidate_id("cover", timestamp)
        cover_candidates.append({
            "id": item_id,
            "label": label,
            "summary": summary,
            "preview_url": _thumb_url(project_id, source_path, time_seconds=timestamp),
            "selected": selected_cover == item_id or (not selected_cover and not cover_candidates),
        })
    hook_specs = []
    if first_segment:
        hook_specs.append(("当前冲突开场", video_segments[:2], "保留当前前三秒的镜头顺序和首句文案"))
    if len(video_segments) > 2:
        result_segment = next(
            (item for item in video_segments[1:] if item["id"] != first_segment["id"]),
            None,
        )
        if result_segment:
            hook_specs.append(("结果先行开场", [result_segment, first_segment], "先展示使用结果，再回到动作证明"))
    hook_candidates = []
    for label, segments, summary in hook_specs:
        item_id = candidate_id("hook", [item["id"] for item in segments])
        hook_candidates.append({
            "id": item_id,
            "label": label,
            "summary": summary,
            "preview_url": segments[0].get("preview_url") or video_url,
            "selected": selected_hook == item_id or (not selected_hook and not hook_candidates),
        })
    bgm_candidates = [{
        "id": candidate_id("bgm", music_id),
        "label": "当前背景音乐",
        "summary": "保留当前混音、淡入淡出和口播避让设置",
        "preview_url": None,
        "selected": selected_bgm == candidate_id("bgm", music_id) or not selected_bgm,
    }] if music_id else []
    ending_candidates = [{
        "id": candidate_id("ending", last_segment["id"]),
        "label": "当前结尾",
        "summary": "保留最后一个产品画面和行动引导",
        "preview_url": last_segment.get("poster_url") or poster_url,
        "selected": selected_ending == candidate_id("ending", last_segment["id"]) or not selected_ending,
    }] if last_segment else []
    candidate_groups = [
        {"kind": "cover", "label": "封面", "empty_message": None if cover_candidates else "暂时无法从成片提取清晰封面", "candidates": cover_candidates},
        {"kind": "hook", "label": "前三秒", "empty_message": None if hook_candidates else "当前没有可组合的前三秒方案", "candidates": hook_candidates},
        {"kind": "bgm", "label": "背景音乐", "empty_message": None if bgm_candidates else "当前成片未配置背景音乐", "candidates": bgm_candidates},
        {"kind": "ending", "label": "结尾", "empty_message": None if ending_candidates else "当前没有可用的结尾画面", "candidates": ending_candidates},
    ]

    qa_passed = final_review.get("status") == "pass"
    stored_versions = board.get("_delivery_versions") if isinstance(board.get("_delivery_versions"), list) else []
    current_delivery = board.get("_current_delivery") if isinstance(board.get("_current_delivery"), Mapping) else {}
    versions = []
    for index, version in enumerate(stored_versions):
        if not isinstance(version, Mapping):
            continue
        video = version.get("video") if isinstance(version.get("video"), Mapping) else {}
        version_id = _safe_text(version.get("version_id"), f"v{index + 1}")
        versions.append({
            "id": version_id,
            "label": f"V{index + 1}",
            "active": current_delivery.get("version_id") == version_id,
            "qa_status": "检查通过" if (version.get("qa") or {}).get("status") == "pass" else "检查未通过",
            "video_url": _media_url(project_id, video.get("path")),
            "poster_url": _media_url(project_id, video.get("poster_path")) or _thumb_url(project_id, video.get("path"), time_seconds=1),
            "change_summary": _safe_text(version.get("change_summary"), "该版本暂无变更说明"),
        })
    if not versions and video_url:
        versions = [{
            "id": candidate_id("version", version_seed),
            "label": "当前版",
            "active": True,
            "qa_status": "检查通过" if qa_passed else "等待检查",
            "video_url": video_url,
            "poster_url": poster_url,
            "change_summary": "当前已认证成片" if qa_passed else "当前成片等待完整检查",
        }]
    pending_changes = []
    for kind, selected, label in (
        ("cover", selected_cover, "封面"), ("hook", selected_hook, "前三秒"),
        ("bgm", selected_bgm, "背景音乐"), ("ending", selected_ending, "结尾"),
    ):
        if selected:
            pending_changes.append({"kind": kind, "label": label, "summary": "已选择新方案，等待生成新版"})
    for override in delivery_review.get("copy_overrides") or []:
        if isinstance(override, Mapping):
            pending_changes.append({"kind": "copy", "label": "文案", "summary": "文案已修改，等待生成新版"})
    evaluation = None
    # 评审 #3：成片评价卡优先读 final 范围报告；无 scoped 文件时回退默认键。
    eval_report = _artifact(board, "evaluation_report.final") or _artifact(board, "evaluation_report")
    if isinstance(eval_report, Mapping) and eval_report.get("scope") == "final":
        evaluation = _evaluation_summary(eval_report)
    qa_status = _merge_qa_with_evaluation(
        "pass" if qa_passed else ("fail" if final_review.get("status") else None),
        evaluation,
        pending_label="等待成片检查",
    )
    data: dict[str, Any] = {
        "duration_seconds": duration,
        "qa_status": qa_status,
        "download_url": video_url,
        "format_label": _safe_text(output.get("resolution"), "竖屏视频") if output else "竖屏视频",
        "player": {
            "video_url": video_url,
            "poster_url": poster_url,
            "duration_seconds": duration,
        },
        "timeline": {"duration_seconds": duration, "tracks": tracks},
        "candidate_groups": candidate_groups,
        "versions": versions,
        "pending_changes": pending_changes,
        "evaluation": evaluation,
    }
    # The publish stage shares this review workbench but additionally surfaces
    # the delivery package: publish_log entries, copy metadata and delivery
    # notes. Compose keeps the review-only surface.
    if stage_name == "publish":
        publish_log = _artifact(board, "publish_log")
        entries = []
        for entry in publish_log.get("entries") or []:
            if not isinstance(entry, Mapping):
                continue
            used = (
                entry.get("metadata_used")
                if isinstance(entry.get("metadata_used"), Mapping)
                else {}
            )
            platform = str(entry.get("platform") or "local")
            status = str(entry.get("status") or "exported")
            entries.append({
                "platform": platform,
                "platform_label": PLATFORM_LABELS.get(platform, platform),
                "status": status,
                "status_label": PUBLISH_STATUS_LABELS.get(status, status),
                "title": _safe_text(used.get("title"), "未设置标题"),
                "description": _safe_text(used.get("description")),
                "hashtags": [
                    str(tag) for tag in (used.get("hashtags") or [])
                    if isinstance(tag, str)
                ][:12],
                "export_path": _project_relative_path(
                    str(board.get("project_id") or "project"), entry.get("export_path")
                ),
                "timestamp": _safe_text(entry.get("timestamp")),
            })
        log_meta = (
            publish_log.get("metadata")
            if isinstance(publish_log.get("metadata"), Mapping)
            else {}
        )
        project_id = str(board.get("project_id") or "project")
        package_path = _project_relative_path(
            project_id,
            next((item.get("export_path") for item in publish_log.get("entries") or []
                  if isinstance(item, Mapping) and item.get("export_path")),
                 log_meta.get("hero_output")),
        )
        evidence = []
        for item in (log_meta.get("qa_evidence") or []):
            path = _project_relative_path(project_id, item)
            if path:
                evidence.append({
                    "relative_path": path,
                    "label": Path(path).name,
                    "download_url": _delivery_url(project_id, path),
                })
        data["delivery"] = {
            "entries": entries,
            "package_path": package_path,
            "package_files": _delivery_package_files(board, project_id, package_path),
            "notes": _safe_text(
                log_meta.get("distribution_notes"),
                "该版本尚未填写交付说明",
            ),
            "hero_output": _project_relative_path(project_id, log_meta.get("hero_output")),
            "qa_evidence": evidence,
        }
    return {
        "type": "delivery_review",
        "data": data,
    }


def _editor_for(stage_name: str, board: Mapping[str, Any]) -> dict[str, Any]:
    editor_type = EDITOR_BY_STAGE.get(stage_name)
    if editor_type == "research_review":
        return _research_editor(board)
    if editor_type == "proposal_choice":
        return _proposal_editor(board)
    if editor_type == "script_editor":
        return _script_editor(board)
    if editor_type == "shot_mapping":
        return _shot_editor(board)
    if editor_type == "asset_review":
        return _asset_editor(board)
    if editor_type == "sample_review":
        return _sample_editor(board)
    if editor_type == "edit_review":
        return _edit_editor(board)
    if editor_type == "delivery_review":
        return _delivery_editor(board, stage_name)
    return {"type": "unavailable", "data": {"message": "该步骤暂无可展示的结构化内容"}}


def _stage_label(name: str) -> str:
    return STAGE_LABELS.get(name) or LEGACY_STAGE_LABELS.get(name) or "其他步骤"


def _stage_summary(label: str, raw_status: str) -> str:
    return {
        "pending": f"{label}尚未开始",
        "in_progress": f"正在处理{label}",
        "awaiting_human": f"{label}等待确认",
        "completed": f"{label}已完成",
        "failed": f"{label}处理失败，请查看诊断信息",
    }.get(raw_status, f"{label}状态暂不可用")


def _select_current_stage(stages: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    for status in ("awaiting_human", "in_progress", "pending"):
        match = next((stage for stage in stages if stage.get("status") == status), None)
        if match is not None:
            return match
    return stages[-1]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 批级驾驶舱投影（Batch_Workbench_Aggregate_State_Event_Contract v1.0 §2）
# 实现细节委托 backlot/batch_state.py；此处只做顶层状态装配。
# ---------------------------------------------------------------------------


def _batch_editor(board: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, Any]:
    from backlot.batch_state import build_batch_review_data

    data = build_batch_review_data(board, batch)
    return {"type": "batch_review", "data": data}


def _batch_progress_percent(data: Mapping[str, Any], phase: str) -> int:
    rail_phases = [str(item.get("phase")) for item in (data.get("rail") or [])]
    total = max(len(rail_phases), 1)
    if phase == "completed":
        return 100
    if phase in rail_phases:
        index = rail_phases.index(phase)
    else:  # blocked：停驻在最后推进到的位置
        index = total - 1
    return round(index / total * 100)


def _batch_operator_state(board: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, Any]:
    """批项目（含 candidate_batch）的批级状态投影。"""
    from backlot.batch_state import RAIL_LABELS, build_batch_review_data

    data = build_batch_review_data(board, batch)
    phase = str(data.get("phase") or "building")
    gates = [gate for gate in (data.get("pending_gates") or []) if gate.get("candidates")]
    stages = []
    for rail_item in data.get("rail") or []:
        rail_phase = str(rail_item.get("phase"))
        raw_status = rail_item.get("status")
        stage_status = (
            "completed" if raw_status == "completed"
            else ("awaiting_human" if gates and raw_status == "current" else
                  "in_progress" if raw_status == "current" else "pending")
        )
        stages.append({
            "id": rail_phase,
            "label": RAIL_LABELS.get(rail_phase, rail_phase),
            "status": STATUS_LABELS.get(stage_status, STATUS_LABELS["unknown"]),
            "version": 0,
            "updated_at": None,
            "updated_by": None,
            "editable": False,
            "summary": _stage_summary(RAIL_LABELS.get(rail_phase, rail_phase), stage_status),
            "warnings": [w.get("description") for w in (data.get("warnings") or []) if w.get("candidate_id") is None],
            "editor": {"type": "unavailable", "data": {"message": "批级阶段在驾驶舱总览中展示"}},
        })
    current = next((stage for stage in stages if stage["id"] == phase), stages[0])
    pending_review = None
    if gates:
        gate = gates[0]
        pending_review = {
            "kind": "batch_gate",
            "label": f"批量确认{gate['label']}（{len(gate['candidates'])} 个候选）",
            "summary": data.get("phase_reason") or "可在驾驶舱逐候选复核后一键全部通过",
            "subject_version": 0,
            "gate": gate["gate"],
            "candidates": gate["candidates"],
        }
    consistency_label = {"stable": "稳定", "unstable": "读取期间候选状态变化", "degraded": "存在降级候选或预算不一致"}
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "project_id": str(board.get("project_id") or "unknown-batch"),
        "title": _safe_text(board.get("title"), "批量混剪"),
        "pipeline": "cinematic-fast",
        "skill": None,
        "summary": {
            "current_stage": RAIL_LABELS.get(phase, phase),
            "current_task": f"{data.get('phase_reason') or '批量生产进行中'}（一致性：{consistency_label.get(data.get('consistency'), data.get('consistency'))}）",
            "progress_percent": _batch_progress_percent(data, phase),
            "next_action": "等待批级门确认" if pending_review else "在驾驶舱查看候选矩阵与评分",
            "estimated_seconds": None,
            "estimate_confidence": None,
            "spent_usd": float((data.get("budget") or {}).get("spent_usd") or 0),
        },
        "stages": stages,
        "workspace": {
            "stage_id": phase,
            "editor": _batch_editor(board, batch),
            "read_only": True,
            "upgrade_action": None,
        },
        "pending_review": pending_review,
        "permissions": ["view", "review"],
        "active_job": None,
        "revision": "0" * 64,
        "legacy": {
            "read_only": False,
            "source_pipeline": "cinematic-fast",
            "upgrade_available": False,
            "message": "",
        },
    }
    state["revision"] = operator_revision(state)
    validate_operator_state(state)
    return state


def operator_revision(state: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in state.items() if key != "revision"}
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _performance_summary(project_dir: Path) -> dict[str, Any]:
    reports = sorted((project_dir / "analysis" / "benchmarks").glob("*.json"))
    if not reports:
        return {"promise": None, "message": "实测数据不足，暂不展示效率承诺"}
    try:
        report = json.loads(reports[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"promise": None, "message": "实测数据暂时无法读取"}
    sla = report.get("sla") if isinstance(report.get("sla"), Mapping) else {}
    cold = sla.get("cold") if isinstance(sla.get("cold"), Mapping) else {}
    if cold.get("publish_sla") is True:
        return {"promise": "完整制作通常可在 3-5 小时内完成", "message": "已达到真实样本发布门槛"}
    count = int(cold.get("sample_count") or 0)
    return {"promise": None, "message": f"已完成 {count} 次完整制作实测，样本仍不足"}


def project_operator_state(board_state: Mapping[str, Any]) -> dict[str, Any]:
    """Project BoardState into a recursively closed business response."""
    board = dict(board_state)
    # 批项目（candidate_batch 索引存在）走批级驾驶舱分支（设计文档 §4.1）。
    candidate_batch = _artifact(board, "candidate_batch")
    if isinstance(candidate_batch, Mapping) and candidate_batch.get("candidates"):
        return _batch_operator_state(board, candidate_batch)
    pipeline_meta = board.get("pipeline") if isinstance(board.get("pipeline"), Mapping) else {}
    pipeline_type = str(pipeline_meta.get("pipeline_type") or "unknown")
    raw_stages = [
        stage for stage in (board.get("stages") or [])
        if isinstance(stage, Mapping) and stage.get("name")
    ]
    if pipeline_type in {"cinematic", "cinematic-fast"}:
        stages_by_name = {str(stage["name"]): stage for stage in raw_stages}
        raw_stages = [
            stages_by_name.get(name, {
                "name": name,
                "status": "unknown",
                "versions": 0,
                "timestamp": None,
            })
            for name in STAGE_LABELS
        ]
        # The operator commit removes the awaiting-human checkpoint after the
        # execution plan is approved. Treat that durable approval as the
        # completed Assets gate until the Agent writes the next checkpoint.
        execution_plan = _artifact(board, "shot_execution_plan")
        if execution_plan.get("status") == "approved":
            raw_stages = [
                {
                    **stage,
                    "status": "completed",
                    "human_approved": True,
                }
                if stage.get("name") == "assets" and stage.get("status") in {"pending", "awaiting_human"}
                else stage
                for stage in raw_stages
            ]
    elif not raw_stages:
        raw_stages = [{"name": "unknown", "status": "pending", "versions": 0}]

    stages = []
    for raw in raw_stages:
        name = str(raw.get("name"))
        raw_status = str(raw.get("status") or "unknown")
        label = _stage_label(name)
        warnings = []
        if raw_status == "failed":
            warnings.append("该步骤处理失败，请打开诊断信息查看详情")
        stages.append({
            "id": name,
            "label": label,
            "status": STATUS_LABELS.get(raw_status, STATUS_LABELS["unknown"]),
            "version": max(0, int(raw.get("versions") or 0)),
            "updated_at": _safe_text(raw.get("timestamp")) or None,
            "updated_by": None,
            "editable": False,
            "summary": _stage_summary(label, raw_status),
            "warnings": warnings,
            "editor": _editor_for(name, board),
        })

    current_raw = _select_current_stage(raw_stages)
    current_name = str(current_raw.get("name"))
    current = next(stage for stage in stages if stage["id"] == current_name)
    completed = sum(1 for stage in raw_stages if stage.get("status") == "completed")
    progress = round(completed / len(raw_stages) * 100)
    fastline = board.get("fastline") if isinstance(board.get("fastline"), Mapping) else {}
    eta = fastline.get("eta") if isinstance(fastline.get("eta"), Mapping) else {}
    current_task = _safe_text(fastline.get("current_task")) or current["summary"]
    next_action = _safe_text(fastline.get("next_action"))
    if not next_action:
        next_action = "请确认当前步骤" if current_raw.get("status") == "awaiting_human" else "等待当前步骤完成"
    spent = _number((board.get("cost") or {}).get("total_spent_usd"))

    pipeline_is_fastline = pipeline_type == "cinematic-fast"
    source_pipeline = pipeline_type or "unknown"
    legacy_message = "" if pipeline_is_fastline else "该项目创建于快线升级前，可查看内容；编辑前需创建快线运营副本"
    upgrade_available = pipeline_type == "cinematic"

    pending_review = None
    if current_raw.get("status") == "awaiting_human":
        kind = (
            "script_lock" if current_name == "script"
            else "creative_lock" if current_name == "assets"
            else "sample" if current_name == "sample"
            else "stage"
        )
        pending_review = {
            "kind": kind,
            "label": f"请确认{current['label']}",
            "summary": current["summary"],
            "subject_version": current["version"],
        }

    state: dict[str, Any] = {
        "schema_version": "1.0",
        "project_id": str(board.get("project_id") or "unknown-project"),
        "title": _safe_text(board.get("title"), "未命名项目"),
        "pipeline": source_pipeline,
        "skill": None,
        "summary": {
            "current_stage": current["label"],
            "current_task": current_task,
            "progress_percent": progress,
            "next_action": next_action,
            "estimated_seconds": int(eta["seconds"]) if _number(eta.get("seconds")) is not None else None,
            "estimate_confidence": eta.get("confidence") if eta.get("confidence") in {"low", "medium", "high"} else None,
            "spent_usd": spent,
        },
        "stages": stages,
        "workspace": {
            "stage_id": current_name,
            "editor": current["editor"],
            "read_only": True,
            "upgrade_action": "创建快线运营副本" if upgrade_available else None,
        },
        "pending_review": pending_review,
        "permissions": ["view"],
        "active_job": None,
        "revision": "0" * 64,
        "legacy": {
            "read_only": not pipeline_is_fastline,
            "source_pipeline": source_pipeline,
            "upgrade_available": upgrade_available,
            "message": legacy_message,
        },
    }
    state["revision"] = operator_revision(state)
    validate_operator_state(state)
    return state


def _inject_generation_tasks(state: dict[str, Any], project_dir: Path) -> None:
    """把 operator/shot-generation/tasks 下的真实生成任务注入 asset_review.execution_plan。

    与 `_generation_tasks_for_operator` 配对使用；`load_operator_state` 与集成测试共享本函数，
    确保真实任务注入只有一条代码路径。
    """
    tasks = _generation_tasks_for_operator(project_dir, state["project_id"])
    for stage in state["stages"]:
        editor = stage.get("editor") if isinstance(stage, Mapping) else None
        if not isinstance(editor, dict) or editor.get("type") != "asset_review":
            continue
        data = editor.get("data")
        execution = data.get("execution_plan") if isinstance(data, dict) else None
        if isinstance(execution, dict):
            execution["generation_tasks"] = tasks


def load_operator_state(
    project_dir: Path, *, permissions: tuple[str, ...] = ("view",)
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    board = load_board_state(project_dir)
    board["_project_dir"] = project_dir
    try:
        from backlot.delivery_versions import DeliveryVersionService

        delivery_versions = DeliveryVersionService(project_dir)
        board["_delivery_versions"] = delivery_versions.list()
        board["_current_delivery"] = delivery_versions.current()
    except (OSError, ValueError):
        board["_delivery_versions"] = []
        board["_current_delivery"] = None
    state = project_operator_state(board)
    _inject_generation_tasks(state, project_dir)
    state["summary"]["performance"] = _performance_summary(project_dir)
    if (project_dir / "operator" / "operator-managed").exists():
        # 纯读取（修正 3）：读取路径一律不创建 review/写 checkpoint/补事件。
        # ensure_*_review_for_checkpoint 只允许出现在：
        #  - 新项目产生 awaiting_human checkpoint 的写事务（同事务创建）
        #  - 显式迁移脚本 scripts/backfill_gate_reviews.py
        # 缺 review 时由上层（batch prepare / 单条审批）以「审批信息需要更新」反馈。
        from backlot.operator_reviews import ReviewService

        review_service = ReviewService(project_dir)
        review = review_service.pending()
        if review is None:
            state["pending_review"] = None
        else:
            kind_label = (
                "制作剧本" if review["kind"] == "script_lock"
                else "创意方案" if review["kind"] == "creative_lock"
                else "样片"
            )
            state["pending_review"] = {
                "kind": review["kind"],
                "label": f"请确认{kind_label}",
                "summary": "内容已准备完成，等待人工确认",
                "subject_version": review["subject_version"],
                "review_id": review["review_id"],
                "subject_hash": review.get("subject_hash"),
                "actions": ["批准", "拒绝"] if "review" in permissions else [],
            }
    state["permissions"] = [
        item for item in ("view", "edit", "review", "manage") if item in permissions
    ]
    # Phase 2 审批只读模式：三确认门有 pending review → view_mode=approval
    # （前端据此进入只读审批布局；不依赖 canEdit 判断，编辑视图由 view_mode 独立决定）。
    pending_review = state.get("pending_review")
    stage_id = ((state.get("workspace") or {}).get("stage_id") or "")
    if isinstance(pending_review, Mapping) and pending_review.get("review_id") \
            and stage_id in {"script", "assets", "sample"}:
        state["workspace"]["view_mode"] = "approval"
    else:
        state["workspace"]["view_mode"] = "workbench"
    state["revision"] = operator_revision(state)
    validate_operator_state(state)
    return state


def publish_batch_snapshot(state: dict, project_dir: Path) -> None:
    """显式发布路径（契约 §5）：批快照事件由批量写/刷新端点调用，读取路径不触发。

    读取路径（load_operator_state）保持纯读：不写 batch-events.jsonl /
    batch-last-snapshot.json（评审修正 3）；缺省调用点 = Phase 2/3 批量投影端点。
    """
    editor = state.get("workspace", {}).get("editor") if isinstance(state.get("workspace"), Mapping) else None
    if not (isinstance(editor, Mapping) and editor.get("type") == "batch_review"):
        return
    try:
        from backlot.batch_events import publish_snapshot

        data = editor.get("data") if isinstance(editor.get("data"), Mapping) else {}
        publish_snapshot(
            project_dir,
            aggregate_revision=str(data.get("aggregate_revision") or ""),
            phase=str(data.get("phase") or "building"),
            candidates={
                str(view.get("candidate_id") or ""): view.get("child_revision")
                for view in (data.get("candidates") or [])
                if isinstance(view, Mapping) and view.get("candidate_id")
            },
        )
    except Exception:
        pass


def delivery_candidate_ids(project_dir: Path) -> dict[str, set[str]]:
    """Return the delivery candidates valid for the project's current version."""
    state = load_operator_state(project_dir)
    allowed = {kind: set() for kind in ("cover", "hook", "bgm", "ending")}
    for stage in state.get("stages", []):
        editor = stage.get("editor") if isinstance(stage, Mapping) else None
        if not isinstance(editor, Mapping) or editor.get("type") != "delivery_review":
            continue
        data = editor.get("data") if isinstance(editor.get("data"), Mapping) else {}
        for group in data.get("candidate_groups", []):
            if not isinstance(group, Mapping):
                continue
            kind = str(group.get("kind") or "")
            if kind not in allowed:
                continue
            allowed[kind].update(
                str(item["id"])
                for item in group.get("candidates", [])
                if isinstance(item, Mapping) and item.get("id")
            )
    return allowed

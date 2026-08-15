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

from backlot.operator_language import LEGACY_STAGE_LABELS, STAGE_LABELS, STATUS_LABELS
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


def _number(value: Any) -> float | int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _media_url(project_id: str, relative_path: Any) -> str | None:
    if not isinstance(relative_path, str) or not relative_path or _ABSOLUTE_PATH.match(relative_path):
        return None
    parts = [part for part in relative_path.replace("\\", "/").split("/") if part not in {"", ".", ".."}]
    if not parts:
        return None
    encoded_path = "/".join(quote(part, safe="") for part in parts)
    return f"/media/{quote(project_id, safe='')}/{encoded_path}"


def _artifact(board: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = (board.get("artifacts") or {}).get(name)
    return value if isinstance(value, Mapping) else {}


def _research_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    research = _artifact(board, "research_brief")
    source = _artifact(board, "source_media_review")
    files = source.get("files") if isinstance(source.get("files"), list) else []
    risks: list[str] = []
    usable = 0
    for item in files:
        if not isinstance(item, Mapping):
            continue
        if item.get("usable_for"):
            usable += 1
        for risk in item.get("quality_risks") or []:
            safe = _safe_text(risk)
            if safe:
                risks.append(safe)
    summary = _safe_text(source.get("summary")) or _safe_text(research.get("summary"))
    if not summary:
        summary = _safe_text(research.get("topic"), "该步骤暂无结构化内容")
    return {
        "type": "research_review",
        "data": {
            "reference_summary": summary,
            "source_count": len(files),
            "usable_count": usable,
            "risks": risks,
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
        })
    selected = proposal.get("selected_concept")
    selected_id = _safe_text(selected.get("concept_id")) if isinstance(selected, Mapping) else ""
    return {
        "type": "proposal_choice",
        "data": {"concepts": concepts, "selected_id": selected_id or None},
    }


def _script_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    script = _artifact(board, "script")
    raw_sections = script.get("sections") if isinstance(script.get("sections"), list) else []
    sections = []
    for index, section in enumerate(raw_sections):
        if not isinstance(section, Mapping):
            continue
        sections.append({
            "id": _safe_text(section.get("id"), f"section-{index + 1}"),
            "label": _safe_text(section.get("label"), "内容"),
            "text": _safe_text(section.get("text")),
            "start_seconds": _number(section.get("start_seconds")) or 0,
            "end_seconds": _number(section.get("end_seconds")) or 0,
        })
    return {
        "type": "script_editor",
        "data": {
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
    raw_scenes = scene_plan.get("scenes") if isinstance(scene_plan.get("scenes"), list) else []
    shots = []
    for index, scene in enumerate(raw_scenes):
        if not isinstance(scene, Mapping):
            continue
        shots.append({
            "id": _safe_text(scene.get("id"), f"shot-{index + 1}"),
            "beat": _safe_text(scene.get("description")),
            "screen_copy": _safe_text(scene.get("overlay_notes")),
            "source_label": _source_label(scene),
            "in_seconds": _number(scene.get("start_seconds")) or 0,
            "out_seconds": _number(scene.get("end_seconds")) or 0,
        })
    duration = _number((scene_plan.get("metadata") or {}).get("total_duration_seconds"))
    if duration is None and shots:
        duration = max(shot["out_seconds"] for shot in shots)
    return {"type": "shot_mapping", "data": {"duration_seconds": duration, "shots": shots}}


def _asset_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = board.get("artifacts") or {}
    spent = _number((board.get("cost") or {}).get("total_spent_usd"))
    return {
        "type": "asset_review",
        "data": {
            "narration_status": "已准备" if "asset_manifest" in artifacts else "尚未准备",
            "subtitle_status": "已准备" if "asset_manifest" in artifacts else "尚未准备",
            "music_status": "已准备" if "asset_manifest" in artifacts else "尚未准备",
            "estimated_cost_usd": spent,
        },
    }


def _sample_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    report = _artifact(board, "sample_report")
    render = next(
        (
            item for item in (board.get("media") or {}).get("renders", [])
            if isinstance(item, Mapping) and "sample" in str(item.get("path", "")).lower()
        ),
        None,
    )
    project_id = str(board.get("project_id") or "project")
    status = report.get("status")
    return {
        "type": "sample_review",
        "data": {
            "duration_seconds": _number(render.get("duration_seconds")) if render else None,
            "preview_url": _media_url(project_id, render.get("path")) if render else None,
            "qa_status": "检查通过" if status == "pass" else "等待检查" if not status else "需要调整",
            "review_summary": "等待确认样片效果" if status == "pass" else "样片尚未准备完成",
        },
    }


def _edit_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    impact = _artifact(board, "change_impact")
    route = impact.get("route")
    reasons = [_safe_text(reason) for reason in impact.get("reasons") or []]
    reasons = [reason for reason in reasons if reason]
    dirty = impact.get("dirty_scene_ids") if isinstance(impact.get("dirty_scene_ids"), list) else []
    return {
        "type": "edit_review",
        "data": {
            "change_scope": ROUTE_LABELS.get(str(route), "尚未确定修改范围"),
            "reasons": reasons,
            "affected_shot_count": len(dirty),
        },
    }


def _delivery_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    report = _artifact(board, "render_report")
    outputs = report.get("outputs") if isinstance(report.get("outputs"), list) else []
    output = next((item for item in outputs if isinstance(item, Mapping)), None)
    render = next(
        (
            item for item in (board.get("media") or {}).get("renders", [])
            if isinstance(item, Mapping) and "final" in str(item.get("path", "")).lower()
        ),
        None,
    )
    source = render or output
    project_id = str(board.get("project_id") or "project")
    return {
        "type": "delivery_review",
        "data": {
            "duration_seconds": _number(source.get("duration_seconds")) if source else None,
            "qa_status": "检查通过" if output else "等待成片检查",
            "download_url": _media_url(project_id, source.get("path")) if source else None,
            "format_label": _safe_text(output.get("resolution"), "竖屏视频") if output else "竖屏视频",
        },
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
        return _delivery_editor(board)
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


def operator_revision(state: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in state.items() if key != "revision"}
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def project_operator_state(board_state: Mapping[str, Any]) -> dict[str, Any]:
    """Project BoardState into a recursively closed business response."""
    board = dict(board_state)
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
        kind = "creative_lock" if current_name == "assets" else "sample" if current_name == "sample" else "stage"
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


def load_operator_state(
    project_dir: Path, *, permissions: tuple[str, ...] = ("view",)
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    state = project_operator_state(load_board_state(project_dir))
    if (project_dir / "operator" / "operator-managed").exists():
        from backlot.operator_reviews import ReviewService

        review = ReviewService(project_dir).pending()
        if review is None:
            state["pending_review"] = None
        else:
            kind_label = "创意方案" if review["kind"] == "creative_lock" else "样片"
            state["pending_review"] = {
                "kind": review["kind"],
                "label": f"请确认{kind_label}",
                "summary": "内容已准备完成，等待人工确认",
                "subject_version": review["subject_version"],
                "review_id": review["review_id"],
                "actions": ["批准", "拒绝"] if "review" in permissions else [],
            }
    state["permissions"] = [
        item for item in ("view", "edit", "review", "manage") if item in permissions
    ]
    state["revision"] = operator_revision(state)
    validate_operator_state(state)
    return state

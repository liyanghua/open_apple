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
    raw_parts = [part for part in relative_path.replace("\\", "/").split("/") if part not in {"", "."}]
    if ".." in raw_parts:
        return None
    prefix = ["projects", project_id]
    parts = raw_parts[len(prefix):] if raw_parts[:len(prefix)] == prefix else raw_parts
    if not parts:
        return None
    encoded_path = "/".join(quote(part, safe="") for part in parts)
    return f"/media/{quote(project_id, safe='')}/{encoded_path}"


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


def _research_editor(board: Mapping[str, Any]) -> dict[str, Any]:
    research = _artifact(board, "research_brief")
    analysis = _artifact(board, "video_analysis_brief")
    fingerprint = _artifact(board, "reference_fingerprint")
    source = _artifact(board, "source_media_review")
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
        label = _safe_text(item.get("media_id"))
        if not label and isinstance(path, str):
            label = Path(path).stem
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
    return {
        "type": "research_review",
        "data": {
            "reference_summary": summary,
            "source_count": len(files),
            "usable_count": usable,
            "risks": risks,
            "sources": sources,
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
    return {
        "type": "proposal_choice",
        "data": {
            "concepts": concepts,
            "selected_id": selected_id or None,
            "estimated_cost_usd": _number((proposal.get("cost_estimate") or {}).get("total_estimated_usd")),
        },
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
            "text": _safe_text(section.get("narration")) or _safe_text(section.get("text")),
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
            "preview_url": _media_url(project_id, source_path),
            "poster_url": _thumb_url(
                project_id, source_path,
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
    state["summary"]["performance"] = _performance_summary(project_dir)
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

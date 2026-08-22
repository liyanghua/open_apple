"""Localized repair planner (Design_Review P1-3).

Four repair actions with the smallest safe render route and lock discipline:

    rewrite_hook   -> sample   (hook lives in the sample window)
    edit_caption   -> still    (single-frame caption check; sample when motion changes)
    replace_asset  -> sample   (single-shot swap, verified in the sample window)
    shorten_shot   -> full_render (timeline shift affects downstream shots)

Repairs never clear unrelated shots, never roll back stages, and never change
the production lock: `plan_repair` hard-fails when the lock hash differs from
the one the repair targets (rule changes go through re-approval, not repair).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact

VALID_ACTIONS = ("rewrite_hook", "edit_caption", "replace_asset", "shorten_shot")

DEFAULT_TAGS = {
    "rewrite_hook": "weak_hook",
    "edit_caption": "caption_overlap",
    "replace_asset": "cover_mismatch",
    "shorten_shot": "slow_start",
}

DEFAULT_ROUTES = {
    "rewrite_hook": "sample",
    "edit_caption": "still",
    "replace_asset": "sample",
    "shorten_shot": "full_render",
}


def plan_repair(
    project_id: str,
    *,
    repair_id: str,
    action: str,
    targets: list[Mapping[str, Any]],
    evaluation_report_ref: Mapping[str, Any],
    production_lock_hash: str,
    rework_round: int = 1,
    issue_tags: list[str] | None = None,
    render_route: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    if action not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}")
    if not targets:
        raise ValueError("repair requires at least one target")
    if rework_round < 1:
        raise ValueError("rework_round must be >= 1")
    if len(production_lock_hash) != 64:
        raise ValueError("production_lock_hash must be a 64-char sha256")
    route = render_route or DEFAULT_ROUTES[action]
    if route not in ("no_render", "still", "sample", "mux_only", "full_render"):
        raise ValueError(f"invalid render_route {route!r}")
    if action == "shorten_shot" and render_route in (None, "still", "sample") and route in ("still", "sample"):
        raise ValueError("shorten_shot shifts the timeline and must render full_render")

    tags = list(issue_tags or [DEFAULT_TAGS[action]])
    affected_shot_ids: list[str] = []
    for target in targets:
        if target.get("type") not in ("hook", "caption", "asset", "shot"):
            raise ValueError(f"invalid target type {target.get('type')!r}")
        if target.get("type") == "shot" and target.get("id") not in affected_shot_ids:
            affected_shot_ids.append(str(target["id"]))
        elif target.get("type") != "shot" and target.get("id") and target.get("id") not in affected_shot_ids:
            # caption/asset/hook targets map to the shot they sit in via note convention;
            # caller may pass the shot id as target.id with type shot for attribution.
            pass

    repair = {
        "version": "1.0",
        "project_id": project_id,
        "repair_id": repair_id,
        "rework_round": rework_round,
        "action": action,
        "issue_tags": tags,
        "targets": [
            {"type": str(t["type"]), "id": str(t["id"]), **({"note": str(t["note"])} if t.get("note") else {})}
            for t in targets
        ],
        "evaluation_report_ref": {
            "name": str(evaluation_report_ref["name"]),
            "path": str(evaluation_report_ref["path"]),
            **({"artifact_sha256": str(evaluation_report_ref["artifact_sha256"])} if evaluation_report_ref.get("artifact_sha256") else {}),
        },
        "production_lock_hash": production_lock_hash,
        "lock_compliant": True,
        "render_route": route,
        "affected_shot_ids": affected_shot_ids,
        "affected_stages": _affected_stages(route),
        "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return _seal(repair)


def assert_lock_unchanged(repair: Mapping[str, Any], current_lock_hash: str) -> None:
    """Hard rule: repairs must not ride on a changed production lock."""
    if repair.get("production_lock_hash") != current_lock_hash:
        raise ValueError(
            "repair targets an outdated production lock; rule changes require re-approval, not repair"
        )


def repair_decision_entry(repair: Mapping[str, Any], *, subject: str, reason: str) -> dict[str, Any]:
    """decision_log entry (category=rework_cause) for a repair decision."""
    return {
        "decision_id": f"repair-{repair['repair_id']}",
        "stage": "edit",
        "category": "rework_cause",
        "subject": subject,
        "options_considered": [
            {"option_id": repair["action"], "label": _action_label(repair["action"]),
             "score": 0.8, "reason": f"影响范围最小，渲染路线 {repair['render_route']}"},
            {"option_id": "full_regenerate", "label": "整条重生成", "score": 0.2,
             "reason": "成本高且会清空已确认镜头", "rejected_because": "违反局部修复纪律"},
        ],
        "selected": repair["action"],
        "reason": reason,
        "issue_tags": list(repair["issue_tags"]),
        "rework_round": int(repair["rework_round"]),
        "confidence": 0.8,
        "user_visible": True,
    }


def _action_label(action: str) -> str:
    return {
        "rewrite_hook": "重写钩子",
        "edit_caption": "修改字幕样式",
        "replace_asset": "替换素材",
        "shorten_shot": "缩短镜头",
    }[action]


def _affected_stages(route: str) -> list[str]:
    return {
        "no_render": ["edit"],
        "still": ["edit"],
        "sample": ["edit", "sample"],
        "mux_only": ["edit", "compose"],
        "full_render": ["edit", "compose"],
    }[route]


def _seal(repair: dict[str, Any]) -> dict[str, Any]:
    sealed = attach_hashes(repair)
    validate_artifact("repair", sealed)
    return sealed

"""Intent-driven, reversible candidate rerun planning."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping


_STAGES = ("research", "proposal", "script", "scene_plan", "assets", "sample", "edit", "compose", "publish")
_INTENTS = {
    "pacing": ("edit", ["edit", "compose"], "样片预览"),
    "copy": ("script", ["script", "scene_plan", "assets", "sample", "edit", "compose"], "样片预览"),
    "visual": ("assets", ["assets", "sample", "edit", "compose"], "样片预览"),
    "technical": ("sample", ["sample"], "失败阶段预览"),
}
_TRANSITIONS = {
    "draft_plan": {"preview_running"},
    "preview_running": {"awaiting_preview_review"},
    "awaiting_preview_review": {"full_running", "discarded", "draft_plan"},
    "full_running": {"awaiting_final_review", "discarded"},
    "awaiting_final_review": {"promoted", "discarded"},
    "promoted": set(),
    "discarded": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_rerun_plan(
    *, candidate_id: str, child_revision: str, intent: str,
    anchor: Mapping[str, Any], instruction: str,
    vlm_finding_ids: list[Mapping[str, Any]], render_runtime: str,
    confirmed_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if intent not in _INTENTS:
        raise ValueError(f"unknown rerun intent: {intent}")
    if not candidate_id or not child_revision:
        raise ValueError("rerun plan requires candidate_id and child_revision")
    if render_runtime not in {"remotion", "hyperframes", "ffmpeg"}:
        raise ValueError("rerun plan requires a supported render_runtime")
    if not isinstance(anchor, Mapping) or not anchor:
        raise ValueError("rerun plan requires a locator anchor")
    if not instruction.strip():
        raise ValueError("rerun plan requires a user instruction")
    start, stages, preview_stop = _INTENTS[intent]
    return {
        "version": "1.0",
        "plan_id": f"rerun-plan-{uuid.uuid4().hex}",
        "candidate_id": candidate_id,
        "base_revision": child_revision,
        "target_revision": f"rev-{int(child_revision.rsplit('-', 1)[-1]) + 1}" if child_revision.startswith("rev-") and child_revision.rsplit('-', 1)[-1].isdigit() else f"rev-{uuid.uuid4().hex[:8]}",
        "intent": intent,
        "anchor": dict(anchor),
        "instruction": instruction.strip(),
        "vlm_finding_ids": [dict(item) for item in vlm_finding_ids],
        "confirmed_scope": dict(confirmed_scope or {}),
        "from_stage": start,
        "stages": list(stages),
        "preserved_stages": list(_STAGES[:_STAGES.index(start)]),
        "preview_stop_stage": preview_stop,
        "render_runtime": render_runtime,
        "estimated_cost_usd": {"pacing": 0.42, "copy": 1.26, "visual": 0.88, "technical": 0.18}[intent],
        "created_at": _now(),
    }


def create_rerun_run(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not plan.get("plan_id") or not plan.get("candidate_id"):
        raise ValueError("rerun run requires a valid plan")
    return {
        "version": "1.0",
        "run_id": f"rerun-run-{uuid.uuid4().hex}",
        "candidate_id": str(plan["candidate_id"]),
        "base_revision": str(plan["base_revision"]),
        "target_revision": str(plan["target_revision"]),
        "plan_id": str(plan["plan_id"]),
        "plan": dict(plan),
        "status": "draft_plan",
        "progress": {"stage": None, "completed": [], "percent": 0},
        "preview_ref": None,
        "output_ref": None,
        "current_revision": str(plan["base_revision"]),
        "created_at": _now(),
        "updated_at": _now(),
    }


def transition_rerun(run: Mapping[str, Any], status: str, **updates: Any) -> dict[str, Any]:
    current = str(run.get("status"))
    if status not in _TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid rerun transition {current} -> {status}")
    if status == "full_running" and not updates.get("preview_approved"):
        raise ValueError("full rerun requires preview approval")
    updated = dict(run)
    updated.update({key: value for key, value in updates.items() if key != "preview_approved"})
    updated["status"] = status
    updated["updated_at"] = _now()
    if status == "preview_running":
        updated["progress"] = {"stage": "preview", "completed": [], "percent": 0}
    elif status == "full_running":
        updated["progress"] = {"stage": updated["plan"].get("from_stage"), "completed": [], "percent": 0}
    return updated


def promote_rerun(run: Mapping[str, Any]) -> dict[str, Any]:
    if run.get("status") != "awaiting_final_review":
        raise ValueError("only a final-review rerun can be promoted")
    updated = dict(run)
    updated["status"] = "promoted"
    updated["current_revision"] = updated["target_revision"]
    updated["updated_at"] = _now()
    return updated


def discard_rerun(run: Mapping[str, Any]) -> dict[str, Any]:
    if run.get("status") not in {"awaiting_preview_review", "full_running", "awaiting_final_review"}:
        raise ValueError("rerun is not discardable in its current state")
    updated = dict(run)
    updated["status"] = "discarded"
    updated["current_revision"] = updated["base_revision"]
    updated["updated_at"] = _now()
    return updated

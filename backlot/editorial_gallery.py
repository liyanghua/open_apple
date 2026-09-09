"""Read-only source-led Editorial Gallery projection for batch candidates.

The gallery is deliberately a projection: candidate_batch, child checkpoints,
artifacts and render files remain the only sources of truth.  It never creates
sessions or mutates project state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backlot.batch_state import build_batch_review_data, child_snapshot
from backlot.operator_state import _media_url, _thumb_url
from backlot.state import load_board_state


STAGE_IDS = (
    "research", "proposal", "script", "scene_plan", "assets",
    "sample", "edit", "compose", "publish",
)
SUPPORTED_RUNTIME = "remotion"


class EditorialGalleryError(ValueError):
    code = "not_found"
    status_code = 404


def _safe_child_dir(batch_dir: Path, project_id: str) -> Path | None:
    if not isinstance(project_id, str) or not project_id or "/" in project_id or "\\" in project_id:
        return None
    root = batch_dir.parent.resolve()
    try:
        child = (root / project_id).resolve()
        child.relative_to(root)
    except (OSError, ValueError):
        return None
    return child if child.is_dir() else None


def _artifact(board: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = (board.get("artifacts") or {}).get(name)
    return value if isinstance(value, Mapping) else {}


def _child_artifact(board: Mapping[str, Any], child_dir: Path | None, name: str) -> Mapping[str, Any]:
    value = _artifact(board, name)
    if value or child_dir is None:
        return value
    try:
        raw = (child_dir / "artifacts" / f"{name}.json").read_text(encoding="utf-8")
        loaded = __import__("json").loads(raw)
    except (OSError, ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, Mapping) else {}


def _runtime(board: Mapping[str, Any], child_dir: Path | None = None) -> str | None:
    lock = _child_artifact(board, child_dir, "production_lock")
    locked = lock.get("locked_values") if isinstance(lock.get("locked_values"), Mapping) else {}
    decisions = _child_artifact(board, child_dir, "edit_decisions")
    return str(locked.get("render_runtime") or decisions.get("render_runtime") or "").strip() or None


def _fact_summary(board: Mapping[str, Any], child_dir: Path | None = None) -> dict[str, Any]:
    facts = _child_artifact(board, child_dir, "product_facts")
    claims = facts.get("claims") if isinstance(facts.get("claims"), list) else []
    return {
        "claims": [
            {
                "id": item.get("id"),
                "statement": item.get("statement") or item.get("text") or "",
                "evidence": item.get("evidence") or {},
            }
            for item in claims if isinstance(item, Mapping)
        ],
        "source": facts.get("source") or facts.get("source_url") or None,
    }


def _media(board: Mapping[str, Any], project_id: str, child_dir: Path, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    sample_url = snapshot.get("sample_url")
    final_url = snapshot.get("final_url")
    active = final_url or sample_url
    return {
        "sample_url": sample_url,
        "final_url": final_url,
        "poster_url": _thumb_url(project_id, active) if active else None,
        "preview_url": snapshot.get("preview_url"),
        "preview_kind": snapshot.get("preview_kind"),
    }


def _stages(snapshot: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_id = {
        str(item.get("stage_id")): item
        for item in (snapshot.get("stage_states") or [])
        if isinstance(item, Mapping) and item.get("stage_id")
    }
    statuses: dict[str, str] = {}
    stages = []
    for stage_id in STAGE_IDS:
        item = by_id.get(stage_id) or {}
        status = str(item.get("status") or "pending")
        statuses[stage_id] = status
        stages.append({
            "stage_id": stage_id,
            "status": status,
            "updated_at": item.get("updated_at"),
        })
    return stages, statuses


def _candidate_view(batch_dir: Path, view: Mapping[str, Any]) -> dict[str, Any]:
    project_id = str(view.get("project_id") or view.get("candidate_id") or "")
    child_dir = _safe_child_dir(batch_dir, project_id)
    snapshot = child_snapshot(batch_dir, child_dir) if child_dir is not None else {"exists": False}
    board = load_board_state(child_dir) if child_dir is not None and snapshot.get("exists") else {}
    stages, gate_statuses = _stages(snapshot)
    runtime = _runtime(board, child_dir)
    eligible = runtime == SUPPORTED_RUNTIME
    reason = None if eligible else "unsupported_runtime" if runtime else "runtime_unlocked"
    evaluation = (view.get("score") or {}).get("evaluation")
    return {
        "candidate_id": str(view.get("candidate_id") or ""),
        "project_id": project_id,
        "label": str(view.get("label") or view.get("candidate_id") or project_id),
        "direction": dict(view.get("direction") or {}),
        "status": str(view.get("status") or "planned"),
        "current_revision": snapshot.get("child_revision"),
        "child_revision": snapshot.get("child_revision"),
        "selected_for_edit": bool(view.get("candidate_id") in ((view.get("_selected_ids") or []))),
        "quality_conclusion": ((evaluation or {}).get("status") if isinstance(evaluation, Mapping) else None) or "missing",
        "gate_statuses": gate_statuses,
        "fact_summary": _fact_summary(board, child_dir),
        "media": _media(board, project_id, child_dir, snapshot) if child_dir is not None else {
            "sample_url": None, "final_url": None, "poster_url": None,
            "preview_url": None, "preview_kind": None,
        },
        "stages": stages,
        "evaluation": evaluation if isinstance(evaluation, Mapping) else None,
        "studio_eligibility": {
            "eligible": eligible,
            "runtime": runtime,
            "reason": reason,
            "can_create_v2_session": eligible,
        },
        "evidence": {"fact_summary": _fact_summary(board, child_dir), "evaluation": evaluation if isinstance(evaluation, Mapping) else None},
        "links": {"operator": f"/p/{project_id}"},
    }


def build_editorial_gallery(project_dir: str | Path) -> dict[str, Any]:
    """Build the read-only gallery for a cinematic-fast batch project."""
    project_dir = Path(project_dir).resolve()
    board = load_board_state(project_dir)
    artifacts = board.get("artifacts") if isinstance(board.get("artifacts"), Mapping) else {}
    batch = artifacts.get("candidate_batch")
    if not isinstance(batch, Mapping):
        raise EditorialGalleryError("该项目不是批量项目，无法打开编辑工作室")
    board = dict(board)
    board["_project_dir"] = project_dir
    review = build_batch_review_data(board, dict(batch))
    selected = [str(item) for item in ((review.get("selection") or {}).get("selected_candidate_ids") or [])]
    candidates = []
    for view in review.get("candidates") or []:
        enriched = dict(view)
        enriched["_selected_ids"] = selected
        candidates.append(_candidate_view(project_dir, enriched))
    return {
        "schema_version": "1.0",
        "batch_id": str(review.get("batch_id") or project_dir.name),
        "aggregate_revision": str(review.get("aggregate_revision") or ""),
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "consistency": str(review.get("consistency") or "degraded"),
        "batch": {
            "phase": str(review.get("phase") or "unknown"),
            "selection": dict(review.get("selection") or {}),
            "reports": dict(review.get("reports") or {}),
            "warnings": list(review.get("warnings") or []),
        },
        "candidates": candidates,
        "capabilities": {
            "plan_rerun": True,
            "execute_rerun": False,
            "openreel_edit": any(item["studio_eligibility"]["eligible"] for item in candidates),
        },
    }

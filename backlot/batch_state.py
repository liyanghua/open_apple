"""批级聚合状态（Batch_Workbench_Aggregate_State_Event_Contract v1.0）。

只读派生投影：candidate_batch 是批级索引/成员/预算/选择的事实来源；候选项目
的 checkpoint、stage rail、pending review、evaluation 与 sample trace 是候选
状态的事实来源。批动作必须先写事实来源再重算投影，绝不直接编辑投影字段。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backlot.state import load_board_state
from lib.artifact_hashing import semantic_sha256

BATCH_RAIL_PHASES = ("building", "sampling", "scoring", "selection", "editing", "publishing")
RAIL_LABELS = {
    "building": "建批",
    "sampling": "首轮样片",
    "scoring": "评分",
    "selection": "人工选择",
    "editing": "精剪",
    "publishing": "发布",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _child_revision_inputs(project_dir: Path, child_dir: Path) -> dict[str, Any] | None:
    """子项目 revision 输入：不存在 → None；project.json 缺失/损坏 → 抛异常。"""
    if not child_dir.is_dir():
        return None
    marker = child_dir / "project.json"
    if not marker.is_file():
        raise ValueError(f"candidate project marker missing: {child_dir.name}")
    marker_data = json.loads(marker.read_text(encoding="utf-8"))  # 损坏 → 抛异常
    if not isinstance(marker_data, dict) or not marker_data.get("project_id"):
        raise ValueError(f"candidate project marker invalid: {child_dir.name}")
    stages = {}
    for path in sorted(child_dir.glob("checkpoint_*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict) and raw.get("stage"):
            stages[str(raw["stage"])] = {
                "status": str(raw.get("status") or "unknown"),
                "version": max(0, int(raw.get("versions") or 0)),
                "updated_at": raw.get("timestamp"),
            }
    artifact_hashes = {}
    for name in ("evaluation_report.sample", "evaluation_report.final", "sample_execution_trace"):
        path = child_dir / "artifacts" / f"{name}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("semantic_sha256"):
                artifact_hashes[name] = data["semantic_sha256"]
    return {"stages": stages, "artifact_hashes": artifact_hashes}


def child_snapshot(project_dir: Path, child_dir: Path) -> dict[str, Any]:
    """读取一个候选子项目的快照（stages/reviews/评价/音轨/样片链接/revision）。"""
    snapshot: dict[str, Any] = {
        "exists": False,
        "corrupt": False,
        "child_revision": None,
        "stage_states": [],
        "pending_reviews": [],
        "preview_url": None,
        "evaluation": None,
        "audio_tracks": [],
    }
    inputs = None
    try:
        inputs = _child_revision_inputs(project_dir, child_dir)
    except Exception:
        snapshot["corrupt"] = True
        return snapshot
    if inputs is None:
        return snapshot
    snapshot["exists"] = True
    snapshot["child_revision"] = _sha256(_canonical(inputs))
    for stage_id, state in sorted(inputs["stages"].items()):
        snapshot["stage_states"].append({
            "stage_id": stage_id,
            "status": state["status"],
            "version": state["version"],
            "updated_at": state["updated_at"],
        })
    try:
        board = load_board_state(child_dir)
    except Exception:
        snapshot["corrupt"] = True
        return snapshot
    renders = (board.get("media") or {}).get("renders") if isinstance(board.get("media"), Mapping) else []
    render = next(
        (item for item in renders if isinstance(item, Mapping) and "sample" in str(item.get("path", "")).lower()),
        None,
    )
    if render:
        from backlot.operator_state import _media_url

        snapshot["preview_url"] = _media_url(child_dir.name, render.get("path"))
    artifacts = board.get("artifacts") if isinstance(board.get("artifacts"), Mapping) else {}
    eval_report = artifacts.get("evaluation_report.sample") or artifacts.get("evaluation_report")
    if isinstance(eval_report, Mapping) and eval_report.get("scope") == "sample":
        from backlot.operator_state import _evaluation_summary

        snapshot["evaluation"] = _evaluation_summary(eval_report)
    from backlot.operator_state import _audio_tracks

    snapshot["audio_tracks"] = _audio_tracks(artifacts.get("sample_execution_trace"))
    reviews_dir = child_dir / "operator" / "reviews"
    if reviews_dir.is_dir():
        for path in sorted(reviews_dir.glob("*.json")):
            try:
                review = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(review, dict) or review.get("status") != "awaiting_human":
                continue
            snapshot["pending_reviews"].append({
                "review_id": review.get("review_id"),
                "kind": review.get("kind"),
                "subject_version": review.get("subject_version"),
                "subject_hash": review.get("subject_hash"),
                "actions": ["批准", "拒绝"],
            })
    return snapshot


def candidate_phase_for(status: str, snapshot: dict[str, Any]) -> str:
    """候选相位机器值（契约 §2.2）；status 保留 candidate_batch 原始值。"""
    if snapshot.get("corrupt"):
        return "corrupt"
    if not snapshot.get("exists"):
        return "missing"
    stage_statuses = {item["stage_id"]: item["status"] for item in snapshot["stage_states"]}
    if stage_statuses.get("publish") == "completed":
        return "published"
    if stage_statuses.get("compose") == "completed":
        return "composed"
    if status == "selected_for_edit":
        return "selected"
    if stage_statuses.get("edit") == "completed":
        return "editing"
    if status == "evaluated":
        return "evaluated"
    if stage_statuses.get("sample") == "completed" or status == "sampled":
        return "sampled"
    if status == "failed":
        return "failed"
    if status == "in_progress":
        return "sampling"
    return "planned"


def compute_phase(
    views: list[dict[str, Any]],
    selected_ids: list[str],
    blocked_reasons: list[str],
) -> tuple[str, str]:
    """相位归约（契约 §3）+ 人读理由。失败/缺失候选不阻塞相位推进。"""
    alive = [view for view in views if view["candidate_phase"] not in {"failed", "missing", "corrupt"}]
    if not alive:
        return "blocked", "没有可选候选：" + ("；".join(blocked_reasons[:2]) or "全部失败/缺失")
    if "over_budget" in blocked_reasons:
        return "blocked", "预算超限，阻止继续推进"
    phases = {view["candidate_phase"] for view in alive}
    if not selected_ids:
        if phases <= {"evaluated"}:
            return "selection", "全部存活候选已评分，等待人工选择"
        if phases <= {"sampled", "evaluated", "failed"} and "sampled" in phases:
            return "scoring", "候选已有样片，等待评分"
        return "sampling", "至少一个候选尚未完成样片"
    selected = [view for view in views if view["candidate_id"] in selected_ids]
    if all(view["candidate_phase"] == "published" for view in selected):
        return "completed", "全部选中候选已发布"
    if all(view["candidate_phase"] in {"composed", "published"} for view in selected):
        return "publishing", "选中候选已完成成片，等待发布"
    return "editing", "选中候选进入精剪"


def aggregate_revision(
    batch_generation_id: str,
    candidates_summary: list[dict[str, Any]],
    selection: Mapping[str, Any],
    budget_summary: Mapping[str, Any],
) -> str:
    return _sha256(_canonical({
        "batch_generation_id": batch_generation_id,
        "candidates": candidates_summary,
        "selection": selection,
        "budget_summary": budget_summary,
    }))


def build_batch_review_data(board: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, Any]:
    """按契约 §2 组装 batch_review 载荷。"""
    project_dir = board.get("_project_dir") if isinstance(board.get("_project_dir"), Path) else Path.cwd()
    batch_id = str(batch.get("batch_id") or board.get("project_id") or "batch")
    candidates = [
        candidate for candidate in (batch.get("candidates") or [])
        if isinstance(candidate, Mapping)
    ]
    child_root = project_dir.parent
    warnings: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    read_inputs: dict[str, Any] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        project_id = str(candidate.get("project_id") or candidate_id)
        child_dir = child_root / project_id
        snapshot = child_snapshot(project_dir, child_dir)
        read_inputs[candidate_id] = snapshot.get("child_revision")
        phase = candidate_phase_for(str(candidate.get("status") or "planned"), snapshot)
        if phase == "missing":
            warnings.append({
                "code": "candidate_missing",
                "candidate_id": candidate_id,
                "description": f"候选项目 {project_id} 缺失",
                "suggested_action": "重新分叉该候选或从批中移除",
            })
        elif phase == "corrupt":
            warnings.append({
                "code": "candidate_corrupt",
                "candidate_id": candidate_id,
                "description": f"候选项目 {project_id} 制品损坏或不可读",
                "suggested_action": "检查候选项目 artifacts/checkpoint 后重试",
            })
        views.append({
            "candidate_id": candidate_id,
            "project_id": project_id,
            "label": str(candidate.get("label") or candidate_id),
            "direction": dict(candidate.get("direction") or {}),
            "status": str(candidate.get("status") or "planned"),
            "candidate_phase": phase,
            "child_revision": snapshot.get("child_revision"),
            "stage_states": snapshot.get("stage_states") or [],
            "pending_reviews": snapshot.get("pending_reviews") or [],
            "score": {
                "dimension_scores": candidate.get("dimension_scores"),
                "weighted_total": candidate.get("weighted_total"),
                "evaluation": snapshot.get("evaluation"),
            },
            "media": {
                "sample_url": snapshot.get("preview_url"),
                "audio_tracks": snapshot.get("audio_tracks") or [],
            },
            "cost": {
                "cost_usd": float(candidate.get("cost_usd") or 0),
                "attempts": int(candidate.get("attempts") or 0),
            },
            "links": {"project_page": f"/p/{project_id}"},
            "failure": {
                "failure": candidate.get("failure"),
                "technical": bool(candidate.get("failure")) and str(candidate.get("status")) == "failed",
            },
        })

    # 一致性：候选 revision 二次读取复核（unstable）；缺失/损坏/预算不一致（degraded）。
    consistency = "stable"
    for candidate_id, first_revision in read_inputs.items():
        project_id = next(
            (str(c.get("project_id") or c.get("candidate_id")) for c in candidates
             if str(c.get("candidate_id") or "") == candidate_id),
            candidate_id,
        )
        try:
            second = child_snapshot(project_dir, child_root / project_id).get("child_revision")
        except Exception:
            second = first_revision
        if second != first_revision:
            consistency = "unstable"
            break

    cost = board.get("cost") if isinstance(board.get("cost"), Mapping) else {}
    tracker_spent = cost.get("total_spent_usd")
    index_spent = sum(float(candidate.get("cost_usd") or 0) for candidate in candidates)
    budget = batch.get("budget") if isinstance(batch.get("budget"), Mapping) else {}
    max_cost = budget.get("max_cost_usd")
    source = "cost_tracker" if isinstance(tracker_spent, (int, float)) else "candidate_batch"
    spent = float(tracker_spent) if isinstance(tracker_spent, (int, float)) else index_spent
    # 缺失/损坏候选本身即降级（契约 §4/§6：不可静默删除候选）。
    if any(w["code"] in {"candidate_missing", "candidate_corrupt"} for w in warnings):
        if consistency != "unstable":
            consistency = "degraded"
    if isinstance(tracker_spent, (int, float)) and abs(float(tracker_spent) - index_spent) > 0.005:
        if consistency != "unstable":
            consistency = "degraded"
        warnings.append({
            "code": "budget_mismatch",
            "candidate_id": None,
            "description": f"cost_tracker（{tracker_spent}）与候选索引合计（{index_spent}）不一致",
            "suggested_action": "以 cost_tracker 为准，检查候选成本回写",
        })
    over_budget = isinstance(max_cost, (int, float)) and spent > float(max_cost)
    if over_budget:
        if consistency == "stable":
            consistency = "degraded"
        warnings.append({
            "code": "over_budget",
            "candidate_id": None,
            "description": f"已花费 {spent} 超过预算 {max_cost}",
            "suggested_action": "停止新付费调用或提高预算",
        })

    selection = batch.get("selection") if isinstance(batch.get("selection"), Mapping) else {}
    selected_ids = [str(item) for item in (selection.get("selected_candidate_ids") or [])]
    blocked_reasons = [w["code"] for w in warnings if w["code"] == "over_budget"]
    phase, phase_reason = compute_phase(views, selected_ids, blocked_reasons)

    budget_summary = {"spent_usd": spent, "over_budget": over_budget, "source": source}
    generation_id = "none"
    try:
        from backlot.project_commit import ProjectCommitStore

        store = ProjectCommitStore(project_dir)
        pointer = store._read_pointer()
        if isinstance(pointer, dict) and pointer.get("generation_id"):
            generation_id = str(pointer["generation_id"])
    except Exception:
        pass
    revision = aggregate_revision(
        generation_id,
        [
            {
                "candidate_id": view["candidate_id"],
                "project_id": view["project_id"],
                "child_revision": view["child_revision"],
                "candidate_phase": view["candidate_phase"],
            }
            for view in views
        ],
        {"selected_candidate_ids": selected_ids, "reason": selection.get("reason")},
        budget_summary,
    )

    concurrency = batch.get("concurrency") if isinstance(batch.get("concurrency"), Mapping) else {}
    active = [
        view["candidate_id"] for view in views
        if view["candidate_phase"] in {"forking", "sampling", "evaluating", "editing"}
    ]
    rail = []
    current_index = BATCH_RAIL_PHASES.index(phase) if phase in BATCH_RAIL_PHASES else 0
    for index, rail_phase in enumerate(BATCH_RAIL_PHASES):
        rail.append({
            "phase": rail_phase,
            "label": RAIL_LABELS[rail_phase],
            "status": "completed" if index < current_index else ("current" if index == current_index else "pending"),
        })
    if phase in {"completed", "blocked"}:
        rail = [{**item, "status": "completed"} for item in rail]

    gates: list[dict[str, Any]] = []
    for gate, stage_id, review_kind, label in (
        ("script", "script", "script_lock", "剧本确认"),
        ("assets", "assets", "creative_lock", "素材创意确认"),
        ("sample", "sample", "sample", "样片效果确认"),
    ):
        gate_candidates = []
        for view in views:
            stage_awaiting = any(
                item.get("stage_id") == stage_id and item.get("status") == "awaiting_human"
                for item in view["stage_states"]
            )
            review_awaiting = any(
                item.get("kind") == review_kind for item in view["pending_reviews"]
            )
            if stage_awaiting or review_awaiting:
                gate_candidates.append({
                    "candidate_id": view["candidate_id"],
                    "project_id": view["project_id"],
                })
        gates.append({
            "gate": gate,
            "label": label,
            "stage": stage_id,
            "candidates": gate_candidates,
        })

    return {
        "schema_version": "1.0",
        "kind": "batch_review",
        "batch_id": batch_id,
        "aggregate_revision": revision,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "consistency": consistency,
        "phase": phase,
        "phase_reason": phase_reason,
        "rail": rail,
        "candidates": views,
        "budget": {
            "max_cost_usd": float(max_cost) if isinstance(max_cost, (int, float)) else None,
            "spent_usd": spent,
            "reserved_usd": 0.0,
            "remaining_usd": (
                float(max_cost) - spent if isinstance(max_cost, (int, float)) else None
            ),
            "over_budget": over_budget,
            "source": source,
        },
        "concurrency": {
            "max_parallel": int(concurrency.get("max_parallel", 3)),
            "active_count": len(active),
            "active_candidate_ids": active,
        },
        "selection": {
            "selected_candidate_ids": selected_ids,
            "selected_at": selection.get("selected_at"),
            "reason": str(selection.get("reason") or ""),
            "eligible_candidate_ids": [
                view["candidate_id"] for view in views
                if view["status"] == "evaluated" and view["candidate_phase"] not in {"missing", "corrupt"}
            ],
        },
        "pending_gates": gates,
        "warnings": warnings,
    }

"""Candidate batch helpers (Design_Review P1-2).

The batch index coordinates the 5-candidate parallel montage mode: one shared
research pass, N forked candidates with independent projects, unified
scorecard comparison, and a user selection of 1-2 candidates for fine edit.
Selection is only valid for candidates that reached `evaluated`; the batch
never auto-publishes candidates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact

STATUS_FLOW = ("planned", "in_progress", "sampled", "evaluated", "failed", "selected_for_edit")
_TERMINAL_FAILED = "failed"

# 评审 #7：候选状态机。禁止跨状态跳变与伪造——
# - selected_for_edit 只能经 select_for_edit 进入（有 selection 记账）；
# - evaluated 必须携带 evaluation_report_ref，sampled 必须携带 sample_ref；
# - failed 之后只允许 retry 回到 in_progress。
_ALLOWED_TRANSITIONS = {
    "planned": {"in_progress", "failed"},
    "in_progress": {"sampled", "failed"},
    "sampled": {"evaluated", "failed"},
    "evaluated": {"failed"},
    "failed": {"in_progress"},
    "selected_for_edit": set(),
}


def create_candidate_batch(
    batch_id: str,
    *,
    shared_research_refs: list[Mapping[str, Any]],
    candidates: list[Mapping[str, Any]],
    differentiation_axes: Mapping[str, bool] | None = None,
    max_candidates: int = 5,
    max_parallel: int = 3,
    budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not shared_research_refs:
        raise ValueError("candidate_batch requires at least one shared research ref")
    if not candidates:
        raise ValueError("candidate_batch requires at least one candidate")
    if len(candidates) > max_candidates:
        raise ValueError(f"candidate_batch candidate count {len(candidates)} exceeds max_candidates {max_candidates}")

    normalized: list[dict[str, Any]] = []
    for item in candidates:
        status = item.get("status", "planned")
        if status not in STATUS_FLOW:
            raise ValueError(f"invalid candidate status {status!r}")
        normalized.append({
            "candidate_id": str(item["candidate_id"]),
            "label": str(item.get("label") or item["candidate_id"]),
            "direction": dict(item.get("direction") or {}),
            "project_id": str(item["project_id"]),
            "status": status,
            "sample_ref": item.get("sample_ref"),
            "evaluation_report_ref": item.get("evaluation_report_ref"),
            "cost_usd": float(item.get("cost_usd") or 0),
            "attempts": int(item.get("attempts") or 0),
            "failure": item.get("failure"),
            "notes": str(item.get("notes") or ""),
        })

    batch = {
        "version": "1.0",
        "batch_id": batch_id,
        "project_id": f"batch-{batch_id}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "shared_research": {
            "refs": [
                {"name": str(ref["name"]), "path": str(ref["path"]),
                 **({"artifact_sha256": str(ref["artifact_sha256"])} if ref.get("artifact_sha256") else {})}
                for ref in shared_research_refs
            ]
        },
        "concurrency": {"max_candidates": max_candidates, "max_parallel": max_parallel},
        "budget": (
            {
                "max_cost_usd": float(budget["max_cost_usd"]),
                "max_latency_minutes": float(budget["max_latency_minutes"]) if budget.get("max_latency_minutes") is not None else None,
                "max_retries_per_candidate": int(budget.get("max_retries_per_candidate", 2)),
            }
            if budget is not None else None
        ),
        "differentiation_axes": dict(differentiation_axes or {"hook": True, "pacing": True, "packaging": True, "audience": True, "duration": True}),
        "candidates": normalized,
        "selection": {"selected_candidate_ids": [], "selected_at": None, "reason": ""},
    }
    return _seal(batch)


def record_candidate_result(
    batch: Mapping[str, Any],
    candidate_id: str,
    *,
    status: str | None = None,
    sample_ref: Mapping[str, Any] | None = None,
    evaluation_report_ref: Mapping[str, Any] | None = None,
    cost_usd: float = 0.0,
    failure: str | None = None,
    is_retry: bool = False,
) -> dict[str, Any]:
    if status is not None and status not in STATUS_FLOW:
        raise ValueError(f"invalid candidate status {status!r}")
    budget = batch.get("budget") if isinstance(batch.get("budget"), Mapping) else None
    updated = dict(batch)
    # 评审 #6：max_cost_usd 是整批预算。用"当前批总额 + 本次增量"判断，
    # 而不是把每候选成本单独与整批上限比较（原实现每个候选都能花满整批预算）。
    batch_total_before = sum(float(item.get("cost_usd") or 0) for item in updated["candidates"])
    candidates = []
    for item in updated["candidates"]:
        if item["candidate_id"] != candidate_id:
            candidates.append(item)
            continue
        item = dict(item)
        current_status = item.get("status")
        if status is not None and status != current_status:
            if status == "selected_for_edit":
                raise ValueError(
                    f"candidate {candidate_id!r} cannot jump to selected_for_edit; "
                    "selection must go through select_for_edit"
                )
            if status not in _ALLOWED_TRANSITIONS.get(current_status, set()):
                raise ValueError(
                    f"invalid candidate status transition "
                    f"{current_status!r} -> {status!r} for {candidate_id!r}"
                )
        attempts = int(item.get("attempts") or 0)
        if is_retry and budget is not None and attempts + 1 > int(budget.get("max_retries_per_candidate", 2)):
            raise ValueError(
                f"candidate {candidate_id!r} retry budget exceeded "
                f"(attempts={attempts}, max_retries={budget.get('max_retries_per_candidate')})"
            )
        if is_retry:
            item["attempts"] = attempts + 1
        if status is not None:
            item["status"] = status
        if sample_ref is not None:
            item["sample_ref"] = dict(sample_ref)
        if evaluation_report_ref is not None:
            item["evaluation_report_ref"] = dict(evaluation_report_ref)
        effective_status = status if status is not None else current_status
        if effective_status == "evaluated" and not item.get("evaluation_report_ref"):
            raise ValueError(
                f"candidate {candidate_id!r} cannot reach evaluated without an evaluation_report_ref"
            )
        if effective_status == "sampled" and not item.get("sample_ref"):
            raise ValueError(
                f"candidate {candidate_id!r} cannot reach sampled without a sample_ref"
            )
        new_cost = float(item.get("cost_usd") or 0) + float(cost_usd or 0)
        if budget is not None and batch_total_before + float(cost_usd or 0) > float(budget.get("max_cost_usd", 0)):
            raise ValueError(
                f"batch cost {batch_total_before + float(cost_usd or 0)} would exceed "
                f"batch budget max_cost_usd {budget.get('max_cost_usd')}"
            )
        item["cost_usd"] = new_cost
        if failure is not None:
            item["failure"] = failure
        candidates.append(item)
    if not any(item["candidate_id"] == candidate_id for item in candidates):
        raise ValueError(f"unknown candidate_id {candidate_id!r}")
    updated["candidates"] = candidates
    return _seal(updated)


def select_for_edit(
    batch: Mapping[str, Any],
    candidate_ids: list[str],
    *,
    reason: str,
) -> dict[str, Any]:
    if not candidate_ids:
        raise ValueError("select_for_edit requires at least one candidate id")
    if len(candidate_ids) > 2:
        raise ValueError("select_for_edit accepts at most 2 candidates")
    by_id = {item["candidate_id"]: item for item in batch["candidates"]}
    for candidate_id in candidate_ids:
        item = by_id.get(candidate_id)
        if item is None:
            raise ValueError(f"unknown candidate_id {candidate_id!r}")
        if item["status"] != "evaluated":
            raise ValueError(f"candidate {candidate_id!r} must be evaluated before selection (status={item['status']})")
        if not item.get("evaluation_report_ref"):
            raise ValueError(
                f"candidate {candidate_id!r} is marked evaluated but has no evaluation_report_ref "
                "— forged status rejected"
            )
    updated = dict(batch)
    updated["candidates"] = [
        {**item, "status": "selected_for_edit" if item["candidate_id"] in candidate_ids else item["status"]}
        for item in updated["candidates"]
    ]
    updated["selection"] = {
        "selected_candidate_ids": list(candidate_ids),
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    return _seal(updated)


def _seal(batch: dict[str, Any]) -> dict[str, Any]:
    sealed = attach_hashes(batch)
    validate_artifact("candidate_batch", sealed)
    return sealed

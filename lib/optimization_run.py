"""Optimization run state machine (Autoresearch design §3.2, §6).

Python owns schema validation, score aggregation calls, state transitions,
fingerprint dedup, budget/plateau/iteration stop conditions and artifact
persistence. Candidate choice, failure interpretation and mutation selection
stay with the optimize-director skill — no second orchestrator.

Stop conditions (§6.3): max iterations, budget, plateau delta, duplicate
mutation fingerprint, exhausted mutations, or two passing final
confirmations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact

TERMINAL_STATUSES = {"passed", "exhausted", "blocked", "failed"}

_TERMINAL_STOP_REASONS = {
    "confirmations_passed",
    "max_iterations",
    "budget_exceeded",
    "plateau",
    "mutation_fingerprint_duplicate",
    "all_mutations_exhausted",
    "no_dimension_improvement",
    "user_blocked",
    "execution_failed",
}


def _seal(run: dict[str, Any]) -> dict[str, Any]:
    run["updated_at"] = datetime.now(timezone.utc).isoformat()
    sealed = attach_hashes(run)
    validate_artifact("optimization_run", sealed)
    return sealed


def _require_active(run: Mapping[str, Any]) -> None:
    if run["status"] in TERMINAL_STATUSES:
        raise ValueError(
            f"optimization_run {run['run_id']!r} is terminal ({run['status']}): "
            f"{run.get('stop_reason')}"
        )


def policy_snapshot(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the thresholds/limits of a policy into a run snapshot."""
    return {
        "rubric_version": str(policy["rubric_version"]),
        "per_dimension_min": float(policy["per_dimension_min"]),
        "weighted_total_min": float(policy["weighted_total_min"]),
        "required_dimensions": [str(item) for item in policy["required_dimensions"]],
        "weights": {str(k): float(v) for k, v in policy["weights"].items()},
        "max_iterations": int(policy["max_iterations"]),
        "max_retries_per_candidate": int(policy["max_retries_per_candidate"]),
        "max_total_cost_usd": float(policy["max_total_cost_usd"]),
        "plateau_delta": float(policy["plateau_delta"]),
        "confirmation_runs": int(policy["confirmation_runs"]),
    }


def create_optimization_run(
    run_id: str,
    project_id: str,
    *,
    policy: Mapping[str, Any],
    policy_ref: Mapping[str, Any],
    phase: str = "sample",
    baseline_candidate_id: str | None = None,
) -> dict[str, Any]:
    """Create a planned run with a frozen policy snapshot."""
    run = {
        "version": "1.0",
        "run_id": run_id,
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "planned",
        "phase": phase,
        "baseline_candidate_id": baseline_candidate_id,
        "best_candidate_id": None,
        "iteration": 0,
        "policy_ref": dict(policy_ref),
        "policy_snapshot": policy_snapshot(policy),
        "history": [],
        "confirmation": {
            "required_runs": int(policy["confirmation_runs"]),
            "completed_runs": 0,
            "passed": False,
            "runs": [],
        },
        "stop_reason": None,
    }
    return _seal(run)


def begin_iteration(
    run: Mapping[str, Any],
    candidate_ids: list[str],
    *,
    phase: str | None = None,
) -> dict[str, Any]:
    """Enter the next sample-search iteration; stop when max_iterations hit."""
    _require_active(run)
    updated = {**run, "history": list(run["history"])}
    snapshot = updated["policy_snapshot"]
    next_iteration = int(updated["iteration"]) + 1
    if next_iteration > int(snapshot["max_iterations"]):
        updated["status"] = "exhausted"
        updated["stop_reason"] = "max_iterations"
        return _seal(updated)
    updated["iteration"] = next_iteration
    updated["status"] = "running"
    if phase:
        updated["phase"] = phase
    return _seal(updated)


def _verify_pass(
    snapshot: Mapping[str, Any],
    *,
    weighted_total: float | None,
    failure_dimensions: list[str] | None,
    dimension_scores: Mapping[str, Any] | None,
) -> None:
    """按冻结 policy_snapshot 重算达标性（评审 P1 修复）。

    accepted / confirmation passed 不能只信调用方：必须总分 >= 阈值、无失败
    维度、required 维度齐全且每维 >= 单维阈值，否则拒绝。
    """
    reasons: list[str] = []
    if weighted_total is None or float(weighted_total) < float(snapshot["weighted_total_min"]):
        reasons.append(
            f"weighted_total {weighted_total} 低于阈值 {snapshot['weighted_total_min']}"
        )
    if failure_dimensions:
        reasons.append(f"存在失败维度 {list(failure_dimensions)}")
    if dimension_scores is None:
        reasons.append("缺少 dimension_scores，无法验证单维达标")
    else:
        required = [str(item) for item in snapshot["required_dimensions"]]
        missing = [dim for dim in required if dim not in dimension_scores]
        if missing:
            reasons.append(f"缺少必评维度 {missing}")
        low = [
            dim for dim in required
            if dim in dimension_scores
            and float(dimension_scores[dim]) < float(snapshot["per_dimension_min"])
        ]
        if low:
            reasons.append(
                f"维度低于单维阈值 {snapshot['per_dimension_min']}: {low}"
            )
    if reasons:
        raise ValueError(
            "optimization 达标校验失败（accepted/confirmation passed 必须以冻结阈值重算）: "
            + "; ".join(reasons)
        )


def record_iteration(
    run: Mapping[str, Any],
    *,
    candidate_ids: list[str],
    winner: str | None,
    outcome: str,
    weighted_total: float | None,
    failure_dimensions: list[str] | None = None,
    dimension_scores: Mapping[str, Any] | None = None,
    mutation_fingerprint: str | None = None,
    technical_failures: list[str] | None = None,
) -> dict[str, Any]:
    """Append one iteration to history; only verified-passing winners become best."""
    _require_active(run)
    if outcome not in {"accepted", "rejected", "technical_failure"}:
        raise ValueError(f"invalid iteration outcome {outcome!r}")
    if winner is not None and winner not in candidate_ids:
        raise ValueError(f"winner {winner!r} not among candidate_ids")
    updated = {**run, "history": [dict(item) for item in run["history"]]}
    entry = {
        "iteration": int(updated["iteration"]),
        "candidate_ids": [str(item) for item in candidate_ids],
        "winner": winner,
        "outcome": outcome,
        "weighted_total": float(weighted_total) if weighted_total is not None else None,
        "failure_dimensions": [str(item) for item in (failure_dimensions or [])],
        "mutation_fingerprint": mutation_fingerprint,
    }
    if technical_failures:
        entry["technical_failures"] = [str(item) for item in technical_failures]
    updated["history"].append(entry)
    # 失败候选不会成为 best（设计 §10.2）；accepted 必须通过冻结阈值重算
    # （评审 P1 修复：不能只信调用方的 outcome="accepted"）。
    if outcome == "accepted":
        if winner is None:
            raise ValueError("accepted outcome requires a winner")
        _verify_pass(
            updated["policy_snapshot"],
            weighted_total=weighted_total,
            failure_dimensions=failure_dimensions,
            dimension_scores=dimension_scores,
        )
        updated["best_candidate_id"] = winner
        updated["phase"] = "final"
    return _seal(updated)


def mutation_seen(run: Mapping[str, Any], fingerprint: str) -> bool:
    """True when this mutation fingerprint was already executed this run."""
    if not fingerprint:
        return False
    return any(
        entry.get("mutation_fingerprint") == fingerprint for entry in run["history"]
    )


def plateau_reached(run: Mapping[str, Any]) -> bool:
    """True when the last two scored iterations improved by < plateau_delta."""
    scored = [
        entry
        for entry in run["history"]
        if entry.get("weighted_total") is not None
    ]
    if len(scored) < 2:
        return False
    delta = float(run["policy_snapshot"]["plateau_delta"])
    previous, latest = scored[-2]["weighted_total"], scored[-1]["weighted_total"]
    return float(latest) - float(previous) < delta


def check_budget(run: Mapping[str, Any], spent_usd: float) -> bool:
    """True when the run's frozen budget is exceeded (0 = project-budget-managed)."""
    limit = float(run["policy_snapshot"]["max_total_cost_usd"])
    if limit <= 0:
        return False
    return float(spent_usd) > limit


def start_confirmation(
    run: Mapping[str, Any],
    candidate_id: str,
    *,
    reset: bool = False,
) -> dict[str, Any]:
    """Enter the final-confirmation phase for the accepted best candidate."""
    _require_active(run)
    if candidate_id != run.get("best_candidate_id"):
        raise ValueError(
            f"confirmation candidate {candidate_id!r} is not the accepted best "
            f"({run.get('best_candidate_id')!r})"
        )
    updated = {**run}
    if reset:
        updated["confirmation"] = {
            "required_runs": int(run["confirmation"]["required_runs"]),
            "completed_runs": 0,
            "passed": False,
            "runs": [],
        }
    updated["status"] = "awaiting_confirmation"
    updated["phase"] = "final"
    return _seal(updated)


def record_confirmation(
    run: Mapping[str, Any],
    *,
    passed: bool,
    weighted_total: float | None,
    failure_dimensions: list[str] | None = None,
    dimension_scores: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one confirmation run; two passes flip the run to passed.

    评审 P1 修复：passed=True 必须通过冻结阈值重算（总分/失败维度/required
    维度齐全）；任一次失败立即切回 running 进入 repair，不再执行下一次确认。
    """
    if run["status"] != "awaiting_confirmation":
        raise ValueError(
            f"record_confirmation requires status awaiting_confirmation, got {run['status']!r}"
        )
    updated = {**run}
    if passed:
        _verify_pass(
            updated["policy_snapshot"],
            weighted_total=weighted_total,
            failure_dimensions=failure_dimensions,
            dimension_scores=dimension_scores,
        )
    confirmation = {
        **updated["confirmation"],
        "runs": [dict(item) for item in updated["confirmation"]["runs"]],
    }
    index = len(confirmation["runs"]) + 1
    confirmation["runs"].append({
        "index": index,
        "passed": bool(passed),
        "weighted_total": float(weighted_total) if weighted_total is not None else None,
        "failure_dimensions": [str(item) for item in (failure_dimensions or [])],
    })
    confirmation["completed_runs"] = len(confirmation["runs"])
    updated["confirmation"] = confirmation
    if not passed:
        # 任一次确认失败：立即回到 running，仅针对失败维度生成 repair（§6.2），
        # 不再执行下一次确认。
        confirmation["passed"] = False
        updated["status"] = "running"
        return _seal(updated)
    if confirmation["completed_runs"] >= confirmation["required_runs"]:
        confirmation["passed"] = all(item["passed"] for item in confirmation["runs"])
        updated["status"] = "passed"
        updated["stop_reason"] = "confirmations_passed"
    return _seal(updated)


def stop_run(run: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """Stop an active run; exhausted = best candidate may be shown, not auto-approved."""
    _require_active(run)
    if reason not in _TERMINAL_STOP_REASONS:
        raise ValueError(f"invalid stop reason {reason!r}")
    updated = {**run}
    if reason == "user_blocked":
        updated["status"] = "blocked"
    elif reason == "execution_failed":
        updated["status"] = "failed"
    else:
        updated["status"] = "exhausted"
    updated["stop_reason"] = reason
    return _seal(updated)


def set_exhausted_best(run: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    """At exhaustion, best_candidate may point at the highest scorer (§6.3) —
    it is displayed to the user but never marked as automatically passed."""
    if run["status"] != "exhausted":
        raise ValueError("set_exhausted_best only applies to exhausted runs")
    updated = {**run, "best_candidate_id": candidate_id}
    return _seal(updated)

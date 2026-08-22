"""Unified optimization score aggregation (Autoresearch design §2, §3.4).

The VLM judge stays a raw scorer; this module is the single place that turns
dimension scores into a weighted total, applies the frozen policy thresholds,
and decides pass/fail. Strict fail-closed behaviour:

- scores outside [0, 10] or non-numeric are REJECTED (ValueError), never clamped;
- missing/skipped required dimensions fail the candidate (listed in
  failure_dimensions), never silently dropped;
- rubric_version must match the policy or the report is not comparable (ValueError);
- L1a hard_gate.pass and coverage are preconditions of `passed`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact

DIMENSION_IDS = (
    "hook_clarity",
    "reference_mechanism_fidelity",
    "product_evidence",
    "rhythm_pacing",
    "visual_coherence",
    "caption_readability",
    "audio_quality",
    "commercial_originality",
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "hook_clarity": 0.15,
    "reference_mechanism_fidelity": 0.20,
    "product_evidence": 0.20,
    "rhythm_pacing": 0.15,
    "visual_coherence": 0.10,
    "caption_readability": 0.10,
    "audio_quality": 0.05,
    "commercial_originality": 0.05,
}

DEFAULT_RUBRIC = "ecommerce-remix-v1.0"


def build_default_optimization_policy(
    project_id: str,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a sealed, schema-valid optimization policy (人工 review 优先：
    enabled=False 默认，启用自动循环前必须人工批准 rubric/阈值/预算)."""
    policy: dict[str, Any] = {
        "version": "1.0",
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "enabled": False,
        "score_scale": "0-10",
        "rubric_version": DEFAULT_RUBRIC,
        "per_dimension_min": 8.0,
        "weighted_total_min": 8.5,
        "required_dimensions": list(DIMENSION_IDS),
        "weights": dict(DEFAULT_WEIGHTS),
        "beam_width": 5,
        "max_parallel": 3,
        "max_iterations": 6,
        "max_retries_per_candidate": 2,
        "confirmation_runs": 2,
        "max_total_cost_usd": 0.0,
        "plateau_delta": 0.1,
    }
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                policy[key] = value
    sealed = attach_hashes(policy)
    validate_artifact("optimization_policy", sealed)
    return sealed


def _strict_score(dimension_id: str, value: Any) -> float:
    """Reject (never clamp) a score that is not a number in [0, 10]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"optimization scoring: dimension {dimension_id!r} score is not numeric: {value!r}"
        )
    score = float(value)
    if score < 0.0 or score > 10.0:
        raise ValueError(
            f"optimization scoring: dimension {dimension_id!r} score {score} outside [0, 10] — report rejected"
        )
    return score


def aggregate_optimization_scores(
    policy: Mapping[str, Any],
    dimensions: Mapping[str, Any],
    *,
    hard_gate_pass: bool,
    coverage_sufficient: bool,
    rubric_version: str,
    run_id: str | None = None,
    candidate_id: str | None = None,
    iteration: int | None = None,
    parent_candidate_id: str | None = None,
    confirmation_index: int | None = None,
    judge_releasable: bool = False,
) -> dict[str, Any]:
    """Aggregate raw dimension scores into the evaluation_report.optimization block.

    Exact boundaries (design §2.2): 任一维度 7.99 失败；全部 >=8.0 但总分
    8.49 失败；8.50 通过；缺失 required dimension 失败；非法分数拒绝。
    judge_releasable=False（校准不足）时只能 shadow mode：分数照算，但
    passed 恒为 False 并记录 judge_not_calibrated。
    """
    if str(policy.get("rubric_version") or "") != str(rubric_version):
        raise ValueError(
            f"optimization scoring: rubric mismatch (policy={policy.get('rubric_version')!r}, "
            f"report={rubric_version!r}) — scores are not comparable"
        )
    if policy.get("enabled") is not True:
        raise ValueError(
            "optimization scoring: policy.enabled=false — 仅生成比较报告，不宣称自动达标"
        )

    weights = {str(k): float(v) for k, v in (policy.get("weights") or {}).items()}
    required = [str(item) for item in policy.get("required_dimensions") or []]
    missing_weight_dims = [dim for dim in required if dim not in weights]
    if missing_weight_dims:
        raise ValueError(
            f"optimization scoring: required dimensions missing weights: {missing_weight_dims}"
        )
    per_dimension_min = float(policy["per_dimension_min"])
    weighted_total_min = float(policy["weighted_total_min"])

    dimension_scores: dict[str, float] = {}
    failure_dimensions: list[str] = []
    missing_dimensions: list[str] = []
    for dimension_id in required:
        if dimension_id not in dimensions:
            missing_dimensions.append(dimension_id)
            failure_dimensions.append(dimension_id)
            continue
        score = _strict_score(dimension_id, dimensions[dimension_id])
        dimension_scores[dimension_id] = score
        if score < per_dimension_min:
            failure_dimensions.append(dimension_id)

    weighted_total: float | None
    if missing_dimensions:
        # 缺维时总分不可计算，不具可比较性；passed 必为 False。
        weighted_total = None
    else:
        weighted_total = sum(
            weights[dim] * dimension_scores[dim] for dim in required
        )

    if not judge_releasable:
        # 校准不足：只能 shadow mode，分数照算但不得宣称自动达标。
        failure_dimensions.append("judge_not_calibrated")

    passed = (
        hard_gate_pass
        and coverage_sufficient
        and not failure_dimensions
        and weighted_total is not None
        and weighted_total >= weighted_total_min
    )

    return {
        "run_id": run_id,
        "candidate_id": candidate_id,
        "iteration": iteration,
        "parent_candidate_id": parent_candidate_id,
        "dimension_scores": dimension_scores,
        "weighted_total": round(weighted_total, 2) if weighted_total is not None else None,
        "thresholds": {
            "per_dimension_min": per_dimension_min,
            "weighted_total_min": weighted_total_min,
        },
        "passed": passed,
        "failure_dimensions": sorted(set(failure_dimensions)),
        "confirmation_index": confirmation_index,
    }

"""优化分数聚合边界测试（Autoresearch §10.1）。"""

from __future__ import annotations

import pytest

from lib.optimization_scoring import (
    DEFAULT_WEIGHTS,
    DIMENSION_IDS,
    aggregate_optimization_scores,
    build_default_optimization_policy,
)


def _policy(**overrides):
    return build_default_optimization_policy("p-opt", overrides={"enabled": True, **overrides})


def _dims(**scores):
    base = {dim: 8.5 for dim in DIMENSION_IDS}
    base.update(scores)
    return base


def _aggregate(dims, *, hard_gate_pass=True, coverage=True, **kwargs):
    kwargs.setdefault("judge_releasable", True)  # 测试默认已校准
    return aggregate_optimization_scores(
        _policy(),
        dims,
        hard_gate_pass=hard_gate_pass,
        coverage_sufficient=coverage,
        rubric_version="ecommerce-remix-v1.0",
        **kwargs,
    )


def test_all_8_5_passes_exactly_at_threshold():
    block = _aggregate(_dims())
    assert block["weighted_total"] == 8.5
    assert block["passed"] is True
    assert block["failure_dimensions"] == []


def test_single_dimension_7_99_fails():
    block = _aggregate(_dims(hook_clarity=7.99))
    assert block["passed"] is False
    assert "hook_clarity" in block["failure_dimensions"]


def test_all_dims_pass_but_total_8_49_fails():
    # hook_clarity 8.0，其余 8.5 → 总分 8.425 < 8.5
    block = _aggregate(_dims(hook_clarity=8.0))
    assert block["passed"] is False
    assert block["weighted_total"] < 8.5


def test_total_8_50_boundary_passes():
    # 所有维度 8.5 → 8.5 通过（阈值含等号）
    block = _aggregate(_dims())
    assert block["passed"] is True


def test_invalid_score_is_rejected_not_clamped():
    with pytest.raises(ValueError, match="outside \\[0, 10\\]"):
        _aggregate(_dims(hook_clarity=10.5))
    with pytest.raises(ValueError, match="not numeric"):
        _aggregate(_dims(hook_clarity="8.5"))
    with pytest.raises(ValueError, match="not numeric"):
        _aggregate(_dims(hook_clarity=None))


def test_missing_required_dimension_fails_with_uncomputable_total():
    dims = _dims()
    del dims["product_evidence"]
    block = _aggregate(dims)
    assert block["passed"] is False
    assert block["weighted_total"] is None
    assert "product_evidence" in block["failure_dimensions"]


def test_rubric_version_mismatch_rejected():
    with pytest.raises(ValueError, match="rubric mismatch"):
        aggregate_optimization_scores(
            _policy(),
            _dims(),
            hard_gate_pass=True,
            coverage_sufficient=True,
            rubric_version="l3-v1.0",
        )


def test_disabled_policy_cannot_claim_auto_pass():
    policy = build_default_optimization_policy("p-opt")  # enabled=False
    with pytest.raises(ValueError, match="enabled=false"):
        aggregate_optimization_scores(
            policy,
            _dims(),
            hard_gate_pass=True,
            coverage_sufficient=True,
            rubric_version="ecommerce-remix-v1.0",
        )


def test_l1a_or_coverage_failure_blocks_pass():
    assert _aggregate(_dims(), hard_gate_pass=False)["passed"] is False
    assert _aggregate(_dims(), coverage=False)["passed"] is False


def test_block_carries_lineage_and_thresholds():
    block = _aggregate(
        _dims(),
        run_id="r1",
        candidate_id="candidate-03",
        iteration=2,
        parent_candidate_id="candidate-01",
        confirmation_index=1,
    )
    assert block["run_id"] == "r1"
    assert block["candidate_id"] == "candidate-03"
    assert block["iteration"] == 2
    assert block["parent_candidate_id"] == "candidate-01"
    assert block["confirmation_index"] == 1
    assert block["thresholds"] == {"per_dimension_min": 8.0, "weighted_total_min": 8.5}


def test_default_weights_cover_all_dimensions():
    assert set(DEFAULT_WEIGHTS) == set(DIMENSION_IDS)
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_uncalibrated_judge_forces_shadow_mode():
    """校准不足：分数照算，但 passed=False 且记录 judge_not_calibrated。"""
    block = _aggregate(_dims(), judge_releasable=False)
    assert block["weighted_total"] == 8.5
    assert block["passed"] is False
    assert "judge_not_calibrated" in block["failure_dimensions"]

"""optimization_run 状态机测试（Autoresearch §6、§10.2）。"""

from __future__ import annotations

import pytest

from lib.optimization_run import (
    begin_iteration,
    check_budget,
    create_optimization_run,
    mutation_seen,
    plateau_reached,
    record_confirmation,
    record_iteration,
    set_exhausted_best,
    start_confirmation,
    stop_run,
)
from lib.optimization_scoring import DIMENSION_IDS, build_default_optimization_policy
from schemas.artifacts import validate_artifact


def _policy(**overrides):
    return build_default_optimization_policy("p-opt", overrides={"enabled": True, **overrides})


def _run(**overrides):
    policy = _policy(**overrides)
    return create_optimization_run(
        "autoresearch-mix-001",
        "p-opt",
        policy=policy,
        policy_ref={"name": "optimization_policy", "path": "artifacts/optimization_policy.json"},
    )


def _candidates(n=5):
    return [f"candidate-{i:02d}" for i in range(1, n + 1)]


def _scores(value=8.5):
    """全部 required 维度达标的分数集（8.5 ≥ 单维阈值 8.0）。"""
    return {dim: value for dim in DIMENSION_IDS}


def test_create_and_begin_iteration():
    run = _run()
    run = begin_iteration(run, _candidates())
    assert run["status"] == "running"
    assert run["iteration"] == 1


def test_max_iterations_exhausts():
    run = _run(max_iterations=2)
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner=None,
                           outcome="rejected", weighted_total=7.5,
                           failure_dimensions=["hook_clarity"])
    run = begin_iteration(run, _candidates())
    assert run["iteration"] == 2
    run = begin_iteration(run, _candidates())  # 超出 max_iterations
    assert run["status"] == "exhausted"
    assert run["stop_reason"] == "max_iterations"


def test_rejected_candidate_never_becomes_best():
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner="candidate-01",
                           outcome="rejected", weighted_total=7.9,
                           failure_dimensions=["product_evidence"])
    assert run["best_candidate_id"] is None  # 失败候选不会成为 best


def test_accepted_candidate_becomes_best_and_enters_final():
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                           outcome="accepted", weighted_total=8.63,
                           dimension_scores=_scores())
    assert run["best_candidate_id"] == "candidate-03"
    assert run["phase"] == "final"


def test_accepted_without_meeting_thresholds_is_rejected():
    """评审 P1：accepted 必须按冻结阈值重算，不能只信调用方。"""
    run = _run()
    run = begin_iteration(run, _candidates())
    # 总分不达标
    with pytest.raises(ValueError, match="达标校验失败"):
        record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                         outcome="accepted", weighted_total=7.9, dimension_scores=_scores())
    # 带失败维度
    with pytest.raises(ValueError, match="达标校验失败"):
        record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                         outcome="accepted", weighted_total=8.63,
                         dimension_scores=_scores(), failure_dimensions=["hook_clarity"])
    # 缺 dimension_scores
    with pytest.raises(ValueError, match="缺少 dimension_scores"):
        record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                         outcome="accepted", weighted_total=8.63)
    # 缺必评维度
    partial = _scores()
    del partial["product_evidence"]
    with pytest.raises(ValueError, match="缺少必评维度"):
        record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                         outcome="accepted", weighted_total=8.63, dimension_scores=partial)
    # 单维低于阈值
    low = _scores()
    low["hook_clarity"] = 7.99
    with pytest.raises(ValueError, match="单维阈值"):
        record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                         outcome="accepted", weighted_total=8.63, dimension_scores=low)


def test_winner_must_be_among_candidate_ids():
    run = _run()
    run = begin_iteration(run, _candidates())
    with pytest.raises(ValueError, match="not among candidate_ids"):
        record_iteration(run, candidate_ids=_candidates(), winner="candidate-99",
                         outcome="accepted", weighted_total=8.6, dimension_scores=_scores())


def test_mutation_fingerprint_dedup():
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner=None,
                           outcome="rejected", weighted_total=7.5,
                           mutation_fingerprint="sha256:abc")
    assert mutation_seen(run, "sha256:abc") is True
    assert mutation_seen(run, "sha256:def") is False


def test_plateau_detection():
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner=None,
                           outcome="rejected", weighted_total=7.50)
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner=None,
                           outcome="rejected", weighted_total=7.55)  # +0.05 < plateau_delta 0.1
    assert plateau_reached(run) is True
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner=None,
                           outcome="rejected", weighted_total=8.0)  # +0.45 ≥ 0.1
    assert plateau_reached(run) is False


def test_budget_check():
    run = _run(max_total_cost_usd=5.0)
    assert check_budget(run, 4.9) is False
    assert check_budget(run, 5.1) is True
    run_unlimited = _run(max_total_cost_usd=0.0)
    assert check_budget(run_unlimited, 100.0) is False  # 0 = 由项目预算注入


def test_confirmation_requires_best_candidate():
    run = _run()
    run = begin_iteration(run, _candidates())
    with pytest.raises(ValueError, match="not the accepted best"):
        start_confirmation(run, "candidate-02")


def test_two_passing_confirmations_pass_the_run():
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                           outcome="accepted", weighted_total=8.63,
                           dimension_scores=_scores())
    run = start_confirmation(run, "candidate-03")
    assert run["status"] == "awaiting_confirmation"
    run = record_confirmation(run, passed=True, weighted_total=8.7, dimension_scores=_scores())
    assert run["status"] == "awaiting_confirmation"  # 还需第二次
    run = record_confirmation(run, passed=True, weighted_total=8.8, dimension_scores=_scores())
    assert run["status"] == "passed"
    assert run["stop_reason"] == "confirmations_passed"
    assert run["confirmation"]["passed"] is True


def test_confirmation_passed_also_reverified():
    """评审 P1：confirmation passed=True 同样按冻结阈值重算。"""
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                           outcome="accepted", weighted_total=8.63,
                           dimension_scores=_scores())
    run = start_confirmation(run, "candidate-03")
    with pytest.raises(ValueError, match="达标校验失败"):
        record_confirmation(run, passed=True, weighted_total=7.9, dimension_scores=_scores())
    with pytest.raises(ValueError, match="达标校验失败"):
        record_confirmation(run, passed=True, weighted_total=8.7, dimension_scores=_scores(),
                            failure_dimensions=["audio_quality"])


def test_failed_confirmation_returns_to_running_for_repair():
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                           outcome="accepted", weighted_total=8.63,
                           dimension_scores=_scores())
    run = start_confirmation(run, "candidate-03")
    run = record_confirmation(run, passed=True, weighted_total=8.7, dimension_scores=_scores())
    run = record_confirmation(run, passed=False, weighted_total=8.2,
                              failure_dimensions=["product_evidence"])
    assert run["status"] == "running"  # 任一次失败 → 回 running 走 repair
    assert run["confirmation"]["passed"] is False
    assert run["confirmation"]["runs"][-1]["failure_dimensions"] == ["product_evidence"]


def test_first_confirmation_failure_stops_immediately():
    """评审 P1：第一次确认失败即切回 running，不再执行下一次确认。"""
    run = _run()
    run = begin_iteration(run, _candidates())
    run = record_iteration(run, candidate_ids=_candidates(), winner="candidate-03",
                           outcome="accepted", weighted_total=8.63,
                           dimension_scores=_scores())
    run = start_confirmation(run, "candidate-03")
    run = record_confirmation(run, passed=False, weighted_total=8.2,
                              failure_dimensions=["product_evidence"])
    assert run["status"] == "running"
    assert run["confirmation"]["completed_runs"] == 1
    # 已切回 running：下一次确认必须重新 start_confirmation
    with pytest.raises(ValueError, match="awaiting_confirmation"):
        record_confirmation(run, passed=True, weighted_total=8.8, dimension_scores=_scores())


def test_stop_reasons_and_exhausted_best():
    run = _run()
    run = begin_iteration(run, _candidates())
    run = stop_run(run, "budget_exceeded")
    assert run["status"] == "exhausted"
    run = set_exhausted_best(run, "candidate-01")
    assert run["best_candidate_id"] == "candidate-01"
    validate_artifact("optimization_run", run)

    blocked = stop_run(begin_iteration(_run(), _candidates()), "user_blocked")
    assert blocked["status"] == "blocked"
    with pytest.raises(ValueError, match="invalid stop reason"):
        stop_run(begin_iteration(_run(), _candidates()), "bogus")


def test_terminal_run_rejects_further_transitions():
    run = stop_run(begin_iteration(_run(), _candidates()), "budget_exceeded")
    with pytest.raises(ValueError, match="terminal"):
        begin_iteration(run, _candidates())

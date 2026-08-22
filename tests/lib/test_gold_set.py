"""Tests for gold_sample set and calibration statistics (Design_Review P2)."""

from __future__ import annotations

import pytest

from lib.gold_set import (
    add_sample,
    assign_group_split,
    bootstrap_ci,
    cohens_kappa,
    create_gold_set,
    replay_score,
)
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


def test_gold_sample_registered():
    assert "gold_sample" in ARTIFACT_NAMES


def test_create_and_add_samples():
    goldset = create_gold_set("gs-001", judge_version="technical_validator-0.1.0", rubric_version="l1a-v1.0")
    assert goldset["samples"] == []
    goldset = add_sample(goldset, sample_id="s1", video_ref={"path": "renders/s1.mp4"},
                         tier="gold", group_key="sku-towel",
                         labels={"pointwise": {"hook": 8.0}, "failure_tags": [], "expert_reason": "钩子直给"})
    goldset = add_sample(goldset, sample_id="s2", video_ref={"path": "renders/s2.mp4"},
                         tier="hard_negative", group_key="sku-towel",
                         labels={"failure_tags": ["blank_frame"], "expert_reason": "黑帧"})
    validate_artifact("gold_sample", goldset)
    assert len(goldset["samples"]) == 2


def test_hard_negative_requires_failure_tags():
    goldset = create_gold_set("gs-001", judge_version="j", rubric_version="r")
    with pytest.raises(ValueError, match="failure_tags"):
        add_sample(goldset, sample_id="s1", video_ref={"path": "x.mp4"},
                   tier="hard_negative", group_key="g", labels={})


def test_duplicate_sample_rejected():
    goldset = create_gold_set("gs-001", judge_version="j", rubric_version="r")
    goldset = add_sample(goldset, sample_id="s1", video_ref={"path": "x.mp4"}, tier="gold", group_key="g")
    with pytest.raises(ValueError, match="duplicate"):
        add_sample(goldset, sample_id="s1", video_ref={"path": "y.mp4"}, tier="gold", group_key="g")


def test_group_split_keeps_groups_whole():
    goldset = create_gold_set("gs-001", judge_version="j", rubric_version="r")
    for i in range(6):
        goldset = add_sample(goldset, sample_id=f"s{i}", video_ref={"path": f"{i}.mp4"},
                             tier="gold", group_key=f"sku-{i % 3}")
    goldset = assign_group_split(goldset, seed=1)
    for i in range(6):
        first = next(s for s in goldset["samples"] if s["group_key"] == f"sku-{i % 3}")
        assert all(s["split"] == first["split"] for s in goldset["samples"] if s["group_key"] == f"sku-{i % 3}")


def test_cohens_kappa():
    a = {"s1": "pass", "s2": "pass", "s3": "fail", "s4": "fail"}
    b = {"s1": "pass", "s2": "fail", "s3": "fail", "s4": "fail"}
    kappa = cohens_kappa(a, b)
    assert 0.0 < kappa < 1.0
    assert cohens_kappa(a, a) == 1.0


def test_bootstrap_ci():
    ci = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0], seed=42)
    assert ci["mean"] == 3.0
    assert ci["low"] < ci["mean"] < ci["high"]


def test_replay_score_flags_hard_gate_regression():
    goldset = create_gold_set("gs-001", judge_version="j", rubric_version="r")
    goldset = add_sample(goldset, sample_id="s1", video_ref={"path": "x.mp4"}, tier="gold", group_key="g",
                         labels={"pointwise": {"hook": 8.0}})
    goldset = add_sample(goldset, sample_id="s2", video_ref={"path": "y.mp4"}, tier="bad", group_key="g",
                         labels={"pointwise": {"hook": 3.0}})

    def new_judge(sample):
        return {"score": 4.0, "pass": False}

    report = replay_score(goldset, judge_fn=new_judge, judge_version="j2", rubric_version="r")
    assert report["sample_count"] == 2
    assert report["hard_gate_failure_increase"] == 1
    assert report["degradation_flags"]["hard_gate_failure_increase"] is True


def test_candidate_batch_budget_enforced():
    from lib.candidate_batch import create_candidate_batch, record_candidate_result
    batch = create_candidate_batch(
        "b1", shared_research_refs=[{"name": "rf", "path": "rf.json"}],
        candidates=[{"candidate_id": "C1", "label": "x", "project_id": "p1"}],
        max_candidates=10, max_parallel=5,
        budget={"max_cost_usd": 1.0, "max_retries_per_candidate": 1, "max_latency_minutes": 60},
    )
    batch = record_candidate_result(batch, "C1", status="in_progress")
    with pytest.raises(ValueError, match="budget"):
        record_candidate_result(batch, "C1", status="sampled", sample_ref={"path": "c1.mp4"}, cost_usd=1.5)
    batch = record_candidate_result(batch, "C1", status="in_progress", is_retry=True)
    with pytest.raises(ValueError, match="retry budget"):
        record_candidate_result(batch, "C1", status="in_progress", is_retry=True)


def _goldset_with_scores(n_per_dim: int, *, annotator_b: bool = False) -> dict:
    from lib.gold_set import add_sample, create_gold_set

    goldset = create_gold_set("gs-cal", judge_version="video_judge-0.2.0",
                              rubric_version="ecommerce-remix-v1.0")
    for index in range(n_per_dim):
        goldset = add_sample(
            goldset, sample_id=f"s{index}", video_ref={"path": f"renders/s{index}.mp4"},
            tier="gold", group_key=f"group-{index % 7}",
            labels={"pointwise": {"hook_clarity": 8.5, "product_evidence": 9.0},
                    "expert_reason": "ok"},
            annotator_id="human",
        )
        if annotator_b:
            goldset["samples"][-1]["annotators"].append(
                {"annotator_id": "expert-b", "role": "secondary", "annotated_at": "2026-08-23T00:00:00+00:00"}
            )
    return goldset


def test_calibration_report_counts_per_dimension():
    from lib.gold_set import calibration_report

    report = calibration_report(
        _goldset_with_scores(3), min_samples_per_dimension=5, min_kappa=0.6
    )
    assert report["dimensions"]["hook_clarity"]["total"] == 3
    assert report["dimensions"]["product_evidence"]["total"] == 3
    assert report["sufficient"] is False
    assert report["releasable"] is False


def test_calibration_sufficient_and_double_annotated_at_threshold():
    from lib.gold_set import calibration_report

    report = calibration_report(
        _goldset_with_scores(100, annotator_b=True),
        annotator_b="expert-b",
        min_samples_per_dimension=100, min_kappa=0.6,
    )
    assert report["sufficient"] is True
    assert report["double_annotated"] is True
    assert report["kappa"] == 1.0  # 双标注一致
    assert report["releasable"] is True


def test_calibration_without_double_annotation_not_releasable():
    from lib.gold_set import calibration_report

    report = calibration_report(
        _goldset_with_scores(100), min_samples_per_dimension=100, min_kappa=0.6
    )
    assert report["sufficient"] is True
    assert report["releasable"] is False  # 缺双人标注，不允许进入生产门禁


def test_assert_judge_releasable_blocks_insufficient_calibration():
    from lib.gold_set import assert_judge_releasable

    with pytest.raises(ValueError, match="校准不足"):
        assert_judge_releasable(_goldset_with_scores(3), min_samples_per_dimension=100)


def test_assert_judge_releasable_passes_sufficient_calibration():
    from lib.gold_set import assert_judge_releasable

    assert_judge_releasable(
        _goldset_with_scores(100, annotator_b=True),
        annotator_b="expert-b",
        min_samples_per_dimension=100,
    )

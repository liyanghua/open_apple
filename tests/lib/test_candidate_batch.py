"""Contract and builder tests for candidate_batch (Design_Review P1-2)."""

from __future__ import annotations

import pytest

from lib.candidate_batch import create_candidate_batch, record_candidate_result, select_for_edit
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


def _research_refs():
    return [
        {"name": "reference_fingerprint", "path": "artifacts/reference_fingerprint.json", "artifact_sha256": "a" * 64},
        {"name": "research_breakdown", "path": "artifacts/research_breakdown.json", "artifact_sha256": "b" * 64},
        {"name": "source_media_review", "path": "artifacts/source_media_review.json", "artifact_sha256": "c" * 64},
    ]


def _candidates():
    return [
        {"candidate_id": "C1", "label": "结果先行", "project_id": "table-mat-batch-c1",
         "direction": {"hook": "result_first", "pacing": "快切证明", "packaging": "字幕主导", "audience": "新客", "duration": "15s"}},
        {"candidate_id": "C2", "label": "痛点先行", "project_id": "table-mat-batch-c2",
         "direction": {"hook": "problem_first", "pacing": "问题-解决", "packaging": "口播主导", "audience": "老客", "duration": "30s"}},
    ]


def test_candidate_batch_registered():
    assert "candidate_batch" in ARTIFACT_NAMES


def test_create_batch_is_valid():
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    validate_artifact("candidate_batch", batch)
    assert batch["candidates"][0]["status"] == "planned"
    assert batch["selection"]["selected_candidate_ids"] == []


def test_create_batch_rejects_empty_research():
    with pytest.raises(ValueError):
        create_candidate_batch("x", shared_research_refs=[], candidates=_candidates())


def test_create_batch_rejects_too_many_candidates():
    many = [dict(c, candidate_id=f"C{i}") for i, c in enumerate(_candidates() * 4, start=1)]
    with pytest.raises(ValueError):
        create_candidate_batch("x", shared_research_refs=_research_refs(), candidates=many, max_candidates=5)


def test_record_candidate_result_accumulates_cost():
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    batch = record_candidate_result(batch, "C1", status="in_progress")
    batch = record_candidate_result(batch, "C1", status="sampled", sample_ref={"path": "renders/sample-v1.mp4"}, cost_usd=1.5)
    batch = record_candidate_result(batch, "C1", status="evaluated",
                                     evaluation_report_ref={"name": "evaluation_report", "path": "artifacts/evaluation_report.json"},
                                     cost_usd=0.2)
    validate_artifact("candidate_batch", batch)
    item = next(c for c in batch["candidates"] if c["candidate_id"] == "C1")
    assert item["status"] == "evaluated"
    assert item["cost_usd"] == 1.7


def test_record_failure():
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    batch = record_candidate_result(batch, "C2", status="failed", failure="生成超时")
    item = next(c for c in batch["candidates"] if c["candidate_id"] == "C2")
    assert item["failure"] == "生成超时"


def test_select_for_edit_requires_evaluated():
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    with pytest.raises(ValueError, match="evaluated"):
        select_for_edit(batch, ["C1"], reason="看中前 3 秒")


def test_select_for_edit_max_two():
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    for cid in ("C1", "C2"):
        batch = record_candidate_result(batch, cid, status="in_progress")
        batch = record_candidate_result(batch, cid, status="sampled", sample_ref={"path": f"renders/{cid}-sample.mp4"})
        batch = record_candidate_result(batch, cid, status="evaluated",
                                         evaluation_report_ref={"name": "evaluation_report", "path": f"{cid}.json"})
    batch = select_for_edit(batch, ["C1", "C2"], reason="两条都进精剪对比")
    validate_artifact("candidate_batch", batch)
    assert batch["selection"]["selected_candidate_ids"] == ["C1", "C2"]
    assert all(c["status"] == "selected_for_edit" for c in batch["candidates"])
    with pytest.raises(ValueError, match="at most 2"):
        select_for_edit(batch, ["C1", "C2", "C3"], reason="x")


def test_batch_budget_is_enforced_on_batch_total():
    """评审 #6：max_cost_usd 是整批预算，不是每候选预算。"""
    budget = {"max_cost_usd": 2.0, "max_retries_per_candidate": 2}
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates(), budget=budget)
    batch = record_candidate_result(batch, "C1", status="in_progress")
    batch = record_candidate_result(batch, "C1", status="sampled", sample_ref={"path": "c1.mp4"}, cost_usd=1.5)
    batch = record_candidate_result(batch, "C2", status="in_progress")
    with pytest.raises(ValueError, match="batch budget"):
        record_candidate_result(batch, "C2", status="sampled", sample_ref={"path": "c2.mp4"}, cost_usd=1.0)


def test_candidate_cannot_jump_planned_to_evaluated():
    """评审 #7：跨状态跳变（planned -> evaluated）被拒绝。"""
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    with pytest.raises(ValueError, match="transition"):
        record_candidate_result(batch, "C1", status="evaluated",
                                 evaluation_report_ref={"name": "evaluation_report", "path": "x.json"})


def test_candidate_evaluated_requires_evaluation_report_ref():
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    batch = record_candidate_result(batch, "C1", status="in_progress")
    batch = record_candidate_result(batch, "C1", status="sampled", sample_ref={"path": "c1.mp4"})
    with pytest.raises(ValueError, match="evaluation_report_ref"):
        record_candidate_result(batch, "C1", status="evaluated")


def test_candidate_cannot_jump_to_selected_for_edit_via_record():
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=_candidates())
    batch = record_candidate_result(batch, "C1", status="in_progress")
    with pytest.raises(ValueError, match="select_for_edit"):
        record_candidate_result(batch, "C1", status="selected_for_edit")


def test_select_for_edit_rejects_evaluated_without_report_ref():
    seeded = [
        {**_candidates()[0], "status": "evaluated"},
    ]
    batch = create_candidate_batch("table-mat-001", shared_research_refs=_research_refs(), candidates=seeded)
    with pytest.raises(ValueError, match="forged status"):
        select_for_edit(batch, ["C1"], reason="伪造 evaluated 状态")

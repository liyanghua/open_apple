"""Batch cockpit actions 测试（Batch_Workbench_Interaction_Design §4.2）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backlot.batch_actions import BatchActionService
from backlot.operator_errors import OperatorError
from lib.candidate_batch import create_candidate_batch


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _batch_project(tmp_path: Path, candidates: list[dict] | None = None) -> Path:
    batch_dir = tmp_path / "batch-mix-001"
    _write(batch_dir / "project.json", {
        "project_id": "batch-mix-001", "title": "批量混剪", "pipeline_type": "cinematic-fast",
    })
    batch = create_candidate_batch(
        "mix-001",
        shared_research_refs=[{"name": "research_brief", "path": "artifacts/research_brief.json"}],
        candidates=candidates if candidates is not None else [
            {"candidate_id": "cand-01", "label": "结果先行", "project_id": "cand-01", "status": "evaluated",
             "evaluation_report_ref": {"name": "evaluation_report", "path": "cand-01.json"}},
            {"candidate_id": "cand-02", "label": "痛点先行", "project_id": "cand-02", "status": "evaluated",
             "evaluation_report_ref": {"name": "evaluation_report", "path": "cand-02.json"}},
        ],
        source_media_refs=["inputs/source/video-01.mp4"],
    )
    _write(batch_dir / "artifacts" / "candidate_batch.json", batch)
    return batch_dir


def test_select_for_edit_writes_selection_and_decision(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    service = BatchActionService(batch_dir)
    result = service.select_for_edit(
        actor_id="owner", idempotency_key="k1",
        candidate_ids=["cand-01"], reason="钩子最抓人",
    )
    assert result["status"] == "committed"
    batch = json.loads((batch_dir / "artifacts" / "candidate_batch.json").read_text(encoding="utf-8"))
    assert batch["selection"]["selected_candidate_ids"] == ["cand-01"]
    log = json.loads((batch_dir / "artifacts" / "decision_log.json").read_text(encoding="utf-8"))
    assert any(d.get("category") == "concept_selection" for d in log["decisions"])
    # 幂等回放：同 idempotency_key 返回同一结果
    replay = service.select_for_edit(
        actor_id="owner", idempotency_key="k1",
        candidate_ids=["cand-01"], reason="钩子最抓人",
    )
    assert replay == result


def test_select_rejects_more_than_two(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    with pytest.raises(OperatorError, match="1-2"):
        BatchActionService(batch_dir).select_for_edit(
            actor_id="owner", idempotency_key="k2",
            candidate_ids=["cand-01", "cand-02", "cand-03"], reason="x",
        )


def test_select_rejects_non_evaluated_candidate(tmp_path: Path):
    batch_dir = _batch_project(tmp_path, candidates=[
        {"candidate_id": "cand-01", "label": "未评分", "project_id": "cand-01", "status": "planned"},
    ])
    with pytest.raises(ValueError, match="evaluated"):
        BatchActionService(batch_dir).select_for_edit(
            actor_id="owner", idempotency_key="k3",
            candidate_ids=["cand-01"], reason="x",
        )


def _review(candidate_id: str, kind: str = "script_lock") -> dict:
    return {
        "schema_version": "1.0",
        "review_id": f"{candidate_id}-{kind}-v1-abc",
        "project_id": candidate_id,
        "kind": kind,
        "subject_id": "subject",
        "subject_version": 1,
        "subject_hash": "a" * 64,
        "status": "awaiting_human",
        "submitted_by": "agent",
        "decided_by": None,
        "reason": None,
        "created_at": "2026-08-23T00:00:00+00:00",
        "decided_at": None,
    }


def _child_with_review(tmp_path: Path, candidate_id: str, kind: str = "script_lock") -> Path:
    child = tmp_path / candidate_id
    _write(child / "project.json", {
        "project_id": candidate_id, "title": candidate_id, "pipeline_type": "cinematic-fast",
    })
    _write(child / "operator" / "reviews" / f"{candidate_id}-{kind}-v1-abc.json", _review(candidate_id, kind))
    return child


def test_approve_gate_approves_pending_candidates(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    for candidate_id in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, candidate_id, kind="sample")
    result = BatchActionService(batch_dir).approve_gate(
        actor_id="owner", idempotency_key="k4", gate="sample",
        candidate_ids=["cand-01", "cand-02"], reason="批级一键通过",
    )
    assert result["status"] == "committed"
    for candidate_id in ("cand-01", "cand-02"):
        review = json.loads(
            (tmp_path / candidate_id / "operator" / "reviews" / f"{candidate_id}-sample-v1-abc.json")
            .read_text(encoding="utf-8")
        )
        assert review["status"] == "approved"
        assert review.get("effect_confirmation", {}).get("hook") == "pass"


def test_script_gate_approves_checkpoint(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    child = tmp_path / "cand-01"
    _write(child / "project.json", {
        "project_id": "cand-01", "title": "cand-01", "pipeline_type": "cinematic-fast",
    })
    _write(child / "checkpoint_script.json", {
        "version": "1.0",
        "project_id": "cand-01",
        "pipeline_type": "cinematic-fast",
        "stage": "script",
        "status": "awaiting_human",
        "timestamp": "2026-08-23T00:00:00+00:00",
        "artifacts": {},
        "human_approval_required": True,
        "human_approved": False,
        "approval_group": "script_lock",
    })
    result = BatchActionService(batch_dir).approve_gate(
        actor_id="owner", idempotency_key="k7", gate="script",
        candidate_ids=["cand-01"], reason="批级一键通过",
    )
    assert result["status"] == "committed"
    checkpoint = json.loads((child / "checkpoint_script.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "completed"
    assert checkpoint["human_approved"] is True


def test_approve_gate_skips_mismatched_review_kind(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    _child_with_review(tmp_path, "cand-01", kind="sample")
    result = BatchActionService(batch_dir).approve_gate(
        actor_id="owner", idempotency_key="k5", gate="assets",
        candidate_ids=["cand-01"], reason="批级一键通过",
    )
    assert result["status"] == "committed"
    # kind 不匹配：跳过，不审批
    review = json.loads(
        (tmp_path / "cand-01" / "operator" / "reviews" / "cand-01-sample-v1-abc.json")
        .read_text(encoding="utf-8")
    )
    assert review["status"] == "awaiting_human"


def test_approve_gate_rejects_unknown_gate(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    with pytest.raises(OperatorError, match="未知的批级门"):
        BatchActionService(batch_dir).approve_gate(
            actor_id="owner", idempotency_key="k6", gate="publish",
            candidate_ids=["cand-01"], reason="x",
        )

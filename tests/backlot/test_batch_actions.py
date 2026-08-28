"""跨项目审批一致性契约测试（Batch_Workbench_Cross_Project_Approval_Consistency_Contract §8）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import backlot.batch_actions as actions_module
from backlot.batch_actions import BatchActionService, _load_record, recover_batch_action
from backlot.operator_errors import OperatorError
from backlot.operator_reviews import EFFECT_CONFIRMATION_KEYS, ReviewService
from lib.candidate_batch import create_candidate_batch


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _batch_project(tmp_path: Path, n: int = 2) -> Path:
    batch_dir = tmp_path / "batch-mix-001"
    _write(batch_dir / "project.json", {
        "project_id": "batch-mix-001", "title": "批量混剪", "pipeline_type": "cinematic-fast",
    })
    candidates = [
        {"candidate_id": f"cand-{i:02d}", "label": f"方向 {i}", "project_id": f"cand-{i:02d}",
         "status": "evaluated",
         "evaluation_report_ref": {"name": "evaluation_report", "path": f"cand-{i:02d}.json"}}
        for i in range(1, n + 1)
    ]
    batch = create_candidate_batch(
        "mix-001",
        shared_research_refs=[{"name": "research_brief", "path": "artifacts/research_brief.json"}],
        candidates=candidates,
        source_media_refs=["inputs/source/video-01.mp4"],
    )
    _write(batch_dir / "artifacts" / "candidate_batch.json", batch)
    for report_name in ("batch_run_report", "batch_quality_report"):
        _write(batch_dir / "artifacts" / f"{report_name}.json", {
            "data_quality": {"status": "complete"},
        })
    return batch_dir


def _review(candidate_id: str, kind: str, review_id: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "review_id": review_id or f"{candidate_id}-{kind}-v1-abc",
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


def _child_with_review(tmp_path: Path, candidate_id: str, kind: str = "sample") -> Path:
    child = tmp_path / candidate_id
    _write(child / "project.json", {
        "project_id": candidate_id, "title": candidate_id, "pipeline_type": "cinematic-fast",
    })
    _write(child / "operator" / "reviews" / f"{candidate_id}-{kind}-v1-abc.json", _review(candidate_id, kind))
    # P1 质量门要求：final_props 字幕 + 开场镜头屏显文案。
    _write(child / "artifacts" / "final_props.json", {
        "version": "1.0", "project_id": candidate_id, "fps": 30, "durationInFrames": 450,
        "scenes": [{"id": "shot-01", "fromFrame": 0, "toFrameExclusive": 69, "assetId": "proxy-01",
                    "sourceInSeconds": 0, "sourceOutSeconds": 2.3}],
        "captions": [{"text": "一铺即护", "startMs": 0, "endMs": 2300}],
    })
    _write(child / "artifacts" / "shot_execution_plan.json", {
        "version": "1.0", "project_id": candidate_id,
        "shots": [{"id": "shot-01", "screen_copy": "一铺即护", "duration_seconds": 2.3}],
    })
    # P1 质量门要求：评估报告（非 fatal）+ 已批准的样本 review（五项确认全 pass）。
    _write(child / "artifacts" / "evaluation_report.json", {
        "version": "1.0", "project_id": candidate_id, "status": "revise",
        "hard_gate": {"pass": False, "checks": []}, "recommended_action": "repair",
    })
    approved = dict(_review(candidate_id, "sample", review_id=f"{candidate_id}-sample-v2-approved"))
    approved["status"] = "approved"
    approved["decided_by"] = "owner"
    approved["decided_at"] = "2026-08-23T00:01:00+00:00"
    approved["effect_confirmation"] = {
        "creative_direction": "pass", "hook": "pass", "proof": "pass",
        "pacing": "pass", "readability": "pass",
    }
    _write(child / "operator" / "reviews" / f"{candidate_id}-sample-v2-approved.json", approved)
    # 差异度硬门：candidate_variant_plan（六维中 3 维变更 + 3 结构镜头差异，非 opening-only）。
    from lib.candidate_diversity import build_variant_plan
    _write(child / "artifacts" / "candidate_variant_plan.json", build_variant_plan(
        batch_id="b1", candidate_id=candidate_id, variant_revision=1,
        baseline_ref={"name": "x", "path": "artifacts/x.json"},
        dimensions={
            "hook_type": {"value": f"{candidate_id}-hook", "baseline_value": "b", "changed": True, "rationale": "r"},
            "narrative_structure": {"value": f"{candidate_id}-nar", "baseline_value": "b", "changed": True, "rationale": "r"},
            "visual_grammar": {"value": f"{candidate_id}-vg", "baseline_value": "b", "changed": True, "rationale": "r"},
            "pacing_profile": {"value": "b", "baseline_value": "b", "changed": False, "rationale": "r"},
            "evidence_strategy": {"value": "b", "baseline_value": "b", "changed": False, "rationale": "r"},
            "asset_strategy": {"value": "b", "baseline_value": "b", "changed": False, "rationale": "r"},
        },
        shot_differences=[
            {"shot_id": "s0", "difference_type": "shot_order", "evidence_class": "structural",
             "evidence_ref": {"kind": "artifact", "path": "p0"}},
            {"shot_id": "s1", "difference_type": "duration", "evidence_class": "structural",
             "evidence_ref": {"kind": "artifact", "path": "p1"}},
            {"shot_id": "s2", "difference_type": "source_window", "evidence_class": "structural",
             "evidence_ref": {"kind": "artifact", "path": "p2"}},
        ],
        opening_only_change=False,
    ))
    return child


def _service(tmp_path: Path, batch_dir: Path, **kwargs) -> BatchActionService:
    return BatchActionService(batch_dir, **kwargs)


def _participants(tmp_path: Path, gate: str, candidate_ids: list[str]) -> list[dict]:
    participants = []
    for candidate_id in candidate_ids:
        pending = ReviewService(tmp_path / candidate_id).pending()
        assert pending is not None
        participants.append({
            "candidate_id": candidate_id,
            "project_id": candidate_id,
            "review_id": pending["review_id"],
            "subject_version": pending["subject_version"],
            "subject_hash": pending["subject_hash"],
            **({"effect_confirmations": {key: "pass" for key in EFFECT_CONFIRMATION_KEYS}} if gate == "sample" else {}),
        })
    return participants


# ------------------------------------------------------------------ select
def test_select_commits_and_replays(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    for candidate_id in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, candidate_id)
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    result = service.select_for_edit(
        actor_id="owner", idempotency_key="k1", aggregate_revision=revision,
        candidate_ids=["cand-01"], reason="钩子最抓人",
    )
    assert result["status"] == "committed"
    assert result["selected_candidate_ids"] == ["cand-01"]
    record = _load_record(batch_dir, result["batch_action_id"])
    assert record["status"] == "committed"
    # 幂等重放
    replay = service.select_for_edit(
        actor_id="owner", idempotency_key="k1", aggregate_revision=revision,
        candidate_ids=["cand-01"], reason="钩子最抓人",
    )
    assert replay["status"] == "replayed"
    assert replay["selected_candidate_ids"] == ["cand-01"]


def test_select_rejects_when_batch_reports_are_missing(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    (batch_dir / "artifacts" / "batch_run_report.json").unlink()
    _child_with_review(tmp_path, "cand-01")
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()

    with pytest.raises(OperatorError, match="批次报告"):
        service.select_for_edit(
            actor_id="owner", idempotency_key="missing-reports",
            aggregate_revision=revision, candidate_ids=["cand-01"], reason="x",
        )


def test_select_key_reuse_conflict(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    for candidate_id in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, candidate_id)
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    service.select_for_edit(
        actor_id="owner", idempotency_key="k2", aggregate_revision=revision,
        candidate_ids=["cand-01"], reason="x",
    )
    with pytest.raises(OperatorError) as excinfo:
        service.select_for_edit(
            actor_id="owner", idempotency_key="k2", aggregate_revision=revision,
            candidate_ids=["cand-02"], reason="y",
        )
    assert excinfo.value.code == "idempotency_conflict"


def test_select_stale_revision_rejected(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    _child_with_review(tmp_path, "cand-01")
    service = _service(tmp_path, batch_dir)
    with pytest.raises(OperatorError) as excinfo:
        service.select_for_edit(
            actor_id="owner", idempotency_key="k3", aggregate_revision="0" * 64,
            candidate_ids=["cand-01"], reason="x",
        )
    assert excinfo.value.code == "stale"


def test_select_rejects_more_than_two(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    service = _service(tmp_path, batch_dir)
    with pytest.raises(OperatorError, match="1-2"):
        service.select_for_edit(
            actor_id="owner", idempotency_key="k4", aggregate_revision="0" * 64,
            candidate_ids=["cand-01", "cand-02", "cand-03"], reason="x",
        )


# ------------------------------------------------------------ approve gate
def test_approve_gate_commits_participants_with_audit(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    for candidate_id in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, candidate_id, kind="sample")
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    participants = _participants(tmp_path, "sample", ["cand-01", "cand-02"])
    result = service.approve_gate(
        actor_id="owner", idempotency_key="k5", aggregate_revision=revision,
        gate="sample", reason="批级一键通过", participants=participants,
    )
    assert result["status"] == "committed"
    assert {p["candidate_id"] for p in result["participants"]} == {"cand-01", "cand-02"}
    record = _load_record(batch_dir, result["batch_action_id"])
    assert record["status"] == "committed"
    assert all(p["state"] == "committed" for p in record["participants"])
    for candidate_id in ("cand-01", "cand-02"):
        review = json.loads(
            (tmp_path / candidate_id / "operator" / "reviews" / f"{candidate_id}-sample-v1-abc.json")
            .read_text(encoding="utf-8")
        )
        assert review["status"] == "approved"
        log = json.loads((tmp_path / candidate_id / "artifacts" / "decision_log.json").read_text(encoding="utf-8"))
        entry = next(d for d in log["decisions"] if d.get("category") == "batch_approval")
        assert entry["batch_action_id"] == result["batch_action_id"]


def test_script_gate_derives_review_from_checkpoint(tmp_path: Path):
    batch_dir = _batch_project(tmp_path, n=1)
    child = tmp_path / "cand-01"
    _write(child / "project.json", {
        "project_id": "cand-01", "title": "cand-01", "pipeline_type": "cinematic-fast",
    })
    _write(child / "checkpoint_script.json", {
        "version": "1.0", "project_id": "cand-01", "pipeline_type": "cinematic-fast",
        "stage": "script", "status": "awaiting_human",
        "timestamp": "2026-08-23T00:00:00+00:00",
        "artifacts": {"script": {"name": "script", "path": "artifacts/script.json",
                                 "semantic_sha256": "a" * 64, "artifact_sha256": "b" * 64,
                                 "data": {"version": "1.0"}}},
    })
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    # Phase 3：prepare 只校验不创建——先经显式写路径（迁移）补建 review
    from backlot.operator_reviews import ReviewService

    ReviewService(child).ensure_script_review_for_checkpoint()
    result = service.approve_gate(
        actor_id="owner", idempotency_key="k6", aggregate_revision=revision,
        gate="script", reason="批级一键通过",
        participants=[{"candidate_id": "cand-01", "project_id": "cand-01",
                       "review_id": "", "subject_version": 0, "subject_hash": ""}],
    )
    assert result["status"] == "committed"
    checkpoint = json.loads((child / "checkpoint_script.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "completed"
    assert checkpoint["human_approved"] is True
    record = _load_record(batch_dir, result["batch_action_id"])
    assert record["participants"][0]["review_id"]


def test_prepare_snapshot_mismatch_rejects_without_side_effects(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    _child_with_review(tmp_path, "cand-01", kind="sample")
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    bad = _participants(tmp_path, "sample", ["cand-01"])
    bad[0]["subject_hash"] = "f" * 64
    with pytest.raises(OperatorError) as excinfo:
        service.approve_gate(
            actor_id="owner", idempotency_key="k7", aggregate_revision=revision,
            gate="sample", reason="x", participants=bad,
        )
    assert excinfo.value.code == "stale"
    review = json.loads(
        (tmp_path / "cand-01" / "operator" / "reviews" / "cand-01-sample-v1-abc.json")
        .read_text(encoding="utf-8")
    )
    assert review["status"] == "awaiting_human"  # 无副作用
    records = list((batch_dir / "operator" / "batch-actions").glob("*.json"))
    assert records and _load_record(batch_dir, records[0].stem)["status"] == "rejected"


def test_sample_gate_requires_all_pass_confirmations(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    _child_with_review(tmp_path, "cand-01", kind="sample")
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    participants = _participants(tmp_path, "sample", ["cand-01"])
    participants[0]["effect_confirmations"]["hook"] = "adjust"
    with pytest.raises(OperatorError) as excinfo:
        service.approve_gate(
            actor_id="owner", idempotency_key="k8", aggregate_revision=revision,
            gate="sample", reason="x", participants=participants,
        )
    assert excinfo.value.code == "validation_failed"


def test_permission_denial_rejects_whole_action(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    _child_with_review(tmp_path, "cand-01", kind="sample")
    service = _service(
        tmp_path, batch_dir,
        authorizer=lambda project_id, actor_id: project_id != "cand-01",
    )
    revision, _ = service._current_revision()
    with pytest.raises(OperatorError) as excinfo:
        service.approve_gate(
            actor_id="owner", idempotency_key="k9", aggregate_revision=revision,
            gate="sample", reason="x", participants=_participants(tmp_path, "sample", ["cand-01"]),
        )
    assert excinfo.value.code == "forbidden"
    review = json.loads(
        (tmp_path / "cand-01" / "operator" / "reviews" / "cand-01-sample-v1-abc.json")
        .read_text(encoding="utf-8")
    )
    assert review["status"] == "awaiting_human"


def test_commit_mid_failure_needs_recovery_then_recovers(tmp_path: Path, monkeypatch):
    batch_dir = _batch_project(tmp_path)
    for candidate_id in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, candidate_id, kind="sample")
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    participants = _participants(tmp_path, "sample", ["cand-01", "cand-02"])

    original_decide = ReviewService.decide
    calls = {"count": 0}

    def flaky_decide(self, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("fault injected: commit crash")
        return original_decide(self, **kwargs)

    monkeypatch.setattr(actions_module.ReviewService, "decide", flaky_decide)
    with pytest.raises(OperatorError) as excinfo:
        service.approve_gate(
            actor_id="owner", idempotency_key="k10", aggregate_revision=revision,
            gate="sample", reason="x", participants=participants,
        )
    assert excinfo.value.code == "needs_recovery"
    record = _load_record(batch_dir, excinfo.value.details["batch_action_id"])
    assert record["status"] == "needs_recovery"
    # Phase 2 fence 契约：中途失败 → 已 held 候选**补偿回滚**（仅 pointer 匹配者），
    # 读取方仍见动作前事实；恢复时重新提交。
    assert [p["state"] for p in record["participants"]] == ["rolled_back", "committing"]

    # 恢复：续跑完成剩余提交
    monkeypatch.setattr(actions_module.ReviewService, "decide", original_decide)
    recovered = recover_batch_action(batch_dir, record["batch_action_id"])
    assert recovered["status"] == "committed"
    final = _load_record(batch_dir, record["batch_action_id"])
    assert final["status"] == "committed"
    assert all(p["state"] == "committed" for p in final["participants"])
    for candidate_id in ("cand-01", "cand-02"):
        review = json.loads(
            (tmp_path / candidate_id / "operator" / "reviews" / f"{candidate_id}-sample-v1-abc.json")
            .read_text(encoding="utf-8")
        )
        assert review["status"] == "approved"


def test_replay_after_commit(tmp_path: Path):
    batch_dir = _batch_project(tmp_path)
    _child_with_review(tmp_path, "cand-01", kind="sample")
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    participants = _participants(tmp_path, "sample", ["cand-01"])
    first = service.approve_gate(
        actor_id="owner", idempotency_key="k11", aggregate_revision=revision,
        gate="sample", reason="x", participants=participants,
    )
    replay = service.approve_gate(
        actor_id="owner", idempotency_key="k11", aggregate_revision=revision,
        gate="sample", reason="x", participants=participants,
    )
    assert replay["status"] == "replayed"
    assert replay["batch_action_id"] == first["batch_action_id"]


def test_select_rejects_candidate_missing_captions_or_opening(tmp_path: Path):
    """P1 质量门：候选缺字幕或开场就是不可选（未通过 quality gate）。"""
    batch_dir = _batch_project(tmp_path)
    child = tmp_path / "cand-01"
    _write(child / "project.json", {"project_id": "cand-01", "title": "cand-01", "pipeline_type": "cinematic-fast"})
    _write(child / "operator" / "reviews" / "cand-01-sample-v1-abc.json", _review("cand-01", "sample"))
    # 故意不写 final_props / shot_execution_plan —— 字幕与开场缺失。
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    with pytest.raises(OperatorError) as excinfo:
        service.select_for_edit(
            actor_id="owner", idempotency_key="kneg", aggregate_revision=revision,
            candidate_ids=["cand-01"], reason="同质候选",
        )
    assert "质量门" in str(excinfo.value)


def test_sample_gate_hard_gate_rejects_missing_variant_plan(tmp_path: Path):
    """差异度硬门：diversity_mode=hard_gate 时，缺 candidate_variant_plan 的候选在
    sample 门 prepare 阶段被拒（validation_failed）。"""
    batch_dir = _batch_project(tmp_path)
    batch = json.loads((batch_dir / "artifacts" / "candidate_batch.json").read_text(encoding="utf-8"))
    batch["diversity_mode"] = "hard_gate"
    _write(batch_dir / "artifacts" / "candidate_batch.json", batch)

    child = tmp_path / "cand-01"
    _write(child / "project.json", {"project_id": "cand-01", "title": "cand-01", "pipeline_type": "cinematic-fast"})
    _write(child / "operator" / "reviews" / "cand-01-sample-v1-abc.json", _review("cand-01", "sample"))
    # 故意不写 candidate_variant_plan.json

    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    with pytest.raises(OperatorError) as excinfo:
        service.approve_gate(
            actor_id="owner", idempotency_key="k-hard", aggregate_revision=revision,
            gate="sample", reason="x",
            participants=[{
                "candidate_id": "cand-01", "project_id": "cand-01",
                "review_id": "cand-01-sample-v1-abc", "subject_version": 1, "subject_hash": "a" * 64,
                "effect_confirmations": {key: "pass" for key in EFFECT_CONFIRMATION_KEYS},
            }],
        )
    assert "差异度硬门" in str(excinfo.value)

def test_script_gate_prepare_validates_without_creating(tmp_path: Path):
    """Phase 3：缺 review 时批 prepare 只校验不创建——「审批信息需要更新」且不落任何 review。"""
    batch_dir = _batch_project(tmp_path, n=1)
    child = tmp_path / "cand-01"
    _write(child / "project.json", {"project_id": "cand-01", "title": "cand-01",
                                    "pipeline_type": "cinematic-fast"})
    _write(child / "checkpoint_script.json", {"version": "1.0", "project_id": "cand-01",
                                              "pipeline_type": "cinematic-fast", "stage": "script",
                                              "status": "awaiting_human"})
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    with pytest.raises(OperatorError) as exc:
        service.approve_gate(actor_id="owner", idempotency_key="k6b", aggregate_revision=revision,
                             gate="script", reason="x",
                             participants=[{"candidate_id": "cand-01", "project_id": "cand-01",
                                            "review_id": "", "subject_version": 0, "subject_hash": ""}])
    assert exc.value.code == "validation_failed"
    from backlot.operator_reviews import ReviewService

    assert ReviewService(child).pending() is None
    reviews_dir = child / "operator" / "reviews"
    assert not (reviews_dir.exists() and list(reviews_dir.glob("*.json")))


def test_select_participants_with_evaluation_hash(tmp_path: Path):
    """Phase 3：participants 模式——服务端重读评价报告校验 hash/绑定/完整性；
    hash 不匹配 → validation_failed，不产生选择记录。"""
    batch_dir = _batch_project(tmp_path)
    for cid in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, cid)
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    report_path = tmp_path / "cand-01" / "artifacts" / "evaluation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["artifact_sha256"] = "c" * 64
    report.setdefault("scope", "sample")
    report["project_id"] = "cand-01"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    good_p = {"candidate_id": "cand-01", "project_id": "cand-01", "subject_hash": "a" * 64,
              "workflow_revision": 1, "evaluation_hash": "c" * 64}
    result = service.select_for_edit(actor_id="owner", idempotency_key="kp1",
                                     aggregate_revision=revision,
                                     participants=[good_p], reason="钩子最抓人")
    assert result["status"] == "committed"
    assert result["selected_candidate_ids"] == ["cand-01"]
    # hash 不匹配 → 拒绝；且无新记录（幂等键避免误重放）
    bad_p = {**good_p, "evaluation_hash": "b" * 64}
    with pytest.raises(OperatorError) as exc:
        service.select_for_edit(actor_id="owner", idempotency_key="kp2",
                                aggregate_revision=revision, participants=[bad_p], reason="x")
    assert exc.value.code == "validation_failed"
    assert "评价报告" in str(exc.value)

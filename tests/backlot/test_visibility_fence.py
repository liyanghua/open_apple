"""Phase 2 可见性合同（visibility fence）故障测试。

合同：
- F1 批量提交进行中（coordinator=committing，部分参与者已落盘）：批量投影与单条读取仍见**动作前**事实；
- F2 提交中任一候选的 outbox 事件不得提前发布；
- F3 恢复/续跑完成后：全部候选可见新事实，事件恰好发布一次；
- F4 全部参与者 marker 齐全才放行（fence 释放）。

当前行为预期失败（逐候选提交 + 立即 drain outbox）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import backlot.batch_actions as actions_module
from backlot.batch_actions import BatchActionService, recover_batch_action, _actions_dir
from backlot.operator_reviews import ReviewService
from backlot.operator_errors import OperatorError

from test_batch_actions import _batch_project, _child_with_review, _participants, _service  # noqa: F401


def _approve(batch_dir: Path, tmp_path: Path, gate: str = "sample") -> list[dict]:
    service = _service(tmp_path, batch_dir)
    revision, _ = service._current_revision()
    participants = _participants(tmp_path, gate, ["cand-01", "cand-02"])
    service.approve_gate(
        actor_id="owner", idempotency_key="fence-key-1",
        aggregate_revision=revision,
        gate=gate, reason="批量确认样片", participants=participants,
    )
    return participants


def _review_status(tmp_path: Path, candidate_id: str) -> str | None:
    service = ReviewService(tmp_path / candidate_id)
    pending = service.pending()
    if pending:
        return pending["status"]
    # 已决态：读最近 review 文件
    reviews_dir = tmp_path / candidate_id / "operator" / "reviews"
    if reviews_dir.exists():
        statuses = []
        for f in reviews_dir.glob("*.json"):
            try:
                statuses.append(json.loads(f.read_text(encoding="utf-8")).get("status"))
            except Exception:
                continue
        if statuses:
            return statuses[-1]
    return "no-pending"


def _events(project_dir: Path):
    events_dir = project_dir / "operator" / "events"
    if not events_dir.exists():
        return []
    return sorted(p.name for p in events_dir.glob("*"))


def test_fence_holds_reads_until_all_committed(tmp_path: Path, monkeypatch):
    batch_dir = _batch_project(tmp_path)
    for cid in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, cid)

    # 故障注入：第 2 个候选 decide 时抛异常 → coordinator 停在 committing（第 1 个已落盘）。
    original = ReviewService.decide
    calls = {"n": 0}

    def flaky_decide(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("injected fault after first participant commit")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ReviewService, "decide", flaky_decide)
    with pytest.raises((RuntimeError, OperatorError)):
        _approve(batch_dir, tmp_path)

    # F1：提交中，读取仍见动作前事实（候选仍 awaiting，fence 未放行）
    assert _review_status(tmp_path, "cand-01") == "awaiting_human", \
        "提交中读取不应看到候选已通过（fence 关闭）"
    # F2：提交中，**含写集**的 held generation 不得提前 release（initialize 的
    # 空 generation 除外；以 manifest write_set 是否非空判定）
    def _drained_with_writes(project_dir: Path) -> bool:
        gens = (project_dir / "operator" / "generations")
        if not gens.exists():
            return False
        for sub in gens.glob("*"):
            manifest = sub / "manifest.json"
            if not manifest.exists():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                continue
            if (data.get("write_set") or []):
                if (sub / "outbox-drained").exists():
                    return True
        return False

    assert not _drained_with_writes(tmp_path / "cand-01"), "提交中不得提前 drain outbox（held）"

    # 恢复后：fence 放行 → 可见 + 事件发布
    record_files = list((_actions_dir(batch_dir)).glob("*.json"))
    assert record_files, "coordinator record 应存在"
    record = json.loads(record_files[-1].read_text(encoding="utf-8"))
    assert record["status"] in {"prepared", "committing", "needs_recovery"}
    monkeypatch.setattr(ReviewService, "decide", original)
    recovered = recover_batch_action(batch_dir, record["batch_action_id"])
    assert recovered["status"] == "committed"  # F4：全部 marker 后放行
    assert _review_status(tmp_path, "cand-01") == "approved"
    assert _review_status(tmp_path, "cand-02") == "approved"
    # F3：恢复完成后 fence 放行 → outbox-drained 标记出现（事件发布一次；materializer
    # 为空时以标记为准，标记存在即代表 release 已执行）
    released = 0
    for cid in ("cand-01", "cand-02"):
        gens = tmp_path / cid / "operator" / "generations"
        if gens.exists():
            for sub in gens.glob("*"):
                manifest = sub / "manifest.json"
                if manifest.exists() and json.loads(manifest.read_text()).get("write_set"):
                    if (sub / "outbox-drained").exists():
                        released += 1
    assert released >= 2, "恢复后应统一放行全部 held generation"


def test_projection_carries_fence_while_committing(tmp_path: Path, monkeypatch):
    """展示层栅栏：提交中/待恢复 → 候选投影携带 fence 信息；恢复后消失。"""
    from backlot.batch_state import child_snapshot

    batch_dir = _batch_project(tmp_path)
    for cid in ("cand-01", "cand-02"):
        _child_with_review(tmp_path, cid)

    original = ReviewService.decide
    calls = {"n": 0}

    def flaky_decide(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("injected")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ReviewService, "decide", flaky_decide)
    try:
        _approve(batch_dir, tmp_path)
    except Exception:
        pass
    monkeypatch.setattr(ReviewService, "decide", original)

    snap = child_snapshot(tmp_path, tmp_path / "cand-01")
    assert snap.get("fence") and snap["fence"]["status"] in {"prepared", "committing", "needs_recovery"}
    # 恢复后 fence 消失
    records = list((_actions_dir(batch_dir)).glob("*.json"))
    record = json.loads(records[-1].read_text(encoding="utf-8"))
    recover_batch_action(batch_dir, record["batch_action_id"])
    snap2 = child_snapshot(tmp_path, tmp_path / "cand-01")
    assert snap2.get("fence") is None

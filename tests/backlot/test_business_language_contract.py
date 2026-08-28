"""Phase 1 契约测试：业务九步文案、五项中文映射、subject_hash 纯读取选择、读取纯净性。"""
from __future__ import annotations

import json
from pathlib import Path


def test_nine_step_business_labels():
    from backlot.operator_language import STAGE_LABELS

    expected = {
        "research": "了解任务",
        "proposal": "看创意方案",
        "script": "确认脚本",
        "scene_plan": "看分镜",
        "assets": "确认制作准备",
        "sample": "查看样片",
        "edit": "完成剪辑",
        "compose": "检查成片",
        "publish": "确认交付",
    }
    for stage, label in expected.items():
        assert STAGE_LABELS.get(stage) == label, f"{stage}: {STAGE_LABELS.get(stage)} != {label}"


def test_five_item_chinese_mapping():
    from backlot.operator_language import (CONFIRMATION_VALUE_LABELS, EFFECT_CONFIRMATION_LABELS)

    assert EFFECT_CONFIRMATION_LABELS == {
        "creative_direction": "创意方向是否正确",
        "hook": "开头是否马上抓住人",
        "proof": "产品/主题证明是否清楚",
        "pacing": "节奏和画面是否顺",
        "readability": "字幕是否看得清",
    }
    assert CONFIRMATION_VALUE_LABELS == {"pass": "通过", "adjust": "需要修改", "redirect": "不通过"}


def test_subject_hash_helper_selection(tmp_path: Path):
    """修正 1：优先级 pending → 最近已决（approved/rejected，排除 superseded，
    按 decided_at → created_at → review_id 确定性）→ 无则 None。"""
    from backlot.operator_reviews import ReviewService

    project = tmp_path / "proj"
    (project / "operator" / "reviews").mkdir(parents=True)
    (project / "operator" / "operator-managed").touch()

    def _write(review_id: str, status: str, subject_hash: str, *, decided_at=None,
               created_at=None, kind="sample"):
        data = {"schema_version": "1.0", "review_id": review_id, "project_id": "proj",
                "kind": kind, "subject_id": f"{kind}-v1", "subject_version": 1,
                "subject_hash": subject_hash, "status": status, "submitted_by": "t",
                "decided_by": None, "reason": None, "created_at": created_at or "2026-08-28T00:00:00+00:00",
                "decided_at": decided_at}
        (project / "operator" / "reviews" / f"{review_id}.json").write_text(
            json.dumps(data), encoding="utf-8")

    svc = ReviewService(project)
    # ① 按门筛选：存在 script_lock + sample 两类，各取各的
    _write("r-script", "approved", "1" * 64, decided_at="2026-08-28T09:00:00+00:00", kind="script_lock")
    _write("r-sample", "awaiting_human", "a" * 64, kind="sample")
    assert svc.subject_hash_for_gate("script_lock") == "1" * 64
    assert svc.subject_hash_for_gate("sample") == "a" * 64
    assert svc.subject_hash_for_gate("creative_lock") is None
    # ② pending 优先（sample 门）
    assert svc.subject_hash_for_gate("sample") == "a" * 64
    # ③ 无 pending：approved(较晚) > rejected(较早) > superseded(status，最晚但排除)
    (project / "operator" / "reviews" / "r-sample.json").unlink()
    _write("r-sup", "superseded", "d" * 64, decided_at="2026-08-28T10:00:00+00:00", kind="sample")
    _write("r-old", "rejected", "b" * 64, decided_at="2026-08-28T08:00:00+00:00", kind="sample")
    _write("r-new", "approved", "c" * 64, decided_at="2026-08-28T09:00:00+00:00", kind="sample")
    assert svc.subject_hash_for_gate("sample") == "c" * 64
    # ④ 全部清空 → None
    for f in (project / "operator" / "reviews").glob("*.json"):
        f.unlink()
    assert svc.subject_hash_for_gate("sample") is None


def test_read_path_purity(tmp_path: Path):
    """修正 3：连续读取不改变 review 数量、generation pointer、checkpoint 与事件文件。"""
    from backlot.operator_state import load_operator_state

    project = tmp_path / "proj"
    (project / "operator" / "operator-managed").mkdir(parents=True)
    (project / "artifacts").mkdir(parents=True)
    (project / "operator" / "reviews").mkdir(parents=True)
    (project / "artifacts" / "script.json").write_text(
        json.dumps({"version": "1.0", "sections": []}), encoding="utf-8")
    (project / "checkpoint_script.json").write_text(
        json.dumps({"version": "1", "project_id": "proj", "pipeline_type": "cinematic-fast",
                    "stage": "script", "status": "awaiting_human"}), encoding="utf-8")

    def snapshot():
        reviews = sorted(p.name for p in (project / "operator" / "reviews").glob("*.json"))
        pointer = (project / "generation" / "current.json").read_text() if (project / "generation" / "current.json").exists() else None
        cp = (project / "checkpoint_script.json").read_text()
        events = sorted(p.name for p in (project / "operator" / "events").glob("*")) if (project / "operator" / "events").exists() else []
        batch_snapshot = sorted(p.name for p in (project / "operator").glob("batch-*.json*"))
        return reviews, pointer, cp, events, batch_snapshot

    before = snapshot()
    with __import__("contextlib").nullcontext():
        load_operator_state(project)
        load_operator_state(project)
    after = snapshot()
    assert before == after, f"读取产生副作用: {before} -> {after}"

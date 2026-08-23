"""批事件流契约测试（Batch_Workbench_Aggregate_State_Event_Contract §5）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backlot.batch_events import (
    append_event,
    detect_gap,
    publish_snapshot,
    read_events,
)


def test_append_and_read_events_with_strict_seq(tmp_path: Path):
    batch_dir = tmp_path / "batch-mix-001"
    batch_dir.mkdir()
    first = append_event(batch_dir, type="snapshot_published", aggregate_revision="a" * 64, phase="building")
    second = append_event(
        batch_dir, type="candidate_changed", aggregate_revision="b" * 64,
        candidate_id="cand-01", candidate_revision="c" * 64, phase="sampling",
        payload={"changed_fields": ["status"]},
    )
    assert first["event_seq"] == 1
    assert second["event_seq"] == 2
    events = read_events(batch_dir)
    assert [e["event_seq"] for e in events] == [1, 2]
    assert read_events(batch_dir, after_seq=1) == [second]
    assert detect_gap(events) == []


def test_gap_detection_flags_missing_sequences():
    assert detect_gap([{"event_seq": 1}, {"event_seq": 3}]) == [2]
    assert detect_gap([{"event_seq": 5}]) == []


def test_snapshot_publish_dedup_and_changed_candidates(tmp_path: Path):
    batch_dir = tmp_path / "batch-mix-001"
    batch_dir.mkdir()
    first = publish_snapshot(
        batch_dir, aggregate_revision="a" * 64, phase="sampling",
        candidates={"cand-01": "r1", "cand-02": "r2"},
    )
    assert [e["type"] for e in first] == ["candidate_changed", "candidate_changed", "snapshot_published"]
    # 无变化 → 不重复发布
    assert publish_snapshot(
        batch_dir, aggregate_revision="a" * 64, phase="sampling",
        candidates={"cand-01": "r1", "cand-02": "r2"},
    ) == []
    # 一个候选变化 → 只发该候选的 candidate_changed
    third = publish_snapshot(
        batch_dir, aggregate_revision="b" * 64, phase="scoring",
        candidates={"cand-01": "r1", "cand-02": "r3"},
    )
    assert [e["type"] for e in third] == ["candidate_changed", "snapshot_published"]
    assert third[0]["candidate_id"] == "cand-02"
    assert third[0]["candidate_revision"] == "r3"
    # 事件严格递增、event_id 可去重
    all_events = read_events(batch_dir)
    seqs = [e["event_seq"] for e in all_events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    ids = [e["event_id"] for e in all_events]
    assert len(set(ids)) == len(ids)


def test_invalid_event_type_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        append_event(tmp_path / "b", type="nope", aggregate_revision="a" * 64)

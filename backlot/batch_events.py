"""批事件流（契约 §5）：批根项目 operator/batch-events.jsonl 的 append-only 事件。

事件不是状态真相；事件丢失时客户端必须通过 operator-state 重新拉取。
同一批的 event_seq 严格递增，消费者以 event_id 去重、以 event_seq 检测缺口。
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

EVENT_TYPES = frozenset({
    "snapshot_published",
    "phase_changed",
    "candidate_changed",
    "gate_changed",
    "selection_changed",
    "budget_changed",
    "consistency_warning",
    "action_recovered",
})

_EVENTS_FILE = "operator/batch-events.jsonl"
_SNAPSHOT_FILE = "operator/batch-last-snapshot.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _events(batch_dir: Path) -> list[dict[str, Any]]:
    path = batch_dir / _EVENTS_FILE
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return events


@contextmanager
def _locked(batch_dir: Path) -> Iterator[None]:
    lock_path = batch_dir / "operator" / "batch-events.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_event_locked(
    batch_dir: Path,
    *,
    type: str,
    aggregate_revision: str,
    candidate_id: str | None = None,
    candidate_revision: str | None = None,
    phase: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one event; 调用方必须已持有 _locked（避免 flock 重入死锁）。"""
    if type not in EVENT_TYPES:
        raise ValueError(f"invalid batch event type {type!r}")
    events = _events(batch_dir)
    seq = (int(events[-1]["event_seq"]) + 1) if events else 1
    event: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": f"batch-event-{seq:06d}",
        "event_seq": seq,
        "ts": _now(),
        "batch_id": str(batch_dir.name),
        "type": type,
        "aggregate_revision": str(aggregate_revision),
    }
    if candidate_id is not None:
        event["candidate_id"] = str(candidate_id)
    if candidate_revision is not None:
        event["candidate_revision"] = str(candidate_revision)
    if phase is not None:
        event["phase"] = str(phase)
    if payload is not None:
        event["payload"] = payload
    path = batch_dir / _EVENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event


def append_event(
    batch_dir: Path,
    *,
    type: str,
    aggregate_revision: str,
    candidate_id: str | None = None,
    candidate_revision: str | None = None,
    phase: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one event; returns the event (event_id 去重键、event_seq 递增)。"""
    batch_dir = Path(batch_dir)
    with _locked(batch_dir):
        return _append_event_locked(
            batch_dir,
            type=type,
            aggregate_revision=aggregate_revision,
            candidate_id=candidate_id,
            candidate_revision=candidate_revision,
            phase=phase,
            payload=payload,
        )


def read_events(batch_dir: Path, *, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    """补拉：返回 event_seq > after_seq 的事件，最多 limit 条。"""
    return [
        event for event in _events(Path(batch_dir))
        if int(event.get("event_seq") or 0) > after_seq
    ][:limit]


def detect_gap(events: list[dict[str, Any]]) -> list[int]:
    """检测 event_seq 缺口；消费者检测到缺口必须重新拉取完整状态。"""
    sequences = sorted(int(event.get("event_seq") or 0) for event in events)
    if not sequences:
        return []
    return [
        seq for seq in range(sequences[0], sequences[-1] + 1)
        if seq not in set(sequences)
    ]


def publish_snapshot(
    batch_dir: Path,
    *,
    aggregate_revision: str,
    phase: str,
    candidates: dict[str, str | None],
) -> list[dict[str, Any]]:
    """发布 snapshot_published + 变化候选的 candidate_changed（last-snapshot 去重）。"""
    batch_dir = Path(batch_dir)
    appended: list[dict[str, Any]] = []
    with _locked(batch_dir):
        snapshot_path = batch_dir / _SNAPSHOT_FILE
        previous: dict[str, Any] = {}
        if snapshot_path.is_file():
            try:
                previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
        changed = [
            candidate_id for candidate_id, revision in sorted(candidates.items())
            if previous.get(candidate_id) != revision
        ]
        if not changed and previous:
            return appended
        for candidate_id in changed:
            appended.append(_append_event_locked(
                batch_dir,
                type="candidate_changed",
                aggregate_revision=aggregate_revision,
                candidate_id=candidate_id,
                candidate_revision=candidates.get(candidate_id),
                phase=phase,
                payload={"changed_fields": []},
            ))
        appended.append(_append_event_locked(
            batch_dir,
            type="snapshot_published",
            aggregate_revision=aggregate_revision,
            phase=phase,
            payload={"candidates": candidates},
        ))
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(candidates, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    return appended

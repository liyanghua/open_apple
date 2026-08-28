"""Phase 2 展示层栅栏：批量提交进行中（fence 未放行）时，候选投影携带 fence 信息，
前端据此展示「批量提交进行中，结果稍后更新」并抑制刷新后的误导性结论。

状态判定：coordinator record.status ∈ {prepared, committing, needs_recovery} 且包含该候选。
"""
from __future__ import annotations

import json
from pathlib import Path

import backlot.batch_actions as ba

FENCE_STATUSES = {"prepared", "committing", "needs_recovery"}


def active_fence_for(batch_root: Path, project_id: str) -> dict | None:
    if not batch_root.is_dir():
        return None
    found = None
    for actions_dir in batch_root.glob(f"*/{ba._ACTIONS_DIR}"):
        for record_path in actions_dir.glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("status") not in FENCE_STATUSES:
                continue
            for participant in record.get("participants") or []:
                if str(participant.get("project_id")) == project_id:
                    found = {"batch_action_id": record.get("batch_action_id"),
                             "status": record.get("status"), "gate": record.get("gate"),
                             "project_id": project_id}
                    break
            if found:
                return found
    return found

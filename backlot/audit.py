"""Rebuildable, idempotent audit query projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from lib.cache_io import atomic_write_bytes


class AuditStore:
    def __init__(self, db_path: Path, jsonl_path: Path) -> None:
        self.db_path = Path(db_path)
        self.jsonl_path = Path(jsonl_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS operator_audit (
                    action_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY(action_id, event_type)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def materialize(self, stream: str, item: dict[str, Any]) -> None:
        if stream != "audit":
            return
        event = item.get("event") if isinstance(item, dict) else None
        if not isinstance(event, dict):
            return
        action_id = str(event.get("action_id") or "")
        event_type = str(event.get("event_type") or "")
        actor_id = str(event.get("actor_id") or "")
        summary = str(event.get("summary") or "")
        if not all((action_id, event_type, actor_id, summary)):
            return
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO operator_audit
                (action_id,event_type,actor_id,summary,event_json) VALUES (?,?,?,?,?)""",
                (
                    action_id, event_type, actor_id, summary,
                    json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            )
        self.rebuild_jsonl()

    def list_events(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM operator_audit ORDER BY rowid"
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def rebuild_jsonl(self) -> None:
        payload = b"".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            for event in self.list_events()
        )
        atomic_write_bytes(self.jsonl_path, payload)


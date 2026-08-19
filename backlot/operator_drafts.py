"""User-isolated typed draft persistence and conflict handling."""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from backlot.operator_adapters import get_adapter
from backlot.operator_errors import OperatorError
from lib.cache_io import atomic_write_json


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(item, child))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            identity = item.get("id", item.get("section_id", item.get("shot_id", index))) if isinstance(item, dict) else index
            child = f"{prefix}.{identity}" if prefix else str(identity)
            result.update(_flatten(item, child))
        return result
    return {prefix: value}


def _overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + ".") or right.startswith(left + ".")


class DraftService:
    def __init__(
        self,
        project_dir: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.project_id = self.project_dir.name
        try:
            marker = json.loads((self.project_dir / "project.json").read_text(encoding="utf-8"))
            self.project_id = str(marker.get("project_id") or self.project_id)
        except (OSError, json.JSONDecodeError):
            pass
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        schema_path = Path(__file__).parents[1] / "schemas/backlot/operator_draft.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    def _path(self, actor_id: str, stage: str) -> Path:
        if not _IDENTIFIER.fullmatch(actor_id) or stage not in {
            "research", "proposal", "script", "scene_plan", "assets", "sample", "edit",
            "delivery_review",
        }:
            raise OperatorError.validation_failed("草稿身份或阶段无效")
        return self.project_dir / "operator" / "drafts" / actor_id / f"{stage}.json"

    def save(
        self,
        *,
        actor_id: str,
        stage: str,
        base_revision: str,
        base_artifact_hash: str,
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        adapter = get_adapter(stage)
        adapter.touched_fields(changes)
        adapter.validate_project_operations(self.project_dir, changes)
        existing = self._read_file(actor_id, stage)
        now = self.clock().isoformat()
        draft = {
            "schema_version": "1.0",
            "draft_id": existing.get("draft_id", f"draft-{uuid.uuid4().hex}"),
            "project_id": self.project_id,
            "stage": stage,
            "base_revision": base_revision,
            "base_artifact_hash": base_artifact_hash,
            "adapter": adapter.adapter_id,
            "changes": changes,
            "status": "active",
            "created_by": actor_id,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        errors = list(self.validator.iter_errors(draft))
        if errors:
            raise OperatorError.validation_failed("草稿内容不符合要求")
        atomic_write_json(self._path(actor_id, stage), draft)
        return draft

    def _read_file(self, actor_id: str, stage: str) -> dict[str, Any]:
        path = self._path(actor_id, stage)
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorError("recovery_required", "草稿状态需要管理员恢复", 503) from exc
        return value if isinstance(value, dict) else {}

    def load(self, actor_id: str, stage: str) -> dict[str, Any] | None:
        draft = self._read_file(actor_id, stage)
        if not draft:
            return None
        terminal = self._terminal_status(str(draft.get("draft_id")))
        if terminal:
            draft["status"] = terminal
        return draft

    def discard(self, actor_id: str, stage: str) -> dict[str, Any]:
        draft = self._read_file(actor_id, stage)
        if not draft:
            raise OperatorError.validation_failed("没有可丢弃的草稿")
        draft["status"] = "discarded"
        draft["updated_at"] = self.clock().isoformat()
        atomic_write_json(self._path(actor_id, stage), draft)
        return draft

    def mark_stale(self, actor_id: str, stage: str) -> dict[str, Any]:
        draft = self._read_file(actor_id, stage)
        if not draft:
            raise OperatorError.validation_failed("没有可更新的草稿")
        draft["status"] = "stale"
        draft["updated_at"] = self.clock().isoformat()
        atomic_write_json(self._path(actor_id, stage), draft)
        return draft

    def rebase(
        self,
        draft: dict[str, Any],
        *,
        current_revision: str,
        current_artifact_hash: str,
        base_snapshot: dict[str, Any],
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        adapter = get_adapter(str(draft["stage"]))
        ours = adapter.touched_fields(draft.get("changes", []))
        old, current = _flatten(base_snapshot), _flatten(current_snapshot)
        theirs = {
            path for path in set(old) | set(current) if old.get(path) != current.get(path)
        }
        conflicts = sorted(
            ours_field
            for ours_field in ours
            if any(_overlap(ours_field, theirs_field) for theirs_field in theirs)
        )
        if conflicts:
            raise OperatorError(
                "revision_conflict",
                "当前内容已被其他修改更新",
                409,
                field_errors=[
                    {"field": field, "message": "该字段与你的草稿同时发生了变化"}
                    for field in conflicts
                ],
            )
        rebased = copy.deepcopy(draft)
        rebased.update(
            base_revision=current_revision,
            base_artifact_hash=current_artifact_hash,
            status="active",
            updated_at=self.clock().isoformat(),
        )
        persisted = dict(rebased)
        atomic_write_json(
            self._path(str(rebased["created_by"]), str(rebased["stage"])), persisted
        )
        rebased["preview_required"] = True
        return rebased

    def _terminal_status(self, draft_id: str) -> str | None:
        generations = self.project_dir / "operator" / "generations"
        if not generations.exists():
            return None
        for directory in sorted(generations.glob("generation-*"), reverse=True):
            try:
                if (directory / "status").read_text(encoding="ascii") != "committed":
                    continue
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            transition = manifest.get("draft_transition") or {}
            if transition.get("draft_id") == draft_id:
                return transition.get("status")
        return None

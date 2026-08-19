"""Shared contract for fixed Backlot stage adapters."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backlot.operator_errors import OperatorError


def invalid(message: str, field: str = "changes") -> OperatorError:
    return OperatorError.validation_failed(
        message, field_errors=[{"field": field, "message": message}]
    )


def item_by_id(items: list[dict[str, Any]], item_id: str, label: str) -> dict[str, Any]:
    for item in items:
        if item.get("id", item.get(f"{label}_id")) == item_id:
            return item
    raise invalid(f"找不到指定的{label}", f"{label}.{item_id}")


def reorder(items: list[dict[str, Any]], ids: list[str], label: str) -> list[dict[str, Any]]:
    indexed = {
        str(item.get("id", item.get(f"{label}_id"))): item for item in items
    }
    if len(ids) != len(set(ids)) or set(ids) != set(indexed):
        raise invalid(f"{label}排序必须完整且不能重复", label)
    return [indexed[item_id] for item_id in ids]


class BaseAdapter:
    stage = ""
    adapter_id = ""
    artifact_name = ""
    operation_fields: dict[str, frozenset[str]] = {}
    field_labels: dict[str, str] = {}

    def load_snapshot(self, project_dir: Path) -> dict[str, Any]:
        path = Path(project_dir) / "artifacts" / f"{self.artifact_name}.json"
        if not path.exists():
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("data"), dict):
            loaded = loaded["data"]
        if not isinstance(loaded, dict):
            raise invalid("当前阶段内容无法编辑")
        return loaded

    def _check_operation(self, operation: dict[str, Any]) -> str:
        if not isinstance(operation, dict):
            raise invalid("修改内容格式不正确")
        name = operation.get("op")
        allowed = self.operation_fields.get(str(name))
        if allowed is None or set(operation) != allowed:
            raise invalid("该修改类型或字段不受支持")
        return str(name)

    def apply(
        self,
        snapshot: dict[str, Any],
        operations: list[dict[str, Any]],
        *,
        validate: bool = True,
    ) -> dict[str, Any]:
        changed = copy.deepcopy(snapshot)
        for operation in operations:
            name = self._check_operation(operation)
            self._apply_one(changed, name, operation)
        if validate:
            self.validate(changed)
        return changed

    def _apply_one(
        self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]
    ) -> None:
        raise NotImplementedError

    def validate(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        return []

    def validate_project_operations(
        self, project_dir: Path, operations: list[dict[str, Any]]
    ) -> None:
        """Validate operations that depend on the current project projection."""
        return None

    def touched_fields(self, operations: list[dict[str, Any]]) -> set[str]:
        fields: set[str] = set()
        for operation in operations:
            name = self._check_operation(operation)
            fields.add(self._touched_field(name, operation))
        return fields

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        return name

    def diff(
        self, before: dict[str, Any], after: dict[str, Any]
    ) -> list[str]:
        changes = []
        for field, label in self.field_labels.items():
            if before.get(field) != after.get(field):
                changes.append(f"{label}已调整")
        if not changes and before != after:
            changes.append("阶段内容已调整")
        return changes

    def change_signals(
        self, operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        for operation in operations:
            self._check_operation(operation)
        return {
            "reopen_creative": False,
            "reopen_sample": False,
            "render_route": "no_render",
        }

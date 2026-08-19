from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import BaseAdapter, invalid


_KINDS = {"cover", "hook", "bgm", "ending"}


class DeliveryReviewAdapter(BaseAdapter):
    """Constrained operator decisions for producing a new certified version."""

    stage = "delivery_review"
    adapter_id = "delivery-review-v1"
    artifact_name = "delivery_review"
    operation_fields = {
        "select_delivery_candidate": frozenset({"op", "candidate_kind", "candidate_id"}),
        "replace_delivery_copy": frozenset({"op", "section_id", "text"}),
        "clear_delivery_selection": frozenset({"op", "kind"}),
    }
    field_labels = {
        "selected_cover_id": "封面",
        "selected_hook_id": "前三秒",
        "selected_bgm_id": "背景音乐",
        "selected_bgm_volume": "背景音乐音量",
        "selected_ending_id": "结尾",
        "copy_overrides": "文案",
    }

    def load_snapshot(self, project_dir: Path) -> dict[str, Any]:
        loaded = super().load_snapshot(project_dir)
        if loaded:
            return loaded
        project_dir = Path(project_dir)
        try:
            marker = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker = {}
        try:
            report = json.loads((project_dir / "artifacts/render_report.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {}
        if isinstance(report.get("data"), dict):
            report = report["data"]
        try:
            current = json.loads((project_dir / "operator/current-delivery.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        output = next(
            (item for item in report.get("outputs", []) if isinstance(item, dict)), {}
        )
        render_id = str(report.get("video_master_sha256") or Path(str(output.get("path") or "current-render")).stem)
        return {
            "schema_version": "1.0",
            "project_id": str(marker.get("project_id") or project_dir.name),
            "base_render_id": render_id,
            "base_version_id": str(current.get("version_id") or "legacy-current"),
            "selected_cover_id": None,
            "selected_hook_id": None,
            "selected_bgm_id": None,
            "selected_ending_id": None,
            "copy_overrides": [],
            "updated_by": "system",
            "updated_at": str(marker.get("updated_at") or marker.get("created_at") or "1970-01-01T00:00:00Z"),
        }

    @staticmethod
    def _selection_field(kind: str) -> str:
        if kind not in _KINDS:
            raise invalid("候选类型不受支持")
        return f"selected_{kind}_id"

    def _check_operation(self, operation: dict[str, Any]) -> str:
        if (
            isinstance(operation, dict)
            and operation.get("op") == "select_delivery_candidate"
            and operation.get("candidate_kind") == "bgm"
            and set(operation) == {"op", "candidate_kind", "candidate_id", "volume"}
        ):
            return "select_delivery_candidate"
        if (
            isinstance(operation, dict)
            and operation.get("op") == "replace_delivery_copy"
            and set(operation) == {"op", "section_id", "text", "sync_narration"}
        ):
            return "replace_delivery_copy"
        return super()._check_operation(operation)

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        if name == "select_delivery_candidate":
            kind = str(operation["candidate_kind"])
            field = self._selection_field(kind)
            candidate_id = operation["candidate_id"]
            if candidate_id is not None and not str(candidate_id).startswith(f"{kind}-"):
                raise invalid("候选与调整类型不匹配")
            snapshot[field] = candidate_id
            if kind == "bgm" and "volume" in operation:
                volume = operation["volume"]
                if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not 0 <= volume <= 1:
                    raise invalid("背景音乐音量不符合要求")
                snapshot["selected_bgm_volume"] = volume
            return
        if name == "clear_delivery_selection":
            field = self._selection_field(str(operation["kind"]))
            snapshot[field] = None
            if field == "selected_bgm_id":
                snapshot.pop("selected_bgm_volume", None)
            return
        overrides = snapshot.setdefault("copy_overrides", [])
        section_id = str(operation["section_id"])
        existing = next(
            (item for item in overrides if item.get("segment_id") == section_id), None
        )
        value = {
            "segment_id": section_id,
            "text": operation["text"],
            "sync_narration": operation.get("sync_narration", True),
        }
        if existing is None:
            overrides.append(value)
        else:
            existing.update(value)

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        if name == "replace_delivery_copy":
            return f"copy_overrides.{operation['section_id']}"
        if name == "clear_delivery_selection":
            return self._selection_field(str(operation["kind"]))
        return self._selection_field(str(operation["candidate_kind"]))

    def validate(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        warnings = []
        for item in snapshot.get("copy_overrides") or []:
            if not isinstance(item, dict) or not item.get("segment_id"):
                raise invalid("文案修改内容不符合要求")
            item.setdefault("sync_narration", True)
            if item.get("sync_narration") is False:
                warnings.append({"field": "copy_overrides", "message": "文案未同步口播，成片可能出现音画不一致"})
        return warnings

    def validate_project_operations(
        self, project_dir: Path, operations: list[dict[str, Any]]
    ) -> None:
        from backlot.operator_state import delivery_candidate_ids

        allowed = delivery_candidate_ids(project_dir)
        for operation in operations:
            name = self._check_operation(operation)
            if name != "select_delivery_candidate" or operation.get("candidate_id") is None:
                continue
            kind = str(operation["candidate_kind"])
            candidate_id = str(operation["candidate_id"])
            if candidate_id not in allowed.get(kind, set()):
                raise invalid(
                    "候选不属于当前项目或当前成片版本，请刷新后重新选择",
                    f"{kind}.{candidate_id}",
                )

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        names = {self._check_operation(item) for item in operations}
        copy_items = [item for item in operations if item.get("op") == "replace_delivery_copy"]
        copy_with_voice = any(item.get("sync_narration", True) for item in copy_items)
        only_cover = bool(names) and names <= {"select_delivery_candidate", "clear_delivery_selection"} and all(
            item.get("candidate_kind", item.get("kind")) == "cover" for item in operations
        )
        only_audio = bool(names) and names <= {"select_delivery_candidate", "clear_delivery_selection"} and all(
            item.get("candidate_kind", item.get("kind")) == "bgm" for item in operations
        )
        return {
            "reopen_creative": copy_with_voice,
            "reopen_sample": not only_cover,
            "render_route": "no_render" if only_cover else "mux_only" if only_audio else "full_render",
        }

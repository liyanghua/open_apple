"""Append-only review decisions that preserve the certified compose state."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from backlot.operator_adapters import get_adapter
from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes, semantic_sha256
from schemas.artifacts import validate_artifact


def _display(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"{len(value)}项内容" if isinstance(value, list) else "已配置"


def _lookup(snapshot: dict[str, Any], field: str) -> Any:
    cursor: Any = snapshot
    for part in field.split("."):
        if isinstance(cursor, dict):
            cursor = cursor.get(part)
        elif isinstance(cursor, list):
            cursor = next(
                (
                    item for item in cursor
                    if isinstance(item, dict)
                    and str(item.get("segment_id", item.get("id"))) == part
                ),
                None,
            )
        else:
            return None
    return cursor


class DeliveryReviewRevisionService:
    """Commit delivery-review drafts without invalidating compose artifacts."""

    def __init__(
        self,
        project_dir: Path,
        *,
        store: ProjectCommitStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.store = store or ProjectCommitStore(self.project_dir)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.adapter = get_adapter("delivery_review")
        schema_path = Path(__file__).parents[1] / "schemas/backlot/operator_revision.schema.json"
        self.revision_validator = Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )

    @property
    def revision_dir(self) -> Path:
        return self.project_dir / "operator/revisions/delivery_review"

    def load_snapshot(self) -> dict[str, Any]:
        return self.adapter.load_snapshot(self.project_dir)

    def list(self) -> list[dict[str, Any]]:
        revisions = []
        for path in sorted(self.revision_dir.glob("*.json")) if self.revision_dir.exists() else []:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                revisions.append(value)
        return revisions

    def _find(self, revision_id: str) -> dict[str, Any]:
        for revision in self.list():
            if revision.get("revision_id") == revision_id:
                return revision
        raise OperatorError.validation_failed("找不到指定的成片审核版本")

    def commit(
        self,
        *,
        draft: dict[str, Any],
        actor_id: str,
        reason: str,
        preview_token: str,
        impact_service: Any,
        base_generation: str,
        base_snapshot: dict[str, Any],
        idempotency_key: str | None = None,
        request_digest: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            generations = self.project_dir / "operator/generations"
            for directory in sorted(generations.glob("generation-*"), reverse=True) if generations.exists() else []:
                try:
                    if (directory / "status").read_text(encoding="ascii") != "committed":
                        continue
                    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                action = manifest.get("action") or {}
                if action.get("idempotency_key") != idempotency_key:
                    continue
                if action.get("request_digest") != request_digest:
                    raise OperatorError("idempotency_conflict", "该请求标识已用于其他内容", 409)
                return self._find(str(manifest.get("result", {}).get("revision_id") or ""))
        if draft.get("stage") != "delivery_review":
            raise OperatorError.validation_failed("成片审核草稿类型不正确")
        if draft.get("created_by") != actor_id or draft.get("status") != "active":
            raise OperatorError("forbidden", "该草稿不可由当前用户提交", 403)
        self.adapter.validate_project_operations(self.project_dir, draft.get("changes", []))
        impact_service.verify_token(
            preview_token,
            draft=draft,
            actor_id=actor_id,
            base_generation=base_generation,
        )
        pointer = self.store.initialize()
        if pointer["generation_id"] != base_generation:
            raise OperatorError("revision_conflict", "当前版本已更新，请重新预览", 409)
        result = self.adapter.apply(base_snapshot, draft.get("changes", []))
        result["updated_by"] = actor_id
        result["updated_at"] = self.clock().isoformat()
        validate_artifact("delivery_review", result)
        canonical = attach_hashes(result)
        revisions = self.list()
        revision_id = f"rev-{uuid.uuid4().hex}"
        labels = self.adapter.diff(base_snapshot, result)
        changes = []
        for index, field in enumerate(sorted(self.adapter.touched_fields(draft.get("changes", [])))):
            changes.append({
                "field": field,
                "label": labels[min(index, len(labels) - 1)] if labels else "成片审核内容已调整",
                "before": _display(_lookup(base_snapshot, field)),
                "after": _display(_lookup(result, field)),
            })
        revision = {
            "schema_version": "1.0",
            "revision_id": revision_id,
            "parent_revision_id": revisions[-1]["revision_id"] if revisions else None,
            "project_id": self.store.project_id,
            "artifact_name": "delivery_review",
            "base_semantic_sha256": semantic_sha256(base_snapshot),
            "result_semantic_sha256": semantic_sha256(canonical),
            "actor_id": actor_id,
            "reason": reason,
            "created_at": self.clock().isoformat(),
            "snapshot": canonical,
            "changes": changes,
        }
        if list(self.revision_validator.iter_errors(revision)):
            raise OperatorError.validation_failed("成片审核版本内容不符合要求")
        sequence = len(revisions) + 1
        action = {"action_id": f"commit-{revision_id}", "type": "commit_delivery_review"}
        if idempotency_key:
            action.update(idempotency_key=idempotency_key, request_digest=request_digest)
        with self.store.transaction(
            action=action,
            result={"status": "queued", "revision_id": revision_id},
            audit={"event_type": "delivery_review_committed", "actor_id": actor_id},
            draft_transition={"draft_id": draft["draft_id"], "status": "committed"},
            business_diff=labels,
            expected_generation=base_generation,
        ) as sink:
            sink.stage_json("artifacts/delivery_review.json", canonical, schema="delivery_review")
            sink.stage_json(
                f"operator/revisions/delivery_review/{sequence:06d}-{revision_id}.json",
                revision,
                schema="operator_revision",
            )
            sink.stage_json(
                "operator/current-revisions/delivery_review.json",
                {"revision_id": revision_id, "artifact_name": "delivery_review"},
                schema="revision_pointer",
            )
            sink.append_event("actions", {
                "event_type": "delivery_generation_requested",
                "review_revision_id": revision_id,
                "actor_id": actor_id,
            })
        return revision

"""Append-only business revisions for typed operator edits."""

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


def _display(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"{len(value)}项内容" if isinstance(value, list) else "已配置"


def _lookup(snapshot: dict[str, Any], field: str) -> Any:
    cursor: Any = snapshot
    for part in field.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        elif isinstance(cursor, list):
            cursor = next(
                (
                    item for item in cursor
                    if isinstance(item, dict)
                    and str(item.get("id", item.get("section_id", item.get("shot_id")))) == part
                ),
                None,
            )
        else:
            return None
    return cursor


class RevisionService:
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
        schema_path = Path(__file__).parents[1] / "schemas/backlot/operator_revision.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    def _revision_dir(self, stage: str) -> Path:
        get_adapter(stage)
        return self.project_dir / "operator" / "revisions" / stage

    def list(self, stage: str) -> list[dict[str, Any]]:
        directory = self._revision_dir(stage)
        revisions = []
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                revisions.append(value)
        return revisions

    def _find(self, stage: str, revision_id: str) -> dict[str, Any]:
        for revision in self.list(stage):
            if revision.get("revision_id") == revision_id:
                return revision
        raise OperatorError.validation_failed("找不到指定版本")

    def commit_draft(
        self,
        *,
        draft: dict[str, Any],
        actor_id: str,
        reason: str,
        preview_token: str,
        impact_service,
        base_generation: str,
        base_snapshot: dict[str, Any],
        idempotency_key: str | None = None,
        request_digest: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            for directory in sorted(
                (self.project_dir / "operator/generations").glob("generation-*"),
                reverse=True,
            ):
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
                return self._find(str(draft["stage"]), manifest["result"]["revision_id"])
        if draft.get("created_by") != actor_id or draft.get("status") not in {"active", "stale"}:
            raise OperatorError("forbidden", "该草稿不可由当前用户提交", 403)
        impact_service.verify_token(
            preview_token,
            draft=draft,
            actor_id=actor_id,
            base_generation=base_generation,
        )
        pointer = self.store.initialize()
        if pointer["generation_id"] != base_generation:
            raise OperatorError("revision_conflict", "当前版本已更新，请重新预览", 409)
        adapter = get_adapter(str(draft["stage"]))
        result = adapter.apply(base_snapshot, draft.get("changes", []))
        artifact_snapshot = (
            result.get("research_annotations", {})
            if draft["stage"] == "research"
            else result
        )
        clean = dict(artifact_snapshot)
        clean.pop("semantic_sha256", None)
        clean.pop("artifact_sha256", None)
        canonical = attach_hashes(clean)
        revisions = self.list(str(draft["stage"]))
        parent = revisions[-1]["revision_id"] if revisions else None
        revision_id = f"rev-{uuid.uuid4().hex}"
        labels = adapter.diff(base_snapshot, result)
        touched = sorted(adapter.touched_fields(draft.get("changes", [])))
        changes = [
            {
                "field": field,
                "label": labels[min(index, len(labels) - 1)] if labels else "内容已调整",
                "before": _display(_lookup(base_snapshot, field)),
                "after": _display(_lookup(result, field)),
            }
            for index, field in enumerate(touched)
        ]
        revision = {
            "schema_version": "1.0",
            "revision_id": revision_id,
            "parent_revision_id": parent,
            "project_id": self.store.project_id,
            "artifact_name": adapter.artifact_name,
            "base_semantic_sha256": semantic_sha256(base_snapshot) if base_snapshot else None,
            "result_semantic_sha256": semantic_sha256(canonical),
            "actor_id": actor_id,
            "reason": reason,
            "created_at": self.clock().isoformat(),
            "snapshot": canonical,
            "changes": changes,
        }
        errors = list(self.validator.iter_errors(revision))
        if errors:
            raise OperatorError.validation_failed("版本内容不符合要求")
        sequence = len(revisions) + 1
        revision_relative = (
            f"operator/revisions/{draft['stage']}/{sequence:06d}-{revision_id}.json"
        )
        action = {"action_id": f"commit-{revision_id}", "type": "commit_draft"}
        if idempotency_key:
            action.update(
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
        with self.store.transaction(
            action=action,
            result={"status": "committed", "revision_id": revision_id},
            audit={"event_type": "revision_committed", "actor_id": actor_id},
            draft_transition={"draft_id": draft["draft_id"], "status": "committed"},
            business_diff=labels,
        ) as sink:
            sink.stage_json(
                f"artifacts/{adapter.artifact_name}.json",
                canonical,
                schema=adapter.artifact_name,
            )
            sink.stage_json(revision_relative, revision, schema="operator_revision")
            sink.stage_json(
                f"operator/current-revisions/{draft['stage']}.json",
                {"revision_id": revision_id, "artifact_name": adapter.artifact_name},
                schema="revision_pointer",
            )
            checkpoint = self.project_dir / f"checkpoint_{draft['stage']}.json"
            if checkpoint.exists():
                sink.stage_delete(checkpoint.relative_to(self.project_dir).as_posix())
        return revision

    def compare(
        self,
        stage: str,
        from_revision_id: str | None,
        to_revision_id: str,
        *,
        base_snapshot: dict[str, Any] | None = None,
    ) -> list[str]:
        target = self._find(stage, to_revision_id)
        source = self._find(stage, from_revision_id) if from_revision_id else None
        before = source["snapshot"] if source else (base_snapshot or {})
        return get_adapter(stage).diff(before, target["snapshot"])

    def prepare_restore(
        self, stage: str, revision_id: str, *, actor_id: str
    ) -> dict[str, Any]:
        revision = self._find(stage, revision_id)
        return {
            "restore_id": f"restore-{uuid.uuid4().hex}",
            "stage": stage,
            "source_revision_id": revision_id,
            "actor_id": actor_id,
            "snapshot": revision["snapshot"],
            "requires_impact_preview": True,
        }

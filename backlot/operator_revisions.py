"""Append-only business revisions for typed operator edits."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, ValidationError

from backlot.operator_adapters import get_adapter
from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes, semantic_sha256
from schemas.artifacts import validate_artifact


_RESEARCH_ANNOTATION_COLLECTIONS: dict[str, type] = {
    "media_dispositions": dict,
    "logo_usage": dict,
    "claim_boundaries": dict,
    "reference_methods": dict,
    "direction_preferences": dict,
    "matrix_resolutions": dict,
    "local_reanalysis_requests": list,
    "business_notes": dict,
}


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _research_annotations_artifact(
    result: dict[str, Any],
    *,
    project_id: str,
    revision_id: str,
    created_at: str,
    fallback_base_research_revision: Any,
) -> dict[str, Any]:
    nested = result.get("research_annotations")
    annotations = nested if isinstance(nested, dict) else result
    base_research_revision = annotations.get("base_research_revision")
    if not _is_sha256(base_research_revision):
        base_research_revision = fallback_base_research_revision
    base_research_revision = str(base_research_revision).lower()

    input_hashes = annotations.get("input_hashes")
    if not isinstance(input_hashes, dict):
        input_hashes = {}
    else:
        input_hashes = dict(input_hashes)
    input_hashes.setdefault("base_research_revision", base_research_revision)

    artifact: dict[str, Any] = {
        "version": str(annotations.get("version") or "1.0"),
        "project_id": project_id,
        "created_at": created_at,
        "producer": "backlot.operator_revisions",
        "input_hashes": input_hashes,
        "revision_id": revision_id,
        "base_research_revision": base_research_revision,
    }
    for name, collection_type in _RESEARCH_ANNOTATION_COLLECTIONS.items():
        artifact[name] = annotations.get(name, collection_type())
    return artifact


def _validate_research_annotations(artifact: dict[str, Any]) -> None:
    try:
        validate_artifact("research_annotations", artifact)
    except ValidationError as exc:
        raise OperatorError.validation_failed("研究标注内容不符合要求") from exc


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
        revisions = self.list(str(draft["stage"]))
        parent = revisions[-1]["revision_id"] if revisions else None
        revision_id = f"rev-{uuid.uuid4().hex}"
        created_at = self.clock().isoformat()
        clean = (
            _research_annotations_artifact(
                result,
                project_id=self.store.project_id,
                revision_id=revision_id,
                created_at=created_at,
                fallback_base_research_revision=(
                    draft.get("base_revision")
                    if _is_sha256(draft.get("base_revision"))
                    else draft["base_artifact_hash"]
                ),
            )
            if draft["stage"] == "research"
            else dict(result)
        )
        clean.pop("semantic_sha256", None)
        clean.pop("artifact_sha256", None)
        if draft["stage"] in {"script", "assets"} and clean.get("status") == "approved":
            clean["approval"] = {
                "approved_by": actor_id,
                "approved_at": created_at,
            }
        canonical = attach_hashes(clean)
        if draft["stage"] == "research":
            _validate_research_annotations(canonical)
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
            "created_at": created_at,
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
            expected_generation=base_generation,
        ) as sink:
            sink.stage_json(
                f"artifacts/{adapter.artifact_name}.json",
                canonical,
                schema=adapter.artifact_name,
            )
            if draft["stage"] == "proposal" and isinstance(canonical.get("creative_control_plan"), dict):
                plan = dict(canonical["creative_control_plan"])
                plan.pop("semantic_sha256", None)
                plan.pop("artifact_sha256", None)
                plan_artifact = {
                    "version": "1.0", "project_id": self.store.project_id,
                    "created_at": created_at, "producer": "backlot.operator_revisions",
                    "input_hashes": {"proposal_packet": semantic_sha256(canonical)},
                    "plan_id": str(plan.get("plan_id") or f"creative-control-{self.store.project_id}"),
                    "plan_version": int(plan.get("plan_version") or 1),
                    "status": str(plan.get("status") or "draft"),
                    "selected_direction_id": str(plan.get("selected_direction_id") or canonical.get("selected_concept_id") or "selected"),
                    "sections": plan.get("sections") or {},
                    "section_reviews": plan.get("section_reviews") or {},
                    "feedback": plan.get("feedback") or {},
                }
                if plan_artifact["status"] == "approved":
                    plan_artifact.update({"locked_at": created_at, "locked_by": actor_id})
                sink.stage_json("artifacts/creative_control_plan.json", attach_hashes(plan_artifact), schema="creative_control_plan")
            sink.stage_json(revision_relative, revision, schema="operator_revision")
            sink.stage_json(
                f"operator/current-revisions/{draft['stage']}.json",
                {"revision_id": revision_id, "artifact_name": adapter.artifact_name},
                schema="revision_pointer",
            )
            # Research annotations are human decisions on completed evidence.
            # They enrich the next stage; they do not invalidate the Research
            # checkpoint or force its completed state back to pending.
            if draft["stage"] != "research":
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
            "restore_id": f"restore-{semantic_sha256({'stage': stage, 'revision_id': revision_id, 'actor_id': actor_id})[:32]}",
            "stage": stage,
            "source_revision_id": revision_id,
            "actor_id": actor_id,
            "snapshot": revision["snapshot"],
            "requires_impact_preview": True,
        }

    def commit_restore(
        self,
        *,
        stage: str,
        revision_id: str,
        actor_id: str,
        reason: str,
        current_snapshot: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
        expected_generation: str | None = None,
    ) -> dict[str, Any]:
        for directory in sorted((self.project_dir / "operator/generations").glob("generation-*"), reverse=True):
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
            return self._find(stage, manifest["result"]["revision_id"])
        target = self._find(stage, revision_id)
        adapter = get_adapter(stage)
        revisions = self.list(stage)
        parent = revisions[-1]["revision_id"] if revisions else None
        result_id = f"rev-{uuid.uuid4().hex}"
        created_at = self.clock().isoformat()
        restored_snapshot = target["snapshot"]
        if stage == "research":
            clean = _research_annotations_artifact(
                restored_snapshot,
                project_id=self.store.project_id,
                revision_id=result_id,
                created_at=created_at,
                fallback_base_research_revision=restored_snapshot.get(
                    "base_research_revision"
                ),
            )
            restored_snapshot = attach_hashes(clean)
            _validate_research_annotations(restored_snapshot)
        labels = adapter.diff(current_snapshot, restored_snapshot)
        revision = {
            "schema_version": "1.0", "revision_id": result_id,
            "parent_revision_id": parent, "project_id": self.store.project_id,
            "artifact_name": adapter.artifact_name,
            "base_semantic_sha256": semantic_sha256(current_snapshot) if current_snapshot else None,
            "result_semantic_sha256": semantic_sha256(restored_snapshot),
            "actor_id": actor_id, "reason": reason or "恢复历史版本",
            "created_at": created_at, "snapshot": restored_snapshot,
            "changes": [{"field": "restored_revision", "label": label, "before": None, "after": "已恢复"} for label in labels] or [{"field": "restored_revision", "label": "已恢复历史版本", "before": None, "after": "已恢复"}],
        }
        errors = list(self.validator.iter_errors(revision))
        if errors:
            raise OperatorError.validation_failed("恢复版本内容不符合要求")
        relative = f"operator/revisions/{stage}/{len(revisions) + 1:06d}-{result_id}.json"
        with self.store.transaction(
            action={"action_id": f"restore-{result_id}", "type": "restore_revision", "idempotency_key": idempotency_key, "request_digest": request_digest},
            result={"status": "committed", "revision_id": result_id},
            audit={"event_type": "revision_restored", "actor_id": actor_id},
            business_diff=labels,
            expected_generation=expected_generation,
        ) as sink:
            sink.stage_json(f"artifacts/{adapter.artifact_name}.json", restored_snapshot, schema=adapter.artifact_name)
            sink.stage_json(relative, revision, schema="operator_revision")
            sink.stage_json(f"operator/current-revisions/{stage}.json", {"revision_id": result_id, "artifact_name": adapter.artifact_name}, schema="revision_pointer")
            if stage != "research":
                checkpoint = self.project_dir / f"checkpoint_{stage}.json"
                if checkpoint.exists():
                    sink.stage_delete(checkpoint.relative_to(self.project_dir).as_posix())
        return revision

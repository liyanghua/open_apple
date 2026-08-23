"""Secure v2 routes for the typed Backlot operator workbench."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote_to_bytes

from fastapi import APIRouter, Request

from backlot.operator_adapters import get_adapter
from backlot.operator_drafts import DraftService
from backlot.batch_actions import BatchActionService
from backlot.delivery_review_revisions import DeliveryReviewRevisionService
from backlot.operator_errors import OperatorError
from backlot.operator_impact import ImpactService
from backlot.operator_migration import OperatorMigrationService
from backlot.operator_revisions import RevisionService
from backlot.operator_reviews import ReviewService
from backlot.project_commit import ProjectCommitStore
from backlot.project_creation import ProjectCreationService
from backlot.skill_catalog import SkillCatalog
from backlot.shot_generation import ShotGenerationService
from lib.artifact_hashing import semantic_sha256


def _existing_review_note_for_idempotency_key(
    project_dir: Path, event: dict[str, Any]
) -> dict[str, Any] | None:
    """Return an identical prior note or reject reuse of its idempotency key."""
    key = event.get("idempotency_key")
    if not key:
        return None
    path = project_dir / "review_notes.jsonl"
    if not path.exists():
        return None
    semantic_fields = ("actor", "note", "stage", "version_ref")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            existing = json.loads(line)
            if existing.get("idempotency_key") != key:
                continue
            if any(existing.get(field) != event.get(field) for field in semantic_fields):
                raise OperatorError(
                    "idempotency_conflict",
                    "同一重复提交标识不能用于不同的审核意见",
                    409,
                )
            return existing
    return None


def _review_notes_materializer(project_dir: Path) -> Callable[[str, dict[str, Any]], None]:
    """Outbox materializer for the review-notes store.

    Runs inside the commit store's drain step, which holds the project lock.
    Recovery rules (review P1-②):

    - ``review_notes``: idempotent replay — the line keeps ``_outbox_id`` so a
      re-drain after a crash cannot duplicate it, and the client
      ``idempotency_key`` is also checked against existing lines;
    - ``events`` and any other stream: delegated to the canonical default-drain
      behavior (project events.jsonl / operator dir, dedupe by ``_outbox_id``),
      so an undrained ``events`` outbox is never silently dropped.
    """

    def _default_target_and_dedupe(stream: str) -> tuple[Path, set[str]]:
        if stream == "events":
            target = project_dir / "events.jsonl"
        else:
            target = project_dir / "operator" / f"{stream}.jsonl"
        delivered: set[str] = set()
        if target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                with contextlib.suppress(json.JSONDecodeError):
                    delivered.add(json.loads(line).get("_outbox_id", ""))
        return target, delivered

    def materialize(stream: str, item: dict[str, Any]) -> None:
        event = dict(item.get("event") or {})
        outbox_id = item.get("outbox_id", "")
        if stream == "review_notes":
            path = project_dir / "review_notes.jsonl"
            existing: list[dict[str, Any]] = []
            if path.exists():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    with contextlib.suppress(json.JSONDecodeError):
                        existing.append(json.loads(line))
            if any(note.get("_outbox_id") == outbox_id for note in existing):
                return  # crash replay of the same generation
            if event.get("idempotency_key"):
                try:
                    same_key = _existing_review_note_for_idempotency_key(
                        project_dir, event
                    )
                except OperatorError:
                    # The API rejects conflicts before commit. A legacy/corrupt
                    # committed outbox must still drain instead of wedging all
                    # future project transactions.
                    return
                if same_key is not None:
                    return
            event["_outbox_id"] = outbox_id
            line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
            existing_bytes = path.read_bytes() if path.exists() else b""
            fd, tmp_path = tempfile.mkstemp(dir=project_dir, prefix=".review_notes-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(existing_bytes + line.encode("utf-8"))
                os.replace(tmp_path, path)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp_path)
            return
        # Canonical default-drain delegation for every other stream.
        target, delivered = _default_target_and_dedupe(stream)
        if outbox_id in delivered:
            return
        event["_outbox_id"] = outbox_id
        existing_bytes = target.read_bytes() if target.exists() else b""
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".outbox-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(existing_bytes + json.dumps(event, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
            os.replace(tmp_path, target)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_path)

    return materialize


def create_operator_router(
    *,
    resolve_project: Callable[[str], Path],
    projects_dir: Callable[[], Path],
    auth_store: Callable[[], Any],
    authenticate: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/v2")
    preview_secret = secrets.token_bytes(32)

    async def body(request: Request) -> dict[str, Any]:
        try:
            value = await request.json()
        except Exception as exc:
            raise OperatorError.validation_failed("请求内容格式不正确") from exc
        if not isinstance(value, dict):
            raise OperatorError.validation_failed("请求内容格式不正确")
        return value

    def project(project_id: str) -> Path:
        return resolve_project(project_id)

    def snapshot(project_dir: Path, stage: str) -> dict[str, Any]:
        return get_adapter(stage).load_snapshot(project_dir)

    def catalog() -> SkillCatalog:
        return SkillCatalog(Path(__file__).parents[1] / "skills" / "catalog")

    @router.post("/projects/{project_id}/inputs/{kind}")
    async def upload_input(project_id: str, kind: str, request: Request) -> dict:
        """Store one browser-selected media file under the project inputs."""
        authenticate(request, project_id, "edit", csrf=True)
        if kind not in {"reference", "source"}:
            raise OperatorError.validation_failed("素材类型不受支持")
        encoded_name = request.headers.get("x-upload-path", "").strip()
        try:
            raw_name = unquote_to_bytes(encoded_name).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OperatorError.validation_failed("素材文件名编码不正确") from exc
        relative = PurePosixPath(raw_name)
        if not raw_name or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise OperatorError.validation_failed("素材文件名不安全")
        if len(relative.parts) > 2:
            relative = PurePosixPath(relative.parts[-1])
        filename = relative.name
        if Path(filename).suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".jpg", ".jpeg", ".png", ".webp", ".wav", ".mp3", ".m4a"}:
            raise OperatorError.validation_failed("只支持常见视频、图片和音频格式")
        project_dir = project(project_id)
        target_dir = project_dir / ("inputs/reference" if kind == "reference" else "inputs/source/video/product")
        target_dir.mkdir(parents=True, exist_ok=True)
        if project_dir.resolve() not in target_dir.resolve().parents:
            raise OperatorError.validation_failed("素材目录不安全")
        target = (target_dir / filename).resolve()
        if target.parent != target_dir.resolve():
            raise OperatorError.validation_failed("素材文件名不安全")
        max_bytes = 500 * 1024 * 1024
        size = 0
        digest = hashlib.sha256()
        fd, temp_name = tempfile.mkstemp(prefix=".upload-", dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > max_bytes:
                        raise OperatorError.validation_failed("单个素材不能超过 500MB")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except OperatorError:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise
        except Exception as exc:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_name)
            raise OperatorError("invalid_write_context", "素材上传失败，请重试", 409) from exc
        relative_root = "inputs/reference" if kind == "reference" else "inputs/source/video/product"
        return {"status": "uploaded", "path": f"{relative_root}/{filename}", "bytes": size, "sha256": digest.hexdigest()}

    @router.get("/skills")
    async def list_skills(request: Request) -> list:
        authenticate(request, None, "read")
        return catalog().list()

    @router.post("/projects")
    async def create_project(request: Request) -> dict:
        session = authenticate(request, None, "create_project", csrf=True)
        payload = await body(request)
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            raise OperatorError.validation_failed("缺少重复提交保护标识")
        skill = catalog().resolve(str(payload.get("skill_id") or ""), payload.get("skill_version"))
        intake = payload.get("intake") if isinstance(payload.get("intake"), dict) else {}
        for field, prefix in (("reference_paths", "inputs/reference"), ("source_paths", "inputs/source")):
            values = intake.get(field) if isinstance(intake.get(field), list) else []
            for value in values:
                candidate = PurePosixPath(str(value))
                if candidate.is_absolute() or ".." in candidate.parts or not (str(candidate) == prefix or str(candidate).startswith(f"{prefix}/")):
                    raise OperatorError.validation_failed("素材路径必须位于项目输入目录", field_errors=[{"field": field, "message": "请使用 inputs/reference 或 inputs/source 下的路径"}])
        catalog().validate_intake(skill, intake)
        project_id = str(payload.get("project_id") or "")
        digest = semantic_sha256({"project_id": project_id, "skill": skill["digest"], "intake": intake})
        result = ProjectCreationService(projects_dir(), auth_store()).create_from_skill(
            project_id=project_id,
            title=str(payload.get("title") or intake.get("product_name") or "未命名项目"),
            owner_id=session.actor.user_id,
            idempotency_key=key,
            request_digest=digest,
            resolved_skill=skill,
            intake=intake,
            snapshot_writer=catalog().write_snapshot,
        )
        return {**result, "skill": {"id": skill["id"], "version": skill["version"]}}

    @router.get("/projects/{project_id}/drafts/{stage}")
    async def load_draft(project_id: str, stage: str, request: Request) -> dict | None:
        session = authenticate(request, project_id, "read")
        return DraftService(project(project_id)).load(session.actor.user_id, stage)

    @router.put("/projects/{project_id}/drafts/{stage}")
    async def save_draft(project_id: str, stage: str, request: Request) -> dict:
        session = authenticate(request, project_id, "edit", csrf=True)
        payload = await body(request)
        project_dir = project(project_id)
        return DraftService(project_dir).save(
            actor_id=session.actor.user_id,
            stage=stage,
            base_revision=str(payload.get("base_revision") or ""),
            base_artifact_hash=semantic_sha256(snapshot(project_dir, stage)),
            changes=payload.get("changes") if isinstance(payload.get("changes"), list) else [],
        )

    @router.delete("/projects/{project_id}/drafts/{stage}")
    async def discard_draft(project_id: str, stage: str, request: Request) -> dict:
        session = authenticate(request, project_id, "edit", csrf=True)
        return DraftService(project(project_id)).discard(session.actor.user_id, stage)

    @router.post("/projects/{project_id}/shot-generations/quote")
    async def quote_shot_generation(project_id: str, request: Request) -> dict:
        authenticate(request, project_id, "read")
        payload = await body(request)
        return ShotGenerationService(project(project_id)).quote(
            shot_id=str(payload.get("shot_id") or ""),
            proposal_id=str(payload.get("proposal_id") or ""),
            quality=str(payload.get("quality") or ""),
            parent_task_id=(str(payload["parent_task_id"]) if payload.get("parent_task_id") else None),
        )

    @router.post("/projects/{project_id}/shot-generations")
    async def create_shot_generation(project_id: str, request: Request) -> dict:
        session = authenticate(request, project_id, "edit", csrf=True)
        payload = await body(request)
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            raise OperatorError.validation_failed("缺少重复提交保护标识")
        return ShotGenerationService(project(project_id)).enqueue(
            actor_id=session.actor.user_id,
            idempotency_key=key,
            shot_id=str(payload.get("shot_id") or ""),
            proposal_id=str(payload.get("proposal_id") or ""),
            plan_version=int(payload.get("plan_version") or 0),
            quality=str(payload.get("quality") or ""),
            confirmed_estimated_cost_usd=float(payload.get("confirmed_estimated_cost_usd") or -1),
            parent_task_id=(str(payload["parent_task_id"]) if payload.get("parent_task_id") else None),
        )

    @router.get("/projects/{project_id}/shot-generations/{task_id}")
    async def read_shot_generation(project_id: str, task_id: str, request: Request) -> dict:
        authenticate(request, project_id, "read")
        return ShotGenerationService(project(project_id)).get(task_id)

    @router.post("/projects/{project_id}/shot-generations/{task_id}/adopt")
    async def adopt_shot_generation(project_id: str, task_id: str, request: Request) -> dict:
        session = authenticate(request, project_id, "edit", csrf=True)
        return ShotGenerationService(project(project_id)).adopt(
            actor_id=session.actor.user_id,
            task_id=task_id,
        )

    @router.post("/projects/{project_id}/drafts/{stage}/impact")
    async def preview_impact(project_id: str, stage: str, request: Request) -> dict:
        session = authenticate(request, project_id, "edit", csrf=True)
        payload = await body(request)
        project_dir = project(project_id)
        draft = DraftService(project_dir).load(session.actor.user_id, stage)
        if not draft or draft.get("status") != "active":
            raise OperatorError.validation_failed("没有可预览的草稿")
        before = snapshot(project_dir, stage)
        get_adapter(stage).validate_project_operations(project_dir, draft["changes"])
        after = get_adapter(stage).apply(before, draft["changes"])
        generation = str(payload.get("base_generation") or "")
        if not generation:
            generation = ProjectCommitStore(project_dir).initialize()["generation_id"]
        return ImpactService(secret=preview_secret).preview(
            draft=draft,
            actor_id=session.actor.user_id,
            base_generation=generation,
            before=before,
            after=after,
        )

    @router.post("/projects/{project_id}/drafts/{stage}/commit")
    async def commit_draft(project_id: str, stage: str, request: Request) -> dict:
        session = authenticate(request, project_id, "submit", csrf=True)
        payload = await body(request)
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            raise OperatorError.validation_failed("缺少重复提交保护标识")
        project_dir = project(project_id)
        draft = DraftService(project_dir).load(session.actor.user_id, stage)
        if not draft:
            raise OperatorError.validation_failed("没有可提交的草稿")
        digest = semantic_sha256(
            {"project_id": project_id, "actor_id": session.actor.user_id, "stage": stage, "body": payload}
        )
        generation = str(payload.get("base_generation") or "")
        if not generation:
            generation = ProjectCommitStore(project_dir).initialize()["generation_id"]
        commit_service = (
            DeliveryReviewRevisionService(project_dir)
            if stage == "delivery_review"
            else RevisionService(project_dir)
        )
        commit_method = (
            commit_service.commit
            if stage == "delivery_review"
            else commit_service.commit_draft
        )
        revision = commit_method(
            draft=draft,
            actor_id=session.actor.user_id,
            reason=str(payload.get("reason") or ""),
            preview_token=str(payload.get("preview_token") or ""),
            impact_service=ImpactService(secret=preview_secret),
            base_generation=generation,
            base_snapshot=snapshot(project_dir, stage),
            idempotency_key=key,
            request_digest=digest,
        )
        return {
            "schema_version": "1.0",
            "action_id": f"commit-{revision['revision_id']}",
            "result_revision": revision["revision_id"],
            "status": "queued" if stage == "delivery_review" else "committed",
            "links": [{"rel": "project", "href": f"/p/{project_id}"}],
        }

    @router.get("/projects/{project_id}/versions/{stage}")
    async def versions(project_id: str, stage: str, request: Request) -> list:
        authenticate(request, project_id, "read")
        return [
            {
                "revision_id": item["revision_id"],
                "parent_revision_id": item["parent_revision_id"],
                "reason": item["reason"],
                "created_at": item["created_at"],
                "changes": [change["label"] for change in item.get("changes", [])],
            }
            for item in RevisionService(project(project_id)).list(stage)
        ]

    @router.post("/projects/{project_id}/versions/{stage}/compare")
    async def compare_versions(project_id: str, stage: str, request: Request) -> dict:
        authenticate(request, project_id, "read")
        payload = await body(request)
        changes = RevisionService(project(project_id)).compare(
            stage,
            payload.get("from_revision_id"),
            str(payload.get("to_revision_id") or ""),
            base_snapshot=payload.get("base_snapshot") or {},
        )
        return {"changes": changes}

    @router.post("/projects/{project_id}/versions/{stage}/{revision_id}/restore")
    async def restore_version(
        project_id: str, stage: str, revision_id: str, request: Request
    ) -> dict:
        session = authenticate(request, project_id, "edit", csrf=True)
        payload = await body(request)
        project_dir = project(project_id)
        service = RevisionService(project_dir)
        prepared = service.prepare_restore(stage, revision_id, actor_id=session.actor.user_id)
        restore_draft = {
            "draft_id": prepared["restore_id"], "stage": stage,
            "created_by": session.actor.user_id, "status": "active",
            "changes": [],
        }
        generation = ProjectCommitStore(project_dir).initialize()["generation_id"]
        if not payload.get("preview_token"):
            preview = ImpactService(secret=preview_secret).preview(
                draft=restore_draft, actor_id=session.actor.user_id,
                base_generation=generation, before=snapshot(project_dir, stage),
                after=prepared["snapshot"],
            )
            preview["render_mode"] = "重新生成完整画面"
            preview["reopen_reviews"] = ["creative_lock", "sample"]
            preview["affected_stages"] = list(dict.fromkeys(preview["affected_stages"] + ["制作准备", "样片确认", "修改与精剪"]))
            return {key: value for key, value in preview.items() if key != "draft_id"}
        ImpactService(secret=preview_secret).verify_token(
            str(payload["preview_token"]), draft=restore_draft,
            actor_id=session.actor.user_id, base_generation=generation,
        )
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            raise OperatorError.validation_failed("缺少重复提交保护标识")
        revision = service.commit_restore(
            stage=stage, revision_id=revision_id, actor_id=session.actor.user_id,
            reason=str(payload.get("reason") or "恢复历史版本"),
            current_snapshot=snapshot(project_dir, stage), idempotency_key=key,
            request_digest=semantic_sha256(payload),
            expected_generation=generation,
        )
        return {"status": "committed", "result_revision": revision["revision_id"]}

    @router.post("/projects/{project_id}/reviews/{review_id}/{decision}")
    async def decide_review(
        project_id: str, review_id: str, decision: str, request: Request
    ) -> dict:
        session = authenticate(request, project_id, "review", csrf=True)
        payload = await body(request)
        if "subject_version" not in payload or "subject_hash" not in payload:
            raise OperatorError.validation_failed("缺少待确认内容的版本或校验值")
        normalized = {"approve": "approved", "reject": "rejected"}.get(decision, decision)
        service = ReviewService(project(project_id))
        return service.decide(
            review_id=review_id,
            decision=normalized,
            actor_id=session.actor.user_id,
            reason=str(payload.get("reason") or ""),
            expected_version=int(payload["subject_version"]),
            expected_hash=str(payload["subject_hash"]),
            issue_tags=(
                [str(t) for t in payload["issue_tags"]]
                if isinstance(payload.get("issue_tags"), list)
                else None
            ),
            effect_confirmations=(
                {str(key): str(value) for key, value in payload["effect_confirmations"].items()}
                if isinstance(payload.get("effect_confirmations"), dict)
                else None
            ),
        )

    @router.post("/projects/{project_id}/review-notes")
    async def add_review_note(project_id: str, request: Request) -> dict:
        """Append one operator review note through the atomic commit store.

        P2-⑨ fix: notes go through a ProjectCommitStore generation (project
        lock + audit manifest + recovery) instead of a bare file append, so
        concurrent submissions cannot lose or interleave entries.
        """
        session = authenticate(request, project_id, "review", csrf=True)
        payload = await body(request)
        note = str(payload.get("note") or "").strip()
        if not note:
            raise OperatorError.validation_failed("审核意见不能为空")
        if len(note) > 4000:
            raise OperatorError.validation_failed("审核意见内容过长")
        stage = str(payload.get("stage") or "")
        version_ref = str(payload.get("version_ref") or "")
        idempotency_key = request.headers.get("idempotency-key", "").strip() or None
        actor = getattr(session.actor, "user_id", None) or "user"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "note": note,
            "stage": stage,
            "version_ref": version_ref,
            **({"idempotency_key": idempotency_key} if idempotency_key else {}),
        }
        project_dir = project(project_id)
        store = ProjectCommitStore(
            project_dir, outbox_materializer=_review_notes_materializer(project_dir)
        )
        with store.transaction(
            action={
                "action_id": f"note-{idempotency_key or uuid.uuid4().hex[:12]}",
                "type": "add_review_note",
            },
            result={"status": "recorded"},
            audit={"event_type": "review_note_added", "actor_id": actor},
        ) as sink:
            existing = _existing_review_note_for_idempotency_key(project_dir, entry)
            if existing is None:
                sink.append_event("review_notes", entry)
        visible = dict(existing or entry)
        visible.pop("_outbox_id", None)
        return {"status": "recorded", "review_note": visible}

    @router.get("/projects/{project_id}/members")
    async def members(project_id: str, request: Request) -> list:
        authenticate(request, project_id, "manage_members")
        return auth_store().project_members(project_id)

    @router.put("/projects/{project_id}/members/{user_id}")
    async def set_member(project_id: str, user_id: str, request: Request) -> dict:
        authenticate(request, project_id, "manage_members", csrf=True)
        payload = await body(request)
        auth_store().set_project_role(project_id, user_id, str(payload.get("role") or ""))
        return {"status": "updated"}

    @router.delete("/projects/{project_id}/members/{user_id}")
    async def remove_member(project_id: str, user_id: str, request: Request) -> dict:
        authenticate(request, project_id, "manage_members", csrf=True)
        auth_store().remove_project_role(project_id, user_id)
        return {"status": "removed"}

    @router.post("/projects/{project_id}/fork-fastline")
    async def fork_fastline(project_id: str, request: Request) -> dict:
        session = authenticate(request, project_id, "fork", csrf=True)
        payload = await body(request)
        return OperatorMigrationService(projects_dir(), auth_store()).migrate(
            source_project_id=project_id,
            target_project_id=str(payload.get("target_project_id") or ""),
            owner_id=session.actor.user_id,
            idempotency_key=request.headers.get("idempotency-key", ""),
            request_digest=semantic_sha256(payload),
        )

    @router.post("/projects/{project_id}/versions/{stage}/{revision_id}/fork")
    async def fork_revision(
        project_id: str, stage: str, revision_id: str, request: Request
    ) -> dict:
        session = authenticate(request, project_id, "fork", csrf=True)
        payload = await body(request)
        return ProjectCreationService(projects_dir(), auth_store()).fork_revision(
            source_project_id=project_id,
            stage=stage,
            revision_id=revision_id,
            target_project_id=str(payload.get("target_project_id") or ""),
            owner_id=session.actor.user_id,
            idempotency_key=request.headers.get("idempotency-key", ""),
            request_digest=semantic_sha256(payload),
        )

    @router.get("/projects/{project_id}/batch/events")
    async def batch_events(project_id: str, request: Request) -> dict:
        """批事件补拉（契约 §5）：after_seq 之后的事件；缺口检测由客户端执行。"""
        authenticate(request, project_id, "read")
        from backlot.batch_events import detect_gap, read_events

        after_seq = int(request.query_params.get("after_seq") or 0)
        events = read_events(project(project_id), after_seq=after_seq)
        return {"events": events, "gaps": detect_gap(events)}

    @router.post("/projects/{project_id}/batch/select")
    async def batch_select_for_edit(project_id: str, request: Request) -> dict:
        """批级驾驶舱：人工选择 1–2 个候选进入精剪（契约 B：乐观并发 + 幂等）。"""
        session = authenticate(request, project_id, "review", csrf=True)
        payload = await body(request)
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            raise OperatorError.validation_failed("缺少重复提交保护标识")
        from backlot.auth import authorize_project

        def authorizer(child_id: str, actor: Any) -> bool:
            return authorize_project(auth_store(), actor, child_id, "review")

        candidate_ids = [str(item) for item in (payload.get("candidate_ids") or [])]
        return BatchActionService(project(project_id), authorizer=authorizer).select_for_edit(
            actor_id=session.actor.user_id,
            idempotency_key=key,
            aggregate_revision=str(payload.get("aggregate_revision") or ""),
            candidate_ids=candidate_ids,
            reason=str(payload.get("reason") or ""),
        )

    @router.post("/projects/{project_id}/batch/approve-gate")
    async def batch_approve_gate(project_id: str, request: Request) -> dict:
        """批级一键通过（契约 B）：participants 快照 + 协调记录 + 恢复。"""
        session = authenticate(request, project_id, "review", csrf=True)
        payload = await body(request)
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            raise OperatorError.validation_failed("缺少重复提交保护标识")
        from backlot.auth import authorize_project

        def authorizer(child_id: str, actor: Any) -> bool:
            return authorize_project(auth_store(), actor, child_id, "review")

        gate = str(payload.get("gate") or "")
        participants = [
            dict(item) for item in (payload.get("participants") or [])
            if isinstance(item, dict)
        ]
        return BatchActionService(project(project_id), authorizer=authorizer).approve_gate(
            actor_id=session.actor.user_id,
            idempotency_key=key,
            aggregate_revision=str(payload.get("aggregate_revision") or ""),
            gate=gate,
            reason=str(payload.get("reason") or ""),
            participants=participants,
        )

    @router.post("/projects/{project_id}/batch/actions/{batch_action_id}/recover")
    async def batch_recover(project_id: str, batch_action_id: str, request: Request) -> dict:
        """协调记录恢复（契约 B §4.3）：续跑未完成的提交。"""
        authenticate(request, project_id, "review", csrf=True)
        from backlot.batch_actions import recover_batch_action

        return recover_batch_action(project(project_id), batch_action_id)

    return router

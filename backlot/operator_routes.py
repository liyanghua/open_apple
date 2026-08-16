"""Secure v2 routes for the typed Backlot operator workbench."""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable

from fastapi import APIRouter, Request

from backlot.operator_adapters import get_adapter
from backlot.operator_drafts import DraftService
from backlot.operator_errors import OperatorError
from backlot.operator_impact import ImpactService
from backlot.operator_migration import OperatorMigrationService
from backlot.operator_revisions import RevisionService
from backlot.operator_reviews import ReviewService
from backlot.project_commit import ProjectCommitStore
from backlot.project_creation import ProjectCreationService
from backlot.skill_catalog import SkillCatalog
from lib.artifact_hashing import semantic_sha256


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
        raw_name = request.headers.get("x-upload-path", "").strip()
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

    @router.post("/projects/{project_id}/drafts/{stage}/impact")
    async def preview_impact(project_id: str, stage: str, request: Request) -> dict:
        session = authenticate(request, project_id, "edit", csrf=True)
        payload = await body(request)
        project_dir = project(project_id)
        draft = DraftService(project_dir).load(session.actor.user_id, stage)
        if not draft or draft.get("status") != "active":
            raise OperatorError.validation_failed("没有可预览的草稿")
        before = snapshot(project_dir, stage)
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
        revision = RevisionService(project_dir).commit_draft(
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
            "status": "committed",
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
        normalized = {"approve": "approved", "reject": "rejected"}.get(decision, decision)
        service = ReviewService(project(project_id))
        active = service._find(review_id)
        return service.decide(
            review_id=review_id,
            decision=normalized,
            actor_id=session.actor.user_id,
            reason=str(payload.get("reason") or ""),
            expected_version=int(payload.get("subject_version") or active["subject_version"]),
            expected_hash=str(payload.get("subject_hash") or active["subject_hash"]),
        )

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

    return router

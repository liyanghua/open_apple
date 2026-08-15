"""Secure v2 routes for the typed Backlot operator workbench."""

from __future__ import annotations

import secrets
from pathlib import Path
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
        return RevisionService(project(project_id)).prepare_restore(
            stage, revision_id, actor_id=session.actor.user_id
        )

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

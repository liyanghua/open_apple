"""Uniform mutation preconditions, idempotency and action results."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from jsonschema import Draft202012Validator

from backlot.auth import authorize_project, require_csrf, require_session
from backlot.auth_store import AuthStore, SessionRecord
from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import semantic_sha256


_REVISION = re.compile(r"^[A-Fa-f0-9r]{64}$")


@dataclass(frozen=True)
class MutationRequest:
    schema_version: str
    idempotency_key: str
    reason: str
    base_revision: str

    @classmethod
    def from_values(
        cls,
        *,
        schema_version: str,
        idempotency_key: str,
        reason: str,
        base_revision: str,
    ) -> "MutationRequest":
        if (
            schema_version != "1.0"
            or not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or not isinstance(reason, str)
            or not reason.strip()
            or not isinstance(base_revision, str)
            or not _REVISION.fullmatch(base_revision)
        ):
            raise OperatorError.validation_failed("提交前置信息不完整")
        return cls(
            schema_version,
            idempotency_key.strip(),
            reason.strip(),
            base_revision,
        )


def authorize_mutation(
    request: Request,
    auth_store: AuthStore,
    *,
    project_id: str,
    action: str,
) -> SessionRecord:
    session = require_session(request, auth_store)
    require_csrf(request, session)
    if not authorize_project(auth_store, session.actor, project_id, action):
        raise OperatorError("forbidden", "你没有执行该操作的项目权限", 403)
    return session


class ActionService:
    def __init__(
        self, project_dir: Path, *, store: ProjectCommitStore | None = None
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.store = store or ProjectCommitStore(self.project_dir)
        schema_path = Path(__file__).parents[1] / "schemas/backlot/mutation_result.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    def _replay(self, idempotency_key: str, digest: str) -> dict[str, Any] | None:
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
            action = manifest.get("action") or {}
            if action.get("idempotency_key") != idempotency_key:
                continue
            if action.get("request_digest") != digest:
                raise OperatorError("idempotency_conflict", "该请求标识已用于其他内容", 409)
            return manifest.get("result")
        return None

    def execute(
        self,
        *,
        action_type: str,
        actor_id: str,
        idempotency_key: str,
        request_body: dict[str, Any],
        mutate: Callable[[Any], dict[str, Any]],
    ) -> dict[str, Any]:
        digest = semantic_sha256({
            "project_id": self.store.project_id,
            "action_type": action_type,
            "actor_id": actor_id,
            "request": request_body,
        })
        replay = self._replay(idempotency_key, digest)
        if replay is not None:
            return replay
        action_id = f"action-{uuid.uuid4().hex}"
        result: dict[str, Any] = {
            "schema_version": "1.0",
            "action_id": action_id,
            "result_revision": "pending",
            "status": "accepted",
            "links": [],
        }
        with self.store.transaction(
            action={
                "action_id": action_id,
                "type": action_type,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
                "request_digest": digest,
            },
            result=result,
            audit={"event_type": action_type, "actor_id": actor_id},
        ) as sink:
            supplied = mutate(sink)
            links = supplied.get("links", [])
            if isinstance(links, dict):
                links = [{"rel": rel, "href": href} for rel, href in links.items()]
            result.update(
                result_revision=str(supplied.get("result_revision") or "pending"),
                status=supplied.get("status", "committed"),
                links=links,
            )
            if list(self.validator.iter_errors(result)):
                raise OperatorError.validation_failed("操作结果不符合要求")
            sink.append_event(
                "audit",
                {
                    "action_id": action_id,
                    "event_type": action_type,
                    "actor_id": actor_id,
                    "summary": str(supplied.get("summary") or "项目内容已更新"),
                },
            )
        return result

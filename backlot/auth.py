"""Authentication and authorization policy for Backlot."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import Request

from backlot.auth_store import AuthStore, SessionRecord, UserRecord
from backlot.operator_errors import OperatorError


SESSION_COOKIE = "backlot_session"

SYSTEM_CAPABILITIES = {
    "operator": {"read", "edit", "submit", "agent", "review", "fork", "manage_members", "create_project"},
    "reviewer": {"read", "edit", "submit", "agent", "review", "fork"},
    "admin": {"read", "edit", "submit", "agent", "review", "fork", "manage_members", "diagnostics", "create_project"},
}
PROJECT_CAPABILITIES = {
    "owner": {"read", "edit", "submit", "agent", "review", "fork", "manage_members"},
    "editor": {"read", "edit", "submit", "agent", "fork"},
    "reviewer": {"read", "review"},
    "viewer": {"read"},
}


def authorize_project(
    store: AuthStore,
    actor: UserRecord,
    project_id: str,
    action: str,
) -> bool:
    system = SYSTEM_CAPABILITIES.get(actor.system_role, set())
    if action not in system:
        return False
    if actor.system_role == "admin":
        return True
    project_role = store.project_role(project_id, actor.user_id)
    return action in PROJECT_CAPABILITIES.get(project_role or "", set())


def session_from_request(request: Request, store: AuthStore) -> SessionRecord | None:
    return store.resolve_session(request.cookies.get(SESSION_COOKIE, ""))


def require_session(request: Request, store: AuthStore) -> SessionRecord:
    session = session_from_request(request, store)
    if session is None:
        raise OperatorError("auth_required", "请先登录", 401)
    return session


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host or urlsplit(origin).netloc.casefold() != host.casefold():
        raise OperatorError("csrf_failed", "请求来源验证失败", 403)


def require_csrf(request: Request, session: SessionRecord) -> None:
    require_same_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
        raise OperatorError("csrf_failed", "安全校验失败，请刷新页面后重试", 403)

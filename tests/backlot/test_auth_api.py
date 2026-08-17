from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def auth_store(tmp_path):
    from backlot.auth_store import AuthStore

    store = AuthStore(tmp_path / "backlot.db")
    store.initialize()
    return store


@pytest.fixture
def auth_client(auth_store, monkeypatch):
    from backlot import server as server_mod

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app(auth_store=auth_store)) as client:
        yield client


def _login(client, username="operator", password="a sufficiently long password"):
    return client.post(
        "/api/v2/auth/login",
        json={"schema_version": "1.0", "username": username, "password": password},
        headers={"Origin": "http://testserver"},
    )


def test_loopback_setup_closes_permanently_after_first_admin(auth_client, auth_store) -> None:
    assert auth_client.get("/setup").status_code == 200
    auth_store.create_user("admin", "a sufficiently long password", "admin")
    assert auth_client.get("/setup").status_code == 404


def test_login_me_and_csrf_protected_logout(auth_client, auth_store) -> None:
    auth_store.create_user("operator", "a sufficiently long password", "operator")

    response = _login(auth_client)
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "operator"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie

    me = auth_client.get("/api/v2/auth/me")
    assert me.status_code == 200
    csrf = me.json()["csrf_token"]

    assert auth_client.post(
        "/api/v2/auth/logout",
        headers={"Origin": "http://testserver"},
    ).status_code == 403
    assert auth_client.post(
        "/api/v2/auth/logout",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    ).status_code == 200
    assert auth_client.get("/api/v2/auth/me").status_code == 401


def test_login_rejects_cross_origin_and_uses_uniform_failure(auth_client, auth_store) -> None:
    auth_store.create_user("operator", "a sufficiently long password", "operator")

    cross_origin = auth_client.post(
        "/api/v2/auth/login",
        json={"schema_version": "1.0", "username": "operator", "password": "wrong"},
        headers={"Origin": "https://attacker.invalid"},
    )
    assert cross_origin.status_code == 403
    assert cross_origin.json()["error"]["code"] == "csrf_failed"

    unknown = _login(auth_client, username="missing", password="wrong password")
    wrong = _login(auth_client, password="wrong password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert "missing" not in unknown.text


def test_login_rate_limit_is_bounded(auth_client, auth_store) -> None:
    auth_store.create_user("operator", "a sufficiently long password", "operator")
    responses = [_login(auth_client, password="wrong password") for _ in range(7)]
    assert responses[-1].status_code == 429
    assert responses[-1].json()["error"]["code"] == "auth_required"


def test_page_routes_redirect_unauthenticated_requests_to_login(auth_client, auth_store) -> None:
    auth_store.create_user("operator", "a sufficiently long password", "operator")

    for path in ("/", "/p/film", "/p/film/extra"):
        response = auth_client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    api_response = auth_client.get("/api/projects")
    assert api_response.status_code == 401
    assert api_response.json()["error"]["code"] == "auth_required"


def test_page_routes_render_after_login(auth_client, auth_store) -> None:
    auth_store.create_user("operator", "a sufficiently long password", "operator")
    assert _login(auth_client).status_code == 200

    pages = (
        ("/", "视频项目工作台"),
        ("/p/film", "项目制作进度"),
        ("/p/film/extra", "项目制作进度"),
    )
    for path, title in pages:
        response = auth_client.get(path, follow_redirects=False)
        assert response.status_code == 200
        assert title in response.text


def test_expired_and_revoked_sessions_redirect_page_requests(auth_client, auth_store) -> None:
    from backlot.auth import SESSION_COOKIE

    actor = auth_store.create_user("operator", "a sufficiently long password", "operator")
    expired = auth_store.create_session(actor.user_id, ttl_seconds=-1)
    auth_client.cookies.set(SESSION_COOKIE, expired.session_token)
    assert auth_client.get("/", follow_redirects=False).status_code == 303

    revoked = auth_store.create_session(actor.user_id)
    auth_store.revoke_session(revoked.session_token)
    auth_client.cookies.set(SESSION_COOKIE, revoked.session_token)
    assert auth_client.get("/p/film", follow_redirects=False).status_code == 303


def test_public_pages_and_test_mode_remain_available(auth_client, backlot_client) -> None:
    for path in ("/login", "/ui/library.js", "/api/health"):
        assert auth_client.get(path, follow_redirects=False).status_code == 200

    assert backlot_client.get("/", follow_redirects=False).status_code == 200
    assert backlot_client.get("/p/film", follow_redirects=False).status_code == 200

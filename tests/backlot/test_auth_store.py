from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def clock():
    value = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
    return value, lambda: value[0]


@pytest.fixture
def auth_store(tmp_path, clock):
    from backlot.auth_store import AuthStore

    store = AuthStore(tmp_path / "backlot.db", clock=clock[1])
    store.initialize()
    return store


def test_passwords_are_scrypt_hashed_and_authentication_is_constant_shape(auth_store) -> None:
    user = auth_store.create_user("Owner", "correct horse battery staple", "admin")

    assert auth_store.authenticate("owner", "correct horse battery staple").user_id == user.user_id
    assert auth_store.authenticate("owner", "wrong password") is None

    with sqlite3.connect(auth_store.db_path) as connection:
        password_hash, salt = connection.execute(
            "SELECT password_hash, password_salt FROM users WHERE user_id = ?",
            (user.user_id,),
        ).fetchone()
    assert isinstance(password_hash, bytes) and len(password_hash) == 32
    assert isinstance(salt, bytes) and len(salt) == 16
    assert b"correct horse" not in password_hash


def test_session_tokens_are_hashed_expire_and_can_be_revoked(auth_store, clock) -> None:
    user = auth_store.create_user("operator", "a sufficiently long password", "operator")
    credentials = auth_store.create_session(user.user_id, ttl_seconds=60)

    session = auth_store.resolve_session(credentials.session_token)
    assert session.actor.user_id == user.user_id
    assert session.csrf_token == credentials.csrf_token

    with sqlite3.connect(auth_store.db_path) as connection:
        stored = connection.execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert credentials.session_token not in stored

    clock[0][0] += timedelta(seconds=61)
    assert auth_store.resolve_session(credentials.session_token) is None

    fresh = auth_store.create_session(user.user_id)
    assert auth_store.revoke_session(fresh.session_token) is True
    assert auth_store.resolve_session(fresh.session_token) is None


def test_system_role_and_project_acl_permissions_intersect(auth_store) -> None:
    from backlot.auth import authorize_project

    owner = auth_store.create_user("owner", "a sufficiently long password", "operator")
    editor = auth_store.create_user("editor", "a sufficiently long password", "operator")
    reviewer = auth_store.create_user("reviewer", "a sufficiently long password", "reviewer")
    viewer = auth_store.create_user("viewer", "a sufficiently long password", "operator")
    admin = auth_store.create_user("admin", "a sufficiently long password", "admin")

    auth_store.set_project_role("film", owner.user_id, "owner")
    auth_store.set_project_role("film", editor.user_id, "editor")
    auth_store.set_project_role("film", reviewer.user_id, "reviewer")
    auth_store.set_project_role("film", viewer.user_id, "viewer")

    assert authorize_project(auth_store, owner, "film", "manage_members")
    assert authorize_project(auth_store, editor, "film", "edit")
    assert not authorize_project(auth_store, editor, "film", "review")
    assert authorize_project(auth_store, reviewer, "film", "review")
    assert not authorize_project(auth_store, reviewer, "film", "edit")
    assert authorize_project(auth_store, viewer, "film", "read")
    assert not authorize_project(auth_store, viewer, "film", "edit")
    assert authorize_project(auth_store, admin, "unassigned-project", "diagnostics")


def test_last_owner_cannot_be_removed_or_demoted(auth_store) -> None:
    owner = auth_store.create_user("owner", "a sufficiently long password", "operator")
    second = auth_store.create_user("second", "a sufficiently long password", "operator")
    auth_store.set_project_role("film", owner.user_id, "owner")

    with pytest.raises(ValueError, match="last owner"):
        auth_store.remove_project_role("film", owner.user_id)
    with pytest.raises(ValueError, match="last owner"):
        auth_store.set_project_role("film", owner.user_id, "editor")

    auth_store.set_project_role("film", second.user_id, "owner")
    auth_store.remove_project_role("film", owner.user_id)
    assert auth_store.project_role("film", owner.user_id) is None


def test_create_admin_cli_has_no_default_password(tmp_path, monkeypatch, capsys) -> None:
    from backlot import __main__ as cli

    monkeypatch.setenv("BACKLOT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "admin password is long enough")

    assert cli.main(["users", "create-admin", "--username", "root"]) == 0
    output = capsys.readouterr().out
    assert "管理员已创建" in output
    assert "admin password" not in output

    assert cli.main(["users", "create-admin", "--username", "root"]) == 1


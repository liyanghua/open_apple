"""SQLite persistence for Backlot users, sessions, and project ACLs."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


SYSTEM_ROLES = frozenset({"operator", "reviewer", "admin"})
PROJECT_ROLES = frozenset({"owner", "editor", "reviewer", "viewer"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    username: str
    system_role: str


@dataclass(frozen=True)
class SessionCredentials:
    session_token: str
    csrf_token: str
    expires_at: str


@dataclass(frozen=True)
class SessionRecord:
    actor: UserRecord
    csrf_token: str
    expires_at: str


class AuthStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.db_path = Path(db_path)
        self._clock = clock

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_normalized TEXT NOT NULL UNIQUE,
                    password_hash BLOB NOT NULL,
                    password_salt BLOB NOT NULL,
                    system_role TEXT NOT NULL CHECK (system_role IN ('operator','reviewer','admin')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_acl (
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    project_role TEXT NOT NULL CHECK (project_role IN ('owner','editor','reviewer','viewer')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, user_id)
                );
                """
            )

    def user_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, username: str, password: str, system_role: str) -> UserRecord:
        display = username.strip()
        normalized = display.casefold()
        if not display or len(password) < 12:
            raise ValueError("Username is required and password must contain at least 12 characters")
        if system_role not in SYSTEM_ROLES:
            raise ValueError("Unknown system role")
        user_id = uuid.uuid4().hex
        salt = secrets.token_bytes(16)
        created_at = self._clock().isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO users
                    (user_id, username, username_normalized, password_hash, password_salt,
                     system_role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        display,
                        normalized,
                        _password_hash(password, salt),
                        salt,
                        system_role,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Username already exists") from exc
        return UserRecord(user_id, display, system_role)

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        normalized = username.strip().casefold()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT user_id, username, password_hash, password_salt, system_role
                FROM users WHERE username_normalized = ? AND active = 1""",
                (normalized,),
            ).fetchone()
        if row is None:
            _password_hash(password, b"\0" * 16)
            return None
        candidate = _password_hash(password, bytes(row["password_salt"]))
        if not secrets.compare_digest(candidate, bytes(row["password_hash"])):
            return None
        return UserRecord(row["user_id"], row["username"], row["system_role"])

    def create_session(self, user_id: str, *, ttl_seconds: int = 12 * 60 * 60) -> SessionCredentials:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = self._clock()
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM users WHERE user_id = ? AND active = 1", (user_id,)
            ).fetchone() is None:
                raise ValueError("Unknown or inactive user")
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (_token_hash(session_token), user_id, csrf_token, expires_at, now.isoformat()),
            )
        return SessionCredentials(session_token, csrf_token, expires_at)

    def resolve_session(self, session_token: str) -> SessionRecord | None:
        if not session_token:
            return None
        token_hash = _token_hash(session_token)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT u.user_id, u.username, u.system_role, s.csrf_token, s.expires_at
                FROM sessions s JOIN users u ON u.user_id = s.user_id
                WHERE s.token_hash = ? AND u.active = 1""",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at <= self._clock():
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
        actor = UserRecord(row["user_id"], row["username"], row["system_role"])
        return SessionRecord(actor, row["csrf_token"], row["expires_at"])

    def revoke_session(self, session_token: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (_token_hash(session_token),)
            )
            return cursor.rowcount > 0

    def set_project_role(self, project_id: str, user_id: str, project_role: str) -> None:
        if not project_id or project_role not in PROJECT_ROLES:
            raise ValueError("Unknown project role")
        now = self._clock().isoformat()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT project_role FROM project_acl WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if current and current["project_role"] == "owner" and project_role != "owner":
                self._require_another_owner(connection, project_id, user_id)
            try:
                connection.execute(
                    """INSERT INTO project_acl
                    (project_id, user_id, project_role, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, user_id) DO UPDATE SET
                      project_role = excluded.project_role,
                      updated_at = excluded.updated_at""",
                    (project_id, user_id, project_role, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Unknown user") from exc

    @staticmethod
    def _require_another_owner(
        connection: sqlite3.Connection, project_id: str, user_id: str
    ) -> None:
        count = connection.execute(
            "SELECT COUNT(*) FROM project_acl WHERE project_id = ? AND project_role = 'owner' AND user_id != ?",
            (project_id, user_id),
        ).fetchone()[0]
        if count == 0:
            raise ValueError("Cannot remove or demote the last owner")

    def remove_project_role(self, project_id: str, user_id: str) -> None:
        with self._connect() as connection:
            current = connection.execute(
                "SELECT project_role FROM project_acl WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if current and current["project_role"] == "owner":
                self._require_another_owner(connection, project_id, user_id)
            connection.execute(
                "DELETE FROM project_acl WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )

    def project_role(self, project_id: str, user_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_role FROM project_acl WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
        return str(row["project_role"]) if row else None

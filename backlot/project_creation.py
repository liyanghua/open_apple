"""Crash-recoverable project reservations, creation and revision forks."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backlot.auth_store import AuthStore
from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes
from lib.cache_io import atomic_write_json


_PROJECT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProjectCreationService:
    def __init__(
        self,
        projects_dir: Path,
        auth_store: AuthStore,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.projects_dir = Path(projects_dir).resolve()
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.auth_store = auth_store
        self.db_path = auth_store.db_path
        self.fault = fault_injector or (lambda _point: None)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS project_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_digest TEXT NOT NULL,
                    target_project_id TEXT NOT NULL UNIQUE,
                    source_project_id TEXT,
                    migration_version TEXT,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    def create(
        self,
        *,
        project_id: str,
        title: str,
        pipeline_type: str,
        owner_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        return self._create(
            project_id=project_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            source_project_id=None,
            initializer=lambda directory: atomic_write_json(
                directory / "project.json",
                {"project_id": project_id, "title": title, "pipeline_type": pipeline_type},
            ),
        )

    def create_from_skill(
        self,
        *,
        project_id: str,
        title: str,
        owner_id: str,
        idempotency_key: str,
        request_digest: str,
        resolved_skill: dict[str, Any],
        intake: dict[str, Any],
        snapshot_writer: Callable[[Path, dict[str, Any], dict[str, Any]], None],
    ) -> dict[str, Any]:
        def initialize(directory: Path) -> None:
            atomic_write_json(directory / "project.json", {
                "project_id": project_id,
                "title": title,
                "pipeline_type": resolved_skill["manifest"]["pipeline"],
                "skill": {"id": resolved_skill["id"], "version": resolved_skill["version"]},
            })
            snapshot_writer(directory, resolved_skill, intake)

        return self._create(
            project_id=project_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            source_project_id=None,
            initializer=initialize,
        )

    def _reserve(
        self,
        *,
        project_id: str,
        owner_id: str,
        idempotency_key: str,
        request_digest: str,
        source_project_id: str | None,
    ) -> sqlite3.Row:
        if not _PROJECT_ID.fullmatch(project_id):
            raise OperatorError.validation_failed("项目标识格式不正确")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM project_reservations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing["request_digest"] != request_digest:
                    raise OperatorError("idempotency_conflict", "该请求标识已用于其他内容", 409)
                return existing
            try:
                connection.execute(
                    """INSERT INTO project_reservations
                    (reservation_id,idempotency_key,request_digest,target_project_id,
                     source_project_id,migration_version,owner_id,status,response_json,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"reservation-{idempotency_key}", idempotency_key, request_digest,
                        project_id, source_project_id, None, owner_id, "reserved", None, now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise OperatorError("idempotency_conflict", "目标项目已被其他请求占用", 409) from exc
            return connection.execute(
                "SELECT * FROM project_reservations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()

    def _create(
        self,
        *,
        project_id: str,
        owner_id: str,
        idempotency_key: str,
        request_digest: str,
        source_project_id: str | None,
        initializer: Callable[[Path], None],
    ) -> dict[str, Any]:
        reservation = self._reserve(
            project_id=project_id, owner_id=owner_id,
            idempotency_key=idempotency_key, request_digest=request_digest,
            source_project_id=source_project_id,
        )
        if reservation["status"] == "committed":
            return json.loads(reservation["response_json"])
        target = self.projects_dir / project_id
        if not target.exists():
            temporary = Path(tempfile.mkdtemp(prefix=f".{project_id}.", dir=self.projects_dir))
            try:
                initializer(temporary)
                ProjectCommitStore(temporary).initialize()
                with self._connect() as connection:
                    connection.execute(
                        "UPDATE project_reservations SET status='materializing', updated_at=? WHERE idempotency_key=?",
                        (datetime.now(timezone.utc).isoformat(), idempotency_key),
                    )
                os.rename(temporary, target)
            except BaseException:
                if temporary.exists():
                    import shutil
                    shutil.rmtree(temporary)
                raise
        self.fault("after_rename")
        result = {"project_id": project_id, "status": "created"}
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO project_acl(project_id,user_id,project_role,created_at,updated_at)
                VALUES (?,?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET
                project_role='owner', updated_at=excluded.updated_at""",
                (project_id, owner_id, "owner", now, now),
            )
            connection.execute(
                """UPDATE project_reservations SET status='committed', response_json=?, updated_at=?
                WHERE idempotency_key=?""",
                (json.dumps(result, ensure_ascii=False), now, idempotency_key),
            )
        return result

    def fork_revision(
        self,
        *,
        source_project_id: str,
        stage: str,
        revision_id: str,
        target_project_id: str,
        owner_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        source = self.projects_dir / source_project_id
        matches = list((source / "operator/revisions" / stage).glob(f"*-{revision_id}.json"))
        if len(matches) != 1:
            raise OperatorError.validation_failed("找不到要创建分支的版本")
        revision = json.loads(matches[0].read_text(encoding="utf-8"))

        def initialize(directory: Path) -> None:
            atomic_write_json(
                directory / "project.json",
                {
                    "project_id": target_project_id,
                    "title": target_project_id,
                    "pipeline_type": "cinematic-fast",
                    "parent_project_id": source_project_id,
                    "parent_revision_id": revision_id,
                },
            )
            snapshot = dict(revision["snapshot"])
            snapshot["project_id"] = target_project_id
            snapshot.pop("semantic_sha256", None)
            snapshot.pop("artifact_sha256", None)
            atomic_write_json(
                directory / "artifacts" / f"{revision['artifact_name']}.json",
                attach_hashes(snapshot),
            )

        return self._create(
            project_id=target_project_id, owner_id=owner_id,
            idempotency_key=idempotency_key, request_digest=request_digest,
            source_project_id=source_project_id, initializer=initialize,
        )

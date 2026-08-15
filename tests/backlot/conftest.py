from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backlot import server as server_mod
from backlot import state as state_mod


@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(
        server_mod,
        "_PROJECTS_ROOT_STR",
        os.path.normcase(str(root.resolve())),
    )
    monkeypatch.setattr(server_mod, "THUMB_CACHE_DIR", tmp_path / "thumbs")
    return root


@pytest.fixture
def backlot_client(projects_root, monkeypatch):
    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as test_client:
        yield test_client


@pytest.fixture
def make_project():
    def build(
        root: Path,
        project_id: str = "film",
        pipeline_type: str = "cinematic",
    ) -> Path:
        project = root / project_id
        (project / "artifacts").mkdir(parents=True)
        (project / "assets" / "images").mkdir(parents=True)
        (project / "assets" / "video").mkdir(parents=True)
        (project / "renders").mkdir(parents=True)
        (project / "project.json").write_text(
            json.dumps({
                "project_id": project_id,
                "title": "Film",
                "pipeline_type": pipeline_type,
                "created_at": "2026-07-02T00:00:00Z",
            }),
            encoding="utf-8",
        )
        (project / "checkpoint_script.json").write_text(
            json.dumps({
                "version": "1.0",
                "project_id": project_id,
                "pipeline_type": pipeline_type,
                "stage": "script",
                "status": "awaiting_human",
                "timestamp": "2026-07-02T00:01:00Z",
                "artifacts": {},
            }),
            encoding="utf-8",
        )
        return project

    return build

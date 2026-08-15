from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _login(client, username="owner"):
    response = client.post(
        "/api/v2/auth/login",
        json={"schema_version": "1.0", "username": username, "password": "a sufficiently long password"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client.get("/api/v2/auth/me").json()["csrf_token"]


def test_secure_typed_draft_preview_and_commit_flow(tmp_path, monkeypatch) -> None:
    from backlot import server as server_mod
    from backlot.auth_store import AuthStore
    from backlot.project_commit import ProjectCommitStore

    projects = tmp_path / "projects"; project = projects / "film"; (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "film", "title": "桌垫", "pipeline_type": "cinematic-fast",
    }))
    (project / "artifacts/proposal_packet.json").write_text(json.dumps({"hook": "旧钩子", "cta": "了解更多"}))
    store = ProjectCommitStore(project); pointer = store.initialize()
    auth = AuthStore(tmp_path / "backlot.db"); auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    outsider = auth.create_user("outsider", "a sufficiently long password", "operator")
    auth.set_project_role("film", owner.user_id, "owner")
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_watch_projects", lambda: _never())

    with TestClient(server_mod.create_app(auth_store=auth)) as client:
        assert client.get("/api/v2/projects/film/operator-state").status_code == 401
        _login(client, "outsider")
        assert client.get("/api/v2/projects/film/operator-state").status_code == 403
        client.post("/api/v2/auth/logout", headers={"Origin": "http://testserver", "X-CSRF-Token": client.get("/api/v2/auth/me").json()["csrf_token"]})
        csrf = _login(client)
        save_body = {
            "schema_version": "1.0", "base_revision": "r" * 64,
            "base_artifact_hash": "a" * 64,
            "changes": [{"op": "replace_hook", "text": "先刮给你看"}],
        }
        assert client.put(
            "/api/v2/projects/film/drafts/proposal", json=save_body,
            headers={"Origin": "http://testserver"},
        ).status_code == 403
        saved = client.put(
            "/api/v2/projects/film/drafts/proposal", json=save_body,
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert saved.status_code == 200
        preview = client.post(
            "/api/v2/projects/film/drafts/proposal/impact",
            json={"base_generation": pointer["generation_id"]},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert preview.status_code == 200
        committed = client.post(
            "/api/v2/projects/film/drafts/proposal/commit",
            json={
                "schema_version": "1.0", "reason": "强化开头",
                "base_generation": pointer["generation_id"],
                "preview_token": preview.json()["preview_token"],
            },
            headers={
                "Origin": "http://testserver", "X-CSRF-Token": csrf,
                "Idempotency-Key": "commit-1",
            },
        )
        assert committed.status_code == 200
        assert committed.json()["status"] == "committed"
        assert json.loads((project / "artifacts/proposal_packet.json").read_text())["hook"] == "先刮给你看"


async def _never():
    return None


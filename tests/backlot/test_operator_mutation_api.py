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


def test_delivery_review_api_commit_preserves_compose_checkpoint(tmp_path, monkeypatch) -> None:
    from backlot import server as server_mod
    from backlot.auth_store import AuthStore
    from backlot.delivery_versions import DeliveryVersionService
    from backlot.project_commit import ProjectCommitStore

    projects = tmp_path / "projects"; project = projects / "film"; (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "film", "title": "桌垫", "pipeline_type": "cinematic-fast",
        "created_at": "2026-08-19T00:00:00Z",
    }))
    (project / "artifacts/render_report.json").write_text(json.dumps({
        "outputs": [{"path": "renders/final-v1.mp4", "duration_seconds": 30}],
        "video_master_sha256": "a" * 64,
    }))
    checkpoint = b'{"stage":"compose","status":"completed"}'
    (project / "checkpoint_compose.json").write_bytes(checkpoint)
    DeliveryVersionService(project).certify({
        "schema_version": "1.0", "project_id": "film", "version_id": "v1",
        "created_at": "2026-08-19T00:00:00Z", "review_revision_id": None,
        "video": {"path": "renders/final-v1.mp4", "poster_path": None, "subtitles_path": None},
        "audio_mix": {}, "qa": {"status": "pass", "issues": []},
        "change_summary": "首个认证版本", "video_master_sha256": "a" * 64,
    }, actor_id="system")
    current_before = (project / "operator/current-delivery.json").read_bytes()
    pointer = ProjectCommitStore(project).initialize()
    auth = AuthStore(tmp_path / "backlot.db"); auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    auth.set_project_role("film", owner.user_id, "owner")
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_watch_projects", lambda: _never())

    with TestClient(server_mod.create_app(auth_store=auth)) as client:
        csrf = _login(client)
        saved = client.put(
            "/api/v2/projects/film/drafts/delivery_review",
            json={
                "schema_version": "1.0", "base_revision": "r" * 64,
                "changes": [{
                    "op": "replace_delivery_copy", "section_id": "sentence-1",
                    "text": "改过的字幕", "sync_narration": False,
                }],
            },
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert saved.status_code == 200, saved.text
        preview = client.post(
            "/api/v2/projects/film/drafts/delivery_review/impact",
            json={"base_generation": pointer["generation_id"]},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert preview.status_code == 200, preview.text
        assert "音画不一致" in "".join(preview.json()["warnings"])
        committed = client.post(
            "/api/v2/projects/film/drafts/delivery_review/commit",
            json={
                "schema_version": "1.0", "reason": "运营确认调整",
                "base_generation": pointer["generation_id"],
                "preview_token": preview.json()["preview_token"],
            },
            headers={
                "Origin": "http://testserver", "X-CSRF-Token": csrf,
                "Idempotency-Key": "delivery-commit-1",
            },
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["status"] == "queued"
        repeated = client.post(
            "/api/v2/projects/film/drafts/delivery_review/commit",
            json={
                "schema_version": "1.0", "reason": "运营确认调整",
                "base_generation": pointer["generation_id"],
                "preview_token": preview.json()["preview_token"],
            },
            headers={
                "Origin": "http://testserver", "X-CSRF-Token": csrf,
                "Idempotency-Key": "delivery-commit-1",
            },
        )
        assert repeated.status_code == 200
        assert repeated.json()["result_revision"] == committed.json()["result_revision"]

    assert (project / "checkpoint_compose.json").read_bytes() == checkpoint
    assert (project / "operator/current-delivery.json").read_bytes() == current_before


def test_delivery_review_rejects_candidate_outside_current_project_catalog(tmp_path, monkeypatch) -> None:
    from backlot import server as server_mod
    from backlot.auth_store import AuthStore

    projects = tmp_path / "projects"
    project = projects / "film"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "film", "title": "桌垫", "pipeline_type": "cinematic-fast",
        "created_at": "2026-08-19T00:00:00Z",
    }))
    (project / "artifacts/render_report.json").write_text(json.dumps({
        "outputs": [{"path": "renders/final-v1.mp4", "duration_seconds": 30}],
        "video_master_sha256": "a" * 64,
    }))
    auth = AuthStore(tmp_path / "backlot.db")
    auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    auth.set_project_role("film", owner.user_id, "owner")
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_watch_projects", lambda: _never())

    with TestClient(server_mod.create_app(auth_store=auth)) as client:
        csrf = _login(client)
        state = client.get("/api/v2/projects/film/operator-state").json()
        delivery = next(
            stage["editor"]["data"]
            for stage in state["stages"]
            if stage["editor"]["type"] == "delivery_review"
        )
        valid_cover_id = next(
            group["candidates"][0]["id"]
            for group in delivery["candidate_groups"]
            if group["kind"] == "cover"
        )
        accepted = client.put(
            "/api/v2/projects/film/drafts/delivery_review",
            json={
                "schema_version": "1.0",
                "base_revision": "r" * 64,
                "changes": [{
                    "op": "select_delivery_candidate",
                    "candidate_kind": "cover",
                    "candidate_id": valid_cover_id,
                }],
            },
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert accepted.status_code == 200, accepted.text
        restored = client.get("/api/v2/projects/film/drafts/delivery_review")
        assert restored.status_code == 200, restored.text
        assert restored.json()["changes"] == [{
            "op": "select_delivery_candidate",
            "candidate_kind": "cover",
            "candidate_id": valid_cover_id,
        }]
        response = client.put(
            "/api/v2/projects/film/drafts/delivery_review",
            json={
                "schema_version": "1.0",
                "base_revision": "r" * 64,
                "changes": [{
                    "op": "select_delivery_candidate",
                    "candidate_kind": "cover",
                    "candidate_id": "cover-000000000000",
                }],
            },
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "当前项目" in response.json()["error"]["message"]

from __future__ import annotations

import json

import pytest


def test_creation_reservation_is_idempotent_and_assigns_owner(tmp_path) -> None:
    from backlot.auth_store import AuthStore
    from backlot.project_creation import ProjectCreationService

    projects = tmp_path / "projects"
    projects.mkdir()
    auth = AuthStore(tmp_path / "backlot.db")
    auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    service = ProjectCreationService(projects, auth)
    first = service.create(
        project_id="new-film", title="新视频", pipeline_type="cinematic-fast",
        owner_id=owner.user_id, idempotency_key="create-1", request_digest="a" * 64,
    )
    replay = service.create(
        project_id="new-film", title="新视频", pipeline_type="cinematic-fast",
        owner_id=owner.user_id, idempotency_key="create-1", request_digest="a" * 64,
    )
    assert first == replay
    assert auth.project_role("new-film", owner.user_id) == "owner"
    assert json.loads((projects / "new-film/project.json").read_text())["pipeline_type"] == "cinematic-fast"

    with pytest.raises(Exception) as conflict:
        service.create(
            project_id="new-film", title="不同", pipeline_type="cinematic-fast",
            owner_id=owner.user_id, idempotency_key="create-1", request_digest="b" * 64,
        )
    assert getattr(conflict.value, "code", None) == "idempotency_conflict"


def test_fork_records_parent_and_does_not_copy_approval_or_agent_state(tmp_path) -> None:
    from backlot.auth_store import AuthStore
    from backlot.project_creation import ProjectCreationService

    projects = tmp_path / "projects"
    source = projects / "source"
    (source / "operator/revisions/proposal").mkdir(parents=True)
    (source / "operator/reviews").mkdir()
    (source / "operator/agent").mkdir()
    revision = {
        "revision_id": "rev-1", "artifact_name": "proposal_packet",
        "snapshot": {"hook": "历史钩子"},
    }
    (source / "operator/revisions/proposal/000001-rev-1.json").write_text(json.dumps(revision))
    auth = AuthStore(tmp_path / "backlot.db"); auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    result = ProjectCreationService(projects, auth).fork_revision(
        source_project_id="source", stage="proposal", revision_id="rev-1",
        target_project_id="branch", owner_id=owner.user_id,
        idempotency_key="fork-1", request_digest="c" * 64,
    )
    marker = json.loads((projects / result["project_id"] / "project.json").read_text())
    assert marker["parent_project_id"] == "source"
    assert marker["parent_revision_id"] == "rev-1"
    assert json.loads((projects / "branch/artifacts/proposal_packet.json").read_text())["hook"] == "历史钩子"
    assert not (projects / "branch/operator/reviews").exists()
    assert not (projects / "branch/operator/agent").exists()


def test_retry_recovers_directory_published_before_owner_commit(tmp_path) -> None:
    from backlot.auth_store import AuthStore
    from backlot.project_creation import ProjectCreationService

    projects = tmp_path / "projects"; projects.mkdir()
    auth = AuthStore(tmp_path / "backlot.db"); auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    failing = ProjectCreationService(
        projects,
        auth,
        fault_injector=lambda point: (_ for _ in ()).throw(RuntimeError(point))
        if point == "after_rename" else None,
    )
    with pytest.raises(RuntimeError):
        failing.create(
            project_id="recover-film", title="恢复项目", pipeline_type="cinematic-fast",
            owner_id=owner.user_id, idempotency_key="recover-1", request_digest="d" * 64,
        )
    assert (projects / "recover-film").exists()
    assert auth.project_role("recover-film", owner.user_id) is None

    recovered = ProjectCreationService(projects, auth).create(
        project_id="recover-film", title="恢复项目", pipeline_type="cinematic-fast",
        owner_id=owner.user_id, idempotency_key="recover-1", request_digest="d" * 64,
    )
    assert recovered["status"] == "created"
    assert auth.project_role("recover-film", owner.user_id) == "owner"

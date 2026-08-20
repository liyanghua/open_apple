from __future__ import annotations

import json
from pathlib import Path

import pytest


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "demo", "pipeline_type": "unknown"}), encoding="utf-8"
    )
    return project


def _artifact() -> dict:
    return {
        "version": "2.0",
        "project_id": "demo",
        "created_at": "2026-08-15T00:00:00Z",
        "producer": "tests",
        "input_hashes": {},
        "value": "new",
    }


def test_operator_managed_writers_require_transaction(tmp_path, monkeypatch) -> None:
    from backlot.operator_errors import OperatorError
    from backlot.project_commit import ProjectCommitStore
    from lib import artifact_io
    from lib.checkpoint import write_checkpoint
    from lib.production_lock import append_decision_revision

    project = _project(tmp_path)
    ProjectCommitStore(project).initialize()
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda _name, _data: None)

    with pytest.raises(OperatorError) as artifact_failure:
        artifact_io.write_artifact_atomic(
            "artifacts/example.json", "example", _artifact(), project_dir=project
        )
    assert artifact_failure.value.code == "operator_transaction_required"

    with pytest.raises(OperatorError) as checkpoint_failure:
        write_checkpoint(tmp_path, "demo", "research", "in_progress", {})
    assert checkpoint_failure.value.code == "operator_transaction_required"

    with pytest.raises(OperatorError) as decision_failure:
        append_decision_revision(
            project,
            category="cta",
            subject="收口文案",
            selected="立即购买",
            superseded="了解更多",
            reason="提高转化",
        )
    assert decision_failure.value.code == "operator_transaction_required"


def test_writers_stage_one_atomic_generation(tmp_path, monkeypatch) -> None:
    from backlot.project_commit import ProjectCommitStore
    from lib import artifact_io
    from lib.checkpoint import write_checkpoint
    from lib.production_lock import append_decision_revision

    project = _project(tmp_path)
    store = ProjectCommitStore(project)
    store.initialize()
    monkeypatch.setattr(artifact_io, "validate_artifact", lambda _name, _data: None)

    with store.transaction(action={"action_id": "combined"}) as sink:
        envelope = artifact_io.write_artifact_atomic(
            "artifacts/example.json",
            "example",
            _artifact(),
            project_dir=project,
            sink=sink,
        )
        checkpoint_path = write_checkpoint(
            tmp_path, "demo", "research", "in_progress", {},
            next_action={"summary": "测试恢复指令", "verb": "run_stage", "context_refs": ["artifacts/x.json"]},
            sink=sink
        )
        revision_id = append_decision_revision(
            project,
            category="cta",
            subject="收口文案",
            selected="立即购买",
            superseded="了解更多",
            reason="提高转化",
            sink=sink,
        )
        assert not (project / envelope["path"]).exists()
        assert not checkpoint_path.exists()

    assert json.loads((project / "artifacts/example.json").read_text())["value"] == "new"
    assert json.loads(checkpoint_path.read_text())["stage"] == "research"
    decisions = json.loads((project / "artifacts/decision_log.json").read_text())["decisions"]
    assert decisions[-1]["decision_id"] == revision_id
    pointer = json.loads((project / "operator/current-generation.json").read_text())
    manifest = json.loads(
        (project / "operator/generations" / pointer["generation_id"] / "manifest.json").read_text()
    )
    assert {item["relative_path"] for item in manifest["write_set"]} == {
        "artifacts/example.json",
        "checkpoint_research.json",
        "artifacts/decision_log.json",
    }


def test_approval_bundle_stale_preconditions_do_not_write(tmp_path) -> None:
    from backlot.operator_errors import OperatorError
    from backlot.project_commit import ProjectCommitStore
    from lib.approval_groups import approve_bundle, build_approval_bundle

    project = _project(tmp_path)
    for stage in ("script", "assets"):
        (project / f"checkpoint_{stage}.json").write_text(
            json.dumps({"stage": stage, "status": "completed", "artifacts": {}}),
            encoding="utf-8",
        )
    store = ProjectCommitStore(project)
    store.initialize()
    manifest = {
        "approval_groups": {
            "creative": {
                "members": ["script", "assets"],
                "terminal_stage": "assets",
                "required_artifacts": [],
            }
        }
    }
    with store.transaction(action={"action_id": "bundle"}) as sink:
        bundle = build_approval_bundle(project, manifest, "creative", sink=sink)

    with pytest.raises(OperatorError) as stale:
        with store.transaction(action={"action_id": "stale"}) as sink:
            approve_bundle(
                project,
                bundle["bundle_id"],
                approved_by="reviewer",
                expected_version=99,
                expected_hash=bundle["semantic_sha256"],
                sink=sink,
            )
    assert stale.value.code == "review_stale"
    assert not list((project / "artifacts/approvals").glob("*-approved.json"))


def test_research_frames_and_artifacts_roll_back_before_transaction_returns(tmp_path) -> None:
    from backlot.project_commit import ProjectCommitStore

    project = _project(tmp_path)
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame-data")
    store = ProjectCommitStore(
        project,
        fault_injector=lambda point: (_ for _ in ()).throw(RuntimeError(point))
        if point == "after_apply" else None,
    )
    store.initialize()

    with pytest.raises(RuntimeError, match="after_apply"):
        with store.transaction(action={"action_id": "research-bundle"}) as sink:
            sink.stage_json("artifacts/research_breakdown.json", {"version": "new"}, schema="research_breakdown")
            sink.stage_bytes("artifacts/research-frames/frame-1.jpg", frame, media_type="image/jpeg")
            sink.stage_json("checkpoint_research.json", {"stage": "research"}, schema="checkpoint")

    assert not (project / "artifacts/research_breakdown.json").exists()
    assert not (project / "artifacts/research-frames/frame-1.jpg").exists()
    assert not (project / "checkpoint_research.json").exists()
    assert store.recover() == "clean"

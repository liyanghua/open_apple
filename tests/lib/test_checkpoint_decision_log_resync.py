"""Contract tests for decision-log merge + checkpoint envelope re-sync.

Regressions from the table-mat-mix-v7 run:
- appending a decision invalidated earlier checkpoints that embed the
  decision_log envelope ("Artifact disk data does not match embedded
  checkpoint data");
- prerequisite validation read only disk, so re-sync and stage advance had to
  be split across two transactions.
"""

import json
from pathlib import Path

import pytest

from backlot.project_commit import ProjectCommitStore
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import (
    _merge_decision_log,
    _resync_checkpoint_artifacts,
    validate_checkpoint,
)
from tests.contracts.test_phase0_contracts import sample_artifact


def _make_log(project_id: str, decisions: list[dict]) -> dict:
    return {"version": "1.0", "project_id": project_id, "decisions": decisions}


def _decision(decision_id: str, category: str = "music_source") -> dict:
    return {
        "decision_id": decision_id,
        "stage": "proposal",
        "category": category,
        "subject": "背景音乐来源",
        "options_considered": [
            {"option_id": "none", "label": "不配乐", "score": 0.0, "reason": "r"},
        ],
        "selected": "none",
        "reason": "r",
    }


def _proposal_checkpoint(project_id: str, log_env: dict) -> dict:
    return {
        "version": "1.0",
        "project_id": project_id,
        # Legacy (v1) manifest: proposal only requires the canonical
        # proposal_packet, and raw artifact dicts are accepted.
        "pipeline_type": "animated-explainer",
        "stage": "proposal",
        "status": "completed",
        "timestamp": "2026-08-22T00:00:00Z",
        "artifacts": {
            "proposal_packet": sample_artifact("proposal_packet"),
            "decision_log": log_env,
        },
    }


def test_merge_returns_envelope_and_resyncs_checkpoints(tmp_path: Path) -> None:
    project_id = "demo"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    log_env = write_artifact_atomic(
        "artifacts/decision_log.json",
        "decision_log",
        _make_log(project_id, [_decision("d-001")]),
        project_dir=project_dir,
    )
    (project_dir / "checkpoint_proposal.json").write_text(
        json.dumps(_proposal_checkpoint(project_id, log_env)), encoding="utf-8"
    )

    merged = _merge_decision_log(
        tmp_path, project_id, _make_log(project_id, [_decision("d-002")])
    )
    assert merged["semantic_sha256"] == merged["data"]["semantic_sha256"]

    resynced = _resync_checkpoint_artifacts(
        tmp_path, project_id, "decision_log", merged
    )
    assert resynced == ["checkpoint_proposal.json"]

    on_disk = json.loads(
        (project_dir / "checkpoint_proposal.json").read_text(encoding="utf-8")
    )
    assert (
        on_disk["artifacts"]["decision_log"]["semantic_sha256"]
        == merged["semantic_sha256"]
    )
    # The refreshed checkpoint must validate against the merged disk log.
    validate_checkpoint(on_disk, project_dir=project_dir)


def test_merge_is_idempotent_for_existing_decision_ids(tmp_path: Path) -> None:
    project_id = "demo"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    write_artifact_atomic(
        "artifacts/decision_log.json",
        "decision_log",
        _make_log(project_id, [_decision("d-001")]),
        project_dir=project_dir,
    )
    merged = _merge_decision_log(
        tmp_path, project_id, _make_log(project_id, [_decision("d-001")])
    )
    assert len(merged["data"]["decisions"]) == 1


def test_resync_skips_requested_stage(tmp_path: Path) -> None:
    project_id = "demo"
    project_dir = tmp_path / project_id
    project_dir.mkdir()
    log_env = write_artifact_atomic(
        "artifacts/decision_log.json",
        "decision_log",
        _make_log(project_id, [_decision("d-001")]),
        project_dir=project_dir,
    )
    for stage in ("proposal", "compose"):
        cp = _proposal_checkpoint(project_id, log_env)
        cp["stage"] = stage
        (project_dir / f"checkpoint_{stage}.json").write_text(
            json.dumps(cp), encoding="utf-8"
        )
    merged = _merge_decision_log(
        tmp_path, project_id, _make_log(project_id, [_decision("d-002")])
    )
    resynced = _resync_checkpoint_artifacts(
        tmp_path, project_id, "decision_log", merged, skip_stage="compose"
    )
    assert resynced == ["checkpoint_proposal.json"]


def test_validation_reads_transaction_staged_view(tmp_path: Path) -> None:
    """A checkpoint validated inside a transaction must see staged artifacts.

    This is what lets a single transaction re-sync an earlier checkpoint
    envelope AND advance the pipeline in the same commit.
    """
    project_id = tmp_path.name
    old_log = write_artifact_atomic(
        "artifacts/decision_log.json",
        "decision_log",
        _make_log(project_id, [_decision("d-001")]),
        project_dir=tmp_path,
    )
    (tmp_path / "checkpoint_proposal.json").write_text(
        json.dumps(_proposal_checkpoint(project_id, old_log)), encoding="utf-8"
    )

    # Build the merged log the transaction will stage.
    new_data = _make_log(project_id, [_decision("d-001"), _decision("d-002")])
    from lib.artifact_hashing import attach_hashes
    from schemas.artifacts import validate_artifact

    staged_data = attach_hashes(new_data)
    validate_artifact("decision_log", staged_data)
    new_env = {
        "name": "decision_log",
        "path": "artifacts/decision_log.json",
        "semantic_sha256": staged_data["semantic_sha256"],
        "artifact_sha256": staged_data["artifact_sha256"],
        "data": staged_data,
    }

    store = ProjectCommitStore(tmp_path)
    with store.transaction(
        action={"action_id": "test-resync", "type": "test"},
        result={"status": "committed"},
    ) as sink:
        sink.stage_json(
            "artifacts/decision_log.json", staged_data, schema="decision_log"
        )
        refreshed = _proposal_checkpoint(project_id, new_env)
        # Disk still holds the OLD log; only the staged view has the new one.
        validate_checkpoint(refreshed, project_dir=tmp_path, sink=sink)
        sink.stage_json(
            "checkpoint_proposal.json", refreshed, schema="checkpoint"
        )

    # Post-commit both files agree.
    on_disk = json.loads(
        (tmp_path / "checkpoint_proposal.json").read_text(encoding="utf-8")
    )
    validate_checkpoint(on_disk, project_dir=tmp_path)

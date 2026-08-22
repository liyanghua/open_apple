"""Checkpoint envelope auto-refresh (评审 P2 B1) tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import (
    CheckpointValidationError,
    read_checkpoint,
    refresh_checkpoint_envelopes,
    write_checkpoint,
)
from tests.contracts.test_phase0_contracts import sample_artifact


def _init_project(tmp_path: Path) -> Path:
    project = tmp_path / "refresh-demo"
    (project / "artifacts").mkdir(parents=True)
    envelope = write_artifact_atomic(
        "artifacts/research_brief.json",
        "research_brief",
        sample_artifact("research_brief"),
        project_dir=project,
    )
    write_checkpoint(
        tmp_path,
        "refresh-demo",
        "research",
        "completed",
        {"research_brief": envelope},
        pipeline_type="unknown",
    )
    return project


def test_refresh_repairs_stale_envelope_after_disk_rewrite(tmp_path: Path):
    project = _init_project(tmp_path)
    # 磁盘重写同一制品（内容变化 → 新哈希 → 检查点信封漂移）
    updated = sample_artifact("research_brief")
    updated["topic"] = "改写后的研究主题"
    write_artifact_atomic(
        "artifacts/research_brief.json", "research_brief", updated, project_dir=project
    )
    with pytest.raises(CheckpointValidationError):
        read_checkpoint(tmp_path, "refresh-demo", "research")

    report = refresh_checkpoint_envelopes(tmp_path, "refresh-demo")
    assert report == {"research": ["research_brief"]}

    checkpoint = read_checkpoint(tmp_path, "refresh-demo", "research")
    embedded = checkpoint["artifacts"]["research_brief"]["data"]
    assert embedded["topic"] == "改写后的研究主题"


def test_refresh_is_a_noop_when_envelopes_are_current(tmp_path: Path):
    project = _init_project(tmp_path)
    assert refresh_checkpoint_envelopes(tmp_path, "refresh-demo") == {}
    read_checkpoint(tmp_path, "refresh-demo", "research")  # 仍有效


def test_refresh_dry_run_does_not_persist(tmp_path: Path):
    project = _init_project(tmp_path)
    updated = sample_artifact("research_brief")
    updated["topic"] = "改写后的研究主题"
    write_artifact_atomic(
        "artifacts/research_brief.json", "research_brief", updated, project_dir=project
    )
    report = refresh_checkpoint_envelopes(tmp_path, "refresh-demo", dry_run=True)
    assert report == {"research": ["research_brief"]}
    with pytest.raises(CheckpointValidationError):
        read_checkpoint(tmp_path, "refresh-demo", "research")

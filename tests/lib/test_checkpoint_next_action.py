"""Checkpoint next_action resume-directive tests (B2)."""

from pathlib import Path

from lib.checkpoint import read_checkpoint, write_checkpoint


def test_next_action_is_written_and_read_back(tmp_path: Path):
    write_checkpoint(
        tmp_path, "proj", "compose", "in_progress", {},
        metadata={"partial_progress": {"n": 1}},
        next_action={
            "summary": "resume full render from final_props",
            "verb": "resume_render",
            "priority": "blocking",
            "context_refs": ["artifacts/final_props.json"],
        },
    )
    cp = read_checkpoint(tmp_path, "proj", "compose")
    na = cp["next_action"]
    assert na["summary"] == "resume full render from final_props"
    assert na["verb"] == "resume_render"
    assert na["context_refs"] == ["artifacts/final_props.json"]
    assert na["set_at"]  # auto-stamped


def test_new_resume_checkpoint_without_next_action_fails_closed(tmp_path: Path):
    """P1-③: new in_progress/awaiting_human checkpoints MUST carry a resume
    directive — the write fails closed instead of warning. (Reading legacy
    checkpoints without the field stays compatible: validate_checkpoint does
    not require next_action.)"""
    import pytest

    from lib.checkpoint import CheckpointValidationError

    with pytest.raises(CheckpointValidationError, match="next_action"):
        write_checkpoint(tmp_path, "proj", "script", "in_progress", {})
    with pytest.raises(CheckpointValidationError, match="next_action"):
        write_checkpoint(tmp_path, "proj", "script", "awaiting_human", {})


def test_completed_checkpoint_does_not_need_next_action(tmp_path: Path):
    from tests.contracts.test_phase0_contracts import sample_artifact

    write_checkpoint(
        tmp_path, "proj", "script", "completed",
        {"script": sample_artifact("script")},
    )
    cp = read_checkpoint(tmp_path, "proj", "script")
    assert "next_action" not in cp

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lib.production_lock import (
    append_decision_revision,
    build_production_lock,
    compare_production_locks,
)
from lib.checkpoint import CheckpointValidationError, write_checkpoint
from tests.contracts.test_phase0_contracts import sample_artifact


def _lock() -> dict:
    return build_production_lock(
        proposal={
            "project_id": "demo",
            "production_plan": {
                "platform": "tiktok",
                "cta": "立即下单",
                "render_runtime": "remotion",
                "composition_mode": "atelier",
                "output": {"resolution": "1080x1920", "fps": 30, "duration": 30},
            },
        },
        script={"project_id": "demo", "text": "透明也能扛住日常刮擦"},
        scene_plan={"captions": {"profile": "safe", "emphasis": ["刮擦"]}},
        asset_plan={
            "tts": {"provider": "doubao", "model": "seed-tts", "voice": "warm"},
            "bgm": {"id": "track-1"},
            "mix": {"gain": 0, "lufs": -14},
        },
        decisions={"decisions": [{"decision_id": "d-1", "category": "voice_selection", "subject": "voice", "selected": "warm", "options_considered": [{"option_id": "warm", "label": "warm", "score": 1, "reason": "fit"}], "reason": "fit"}]},
    )


@pytest.mark.parametrize(
    ("path", "value", "creative", "sample", "route"),
    [
        ("tts.provider", "other", True, True, "full_render"),
        ("tts.voice", "other", True, True, "full_render"),
        ("cta", "other", True, True, "full_render"),
        ("render_runtime", "ffmpeg", True, True, "full_render"),
        ("composition_mode", "templated", True, True, "full_render"),
        ("narration", "new words", True, True, "full_render"),
        ("captions.profile", "large", False, True, "full_render"),
        ("scene_timing", {"s1": 2}, False, True, "full_render"),
        ("mix.gain", -2, False, False, "mux_only"),
        ("mix.lufs", -16, False, False, "mux_only"),
        ("metadata.notes", "typo fix", False, False, "no_render"),
    ],
)
def test_lock_diff_routes_by_semantic_field(path, value, creative, sample, route):
    previous = _lock()
    current = copy.deepcopy(previous)
    cursor = current["locked_values"]
    parts = path.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value
    diff = compare_production_locks(previous, current)
    assert any(item == path or item.startswith(path + ".") for item in diff.changed_paths)
    assert diff.reopen_creative_lock is creative
    assert diff.reopen_sample is sample
    assert diff.render_route == route


def test_build_lock_contains_hashes_and_decision_ids():
    lock = _lock()
    assert lock["project_id"] == "demo"
    assert len(lock["semantic_sha256"]) == 64
    assert len(lock["artifact_sha256"]) == 64
    assert lock["decision_revision_ids"] == ["d-1"]
    assert set(lock["locked_values"]) == {
        "script", "narration", "tts", "bgm", "mix", "font", "captions",
        "cta", "platform", "output", "render_runtime", "composition_mode",
    }


def test_append_revision_is_append_only_and_uses_same_pair(tmp_path: Path):
    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    old = {
        "version": "1.0",
        "project_id": "demo",
        "decisions": [{
            "decision_id": "d-old",
            "stage": "proposal",
            "category": "voice_selection",
            "subject": "Narration TTS provider",
            "options_considered": [{"option_id": "old", "label": "old", "score": 1, "reason": "initial"}],
            "selected": "old",
            "reason": "initial",
        }],
    }
    (project / "artifacts" / "decision_log.json").write_text(json.dumps(old), encoding="utf-8")
    revision_id = append_decision_revision(
        project,
        category="voice_selection",
        subject="Narration TTS provider",
        selected="new",
        superseded="old",
        reason="warm voice requested",
    )
    log = json.loads((project / "artifacts" / "decision_log.json").read_text())
    assert len(log["decisions"]) == 2
    assert log["decisions"][0]["decision_id"] == "d-old"
    revision = log["decisions"][1]
    assert revision["decision_id"] == revision_id
    assert (revision["category"], revision["subject"]) == ("voice_selection", "Narration TTS provider")
    assert "changed/superseded" in revision["options_considered"][0]["rejected_because"]
    assert revision["selected"] == "new"
    assert log["semantic_sha256"]


def test_revision_reads_legacy_root_log_without_modifying_it(tmp_path: Path):
    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    legacy = project / "decision_log.json"
    legacy.write_text(json.dumps({"version": "1.0", "project_id": "demo", "decisions": []}), encoding="utf-8")
    append_decision_revision(project, category="concept_selection", subject="CTA", selected="new", superseded="old", reason="changed")
    assert legacy.exists()
    assert (project / "artifacts" / "decision_log.json").exists()


def test_invalid_checkpoint_does_not_persist_decision_log(tmp_path: Path):
    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    with pytest.raises(CheckpointValidationError):
        write_checkpoint(
            tmp_path,
            "demo",
            "proposal",
            "awaiting_human",
            {
                "proposal_packet": {},
                "decision_log": {
                    "version": "1.0",
                    "project_id": "demo",
                    "decisions": [],
                },
            },
            pipeline_type="unknown",
        )
    assert not (project / "artifacts" / "decision_log.json").exists()


def test_checkpoint_writes_canonical_decision_log(tmp_path: Path):
    project = tmp_path / "demo"
    project.mkdir()
    write_checkpoint(
        tmp_path,
        "demo",
        "proposal",
        "awaiting_human",
        {
            "proposal_packet": sample_artifact("proposal_packet"),
            "decision_log": {
                "version": "1.0",
                "project_id": "demo",
                "decisions": [],
            },
        },
        pipeline_type="unknown",
    )
    assert (project / "artifacts" / "decision_log.json").exists()

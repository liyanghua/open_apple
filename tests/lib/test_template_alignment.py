from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.template_alignment import (
    alignment_gate_errors,
    current_alignment_checks,
    shot_alignment_errors,
    shot_execution_plan_errors,
    tts_binding_errors,
)


def _cross_artifacts() -> tuple[dict, dict, dict]:
    section = {
        "id": "sec-001", "scene_id": "scene-001",
        "narration": "水分快速被带走", "screen_copy": "可见吸水过程",
        "start_seconds": 0.0, "end_seconds": 2.0,
        "claim_ids": ["absorb-visible"], "action_keys": ["absorb"],
        "evidence_row_ids": ["evidence-001"],
    }
    mapping = {
        "scene_id": "scene-001", "script_section_id": "sec-001",
        "claim_ids": ["absorb-visible"], "action_keys": ["absorb"],
        "evidence_row_ids": ["evidence-001"],
        "source_hash": "a" * 64,
        "source_interval": {"start_seconds": 1.0, "end_seconds_exclusive": 3.0},
    }
    scene = {"id": "scene-001", "script_section_id": "sec-001", **{
        key: mapping[key] for key in ("claim_ids", "action_keys", "evidence_row_ids")
    }}
    from lib.template_assets import _content_hash
    shot = {
        "id": "shot-01", "scene_id": "scene-001", "section_id": "sec-001",
        "narration": section["narration"], "screen_copy": section["screen_copy"],
        "claim_ids": list(section["claim_ids"]), "action_keys": list(section["action_keys"]),
        "evidence_row_ids": list(section["evidence_row_ids"]),
        "source_hash": mapping["source_hash"], "source_interval": dict(mapping["source_interval"]),
        "narration_hash": _content_hash({"section_id": "sec-001", "text": section["narration"]}),
        "screen_copy_hash": _content_hash({"section_id": "sec-001", "text": section["screen_copy"]}),
        "caption_timeline_hash": _content_hash({
            "section_id": "sec-001", "screen_copy": section["screen_copy"],
            "start_seconds": 0.0, "end_seconds": 2.0,
        }),
        "tts_asset_hash": None, "tts_measured_duration": None,
    }
    return {"shots": [shot]}, {"sections": [section]}, {
        "scenes": [scene], "metadata": {"source_mapping": [mapping]}
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("section_id", "sec-999", "section_id"),
        ("claim_ids", ["soft-touch"], "claim_ids"),
        ("source_hash", "b" * 64, "source_hash"),
        ("narration", "旧口播", "narration"),
        ("narration_hash", "b" * 64, "narration_hash"),
        ("caption_timeline_hash", "b" * 64, "caption_timeline_hash"),
    ],
)
def test_shot_execution_plan_rejects_cross_artifact_drift(field, value, message) -> None:
    shot_plan, script, scene_plan = _cross_artifacts()
    shot_plan["shots"][0][field] = value
    assert any(message in error for error in shot_execution_plan_errors(
        shot_plan, script, scene_plan
    ))


def test_shot_execution_plan_accepts_exact_cross_artifact_binding() -> None:
    shot_plan, script, scene_plan = _cross_artifacts()
    assert shot_execution_plan_errors(shot_plan, script, scene_plan) == []


def test_tts_binding_rejects_sidecar_for_old_script(tmp_path: Path) -> None:
    audio = tmp_path / "assets" / "audio"
    audio.mkdir(parents=True)
    output = audio / "narration-s001.mp3"
    output.write_bytes(b"audio")
    (audio / "narration-s001.mp3.lock.json").write_text(
        json.dumps({
            "text_sha": "old-text",
            "speech_rate": 0,
            "voice_id": "zh_female_vv_uranus_bigtts",
            "resource_id": "seed-tts-2.0",
            "format": "mp3",
        }),
        encoding="utf-8",
    )

    errors = tts_binding_errors(
        {"sections": [{"id": "sec-001", "narration": "新口播"}]},
        audio,
    )
    assert any("sec-001" in error and "text" in error for error in errors)


def test_shot_alignment_requires_explicit_section_binding() -> None:
    errors = shot_alignment_errors(
        {
            "shots": [{
                "id": "shot-01",
                "section_id": "sec-002",
                "narration": "旧口播",
                "screen_copy": "旧花字",
            }],
        },
        {"sections": [
            {"id": "sec-001", "narration": "正确口播", "screen_copy": "正确花字"},
            {"id": "sec-002", "narration": "另一句", "screen_copy": "另一花字"},
        ]},
    )
    assert any("shot-01.narration" in error for error in errors)
    assert any("shot-01.screen_copy" in error for error in errors)


def test_alignment_gate_is_fail_closed() -> None:
    assert alignment_gate_errors([{"section_id": "sec-001", "match": "yes"}]) == []
    errors = alignment_gate_errors([
        {"section_id": "sec-001", "match": "partial"},
        {"section_id": "sec-002", "match": "error"},
    ])
    assert len(errors) == 2
    assert all("alignment" in error for error in errors)


def test_old_alignment_report_is_not_applied_to_new_sample() -> None:
    legacy = [{"section_id": "sec-001", "match": "no"}]
    assert current_alignment_checks(
        legacy, sample_sha256="a" * 64, script_sha256="b" * 64,
    ) is None
    report = {
        "sample_sha256": "a" * 64,
        "script_sha256": "b" * 64,
        "checks": [{"section_id": "sec-001", "match": "yes"}],
    }
    assert current_alignment_checks(
        report, sample_sha256="a" * 64, script_sha256="b" * 64,
    ) == report["checks"]

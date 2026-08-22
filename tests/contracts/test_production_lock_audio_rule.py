"""Contract tests for the production_lock audio rule (Design_Review P0-3)."""

from __future__ import annotations

import pytest

from schemas.artifacts import validate_artifact


def _lock(locked_values: dict) -> dict:
    base = {
        "script": "",
        "narration": "",
        "tts": {},
        "bgm": "none_yet",
        "mix": {},
        "font": "",
        "captions": {},
        "cta": "",
        "platform": "",
        "output": {},
        "render_runtime": "remotion",
        "composition_mode": "templated",
    }
    base.update(locked_values)
    return {
        "version": "1.0",
        "project_id": "p-test",
        "created_at": "2026-08-22T00:00:00+00:00",
        "producer": "test",
        "input_hashes": {},
        "semantic_sha256": "a" * 64,
        "artifact_sha256": "b" * 64,
        "lock_version": 1,
        "locked_values": base,
        "decision_revision_ids": [],
    }


def test_lock_with_narration_and_tts_selected_is_valid():
    validate_artifact("production_lock", _lock({
        "narration": "桌面想保护，木纹也别遮住。",
        "tts": {"provider": "doubao", "voice": "warm"},
    }))


def test_lock_with_narration_and_explicit_no_audio_reason_is_valid():
    validate_artifact("production_lock", _lock({
        "narration": "桌面想保护，木纹也别遮住。",
        "mix": {"reason": "本期为动作声实录风格，不做口播"},
    }))


def test_lock_with_narration_but_no_tts_and_no_reason_is_rejected():
    with pytest.raises(Exception):
        validate_artifact("production_lock", _lock({
            "narration": "桌面想保护，木纹也别遮住。",
        }))


def test_lock_without_narration_needs_no_reason():
    validate_artifact("production_lock", _lock({"narration": ""}))

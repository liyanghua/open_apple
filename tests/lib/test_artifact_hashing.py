from __future__ import annotations

from copy import deepcopy

from lib.artifact_hashing import (
    artifact_sha256,
    attach_hashes,
    canonical_bytes,
    semantic_sha256,
    verify_hashes,
)


def _artifact() -> dict:
    return {
        "version": "2.0",
        "project_id": "demo",
        "created_at": "2026-08-14T10:00:00Z",
        "producer": "tests",
        "input_hashes": {"source": "a" * 64},
        "metadata": {
            "run_id": "run-1",
            "event_id": "event-1",
            "absolute_project_path": "/private/demo",
            "stable": "keep-me",
        },
        "payload": {"z": 1, "a": "hello"},
    }


def test_canonical_bytes_uses_jcs_ordering() -> None:
    assert canonical_bytes({"z": 1, "a": "hello"}) == b'{"a":"hello","z":1}'


def test_canonical_omission_paths_include_list_indexes() -> None:
    original = {
        "metadata": [
            {"run_id": "volatile-1", "stable": "keep"},
            {"run_id": "stable-by-position"},
        ]
    }
    changed = deepcopy(original)
    changed["metadata"][0]["run_id"] = "volatile-2"
    omitted = frozenset({("metadata", 0, "run_id")})

    assert canonical_bytes(original, omitted) == canonical_bytes(changed, omitted)
    assert canonical_bytes(original) != canonical_bytes(changed)


def test_semantic_hash_omits_only_declared_volatile_paths() -> None:
    original = attach_hashes(_artifact())
    changed = deepcopy(original)
    changed["created_at"] = "2026-08-14T11:00:00Z"
    changed["metadata"]["run_id"] = "run-2"
    changed["metadata"]["event_id"] = "event-2"
    changed["metadata"]["absolute_project_path"] = "/another/path"
    changed["artifact_sha256"] = "f" * 64

    assert semantic_sha256(changed) == original["semantic_sha256"]

    changed["metadata"]["stable"] = "changed"
    assert semantic_sha256(changed) != original["semantic_sha256"]


def test_artifact_hash_omits_only_its_own_field() -> None:
    attached = attach_hashes(_artifact())
    replayed = deepcopy(attached)
    replayed["artifact_sha256"] = "0" * 64
    assert artifact_sha256(replayed) == attached["artifact_sha256"]

    replayed["created_at"] = "2026-08-14T11:00:00Z"
    assert artifact_sha256(replayed) != attached["artifact_sha256"]


def test_attach_hashes_returns_copy_with_both_hashes() -> None:
    source = _artifact()
    attached = attach_hashes(source)

    assert source == _artifact()
    assert "semantic_sha256" not in source
    assert len(attached["semantic_sha256"]) == 64
    assert len(attached["artifact_sha256"]) == 64
    assert verify_hashes(attached).valid


def test_verify_hashes_reports_semantic_and_integrity_failures_independently() -> None:
    attached = attach_hashes(_artifact())

    semantic_replay = deepcopy(attached)
    semantic_replay["semantic_sha256"] = "0" * 64
    semantic_result = verify_hashes(semantic_replay)
    assert not semantic_result.valid
    assert not semantic_result.semantic_valid
    assert not semantic_result.artifact_valid

    volatile_tamper = deepcopy(attached)
    volatile_tamper["created_at"] = "2026-08-14T12:00:00Z"
    volatile_result = verify_hashes(volatile_tamper)
    assert not volatile_result.valid
    assert volatile_result.semantic_valid
    assert not volatile_result.artifact_valid

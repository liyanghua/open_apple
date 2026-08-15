"""Canonical semantic and integrity hashes for versioned artifacts."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import rfc8785

SEMANTIC_OMIT_PATHS = frozenset({
    ("artifact_sha256",),
    ("semantic_sha256",),
    ("created_at",),
    ("metadata", "run_id"),
    ("metadata", "event_id"),
    ("metadata", "absolute_project_path"),
})
ARTIFACT_OMIT_PATHS = frozenset({("artifact_sha256",)})


@dataclass(frozen=True)
class HashVerification:
    valid: bool
    semantic_valid: bool
    artifact_valid: bool


def _without_paths(
    value: Any,
    omitted: frozenset[tuple[Any, ...]],
    prefix: tuple[Any, ...] = (),
) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_paths(child, omitted, prefix + (key,))
            for key, child in value.items()
            if prefix + (key,) not in omitted
        }
    if isinstance(value, list):
        return [
            _without_paths(child, omitted, prefix + (index,))
            for index, child in enumerate(value)
        ]
    return value


def canonical_bytes(
    value: Any, omitted: frozenset[tuple[Any, ...]] = frozenset()
) -> bytes:
    """Serialize JSON-compatible data using RFC 8785 (JCS)."""
    return rfc8785.dumps(_without_paths(value, omitted))


def semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value, SEMANTIC_OMIT_PATHS)).hexdigest()


def artifact_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value, ARTIFACT_OMIT_PATHS)).hexdigest()


def attach_hashes(value: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with semantic and full-integrity hashes attached."""
    attached = deepcopy(value)
    attached["semantic_sha256"] = semantic_sha256(attached)
    attached["artifact_sha256"] = artifact_sha256(attached)
    return attached


def verify_hashes(value: Any) -> HashVerification:
    if not isinstance(value, dict):
        return HashVerification(False, False, False)

    semantic = value.get("semantic_sha256")
    artifact = value.get("artifact_sha256")
    semantic_valid = isinstance(semantic, str) and semantic == semantic_sha256(value)
    artifact_valid = isinstance(artifact, str) and artifact == artifact_sha256(value)
    return HashVerification(
        valid=semantic_valid and artifact_valid,
        semantic_valid=semantic_valid,
        artifact_valid=artifact_valid,
    )

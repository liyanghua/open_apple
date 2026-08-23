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
    ("generated_at",),
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


def _non_plain_location(value: Any, path: str = "$") -> tuple[str, type] | None:
    """Return (path, type) of the first non-JSON value, else None.

    Object scripts (callables, custom class instances, tuples) must never
    reach a canonical hash: rfc8785 rejects them anyway, but with an opaque
    error and no location.  Walking first makes the contract explicit and
    gives producers a path-qualified failure.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            location = _non_plain_location(child, f"{path}.{key}")
            if location is not None:
                return location
        return None
    if isinstance(value, list):
        for index, child in enumerate(value):
            location = _non_plain_location(child, f"{path}[{index}]")
            if location is not None:
                return location
        return None
    if isinstance(value, bool) or value is None or isinstance(value, (str, int, float)):
        return None
    return path, type(value)


def canonical_bytes(
    value: Any, omitted: frozenset[tuple[Any, ...]] = frozenset()
) -> bytes:
    """Serialize JSON-compatible data using RFC 8785 (JCS).

    Non-plain-JSON values (callables, custom objects, tuples, ...) are
    rejected with a path-qualified TypeError so an object script can never
    smuggle a non-deterministic value into an artifact hash.
    """
    location = _non_plain_location(value)
    if location is not None:
        path, kind = location
        raise TypeError(
            f"value at {path!r} is not plain JSON data ({kind.__name__}); "
            "artifact content may only contain dict/list/str/int/float/bool/null"
        )
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

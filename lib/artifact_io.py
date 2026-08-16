"""Durable artifact envelope I/O with containment and hash verification."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from lib.artifact_hashing import attach_hashes, verify_hashes
from schemas.artifacts import validate_artifact


_ENVELOPE_FIELDS = {
    "name",
    "path",
    "semantic_sha256",
    "artifact_sha256",
    "data",
}


def _artifact_relative_path(path: str | os.PathLike[str]) -> PurePosixPath:
    raw = os.fspath(path)
    if not isinstance(raw, str):
        raise ValueError("Artifact path must be a project-relative path under artifacts/")
    if "\\" in raw:
        raise ValueError("Artifact path must be a project-relative path under artifacts/")
    candidate = PurePosixPath(raw)
    if (
        candidate.is_absolute()
        or len(candidate.parts) < 2
        or candidate.parts[0] != "artifacts"
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("Artifact path must be a project-relative path under artifacts/")
    return candidate


def _contained_path(project_dir: Path, relative: PurePosixPath) -> Path:
    root = project_dir.resolve()
    artifacts_root = (root / "artifacts").resolve()
    target = (root / Path(*relative.parts)).resolve()
    if (
        target == artifacts_root
        or artifacts_root not in target.parents
        or root not in target.parents
    ):
        raise ValueError("Artifact path must be a project-relative path under artifacts/")
    return target


def canonical_artifact_path(
    project_dir: str | os.PathLike[str], name: str
) -> Path:
    """Return the contained canonical path for a named artifact.

    Keeping this path construction beside the envelope containment checks
    prevents append-only writers from accidentally falling back to a project
    root file (the pre-v2 decision-log location).
    """
    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        raise ValueError("Artifact name must be a simple non-empty filename stem")
    relative = _artifact_relative_path(f"artifacts/{name}.json")
    return _contained_path(Path(project_dir), relative)


def _is_v2_envelope(value: Any) -> bool:
    return isinstance(value, dict) and _ENVELOPE_FIELDS.issubset(value)


def write_artifact_atomic(
    path: str | os.PathLike[str],
    name: str,
    data: dict[str, Any],
    *,
    project_dir: str | os.PathLike[str] | None = None,
    sink: Any = None,
) -> dict[str, Any]:
    """Hash, validate, and atomically write canonical artifact data.

    The returned envelope is embedded in checkpoints. The file on disk contains
    only the artifact data so downstream consumers can read it directly.
    """
    raw_path = Path(path)
    if raw_path.is_absolute():
        if project_dir is None:
            raise ValueError(
                "Absolute artifact path must be project-relative under artifacts "
                "unless project_dir is provided"
            )
        root = Path(project_dir).resolve()
        resolved = raw_path.resolve()
        try:
            relative = _artifact_relative_path(resolved.relative_to(root).as_posix())
        except ValueError as exc:
            raise ValueError("Absolute artifact path must belong to project_dir") from exc
        target = resolved
    else:
        relative = _artifact_relative_path(path)
        target = _contained_path(
            Path(project_dir) if project_dir is not None else Path.cwd(), relative
        )
    if not isinstance(name, str) or not name:
        raise ValueError("Artifact name must be a non-empty string")
    if not isinstance(data, dict):
        raise TypeError("Artifact data must be a JSON object")

    attached = attach_hashes(data)
    validate_artifact(name, attached)
    envelope = {
        "name": name,
        "path": relative.as_posix(),
        "semantic_sha256": attached["semantic_sha256"],
        "artifact_sha256": attached["artifact_sha256"],
        "data": attached,
    }

    from backlot.project_write_sink import require_project_sink

    root = Path(project_dir) if project_dir is not None else Path.cwd()
    write_sink = require_project_sink(root, sink)
    if write_sink is not None:
        write_sink.stage_json(relative.as_posix(), attached, schema=name)
        return envelope

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(attached, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return envelope


def load_artifact_envelope(
    project_dir: str | os.PathLike[str], envelope: dict[str, Any]
) -> dict[str, Any]:
    """Load and verify a v2 envelope against its project-local disk copy."""
    if not _is_v2_envelope(envelope):
        raise ValueError("Artifact envelope is missing required v2 fields")
    if not isinstance(envelope["name"], str) or not envelope["name"]:
        raise ValueError("Artifact envelope name must be a non-empty string")

    relative = _artifact_relative_path(envelope["path"])
    target = _contained_path(Path(project_dir), relative)
    try:
        with open(target, encoding="utf-8") as handle:
            disk_value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load artifact envelope from disk: {exc}") from exc

    data = envelope["data"]
    if not isinstance(data, dict):
        raise ValueError("Artifact envelope data must be a JSON object")

    if envelope["semantic_sha256"] != data.get("semantic_sha256"):
        raise ValueError("Artifact semantic hash does not match envelope")
    if envelope["artifact_sha256"] != data.get("artifact_sha256"):
        raise ValueError("Artifact integrity hash does not match envelope")
    verification = verify_hashes(data)
    if not verification.valid:
        raise ValueError(
            "Artifact hash verification failed "
            f"(semantic={verification.semantic_valid}, artifact={verification.artifact_valid})"
        )

    legacy_disk_envelope = disk_value if _is_v2_envelope(disk_value) else None
    disk_data = disk_value["data"] if legacy_disk_envelope is not None else disk_value
    if not isinstance(disk_data, dict):
        raise ValueError("Artifact disk data must be a JSON object")
    disk_verification = verify_hashes(disk_data)
    if not disk_verification.valid:
        raise ValueError("Artifact disk hash verification failed")
    if disk_data != data:
        raise ValueError("Artifact disk data does not match embedded checkpoint data")
    if legacy_disk_envelope is not None and legacy_disk_envelope != envelope:
        raise ValueError(
            "Artifact disk envelope does not match embedded checkpoint envelope"
        )
    try:
        validate_artifact(envelope["name"], data)
    except Exception as exc:
        raise ValueError(f"Artifact schema validation failed: {exc}") from exc
    return data


def unwrap_checkpoint_artifact(
    project_dir: str | os.PathLike[str],
    name: str,
    artifact: Any,
) -> Any:
    """Read v2 envelopes while retaining legacy raw dict/path compatibility."""
    if _is_v2_envelope(artifact):
        if artifact["name"] != name:
            raise ValueError(
                f"Artifact envelope name {artifact['name']!r} does not match {name!r}"
            )
        return load_artifact_envelope(project_dir, artifact)

    if isinstance(artifact, str):
        relative = _artifact_relative_path(artifact)
        target = _contained_path(Path(project_dir), relative)
        try:
            with open(target, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not load legacy artifact path: {exc}") from exc
        if _is_v2_envelope(loaded):
            if loaded["name"] != name:
                raise ValueError(
                    f"Artifact envelope name {loaded['name']!r} does not match {name!r}"
                )
            return load_artifact_envelope(project_dir, loaded)
        artifact = loaded

    if isinstance(artifact, dict):
        validate_artifact(name, artifact)
        return artifact
    raise ValueError(f"Unsupported checkpoint artifact value for {name!r}")

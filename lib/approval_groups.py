"""Atomic approval-bundle lifecycle for grouped human gates."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.artifact_hashing import attach_hashes, semantic_sha256
from lib.pipeline_loader import get_approval_group, load_pipeline_readonly
from schemas.artifacts import validate_artifact


def _bundle_dir(project_dir: Path) -> Path:
    path = project_dir / "artifacts" / "approvals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_bundle(path: Path, bundle: dict[str, Any]) -> Path:
    validate_artifact("approval_bundle", bundle)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(bundle, handle, ensure_ascii=False, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try: os.unlink(temp)
        except FileNotFoundError: pass
        raise
    return path


def _bundle_state(project_dir: Path, bundle_id: str) -> tuple[Path, dict[str, Any]]:
    candidates = sorted(_bundle_dir(project_dir).glob(f"{bundle_id}-v*-*.json"))
    if not candidates:
        raise FileNotFoundError(f"approval bundle not found: {bundle_id}")
    states = []
    for path in candidates:
        try: states.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError): continue
    if not states: raise ValueError(f"approval bundle files are unreadable: {bundle_id}")
    precedence = {"awaiting_human": 0, "approved": 1, "rejected": 1, "superseded": 2}
    return max(
        states,
        key=lambda item: (
            int(item[1].get("bundle_version", 0)),
            precedence.get(str(item[1].get("status")), -1),
            item[0].stat().st_mtime_ns,
        ),
    )


def _approval_input_hash(checkpoint: dict[str, Any]) -> str:
    """Hash creative inputs while ignoring mutable gate bookkeeping.

    The terminal checkpoint is necessarily written twice: once as an
    ``in_progress`` draft so the bundle can be built, and again as
    ``awaiting_human``/``completed`` with the bundle reference.  Gate status,
    timestamps and the bundle artifact itself are not creative inputs and
    must not make that two-phase write self-supersede.
    """
    stable = dict(checkpoint)
    for key in (
        "status", "timestamp", "human_approved", "human_approval_required",
        "approval_group", "approval_bundle_id", "approval_bundle_version",
    ):
        stable.pop(key, None)
    artifacts = dict(stable.get("artifacts") or {})
    artifacts.pop("approval_bundle", None)
    stable["artifacts"] = artifacts
    return semantic_sha256(stable)


def build_approval_bundle(project_dir: Path, manifest: dict[str, Any], group_name: str) -> dict[str, Any]:
    group = (manifest.get("approval_groups") or {}).get(group_name)
    if not group:
        raise ValueError(f"unknown approval group: {group_name}")
    project_id = project_dir.name
    refs: list[dict[str, Any]] = []
    input_hashes: dict[str, str] = {}
    for stage in group["members"]:
        checkpoint_path = project_dir / f"checkpoint_{stage}.json"
        if not checkpoint_path.is_file():
            raise ValueError(f"approval group {group_name} missing member checkpoint: {stage}")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        input_hashes[stage] = _approval_input_hash(checkpoint)
        for name, artifact in (checkpoint.get("artifacts") or {}).items():
            if isinstance(artifact, dict) and {"path", "semantic_sha256", "artifact_sha256"} <= artifact.keys():
                refs.append({"name": name, "path": artifact["path"], "semantic_sha256": artifact["semantic_sha256"], "artifact_sha256": artifact["artifact_sha256"]})
    bundle_id = f"{project_id}-{group_name}"
    previous = list(_bundle_dir(project_dir).glob(f"{bundle_id}-v*-*.json"))
    version = max([int(p.name.split("-v", 1)[1].split("-", 1)[0]) for p in previous] or [0]) + 1
    body = {"version": "1.0", "project_id": project_id, "created_at": datetime.now(timezone.utc).isoformat(), "producer": "approval_groups", "input_hashes": input_hashes, "bundle_id": bundle_id, "bundle_version": version, "group": group_name, "terminal_stage": group["terminal_stage"], "members": group["members"], "artifact_refs": refs, "status": "awaiting_human"}
    bundle = attach_hashes(body)
    _write_bundle(_bundle_dir(project_dir) / f"{bundle_id}-v{version}-awaiting_human.json", bundle)
    return bundle


def approve_bundle(project_dir: Path, bundle_id: str, *, approved_by: str) -> Path:
    source_path, bundle = _bundle_state(project_dir, bundle_id)
    if bundle["status"] != "awaiting_human": raise ValueError("only awaiting_human bundles can be approved")
    body = {k: v for k, v in bundle.items() if k not in {"semantic_sha256", "artifact_sha256", "status", "approved_by"}}
    body.update({"status": "approved", "approved_by": approved_by})
    approved = attach_hashes(body)
    path = _bundle_dir(project_dir) / f"{bundle_id}-v{bundle['bundle_version']}-approved.json"
    _write_bundle(path, approved)
    return path


def reject_bundle(project_dir: Path, bundle_id: str, *, reason: str) -> Path:
    _, bundle = _bundle_state(project_dir, bundle_id)
    if bundle["status"] != "awaiting_human": raise ValueError("only awaiting_human bundles can be rejected")
    body = {k: v for k, v in bundle.items() if k not in {"semantic_sha256", "artifact_sha256", "status", "rejected_reason"}}
    body.update({"status": "rejected", "rejected_reason": reason})
    rejected = attach_hashes(body)
    path = _bundle_dir(project_dir) / f"{bundle_id}-v{bundle['bundle_version']}-rejected.json"
    _write_bundle(path, rejected)
    return path


def reconcile_bundle(project_dir: Path, terminal_checkpoint: dict[str, Any]) -> dict[str, Any]:
    bundle_id = terminal_checkpoint.get("approval_bundle_id")
    if not bundle_id: return {"status": "missing"}
    _, bundle = _bundle_state(project_dir, bundle_id)
    current_hash = _approval_input_hash(terminal_checkpoint)
    expected = (bundle.get("input_hashes") or {}).get(bundle.get("terminal_stage"))
    if expected and expected != current_hash:
        body = {k: v for k, v in bundle.items() if k not in {"semantic_sha256", "artifact_sha256", "status", "superseded_by"}}
        body.update({"status": "superseded", "superseded_by": current_hash})
        superseded = attach_hashes(body)
        path = _bundle_dir(project_dir) / f"{bundle_id}-v{bundle['bundle_version']}-superseded.json"
        _write_bundle(path, superseded)
        return superseded
    return bundle

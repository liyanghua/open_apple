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


def _bundle_dir(project_dir: Path, *, create: bool = True) -> Path:
    path = project_dir / "artifacts" / "approvals"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _write_bundle(
    path: Path, bundle: dict[str, Any], *, project_dir: Path, sink=None
) -> Path:
    validate_artifact("approval_bundle", bundle)
    from backlot.project_write_sink import require_project_sink

    write_sink = require_project_sink(project_dir, sink)
    if write_sink is not None:
        write_sink.stage_json(
            path.relative_to(project_dir).as_posix(), bundle, schema="approval_bundle"
        )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
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


def persist_approval_bundle_snapshot(
    project_dir: Path, bundle: dict[str, Any], *, sink=None
) -> Path:
    """Persist a canonical bundle as the versioned state ReviewService reads."""
    from backlot.project_write_sink import require_project_sink

    require_project_sink(project_dir, sink)
    validate_artifact("approval_bundle", bundle)
    bundle_id = str(bundle.get("bundle_id") or "")
    version = bundle.get("bundle_version")
    status = str(bundle.get("status") or "")
    if not bundle_id or Path(bundle_id).name != bundle_id:
        raise ValueError("approval bundle_id must be a safe file name")
    if not isinstance(version, int) or version < 1:
        raise ValueError("approval bundle_version must be a positive integer")
    if status != "awaiting_human":
        raise ValueError("new approval bundle snapshot must be awaiting_human")
    path = _bundle_dir(project_dir, create=sink is None) / (
        f"{bundle_id}-v{version}-{status}.json"
    )
    return _write_bundle(path, bundle, project_dir=project_dir, sink=sink)


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


def _assert_bundle_artifact_refs_current(
    project_dir: Path, bundle: dict[str, Any]
) -> None:
    """Reject approval when any reviewed artifact changed after bundle creation."""
    from backlot.operator_errors import OperatorError

    for ref in bundle.get("artifact_refs") or []:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise OperatorError("review_stale", "审批内容引用已失效，请刷新后重试", 409)
        path = (project_dir / ref["path"]).resolve()
        try:
            path.relative_to(project_dir.resolve())
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise OperatorError("review_stale", "审批内容引用已失效，请刷新后重试", 409) from exc
        if not isinstance(current, dict):
            raise OperatorError("review_stale", "审批内容引用已失效，请刷新后重试", 409)
        unhashed = {
            key: value for key, value in current.items()
            if key not in {"semantic_sha256", "artifact_sha256"}
        }
        recomputed = attach_hashes(unhashed)
        if (
            current.get("semantic_sha256") != recomputed.get("semantic_sha256")
            or current.get("artifact_sha256") != recomputed.get("artifact_sha256")
            or ref.get("semantic_sha256") != current.get("semantic_sha256")
            or ref.get("artifact_sha256") != current.get("artifact_sha256")
        ):
            raise OperatorError("review_stale", "审批内容已更新，请刷新后重试", 409)


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
        # Resume directive is operational bookkeeping (what the next session
        # does), not a creative input — the two-phase gate write must not
        # self-supersede when only next_action changed between phases.
        "next_action",
    ):
        stable.pop(key, None)
    artifacts = dict(stable.get("artifacts") or {})
    artifacts.pop("approval_bundle", None)
    stable["artifacts"] = artifacts
    return semantic_sha256(stable)


def _require_approved_creative_control_plan(
    project_dir: Path, group_name: str, group: dict[str, Any]
) -> None:
    """Require the fastline director contract before opening its creative gate."""

    if (
        group_name != "creative_lock"
        or "creative_control_plan" not in group.get("required_artifacts", [])
    ):
        return

    proposal_path = project_dir / "checkpoint_proposal.json"
    try:
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        plan = (proposal.get("artifacts") or {}).get("creative_control_plan")
    except (OSError, json.JSONDecodeError, AttributeError):
        plan = None
    if isinstance(plan, dict) and isinstance(plan.get("data"), dict):
        plan = plan["data"]

    if not isinstance(plan, dict) or plan.get("status") != "approved":
        raise ValueError(
            "creative_lock requires creative_control_plan status=approved before approval"
        )


def _candidate_variant_plan_ref(project_dir: Path) -> dict[str, str] | None:
    """Return the candidate plan's integrity reference for creative lock.

    Candidate projects are marked in ``project.json`` by ``batch_fork``.  The
    plan is written before proposal/assets, so it may not belong to any one
    stage checkpoint yet; the approval bundle therefore includes it directly.
    """
    marker_path = project_dir / "project.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        marker = {}
    candidate = marker.get("candidate") if isinstance(marker, dict) else None
    if not isinstance(candidate, dict) or not candidate.get("batch_id"):
        return None
    plan_path = project_dir / "artifacts" / "candidate_variant_plan.json"
    if not plan_path.is_file():
        raise ValueError(
            "candidate project is missing candidate_variant_plan; generate and review the default diversity plan before creative_lock"
        )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_artifact("candidate_variant_plan", plan)
    return {
        "name": "candidate_variant_plan",
        "path": "artifacts/candidate_variant_plan.json",
        "semantic_sha256": str(plan["semantic_sha256"]),
        "artifact_sha256": str(plan["artifact_sha256"]),
    }


def build_approval_bundle(
    project_dir: Path, manifest: dict[str, Any], group_name: str, *, sink=None
) -> dict[str, Any]:
    from backlot.project_write_sink import require_project_sink

    require_project_sink(project_dir, sink)
    group = (manifest.get("approval_groups") or {}).get(group_name)
    if not group:
        raise ValueError(f"unknown approval group: {group_name}")
    _require_approved_creative_control_plan(project_dir, group_name, group)
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
    variant_ref = _candidate_variant_plan_ref(project_dir) if group_name == "creative_lock" else None
    if variant_ref is not None and not any(
        ref.get("path") == variant_ref["path"] for ref in refs
    ):
        refs.append(variant_ref)
        input_hashes["candidate_variant_plan"] = variant_ref["semantic_sha256"]
    bundle_id = f"{project_id}-{group_name}"
    previous = list(_bundle_dir(project_dir, create=sink is None).glob(f"{bundle_id}-v*-*.json"))
    version = max([int(p.name.split("-v", 1)[1].split("-", 1)[0]) for p in previous] or [0]) + 1
    scope_fields: dict[str, Any] = {}
    asset_plan_path = project_dir / "artifacts" / "asset_plan.json"
    if asset_plan_path.is_file():
        try:
            asset_plan = json.loads(asset_plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            asset_plan = {}
        planned_assets = [item for item in asset_plan.get("planned_assets", []) if isinstance(item, dict)]
        cleanup_subjects = [
            str(item.get("approval_subject_hash") or "")
            for item in planned_assets
            if item.get("type") == "clean_product_reference"
            and item.get("paid") is True and item.get("exists") is False
        ]
        video_subjects = [
            str(item.get("approval_subject_hash") or "")
            for item in planned_assets
            if item.get("type") == "generated_video"
            and item.get("paid") is True and item.get("exists") is False
        ]
        subjects = cleanup_subjects or video_subjects
        if subjects and all(len(value) == 64 for value in subjects):
            scope_fields = {
                "approval_scope": "clean_reference" if cleanup_subjects else "image_to_video",
                "approval_subject_hashes": sorted(set(subjects)),
            }
    body = {"version": "1.0", "project_id": project_id, "created_at": datetime.now(timezone.utc).isoformat(), "producer": "approval_groups", "input_hashes": input_hashes, "bundle_id": bundle_id, "bundle_version": version, "group": group_name, "terminal_stage": group["terminal_stage"], "members": group["members"], "artifact_refs": refs, **scope_fields, "status": "awaiting_human"}
    bundle = attach_hashes(body)
    _write_bundle(
        _bundle_dir(project_dir, create=sink is None)
        / f"{bundle_id}-v{version}-awaiting_human.json",
        bundle,
        project_dir=project_dir,
        sink=sink,
    )
    return bundle


def lock_execution_after_creative_lock(
    project_dir: Path, *, approved_by: str,
    approval_scope: str | None = None,
    approved_subject_hashes: list[str] | None = None,
    sink=None,
) -> dict[str, dict[str, Any]]:
    """Lock the shot execution plan + authorize paid generation after the
    creative_lock bundle is approved.

    Returns the new artifact envelopes keyed by artifact name, so the caller can
    refresh the checkpoint envelopes in the same transaction (avoiding envelope
    drift between the rewritten artifacts and the already-written checkpoint).
    """
    from lib.artifact_io import write_artifact_atomic

    envelopes: dict[str, dict[str, Any]] = {}
    approved_at = datetime.now(timezone.utc).isoformat()
    if approval_scope not in {None, "clean_reference", "image_to_video", "all_paid_assets"}:
        raise ValueError(f"unsupported approval scope: {approval_scope}")
    approved_subject_set = set(approved_subject_hashes or [])
    ap_path = project_dir / "artifacts" / "asset_plan.json"
    try:
        current_asset_plan = json.loads(ap_path.read_text(encoding="utf-8")) if ap_path.is_file() else None
    except (OSError, json.JSONDecodeError):
        current_asset_plan = None
    if approval_scope in {"clean_reference", "image_to_video"}:
        if not isinstance(current_asset_plan, dict):
            raise ValueError("scoped creative approval requires asset_plan")
        scoped_type = "clean_product_reference" if approval_scope == "clean_reference" else "generated_video"
        expected_subjects = {
            str(item.get("approval_subject_hash") or "")
            for item in current_asset_plan.get("planned_assets", [])
            if isinstance(item, dict) and item.get("type") == scoped_type
            and item.get("paid") is True and item.get("exists") is False
        }
        if not expected_subjects or approved_subject_set != expected_subjects:
            raise ValueError("approved subject hashes do not match the current paid asset plan")
        if approval_scope == "image_to_video":
            try:
                ledger = json.loads((project_dir / "artifacts/product_asset_ledger.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("纯产品参考图尚未审核通过") from exc
            assets_by_id = {
                str(item.get("asset_id")): item for item in ledger.get("assets", [])
                if isinstance(item, dict) and item.get("asset_id")
            }
            for item in current_asset_plan.get("planned_assets", []):
                if not isinstance(item, dict) or item.get("type") != "generated_video":
                    continue
                reference = item.get("generation_reference") or {}
                asset = assets_by_id.get(str(reference.get("asset_id") or ""), {})
                if (
                    asset.get("clean_reference_status") != "ready"
                    or (asset.get("identity_check") or {}).get("status") != "pass"
                    or bool(asset.get("ocr_residual_text"))
                    or asset.get("generation_eligibility") != "eligible"
                    or asset.get("sha256") != reference.get("sha256")
                ):
                    raise ValueError("纯产品参考图尚未审核通过")

    should_lock_execution = approval_scope != "clean_reference"
    sep_path = project_dir / "artifacts" / "shot_execution_plan.json"
    if should_lock_execution and sep_path.is_file():
        try:
            sep = json.loads(sep_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sep = None
        if isinstance(sep, dict):
            sep = dict(sep)
            if approval_scope == "image_to_video":
                for shot in sep.get("shots", []):
                    if not isinstance(shot, dict) or shot.get("visual_route") != "generated_from_product_image":
                        continue
                    for proposal in shot.get("generation_proposals", []):
                        if not isinstance(proposal, dict):
                            continue
                        if proposal.get("approval_subject_hash") in approved_subject_set:
                            if not isinstance(proposal.get("selected_provider_candidate"), dict):
                                raise ValueError("image-to-video provider selection is missing")
                            proposal["provider_selection_status"] = "locked"
            sep["status"] = "approved"
            sep["approval"] = {"approved_by": approved_by, "approved_at": approved_at}
            envelopes["shot_execution_plan"] = write_artifact_atomic(
                "artifacts/shot_execution_plan.json", "shot_execution_plan", sep,
                project_dir=project_dir, sink=sink,
            )
    if ap_path.is_file():
        try:
            ap = json.loads(ap_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ap = None
        if isinstance(ap, dict):
            ap = dict(ap)
            if approval_scope is None:
                ap["approval_scope"] = "all_paid_assets"
                ap["approved_paid_subject_hashes"] = sorted({
                    str(item.get("approval_subject_hash"))
                    for item in ap.get("planned_assets", [])
                    if isinstance(item, dict) and item.get("paid") is True
                    and item.get("approval_subject_hash")
                })
                ap["paid_generation_approved"] = True
            else:
                ap["approval_scope"] = approval_scope
                ap["approved_paid_subject_hashes"] = sorted(approved_subject_set)
                ap["paid_generation_approved"] = approval_scope in {"image_to_video", "all_paid_assets"}
                if approval_scope == "image_to_video":
                    for item in ap.get("planned_assets", []):
                        if not isinstance(item, dict) or item.get("type") != "generated_video":
                            continue
                        if item.get("approval_subject_hash") in approved_subject_set:
                            generation_plan = item.get("generation_plan")
                            if isinstance(generation_plan, dict):
                                generation_plan["provider_selection_status"] = "locked"
            envelopes["asset_plan"] = write_artifact_atomic(
                "artifacts/asset_plan.json", "asset_plan", ap,
                project_dir=project_dir, sink=sink,
            )
    return envelopes


def approve_bundle(
    project_dir: Path,
    bundle_id: str,
    *,
    approved_by: str,
    expected_version: int | None = None,
    expected_hash: str | None = None,
    expected_approval_scope: str | None = None,
    expected_subject_hashes: list[str] | None = None,
    sink=None,
) -> Path:
    """Approve a bundle: a pure approval-group state transition.

    Does NOT apply any group-specific side effects (execution-plan locking or
    paid-generation authorization); the creative_lock side effect is applied
    explicitly by the caller (ReviewService.decide) via
    ``lock_execution_after_creative_lock``.
    """
    from backlot.project_write_sink import require_project_sink
    from backlot.operator_errors import OperatorError

    require_project_sink(project_dir, sink)
    source_path, bundle = _bundle_state(project_dir, bundle_id)
    if (
        (expected_version is not None and bundle.get("bundle_version") != expected_version)
        or (expected_hash is not None and bundle.get("semantic_sha256") != expected_hash)
    ):
        raise OperatorError("review_stale", "审批内容已更新，请刷新后重试", 409)
    bundle_scope = bundle.get("approval_scope")
    bundle_subjects = sorted(bundle.get("approval_subject_hashes") or [])
    if (
        bundle_scope != expected_approval_scope
        or bundle_subjects != sorted(expected_subject_hashes or [])
    ):
        raise OperatorError("review_stale", "付费审批范围已更新，请刷新后重试", 409)
    _assert_bundle_artifact_refs_current(project_dir, bundle)
    if bundle["status"] != "awaiting_human": raise ValueError("only awaiting_human bundles can be approved")
    body = {k: v for k, v in bundle.items() if k not in {"semantic_sha256", "artifact_sha256", "status", "approved_by"}}
    body.update({"status": "approved", "approved_by": approved_by})
    approved = attach_hashes(body)
    path = _bundle_dir(project_dir) / f"{bundle_id}-v{bundle['bundle_version']}-approved.json"
    _write_bundle(path, approved, project_dir=project_dir, sink=sink)
    return path


def reject_bundle(
    project_dir: Path,
    bundle_id: str,
    *,
    reason: str,
    expected_version: int | None = None,
    expected_hash: str | None = None,
    sink=None,
) -> Path:
    from backlot.project_write_sink import require_project_sink
    from backlot.operator_errors import OperatorError

    require_project_sink(project_dir, sink)
    _, bundle = _bundle_state(project_dir, bundle_id)
    if (
        (expected_version is not None and bundle.get("bundle_version") != expected_version)
        or (expected_hash is not None and bundle.get("semantic_sha256") != expected_hash)
    ):
        raise OperatorError("review_stale", "审批内容已更新，请刷新后重试", 409)
    if bundle["status"] != "awaiting_human": raise ValueError("only awaiting_human bundles can be rejected")
    body = {k: v for k, v in bundle.items() if k not in {"semantic_sha256", "artifact_sha256", "status", "rejected_reason"}}
    body.update({"status": "rejected", "rejected_reason": reason})
    rejected = attach_hashes(body)
    path = _bundle_dir(project_dir) / f"{bundle_id}-v{bundle['bundle_version']}-rejected.json"
    _write_bundle(path, rejected, project_dir=project_dir, sink=sink)
    return path


def inspect_bundle_reconciliation(
    project_dir: Path, terminal_checkpoint: dict[str, Any]
) -> dict[str, Any]:
    bundle_id = terminal_checkpoint.get("approval_bundle_id")
    if not bundle_id:
        return {"action": "unchanged", "bundle": {"status": "missing"}}
    _, bundle = _bundle_state(project_dir, bundle_id)
    current_hash = _approval_input_hash(terminal_checkpoint)
    expected = (bundle.get("input_hashes") or {}).get(bundle.get("terminal_stage"))
    if expected and expected != current_hash:
        body = {k: v for k, v in bundle.items() if k not in {"semantic_sha256", "artifact_sha256", "status", "superseded_by"}}
        body.update({"status": "superseded", "superseded_by": current_hash})
        superseded = attach_hashes(body)
        return {"action": "supersede", "bundle": superseded}
    return {"action": "unchanged", "bundle": bundle}


def reconcile_bundle(
    project_dir: Path, terminal_checkpoint: dict[str, Any], *, sink=None
) -> dict[str, Any]:
    from backlot.project_write_sink import require_project_sink

    require_project_sink(project_dir, sink)
    inspection = inspect_bundle_reconciliation(project_dir, terminal_checkpoint)
    bundle = inspection["bundle"]
    if inspection["action"] == "supersede":
        path = _bundle_dir(project_dir, create=sink is None) / (
            f"{bundle['bundle_id']}-v{bundle['bundle_version']}-superseded.json"
        )
        _write_bundle(path, bundle, project_dir=project_dir, sink=sink)
    return bundle

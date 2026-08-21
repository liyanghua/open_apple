"""Checkpoint writer/reader for pipeline state persistence.

Each stage writes a checkpoint after completion. The orchestrator uses
checkpoints to resume pipelines and to present state at human checkpoints.
"""

from __future__ import annotations

import json
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonschema

from schemas.artifacts import ARTIFACT_NAMES, validate_artifact

# All known stages across all pipelines (used only for artifact name lookup).
ALL_KNOWN_STAGES = frozenset([
    "research", "proposal", "idea", "script", "scene_plan",
    "assets", "edit", "compose", "publish",
])

# Backward-compatible alias — existing code / tests that import STAGES still work.
# New code should use get_pipeline_stages(pipeline_type) instead.
STAGES = ["research", "proposal", "idea", "script", "scene_plan",
          "assets", "edit", "compose", "publish"]

CANONICAL_STAGE_ARTIFACTS = {
    "research": "research_brief",
    "proposal": "proposal_packet",
    "idea": "brief",
    "script": "script",
    "scene_plan": "scene_plan",
    "assets": "asset_manifest",
    "edit": "edit_decisions",
    "compose": "render_report",
    "publish": "publish_log",
}

# Additional artifacts that may be produced alongside canonical ones.
# These are not stage-defining but are required by governance contracts.
SUPPLEMENTARY_ARTIFACTS = {
    "source_media_review",  # Required before first planning stage when user media exists
    "final_review",         # Required by compose stage before presenting to user
    "delivery_review",      # Optional operator decisions attached to compose
    "video_analysis_brief", # Reference-video grounding artifact carried alongside stages
    "media_index",
    "reference_fingerprint",
    "research_breakdown",
    "reference_source_matrix",
    "research_synthesis",
    "research_scorecard",
    "research_annotations",
    "production_lock",
    "approval_bundle",
    "asset_plan",
    "change_impact",
    "render_plan",
    "final_props",
    "sample_report",
}

FASTLINE_ARTIFACTS = frozenset({
    "media_index", "reference_fingerprint", "research_breakdown",
    "reference_source_matrix", "research_synthesis", "research_scorecard",
    "research_annotations", "production_lock",
    "approval_bundle", "asset_plan", "change_impact", "render_plan",
    "final_props", "sample_report",
})

# The fastline's director control plan is created during proposal and becomes
# the creative contract for every downstream planning/preparation stage.  It
# is deliberately not required for proposal itself: that is where the plan is
# authored and reviewed.
_CREATIVE_CONTROL_REQUIRED_STAGES = frozenset({"script", "scene_plan", "assets"})
_PRODUCTION_SCRIPT_REQUIRED_STAGES = frozenset({"scene_plan", "assets"})
_SHOT_EXECUTION_REQUIRED_STAGES = frozenset({"sample", "edit", "compose", "publish"})


def get_pipeline_stages(pipeline_type: str | None) -> list[str]:
    """Return the ordered stage list for a specific pipeline.

    Falls back to STAGES (deterministic canonical order) when pipeline_type
    is not provided or the manifest cannot be loaded.

    Previous versions used a set intersection here, which produced
    nondeterministic ordering. The fallback now uses a stable list.
    """
    if pipeline_type is None:
        # Deterministic canonical fallback — sorted to ensure stable ordering
        import logging
        logging.getLogger(__name__).warning(
            "get_pipeline_stages called without pipeline_type — "
            "using canonical fallback order. Pass pipeline_type for correctness."
        )
        return list(STAGES)

    try:
        from lib.pipeline_loader import load_pipeline_readonly, get_stage_order
        manifest = load_pipeline_readonly(pipeline_type)
        return get_stage_order(manifest)
    except (FileNotFoundError, Exception):
        # Graceful fallback: return all known stages in canonical order
        return list(STAGES)

CHECKPOINT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "checkpoints"
    / "checkpoint.schema.json"
)

# Canonical project root. Checkpoints, artifacts, and the project marker all
# live under PROJECTS_DIR/<project_id>/ — this is the location the Backlot
# board watches. Callers may still pass a different pipeline_dir (tests do),
# but production runs should use the default.
from lib.paths import PROJECTS_DIR  # noqa: E402  (single source of truth)

PROJECT_MARKER_FILENAME = "project.json"
HISTORY_DIRNAME = "history"


class CheckpointValidationError(ValueError):
    """Raised when a checkpoint or its canonical artifacts are invalid."""


def _validate_style_playbook(style_playbook: str | None) -> None:
    """Fail closed when a checkpoint names a visual identity that cannot load."""

    if style_playbook is None:
        return
    try:
        from styles.playbook_loader import list_playbooks, load_playbook

        load_playbook(style_playbook)
    except Exception as exc:
        try:
            available = list_playbooks()
        except Exception:
            available = []
        raise CheckpointValidationError(
            f"Unknown or invalid style_playbook {style_playbook!r}. "
            f"Available playbooks: {available}. Underlying error: {exc}"
        ) from exc


@lru_cache(maxsize=1)
def _load_checkpoint_schema() -> dict[str, Any]:
    with open(CHECKPOINT_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _validate_artifacts_for_stage(
    stage: str,
    status: str,
    artifacts: dict[str, Any],
    pipeline_type: str | None,
    project_dir: Path | None = None,
    sink=None,
) -> None:
    required_artifacts: list[str] = []
    validated_artifacts: dict[str, dict[str, Any]] = {}
    contract_v2 = False
    if pipeline_type and pipeline_type != "unknown":
        try:
            from lib.pipeline_loader import get_stage_produces, load_pipeline_readonly

            manifest = load_pipeline_readonly(pipeline_type)
            contract_v2 = manifest.get("artifact_contract_version") == 2
            if contract_v2:
                required_artifacts = get_stage_produces(manifest, stage)
        except Exception:
            contract_v2 = False

    if not contract_v2:
        fallback = CANONICAL_STAGE_ARTIFACTS.get(stage)
        if fallback is not None:
            required_artifacts = [fallback]

    if status in {"completed", "awaiting_human"}:
        missing = [name for name in required_artifacts if name not in artifacts]
        if missing:
            source = "manifest artifacts" if contract_v2 else "canonical artifact"
            raise CheckpointValidationError(
                f"Stage {stage!r} with status {status!r} must include {source}: "
                f"{', '.join(repr(name) for name in missing)}"
            )

    if "delivery_review" in artifacts and stage != "compose":
        raise CheckpointValidationError(
            "Artifact 'delivery_review' is an optional compose supplementary artifact"
        )

    for artifact_name, artifact_data in artifacts.items():
        if artifact_name not in ARTIFACT_NAMES:
            continue
        try:
            from lib.artifact_io import unwrap_checkpoint_artifact

            is_envelope = (
                isinstance(artifact_data, dict)
                and {"name", "path", "semantic_sha256", "artifact_sha256", "data"}
                <= artifact_data.keys()
            )
            if contract_v2 and not is_envelope:
                raise ValueError(
                    f"Contract v2 artifact {artifact_name!r} must use a v2 envelope"
                )
            if is_envelope and project_dir is None:
                raise ValueError("Project directory is required to verify artifact envelopes")
            if project_dir is not None:
                validated = unwrap_checkpoint_artifact(
                    project_dir, artifact_name, artifact_data, sink=sink
                )
            elif isinstance(artifact_data, dict):
                validate_artifact(artifact_name, artifact_data)
                validated = artifact_data
            else:
                raise ValueError(
                    f"Artifact {artifact_name!r} must be a JSON object matching its schema"
                )
            if isinstance(validated, dict):
                validated_artifacts[artifact_name] = validated
        except Exception as exc:
            raise CheckpointValidationError(
                f"Artifact {artifact_name!r} failed schema validation: {exc}"
            ) from exc

    if pipeline_type == "cinematic-fast" and stage == "research" and status == "completed":
        try:
            from lib.research_validation import validate_research_completion

            validate_research_completion(validated_artifacts["research_scorecard"])
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast research quality gate failed: {exc}"
            ) from exc

    if pipeline_type == "cinematic-fast" and stage == "proposal" and status in {"completed", "awaiting_human"}:
        try:
            from lib.artifact_io import unwrap_checkpoint_artifact
            from lib.research_validation import validate_proposal_research_handoff

            if project_dir is None:
                raise ValueError("proposal research handoff validation requires project_dir")
            with (project_dir / "checkpoint_research.json").open(encoding="utf-8") as handle:
                research_checkpoint = json.load(handle)
            synthesis = unwrap_checkpoint_artifact(
                project_dir,
                "research_synthesis",
                research_checkpoint["artifacts"]["research_synthesis"],
            )
            matrix = unwrap_checkpoint_artifact(
                project_dir,
                "reference_source_matrix",
                research_checkpoint["artifacts"]["reference_source_matrix"],
            )
            validate_proposal_research_handoff(
                validated_artifacts["proposal_packet"], synthesis, matrix
            )
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast proposal research handoff failed: {exc}"
            ) from exc

    if (
        pipeline_type == "cinematic-fast"
        and stage == "scene_plan"
        and status in {"completed", "awaiting_human"}
    ):
        if project_dir is None:
            raise CheckpointValidationError(
                "cinematic-fast scene mapping validation requires project_dir"
            )
        try:
            from lib.artifact_io import unwrap_checkpoint_artifact
            from lib.cinematic_fast_validation import validate_scene_mapping

            research_checkpoint_path = project_dir / "checkpoint_research.json"
            with research_checkpoint_path.open(encoding="utf-8") as handle:
                research_checkpoint = json.load(handle)
            source_envelope = research_checkpoint["artifacts"]["source_media_review"]
            analysis_envelope = research_checkpoint["artifacts"]["video_analysis_brief"]
            matrix_envelope = research_checkpoint["artifacts"]["reference_source_matrix"]
            synthesis_envelope = research_checkpoint["artifacts"].get("research_synthesis")
            source_media_review = unwrap_checkpoint_artifact(
                project_dir, "source_media_review", source_envelope
            )
            video_analysis_brief = unwrap_checkpoint_artifact(
                project_dir, "video_analysis_brief", analysis_envelope
            )
            reference_source_matrix = unwrap_checkpoint_artifact(
                project_dir, "reference_source_matrix", matrix_envelope
            )
            research_synthesis = (
                unwrap_checkpoint_artifact(project_dir, "research_synthesis", synthesis_envelope)
                if synthesis_envelope is not None
                else None
            )
            validate_scene_mapping(
                validated_artifacts["scene_plan"],
                source_media_review,
                video_analysis_brief,
                reference_source_matrix,
                research_synthesis,
            )
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast scene mapping validation failed: {exc}"
            ) from exc


def validate_checkpoint(
    checkpoint: dict[str, Any], *, project_dir: Path | None = None, sink=None
) -> None:
    """Validate checkpoint structure and canonical artifact payloads.

    Uses pipeline_type (if present) to resolve the valid stage list.
    Falls back to ALL_KNOWN_STAGES when pipeline_type is absent.
    """
    stage = checkpoint.get("stage")
    status = checkpoint.get("status")
    artifacts = checkpoint.get("artifacts")
    pipeline_type = checkpoint.get("pipeline_type")

    valid_stages = (
        set(get_pipeline_stages(pipeline_type)) if pipeline_type
        else ALL_KNOWN_STAGES
    )

    if not isinstance(stage, str) or stage not in valid_stages:
        raise CheckpointValidationError(
            f"Invalid stage: {stage!r} for pipeline {pipeline_type!r}. "
            f"Valid stages: {sorted(valid_stages)}"
        )
    if not isinstance(status, str):
        raise CheckpointValidationError(f"Invalid status: {status!r}")
    if not isinstance(artifacts, dict):
        raise CheckpointValidationError("Checkpoint artifacts must be a dictionary")

    _validate_artifacts_for_stage(
        stage, status, artifacts, pipeline_type, project_dir=project_dir, sink=sink
    )

    try:
        jsonschema.validate(instance=checkpoint, schema=_load_checkpoint_schema())
    except jsonschema.ValidationError as exc:
        raise CheckpointValidationError(f"Checkpoint failed schema validation: {exc.message}") from exc


def _checkpoint_path(pipeline_dir: Path, project_id: str, stage: str) -> Path:
    return pipeline_dir / project_id / f"checkpoint_{stage}.json"


def init_project(
    project_id: str,
    *,
    title: str,
    pipeline_type: str,
    pipeline_dir: Optional[Path] = None,
    style_playbook: Optional[str] = None,
) -> Path:
    """Initialize a project workspace with the canonical layout + marker file.

    Creates projects/<project_id>/ with the standard subdirectories and writes
    project.json — the marker the Backlot board uses to render a project's
    identity and stage rail before the first checkpoint exists.

    Idempotent: re-running preserves the original created_at and merges fields.
    Returns the project directory.
    """
    _validate_style_playbook(style_playbook)
    base = pipeline_dir or PROJECTS_DIR
    project_dir = base / project_id
    for sub in (
        "artifacts",
        "assets/images",
        "assets/video",
        "assets/audio",
        "assets/music",
        "renders",
    ):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    marker_path = project_dir / PROJECT_MARKER_FILENAME
    marker: dict[str, Any] = {}
    if marker_path.exists():
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker = json.load(f)
        except (json.JSONDecodeError, OSError):
            marker = {}

    marker.setdefault("version", "1.0")
    marker.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    marker["project_id"] = project_id
    marker["title"] = title
    marker["pipeline_type"] = pipeline_type
    if style_playbook is not None:
        marker["style_playbook"] = style_playbook

    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)

    return project_dir


def _stage_requires_approval(pipeline_type: Optional[str], stage: str) -> Optional[bool]:
    """Read human_approval_default for a stage from its pipeline manifest.

    Returns None when the stage isn't declared in the manifest or no
    pipeline_type was given — the caller then falls back to the value the
    agent passed in.

    A *provided but unknown* pipeline_type raises: a typo must not silently
    disable gate enforcement (fail-closed, not fail-open). Other manifest
    load failures are logged and fall back — a corrupt manifest shouldn't
    strand an otherwise-valid run, but the degradation must be visible.
    """
    if not pipeline_type or pipeline_type == "unknown":
        return None
    from lib.pipeline_loader import get_stage_human_approval_default, load_pipeline_readonly
    try:
        manifest = load_pipeline_readonly(pipeline_type)
    except FileNotFoundError:
        raise CheckpointValidationError(
            f"Unknown pipeline_type {pipeline_type!r} — cannot resolve gate "
            f"policy for stage {stage!r}. Check the spelling against "
            f"pipeline_defs/*.yaml."
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Gate policy unavailable for pipeline %r (%s) — falling back to "
            "the caller's human_approval_required flag.", pipeline_type, exc,
        )
        return None
    return get_stage_human_approval_default(manifest, stage)


def _enforce_approved_creative_control_plan(
    project_dir: Path,
    pipeline_type: str | None,
    stage: str,
    status: str,
) -> None:
    """Block fastline production advancement until the director contract is locked.

    The proposal UI can keep a plan in ``draft`` or ``needs_revision`` while
    the operator reviews it.  Those states are useful for editing, but must
    never be treated as authorization to generate the script, map shots, or
    prepare production assets.  Heartbeats remain writable so the board can
    report progress and the next session can resume.
    """

    if (
        pipeline_type != "cinematic-fast"
        or stage not in _CREATIVE_CONTROL_REQUIRED_STAGES
        or status not in {"awaiting_human", "completed"}
    ):
        return

    plan_path = project_dir / "artifacts" / "creative_control_plan.json"
    plan: dict[str, Any] | None = None
    try:
        with plan_path.open(encoding="utf-8") as handle:
            candidate = json.load(handle)
        if isinstance(candidate, dict):
            plan = candidate
    except (OSError, json.JSONDecodeError):
        plan = None

    if not plan or plan.get("status") != "approved":
        raise CheckpointValidationError(
            f"PREREQUISITE VIOLATION: stage {stage!r} cannot advance; "
            "导演总控单还没有“已锁定”状态（status 必须为 approved）。"
        )


def _enforce_approved_artifact_status(
    project_dir: Path,
    pipeline_type: str | None,
    stage: str,
    status: str,
    *,
    artifact_name: str,
    required_stages: frozenset[str],
    business_label: str,
) -> None:
    if (
        pipeline_type != "cinematic-fast"
        or stage not in required_stages
        or status not in {"awaiting_human", "completed"}
    ):
        return
    path = project_dir / "artifacts" / f"{artifact_name}.json"
    artifact: dict[str, Any] | None = None
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(candidate, dict):
            artifact = candidate
    except (OSError, json.JSONDecodeError):
        artifact = None
    if not artifact or artifact.get("status") != "approved":
        raise CheckpointValidationError(
            f"PREREQUISITE VIOLATION: stage {stage!r} cannot advance; "
            f"{business_label}还没有“已锁定”状态（status 必须为 approved）。"
        )


def _enforce_approved_production_script(
    project_dir: Path,
    pipeline_type: str | None,
    stage: str,
    status: str,
) -> None:
    _enforce_approved_artifact_status(
        project_dir,
        pipeline_type,
        stage,
        status,
        artifact_name="script",
        required_stages=_PRODUCTION_SCRIPT_REQUIRED_STAGES,
        business_label="制作剧本",
    )


def _enforce_approved_shot_execution_plan(
    project_dir: Path,
    pipeline_type: str | None,
    stage: str,
    status: str,
) -> None:
    _enforce_approved_artifact_status(
        project_dir,
        pipeline_type,
        stage,
        status,
        artifact_name="shot_execution_plan",
        required_stages=_SHOT_EXECUTION_REQUIRED_STAGES,
        business_label="镜头执行单",
    )


def _enforce_stage_prerequisites(
    pipeline_dir: Path,
    project_id: str,
    pipeline_type: str | None,
    stage: str,
    status: str,
) -> None:
    """Require completed, approved predecessors before advancing a stage.

    ``in_progress`` and failure heartbeats remain writable so an operator can
    inspect or resume a broken run. Only lifecycle advancement
    (``awaiting_human``/``completed``) is gated.
    """

    if status not in {"awaiting_human", "completed"}:
        return
    if not pipeline_type or pipeline_type == "unknown":
        return

    stages = get_pipeline_stages(pipeline_type)
    if stage not in stages:
        return

    incomplete: list[str] = []
    unapproved: list[str] = []
    for predecessor in stages[: stages.index(stage)]:
        path = _checkpoint_path(pipeline_dir, project_id, predecessor)
        if not path.exists():
            incomplete.append(predecessor)
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                checkpoint = json.load(handle)
            validate_checkpoint(
                checkpoint, project_dir=pipeline_dir / project_id
            )
        except (OSError, json.JSONDecodeError, CheckpointValidationError):
            incomplete.append(predecessor)
            continue
        if (
            checkpoint.get("project_id") != project_id
            or checkpoint.get("pipeline_type") != pipeline_type
            or checkpoint.get("stage") != predecessor
        ):
            incomplete.append(predecessor)
            continue
        if checkpoint.get("status") != "completed":
            incomplete.append(predecessor)
            continue
        if _stage_requires_approval(pipeline_type, predecessor) and not checkpoint.get(
            "human_approved"
        ):
            unapproved.append(predecessor)

    if incomplete or unapproved:
        details = []
        if incomplete:
            details.append(f"incomplete or missing: {incomplete}")
        if unapproved:
            details.append(f"completed without required approval: {unapproved}")
        raise CheckpointValidationError(
            f"PREREQUISITE VIOLATION: stage {stage!r} cannot advance; "
            + "; ".join(details)
            + f". Pipeline order: {stages}."
        )


def _archive_superseded_checkpoint(path: Path, stage: str) -> None:
    """Copy an existing checkpoint into history/ before it is overwritten.

    Preserves the full run record: stage re-runs (script v1 → v2) and gate
    transitions (awaiting_human → completed) remain reconstructable. Repeated
    in_progress refreshes are NOT archived — they are partial-progress
    heartbeats, not versions.

    Archiving is best-effort and must never crash a checkpoint write: the
    Backlot watcher may hold the file open (Windows denies renames of open
    files), so we copy rather than move, and swallow archival I/O failures.
    """
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError):
        existing = {}
    if existing.get("status") == "in_progress":
        return

    try:
        import shutil
        stamp = str(existing.get("timestamp", ""))
        safe_stamp = "".join(c for c in stamp if c.isalnum()) or f"{path.stat().st_mtime_ns}"
        history_dir = path.parent / HISTORY_DIRNAME
        history_dir.mkdir(parents=True, exist_ok=True)
        target = history_dir / f"checkpoint_{stage}_{safe_stamp}.json"
        if target.exists():
            target = history_dir / f"checkpoint_{stage}_{safe_stamp}_{path.stat().st_mtime_ns}.json"
        shutil.copyfile(path, target)
    except OSError:
        import logging
        logging.getLogger(__name__).warning(
            "Could not archive superseded checkpoint %s to history/", path
        )


def _decision_log_path(pipeline_dir: Path, project_id: str) -> Path:
    from lib.artifact_io import canonical_artifact_path

    return canonical_artifact_path(pipeline_dir / project_id, "decision_log")


def _legacy_decision_log_path(pipeline_dir: Path, project_id: str) -> Path:
    """The pre-v2 root log is read-only compatibility, never a write target."""
    return pipeline_dir / project_id / "decision_log.json"


def _merge_decision_log(
    pipeline_dir: Path, project_id: str, new_log: dict[str, Any], *, sink=None
) -> None:
    """Append new decisions to the canonical artifact decision log.

    The legacy project-root file is only read as a migration source.  The
    final write goes through ``write_artifact_atomic`` so a failed checkpoint
    validation cannot leave a partially updated decision log behind.
    """
    path = _decision_log_path(pipeline_dir, project_id)
    legacy_path = _legacy_decision_log_path(pipeline_dir, project_id)
    source = path if path.exists() else legacy_path
    if source.exists():
        with open(source, encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {"version": "1.0", "project_id": project_id, "decisions": []}
    if isinstance(existing, dict) and isinstance(existing.get("data"), dict):
        existing = existing["data"]
    if not isinstance(existing, dict):
        raise CheckpointValidationError("Decision log must be a JSON object")

    new_log_data = (
        new_log["data"]
        if isinstance(new_log.get("data"), dict)
        else new_log
    )
    existing_ids = {
        d.get("decision_id")
        for d in existing.get("decisions", [])
        if isinstance(d, dict) and d.get("decision_id")
    }
    for decision in new_log_data.get("decisions", []):
        if isinstance(decision, dict) and decision.get("decision_id") not in existing_ids:
            existing["decisions"].append(decision)
            existing_ids.add(decision["decision_id"])

    # Do not carry stale hash values into the new calculation.  The schema
    # accepts these fields for canonical v2 logs while remaining compatible
    # with older raw decision logs.
    for field in ("created_at", "producer", "input_hashes", "semantic_sha256", "artifact_sha256"):
        existing.pop(field, None)
    from lib.artifact_io import write_artifact_atomic

    write_artifact_atomic(
        "artifacts/decision_log.json",
        "decision_log",
        existing,
        project_dir=pipeline_dir / project_id,
        sink=sink,
    )


def write_checkpoint(
    pipeline_dir: Path,
    project_id: str,
    stage: str,
    status: str,
    artifacts: dict[str, Any],
    *,
    pipeline_type: Optional[str] = None,
    style_playbook: Optional[str] = None,
    checkpoint_policy: str = "guided",
    human_approval_required: bool = False,
    human_approved: bool = False,
    review: Optional[dict] = None,
    cost_snapshot: Optional[dict] = None,
    error: Optional[str] = None,
    next_action: Optional[dict] = None,
    metadata: Optional[dict] = None,
    approval_group: Optional[str] = None,
    approval_bundle_id: Optional[str] = None,
    approval_bundle_version: Optional[int] = None,
    sink=None,
) -> Path:
    """Write a checkpoint file for a pipeline stage."""
    from backlot.project_write_sink import require_project_sink

    project_dir = pipeline_dir / project_id
    write_sink = require_project_sink(project_dir, sink)
    # Backfill identity fields from the project marker so omitted kwargs
    # cannot bypass either gate enforcement or style validation.
    marker = None
    marker_path = pipeline_dir / project_id / PROJECT_MARKER_FILENAME
    if marker_path.exists() and (not pipeline_type or not style_playbook):
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker = json.load(f)
        except (json.JSONDecodeError, OSError):
            marker = None
    if isinstance(marker, dict):
        if not pipeline_type and marker.get("pipeline_type"):
            pipeline_type = marker["pipeline_type"]
        if not style_playbook and marker.get("style_playbook"):
            style_playbook = marker["style_playbook"]
    _validate_style_playbook(style_playbook)

    valid_stages = (
        set(get_pipeline_stages(pipeline_type)) if pipeline_type
        else ALL_KNOWN_STAGES
    )
    if stage not in valid_stages:
        raise ValueError(
            f"Invalid stage: {stage!r} for pipeline {pipeline_type!r}. "
            f"Valid stages: {sorted(valid_stages)}"
        )

    # --- Gate enforcement (GI-4) ---
    # The pipeline manifest is the binding source of truth for whether a stage
    # gates on human approval; a caller may gate MORE strictly (e.g. a
    # manual_all checkpoint policy) but never less. A gated stage can only be
    # written "completed" with explicit evidence of approval
    # (human_approved=True). Skipping a gate is a hard error.
    #
    # Enforcement happens at write time only: pre-existing checkpoints written
    # before gating (or by hand) still read as completed — deliberate
    # back-compat so in-flight and legacy projects keep resuming.
    manifest_gate = _stage_requires_approval(pipeline_type, stage)
    gated = bool(manifest_gate) or human_approval_required
    if gated:
        human_approval_required = True
        if status == "completed" and not human_approved:
            gate_source = (
                f"human_approval_default: true in the {pipeline_type!r} manifest"
                if manifest_gate
                else "human_approval_required=True was passed by the caller"
            )
            raise CheckpointValidationError(
                f"GATE VIOLATION: stage {stage!r} requires human approval "
                f"({gate_source}) but status='completed' was written without "
                f"human_approved=True. Correct protocol: write "
                f"status='awaiting_human', present the artifact summary to the "
                f"user, END YOUR TURN, and only after the user approves "
                f"re-write with status='completed', human_approved=True."
            )

    _enforce_stage_prerequisites(
        pipeline_dir,
        project_id,
        pipeline_type,
        stage,
        status,
    )

    _enforce_approved_creative_control_plan(
        project_dir,
        pipeline_type,
        stage,
        status,
    )
    _enforce_approved_production_script(
        project_dir,
        pipeline_type,
        stage,
        status,
    )
    _enforce_approved_shot_execution_plan(
        project_dir,
        pipeline_type,
        stage,
        status,
    )

    checkpoint = {
        "version": "1.0",
        "project_id": project_id,
        "pipeline_type": pipeline_type or "unknown",
        "stage": stage,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checkpoint_policy": checkpoint_policy,
        "human_approval_required": human_approval_required,
        "human_approved": human_approved,
        "artifacts": artifacts,
    }
    if style_playbook is not None:
        checkpoint["style_playbook"] = style_playbook
    if review is not None:
        checkpoint["review"] = review
    if cost_snapshot is not None:
        checkpoint["cost_snapshot"] = cost_snapshot
    if error is not None:
        checkpoint["error"] = error
    if next_action is not None:
        if not isinstance(next_action, dict):
            raise CheckpointValidationError("next_action must be a dict")
        next_action = dict(next_action)
        next_action.setdefault("set_at", datetime.now(timezone.utc).isoformat())
        checkpoint["next_action"] = next_action
    elif status in {"awaiting_human", "in_progress"}:
        # Fail closed on NEW resume-point checkpoints (review P1-③): the
        # documented contract (AGENT_GUIDE.md 关键路径纪律) requires a resume
        # directive on every in_progress/awaiting_human checkpoint, because
        # these are exactly the states a later session resumes from. Reading
        # legacy checkpoints written before this rule remains compatible —
        # validate_checkpoint does not require the field.
        raise CheckpointValidationError(
            f"Checkpoint {project_id}/{stage} written with status={status!r} "
            f"and no next_action. Per the resume-directive contract, every "
            f"in_progress/awaiting_human checkpoint must carry next_action "
            f"(summary + verb + context_refs) so a resumed session executes "
            f"instead of re-deriving state. See AGENT_GUIDE.md '关键路径纪律'."
        )
    if metadata is not None:
        checkpoint["metadata"] = metadata
    if approval_group is not None:
        checkpoint["approval_group"] = approval_group
    if approval_bundle_id is not None:
        checkpoint["approval_bundle_id"] = approval_bundle_id
    if approval_bundle_version is not None:
        checkpoint["approval_bundle_version"] = approval_bundle_version

    # Prepare the reference in memory.  Persisting the log is deliberately
    # deferred until after checkpoint validation below, so invalid checkpoint
    # writes cannot mutate the audit trail.
    pending_decision_log = artifacts.get("decision_log")
    if isinstance(pending_decision_log, dict):
        log_ref = str(_decision_log_path(pipeline_dir, project_id))
        for artifact_key in ("proposal_packet", "render_report"):
            if artifact_key not in artifacts or not isinstance(artifacts[artifact_key], dict):
                continue
            plan_or_top = artifacts[artifact_key]
            # V2 envelopes are immutable here; their referenced disk artifact
            # must be rewritten by its producer rather than silently changing
            # an embedded hash during checkpoint assembly.
            if {"name", "path", "semantic_sha256", "artifact_sha256", "data"} <= plan_or_top.keys():
                continue
            if artifact_key == "proposal_packet":
                plan = plan_or_top.get("production_plan")
                if isinstance(plan, dict):
                    plan["decision_log_ref"] = log_ref
            else:
                plan_or_top["decision_log_ref"] = log_ref

    validate_checkpoint(checkpoint, project_dir=project_dir, sink=write_sink)

    path = _checkpoint_path(pipeline_dir, project_id, stage)
    if write_sink is not None:
        if isinstance(pending_decision_log, dict):
            _merge_decision_log(
                pipeline_dir, project_id, pending_decision_log, sink=write_sink
            )
        write_sink.stage_json(
            path.relative_to(project_dir).as_posix(), checkpoint, schema="checkpoint"
        )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize to a temp file first so a mid-write failure (disk full,
    # unserializable metadata) can never leave the stage with a truncated
    # current checkpoint; then archive the superseded file and swap in the
    # new one atomically.
    tmp_path = path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2)
            f.flush()
            import os
            os.fsync(f.fileno())
        # The decision artifact is validated by validate_checkpoint above and
        # is persisted only after the complete checkpoint has been serialized.
        if isinstance(pending_decision_log, dict):
            _merge_decision_log(pipeline_dir, project_id, pending_decision_log)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    # Preserve run history: a superseded completed/awaiting_human checkpoint
    # is copied to history/ (stage versioning, gate audit trail, replay).
    _archive_superseded_checkpoint(path, stage)
    import os
    os.replace(tmp_path, path)

    return path


def read_checkpoint(
    pipeline_dir: Path, project_id: str, stage: str
) -> Optional[dict[str, Any]]:
    """Read a checkpoint file. Returns None if not found."""
    path = _checkpoint_path(pipeline_dir, project_id, stage)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        checkpoint = json.load(f)
    validate_checkpoint(checkpoint, project_dir=pipeline_dir / project_id)
    return checkpoint


def get_latest_checkpoint(
    pipeline_dir: Path, project_id: str
) -> Optional[dict[str, Any]]:
    """Find the most recent checkpoint for a project (by file mtime)."""
    project_dir = pipeline_dir / project_id
    if not project_dir.exists():
        return None

    checkpoints = sorted(
        project_dir.glob("checkpoint_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not checkpoints:
        return None

    with open(checkpoints[0], encoding="utf-8") as f:
        checkpoint = json.load(f)
    validate_checkpoint(checkpoint, project_dir=project_dir)
    return checkpoint


def get_completed_stages(
    pipeline_dir: Path, project_id: str, pipeline_type: str | None = None
) -> list[str]:
    """Return list of stages that have a completed checkpoint.

    When pipeline_type is provided, only checks stages defined in that
    pipeline's manifest — preventing false positives from leftover
    checkpoints of a different pipeline type.
    """
    stages_to_check = get_pipeline_stages(pipeline_type)
    completed = []
    for stage in stages_to_check:
        cp = read_checkpoint(pipeline_dir, project_id, stage)
        if cp and cp.get("status") == "completed":
            completed.append(stage)
    return completed


def get_next_stage(
    pipeline_dir: Path, project_id: str, pipeline_type: str | None = None
) -> Optional[str]:
    """Determine the next stage to run based on completed checkpoints.

    Uses pipeline-specific stage order so that pipelines with different
    stage sequences (e.g. cinematic vs explainer) progress correctly.
    """
    stages = get_pipeline_stages(pipeline_type) if pipeline_type else STAGES
    completed = set(get_completed_stages(pipeline_dir, project_id, pipeline_type))
    for stage in stages:
        if stage not in completed:
            return stage
    return None

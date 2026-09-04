"""Checkpoint writer/reader for pipeline state persistence.

Each stage writes a checkpoint after completion. The orchestrator uses
checkpoints to resume pipelines and to present state at human checkpoints.
"""

from __future__ import annotations

import contextlib
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
    "source_semantic_index",
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
    "sample_execution_trace",
    "differentiation_plan",
}

_SCENE_MAPPING_EVIDENCE_FIELDS = (
    "reference_basis", "source_fit", "mapping_reason", "originality_note",
)

FASTLINE_ARTIFACTS = frozenset({
    "media_index", "reference_fingerprint", "research_breakdown",
    "source_semantic_index",
    "reference_source_matrix", "research_synthesis", "research_scorecard",
    "research_annotations", "production_lock",
    "approval_bundle", "asset_plan", "change_impact", "render_plan",
    "final_props", "sample_report", "sample_execution_trace", "differentiation_plan",
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


def _validate_source_led_scene_mapping(
    scene_plan: dict[str, Any],
    *,
    input_mode: str = "source_led",
    source_media_review: dict[str, Any] | None = None,
    source_semantic_index: dict[str, Any] | None = None,
    reference_source_matrix: dict[str, Any] | None = None,
    research_synthesis: dict[str, Any] | None = None,
    project_dir: Path | None = None,
) -> None:
    """Validate source-led mappings without consulting reference media.

    Source-led projects ground every scene in reviewed owned footage and the
    Research evidence matrix. They never need a reference duration or scene.
    """
    import math

    def nonempty(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def interval(value: Any, label: str) -> tuple[float, float]:
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be an object")
        start = value.get("start_seconds")
        end = value.get("end_seconds_exclusive")
        if (
            isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not math.isfinite(start) or not math.isfinite(end)
            or start < 0 or end <= start
        ):
            raise ValueError(f"{label} must be a non-empty half-open interval")
        return float(start), float(end)

    metadata = scene_plan.get("metadata") if isinstance(scene_plan, dict) else None
    mappings = metadata.get("source_mapping") if isinstance(metadata, dict) else None
    if not isinstance(mappings, list):
        raise ValueError("metadata.source_mapping must be a list")
    if metadata.get("reference_media_usage") != "not_applicable":
        raise ValueError("source-led reference_media_usage must be not_applicable")
    scenes = scene_plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("scene_plan must contain scenes")
    scene_by_id: dict[str, dict[str, Any]] = {}
    for scene in scenes:
        if not isinstance(scene, dict) or not nonempty(scene.get("id")):
            raise ValueError("every scene must have a non-empty id")
        if not nonempty(scene.get("shot_intent")):
            raise ValueError(f"scene {scene.get('id')!r} must have a non-empty shot_intent")
        start = scene.get("start_seconds")
        end = scene.get("end_seconds")
        if (
            isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not math.isfinite(start) or not math.isfinite(end) or end <= start
        ):
            raise ValueError(f"scene {scene.get('id')!r} must have finite ordered timing")
        if scene["id"] in scene_by_id:
            raise ValueError("scene ids must be unique")
        scene_by_id[scene["id"]] = scene

    owned_sources = {
        item.get("path"): item
        for item in (source_media_review or {}).get("files", [])
        if isinstance(item, dict) and item.get("reviewed") is True and nonempty(item.get("path"))
    }
    matrix_rows = {
        item.get("matrix_row_id"): item
        for item in (reference_source_matrix or {}).get("rows", [])
        if isinstance(item, dict) and nonempty(item.get("matrix_row_id"))
    }
    if reference_source_matrix is not None:
        matrix_mode = reference_source_matrix.get("matrix_mode")
        if matrix_mode != input_mode:
            raise ValueError(
                f"source-led matrix_mode must match input_mode {input_mode!r}; "
                f"got {matrix_mode!r}"
            )
    semantic_entries: list[dict[str, Any]] = []
    if source_semantic_index is not None:
        if source_semantic_index.get("input_mode") != input_mode:
            raise ValueError("source_semantic_index.input_mode must match project input_mode")
        for entry in source_semantic_index.get("entries", []):
            if not isinstance(entry, dict) or not nonempty(entry.get("source_path")):
                raise ValueError("source_semantic_index entries require source_path")
            semantic_entries.append(entry)
    elif reference_source_matrix is not None:
        raise ValueError("source-led scene validation requires source_semantic_index")
    mapped_ids: list[str] = []
    allowed_modes = {"none"} if input_mode == "source_led" else {"none", "structural_only"}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise ValueError("every source mapping must be an object")
        scene_id = mapping.get("scene_id")
        if scene_id not in scene_by_id:
            raise ValueError("every source mapping must reference a declared scene")
        mapped_ids.append(scene_id)
        source_path = mapping.get("source_path")
        source = owned_sources.get(source_path)
        if source is None:
            raise ValueError(f"mapping for {scene_id!r} must use a reviewed owned source path")
        evidence = mapping.get("reference_evidence")
        if not isinstance(evidence, dict):
            raise ValueError(f"mapping for {scene_id!r} requires reference_evidence")
        mode = evidence.get("mode")
        if mode not in allowed_modes:
            raise ValueError(
                f"{input_mode} reference_evidence.mode must be one of {sorted(allowed_modes)}; got {mode!r}"
            )
        for field in _SCENE_MAPPING_EVIDENCE_FIELDS:
            if not nonempty(mapping.get(field)):
                raise ValueError(f"mapping for {scene_id!r} requires non-empty {field}")
        if mode == "structural_only":
            for field in ("mechanism", "rationale"):
                if not nonempty(evidence.get(field)):
                    raise ValueError(f"structural_only evidence requires {field}")
        for field in ("reference_scene_id", "reference_interval", "reference_path", "reference_paths"):
            if field in evidence and evidence.get(field) not in (None, [], ""):
                raise ValueError(f"source-led scene mapping must not include {field}")
        for field in ("reference_path", "reference_paths", "reference_media_path", "reference_media"):
            value = mapping.get(field)
            if value not in (None, [], ""):
                raise ValueError(f"source-led scene mapping must not include {field}")
        source_start, source_end = interval(mapping.get("source_interval"), "source_interval")
        timeline_start, timeline_end = interval(mapping.get("timeline_interval"), "timeline_interval")
        scene = scene_by_id[scene_id]
        if not math.isclose(timeline_start, float(scene.get("start_seconds")), abs_tol=1e-6) or not math.isclose(
            timeline_end, float(scene.get("end_seconds")), abs_tol=1e-6
        ):
            raise ValueError(f"timeline_interval for {scene_id!r} must match canonical scene timing")
        probe = source.get("technical_probe")
        duration = probe.get("duration_seconds") if isinstance(probe, dict) else None
        if source.get("media_type") in {"video", "audio"} and (
            isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or source_end > duration
        ):
            raise ValueError(f"source_interval for {scene_id!r} exceeds owned source duration")
        if reference_source_matrix is not None:
            primary_row_id = mapping.get("matrix_row_id")
            if mapping.get("evidence_row_ids") != [primary_row_id]:
                raise ValueError(
                    f"mapping for {scene_id!r} matrix_row_id requires evidence_row_ids == [matrix_row_id]"
                )
            row = matrix_rows.get(primary_row_id)
            if row is None or row.get("resolution") == "pending":
                raise ValueError(f"mapping for {scene_id!r} requires a resolved research matrix row")
            matrix_media_id = row.get("source_media_id")
            path_entries = [
                entry for entry in semantic_entries
                if entry.get("source_path") == source_path
            ]
            if not path_entries:
                raise ValueError(f"mapping for {scene_id!r} is missing source semantic evidence")
            media_entries = [
                entry for entry in path_entries
                if entry.get("media_id") == matrix_media_id == source.get("media_id")
            ]
            if not media_entries:
                raise ValueError(f"mapping for {scene_id!r} has inconsistent source media_id")
            hash_entries = [
                entry for entry in media_entries
                if entry.get("source_hash") == row.get("source_hash")
            ]
            if not hash_entries:
                raise ValueError(f"mapping for {scene_id!r} source hash does not match semantic index")
            if mapping.get("source_hash") != row.get("source_hash"):
                raise ValueError(
                    f"mapping for {scene_id!r} source_hash must equal primary evidence row"
                )
            if source.get("source_hash") not in (None, row.get("source_hash")):
                raise ValueError(
                    f"mapping for {scene_id!r} source hash does not match source review"
                )
            if project_dir is not None:
                source_file = Path(str(source_path))
                if not source_file.is_absolute():
                    source_file = project_dir / source_file
                if source_file.is_file():
                    import hashlib

                    digest = hashlib.sha256()
                    with source_file.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(65536), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != row.get("source_hash"):
                        raise ValueError(
                            f"mapping for {scene_id!r} source_hash does not match source file"
                        )
            matrix_interval = row.get("source_time_range")
            matrix_start, matrix_end = interval(matrix_interval, "matrix source_time_range")
            interval_entries = []
            for entry in hash_entries:
                semantic_start, semantic_end = interval(
                    entry.get("interval"), "semantic source interval"
                )
                if math.isclose(semantic_start, matrix_start, abs_tol=1e-6) and math.isclose(
                    semantic_end, matrix_end, abs_tol=1e-6
                ):
                    interval_entries.append(entry)
            if not interval_entries:
                raise ValueError(
                    f"matrix row for {scene_id!r} has no exact semantic source interval"
                )
            if len(interval_entries) != 1:
                raise ValueError(
                    f"matrix row for {scene_id!r} matches duplicate semantic entries"
                )
            semantic = interval_entries[0]
            if (semantic.get("quality") or {}).get("usable") is not True:
                raise ValueError(f"mapping for {scene_id!r} source semantic quality.usable must be true")
            if (semantic.get("crop_safety") or {}).get("subject_complete_in_3_4") is not True:
                raise ValueError(
                    f"mapping for {scene_id!r} source semantic "
                    "crop_safety.subject_complete_in_3_4 must be true"
                )
            representative_frames = {
                value for value in semantic.get("representative_frames", [])
                if isinstance(value, str) and value
            }
            row_frames = {
                value for value in row.get("evidence_frames", [])
                if isinstance(value, str) and value
            }
            if not representative_frames or not row_frames or not row_frames <= representative_frames:
                raise ValueError(
                    f"mapping for {scene_id!r} has missing or inconsistent representative evidence"
                )
            if matrix_media_id is not None and source.get("media_id") != matrix_media_id:
                source_frames = {
                    value for value in source.get("representative_frames", [])
                    if isinstance(value, str) and value
                }
                row_frames = {
                    value for value in row.get("evidence_frames", [])
                    if isinstance(value, str) and value
                }
                if not (source_frames & row_frames):
                    raise ValueError(
                        f"mapping for {scene_id!r} must use the approved research matrix source"
                    )
            if mapping.get("matrix_resolution_id") != row.get("resolution"):
                raise ValueError(f"mapping for {scene_id!r} must use the research matrix resolution")
            direction_ref = mapping.get("research_direction_ref")
            if not nonempty(direction_ref):
                raise ValueError(f"mapping for {scene_id!r} requires research_direction_ref")
            if research_synthesis is not None:
                directions = {
                    item.get("direction_id") for item in research_synthesis.get("differentiation_directions", [])
                    if isinstance(item, dict)
                }
                if direction_ref not in directions:
                    raise ValueError(f"mapping for {scene_id!r} references an unknown research direction")
            if source_start < matrix_start or source_end > matrix_end:
                raise ValueError(
                    f"mapping for {scene_id!r} must stay within the approved research matrix source interval"
                )
    if len(mapped_ids) != len(set(mapped_ids)) or set(mapped_ids) != set(scene_by_id):
        raise ValueError("scene_plan requires exactly one mapping per scene")


def _validate_source_led_template_prior(
    project_dir: Path, input_context: dict[str, Any]
) -> None:
    """Require source-led template priors to resolve to an intact template pack."""
    if input_context.get("input_mode") != "source_led_template":
        return
    template = input_context.get("template_prior")
    reference = template.get("template_pack_ref") if isinstance(template, dict) else None
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("source_led_template requires template_pack_ref")
    from pathlib import PurePosixPath
    relative = PurePosixPath(reference)
    if (
        relative.is_absolute()
        or len(relative.parts) < 2
        or relative.parts[0] != "artifacts"
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("template_pack_ref must be a project-relative artifacts path")
    target = (Path(project_dir).resolve() / Path(*relative.parts)).resolve()
    artifacts_root = (Path(project_dir).resolve() / "artifacts").resolve()
    if artifacts_root not in target.parents:
        raise ValueError("template_pack_ref must stay inside project artifacts")
    try:
        with target.open(encoding="utf-8") as handle:
            pack = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"template_pack_ref cannot be resolved: {exc}") from exc
    from lib.artifact_hashing import verify_hashes
    if not verify_hashes(pack).valid:
        raise ValueError("template_pack artifact hash verification failed")
    validate_artifact("template_pack", pack)


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
    input_mode: str | None = None
    input_context: dict[str, Any] | None = None
    if project_dir is not None and pipeline_type == "cinematic-fast":
        try:
            from lib.pipeline_loader import load_input_context
            input_context = load_input_context(project_dir)
            input_mode = input_context.get("input_mode")
        except FileNotFoundError:
            # Checkpoint-only tests and legacy callers may validate before a
            # marker exists; preserve the historical reference-driven path.
            input_mode = "reference_driven"
    if pipeline_type and pipeline_type != "unknown":
        try:
            from lib.pipeline_loader import get_stage_produces, load_pipeline_readonly

            manifest = load_pipeline_readonly(pipeline_type)
            contract_v2 = manifest.get("artifact_contract_version") == 2
            if contract_v2:
                required_artifacts = get_stage_produces(
                    manifest, stage, input_mode=input_mode
                )
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

    if (
        pipeline_type == "cinematic-fast"
        and stage in {"sample", "compose", "publish"}
        and status in {"completed", "awaiting_human"}
    ):
        from lib.template_alignment import alignment_checkpoint_gate

        evaluation = validated_artifacts.get("evaluation_report")
        if evaluation is None and project_dir is not None and stage == "publish":
            for filename in ("evaluation_report.final.json", "evaluation_report.json"):
                candidate = project_dir / "artifacts" / filename
                if candidate.is_file():
                    try:
                        evaluation = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        raise CheckpointValidationError(
                            f"publish gate: cannot read {filename}: {exc}"
                        ) from exc
                    break
        current_hashes: dict[str, str] = {}
        for canonical_name in ("script", "scene_plan", "shot_execution_plan", "final_props"):
            current = validated_artifacts.get(canonical_name)
            if current is None and project_dir is not None:
                candidate = project_dir / "artifacts" / f"{canonical_name}.json"
                if candidate.is_file():
                    try:
                        current = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        current = None
            if isinstance(current, dict):
                digest = current.get("artifact_sha256") or current.get("semantic_sha256")
                if digest:
                    current_hashes[canonical_name] = str(digest)
        sample_report = validated_artifacts.get("sample_report")
        render_report = validated_artifacts.get("render_report")
        if render_report is None and project_dir is not None and stage == "publish":
            candidate = project_dir / "artifacts" / "render_report.json"
            if candidate.is_file():
                try:
                    render_report = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    render_report = None
        render_hash = None
        if isinstance(sample_report, dict):
            render_hash = (sample_report.get("probe") or {}).get("sha256")
        if isinstance(render_report, dict):
            render_hash = render_report.get("video_master_sha256") or render_hash
        if render_hash is None and isinstance(evaluation, dict):
            render_hash = evaluation.get("subject_hash")
        if render_hash:
            current_hashes["render"] = str(render_hash)
        alignment_errors = alignment_checkpoint_gate(
            evaluation, input_mode=input_mode or "reference_driven", stage=stage,
            current_hashes=current_hashes,
        )
        if alignment_errors:
            raise CheckpointValidationError("; ".join(alignment_errors))

    if pipeline_type == "cinematic-fast" and stage == "research" and status == "completed":
        try:
            if project_dir is None:
                raise ValueError("research input-mode validation requires project_dir")
            _validate_source_led_template_prior(project_dir, input_context or {})
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast research input-mode gate failed: {exc}"
            ) from exc
        try:
            from lib.research_validation import validate_research_completion

            validate_research_completion(validated_artifacts["research_scorecard"])
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast research quality gate failed: {exc}"
            ) from exc
        try:
            from lib.research_validation import validate_research_derived_files

            if project_dir is None:
                raise ValueError("research derived-file validation requires project_dir")
            validate_research_derived_files(project_dir, validated_artifacts)
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast research derived-file gate failed: {exc}"
            ) from exc

    if pipeline_type == "cinematic-fast" and stage == "publish" and status in {"completed", "awaiting_human"}:
        # 评审缺口 #3：publish 三态语义的代码级执行。
        # 1) fatal L1a 一律阻止；2) revise 由用户确认（skill 层记录
        #    downgrade_approval 决策）；3) optimization 启用时必须双门通过。
        evaluation = validated_artifacts.get("evaluation_report")
        if isinstance(evaluation, dict) and evaluation.get("status") == "fail":
            raise CheckpointValidationError(
                "publish gate: evaluation_report.status=fail（fatal L1a）必须阻止 publish"
            )
        policy = validated_artifacts.get("optimization_policy")
        if isinstance(policy, dict) and policy.get("enabled") is True:
            run = validated_artifacts.get("optimization_run")
            opt = (
                evaluation.get("optimization")
                if isinstance(evaluation, dict) else None
            )
            run_passed = isinstance(run, dict) and run.get("status") == "passed"
            opt_passed = isinstance(opt, dict) and opt.get("passed") is True
            if not (run_passed and opt_passed):
                raise CheckpointValidationError(
                    "publish gate: optimization_policy.enabled=true 但优化门禁未通过"
                    "（需要 optimization_run.status=passed 且 evaluation_report.optimization.passed=true）"
                )

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
                validated_artifacts["proposal_packet"], synthesis, matrix,
                input_mode=input_mode,
            )
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast proposal research handoff failed: {exc}"
            ) from exc

    if (
        pipeline_type == "cinematic-fast"
        and stage == "script"
        and status in {"awaiting_human", "completed"}
        and input_mode in {"source_led", "source_led_template"}
    ):
        try:
            from lib.artifact_io import unwrap_checkpoint_artifact
            from lib.cinematic_fast_validation import validate_script_evidence_closure

            if project_dir is None:
                raise ValueError("source-led script evidence validation requires project_dir")
            with (project_dir / "checkpoint_research.json").open(encoding="utf-8") as handle:
                research_checkpoint = json.load(handle)
            matrix = unwrap_checkpoint_artifact(
                project_dir,
                "reference_source_matrix",
                research_checkpoint["artifacts"]["reference_source_matrix"],
            )
            product_facts = unwrap_checkpoint_artifact(
                project_dir, "product_facts", "artifacts/product_facts.json"
            )
            script = validated_artifacts["script"]
            if status == "completed" and script.get("status") != "approved":
                raise ValueError("completed source-led script must have status 'approved'")
            validate_script_evidence_closure(
                script, matrix, product_facts, input_mode=input_mode
            )
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast script evidence closure failed: {exc}"
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
            matrix_envelope = research_checkpoint["artifacts"]["reference_source_matrix"]
            synthesis_envelope = research_checkpoint["artifacts"].get("research_synthesis")
            source_media_review = unwrap_checkpoint_artifact(
                project_dir, "source_media_review", source_envelope
            )
            reference_source_matrix = unwrap_checkpoint_artifact(
                project_dir, "reference_source_matrix", matrix_envelope
            )
            research_synthesis = (
                unwrap_checkpoint_artifact(project_dir, "research_synthesis", synthesis_envelope)
                if synthesis_envelope is not None
                else None
            )
            scene_plan = validated_artifacts["scene_plan"]
            if input_mode in {"source_led", "source_led_template"}:
                with (project_dir / "checkpoint_script.json").open(encoding="utf-8") as handle:
                    script_checkpoint = json.load(handle)
                script = unwrap_checkpoint_artifact(
                    project_dir,
                    "script",
                    script_checkpoint["artifacts"]["script"],
                )
                if script.get("status") != "approved":
                    raise ValueError("source-led scene plan requires approved script")
                product_facts = unwrap_checkpoint_artifact(
                    project_dir, "product_facts", "artifacts/product_facts.json"
                )
                from lib.cinematic_fast_validation import (
                    validate_scene_evidence_closure,
                    validate_script_evidence_closure,
                )

                validate_script_evidence_closure(
                    script, reference_source_matrix, product_facts,
                    input_mode=input_mode,
                )
                validate_scene_evidence_closure(
                    scene_plan, script, reference_source_matrix,
                    input_mode=input_mode,
                )
                semantic_envelope = research_checkpoint["artifacts"]["source_semantic_index"]
                source_semantic_index = unwrap_checkpoint_artifact(
                    project_dir, "source_semantic_index", semantic_envelope
                )
                _validate_source_led_scene_mapping(
                    scene_plan,
                    input_mode=input_mode,
                    source_media_review=source_media_review,
                    source_semantic_index=source_semantic_index,
                    reference_source_matrix=reference_source_matrix,
                    research_synthesis=research_synthesis,
                    project_dir=project_dir,
                )
                return
            else:
                analysis_envelope = research_checkpoint["artifacts"]["video_analysis_brief"]
                video_analysis_brief = unwrap_checkpoint_artifact(
                    project_dir, "video_analysis_brief", analysis_envelope
                )
                scene_plan_for_validation = scene_plan
            validate_scene_mapping(
                scene_plan_for_validation,
                source_media_review,
                video_analysis_brief,
                reference_source_matrix,
                research_synthesis,
            )
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast scene mapping validation failed: {exc}"
            ) from exc

    if (
        pipeline_type == "cinematic-fast"
        and stage == "assets"
        and status in {"awaiting_human", "completed"}
        and input_mode in {"source_led", "source_led_template"}
    ):
        try:
            from lib.artifact_io import unwrap_checkpoint_artifact
            from lib.template_alignment import shot_execution_plan_errors

            if project_dir is None:
                raise ValueError("source-led shot execution validation requires project_dir")
            script = unwrap_checkpoint_artifact(
                project_dir, "script", "artifacts/script.json"
            )
            scene_plan = unwrap_checkpoint_artifact(
                project_dir, "scene_plan", "artifacts/scene_plan.json"
            )
            errors = shot_execution_plan_errors(
                validated_artifacts["shot_execution_plan"], script, scene_plan,
                audio_dir=project_dir / "assets" / "audio",
            )
            if errors:
                raise ValueError("; ".join(errors[:12]))
        except Exception as exc:
            raise CheckpointValidationError(
                f"cinematic-fast shot execution closure failed: {exc}"
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

    if project_dir is not None and pipeline_type == "cinematic-fast":
        try:
            from lib.pipeline_loader import load_input_context
            context = load_input_context(project_dir)
            checkpoint_mode = checkpoint.get("input_mode")
            if not context.get("legacy_compat") and checkpoint_mode is None:
                raise CheckpointValidationError(
                    "Checkpoint must include input_mode for a canonical project marker"
                )
            if checkpoint_mode is not None and checkpoint_mode != context.get("input_mode"):
                raise CheckpointValidationError(
                    "Checkpoint input_mode does not match project.json input_mode"
                )
        except FileNotFoundError:
            pass

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
    input_mode: Optional[str] = None,
    external_reference: Any = None,
    template_prior: Any = None,
    owned_source_root: Optional[str] = None,
) -> Path:
    """Initialize a project workspace with the canonical layout + marker file.

    Creates projects/<project_id>/ with the standard subdirectories and writes
    project.json — the marker the Backlot board uses to render a project's
    identity and stage rail before the first checkpoint exists.

    Idempotent: re-running preserves the original created_at and merges fields.
    Returns the project directory.
    """
    _validate_style_playbook(style_playbook)
    from lib.pipeline_loader import INPUT_MODES, _normalise_external_reference, _normalise_template_prior
    if input_mode is not None and input_mode not in INPUT_MODES:
        raise ValueError(f"Invalid input_mode {input_mode!r}; expected one of {sorted(INPUT_MODES)}")
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
    explicit_mode = input_mode is not None or (
        "input_mode" in marker and marker.get("input_mode_legacy_compat") is not True
    )
    mode = input_mode or marker.get("input_mode") or "reference_driven"
    if mode not in INPUT_MODES:
        raise ValueError(f"Invalid input_mode {mode!r}; expected one of {sorted(INPUT_MODES)}")
    external = _normalise_external_reference(
        external_reference if external_reference is not None else marker.get("external_reference")
    )
    template = _normalise_template_prior(
        template_prior if template_prior is not None else marker.get("template_prior")
    )
    if mode in {"source_led", "source_led_template"} and (
        external.get("present") or external.get("paths")
    ):
        raise ValueError(f"{mode} projects cannot declare external reference paths")
    if mode == "reference_driven" and explicit_mode:
        paths = external.get("paths") or []
        if not external.get("present") or not paths:
            raise ValueError(
                "reference_driven projects require external_reference.present=true and at least one path"
            )
        unresolved = []
        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = project_dir / path
            if not path.exists():
                unresolved.append(raw)
        if unresolved:
            raise ValueError(f"external reference paths are not resolvable: {unresolved}")
    if mode == "source_led" and template.get("present"):
        raise ValueError("source_led projects cannot declare a template prior")
    if mode == "source_led_template":
        if not template.get("present"):
            raise ValueError("source_led_template projects require a template prior")
        if not isinstance(template.get("template_pack_ref"), str) or not template["template_pack_ref"].strip():
            raise ValueError(
                "source_led_template projects require a non-empty template_pack_ref"
            )
        if template.get("usage") != "structural_only":
            raise ValueError("source_led_template template_prior.usage must be structural_only")
    marker["input_mode"] = mode
    marker["external_reference"] = external
    marker["template_prior"] = template
    marker["owned_source_root"] = owned_source_root or marker.get("owned_source_root") or "inputs/source"
    if input_mode is not None:
        marker.pop("input_mode_legacy_compat", None)
    elif not explicit_mode:
        marker["input_mode_legacy_compat"] = True

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
    *,
    sink=None,
) -> None:
    """Require completed, approved predecessors before advancing a stage.

    ``in_progress`` and failure heartbeats remain writable so an operator can
    inspect or resume a broken run. Only lifecycle advancement
    (``awaiting_human``/``completed``) is gated.

    ``sink`` makes predecessor validation read the transaction's staged view,
    so a same-transaction checkpoint re-sync (e.g. decision_log envelope
    refresh) is visible to the stage being advanced — without it, re-sync and
    advance must be split into two transactions.
    """

    if status not in {"awaiting_human", "completed"}:
        return
    if not pipeline_type or pipeline_type == "unknown":
        return

    stages = get_pipeline_stages(pipeline_type)
    if stage not in stages:
        return

    # Resolve mode-specific stage inputs.  Reference-only artifacts must not be
    # inherited by source-led runs, while genuinely required source-led
    # artifacts must exist before lifecycle advancement.
    mode_required: list[str] = []
    if pipeline_type == "cinematic-fast" and stage != "research":
        try:
            from lib.pipeline_loader import get_stage_required_artifacts, load_input_context, load_pipeline_readonly
            context = load_input_context(pipeline_dir / project_id)
            mode_required = get_stage_required_artifacts(
                load_pipeline_readonly(pipeline_type), stage, context=context
            )
        except FileNotFoundError:
            mode_required = []

    incomplete: list[str] = []
    available_artifacts: set[str] = set()
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
                checkpoint, project_dir=pipeline_dir / project_id, sink=sink
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
        if isinstance(checkpoint.get("artifacts"), dict):
            available_artifacts.update(checkpoint["artifacts"])
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
    if mode_required:
        missing_inputs = [name for name in mode_required if name not in available_artifacts]
        if missing_inputs:
            raise CheckpointValidationError(
                f"PREREQUISITE VIOLATION: stage {stage!r} missing mode-specific input artifacts: {missing_inputs}"
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


def _resync_checkpoint_artifacts(
    pipeline_dir: Path,
    project_id: str,
    artifact_name: str,
    envelope: dict[str, Any],
    *,
    sink=None,
    skip_stage: str | None = None,
) -> list[str]:
    """Re-embed a refreshed artifact envelope into checkpoints that carry it.

    Canonical artifacts are occasionally legitimately revised mid-run (the
    decision log grows on every append; render_plan flips sample→full at
    compose). Checkpoints embed v2 envelopes whose `data` must keep matching
    the disk artifact, so every affected checkpoint has to be re-synced in the
    same transaction — otherwise a later stage write fails prerequisite
    validation with "Artifact disk data does not match embedded checkpoint
    data".
    """
    project_dir = pipeline_dir / project_id
    resynced: list[str] = []
    for path in sorted(project_dir.glob("checkpoint_*.json")):
        try:
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(checkpoint, dict):
            continue
        if checkpoint.get("stage") == skip_stage:
            continue
        artifacts = checkpoint.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        if not isinstance(artifacts.get(artifact_name), dict):
            continue
        artifacts[artifact_name] = envelope
        # Validate before writing: a stale envelope here is exactly the
        # contract violation this helper exists to prevent.
        validate_checkpoint(checkpoint, project_dir=project_dir, sink=sink)
        relative = path.relative_to(project_dir).as_posix()
        if sink is not None:
            sink.stage_json(relative, checkpoint, schema="checkpoint")
        else:
            import os
            import tempfile

            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(checkpoint, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, path)
            except BaseException:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp_name)
                raise
        resynced.append(path.name)
    return resynced


def _merge_decision_log(
    pipeline_dir: Path, project_id: str, new_log: dict[str, Any], *, sink=None
) -> dict[str, Any]:
    """Append new decisions to the canonical artifact decision log.

    The legacy project-root file is only read as a migration source.  The
    final write goes through ``write_artifact_atomic`` so a failed checkpoint
    validation cannot leave a partially updated decision log behind.

    Returns the merged v2 envelope so callers can embed it (and so checkpoints
    that already embed a decision_log envelope can be re-synced in the same
    transaction).
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

    envelope = write_artifact_atomic(
        "artifacts/decision_log.json",
        "decision_log",
        existing,
        project_dir=pipeline_dir / project_id,
        sink=sink,
    )
    return envelope


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
    input_mode = None
    marker_path = pipeline_dir / project_id / PROJECT_MARKER_FILENAME
    if marker_path.exists():
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
        input_mode = marker.get("input_mode") or "reference_driven"
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
        sink=write_sink,
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
        **({"input_mode": input_mode} if input_mode else {}),
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

    # Prepare the reference in memory. Persisting the log stays deferred until
    # AFTER checkpoint validation, so an invalid checkpoint write cannot mutate
    # the audit trail (contract test: test_invalid_checkpoint_does_not_persist_
    # decision_log). After a successful validation, the merge result is
    # re-embedded so the stored envelope always matches the appended log.
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
    merged_log_envelope = None
    if isinstance(pending_decision_log, dict):
        merged_log_envelope = _merge_decision_log(
            pipeline_dir, project_id, pending_decision_log, sink=write_sink
        )
        # Re-embed the merge result: the caller's envelope may have described
        # only the pre-merge log, and the persisted checkpoint must reference
        # the post-merge artifact or every later stage write goes stale.
        artifacts["decision_log"] = merged_log_envelope
        # Earlier checkpoints that embed the log (proposal, prior compose runs)
        # must be re-synced in the same transaction, or their envelopes go
        # stale against the appended log.
        _resync_checkpoint_artifacts(
            pipeline_dir,
            project_id,
            "decision_log",
            merged_log_envelope,
            sink=write_sink,
            skip_stage=stage,
        )
    if write_sink is not None:
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


def sync_checkpoint_envelopes(
    project_dir: Path, checkpoint: dict[str, Any]
) -> list[str]:
    """Rebuild stale v2 envelopes inside one checkpoint from their disk files.

    Mutates ``checkpoint["artifacts"]`` in place and returns the artifact
    names that were refreshed. Used by ``refresh_checkpoint_envelopes`` and
    by legacy backfills that must re-sync (e.g. a drifted decision_log)
    before adding a missing artifact.
    """
    from lib.artifact_io import _artifact_relative_path, _contained_path

    artifacts = checkpoint.get("artifacts")
    if not isinstance(artifacts, dict):
        return []
    refreshed_names: list[str] = []
    for name, value in list(artifacts.items()):
        if not (
            isinstance(value, dict)
            and {"name", "path", "semantic_sha256", "artifact_sha256", "data"}
            <= value.keys()
        ):
            continue
        rel = str(value["path"])
        try:
            target = _contained_path(project_dir, _artifact_relative_path(rel))
        except ValueError:
            continue
        try:
            disk_value = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(disk_value, dict)
            and "data" in disk_value
            and "semantic_sha256" in disk_value
        ):
            disk_data = disk_value["data"]
        else:
            disk_data = disk_value
        if not isinstance(disk_data, dict):
            continue
        if (
            "semantic_sha256" not in disk_data
            or "artifact_sha256" not in disk_data
        ):
            continue
        if (
            value["data"] == disk_data
            and value["semantic_sha256"] == disk_data["semantic_sha256"]
        ):
            continue  # not stale
        artifacts[name] = {
            "name": name,
            "path": rel,
            "semantic_sha256": disk_data["semantic_sha256"],
            "artifact_sha256": disk_data["artifact_sha256"],
            "data": disk_data,
        }
        refreshed_names.append(name)
    return refreshed_names


def persist_checkpoint_atomic(
    pipeline_dir: Path,
    project_id: str,
    stage: str,
    checkpoint: dict[str, Any],
    *,
    sink=None,
) -> Path:
    """Validate and atomically persist one checkpoint — no decision-log merge.

    Unlike ``write_checkpoint`` this neither merges the decision log nor
    resyncs other checkpoints; it validates this checkpoint (and its prior
    stages, which must already be persisted) then swaps the file atomically.
    Used by ``refresh_checkpoint_envelopes`` and legacy contract backfills,
    where the producer must fix one stage without re-validating every later
    checkpoint mid-transition.
    """
    project_dir = pipeline_dir / project_id
    validate_checkpoint(checkpoint, project_dir=project_dir, sink=sink)
    path = _checkpoint_path(pipeline_dir, project_id, stage)
    if sink is not None:
        sink.stage_json(path.relative_to(project_dir).as_posix(), checkpoint, schema="checkpoint")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(checkpoint, handle, indent=2)
            handle.flush()
            import os

            os.fsync(handle.fileno())
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    _archive_superseded_checkpoint(path, stage)
    import os

    os.replace(tmp_path, path)
    return path


def refresh_checkpoint_envelopes(
    pipeline_dir: Path,
    project_id: str,
    *,
    pipeline_type: str | None = None,
    dry_run: bool = False,
    sink=None,
) -> dict[str, list[str]]:
    """Refresh stale v2 artifact envelopes across all checkpoints (评审 P2 B1).

    When an artifact file is rewritten on disk (a backfill repairs a report,
    a fingerprint is re-extracted, ...), every checkpoint that embedded the
    old content goes stale and later stage writes fail prerequisite
    validation with envelope drift. This rebuilds each envelope from its file
    on disk, re-validates, and re-persists the checkpoints in stage order so
    the whole run validates again. Returns {stage: [refreshed artifact names]}.
    """
    project_dir = pipeline_dir / project_id
    if not project_dir.is_dir():
        raise ValueError(f"project dir not found: {project_dir}")

    checkpoints: dict[str, dict[str, Any]] = {}
    for path in sorted(project_dir.glob("checkpoint_*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict) and raw.get("stage"):
            checkpoints[str(raw["stage"])] = raw

    stages = get_pipeline_stages(pipeline_type)
    ordered = [s for s in stages if s in checkpoints] + [
        s for s in checkpoints if s not in stages
    ]

    report: dict[str, list[str]] = {}
    for stage in ordered:
        checkpoint = checkpoints[stage]
        refreshed_names = sync_checkpoint_envelopes(project_dir, checkpoint)
        if not refreshed_names:
            continue
        if dry_run:
            report[stage] = refreshed_names
            continue
        persist_checkpoint_atomic(pipeline_dir, project_id, stage, checkpoint, sink=sink)
        report[stage] = refreshed_names
    return report


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

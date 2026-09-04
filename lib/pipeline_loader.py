"""Pipeline manifest loader.

Loads and validates pipeline YAML manifests from pipeline_defs/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml
import jsonschema


class PipelineManifestError(ValueError):
    """Raised when a manifest passes JSON Schema but violates workflow semantics."""


INPUT_MODES = frozenset({"reference_driven", "source_led", "source_led_template"})

PIPELINE_DEFS_DIR = Path(__file__).resolve().parent.parent / "pipeline_defs"
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "pipelines"
    / "pipeline_manifest.schema.json"
)


from functools import lru_cache


@lru_cache(maxsize=1)
def _load_manifest_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=64)
def _load_pipeline_cached(name: str, defs_dir_key: str) -> dict[str, Any]:
    """Cached manifest load. Treat the returned dict as READ-ONLY."""
    return load_pipeline(name, Path(defs_dir_key) if defs_dir_key else None)


def load_pipeline_readonly(name: str, defs_dir: Optional[Path] = None) -> dict[str, Any]:
    """Load a manifest through a cache. The result MUST NOT be mutated.

    Manifests are immutable within a run; hot paths (gate checks on every
    checkpoint write, board state derivation) should use this instead of
    re-parsing YAML + re-validating the schema each call.
    """
    return _load_pipeline_cached(name, str(defs_dir) if defs_dir else "")


def load_pipeline(name: str, defs_dir: Optional[Path] = None) -> dict[str, Any]:
    """Load and validate a pipeline manifest by name.

    Args:
        name: Pipeline name (without .yaml extension).
        defs_dir: Override directory for pipeline definitions.

    Returns:
        Validated pipeline manifest dict.
    """
    defs_dir = defs_dir or PIPELINE_DEFS_DIR
    path = defs_dir / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Pipeline manifest not found: {path}")

    with open(path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    schema = _load_manifest_schema()
    jsonschema.validate(instance=manifest, schema=schema)
    _validate_approval_groups(manifest)
    _validate_mode_requirements(manifest)

    return manifest


def _validate_mode_requirements(manifest: dict[str, Any]) -> None:
    """Validate mode requirement keys beyond the JSON schema's shape checks."""
    modes = manifest.get("mode_requirements") or {}
    for mode in modes:
        if mode not in INPUT_MODES and mode not in {"all_modes", "batch_root"}:
            raise PipelineManifestError(
                f"pipeline {manifest.get('name')}: unknown input mode {mode!r}"
            )
    stage_names = {stage.get("name") for stage in manifest.get("stages", [])}
    for mode, values in modes.items():
        if mode in {"all_modes", "batch_root"}:
            continue
        for key, artifacts in (values or {}).items():
            if not isinstance(artifacts, list):
                raise PipelineManifestError(
                    f"pipeline {manifest.get('name')} mode {mode}: {key} must be a list"
                )
            if key.endswith(("_required", "_produces")):
                stage = key.rsplit("_", 1)[0]
                if stage not in stage_names:
                    raise PipelineManifestError(
                        f"pipeline {manifest.get('name')} mode {mode}: unknown stage in {key!r}"
                    )


def _normalise_external_reference(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"present": value, "paths": [], "usage": "analysis_only" if value else "not_applicable"}
    if isinstance(value, (list, tuple)):
        paths = [str(item) for item in value if str(item).strip()]
        return {"present": bool(paths), "paths": paths, "usage": "analysis_only" if paths else "not_applicable"}
    if isinstance(value, dict):
        result = dict(value)
        paths = result.get("paths")
        if not isinstance(paths, list):
            paths = []
        result["paths"] = [str(item) for item in paths if str(item).strip()]
        result.setdefault("present", bool(result["paths"]))
        result.setdefault("usage", "analysis_only" if result["present"] else "not_applicable")
        return result
    return {"present": False, "paths": [], "usage": "not_applicable"}


def _normalise_template_prior(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"present": value, "usage": "structural_only" if value else "not_applicable"}
    if isinstance(value, str):
        return {"present": bool(value), "usage": "structural_only" if value else "not_applicable", "template_pack_ref": value}
    if isinstance(value, dict):
        result = dict(value)
        result.setdefault("present", bool(str(result.get("template_pack_ref") or "").strip()))
        result.setdefault("usage", "structural_only" if result["present"] else "not_applicable")
        return result
    return {"present": False, "usage": "not_applicable"}


def load_input_context(project_dir: str | Path) -> dict[str, Any]:
    """Load and normalize the project's input-mode contract.

    Projects created before input modes existed intentionally default to
    ``reference_driven`` so their existing checkpoints remain resumable.
    """
    marker_path = Path(project_dir) / "project.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"Project marker not found: {marker_path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineManifestError(f"Invalid project marker: {marker_path}") from exc
    if not isinstance(marker, dict):
        raise PipelineManifestError("project.json must be an object")
    legacy_compat = "input_mode" not in marker or marker.get("input_mode_legacy_compat") is True
    mode = marker.get("input_mode") or "reference_driven"
    if mode not in INPUT_MODES:
        raise PipelineManifestError(
            f"Invalid input_mode {mode!r}; expected one of {sorted(INPUT_MODES)}"
        )
    external = _normalise_external_reference(marker.get("external_reference"))
    template = _normalise_template_prior(marker.get("template_prior"))
    owned_root = marker.get("owned_source_root") or "inputs/source"
    if not isinstance(owned_root, str) or not owned_root.strip():
        raise PipelineManifestError("owned_source_root must be a non-empty path")
    if mode == "reference_driven" and not legacy_compat:
        paths = external.get("paths") or []
        if not external.get("present") or not paths:
            raise PipelineManifestError(
                "reference_driven projects require external_reference.present=true and at least one path"
            )
        unresolved = []
        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = Path(project_dir) / path
            if not path.exists():
                unresolved.append(raw)
        if unresolved:
            raise PipelineManifestError(
                f"external reference paths are not resolvable: {unresolved}"
            )
    if mode in {"source_led", "source_led_template"} and (
        external.get("present") or external.get("paths")
    ):
        raise PipelineManifestError(
            f"{mode} projects cannot declare external reference paths"
        )
    if mode == "source_led" and template.get("present"):
        raise PipelineManifestError("source_led projects cannot declare a template prior")
    if mode == "source_led_template":
        if not template.get("present"):
            raise PipelineManifestError("source_led_template projects require a template prior")
        if not isinstance(template.get("template_pack_ref"), str) or not template["template_pack_ref"].strip():
            raise PipelineManifestError(
                "source_led_template projects require a non-empty template_pack_ref"
            )
        if template.get("usage") != "structural_only":
            raise PipelineManifestError(
                "source_led_template template_prior.usage must be structural_only"
            )
    return {
        "project_id": marker.get("project_id"),
        "pipeline_type": marker.get("pipeline_type"),
        "input_mode": mode,
        "external_reference": external,
        "template_prior": template,
        "owned_source_root": owned_root,
        "legacy_compat": legacy_compat,
    }


def _validate_approval_groups(manifest: dict[str, Any]) -> None:
    groups = manifest.get("approval_groups", {}) or {}
    stages = {stage["name"]: stage for stage in manifest.get("stages", [])}
    ownership: dict[str, str] = {}
    for group_name, group in groups.items():
        members = group["members"]
        terminal = group["terminal_stage"]
        if terminal not in members:
            raise PipelineManifestError(f"pipeline {manifest.get('name')} approval group {group_name}: terminal stage is not a member")
        if not stages.get(terminal, {}).get("approval_group_terminal", False):
            raise PipelineManifestError(f"pipeline {manifest.get('name')} approval group {group_name}: terminal stage {terminal} is not marked terminal")
        for member in members:
            if member not in stages:
                raise PipelineManifestError(f"pipeline {manifest.get('name')} approval group {group_name}: unknown stage {member}")
            if member in ownership and ownership[member] != group_name:
                raise PipelineManifestError(f"pipeline {manifest.get('name')} stage {member}: duplicated approval group ownership")
            ownership[member] = group_name
            if member != terminal and stages[member].get("human_approval_default", False):
                raise PipelineManifestError(f"pipeline {manifest.get('name')} approval group {group_name}: non-terminal member {member} cannot gate independently")
        produced = {artifact for member in members for artifact in stages[member].get("produces", [])}
        missing = [artifact for artifact in group.get("required_artifacts", []) if artifact not in produced]
        if missing:
            raise PipelineManifestError(f"pipeline {manifest.get('name')} approval group {group_name}: required artifacts missing {missing}")


def get_approval_group(manifest: dict[str, Any], stage_name: str) -> dict[str, Any] | None:
    for name, group in (manifest.get("approval_groups", {}) or {}).items():
        if stage_name in group.get("members", []):
            return {"name": name, **group}
    return None


def get_approval_group_terminal(manifest: dict[str, Any], group_name: str) -> str | None:
    group = (manifest.get("approval_groups", {}) or {}).get(group_name)
    return group.get("terminal_stage") if group else None


def stage_is_group_terminal(manifest: dict[str, Any], stage_name: str) -> bool:
    group = get_approval_group(manifest, stage_name)
    return bool(group and group.get("terminal_stage") == stage_name)


def list_pipelines(defs_dir: Optional[Path] = None) -> list[str]:
    """List all available pipeline manifest names."""
    defs_dir = defs_dir or PIPELINE_DEFS_DIR
    return [p.stem for p in defs_dir.glob("*.yaml")]


def _condition_is_active(condition: Optional[str], context: Optional[dict[str, Any]]) -> bool:
    """Evaluate a simple manifest condition against runtime context."""
    if not condition:
        return True
    if not context:
        return False
    return bool(context.get(condition))


def get_reference_input_config(manifest: dict) -> dict[str, Any]:
    """Return reference-input configuration, defaulting to disabled."""
    return manifest.get("reference_input", {}) or {}


def pipeline_supports_reference_input(manifest: dict) -> bool:
    """Whether the manifest declares support for reference-video input."""
    return bool(get_reference_input_config(manifest).get("supported", False))


def get_stage_sub_stages(
    manifest: dict,
    stage_name: str,
    *,
    context: Optional[dict[str, Any]] = None,
    include_inactive: bool = True,
) -> list[dict[str, Any]]:
    """Return sub-stage definitions for a stage.

    By default this returns all declared sub-stages so agents can inspect the
    full workflow shape. Pass ``include_inactive=False`` with context to filter
    to active sub-stages only.
    """
    for stage in manifest["stages"]:
        if stage["name"] != stage_name:
            continue
        sub_stages = list(stage.get("sub_stages", []))
        if include_inactive:
            return sub_stages
        return [
            sub_stage
            for sub_stage in sub_stages
            if _condition_is_active(sub_stage.get("condition"), context)
        ]
    return []


def get_stage_order(
    manifest: dict,
    *,
    include_sub_stages: bool = False,
    context: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Extract the ordered list of stage names from a manifest.

    ``include_sub_stages=True`` exposes declarative sample/preview units to the
    agent without turning them into mandatory checkpoint stages. Sub-stages are
    emitted as ``<stage>.<sub_stage>``.
    """
    order: list[str] = []
    for stage in manifest["stages"]:
        order.append(stage["name"])
        if not include_sub_stages:
            continue
        for sub_stage in get_stage_sub_stages(
            manifest,
            stage["name"],
            context=context,
            include_inactive=context is None,
        ):
            order.append(f"{stage['name']}.{sub_stage['name']}")
    return order


def get_required_tools(
    manifest: dict,
    *,
    input_mode: str | None = None,
    context: dict[str, Any] | None = None,
) -> set[str]:
    """Collect tools across stages, sub-stages, and reference-input analysis."""
    mode = input_mode or (context or {}).get("input_mode")
    if mode is not None and mode not in INPUT_MODES:
        raise PipelineManifestError(f"Invalid input_mode {mode!r}")
    tools: set[str] = set()
    for stage in manifest["stages"]:
        tools.update(get_stage_required_tools(manifest, stage["name"], input_mode=mode))
        tools.update(stage.get("preferred_tools", []))
        tools.update(stage.get("fallback_tools", []))
        tools.update(stage.get("tools_available", []))
        for sub_stage in stage.get("sub_stages", []):
            tools.update(sub_stage.get("tools_available", []))
    tools.update(get_reference_input_config(manifest).get("analysis_tools", []))
    if mode in {"source_led", "source_led_template"}:
        # frame_sampler / scene_detect still analyze owned footage. The
        # reference-video analyzer itself must not enter source-led preflight.
        tools.discard("video_analyzer")
    return tools


def get_stage_required_tools(
    manifest: dict[str, Any], stage_name: str, *, input_mode: str | None = None,
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Return required tools for a stage after applying the input mode."""
    stage = next(
        (item for item in manifest.get("stages", []) if item.get("name") == stage_name),
        None,
    )
    if stage is None:
        return []
    mode = input_mode or (context or {}).get("input_mode")
    if mode is None:
        return list(stage.get("required_tools", []))
    if mode not in INPUT_MODES:
        raise PipelineManifestError(f"Invalid input_mode {mode!r}")
    modes = manifest.get("mode_requirements") or {}
    key = f"{stage_name}_required_tools"
    controlled = {
        tool for values in modes.values() if isinstance(values, dict)
        for tool in (values.get(key, []) or [])
    }
    result = [tool for tool in stage.get("required_tools", []) if tool not in controlled]
    for tool in [*((modes.get("all_modes") or {}).get(key, []) or []), *((modes.get(mode) or {}).get(key, []) or [])]:
        if tool not in result:
            result.append(tool)
    return result


def get_stage_skill(manifest: dict, stage_name: str) -> Optional[str]:
    """Get the skill path for an instruction-driven stage."""
    for stage in manifest["stages"]:
        if stage["name"] == stage_name:
            return stage.get("skill")
    return None


def _resolve_mode_artifacts(
    manifest: dict[str, Any],
    stage_name: str,
    kind: str,
    input_mode: str | None = None,
) -> list[str]:
    """Resolve mode-specific stage artifacts, replacing static mode entries."""
    stage = next(
        (item for item in manifest.get("stages", []) if item.get("name") == stage_name),
        None,
    )
    if stage is None:
        return []
    base = list(stage.get(f"{kind}_artifacts_in" if kind == "required" else kind, []))
    if input_mode is None:
        return base
    if input_mode not in INPUT_MODES:
        raise PipelineManifestError(f"Invalid input_mode {input_mode!r}")
    modes = manifest.get("mode_requirements") or {}
    common = list((modes.get("all_modes") or {}).get(f"{stage_name}_{kind}", []))
    selected = list((modes.get(input_mode) or {}).get(f"{stage_name}_{kind}", []))
    # Any artifact named by a mode-specific variant is mode-controlled. Remove
    # all such names from the legacy static list before adding the selected
    # variant, preventing a union from keeping reference-only inputs alive.
    controlled: set[str] = set()
    for values in modes.values():
        if not isinstance(values, dict):
            continue
        controlled.update(values.get(f"{stage_name}_{kind}", []) or [])
    result = [name for name in base if name not in controlled]
    for name in [*common, *selected]:
        if name not in result:
            result.append(name)
    return result


def get_stage_required_artifacts(
    manifest: dict[str, Any], stage_name: str, *, input_mode: str | None = None,
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Return resolved stage inputs for an input mode.

    ``context`` may be the result of :func:`load_input_context`; an explicit
    ``input_mode`` wins when both are supplied.
    """
    mode = input_mode or (context or {}).get("input_mode")
    return _resolve_mode_artifacts(manifest, stage_name, "required", mode)


def get_stage_produces(
    manifest: dict[str, Any], stage_name: str, *, input_mode: str | None = None,
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Return mode-resolved artifacts declared as produced by a stage."""
    mode = input_mode or (context or {}).get("input_mode")
    return _resolve_mode_artifacts(manifest, stage_name, "produces", mode)


# Descriptive alias used by stage directors and external integrations.
resolve_stage_requirements = get_stage_required_artifacts


def get_stage_human_approval_default(manifest: dict, stage_name: str) -> Optional[bool]:
    """Whether a stage gates on human approval. None if the stage isn't declared.

    This is the single lookup used by gate enforcement (lib/checkpoint.py)
    and the Backlot board — keep them reading the same field the same way.
    """
    for stage in manifest["stages"]:
        if stage["name"] == stage_name:
            return bool(stage.get("human_approval_default", False))
    return None


def get_stage_review_focus(manifest: dict, stage_name: str) -> list[str]:
    """Get the review focus items for a stage."""
    for stage in manifest["stages"]:
        if stage["name"] == stage_name:
            return stage.get("review_focus", [])
    return []


# ---------------------------------------------------------------------------
# Capability-Extension Enforcement
# ---------------------------------------------------------------------------

class ExtensionNotPermitted(PermissionError):
    """Raised when a capability extension is used but not permitted by the pipeline."""


def check_extension_permitted(
    manifest: dict,
    extension_type: str,
) -> None:
    """Enforce that a capability extension is permitted by the pipeline manifest.

    Args:
        manifest: Loaded pipeline manifest dict.
        extension_type: One of 'custom_scripts', 'custom_playbooks',
                        'custom_skills', 'custom_tools'.

    Raises:
        ExtensionNotPermitted: If the extension is not allowed.
    """
    valid_extensions = {"custom_scripts", "custom_playbooks", "custom_skills", "custom_tools"}
    if extension_type not in valid_extensions:
        raise ValueError(
            f"Unknown extension type {extension_type!r}. "
            f"Valid types: {sorted(valid_extensions)}"
        )

    extensions = manifest.get("extensions", {})
    if not extensions.get(extension_type, False):
        raise ExtensionNotPermitted(
            f"Pipeline {manifest.get('name', 'unknown')!r} does not permit "
            f"{extension_type}. Set extensions.{extension_type}: true in the "
            f"pipeline manifest to allow this."
        )


def get_permitted_extensions(manifest: dict) -> dict[str, bool]:
    """Return the extension permission flags for a pipeline."""
    defaults = {
        "custom_scripts": False,
        "custom_playbooks": False,
        "custom_skills": False,
        "custom_tools": False,
    }
    extensions = manifest.get("extensions", {})
    return {k: extensions.get(k, v) for k, v in defaults.items()}

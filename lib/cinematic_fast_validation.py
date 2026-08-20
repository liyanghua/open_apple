"""Pipeline-specific semantic validation for cinematic-fast artifacts."""

from __future__ import annotations

import math
from typing import Any, Mapping


_EVIDENCE_FIELDS = (
    "reference_basis",
    "source_fit",
    "mapping_reason",
    "originality_note",
)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _validate_interval(
    mapping: Mapping[str, Any], field: str
) -> tuple[float, float]:
    interval = mapping.get(field)
    if not isinstance(interval, Mapping):
        raise ValueError(f"{field} must be an object")
    start = interval.get("start_seconds")
    end = interval.get("end_seconds_exclusive")
    if (
        not _finite_number(start)
        or not _finite_number(end)
    ):
        raise ValueError(f"{field} values must be finite numbers")
    if (
        start < 0
        or end <= start
    ):
        raise ValueError(f"{field} must be a non-empty half-open interval")
    return float(start), float(end)


def validate_scene_mapping(
    scene_plan: Mapping[str, Any],
    source_media_review: Mapping[str, Any],
    video_analysis_brief: Mapping[str, Any],
    reference_source_matrix: Mapping[str, Any] | None = None,
    research_synthesis: Mapping[str, Any] | None = None,
) -> None:
    """Reject scene plans whose source mapping is not grounded and traceable."""
    metadata = scene_plan.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("scene_plan metadata is required")
    if metadata.get("reference_media_usage") != "analysis_only":
        raise ValueError("reference_media_usage must be analysis_only")

    scenes = scene_plan.get("scenes")
    mappings = metadata.get("source_mapping")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("scene_plan must contain scenes")
    if not isinstance(mappings, list):
        raise ValueError("metadata.source_mapping must be a list")

    scene_ids: list[str] = []
    scene_by_id: dict[str, Mapping[str, Any]] = {}
    for scene in scenes:
        if not isinstance(scene, Mapping) or not _nonempty(scene.get("id")):
            raise ValueError("every scene must have a non-empty id")
        if not _nonempty(scene.get("shot_intent")):
            raise ValueError(f"scene {scene.get('id')!r} must have a non-empty shot_intent")
        start = scene.get("start_seconds")
        end = scene.get("end_seconds")
        if not _finite_number(start) or not _finite_number(end) or end <= start:
            raise ValueError(f"scene {scene.get('id')!r} must have finite ordered timing")
        scene_ids.append(scene["id"])
        scene_by_id[scene["id"]] = scene
    if len(scene_ids) != len(set(scene_ids)):
        raise ValueError("scene ids must be unique")

    owned_sources = {
        item.get("path"): item
        for item in source_media_review.get("files", [])
        if isinstance(item, Mapping)
        and item.get("reviewed") is True
        and _nonempty(item.get("path"))
    }
    reference_source = video_analysis_brief.get("source")
    reference_duration = (
        reference_source.get("duration_seconds")
        if isinstance(reference_source, Mapping) else None
    )
    if not _finite_number(reference_duration) or reference_duration <= 0:
        raise ValueError("reference video requires finite duration")
    structure = video_analysis_brief.get("structure_analysis")
    reference_scenes: dict[str, Mapping[str, Any]] = {}
    if isinstance(structure, Mapping):
        for index, item in enumerate(structure.get("scenes", [])):
            if not isinstance(item, Mapping):
                continue
            scene_index = item.get("scene_index") if isinstance(item.get("scene_index"), int) else index
            reference_scenes[f"reference-{scene_index + 1}"] = item

    mapping_ids: list[str] = []
    matrix_rows = {
        item.get("matrix_row_id"): item
        for item in (reference_source_matrix or {}).get("rows", [])
        if isinstance(item, Mapping) and _nonempty(item.get("matrix_row_id"))
    }
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            raise ValueError("every source mapping must be an object")
        scene_id = mapping.get("scene_id")
        if not _nonempty(scene_id):
            raise ValueError("every source mapping must have a scene_id")
        mapping_ids.append(scene_id)
        source_path = mapping.get("source_path")
        if source_path not in owned_sources:
            raise ValueError(
                f"mapping for {scene_id!r} must use a reviewed owned source path"
            )
        for field in _EVIDENCE_FIELDS:
            if not _nonempty(mapping.get(field)):
                raise ValueError(f"mapping for {scene_id!r} requires non-empty {field}")
        if reference_source_matrix is not None:
            matrix_row_id = mapping.get("matrix_row_id")
            matrix_row = matrix_rows.get(matrix_row_id)
            if matrix_row is None or matrix_row.get("resolution") == "pending":
                raise ValueError(
                    f"mapping for {scene_id!r} requires a resolved research matrix row"
                )
            if mapping.get("matrix_resolution_id") != matrix_row.get("resolution"):
                raise ValueError(
                    f"mapping for {scene_id!r} must use the research matrix resolution"
                )
            source = owned_sources[source_path]
            if source.get("media_id") and source.get("media_id") != matrix_row.get("source_media_id"):
                raise ValueError(
                    f"mapping for {scene_id!r} must use the approved research matrix source"
                )
            matrix_source_interval = matrix_row.get("source_time_range")
            if isinstance(matrix_source_interval, Mapping):
                candidate_source_interval = mapping.get("source_interval")
                if candidate_source_interval != matrix_source_interval:
                    raise ValueError(
                        f"mapping for {scene_id!r} must use the approved research matrix source interval"
                    )
            if not _nonempty(mapping.get("research_direction_ref")):
                raise ValueError(
                    f"mapping for {scene_id!r} requires research_direction_ref"
                )
            if research_synthesis is not None:
                direction_ids = {
                    item.get("direction_id")
                    for item in research_synthesis.get("differentiation_directions", [])
                    if isinstance(item, Mapping)
                }
                if mapping.get("research_direction_ref") not in direction_ids:
                    raise ValueError(
                        f"mapping for {scene_id!r} references an unknown research direction"
                    )
        reference_evidence = mapping.get("reference_evidence")
        if not isinstance(reference_evidence, Mapping):
            raise ValueError(f"mapping for {scene_id!r} requires reference_evidence")
        mode = reference_evidence.get("mode")
        if mode not in {"direct_segment", "structural_only", "none"}:
            raise ValueError(f"mapping for {scene_id!r} has invalid reference mode")
        if mode in {"direct_segment", "structural_only"}:
            for field in ("mechanism", "rationale"):
                if not _nonempty(reference_evidence.get(field)):
                    raise ValueError(
                        f"reference_evidence for {scene_id!r} requires non-empty {field}"
                    )
        if mode == "direct_segment":
            reference_scene_id = reference_evidence.get("reference_scene_id")
            if not _nonempty(reference_scene_id):
                raise ValueError(
                    f"direct reference for {scene_id!r} requires reference_scene_id"
                )
            reference_scene = reference_scenes.get(reference_scene_id)
            if reference_scene is None:
                raise ValueError(
                    f"reference_scene_id for {scene_id!r} was not analyzed"
                )
            reference_start, reference_end = _validate_interval(
                reference_evidence, "reference_interval"
            )
            scene_start = reference_scene.get("start_time")
            scene_end = reference_scene.get("end_time")
            if (
                not _finite_number(scene_start)
                or not _finite_number(scene_end)
                or reference_start < scene_start
                or reference_end > scene_end
                or reference_end > reference_duration
            ):
                raise ValueError(
                    f"reference_interval for {scene_id!r} must stay inside reference scene"
                )
        elif "reference_interval" in reference_evidence:
            raise ValueError(
                f"{mode} reference evidence must not include reference_interval"
            )
        elif "reference_scene_id" in reference_evidence:
            raise ValueError(
                f"{mode} reference evidence must not include reference_scene_id"
            )
        source_start, source_end = _validate_interval(mapping, "source_interval")
        timeline_start, timeline_end = _validate_interval(
            mapping, "timeline_interval"
        )

        source = owned_sources[source_path]
        if source.get("media_type") in {"video", "audio"}:
            probe = source.get("technical_probe")
            duration = probe.get("duration_seconds") if isinstance(probe, Mapping) else None
            if not _finite_number(duration) or duration <= 0:
                raise ValueError(
                    f"reviewed owned source {source_path!r} requires finite duration"
                )
            if source_end > duration:
                raise ValueError(
                    f"source_interval for {scene_id!r} exceeds owned source duration"
                )

        scene = scene_by_id.get(scene_id)
        if scene is not None and (
            not math.isclose(timeline_start, float(scene["start_seconds"]), abs_tol=1e-6)
            or not math.isclose(timeline_end, float(scene["end_seconds"]), abs_tol=1e-6)
        ):
            raise ValueError(
                f"timeline_interval for {scene_id!r} must match canonical scene timing"
            )

    if len(mapping_ids) != len(set(mapping_ids)) or set(mapping_ids) != set(scene_ids):
        raise ValueError("scene_plan requires exactly one mapping per scene")

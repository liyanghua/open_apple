"""Pipeline-specific semantic validation for cinematic-fast artifacts."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping


_EVIDENCE_FIELDS = (
    "reference_basis",
    "source_fit",
    "mapping_reason",
    "originality_note",
)

_SOURCE_LED_MODES = {"source_led", "source_led_template"}
_FACT_REF = re.compile(r"^product_facts\.claims\[([0-9]+)\]$")


def _matches_matrix_source(
    source: Mapping[str, Any], matrix_row: Mapping[str, Any]
) -> bool:
    """Bridge legacy Research labels to content-addressed source media IDs.

    Early Research artifacts used sequence labels such as ``source-04`` while
    source-media review now persists content-addressed IDs.  Both records
    retain representative evidence frames, which provides a grounded identity
    bridge without accepting an arbitrary source substitution.
    """
    if matrix_row.get("source_media_id") is None:
        # A rewrite row records a deliberately missing source (for example an
        # original CTA). It may use any reviewed owned footage, but never a
        # reference asset; that invariant is enforced by the caller's source
        # path check.
        return matrix_row.get("resolution") == "rewrite"
    if source.get("media_id") == matrix_row.get("source_media_id"):
        return True
    source_frames = {
        value for value in source.get("representative_frames", [])
        if isinstance(value, str) and value
    }
    matrix_frames = {
        value for value in matrix_row.get("evidence_frames", [])
        if isinstance(value, str) and value
    }
    return bool(source_frames & matrix_frames)


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


def _string_set(value: Any, field: str, *, owner: str) -> set[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{owner} requires non-empty {field}")
    result: set[str] = set()
    for item in value:
        if not _nonempty(item):
            raise ValueError(f"{owner} {field} must contain non-empty strings")
        result.add(item.strip())
    if len(result) != len(value):
        raise ValueError(f"{owner} {field} must not contain duplicates")
    return result


def _accepted_matrix_rows(
    matrix: Mapping[str, Any], *, input_mode: str
) -> dict[str, Mapping[str, Any]]:
    if matrix.get("matrix_mode") != input_mode:
        raise ValueError(
            f"evidence matrix_mode must match input_mode {input_mode!r}"
        )
    result: dict[str, Mapping[str, Any]] = {}
    for row in matrix.get("rows", []):
        if not isinstance(row, Mapping) or not _nonempty(row.get("matrix_row_id")):
            continue
        row_id = row["matrix_row_id"]
        if row_id in result:
            raise ValueError(f"evidence matrix row ids must be unique: {row_id}")
        result[row_id] = row
    return result


def _rows_for_owner(
    owner: Mapping[str, Any], rows_by_id: Mapping[str, Mapping[str, Any]], *, label: str
) -> tuple[list[Mapping[str, Any]], set[str], set[str]]:
    row_ids = _string_set(owner.get("evidence_row_ids"), "evidence_row_ids", owner=label)
    rows: list[Mapping[str, Any]] = []
    for row_id in row_ids:
        row = rows_by_id.get(row_id)
        if row is None:
            raise ValueError(f"{label} references unknown evidence row {row_id!r}")
        if row.get("resolution") != "accept":
            raise ValueError(f"{label} evidence row {row_id!r} must have resolution 'accept'")
        rows.append(row)
    claims = {
        item
        for row in rows
        for item in _string_set(row.get("claim_ids"), "claim_ids", owner=f"evidence row {row.get('matrix_row_id')!r}")
    }
    actions = {
        item
        for row in rows
        for item in _string_set(row.get("action_keys"), "action_keys", owner=f"evidence row {row.get('matrix_row_id')!r}")
    }
    return rows, claims, actions


def _validate_owner_evidence_sets(
    owner: Mapping[str, Any], rows_by_id: Mapping[str, Mapping[str, Any]], *, label: str
) -> list[Mapping[str, Any]]:
    rows, row_claims, row_actions = _rows_for_owner(owner, rows_by_id, label=label)
    claims = _string_set(owner.get("claim_ids"), "claim_ids", owner=label)
    actions = _string_set(owner.get("action_keys"), "action_keys", owner=label)
    if claims != row_claims:
        raise ValueError(f"{label} claim_ids must equal its evidence rows")
    if actions != row_actions:
        raise ValueError(f"{label} action_keys must equal its evidence rows")
    routed_rows = [row for row in rows if _nonempty(row.get("visual_route"))]
    if routed_rows:
        routes = {str(row["visual_route"]) for row in routed_rows}
        if len(routes) != 1 or owner.get("visual_route") not in routes:
            raise ValueError(f"{label} visual_route must equal its evidence row")
        if owner.get("claim_visual_requirements") != routed_rows[0].get(
            "claim_visual_requirements"
        ):
            raise ValueError(
                f"{label} claim_visual_requirements must equal its evidence row"
            )
        expected_reference = routed_rows[0].get("generation_reference")
        if owner.get("generation_reference") != expected_reference:
            raise ValueError(
                f"{label} generation_reference must equal its evidence row"
            )
    return rows


def _validate_owner_provenance_sets(
    owner: Mapping[str, Any], rows: list[Mapping[str, Any]], *, label: str
) -> None:
    """Keep ProductBible/page provenance attached to every downstream owner."""
    for field in (
        "product_fact_refs", "product_page_refs", "page_asset_ids", "page_evidence_ids",
    ):
        expected = {
            str(value)
            for row in rows
            for value in (row.get(field) or [])
            if str(value).strip()
        }
        actual = {
            str(value) for value in (owner.get(field) or []) if str(value).strip()
        }
        if field == "product_fact_refs" and not actual:
            raise ValueError(f"{label} requires product_fact_refs")
        if actual != expected:
            raise ValueError(f"{label} {field} must equal its evidence rows")


def _validate_fact_refs(
    rows: list[Mapping[str, Any]], product_facts: Mapping[str, Any]
) -> None:
    claims = product_facts.get("claims")
    if not isinstance(claims, list):
        raise ValueError("source-led evidence validation requires product_facts.claims")
    for row in rows:
        refs = _string_set(
            row.get("product_fact_refs"), "product_fact_refs",
            owner=f"evidence row {row.get('matrix_row_id')!r}",
        )
        for ref in refs:
            match = _FACT_REF.fullmatch(ref)
            if match is None or int(match.group(1)) >= len(claims):
                raise ValueError(f"invalid product fact reference: {ref!r}")
            claim = claims[int(match.group(1))]
            if not isinstance(claim, Mapping) or claim.get("status") == "forbidden":
                raise ValueError(f"evidence row references forbidden product fact: {ref}")


def _validate_section_wording(
    section: Mapping[str, Any], rows: list[Mapping[str, Any]], *, label: str
) -> None:
    allowed = {
        phrase
        for row in rows
        for phrase in row.get("allowed_wording", [])
        if _nonempty(phrase)
    }
    prohibited = {
        phrase
        for row in rows
        for phrase in row.get("prohibited_wording", [])
        if _nonempty(phrase)
    }
    if not allowed:
        raise ValueError(f"{label} evidence rows require allowed_wording")
    for field in ("narration", "screen_copy"):
        text = section.get(field)
        if not _nonempty(text):
            continue
        blocked = sorted(phrase for phrase in prohibited if phrase in text)
        if blocked:
            raise ValueError(
                f"{label} {field} contains prohibited_wording {blocked!r}"
            )
        if not any(phrase in text for phrase in allowed):
            raise ValueError(f"{label} {field} is outside allowed_wording")


def validate_script_evidence_closure(
    script: Mapping[str, Any],
    reference_source_matrix: Mapping[str, Any],
    product_facts: Mapping[str, Any],
    *,
    input_mode: str,
) -> None:
    """Validate source-led Script claims against accepted Research evidence.

    Reference-driven and legacy projects keep their existing contract.  New
    source-led scripts fail closed: every section explicitly owns the exact
    claim/action union of its accepted matrix rows, and both narration and
    screen copy stay inside those rows' wording boundary and ProductBible.
    """
    if input_mode not in _SOURCE_LED_MODES:
        return
    rows_by_id = _accepted_matrix_rows(reference_source_matrix, input_mode=input_mode)
    sections = script.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("script must contain sections")
    section_ids: set[str] = set()
    scene_ids: set[str] = set()
    from lib.product_facts import check_text_facts

    for section in sections:
        if not isinstance(section, Mapping) or not _nonempty(section.get("id")):
            raise ValueError("every script section must have a non-empty id")
        label = f"script section {section.get('id')!r}"
        if section["id"] in section_ids:
            raise ValueError("script section ids must be unique")
        section_ids.add(section["id"])
        if not _nonempty(section.get("scene_id")):
            raise ValueError(f"{label} requires scene_id")
        if section["scene_id"] in scene_ids:
            raise ValueError("source-led script scene_ids must be unique")
        scene_ids.add(section["scene_id"])
        if len(section.get("evidence_row_ids") or []) != 1:
            raise ValueError(f"{label} requires exactly one evidence_row_ids entry in source-led v1")
        rows = _validate_owner_evidence_sets(section, rows_by_id, label=label)
        _validate_owner_provenance_sets(section, rows, label=label)
        _validate_fact_refs(rows, product_facts)
        _validate_section_wording(section, rows, label=label)
        for field in ("narration", "screen_copy"):
            text = str(section.get(field) or "")
            conflicts = check_text_facts(text, product_facts)
            if conflicts:
                raise ValueError(f"{label} {field} violates product facts: {conflicts}")
            for fact in product_facts.get("claims", []):
                if (
                    isinstance(fact, Mapping)
                    and fact.get("status") == "forbidden"
                    and _nonempty(fact.get("claim"))
                    and fact["claim"] in text
                ):
                    raise ValueError(
                        f"{label} {field} contains forbidden product fact {fact['claim']!r}"
                    )


def validate_scene_evidence_closure(
    scene_plan: Mapping[str, Any],
    script: Mapping[str, Any],
    reference_source_matrix: Mapping[str, Any],
    *,
    input_mode: str,
) -> None:
    """Require Scene and source mapping evidence to equal the Script section."""
    if input_mode not in _SOURCE_LED_MODES:
        return
    rows_by_id = _accepted_matrix_rows(reference_source_matrix, input_mode=input_mode)
    sections = script.get("sections")
    if not isinstance(sections, list):
        raise ValueError("script must contain sections")
    section_by_id = {
        section.get("id"): section
        for section in sections
        if isinstance(section, Mapping) and _nonempty(section.get("id"))
    }
    scenes = scene_plan.get("scenes")
    metadata = scene_plan.get("metadata")
    mappings = metadata.get("source_mapping") if isinstance(metadata, Mapping) else None
    if not isinstance(scenes, list) or not isinstance(mappings, list):
        raise ValueError("scene_plan requires scenes and metadata.source_mapping")
    mapping_by_scene = {
        mapping.get("scene_id"): mapping
        for mapping in mappings
        if isinstance(mapping, Mapping) and _nonempty(mapping.get("scene_id"))
    }
    seen_sections: set[str] = set()
    for scene in scenes:
        if not isinstance(scene, Mapping) or not _nonempty(scene.get("id")):
            raise ValueError("every scene must have a non-empty id")
        scene_id = scene["id"]
        label = f"scene {scene_id!r}"
        section_id = scene.get("script_section_id")
        section = section_by_id.get(section_id)
        if section is None:
            raise ValueError(f"{label} script_section_id must resolve to a script section")
        if section.get("scene_id") != scene_id:
            raise ValueError(f"{label} and script_section_id must be mutually bound")
        if section_id in seen_sections:
            raise ValueError("source-led scene plan must map each script section exactly once")
        seen_sections.add(section_id)
        if len(section.get("evidence_row_ids") or []) != 1:
            raise ValueError(
                f"script section {section_id!r} requires exactly one evidence_row_ids entry in source-led v1"
            )
        section_rows = _validate_owner_evidence_sets(
            section, rows_by_id, label=f"script section {section_id!r}"
        )
        _validate_owner_provenance_sets(
            section, section_rows, label=f"script section {section_id!r}"
        )
        for field in (
            "claim_ids", "action_keys", "evidence_row_ids", "product_fact_refs",
            "product_page_refs", "page_asset_ids", "page_evidence_ids",
        ):
            if set(scene.get(field) or []) != set(section.get(field) or []):
                raise ValueError(f"{label} {field} must equal script section")
        scene_rows = _validate_owner_evidence_sets(scene, rows_by_id, label=label)
        _validate_owner_provenance_sets(scene, scene_rows, label=label)
        mapping = mapping_by_scene.get(scene_id)
        if mapping is None:
            raise ValueError(f"{label} requires exactly one source mapping")
        if mapping.get("script_section_id") != section_id:
            raise ValueError(f"mapping for {scene_id!r} script_section_id must equal scene")
        for field in (
            "claim_ids", "action_keys", "evidence_row_ids", "product_fact_refs",
            "product_page_refs", "page_asset_ids", "page_evidence_ids",
        ):
            if set(mapping.get(field) or []) != set(section.get(field) or []):
                raise ValueError(f"mapping for {scene_id!r} {field} must equal script section")
        mapping_rows = _validate_owner_evidence_sets(
            mapping, rows_by_id, label=f"mapping for {scene_id!r}"
        )
        _validate_owner_provenance_sets(
            mapping, mapping_rows, label=f"mapping for {scene_id!r}"
        )
        primary_row_id = mapping.get("matrix_row_id")
        if scene.get("evidence_row_ids") != [primary_row_id]:
            raise ValueError(
                f"scene {scene_id!r} matrix_row_id requires evidence_row_ids == [matrix_row_id]"
            )
        if mapping.get("evidence_row_ids") != [primary_row_id]:
            raise ValueError(
                f"mapping for {scene_id!r} matrix_row_id requires evidence_row_ids == [matrix_row_id]"
            )
        primary_row = rows_by_id.get(primary_row_id)
        if primary_row is None or primary_row.get("resolution") != "accept":
            raise ValueError(f"mapping for {scene_id!r} requires an accepted primary evidence row")
        visual_route = primary_row.get("visual_route") or "owned_source"
        if visual_route == "generated_from_product_image":
            for owner_label, owner in ((label, scene), (f"mapping for {scene_id!r}", mapping)):
                fabricated = [
                    field
                    for field in ("source_path", "source_interval", "source_hash")
                    if field in owner
                ]
                if fabricated:
                    raise ValueError(
                        f"{owner_label} generated route must not contain owned-source fields: "
                        f"{fabricated!r}"
                    )
            if mapping.get("generation_spec") != primary_row.get("generation_spec"):
                raise ValueError(
                    f"mapping for {scene_id!r} generation_spec must equal primary evidence row"
                )
        elif visual_route == "owned_source":
            if mapping.get("source_hash") != primary_row.get("source_hash"):
                raise ValueError(
                    f"mapping for {scene_id!r} source_hash must equal primary evidence row"
                )
            source_start, source_end = _validate_interval(mapping, "source_interval")
            row_start, row_end = _validate_interval(
                {"source_interval": primary_row.get("source_time_range")}, "source_interval"
            )
            if source_start < row_start or source_end > row_end:
                raise ValueError(
                    f"mapping for {scene_id!r} must stay within approved evidence interval"
                )
        else:
            raise ValueError(
                f"mapping for {scene_id!r} has unsupported visual_route {visual_route!r}"
            )
    if seen_sections != set(section_by_id):
        raise ValueError("source-led scene plan must map every script section exactly once")


def validate_scene_mapping(
    scene_plan: Mapping[str, Any],
    source_media_review: Mapping[str, Any],
    video_analysis_brief: Mapping[str, Any],
    reference_source_matrix: Mapping[str, Any] | None = None,
    research_synthesis: Mapping[str, Any] | None = None,
) -> None:
    """Reject scene plans whose source mapping is not grounded and traceable."""
    if (
        reference_source_matrix is not None
        and reference_source_matrix.get("matrix_mode", "reference") != "reference"
    ):
        raise ValueError("reference-driven scene validation requires matrix_mode 'reference'")
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
            if not _matches_matrix_source(source, matrix_row):
                raise ValueError(
                    f"mapping for {scene_id!r} must use the approved research matrix source"
                )
            matrix_source_interval = matrix_row.get("source_time_range")
            if isinstance(matrix_source_interval, Mapping):
                candidate_source_interval = mapping.get("source_interval")
                matrix_start, matrix_end = _validate_interval(
                    {"source_interval": matrix_source_interval}, "source_interval"
                )
                source_start, source_end = _validate_interval(
                    mapping, "source_interval"
                )
                if source_start < matrix_start or source_end > matrix_end:
                    raise ValueError(
                        f"mapping for {scene_id!r} must stay within the approved research matrix source interval"
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

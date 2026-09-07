"""Build canonical source-led Research artifacts from owned-media observations."""

from __future__ import annotations

import re
import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from lib.artifact_hashing import attach_hashes, semantic_sha256


_SOURCE_MODES = {"source_led", "source_led_template"}
_FACT_REF = re.compile(r"^product_facts\.claims\[([0-9]+)\]$")
_STRENGTH_ORDER = {"weak": 0, "moderate": 1, "strong": 2}
_EVIDENCE_CLASSES = {
    "identity", "static_feature", "dynamic_action", "dynamic_result",
    "measurement", "metaphor_prop",
}


def _strings(value: Any, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be a list of strings")
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            raise ValueError(f"{field} must not contain empty values")
        if text not in result:
            result.append(text)
    if required and not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _interval(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError("interval must be an object")
    start, end = value.get("start_seconds"), value.get("end_seconds_exclusive")
    if (isinstance(start, bool) or isinstance(end, bool) or
            not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or
            not math.isfinite(start) or not math.isfinite(end) or
            start < 0 or end <= start):
        raise ValueError("interval must be a non-empty half-open interval")
    return {"start_seconds": float(start), "end_seconds_exclusive": float(end)}


def _check_fact(product_facts: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    match = _FACT_REF.fullmatch(reference)
    claims = product_facts.get("claims")
    if match is None or not isinstance(claims, list):
        raise ValueError(f"invalid product fact reference: {reference!r}")
    index = int(match.group(1))
    if index >= len(claims) or not isinstance(claims[index], Mapping):
        raise ValueError(f"product fact reference is out of range: {reference!r}")
    if claims[index].get("status") == "forbidden":
        raise ValueError(f"claim binding references forbidden product fact: {reference}")
    return claims[index]


def _normalize(observation: Mapping[str, Any], product_facts: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    media_id = str(observation.get("media_id") or "").strip()
    source_path = str(observation.get("source_path") or "").strip()
    source_hash = str(observation.get("source_hash") or "").strip()
    if not media_id or not source_path:
        raise ValueError("observation requires media_id and source_path")
    if not re.fullmatch(r"[a-f0-9]{64}", source_hash):
        raise ValueError("source_hash must be a lowercase sha256")
    evidence_class = str(observation.get("evidence_class") or "static_feature").strip()
    if evidence_class not in _EVIDENCE_CLASSES:
        raise ValueError("unsupported evidence class")
    measurement_type = str(observation.get("measurement_type") or "").strip()
    if evidence_class == "measurement" and not measurement_type:
        raise ValueError("measurement evidence requires measurement_type")
    if evidence_class != "measurement" and measurement_type:
        raise ValueError("measurement_type is only valid for measurement evidence")
    raw_bindings = observation.get("claim_bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise ValueError("observation requires claim_bindings")
    bindings: list[dict[str, Any]] = []
    for raw in raw_bindings:
        if not isinstance(raw, Mapping):
            raise ValueError("claim binding must be an object")
        claim_id = str(raw.get("claim_id") or "").strip()
        fact_ref = str(raw.get("product_fact_ref") or "").strip()
        if not claim_id:
            raise ValueError("claim binding requires claim_id")
        product_fact = _check_fact(product_facts, fact_ref)
        allowed_wording = _strings(
            raw.get("allowed_wording"), "allowed_wording", required=True
        )
        fact_allowed_wording = _strings(
            product_fact.get("allowed_wording", []), "product_fact.allowed_wording"
        )
        if fact_allowed_wording and not set(allowed_wording).issubset(fact_allowed_wording):
            raise ValueError("claim binding allowed wording must be allowed by the product fact")
        prohibited_wording = list(dict.fromkeys([
            *_strings(
                product_fact.get("prohibited_wording", []),
                "product_fact.prohibited_wording",
            ),
            *_strings(raw.get("prohibited_wording", []), "prohibited_wording"),
        ]))
        strength = str(raw.get("evidence_strength") or "")
        if strength not in _STRENGTH_ORDER:
            raise ValueError("evidence_strength must be strong, moderate, or weak")
        required_class = str(raw.get("required_evidence_class") or evidence_class).strip()
        if required_class not in _EVIDENCE_CLASSES:
            raise ValueError("required_evidence_class is invalid")
        required_measurement_type = str(raw.get("required_measurement_type") or "").strip()
        if required_class == "measurement" and not required_measurement_type:
            raise ValueError("measurement claim requires required_measurement_type")
        if required_class != "measurement" and required_measurement_type:
            raise ValueError("required_measurement_type is only valid for measurement claims")
        requires_result = raw.get("requires_visible_result") is True
        if evidence_class == "metaphor_prop":
            raise ValueError("metaphor prop cannot support a product fact claim")
        if required_class != evidence_class:
            raise ValueError(
                f"evidence class {evidence_class!r} does not satisfy required evidence class {required_class!r}"
            )
        if required_class == "measurement" and required_measurement_type != measurement_type:
            raise ValueError(
                f"measurement type {measurement_type!r} does not satisfy required measurement type "
                f"{required_measurement_type!r}"
            )
        bindings.append({
            "claim_id": claim_id, "product_fact_ref": fact_ref,
            "product_page_refs": _strings(
                product_fact.get("product_page_refs", []), "product_page_refs"
            ),
            "page_asset_ids": _strings(
                product_fact.get("page_asset_ids", []), "page_asset_ids"
            ),
            "page_evidence_ids": _strings(
                product_fact.get("page_evidence_ids", []), "page_evidence_ids"
            ),
            "allowed_wording": allowed_wording,
            "prohibited_wording": prohibited_wording,
            "forbidden_substitutions": _strings(
                raw.get("forbidden_substitutions", []), "forbidden_substitutions"
            ),
            "evidence_strength": strength,
            "required_evidence_class": required_class,
            "requires_visible_result": requires_result,
        })
        if required_measurement_type:
            bindings[-1]["required_measurement_type"] = required_measurement_type
    crop, quality = observation.get("crop_safety"), observation.get("quality")
    if not isinstance(crop, Mapping) or not isinstance(quality, Mapping):
        raise ValueError("observation requires crop_safety and quality")
    if not isinstance(crop.get("subject_complete_in_3_4"), bool):
        raise ValueError("crop_safety.subject_complete_in_3_4 must be a bool")
    if not isinstance(quality.get("usable"), bool):
        raise ValueError("quality.usable must be a bool")
    confidence = quality.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("quality.confidence must be between 0 and 1")
    observation_interval = _interval(observation.get("interval"))
    observed_results = _strings(observation.get("observed_results", []), "observed_results")
    temporal_evidence = observation.get("temporal_evidence")
    if any(item["requires_visible_result"] for item in bindings):
        if evidence_class != "dynamic_result" or not observed_results:
            raise ValueError("claim requires a dynamic_result evidence class with a visible result")
        if not isinstance(temporal_evidence, Mapping) or set(temporal_evidence) != {"before", "action", "result"}:
            raise ValueError("temporal evidence requires before, action, and result phases")
        temporal_evidence = {
            phase: _interval(temporal_evidence[phase])
            for phase in ("before", "action", "result")
        }
        for phase, phase_interval in temporal_evidence.items():
            if (
                phase_interval["start_seconds"] < observation_interval["start_seconds"]
                or phase_interval["end_seconds_exclusive"]
                > observation_interval["end_seconds_exclusive"]
            ):
                raise ValueError(
                    f"temporal evidence phase {phase!r} must stay inside the observation interval"
                )
        if not (
            temporal_evidence["before"]["start_seconds"]
            < temporal_evidence["action"]["end_seconds_exclusive"]
            <= temporal_evidence["result"]["end_seconds_exclusive"]
        ):
            raise ValueError("temporal evidence phases are not ordered")
    elif temporal_evidence is not None:
        if not isinstance(temporal_evidence, Mapping):
            raise ValueError("temporal_evidence must be an object")
        temporal_evidence = {
            phase: _interval(value)
            for phase, value in temporal_evidence.items()
        }
    entry = {
        "media_id": media_id, "source_path": source_path, "source_hash": source_hash,
        "interval": observation_interval,
        "observed_subject": _strings(observation.get("observed_subject"), "observed_subject", required=True),
        "observed_actions": _strings(observation.get("observed_actions"), "observed_actions", required=True),
        "observed_results": observed_results,
        "evidence_class": evidence_class,
        "allowed_claim_ids": _strings([item["claim_id"] for item in bindings], "allowed_claim_ids", required=True),
        "crop_safety": {"subject_complete_in_3_4": crop["subject_complete_in_3_4"], "safe_caption_regions": _strings(crop.get("safe_caption_regions", []), "safe_caption_regions")},
        "quality": {"usable": quality["usable"], "confidence": float(confidence), "risks": _strings(quality.get("risks", []), "quality.risks")},
        "representative_frames": _strings(observation.get("representative_frames"), "representative_frames", required=True),
    }
    if temporal_evidence is not None:
        entry["temporal_evidence"] = temporal_evidence
    if measurement_type:
        entry["measurement_type"] = measurement_type
    return entry, bindings


def build_source_research_artifacts(*, project_id: str, input_mode: str,
                                    observations: Sequence[Mapping[str, Any]],
                                    product_facts: Mapping[str, Any],
                                    visual_requirement_specs: Sequence[Mapping[str, Any]] | None = None,
                                    clean_references: Sequence[Mapping[str, Any]] = (),
                                    created_at: str | None = None,
                                    producer: str = "lib.source_semantics") -> dict[str, dict[str, Any]]:
    """Return a hash-bound semantic index and canonical evidence matrix."""
    if input_mode not in _SOURCE_MODES:
        raise ValueError(f"source semantics do not support input_mode {input_mode!r}")
    if not str(project_id).strip() or not observations:
        raise ValueError("project_id and at least one observation are required")
    timestamp = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entries, rows, source_hashes = [], [], {}
    for ordinal, observation in enumerate(observations, start=1):
        entry, bindings = _normalize(observation, product_facts)
        entries.append(entry)
        source_hashes[f"source_{ordinal}"] = entry["source_hash"]
        for claim_ordinal, binding in enumerate(bindings, start=1):
            product_fact = _check_fact(product_facts, binding["product_fact_ref"])
            visualizability = (
                "observable"
                if entry["evidence_class"] in {"dynamic_action", "dynamic_result", "measurement"}
                else "contextual"
            )
            requirement = {
                "product_fact_ref": binding["product_fact_ref"],
                "claim_id": binding["claim_id"],
                "visualizability": visualizability,
                "required_subjects": list(entry["observed_subject"]),
                "required_actions": list(entry["observed_actions"]),
                "required_results": list(entry["observed_results"]),
                "forbidden_substitutions": list(binding["forbidden_substitutions"]),
                "allowed_wording": list(binding["allowed_wording"]),
                "prohibited_wording": list(binding["prohibited_wording"]),
                "candidate_page_asset_ids": list(binding["page_asset_ids"]),
                "sku_scope": list(
                    product_fact.get("sku_scope")
                    or [str(product_facts.get("sku") or "unscoped")]
                ),
                "risk_level": str(product_fact.get("risk_level") or "medium"),
                "evidence_policy": {
                    "fact_basis": (
                        "merchant_page_claim"
                        if product_fact.get("evidence_status") == "page_claim"
                        else "qualified_or_observed_fact"
                    ),
                    "generated_media_role": "visual_expression_only",
                    "generated_media_can_prove_claim": False,
                },
            }
            selected_source = {
                "media_id": entry["media_id"],
                "source_path": entry["source_path"],
                "source_hash": entry["source_hash"],
                "source_time_range": dict(entry["interval"]),
                "evidence_frames": list(entry["representative_frames"]),
                "confidence": entry["quality"]["confidence"],
            }
            rows.append({
                "matrix_row_id": f"evidence-{ordinal:03d}-claim-{claim_ordinal:03d}",
                "reference_scene_id": None, "reference_time_range": None,
                "reference_intent": "source-led evidence: " + ", ".join(entry["observed_actions"]),
                "source_media_id": entry["media_id"], "source_hash": entry["source_hash"],
                "source_time_range": dict(entry["interval"]),
                "match_reason": "；".join(entry["observed_results"]) or "observed owned-source action",
                "confidence": entry["quality"]["confidence"], "evidence_frames": list(entry["representative_frames"]),
                "unmatched_gap": None, "resolution": "accept",
                "claim_ids": [binding["claim_id"]],
                "action_keys": list(entry["observed_actions"]),
                "product_fact_refs": [binding["product_fact_ref"]],
                "product_page_refs": list(binding["product_page_refs"]),
                "page_asset_ids": list(binding["page_asset_ids"]),
                "page_evidence_ids": list(binding["page_evidence_ids"]),
                "allowed_wording": list(binding["allowed_wording"]),
                "prohibited_wording": list(binding["prohibited_wording"]),
                "evidence_strength": binding["evidence_strength"],
                "evidence_class": entry["evidence_class"],
                "required_evidence_class": binding["required_evidence_class"],
                "requires_visible_result": binding["requires_visible_result"],
                "temporal_evidence": entry.get("temporal_evidence"),
                "visual_route": "owned_source",
                "claim_visual_requirements": requirement,
                "owned_candidates": [{
                    **selected_source,
                    "observed_subjects": list(entry["observed_subject"]),
                    "observed_actions": list(entry["observed_actions"]),
                    "observed_results": list(entry["observed_results"]),
                    "subject_complete_in_3_4": bool(
                        entry["crop_safety"]["subject_complete_in_3_4"]
                    ),
                    "status": "accepted",
                    "rejection_reasons": [],
                }],
                "selected_source": selected_source,
                "generation_reference": None,
                "generation_spec": None,
                "route_reason": (
                    "owned candidate covers the bound subject, action, result, and 3:4 crop"
                ),
            })
            if entry.get("measurement_type"):
                rows[-1]["measurement_type"] = entry["measurement_type"]
            if binding.get("required_measurement_type"):
                rows[-1]["required_measurement_type"] = binding["required_measurement_type"]
    if visual_requirement_specs is not None:
        from lib.product_image_routing import (
            compile_claim_visual_requirements,
            route_claim_coverage,
        )

        requirements = compile_claim_visual_requirements(
            product_facts, visual_requirement_specs
        )
        routed_rows: list[dict[str, Any]] = []
        unmatched_gaps: list[dict[str, Any]] = []
        entries_by_media = {entry["media_id"]: entry for entry in entries}
        for ordinal, requirement in enumerate(requirements, start=1):
            if not requirement.get("required_actions"):
                raise ValueError("routed visual requirements require at least one action")
            decision = route_claim_coverage(
                requirement,
                owned_candidates=entries,
                clean_references=clean_references,
            )
            route = str(decision["visual_route"])
            selected = decision.get("selected_source") or {}
            selected_entry = entries_by_media.get(str(selected.get("media_id") or ""), {})
            fact_ref = str(requirement["product_fact_ref"])
            fact = _check_fact(product_facts, fact_ref)
            row_id = f"evidence-coverage-{ordinal:03d}"
            required_results = list(requirement.get("required_results") or [])
            row: dict[str, Any] = {
                "matrix_row_id": row_id,
                "reference_scene_id": None,
                "reference_time_range": None,
                "reference_intent": "source-led claim coverage: " + ", ".join(
                    requirement["required_actions"]
                ),
                "source_media_id": (
                    str(selected.get("media_id")) if route == "owned_source" else None
                ),
                "source_time_range": (
                    deepcopy(selected.get("source_time_range"))
                    if route == "owned_source" else None
                ),
                "match_reason": str(decision["route_reason"]),
                "confidence": (
                    float(selected.get("confidence") or 0)
                    if route == "owned_source" else 1.0
                ),
                "evidence_frames": (
                    list(selected.get("evidence_frames") or [])
                    if route == "owned_source" else []
                ),
                "unmatched_gap": str(decision["route_reason"]) if route == "omit" else None,
                "resolution": "omit" if route == "omit" else "accept",
                "claim_ids": [str(requirement["claim_id"])],
                "action_keys": list(requirement["required_actions"]),
                "product_fact_refs": [fact_ref],
                "product_page_refs": _strings(
                    fact.get("product_page_refs", []), "product_page_refs"
                ),
                "page_asset_ids": list(requirement.get("candidate_page_asset_ids") or []),
                "page_evidence_ids": _strings(
                    fact.get("page_evidence_ids", []), "page_evidence_ids"
                ),
                "allowed_wording": list(requirement["allowed_wording"]),
                "prohibited_wording": list(requirement.get("prohibited_wording") or []),
                "evidence_strength": "strong" if route == "owned_source" else "weak",
                "evidence_class": str(selected_entry.get("evidence_class") or "static_feature"),
                "required_evidence_class": (
                    str(selected_entry.get("evidence_class") or "static_feature")
                    if route == "owned_source"
                    else "static_feature"
                ),
                "requires_visible_result": (
                    requirement.get("visualizability") == "observable" and bool(required_results)
                ),
                "temporal_evidence": (
                    deepcopy(selected_entry.get("temporal_evidence"))
                    if route == "owned_source"
                    and requirement.get("visualizability") == "observable"
                    and required_results
                    else None
                ),
                **deepcopy(decision),
            }
            if route == "owned_source":
                row["source_hash"] = str(selected["source_hash"])
            if route == "omit":
                unmatched_gaps.append({
                    "matrix_row_id": row_id,
                    "reason": str(decision["route_reason"]),
                })
            routed_rows.append(row)
        rows = routed_rows
    else:
        unmatched_gaps = []
    input_hashes = {**source_hashes, "product_facts": str(product_facts.get("semantic_sha256") or semantic_sha256(product_facts))}
    if visual_requirement_specs is not None:
        input_hashes["visual_requirements"] = semantic_sha256(
            list(visual_requirement_specs)
        )
        for ordinal, reference in enumerate(clean_references, start=1):
            reference_hash = str(reference.get("sha256") or "")
            if not re.fullmatch(r"[a-f0-9]{64}", reference_hash):
                raise ValueError("clean reference requires a lowercase sha256")
            input_hashes[f"clean_reference_{ordinal}"] = reference_hash
    common = {"version": "1.0", "project_id": str(project_id), "created_at": timestamp, "producer": producer, "input_hashes": input_hashes}
    return {
        "source_semantic_index": attach_hashes({**common, "input_mode": input_mode, "entries": entries}),
        "reference_source_matrix": attach_hashes({**common, "matrix_mode": input_mode, "rows": rows, "unmatched_gaps": unmatched_gaps}),
    }


def enrich_matrix_product_provenance(
    matrix: Mapping[str, Any], product_facts: Mapping[str, Any]
) -> dict[str, Any]:
    """Backfill page provenance on an existing canonical source-led matrix.

    This is a deterministic migration for captures created before page
    evidence fields were carried through the evidence matrix.  Product fact
    references remain the only join keys; no semantic matching or guessing is
    performed here.
    """
    enriched = deepcopy(dict(matrix))
    rows = []
    for raw_row in enriched.get("rows") or []:
        row = dict(raw_row)
        facts = [_check_fact(product_facts, str(ref)) for ref in row.get("product_fact_refs") or []]
        for field in ("product_page_refs", "page_asset_ids", "page_evidence_ids"):
            row[field] = list(dict.fromkeys(
                str(value)
                for fact in facts
                for value in fact.get(field, [])
                if str(value).strip()
            ))
        rows.append(row)
    enriched["rows"] = rows
    return attach_hashes(enriched)

"""Build canonical source-led Research artifacts from owned-media observations."""

from __future__ import annotations

import re
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from lib.artifact_hashing import attach_hashes, semantic_sha256


_SOURCE_MODES = {"source_led", "source_led_template"}
_FACT_REF = re.compile(r"^product_facts\.claims\[([0-9]+)\]$")
_STRENGTH_ORDER = {"weak": 0, "moderate": 1, "strong": 2}


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


def _check_fact(product_facts: Mapping[str, Any], reference: str) -> None:
    match = _FACT_REF.fullmatch(reference)
    claims = product_facts.get("claims")
    if match is None or not isinstance(claims, list):
        raise ValueError(f"invalid product fact reference: {reference!r}")
    index = int(match.group(1))
    if index >= len(claims) or not isinstance(claims[index], Mapping):
        raise ValueError(f"product fact reference is out of range: {reference!r}")
    if claims[index].get("status") == "forbidden":
        raise ValueError(f"claim binding references forbidden product fact: {reference}")


def _normalize(observation: Mapping[str, Any], product_facts: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    media_id = str(observation.get("media_id") or "").strip()
    source_path = str(observation.get("source_path") or "").strip()
    source_hash = str(observation.get("source_hash") or "").strip()
    if not media_id or not source_path:
        raise ValueError("observation requires media_id and source_path")
    if not re.fullmatch(r"[a-f0-9]{64}", source_hash):
        raise ValueError("source_hash must be a lowercase sha256")
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
        _check_fact(product_facts, fact_ref)
        strength = str(raw.get("evidence_strength") or "")
        if strength not in _STRENGTH_ORDER:
            raise ValueError("evidence_strength must be strong, moderate, or weak")
        bindings.append({
            "claim_id": claim_id, "product_fact_ref": fact_ref,
            "allowed_wording": _strings(raw.get("allowed_wording"), "allowed_wording", required=True),
            "prohibited_wording": _strings(raw.get("prohibited_wording", []), "prohibited_wording"),
            "evidence_strength": strength,
        })
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
    entry = {
        "media_id": media_id, "source_path": source_path, "source_hash": source_hash,
        "interval": _interval(observation.get("interval")),
        "observed_subject": _strings(observation.get("observed_subject"), "observed_subject", required=True),
        "observed_actions": _strings(observation.get("observed_actions"), "observed_actions", required=True),
        "observed_results": _strings(observation.get("observed_results", []), "observed_results"),
        "allowed_claim_ids": _strings([item["claim_id"] for item in bindings], "allowed_claim_ids", required=True),
        "crop_safety": {"subject_complete_in_3_4": crop["subject_complete_in_3_4"], "safe_caption_regions": _strings(crop.get("safe_caption_regions", []), "safe_caption_regions")},
        "quality": {"usable": quality["usable"], "confidence": float(confidence), "risks": _strings(quality.get("risks", []), "quality.risks")},
        "representative_frames": _strings(observation.get("representative_frames"), "representative_frames", required=True),
    }
    return entry, bindings


def build_source_research_artifacts(*, project_id: str, input_mode: str,
                                    observations: Sequence[Mapping[str, Any]],
                                    product_facts: Mapping[str, Any],
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
                "allowed_wording": list(binding["allowed_wording"]),
                "prohibited_wording": list(binding["prohibited_wording"]),
                "evidence_strength": binding["evidence_strength"],
            })
    input_hashes = {**source_hashes, "product_facts": str(product_facts.get("semantic_sha256") or semantic_sha256(product_facts))}
    common = {"version": "1.0", "project_id": str(project_id), "created_at": timestamp, "producer": producer, "input_hashes": input_hashes}
    return {
        "source_semantic_index": attach_hashes({**common, "input_mode": input_mode, "entries": entries}),
        "reference_source_matrix": attach_hashes({**common, "matrix_mode": input_mode, "rows": rows, "unmatched_gaps": []}),
    }

"""Claim-level visual requirements and product-reference validation.

This module is intentionally deterministic.  It decides what a claim needs
and whether a derived product image is safe to route; it never calls a media
provider and never upgrades generated media into product-fact evidence.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping, Sequence


_FACT_REF = re.compile(r"^product_facts\.claims\[([0-9]+)\]$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_VISUALIZABILITY = {"observable", "contextual", "non_observable"}
_UNCONFIRMED_EVIDENCE = {"needs_human_confirmation", "restricted", "forbidden"}


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


def _fact_for_ref(product_facts: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    match = _FACT_REF.fullmatch(reference)
    claims = product_facts.get("claims")
    if match is None or not isinstance(claims, list):
        raise ValueError(f"invalid product fact reference: {reference!r}")
    index = int(match.group(1))
    if index >= len(claims) or not isinstance(claims[index], Mapping):
        raise ValueError(f"product fact reference is out of range: {reference!r}")
    return claims[index]


def compile_claim_visual_requirements(
    product_facts: Mapping[str, Any],
    requirement_specs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compile authored visual intent against canonical, SKU-scoped facts.

    Wording, page assets, SKU, and risk always come from ``product_facts``;
    the authored specs may define only how that fact should be visualized.
    """
    if not isinstance(requirement_specs, Sequence) or isinstance(requirement_specs, (str, bytes)):
        raise ValueError("requirement_specs must be a list")
    compiled: list[dict[str, Any]] = []
    for raw in requirement_specs:
        if not isinstance(raw, Mapping):
            raise ValueError("visual requirement must be an object")
        fact_ref = str(raw.get("product_fact_ref") or "").strip()
        fact = _fact_for_ref(product_facts, fact_ref)
        if fact.get("status") == "forbidden":
            raise ValueError(f"product fact is forbidden: {fact_ref}")
        if fact.get("evidence_status") in _UNCONFIRMED_EVIDENCE:
            raise ValueError(f"product fact is not confirmed: {fact_ref}")

        visualizability = str(raw.get("visualizability") or "").strip()
        if visualizability not in _VISUALIZABILITY:
            raise ValueError("visualizability must be observable, contextual, or non_observable")
        subjects = _strings(raw.get("required_subjects", []), "required_subjects")
        actions = _strings(raw.get("required_actions", []), "required_actions")
        results = _strings(raw.get("required_results", []), "required_results")
        substitutions = _strings(
            raw.get("forbidden_substitutions", []), "forbidden_substitutions"
        )
        if visualizability == "observable" and not (subjects and actions and results):
            raise ValueError("observable claims require subjects, actions, and results")

        allowed_wording = _strings(
            fact.get("allowed_wording", []), "allowed wording", required=True
        )
        sku_scope = _strings(
            fact.get("sku_scope") or ([product_facts.get("sku")] if product_facts.get("sku") else []),
            "sku_scope",
            required=True,
        )
        evidence_status = str(fact.get("evidence_status") or "")
        fact_basis = {
            "page_claim": "merchant_page_claim",
            "qualified_report": "qualified_report",
            "visually_observed": "visually_observed",
        }.get(evidence_status, "authorized_product_fact")

        compiled.append({
            "product_fact_ref": fact_ref,
            "claim_id": str(fact.get("claim_id") or "").strip(),
            "visualizability": visualizability,
            "required_subjects": subjects,
            "required_actions": actions,
            "required_results": results,
            "forbidden_substitutions": substitutions,
            "allowed_wording": allowed_wording,
            "prohibited_wording": _strings(
                fact.get("prohibited_wording", []), "prohibited_wording"
            ),
            "candidate_page_asset_ids": _strings(
                fact.get("page_asset_ids", []), "page_asset_ids"
            ),
            "sku_scope": sku_scope,
            "risk_level": str(fact.get("risk_level") or "medium"),
            "evidence_policy": {
                "fact_basis": fact_basis,
                "generated_media_role": "visual_expression_only",
                "generated_media_can_prove_claim": False,
            },
        })
    return compiled


def validate_clean_reference_asset(
    asset: Mapping[str, Any],
    *,
    parent_asset: Mapping[str, Any],
    expected_sku: str,
) -> dict[str, Any]:
    """Validate lineage and generation safety for one clean reference."""
    if asset.get("asset_role") != "derived_clean_reference":
        raise ValueError("clean reference must use derived_clean_reference role")
    if asset.get("usage_role") != "generation_reference":
        raise ValueError("clean reference must use generation_reference usage")
    if asset.get("parent_asset_id") != parent_asset.get("asset_id"):
        raise ValueError("clean reference parent asset does not match")
    if expected_sku not in _strings(asset.get("sku_scope", []), "sku_scope", required=True):
        raise ValueError("clean reference SKU does not match the selected SKU")
    if expected_sku not in _strings(parent_asset.get("sku_scope", []), "parent sku_scope", required=True):
        raise ValueError("parent asset SKU does not match the selected SKU")
    if asset.get("clean_reference_status") != "ready":
        raise ValueError("clean reference is not ready")
    if (asset.get("identity_check") or {}).get("status") != "pass":
        raise ValueError("clean reference identity check must pass")
    if asset.get("generation_eligibility") != "eligible":
        raise ValueError("clean reference is not eligible for generation")
    if asset.get("ocr_residual_text"):
        raise ValueError("clean reference contains residual OCR text")

    output_hash = str(asset.get("sha256") or "")
    parent_hash = str(parent_asset.get("sha256") or "")
    if not _SHA256.fullmatch(output_hash) or not _SHA256.fullmatch(parent_hash):
        raise ValueError("clean reference and parent require sha256 hashes")
    transforms = asset.get("transforms")
    if not isinstance(transforms, list) or not transforms:
        raise ValueError("clean reference requires at least one transform")
    previous_hash = parent_hash
    for index, transform in enumerate(transforms):
        if not isinstance(transform, Mapping):
            raise ValueError("clean reference transforms must be structured")
        if str(transform.get("input_hash") or "") != previous_hash:
            raise ValueError(f"clean reference transform {index} input hash does not match")
        transform_output = str(transform.get("output_hash") or "")
        if not _SHA256.fullmatch(transform_output):
            raise ValueError(f"clean reference transform {index} output hash is invalid")
        previous_hash = transform_output
    if previous_hash != output_hash:
        raise ValueError("clean reference transform output hash does not match asset hash")
    return deepcopy(dict(asset))

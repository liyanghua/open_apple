"""Normalize browser-captured product claims into SKU-scoped product facts.

Browser capture records what a merchant page says.  It never upgrades those
claims to independent test evidence merely because the wording appears on a
detail image.
"""

from __future__ import annotations

from typing import Any, Mapping

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact


def reconcile_product_facts(
    *,
    capture: Mapping[str, Any],
    asset_ledger: Mapping[str, Any],
    operator_confirmation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a canonical ProductBible while preserving evidence strength."""
    validate_artifact("product_page_capture", dict(capture))
    validate_artifact("product_asset_ledger", dict(asset_ledger))
    if capture.get("acquisition_status") != "complete":
        raise ValueError("product page acquisition is not complete")
    identity = capture.get("page_identity") or {}
    selected_sku = str(identity.get("selected_sku_id") or "").strip()
    confirmed_sku = str((operator_confirmation or {}).get("selected_sku_id") or selected_sku).strip()
    if not selected_sku or confirmed_sku != selected_sku:
        raise ValueError("SKU confirmation conflicts with browser-selected SKU")
    ledger_ids = {
        str(item.get("asset_id") or "")
        for item in asset_ledger.get("assets", [])
        if isinstance(item, Mapping)
    }
    missing_assets = set(capture.get("asset_refs") or []) - ledger_ids
    if missing_assets:
        raise ValueError("product page capture references missing ledger assets")

    screenshots = [
        item for item in ((capture.get("capture_evidence") or {}).get("screenshots") or [])
        if isinstance(item, Mapping) and str(item.get("evidence_id") or "").strip()
    ]
    screenshot_ids = [str(item["evidence_id"]) for item in screenshots]

    claims: list[dict[str, Any]] = []
    params: list[str] = []
    for fact_index, raw in enumerate(capture.get("fact_candidates") or []):
        if not isinstance(raw, Mapping) or raw.get("volatile") is True:
            continue
        statement = str(raw.get("statement") or "").strip()
        evidence_status = str(raw.get("evidence_status") or "page_claim")
        if not statement:
            continue
        if raw.get("claim_class") == "identity" and evidence_status in {"page_claim", "visually_observed"}:
            params.append(statement)
        status = "forbidden" if evidence_status in {"forbidden", "restricted"} else "needs_evidence"
        provenance_refs = list(raw.get("provenance_refs") or [])
        page_asset_ids: list[str] = []
        page_evidence_ids: list[str] = []
        for reference in provenance_refs:
            reference_text = str(reference)
            asset_prefix = "product_asset_ledger:"
            if reference_text.startswith(asset_prefix):
                asset_id = reference_text[len(asset_prefix):]
                if asset_id not in ledger_ids:
                    raise ValueError(f"product fact references missing ledger asset: {asset_id}")
                if asset_id not in page_asset_ids:
                    page_asset_ids.append(asset_id)
            if reference_text.startswith("capture_evidence.screenshots["):
                try:
                    screenshot_index = int(reference_text.split("[", 1)[1].split("]", 1)[0])
                except (ValueError, IndexError):
                    raise ValueError(f"invalid product page screenshot reference: {reference_text}")
                if screenshot_index >= len(screenshot_ids):
                    raise ValueError(f"product fact references missing screenshot: {reference_text}")
                page_evidence_ids.append(screenshot_ids[screenshot_index])
        # Browser observations such as ``visible_parameters`` refer to the
        # captured page state.  Preserve the first page screenshot as their
        # reproducible visual anchor instead of leaving a human-facing claim
        # with only an opaque prose provenance token.
        if not page_evidence_ids and any(
            str(reference).startswith(("visible_", "page_identity."))
            for reference in provenance_refs
        ) and screenshot_ids:
            page_evidence_ids.append(screenshot_ids[0])
        claims.append({
            "claim_id": str(raw.get("fact_id") or ""),
            "claim": statement,
            "statement": statement,
            "claim_class": str(raw.get("claim_class") or "feature"),
            "status": status,
            "evidence_status": evidence_status,
            "evidence": "商品页可见声明，未自动等同于独立检测结论",
            "sku_scope": list(raw.get("sku_scope") or [selected_sku]),
            "provenance_refs": provenance_refs,
            "product_page_refs": [f"product_page_capture.fact_candidates[{fact_index}]"],
            "page_asset_ids": page_asset_ids,
            "page_evidence_ids": list(dict.fromkeys(page_evidence_ids)),
            "required_visual_evidence": list(raw.get("required_visual_evidence") or []),
            "allowed_wording": list(raw.get("allowed_wording") or []),
            "prohibited_wording": list(raw.get("prohibited_wording") or []),
            "risk_level": str(raw.get("risk_level") or "medium"),
        })

    payload = {
        "version": "1.0",
        "product_id": f"{identity.get('platform')}:{identity.get('item_id')}:{selected_sku}",
        "product_name": str(identity.get("title") or "").strip(),
        "sku": selected_sku,
        "params": params,
        "provenance": {
            "sku": "product_page_capture.page_identity + operator_confirmation",
            "params": "product_page_capture.fact_candidates",
            "claims": "product_page_capture.fact_candidates",
        },
        "claims": claims,
        "visual_identity": {
            "must_preserve": [f"当前 SKU：{identity.get('selected_sku_text') or selected_sku}"],
            "allowed_variation": ["景别", "角度", "光线"],
            "forbidden": ["使用其他 SKU 主图代替当前 SKU"],
        },
        "filled_by": "agent_browser_capture+operator_confirmation",
    }
    return attach_hashes(payload)

from __future__ import annotations

import pytest

from tests.contracts.test_product_page_acquisition import (
    _capture,
    _complete_v11_capture,
    _ledger,
)


def test_page_claim_stays_unverified_without_qualification_asset() -> None:
    from lib.product_fact_reconciliation import reconcile_product_facts

    facts = reconcile_product_facts(
        capture=_capture(),
        asset_ledger=_ledger(),
        operator_confirmation={"selected_sku_id": "6276962282892"},
    )

    claim = facts["claims"][0]
    assert claim["statement"] == "10A级抗菌"
    assert claim["status"] == "needs_evidence"
    assert claim["evidence_status"] == "page_claim"
    assert "经独立检测达到10A级抗菌" in claim["prohibited_wording"]
    assert claim["product_page_refs"] == ["product_page_capture.fact_candidates[0]"]
    assert claim["page_evidence_ids"] == ["page-shot-001"]
    assert claim["page_asset_ids"] == []


def test_reconciliation_keeps_direct_page_asset_provenance() -> None:
    from lib.product_fact_reconciliation import reconcile_product_facts

    capture = _capture()
    capture["fact_candidates"][0]["provenance_refs"].append(
        "product_asset_ledger:page-asset-selected-sku"
    )

    facts = reconcile_product_facts(
        capture=capture,
        asset_ledger=_ledger(),
        operator_confirmation={"selected_sku_id": "6276962282892"},
    )

    assert facts["claims"][0]["page_asset_ids"] == ["page-asset-selected-sku"]


def test_reconciliation_rejects_operator_and_page_sku_conflict() -> None:
    from lib.product_fact_reconciliation import reconcile_product_facts

    with pytest.raises(ValueError, match="SKU"):
        reconcile_product_facts(
            capture=_capture(),
            asset_ledger=_ledger(),
            operator_confirmation={"selected_sku_id": "wrong-sku"},
        )


def test_dynamic_page_claim_needs_owned_result_or_qualified_report() -> None:
    from lib.product_fact_reconciliation import reconcile_product_facts

    capture = _capture()
    capture["fact_candidates"][0].update({
        "fact_id": "page-fact-absorb",
        "statement": "吸水速干",
        "claim_class": "benefit",
        "required_visual_evidence": ["dynamic_result"],
        "allowed_wording": ["商品页标注吸水速干"],
        "prohibited_wording": ["一滚就干", "水滴一沾上就被吸进去"],
    })

    facts = reconcile_product_facts(
        capture=capture,
        asset_ledger=_ledger(),
        operator_confirmation={"selected_sku_id": "6276962282892"},
    )

    assert facts["claims"][0]["status"] == "needs_evidence"
    assert facts["claims"][0]["required_visual_evidence"] == ["dynamic_result"]


def test_reconciliation_preserves_all_stable_v11_facts_and_excludes_volatile() -> None:
    from lib.product_fact_reconciliation import reconcile_product_facts

    capture = _complete_v11_capture()
    capture["fact_candidates"].append({
        "fact_id": "stable-origin",
        "statement": "原产地中国大陆",
        "claim_class": "identity",
        "evidence_status": "page_claim",
        "sku_scope": ["6276962282892"],
        "provenance_refs": ["capture_evidence.screenshots[0]"],
        "allowed_wording": ["商品页参数标注原产地中国大陆"],
        "prohibited_wording": ["宣称由视频独立证明产地"],
        "required_visual_evidence": [],
        "risk_level": "low",
    })
    capture["fact_candidates"].append({
        "fact_id": "volatile-price",
        "statement": "到手价19.18元",
        "claim_class": "identity",
        "evidence_status": "page_claim",
        "sku_scope": ["6276962282892"],
        "provenance_refs": ["capture_evidence.screenshots[0]"],
        "allowed_wording": ["到手价19.18元"],
        "prohibited_wording": [],
        "required_visual_evidence": [],
        "risk_level": "high",
        "volatile": True,
    })
    capture["capture_scope"]["fact_candidate_count"] = 3
    capture["capture_scope"]["excluded_volatile_count"] = 1

    facts = reconcile_product_facts(
        capture=capture,
        asset_ledger=_ledger(),
        operator_confirmation={"selected_sku_id": "6276962282892"},
    )

    assert [claim["claim_id"] for claim in facts["claims"]] == [
        "page-fact-001",
        "stable-origin",
    ]
    assert "原产地中国大陆" in facts["params"]
    assert all(claim["claim_id"] != "volatile-price" for claim in facts["claims"])

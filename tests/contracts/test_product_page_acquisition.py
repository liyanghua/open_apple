from __future__ import annotations

from copy import deepcopy

import jsonschema
import pytest

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact


def _capture() -> dict:
    return attach_hashes({
        "version": "1.0",
        "project_id": "maojin-yinlizi",
        "created_at": "2026-09-06T10:00:00+08:00",
        "producer": "cinematic-fast/research-director",
        "input_hashes": {},
        "acquisition_status": "complete",
        "requested_url": "https://detail.tmall.com/item.htm?id=1060430166297&skuId=6276962282892",
        "canonical_url": "https://detail.tmall.com/item.htm?id=1060430166297&skuId=6276962282892",
        "page_identity": {
            "platform": "tmall",
            "item_id": "1060430166297",
            "url_sku_id": "6276962282892",
            "selected_sku_id": "6276962282892",
            "selected_sku_text": "柔胭粉",
            "title": "花花公子银离子纯棉毛巾",
            "store": "花花公子家居旗舰店",
            "brand": "PLAYBOY/花花公子",
        },
        "fact_candidates": [{
            "fact_id": "page-fact-001",
            "statement": "10A级抗菌",
            "claim_class": "feature",
            "evidence_status": "page_claim",
            "sku_scope": ["6276962282892"],
            "provenance_refs": ["capture_evidence.screenshots[0]"],
            "allowed_wording": ["商品页标注10A级抗菌"],
            "prohibited_wording": ["经独立检测达到10A级抗菌"],
            "required_visual_evidence": ["qualification_report"],
            "risk_level": "high",
        }],
        "asset_refs": ["page-asset-selected-sku"],
        "capture_evidence": {
            "page_state": "public",
            "screenshots": [{
                "evidence_id": "page-shot-001",
                "local_path": "analysis/product_page/selected-sku.png",
                "sha256": "a" * 64,
            }],
        },
        "gaps": ["未发现可核验的检测报告正文"],
    })


def _ledger() -> dict:
    return attach_hashes({
        "version": "1.0",
        "project_id": "maojin-yinlizi",
        "created_at": "2026-09-06T10:00:00+08:00",
        "producer": "cinematic-fast/research-director",
        "input_hashes": {"product_page_capture": "b" * 64},
        "assets": [{
            "asset_id": "page-asset-selected-sku",
            "source_page_ref": "product_page_capture.page_identity",
            "asset_role": "selected_sku",
            "usage_role": "identity_anchor",
            "original_url": "https://gw.alicdn.com/example.webp",
            "local_path": "assets/product_page/raw/selected-sku.webp",
            "width": 1000,
            "height": 1000,
            "mime_type": "image/webp",
            "sha256": "c" * 64,
            "sku_scope": ["6276962282892"],
            "parent_asset_id": None,
            "transforms": [],
        }],
    })


def test_product_page_capture_and_asset_ledger_are_canonical_artifacts() -> None:
    validate_artifact("product_page_capture", _capture())
    validate_artifact("product_asset_ledger", _ledger())


def test_product_asset_ledger_accepts_a_traceable_clean_reference() -> None:
    ledger = _ledger()
    parent = ledger["assets"][0]
    ledger["assets"].append({
        "asset_id": "page-asset-selected-sku-clean-v1",
        "source_page_ref": parent["source_page_ref"],
        "asset_role": "derived_clean_reference",
        "usage_role": "generation_reference",
        "original_url": parent["original_url"],
        "local_path": "assets/product_page/derived/selected-sku-clean-v1.png",
        "width": 1000,
        "height": 1000,
        "mime_type": "image/png",
        "sha256": "d" * 64,
        "sku_scope": ["6276962282892"],
        "parent_asset_id": parent["asset_id"],
        "claim_refs": ["product_facts.claims[0]"],
        "derived_asset_ids": [],
        "transforms": [{
            "operation": "text_region_removal",
            "input_hash": parent["sha256"],
            "output_hash": "d" * 64,
        }],
        "clean_reference_status": "ready",
        "ocr_regions": [],
        "ocr_residual_text": [],
        "identity_check": {"status": "pass", "notes": []},
        "generation_eligibility": "eligible",
    })
    ledger = attach_hashes(ledger)

    validate_artifact("product_asset_ledger", ledger)


def test_clean_reference_cannot_be_ready_with_residual_text() -> None:
    ledger = _ledger()
    parent = ledger["assets"][0]
    ledger["assets"].append({
        "asset_id": "page-asset-selected-sku-clean-v1",
        "source_page_ref": parent["source_page_ref"],
        "asset_role": "derived_clean_reference",
        "usage_role": "generation_reference",
        "original_url": parent["original_url"],
        "local_path": "assets/product_page/derived/selected-sku-clean-v1.png",
        "width": 1000,
        "height": 1000,
        "mime_type": "image/png",
        "sha256": "d" * 64,
        "sku_scope": ["6276962282892"],
        "parent_asset_id": parent["asset_id"],
        "claim_refs": ["product_facts.claims[0]"],
        "derived_asset_ids": [],
        "transforms": [{
            "operation": "text_region_removal",
            "input_hash": parent["sha256"],
            "output_hash": "d" * 64,
        }],
        "clean_reference_status": "ready",
        "ocr_regions": [],
        "ocr_residual_text": ["10A级抗菌"],
        "identity_check": {"status": "pass", "notes": []},
        "generation_eligibility": "eligible",
    })
    ledger = attach_hashes(ledger)

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("product_asset_ledger", ledger)


def test_complete_capture_requires_url_sku_to_match_selected_sku() -> None:
    capture = _capture()
    capture["page_identity"]["selected_sku_id"] = "different-sku"

    with pytest.raises(jsonschema.ValidationError, match="SKU"):
        validate_artifact("product_page_capture", capture)


def test_page_claim_cannot_be_labeled_as_qualified_report() -> None:
    capture = deepcopy(_capture())
    capture["fact_candidates"][0]["evidence_status"] = "qualified_report"

    with pytest.raises(jsonschema.ValidationError, match="qualified"):
        validate_artifact("product_page_capture", capture)

from __future__ import annotations

from copy import deepcopy

import pytest

from lib.product_fact_reconciliation import reconcile_product_facts
from tests.contracts.test_product_page_acquisition import _capture, _ledger


def _facts() -> dict:
    return reconcile_product_facts(
        capture=_capture(),
        asset_ledger=_ledger(),
        operator_confirmation={"selected_sku_id": "6276962282892"},
    )


def test_compile_observable_claim_keeps_fact_wording_assets_and_sku() -> None:
    from lib.product_image_routing import compile_claim_visual_requirements

    facts = _facts()
    facts["claims"][0]["page_asset_ids"] = ["page-asset-selected-sku"]

    requirements = compile_claim_visual_requirements(
        facts,
        [{
            "product_fact_ref": "product_facts.claims[0]",
            "visualizability": "observable",
            "required_subjects": ["target_product"],
            "required_actions": ["continuous_pour_water", "water_contacts_towel"],
            "required_results": ["visible_water_contact_result"],
            "forbidden_substitutions": ["roller_only", "single_droplet_only"],
        }],
    )

    assert requirements == [{
        "product_fact_ref": "product_facts.claims[0]",
        "claim_id": "page-fact-001",
        "visualizability": "observable",
        "required_subjects": ["target_product"],
        "required_actions": ["continuous_pour_water", "water_contacts_towel"],
        "required_results": ["visible_water_contact_result"],
        "forbidden_substitutions": ["roller_only", "single_droplet_only"],
        "allowed_wording": ["商品页标注10A级抗菌"],
        "prohibited_wording": ["经独立检测达到10A级抗菌"],
        "candidate_page_asset_ids": ["page-asset-selected-sku"],
        "sku_scope": ["6276962282892"],
        "risk_level": "high",
        "evidence_policy": {
            "fact_basis": "merchant_page_claim",
            "generated_media_role": "visual_expression_only",
            "generated_media_can_prove_claim": False,
        },
    }]


def test_compile_non_observable_claim_never_promotes_generated_media_to_evidence() -> None:
    from lib.product_image_routing import compile_claim_visual_requirements

    requirement = compile_claim_visual_requirements(
        _facts(),
        [{
            "product_fact_ref": "product_facts.claims[0]",
            "visualizability": "non_observable",
            "required_subjects": ["target_product"],
            "required_actions": [],
            "required_results": [],
            "forbidden_substitutions": ["simulated_antibacterial_proof"],
        }],
    )[0]

    assert requirement["visualizability"] == "non_observable"
    assert requirement["evidence_policy"]["generated_media_can_prove_claim"] is False
    assert requirement["evidence_policy"]["generated_media_role"] == "visual_expression_only"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"status": "forbidden"}, "forbidden"),
        ({"evidence_status": "needs_human_confirmation"}, "not confirmed"),
        ({"allowed_wording": []}, "allowed wording"),
    ],
)
def test_compile_claim_fails_closed_for_unusable_fact(mutation: dict, message: str) -> None:
    from lib.product_image_routing import compile_claim_visual_requirements

    facts = deepcopy(_facts())
    facts["claims"][0].update(mutation)

    with pytest.raises(ValueError, match=message):
        compile_claim_visual_requirements(
            facts,
            [{
                "product_fact_ref": "product_facts.claims[0]",
                "visualizability": "contextual",
                "required_subjects": ["target_product"],
                "required_actions": [],
                "required_results": [],
                "forbidden_substitutions": [],
            }],
        )


def test_observable_claim_requires_subject_action_and_result_contract() -> None:
    from lib.product_image_routing import compile_claim_visual_requirements

    with pytest.raises(ValueError, match="observable.*subjects, actions, and results"):
        compile_claim_visual_requirements(
            _facts(),
            [{
                "product_fact_ref": "product_facts.claims[0]",
                "visualizability": "observable",
                "required_subjects": ["target_product"],
                "required_actions": [],
                "required_results": [],
                "forbidden_substitutions": [],
            }],
        )


def test_validate_clean_reference_requires_parent_sku_hashes_and_identity_pass() -> None:
    from lib.product_image_routing import validate_clean_reference_asset

    parent = _ledger()["assets"][0]
    clean = {
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
    }

    assert validate_clean_reference_asset(
        clean, parent_asset=parent, expected_sku="6276962282892"
    )["asset_id"] == clean["asset_id"]

    broken = deepcopy(clean)
    broken["identity_check"]["status"] = "needs_human"
    with pytest.raises(ValueError, match="identity"):
        validate_clean_reference_asset(
            broken, parent_asset=parent, expected_sku="6276962282892"
        )

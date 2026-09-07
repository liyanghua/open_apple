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


def test_compile_claim_can_select_an_ordered_subset_of_approved_wording() -> None:
    from lib.product_image_routing import compile_claim_visual_requirements

    facts = _facts()
    facts["claims"][0]["allowed_wording"] = [
        "商品页标注10A级抗菌",
        "画面展示柔胭粉毛巾，抗菌为商品页声明",
    ]
    requirement = compile_claim_visual_requirements(
        facts,
        [{
            "product_fact_ref": "product_facts.claims[0]",
            "visualizability": "non_observable",
            "required_subjects": ["target_product"],
            "required_actions": ["slow_product_reveal"],
            "required_results": ["selected_sku_remains_identifiable"],
            "forbidden_substitutions": [],
            "preferred_wording": [
                "画面展示柔胭粉毛巾，抗菌为商品页声明",
                "商品页标注10A级抗菌",
            ],
        }],
    )[0]

    assert requirement["allowed_wording"] == [
        "画面展示柔胭粉毛巾，抗菌为商品页声明",
        "商品页标注10A级抗菌",
    ]

    with pytest.raises(ValueError, match="preferred wording"):
        compile_claim_visual_requirements(
            facts,
            [{
                "product_fact_ref": "product_facts.claims[0]",
                "visualizability": "contextual",
                "required_subjects": ["target_product"],
                "required_actions": ["slow_product_reveal"],
                "required_results": ["selected_sku_remains_identifiable"],
                "forbidden_substitutions": [],
                "preferred_wording": ["独立检测已经证明抗菌"],
            }],
        )


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


def _visual_requirement() -> dict:
    return {
        "product_fact_ref": "product_facts.claims[0]",
        "claim_id": "absorb-visible",
        "visualizability": "observable",
        "required_subjects": ["target_product", "water"],
        "required_actions": ["continuous_pour_water", "water_contacts_towel"],
        "required_results": ["visible_water_contact_result"],
        "forbidden_substitutions": ["roller_only", "single_droplet_only"],
        "allowed_wording": ["一股水浇下，湿润范围清楚可见"],
        "prohibited_wording": ["一触即收", "瞬间吸干"],
        "candidate_page_asset_ids": ["page-asset-main-03"],
        "sku_scope": ["6276962282892"],
        "risk_level": "medium",
        "evidence_policy": {
            "fact_basis": "merchant_page_claim",
            "generated_media_role": "visual_expression_only",
            "generated_media_can_prove_claim": False,
        },
    }


def _owned_candidate(**overrides) -> dict:
    candidate = {
        "media_id": "towel-pour-01",
        "source_path": "inputs/source/towel-pour-01.mp4",
        "source_hash": "a" * 64,
        "interval": {"start_seconds": 1.0, "end_seconds_exclusive": 4.5},
        "observed_subject": ["target_product", "water"],
        "observed_actions": ["continuous_pour_water", "water_contacts_towel"],
        "observed_results": ["visible_water_contact_result"],
        "evidence_class": "dynamic_result",
        "evidence_strength": "strong",
        "crop_safety": {"subject_complete_in_3_4": True},
        "quality": {"usable": True, "confidence": 0.94, "risks": []},
        "representative_frames": ["analysis/towel-pour-01/frame.jpg"],
    }
    candidate.update(overrides)
    return candidate


def _clean_reference(**overrides) -> dict:
    reference = {
        "asset_id": "page-asset-main-03-clean-v1",
        "local_path": "assets/product_page/derived/main-03-clean-v1.png",
        "sha256": "d" * 64,
        "parent_asset_id": "page-asset-main-03",
        "claim_refs": ["product_facts.claims[0]"],
        "sku_scope": ["6276962282892"],
        "clean_reference_status": "ready",
        "ocr_residual_text": [],
        "identity_check": {"status": "pass", "notes": []},
        "generation_eligibility": "eligible",
    }
    reference.update(overrides)
    return reference


def test_router_selects_owned_only_when_subject_action_result_and_crop_match() -> None:
    from lib.product_image_routing import route_claim_coverage

    decision = route_claim_coverage(
        _visual_requirement(),
        owned_candidates=[_owned_candidate()],
        clean_references=[_clean_reference()],
    )

    assert decision["visual_route"] == "owned_source"
    assert decision["selected_source"]["media_id"] == "towel-pour-01"
    assert decision["generation_reference"] is None
    assert decision["owned_candidates"][0]["status"] == "accepted"


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (
            _owned_candidate(
                observed_actions=["single_droplet_only", "water_contacts_towel"]
            ),
            "required actions",
        ),
        (
            _owned_candidate(
                observed_actions=["roller_only"], observed_results=[]
            ),
            "forbidden substitution",
        ),
        (
            _owned_candidate(
                observed_actions=["read_fluorescent_agent_detector"],
                observed_results=["gauge_reads_0_00"],
                evidence_class="measurement",
                measurement_type="fluorescent_agent",
            ),
            "required actions",
        ),
    ],
)
def test_router_rejects_semantically_wrong_owned_footage(candidate: dict, reason: str) -> None:
    from lib.product_image_routing import route_claim_coverage

    decision = route_claim_coverage(
        _visual_requirement(), owned_candidates=[candidate], clean_references=[]
    )

    assert decision["visual_route"] == "omit"
    assert decision["selected_source"] is None
    assert reason in " ".join(decision["owned_candidates"][0]["rejection_reasons"])


def test_router_uses_ready_clean_reference_when_owned_coverage_is_invalid() -> None:
    from lib.product_image_routing import route_claim_coverage

    decision = route_claim_coverage(
        _visual_requirement(),
        owned_candidates=[_owned_candidate(observed_actions=["roller_only"], observed_results=[])],
        clean_references=[_clean_reference()],
    )

    assert decision["visual_route"] == "generated_from_product_image"
    assert decision["selected_source"] is None
    assert decision["generation_reference"]["asset_id"] == "page-asset-main-03-clean-v1"
    assert decision["generation_spec"]["operation"] == "image_to_video"
    assert decision["generation_spec"]["required_actions"] == [
        "continuous_pour_water", "water_contacts_towel"
    ]
    assert decision["generation_spec"]["evidence_role"] == "visual_expression_only"
    rejected = decision["owned_candidates"][0]
    assert rejected["observed_actions"] == ["roller_only"]
    assert rejected["observed_results"] == []
    assert rejected["subject_complete_in_3_4"] is True


@pytest.mark.parametrize(
    "reference",
    [
        _clean_reference(sku_scope=["different-sku"]),
        _clean_reference(ocr_residual_text=["吸水力max"]),
        _clean_reference(identity_check={"status": "needs_human", "notes": []}),
    ],
)
def test_router_omits_when_clean_reference_is_unsafe(reference: dict) -> None:
    from lib.product_image_routing import route_claim_coverage

    decision = route_claim_coverage(
        _visual_requirement(), owned_candidates=[], clean_references=[reference]
    )

    assert decision["visual_route"] == "omit"
    assert decision["generation_reference"] is None

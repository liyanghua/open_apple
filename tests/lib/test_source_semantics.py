from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from lib.artifact_hashing import attach_hashes, semantic_sha256
from lib.checkpoint import (
    FASTLINE_ARTIFACTS,
    SUPPLEMENTARY_ARTIFACTS,
    CheckpointValidationError,
    _validate_source_led_scene_mapping,
    init_project,
    validate_checkpoint,
)
from lib.research_validation import (
    validate_proposal_research_handoff,
    validate_research_derived_files,
)
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


HASH = "a" * 64


def _product_facts() -> dict:
    facts = {
        "version": "1.0",
        "product_name": "银离子毛巾",
        "claims": [
            {
                "claim": "画面可展示吸水过程",
                "status": "needs_evidence",
                "evidence": "自有素材实拍",
            },
            {
                "claim": "吸水率 99%",
                "status": "forbidden",
                "evidence": "无检测报告",
            },
        ],
    }
    facts["semantic_sha256"] = semantic_sha256(facts)
    return facts


def _observation() -> dict:
    return {
        "media_id": "towel-023",
        "source_path": "inputs/source/towel-023.mp4",
        "source_hash": HASH,
        "interval": {"start_seconds": 1.2, "end_seconds_exclusive": 4.8},
        "observed_subject": ["毛巾", "水流", "手部"],
        "observed_actions": ["pour_water", "absorb"],
        "observed_results": ["倒水后水面明显减少"],
        "crop_safety": {
            "subject_complete_in_3_4": True,
            "safe_caption_regions": ["top", "bottom"],
        },
        "quality": {"usable": True, "confidence": 0.92, "risks": []},
        "representative_frames": ["analysis/media/towel-023/frame_0001.jpg"],
        "claim_bindings": [
            {
                "claim_id": "absorb-visible",
                "product_fact_ref": "product_facts.claims[0]",
                "allowed_wording": ["可见吸水过程", "水分快速被带走"],
                "prohibited_wording": ["吸水率 99%"],
                "evidence_strength": "strong",
            }
        ],
    }


def _build_artifacts(input_mode: str = "source_led_template") -> dict:
    from lib.source_semantics import build_source_research_artifacts

    return build_source_research_artifacts(
        project_id="demo",
        input_mode=input_mode,
        observations=[_observation()],
        product_facts=_product_facts(),
        created_at="2026-09-03T00:00:00Z",
    )


def test_builder_creates_schema_valid_index_and_canonical_source_led_matrix() -> None:
    artifacts = _build_artifacts()
    index = artifacts["source_semantic_index"]
    matrix = artifacts["reference_source_matrix"]

    validate_artifact("source_semantic_index", index)
    validate_artifact("reference_source_matrix", matrix)

    assert index["input_mode"] == "source_led_template"
    assert index["entries"] == [
        {
            "media_id": "towel-023",
            "source_path": "inputs/source/towel-023.mp4",
            "source_hash": HASH,
            "interval": {"start_seconds": 1.2, "end_seconds_exclusive": 4.8},
            "observed_subject": ["毛巾", "水流", "手部"],
            "observed_actions": ["pour_water", "absorb"],
            "observed_results": ["倒水后水面明显减少"],
            "allowed_claim_ids": ["absorb-visible"],
            "crop_safety": {
                "subject_complete_in_3_4": True,
                "safe_caption_regions": ["top", "bottom"],
            },
            "quality": {"usable": True, "confidence": 0.92, "risks": []},
            "representative_frames": ["analysis/media/towel-023/frame_0001.jpg"],
        }
    ]
    row = matrix["rows"][0]
    assert matrix["matrix_mode"] == "source_led_template"
    assert row["reference_scene_id"] is None
    assert row["reference_time_range"] is None
    assert row["source_media_id"] == "towel-023"
    assert row["claim_ids"] == ["absorb-visible"]
    assert row["action_keys"] == ["pour_water", "absorb"]
    assert row["product_fact_refs"] == ["product_facts.claims[0]"]
    assert row["allowed_wording"] == ["可见吸水过程", "水分快速被带走"]
    assert row["prohibited_wording"] == ["吸水率 99%"]
    assert row["evidence_strength"] == "strong"


def test_builder_rejects_binding_to_forbidden_product_fact() -> None:
    observation = _observation()
    observation["claim_bindings"][0]["product_fact_ref"] = "product_facts.claims[1]"

    from lib.source_semantics import build_source_research_artifacts

    with pytest.raises(ValueError, match="forbidden product fact"):
        build_source_research_artifacts(
            project_id="demo",
            input_mode="source_led",
            observations=[observation],
            product_facts=_product_facts(),
        )


def test_builder_rejects_non_finite_source_interval() -> None:
    observation = _observation()
    observation["interval"]["start_seconds"] = float("nan")

    from lib.source_semantics import build_source_research_artifacts

    with pytest.raises(ValueError, match="interval"):
        build_source_research_artifacts(
            project_id="demo",
            input_mode="source_led",
            observations=[observation],
            product_facts=_product_facts(),
        )


def test_builder_emits_one_matrix_row_per_claim_binding() -> None:
    observation = _observation()
    observation["claim_bindings"].append(
        {
            "claim_id": "absorb-result",
            "product_fact_ref": "product_facts.claims[0]",
            "allowed_wording": ["水分被毛巾带走"],
            "prohibited_wording": ["瞬间全干"],
            "evidence_strength": "moderate",
        }
    )

    from lib.source_semantics import build_source_research_artifacts

    matrix = build_source_research_artifacts(
        project_id="demo",
        input_mode="source_led",
        observations=[observation],
        product_facts=_product_facts(),
    )["reference_source_matrix"]

    assert len(matrix["rows"]) == 2
    assert [row["claim_ids"] for row in matrix["rows"]] == [
        ["absorb-visible"],
        ["absorb-result"],
    ]
    assert matrix["rows"][0]["allowed_wording"] == [
        "可见吸水过程",
        "水分快速被带走",
    ]
    assert matrix["rows"][0]["evidence_strength"] == "strong"
    assert matrix["rows"][1]["allowed_wording"] == ["水分被毛巾带走"]
    assert matrix["rows"][1]["evidence_strength"] == "moderate"


@pytest.mark.parametrize(
    ("container", "field"),
    [("crop_safety", "subject_complete_in_3_4"), ("quality", "usable")],
)
def test_builder_rejects_non_boolean_safety_flags(container: str, field: str) -> None:
    observation = _observation()
    observation[container][field] = "yes"

    from lib.source_semantics import build_source_research_artifacts

    with pytest.raises(ValueError, match=field):
        build_source_research_artifacts(
            project_id="demo",
            input_mode="source_led",
            observations=[observation],
            product_facts=_product_facts(),
        )


def test_source_led_matrix_schema_rejects_fabricated_reference_fields() -> None:
    matrix = _build_artifacts("source_led")["reference_source_matrix"]
    matrix["rows"][0]["reference_scene_id"] = "reference-1"
    matrix["rows"][0]["reference_time_range"] = {
        "start_seconds": 0,
        "end_seconds_exclusive": 1,
    }

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("reference_source_matrix", matrix)


def test_reference_matrix_mode_keeps_real_reference_fields_required() -> None:
    matrix = _build_artifacts("source_led")["reference_source_matrix"]
    matrix["matrix_mode"] = "reference"

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("reference_source_matrix", matrix)


def test_proposal_handoff_requires_matrix_mode_to_match_input_mode() -> None:
    matrix = _build_artifacts("source_led")["reference_source_matrix"]
    synthesis = {
        "differentiation_directions": [{"direction_id": "direction-1"}]
    }
    proposal = {
        "concept_options": [
            {
                "id": "concept-1",
                "research_direction_refs": ["direction-1"],
                "matrix_row_refs": [matrix["rows"][0]["matrix_row_id"]],
                "fingerprint_rule_refs": ["proof-pair"],
            }
        ]
    }

    validate_proposal_research_handoff(
        proposal, synthesis, matrix, input_mode="source_led"
    )
    matrix["matrix_mode"] = "source_led_template"
    with pytest.raises(ValueError, match="matrix_mode"):
        validate_proposal_research_handoff(
            proposal, synthesis, matrix, input_mode="source_led"
        )


def test_source_led_scene_validation_requires_matching_matrix_mode() -> None:
    artifacts = _build_artifacts("source_led")
    matrix = artifacts["reference_source_matrix"]
    matrix["matrix_mode"] = "reference"
    scene_plan = {
        "scenes": [
            {
                "id": "s1",
                "shot_intent": "show visible absorption",
                "start_seconds": 0,
                "end_seconds": 1,
            }
        ],
        "metadata": {
            "reference_media_usage": "not_applicable",
            "source_mapping": [
                {
                    "scene_id": "s1",
                    "source_path": "inputs/source/towel-023.mp4",
                    "source_interval": {
                        "start_seconds": 1.2,
                        "end_seconds_exclusive": 2.2,
                    },
                    "timeline_interval": {
                        "start_seconds": 0,
                        "end_seconds_exclusive": 1,
                    },
                    "reference_evidence": {"mode": "none"},
                    "reference_basis": "source-led observation",
                    "source_fit": "visible absorption action",
                    "mapping_reason": "matches the claim action",
                    "originality_note": "owned footage only",
                    "matrix_row_id": matrix["rows"][0]["matrix_row_id"],
                    "evidence_row_ids": [matrix["rows"][0]["matrix_row_id"]],
                    "source_hash": matrix["rows"][0]["source_hash"],
                    "matrix_resolution_id": "accept",
                    "research_direction_ref": "direction-1",
                }
            ],
        },
    }
    source_review = {
        "files": [
            {
                "media_id": "towel-023",
                "path": "inputs/source/towel-023.mp4",
                "media_type": "video",
                "reviewed": True,
                "technical_probe": {"duration_seconds": 8},
            }
        ]
    }

    with pytest.raises(ValueError, match="matrix_mode"):
        _validate_source_led_scene_mapping(
            scene_plan,
            input_mode="source_led",
            source_media_review=source_review,
            source_semantic_index=artifacts["source_semantic_index"],
            reference_source_matrix=matrix,
            research_synthesis={
                "differentiation_directions": [{"direction_id": "direction-1"}]
            },
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda index: index["entries"][0]["quality"].update(usable=False), "usable"),
        (
            lambda index: index["entries"][0]["crop_safety"].update(
                subject_complete_in_3_4=False
            ),
            "subject_complete_in_3_4",
        ),
        (lambda index: index["entries"][0].update(source_path="inputs/source/other.mp4"), "semantic evidence"),
        (lambda index: index["entries"][0].update(media_id="other-media"), "media_id"),
        (lambda index: index["entries"][0].update(source_hash="b" * 64), "source hash"),
        (
            lambda index: index["entries"][0].update(
                interval={"start_seconds": 2, "end_seconds_exclusive": 3}
            ),
            "semantic source interval",
        ),
        (
            lambda index: index["entries"][0].update(
                representative_frames=["analysis/media/other/frame.jpg"]
            ),
            "representative evidence",
        ),
    ],
)
def test_source_led_scene_validation_rejects_invalid_semantic_source(
    mutation, message: str
) -> None:
    artifacts = _build_artifacts("source_led")
    index = artifacts["source_semantic_index"]
    matrix = artifacts["reference_source_matrix"]
    mutation(index)
    scene_plan = {
        "scenes": [{"id": "s1", "shot_intent": "proof", "start_seconds": 0, "end_seconds": 1}],
        "metadata": {"reference_media_usage": "not_applicable", "source_mapping": [{
            "scene_id": "s1", "source_path": "inputs/source/towel-023.mp4",
            "source_interval": {"start_seconds": 1.2, "end_seconds_exclusive": 2.2},
            "timeline_interval": {"start_seconds": 0, "end_seconds_exclusive": 1},
            "reference_evidence": {"mode": "none"}, "reference_basis": "owned observation",
            "source_fit": "visible action", "mapping_reason": "claim match",
            "originality_note": "owned only", "matrix_row_id": matrix["rows"][0]["matrix_row_id"],
            "evidence_row_ids": [matrix["rows"][0]["matrix_row_id"]],
            "source_hash": matrix["rows"][0]["source_hash"],
            "matrix_resolution_id": "accept", "research_direction_ref": "direction-1",
        }]},
    }
    source_review = {"files": [{
        "media_id": "towel-023", "path": "inputs/source/towel-023.mp4",
        "media_type": "video", "reviewed": True,
        "technical_probe": {"duration_seconds": 8},
    }]}

    with pytest.raises(ValueError, match=message):
        _validate_source_led_scene_mapping(
            scene_plan, input_mode="source_led", source_media_review=source_review,
            source_semantic_index=index, reference_source_matrix=matrix,
            research_synthesis={"differentiation_directions": [{"direction_id": "direction-1"}]},
        )


def test_source_led_scene_validation_allows_two_semantic_windows_for_same_path() -> None:
    from lib.source_semantics import build_source_research_artifacts

    first = _observation()
    second = deepcopy(first)
    second["interval"] = {"start_seconds": 5, "end_seconds_exclusive": 7}
    second["representative_frames"] = ["analysis/media/towel-023/frame_0002.jpg"]
    second["claim_bindings"][0].update(
        claim_id="absorb-result",
        allowed_wording=["吸水结果清晰可见"],
    )
    artifacts = build_source_research_artifacts(
        project_id="demo", input_mode="source_led",
        observations=[first, second], product_facts=_product_facts(),
    )
    matrix = artifacts["reference_source_matrix"]
    selected_row = matrix["rows"][1]
    scene_plan = {
        "scenes": [{"id": "s1", "shot_intent": "proof result", "start_seconds": 0, "end_seconds": 1}],
        "metadata": {"reference_media_usage": "not_applicable", "source_mapping": [{
            "scene_id": "s1", "source_path": "inputs/source/towel-023.mp4",
            "source_interval": {"start_seconds": 5.2, "end_seconds_exclusive": 6.2},
            "timeline_interval": {"start_seconds": 0, "end_seconds_exclusive": 1},
            "reference_evidence": {"mode": "none"}, "reference_basis": "owned observation",
            "source_fit": "visible result", "mapping_reason": "second semantic window",
            "originality_note": "owned only", "matrix_row_id": selected_row["matrix_row_id"],
            "evidence_row_ids": [selected_row["matrix_row_id"]],
            "source_hash": selected_row["source_hash"],
            "matrix_resolution_id": "accept", "research_direction_ref": "direction-1",
        }]},
    }
    source_review = {"files": [{
        "media_id": "towel-023", "path": "inputs/source/towel-023.mp4",
        "media_type": "video", "reviewed": True,
        "technical_probe": {"duration_seconds": 8},
    }]}

    _validate_source_led_scene_mapping(
        scene_plan, input_mode="source_led", source_media_review=source_review,
        source_semantic_index=artifacts["source_semantic_index"],
        reference_source_matrix=matrix,
        research_synthesis={"differentiation_directions": [{"direction_id": "direction-1"}]},
    )


def test_source_led_template_prior_must_resolve_to_valid_hash_bound_pack(
    tmp_path: Path,
) -> None:
    from lib.checkpoint import _validate_source_led_template_prior

    pack = attach_hashes({
        "version": "1.0", "project_id": "demo",
        "created_at": "2026-09-03T00:00:00Z", "taxonomy_version": "1",
        "source_document": {"path": "templates.xlsx", "sha256": HASH, "parser_version": "1"},
        "templates": [{
            "template_id": "template-1", "sheet_name": "A", "slots": [{
                "slot_id": "slot-1", "ordinal": 1,
                "shot_language": {"shot_size": "close_up"},
            }],
        }],
    })
    artifact_path = tmp_path / "artifacts" / "template_pack.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(pack), encoding="utf-8")
    context = {"input_mode": "source_led_template", "template_prior": {
        "present": True, "usage": "structural_only",
        "template_pack_ref": "artifacts/template_pack.json",
    }}

    _validate_source_led_template_prior(tmp_path, context)
    pack["taxonomy_version"] = "tampered"
    artifact_path.write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        _validate_source_led_template_prior(tmp_path, context)


def test_source_semantic_index_is_registered_for_artifacts_and_fastline() -> None:
    assert "source_semantic_index" in ARTIFACT_NAMES
    assert "source_semantic_index" in FASTLINE_ARTIFACTS
    assert "source_semantic_index" in SUPPLEMENTARY_ARTIFACTS


def test_source_led_research_checkpoint_requires_source_semantic_index(
    tmp_path: Path,
) -> None:
    project_dir = init_project(
        "source-semantics",
        title="Source semantics",
        pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path,
        input_mode="source_led",
        external_reference=False,
    )
    checkpoint = {
        "version": "1.0",
        "project_id": "source-semantics",
        "pipeline_type": "cinematic-fast",
        "input_mode": "source_led",
        "stage": "research",
        "status": "completed",
        "timestamp": "2026-09-03T00:00:00Z",
        "artifacts": {},
    }

    with pytest.raises(CheckpointValidationError, match="source_semantic_index"):
        validate_checkpoint(checkpoint, project_dir=project_dir)


def test_source_led_schema_requires_complete_semantic_evidence_fields() -> None:
    matrix = _build_artifacts("source_led")["reference_source_matrix"]
    for field in (
        "claim_ids",
        "action_keys",
        "allowed_wording",
        "prohibited_wording",
        "evidence_strength",
    ):
        mutated = deepcopy(matrix)
        mutated["rows"][0].pop(field)
        with pytest.raises(jsonschema.ValidationError, match=field):
            validate_artifact("reference_source_matrix", mutated)


def test_research_derived_file_gate_checks_semantic_index_frames(
    tmp_path: Path,
) -> None:
    index = _build_artifacts("source_led")["source_semantic_index"]

    with pytest.raises(ValueError, match="frame_0001.jpg"):
        validate_research_derived_files(
            tmp_path, {"source_semantic_index": index}
        )

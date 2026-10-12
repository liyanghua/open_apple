from lib.reference_fidelity import build_alignment_report, default_fidelity_policy, validate_replacement_matrix


def test_high_risk_claim_requires_evidence():
    errors = validate_replacement_matrix([{
        "reference_shot_id": "s1", "target_shot_id": "t1",
        "claim_ids": ["oil-960"], "product_fact_refs": ["facts.claims.0"],
    }], high_risk_claim_ids={"oil-960"})
    assert errors == ["row 0 high-risk claims require evidence"]


def test_target_shot_must_be_unique():
    errors = validate_replacement_matrix([
        {"reference_shot_id": "s1", "target_shot_id": "t1"},
        {"reference_shot_id": "s2", "target_shot_id": "t1"},
    ])
    assert "duplicate target_shot_id: t1" in errors


def test_alignment_report_blocks_reference_media_and_timing_misses():
    report = build_alignment_report(
        reference_duration_seconds=12.434,
        target_duration_seconds=12.042,
        matrix_rows=[{"reference_shot_id": "s1", "target_shot_id": "t1"}],
        voice_segments=[{"segment_id": "n1", "start_drift_ms": 10, "end_drift_ms": 170}],
        render_inputs=["inputs/reference/original.mp4"],
    )
    assert report["status"] == "fail"
    assert report["reference_fidelity"]["score"] < 0.85
    assert "duration_drift" in report["hard_gate_failures"]
    assert "reference_media_in_render" in report["hard_gate_failures"]


def test_alignment_report_passes_with_evidence_and_timing_in_budget():
    report = build_alignment_report(
        reference_duration_seconds=12.434,
        target_duration_seconds=12.43,
        matrix_rows=[{
            "reference_shot_id": "s1", "target_shot_id": "t1",
            "claim_ids": ["oil-960"], "product_fact_refs": ["facts.0"],
            "evidence_row_ids": ["report-960"],
        }],
        high_risk_claim_ids={"oil-960"},
        voice_segments=[{"segment_id": "n1", "start_drift_ms": 10, "end_drift_ms": 15}],
        render_inputs=["assets/video/product.mp4"],
        product_identity_match=True,
    )
    assert report["status"] == "pass"
    assert report["product_truth"]["score"] == 1


def test_default_policy_locks_timing_and_forbids_reference_media():
    policy = default_fidelity_policy()
    assert policy["mode"] == "reference_fidelity"
    assert policy["duration_drift_tolerance_ms"] == 120
    assert "reference_original_pixels" in policy["forbidden_dimensions"]

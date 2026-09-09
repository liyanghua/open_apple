from pathlib import Path

import pytest

from lib.cache_keys import canonical_digest


def test_alignment_evidence_binds_output_timeline_and_current_sources(tmp_path: Path):
    from lib.editorial_alignment_evidence import build_editorial_alignment_evidence

    output = tmp_path / "preview.mp4"
    output.write_bytes(b"new-render")
    evidence = build_editorial_alignment_evidence(
        timeline={"timeline_hash": canonical_digest({"tracks": []}), "tracks": []},
        output_path=output,
        output_probe={"duration_seconds": 3.0},
        frame_samples=[{"timestamp_seconds": 0.0, "path": "frame-000.png"}],
        fact_bindings=[{"shot_id": "shot-1", "claim_ids": ["claim-1"]}],
        script_hash="b" * 64,
        product_facts_hash="c" * 64,
        visual_requirements=[{"id": "visual-1", "claim_ids": ["claim-1"]}],
        checks=[{"shot_id": "shot-1", "scene_id": "scene-1", "action_match": "pass",
                 "result_support": "pass", "narration_caption_match": "pass",
                 "crop_completeness": "pass", "product_identity_match": "pass",
                 "status": "pass", "reason_codes": []}],
    )
    assert evidence["status"] == "pass"
    assert evidence["output_sha256"]
    assert evidence["timeline_hash"] == canonical_digest({"tracks": []})
    assert evidence["source_hashes"] == {
        "script": "b" * 64,
        "product_facts": "c" * 64,
    }
    assert evidence["output_probe"] == {"duration_seconds": 3.0}


def test_alignment_evidence_rejects_baseline_report_or_missing_output_probe(tmp_path: Path):
    from lib.editorial_alignment_evidence import build_editorial_alignment_evidence

    output = tmp_path / "final.mp4"
    output.write_bytes(b"new-render")
    with pytest.raises(ValueError, match="baseline|output_probe"):
        build_editorial_alignment_evidence(
            timeline={"timeline_hash": canonical_digest({"tracks": []}), "tracks": []},
            output_path=output,
            output_probe=None,
            frame_samples=[],
            fact_bindings=[],
            script_hash="b" * 64,
            product_facts_hash="c" * 64,
            visual_requirements=[],
            baseline_alignment={"status": "pass"},
        )

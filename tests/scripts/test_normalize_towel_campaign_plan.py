from __future__ import annotations

import json
from pathlib import Path

from scripts.normalize_towel_campaign_plan import normalize
from schemas.artifacts import validate_artifact


def _facts(product_id: str, sku: str) -> dict:
    return {
        "version": "1.0",
        "product_name": sku,
        "product_id": product_id,
        "sku": sku,
        "claims": [{
            "claim_id": f"{sku}-C01",
            "claim": "页面标注材质",
            "status": "needs_evidence",
            "evidence_status": "page_claim",
            "allowed_wording": ["页面标注材质"],
            "prohibited_wording": [],
        }],
    }


def test_normalize_writes_campaign_and_pending_fact_snapshots(tmp_path: Path):
    project = tmp_path / "playboy-towel-p1p2-v1"
    (project / "artifacts").mkdir(parents=True)
    (tmp_path / "playboy-towel-p1-v1" / "artifacts").mkdir(parents=True)
    (tmp_path / "playboy-towel-p2-v1" / "artifacts").mkdir(parents=True)
    (tmp_path / "playboy-towel-p1-v1" / "artifacts" / "product_facts.json").write_text(
        json.dumps(_facts("p1", "yb-bb-03")), encoding="utf-8"
    )
    (tmp_path / "playboy-towel-p2-v1" / "artifacts" / "product_facts.json").write_text(
        json.dumps(_facts("p2", "yb-bb-12")), encoding="utf-8"
    )
    (project / "batch_plan.json").write_text(json.dumps({
        "campaign_id": "pilot",
        "products": [{"fact_version": "P1_fact_v1"}, {"fact_version": "P2_fact_v1"}],
        "slots": [{
            "slot_id": "P1-A01",
            "product_key": "P1",
            "content_group": "A",
            "week": "W1",
        }],
    }), encoding="utf-8")

    result = normalize(project)
    assert result["slot_count"] == 1
    assert result["status"] == "pending_confirmation"
    plan = json.loads((project / "artifacts" / "campaign_plan.json").read_text())
    validate_artifact("campaign_plan", plan)
    snapshot = json.loads((project / "artifacts" / "fact_snapshot_P1.json").read_text())
    validate_artifact("fact_snapshot", snapshot)
    assert snapshot["status"] == "pending_confirmation"

"""Unit tests for lib.template_assets（assets 阶段制品：no-paid 计划 + fail-closed gate）。"""

from __future__ import annotations

import json
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import get_completed_stages, get_next_stage
from lib.template_assets import build_assets
from lib.template_fork import fork_template_run
from lib.template_mainline import advance_to_assets
from lib.template_run_plan import create_template_run, check_template_run_plan_ready
from lib.template_source_match import match_run_plan

ROOT = Path(__file__).resolve().parents[2]
REAL_SOURCE = ROOT / "projects/table-mat-mix-v8"
PACK = ROOT / "projects/template-pack-library/artifacts/template_pack.json"


def _setup_run(tmp_path: Path, template: dict, facts: dict, *, approved: bool = True) -> str:
    run_id = f"template-run-{template['template_id']}-ast"
    fork_template_run(run_id, source_project_dir=REAL_SOURCE, pipeline_dir=tmp_path,
                      product_facts_path=ROOT / "projects/template-pilot/artifacts/product_facts.json")
    rp = create_template_run(template, template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"},
                             product_facts_ref={"artifact_sha256": facts.get("artifact_sha256", "b" * 64)})
    match_run_plan(template.get("slots") or [], rp)
    if approved:
        rp["status"] = "approved"
    write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp, project_dir=tmp_path / run_id)
    return run_id


def test_assets_gate_blocks_unapproved_run_plan(tmp_path: Path):
    import pytest
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    run_id = _setup_run(tmp_path, template, facts, approved=False)
    # run_plan 未批准（awaiting_human）→ build_assets 必须 fail-closed 拦住
    with pytest.raises(SystemExit):
        build_assets(tmp_path / run_id, template, pipeline_dir=tmp_path)


def test_advance_to_assets_writes_awaiting_human_no_paid(tmp_path: Path):
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    run_id = _setup_run(tmp_path, template, facts)
    # 推进到 assets
    next_stage = advance_to_assets(run_id, pipeline_dir=tmp_path)
    assert next_stage == "assets"  # awaiting_human 不计为 completed
    from lib.checkpoint import read_checkpoint
    cp = read_checkpoint(tmp_path, run_id, "assets")
    assert cp.get("status") == "awaiting_human"
    # 四个制品全部 schema 有效 + 无 paid
    for name in ("shot_execution_plan", "asset_plan", "production_lock", "approval_bundle"):
        _ = json.loads((tmp_path / run_id / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))
    ap = json.loads((tmp_path / run_id / "artifacts" / "asset_plan.json").read_text(encoding="utf-8"))
    assert ap["paid_generation_approved"] is False
    assert all(not a["paid"] for a in ap["planned_assets"])
    assert all(s["gap_strategy"] == "none" for s in json.loads((tmp_path / run_id / "artifacts" / "shot_execution_plan.json").read_text(encoding="utf-8"))["shots"])

"""Unit tests for lib.template_batch（批量控制面 + run 状态刷新）。"""

from __future__ import annotations

from pathlib import Path

from lib.template_batch import create_template_batch, mark_pilot, refresh_template_batch_status


def _pack() -> dict:
    return {
        "version": "1.0",
        "artifact_sha256": "a" * 64,
        "templates": [
            {"template_id": "t1", "slots": [{"slot_id": "t1-s1", "duration_s": 2.0}]},
            {"template_id": "t2", "slots": [{"slot_id": "t2-s1", "duration_s": 2.0}]},
        ],
    }


def test_create_batch_and_mark_pilot():
    b = create_template_batch(_pack(), product_facts_ref={"artifact_sha256": "b" * 64})
    assert len(b["runs"]) == 2
    assert all(r["status"] == "planned" for r in b["runs"])
    b = mark_pilot(b, ["t1"])
    assert b["pilot_run_ids"] == ["t1"]


def test_refresh_status_reflects_completed_scene_plan(tmp_path: Path):
    import json
    from lib.template_fork import fork_template_run
    from lib.template_mainline import advance_run_full

    ROOT = Path(__file__).resolve().parents[2]
    anchor = ROOT / "projects/template-run-sheet-01-video1-aks-zhuodian"
    if not anchor.is_dir():
        import pytest
        pytest.skip("主链路 run 产物未就绪（需先跑主链路）")
    # 复用真实共享研究源，fork 一条干净 run，并推进到 scene_plan。
    template_id = "sheet-01-video1-aks-zhuodian"
    run_id = "template-run-sheet-01-video1-aks-zhuodian"
    fork_template_run(
        run_id,
        source_project_dir=ROOT / "projects/table-mat-mix-v8",
        pipeline_dir=tmp_path,
        product_facts_path=ROOT / "projects/template-pilot/artifacts/product_facts.json",
    )
    pack = json.loads((ROOT / "projects/template-pack-library/artifacts/template_pack.json").read_text(encoding="utf-8"))
    from lib.artifact_io import write_artifact_atomic
    from lib.template_run_plan import create_template_run
    from lib.template_source_match import match_run_plan
    template = next(t for t in pack["templates"] if t["template_id"] == template_id)
    facts = json.loads((ROOT / "projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    rp = create_template_run(template, template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"},
                             product_facts_ref={"artifact_sha256": facts.get("artifact_sha256", "b" * 64)})
    match_run_plan(template.get("slots") or [], rp)
    write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp, project_dir=tmp_path / run_id)
    advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack)

    b = create_template_batch(pack, product_facts_ref={"artifact_sha256": facts.get("artifact_sha256", "b" * 64)})
    refreshed = refresh_template_batch_status(b, pipeline_dir=tmp_path)
    statuses = {r["template_id"]: r["status"] for r in refreshed["runs"]}
    assert statuses[template_id] == "in_progress"

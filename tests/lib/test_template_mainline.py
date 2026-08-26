"""集成测试：lib.template_mainline 主链路推进（proposal → script → scene_plan）。"""

from __future__ import annotations

from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import get_completed_stages, get_next_stage
from lib.template_fork import fork_template_run
from lib.template_mainline import advance_run_full
from lib.template_run_plan import create_template_run
from lib.template_source_match import match_run_plan
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]
REAL_SOURCE = ROOT / "projects/table-mat-mix-v8"
PACK = ROOT / "projects/template-pack-library/artifacts/template_pack.json"


def _fresh_run(tmp_path: Path, template_id: str, template: dict, facts: dict) -> Path:
    """建一条干净的 template run：fork 共享 research + 写 template_run_plan + product_facts。"""
    run_id = f"template-run-{template_id}-itest"
    fork_template_run(run_id, source_project_dir=REAL_SOURCE, pipeline_dir=tmp_path)
    rp = create_template_run(
        template,
        template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"},
        product_facts_ref={"artifact_sha256": facts.get("artifact_sha256", "b" * 64)},
        adaptation_policy=str(template.get("archetype") or "proof-first"),
    )
    match_run_plan(template.get("slots") or [], rp)
    write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp,
                          project_dir=tmp_path / run_id)
    (tmp_path / run_id / "artifacts" / "product_facts.json").write_text(
        ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    return tmp_path / run_id


def test_advance_run_full_walks_proposal_script_scene_plan(tmp_path: Path):
    import json
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    template = next(t for t in pack["templates"] if t["template_id"] == "sheet-01-video1-aks-zhuodian")
    facts = json.loads(ROOT.joinpath("projects/template-pilot/artifacts/product_facts.json").read_text(encoding="utf-8"))
    _fresh_run(tmp_path, template["template_id"], template, facts)
    run_id = f"template-run-{template['template_id']}-itest"

    stages = advance_run_full(run_id, pipeline_dir=tmp_path, pack=pack)
    assert stages == ["research", "proposal", "script", "scene_plan"]
    assert get_next_stage(tmp_path, run_id, "cinematic-fast") == "assets"

    # 制品全部 schema 有效
    for name in ("proposal_packet", "creative_control_plan", "script", "scene_plan"):
        data = json.loads((tmp_path / run_id / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))
        validate_artifact(name, data)

    # scene_plan 每个 scene 都 ground 到 matrix row
    sp = json.loads((tmp_path / run_id / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    assert len(sp["metadata"]["source_mapping"]) == len(sp["scenes"])
    assert all(m.get("matrix_row_id") for m in sp["metadata"]["source_mapping"])

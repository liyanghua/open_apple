"""一次性引导：sheet-14 压缩变体 c1（10 镜/18.2s）run。

- c1 模板：从 sheet-14 保留镜（kept_ordinals）派生，slot_id 保持键控不变；
- 注册 c1 动作/文案表（复用现有机制）；
- 引导 run：create_template_run + match_run_plan（owned 绑定）+ fork（研究种子）+ 落盘。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
ROOT = Path(__file__).resolve().parents[1]

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.template_fork import fork_template_run
from lib.template_mainline import _NARRATION_BY_TEMPLATE
from lib.template_run_plan import create_template_run
from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE, match_run_plan
from schemas.artifacts import validate_artifact

PACK_PATH = ROOT / "projects/template-pack-library/artifacts/template_pack.json"
CANDS = ROOT / "docs/reports/export/compression-candidates-2026-08-27.json"
FACTS_SRC = ROOT / "projects/template-run-sheet-14-video15-aks-zhuodian/artifacts/product_facts.json"
SHARED_RESEARCH = ROOT / "projects/table-mat-mix-v8"
C1 = "sheet-14-video15-aks-zhuodian-c1"
RUN = f"template-run-{C1}"

pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
if any(t["template_id"] == C1 for t in pack["templates"]):
    print("c1 已存在，跳过 pack 追加")
    c1 = next(t for t in pack["templates"] if t["template_id"] == C1)
else:
    kept = json.loads(CANDS.read_text(encoding="utf-8"))["sheet-14-video15-aks-zhuodian"][0]["kept_ordinals"]
    parent = next(t for t in pack["templates"] if t["template_id"] == "sheet-14-video15-aks-zhuodian")
    kept_slots = [parent["slots"][o - 1].copy() for o in kept]
    for i, s in enumerate(kept_slots, start=1):
        s["ordinal"] = i
    c1 = {"template_id": C1, "sheet_name": "视频15_AKS桌垫·压缩版",
          "archetype": parent.get("archetype") or "proof-first", "slots": kept_slots}
    pack["templates"].append(c1)
    sealed = attach_hashes(dict(pack))
    validate_artifact("template_pack", sealed)
    write_artifact_atomic("artifacts/template_pack.json", "template_pack", sealed,
                          project_dir=ROOT / "projects/template-pack-library")
    print(f"c1 appended（{len(kept_slots)} 镜）| pack sha {sealed['artifact_sha256'][:10]}")

    rows14 = _NARRATION_BY_TEMPLATE["sheet-14-video15-aks-zhuodian"]
    SLOT_ACTION_BY_TEMPLATE[C1] = [SLOT_ACTION_BY_TEMPLATE["sheet-14-video15-aks-zhuodian"][o - 1] for o in kept]
    _NARRATION_BY_TEMPLATE[C1] = [rows14[o - 1] for o in kept]
    print("c1 动作/文案表已注册（10 行对齐）")

# run 引导
run_dir = ROOT / "projects" / RUN
if (run_dir / "artifacts/template_run_plan.json").exists():
    print("run 已存在，跳过引导")
else:
    facts = json.loads(FACTS_SRC.read_text(encoding="utf-8"))
    facts_ref = {"artifact_sha256": facts.get("artifact_sha256") or attach_hashes(dict(facts))["artifact_sha256"]}
    pack_hash = attach_hashes(dict(pack))["artifact_sha256"]
    run = create_template_run(c1, template_pack_ref={"artifact_sha256": pack_hash, "version": "1.0"},
                              product_facts_ref=facts_ref,
                              adaptation_policy=str(c1.get("archetype") or "proof-first"))
    match_run_plan(c1.get("slots") or [], run)
    sealed_run = attach_hashes(dict(run))
    validate_artifact("template_run_plan", sealed_run)
    run_dir.mkdir(parents=True, exist_ok=True)
    fork_template_run(RUN, source_project_dir=SHARED_RESEARCH, pipeline_dir=ROOT / "projects",
                      product_facts_path=FACTS_SRC)
    write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", sealed_run,
                          project_dir=run_dir)
    n_owned = sum(1 for b in sealed_run["slot_bindings"] if b["source"] == "owned")
    print(f"run 引导完成: {RUN} | owned {n_owned}/{len(sealed_run['slot_bindings'])} | research seeded")

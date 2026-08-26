"""初始化 template_pilot：pilot run 项目 + template_run_plan + template_batch（主链路模式）。

约定（复用主链路，不旁路）：
- 共享商品事实：`artifacts/product_facts.json`（Code Agent 弹卡后用户填写，单一共享）；
- 共享研究：`projects/table-mat-mix-v8` 的一次 video 分析（9 件研究制品 + analysis/），
  每个 template run 由 `lib.template_fork.fork_template_run` 播种为**从 proposal 开始**
  的 main-chain 项目（research checkpoint 直接 completed，不重复分析）；
- 从 template_pack 选 pilot 模板，用 `lib.template_source_match.match_run_plan` 做
  **no-dup + consistency** 的 slot→自有素材绑定；
- `template_batch.shared_research_refs` 记录共享研究制品引用。

用法：python -m scripts.init_template_pilot [--batch project/template-pilot] [--facts <product_facts.json>]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.template_batch import create_template_batch, mark_pilot, refresh_template_batch_status_for_pipeline
from lib.template_fork import fork_template_run, shared_research_refs
from lib.template_run_plan import create_template_run, select_pilot
from lib.template_source_match import match_run_plan
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[1]
# 共享研究源项目：一次视频分析（含 9 件研究制品 + analysis/），各 template run 复用，不重跑。
SHARED_RESEARCH_SOURCE = ROOT / "projects/table-mat-mix-v8"


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _require_sha(value: dict | None, field: str) -> str:
    """要求真实 artifact_sha256；缺失则抛错（不伪造 hash 让错误 provenance 看似合法）。"""
    sha = str((value or {}).get("artifact_sha256") or "").strip()
    if len(sha) != 64:
        raise SystemExit(f"{field} 缺少真实 artifact_sha256，请先落盘该制品")
    return sha


def main() -> None:
    parser = argparse.ArgumentParser(description="Init template pilot runs")
    parser.add_argument("--batch", default="template-pilot")
    parser.add_argument("--facts", default="artifacts/product_facts.json")
    parser.add_argument("--n-pilot", type=int, default=8)
    args = parser.parse_args()

    pack_path = ROOT / "projects/template-pack-library/artifacts/template_pack.json"
    pack = _load(pack_path)
    if not pack:
        raise SystemExit(f"template_pack not found: {pack_path}")

    facts = _load(ROOT / args.facts)
    if not facts:
        raise SystemExit(f"product_facts not found: {args.facts}（先用 Code Agent 弹卡填写）")
    facts_ref = {"artifact_sha256": _require_sha(facts, "product_facts")}
    pack_hash = _require_sha(pack, "template_pack")

    if not SHARED_RESEARCH_SOURCE.exists():
        raise SystemExit(f"共享研究源项目不存在: {SHARED_RESEARCH_SOURCE}")
    shared_refs = shared_research_refs(SHARED_RESEARCH_SOURCE)
    if not shared_refs:
        raise SystemExit(f"共享研究源缺少研究制品: {SHARED_RESEARCH_SOURCE}")

    pilot_ids = select_pilot(pack["templates"], n=args.n_pilot)
    batch_dir = ROOT / "projects" / args.batch
    (batch_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    run_plan_refs: dict[str, dict] = {}
    facts_path = ROOT / args.facts

    for template in pack["templates"]:
        tid = str(template.get("template_id") or "")
        if tid not in pilot_ids:
            continue
        run = create_template_run(template, template_pack_ref={
            "artifact_sha256": pack_hash,
            "version": "1.0",
        }, product_facts_ref=facts_ref, adaptation_policy=str(template.get("archetype") or "proof-first"))
        # slot → 自有素材绑定（no-dup + consistency：lib.template_source_match，就地更新 run 的 bindings）
        match_run_plan(template.get("slots") or [], run)
        sealed = attach_hashes(dict(run))
        validate_artifact("template_run_plan", sealed)
        run_dir = ROOT / "projects" / f"template-run-{tid}"
        # 播种共享 research → completed checkpoint，使 run 从 proposal 开始走主链路。
        fork_template_run(
            run_dir.name,
            source_project_dir=SHARED_RESEARCH_SOURCE,
            pipeline_dir=ROOT / "projects",
            product_facts_path=facts_path,
        )
        write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", sealed, project_dir=run_dir)
        # 共享事实卡复制到该 run（只读引用；fork 若已复制则跳过）
        if not (run_dir / "artifacts" / "product_facts.json").exists():
            shutil.copyfile(facts_path, run_dir / "artifacts" / "product_facts.json")
        run_plan_refs[tid] = {"artifact_sha256": sealed["artifact_sha256"]}
        n_owned = sum(1 for b in sealed["slot_bindings"] if b["source"] == "owned")
        print(f"  run {tid} -> {run_dir} ({n_owned}/{len(sealed['slot_bindings'])} owned slots, research seeded)")

    batch = create_template_batch(
        pack,
        product_facts_ref=facts_ref,
        template_run_plan_refs=run_plan_refs,
        shared_research_refs=shared_refs,
    )
    batch = mark_pilot(batch, pilot_ids)
    batch_sealed = attach_hashes(dict(batch))
    validate_artifact("template_batch", batch_sealed)
    write_artifact_atomic("artifacts/template_batch.json", "template_batch", batch_sealed, project_dir=batch_dir)
    # 批控制面投影：把 run 项目的 checkpoint 推进点刷进 batch.run.status（只读投影）。
    refreshed = refresh_template_batch_status_for_pipeline(batch_sealed, pipeline_dir=ROOT / "projects")
    write_artifact_atomic("artifacts/template_batch.json", "template_batch", refreshed, project_dir=batch_dir)
    # 共享事实卡写入批根（若源即批根则跳过，避免 SameFileError）
    facts_src = (ROOT / args.facts).resolve()
    facts_dst = (batch_dir / "artifacts" / "product_facts.json").resolve()
    if facts_src != facts_dst:
        shutil.copyfile(facts_src, facts_dst)
    print(f"\nOK: {len(pilot_ids)} pilot runs + template_batch -> {batch_dir}/artifacts/template_batch.json")


if __name__ == "__main__":
    main()

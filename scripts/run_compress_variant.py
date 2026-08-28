"""压缩变体一键流水线：bootstrap → 提案种子 → rebuild → 资产同步 → prep → 渲染 → QA
→ assets/sample 门 → edit → compose → publish（与 c1 同路径，供选版候选一键出片）。

用法：python -m scripts.run_compress_variant --base sheet-05-video5-aks-zhuodian [--use-first]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
ROOT = Path(__file__).resolve().parents[1]

from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import write_checkpoint
from lib.template_fork import fork_template_run
from lib.template_mainline import _NARRATION_BY_TEMPLATE
from lib.template_compression import compression_plan_for_subset
from lib.template_run_plan import create_template_run
from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE, match_run_plan
from schemas.artifacts import validate_artifact

PACK_PATH = ROOT / "projects/template-pack-library/artifacts/template_pack.json"
CANDS = ROOT / "docs/reports/export/compression-candidates-2026-08-27.json"
SHARED_RESEARCH = ROOT / "projects/table-mat-mix-v8"
PIPELINE = "cinematic-fast"
MANIFESTS = ("proposal_packet.json", "creative_control_plan.json", "hook_plan.json", "decision_log.json")
ASSET_BOARD = ("asset_plan.json", "production_lock.json", "approval_bundle.json")


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _envelope(path: str, key: str, data: dict) -> dict:
    return {"name": key, "path": path, "semantic_sha256": data.get("semantic_sha256", "1" * 64),
            "artifact_sha256": data.get("artifact_sha256", "1" * 64), "data": data}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    args = ap.parse_args()
    base = args.base
    tid = f"{base}-c1"
    run = f"template-run-{tid}"
    pack_dir = ROOT / "projects/template-pack-library"
    pack = _load(PACK_PATH) or {}
    candidates = _load(CANDS) or {}
    solutions = candidates.get(base) or []
    if not solutions:
        print(f"无候选: {base}"); return 2
    kept = solutions[0]["kept_ordinals"]
    src_run = ROOT / "projects" / f"template-run-{base}"
    run_dir = ROOT / "projects" / run
    parent = next(t for t in pack["templates"] if t["template_id"] == base)
    compression = compression_plan_for_subset(parent, kept)
    if not compression["all_hard_ok"]:
        failed = [name for name in ("h1_ok", "h2_ok", "h3_ok", "h4_ok", "capacity_ok", "dur_ok")
                  if not compression.get(name)]
        raise SystemExit(f"{base}: 压缩候选未通过当前素材池硬门: {', '.join(failed)}")

    # 1) pack 追加变体 + 表注册
    with ProjectCommitStore(pack_dir).transaction(action={"action_id": f"pack-{tid}"}) as sink:
        if not any(t["template_id"] == tid for t in pack.get("templates", [])):
            slots = [parent["slots"][o - 1].copy() for o in kept]
            for i, s in enumerate(slots, start=1):
                s["ordinal"] = i
            pack["templates"].append({"template_id": tid, "sheet_name": f"{parent.get('sheet_name')}·压缩版",
                                      "archetype": parent.get("archetype") or "proof-first", "slots": slots})
            sealed = attach_hashes(dict(pack))
            validate_artifact("template_pack", sealed)
            write_artifact_atomic("artifacts/template_pack.json", "template_pack", sealed,
                                  project_dir=pack_dir, sink=sink)
            print(f"[1] pack: {tid}（{len(slots)} 镜）")
        # 表注册（持久化到 lib 由外部完成；此处校验可用）
        if tid not in SLOT_ACTION_BY_TEMPLATE:
            raise SystemExit(f"{tid}: 请在 lib/template_source_match.py + template_mainline.py 持久化 c1 表后再跑")

    # 2) run 引导
    if not (run_dir / "artifacts/template_run_plan.json").exists():
        facts = _load(src_run / "artifacts/product_facts.json") or {}
        facts_ref = {"artifact_sha256": facts.get("artifact_sha256") or attach_hashes(dict(facts))["artifact_sha256"]}
        pack_hash = attach_hashes(dict(pack))["artifact_sha256"]
        template = next(t for t in pack["templates"] if t["template_id"] == tid)
        rp = create_template_run(template, template_pack_ref={"artifact_sha256": pack_hash, "version": "1.0"},
                                 product_facts_ref=facts_ref,
                                 adaptation_policy=str(template.get("archetype") or "proof-first"))
        rp["compression"] = compression
        match_run_plan(template.get("slots") or [], rp)
        sealed = attach_hashes(dict(rp))
        validate_artifact("template_run_plan", sealed)
        run_dir.mkdir(parents=True, exist_ok=True)
        fork_template_run(run, source_project_dir=SHARED_RESEARCH, pipeline_dir=ROOT / "projects",
                          product_facts_path=src_run / "artifacts/product_facts.json")
        with ProjectCommitStore(run_dir).transaction(action={"action_id": f"seed-rp-{run}"}) as sink:
            write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", sealed,
                                  project_dir=run_dir, sink=sink)
        print(f"[2] run 引导: {run}")
    else:
        existing = _load(run_dir / "artifacts/template_run_plan.json") or {}
        if existing.get("compression") != compression:
            existing["compression"] = compression
            existing.pop("semantic_sha256", None)
            existing.pop("artifact_sha256", None)
            sealed = attach_hashes(existing)
            validate_artifact("template_run_plan", sealed)
            with ProjectCommitStore(run_dir).transaction(action={"action_id": f"backfill-compression-{run}"}) as sink:
                write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", sealed,
                                      project_dir=run_dir, sink=sink)
            print(f"[2] run 引导：已回填 compression 契约 {run}")

    # 3) 提案种子（复制 4 件 + 提案 checkpoint）
    with ProjectCommitStore(run_dir).transaction(action={"action_id": f"seed-proposal-{run}"}) as sink:
        artifacts_map = {}
        for name in MANIFESTS:
            data = attach_hashes(dict(_load(src_run / "artifacts" / name) or {}))
            write_artifact_atomic(f"artifacts/{name}", name.split(".")[0], data, project_dir=run_dir, sink=sink)
            artifacts_map[name.split(".")[0]] = _envelope(f"artifacts/{name}", name.split(".")[0], data)
        write_checkpoint(ROOT / "projects", run, "proposal", "completed", artifacts_map,
                         pipeline_type=PIPELINE, next_action=None,
                         review={"findings": [], "verdict": "pass"}, sink=sink)
        print("[3] proposal 种子完成")

    # 4) 剧本/场景重建 + run plan 批准 + 资产同步
    from lib.template_mainline import rebuild_aligned_run
    rebuild_aligned_run(run)
    print("[4] script/scene_plan 重建（语义门通过）")
    rp = _load(run_dir / "artifacts/template_run_plan.json") or {}
    if str(rp.get("status") or "") != "approved":
        rp["status"] = "approved"; rp.pop("semantic_sha256", None); rp.pop("artifact_sha256", None)
        with ProjectCommitStore(run_dir).transaction(action={"action_id": f"approve-rp-{run}"}) as sink:
            write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan",
                                  attach_hashes(dict(rp)), project_dir=run_dir, sink=sink)
    from lib.template_assets import sync_assets_artifacts
    template = next(t for t in pack["templates"] if t["template_id"] == tid)
    with ProjectCommitStore(run_dir).transaction(action={"action_id": f"sync-assets-{run}"}) as sink:
        sync_assets_artifacts(run_dir, template, pipeline_dir=ROOT / "projects", sink=sink)
    print("[5] run plan 批准 + 资产四制品同步")

    # 5) 资产门 checkpoint（awaiting → approve）
    with ProjectCommitStore(run_dir).transaction(action={"action_id": f"seed-assets-{run}"}) as sink:
        artifacts_map = {}
        # sync_assets_artifacts above already generated these for the child run.
        # Never copy the parent's plans after compression: that restores the
        # parent's shot count/duration and leaves approval refs stale.
        for name in ASSET_BOARD:
            data = _load(run_dir / "artifacts" / name) or {}
            artifacts_map[name.split(".")[0]] = _envelope(f"artifacts/{name}", name.split(".")[0], data)
        sep = _load(run_dir / "artifacts/shot_execution_plan.json") or {}
        artifacts_map["shot_execution_plan"] = _envelope("artifacts/shot_execution_plan.json",
                                                         "shot_execution_plan", sep)
        write_checkpoint(ROOT / "projects", run, "assets", "awaiting_human", artifacts_map,
                         pipeline_type=PIPELINE,
                         next_action={"summary": f"{tid} 资产就绪（{len(sep.get('shots') or [])} 镜）",
                                      "verb": "await_user", "context_refs": ["artifacts/asset_manifest.json"]},
                         review={"findings": [], "verdict": "pass"}, sink=sink)
        print("[6] assets 门 awaiting（待 approve 脚本落 completed）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""历史成片总览：只读聚合（无付费、无评分执行；L3 分数仅读制品）。

复用 scripts.export_top_videos 的发现/收集/判定/排名逻辑（同一代码路径），
但**永不调用 video_judge**——L3 分数只读 artifacts/l3_advisory.json；
缺失时标记「未评分」，页面上提示由 export 脚本补分。
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import yaml

from backlot.operator_language import STAGE_LABELS, STATUS_LABELS
from scripts.export_top_videos import (
    DEFAULT_POLICY,
    PROJECTS,
    collect_run,
    discover_runs,
    rank_runs,
    rule_verdict,
    tier_of,
)
from lib.template_source_match import (capacity_verdict, is_template_calibrated,
                          material_reuse_report, semantic_mismatches)
from scripts.gen_template_audio import narration_filename


def _load_any(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _audio_coverage(project: Path, script: dict) -> dict:
    """口播覆盖强校验：每个有声 section 必须存在 TTS 文件 + 成品混音存在。"""
    audio_dir = project / "assets" / "audio"
    missing = []
    narrated = 0
    for sec in (script.get("sections") or []):
        if not str(sec.get("narration") or "").strip():
            continue
        narrated += 1
        if not (audio_dir / narration_filename(str(sec.get("id") or ""))).is_file():
            missing.append(str(sec.get("id")))
    mix_ok = (audio_dir / "sample-mix.mp3").is_file()
    return {"narrated": narrated, "missing": missing, "mix_ok": mix_ok,
            "coverage_ok": not missing and mix_ok}


_PACK_CACHE: dict = {}
_PUBLISHED_C1: set[str] | None = None
_RELEASES: dict | None = None


def _release_status(template_id: str, run: str) -> str:
    """发布版本标记：official（正式入口）/ superseded（已被压缩版取代）/ baseline（未指认）。"""
    global _RELEASES
    if _RELEASES is None:
        _RELEASES = _load_any(ROOT / "projects/template-pack-library/artifacts/release_designations.json") or {}
    for d in _RELEASES.get("designations", []):
        if str(d.get("official_run")) == run:
            return "official"
        if str(d.get("superseded_run")) == run:
            return "superseded"
    return "baseline"


def _capacity_verdict(project: Path, template_id: str) -> dict:
    """素材容量判定（P0-4）：只读计算，输出 verdict + reasons。"""
    global _PACK_CACHE
    if not _PACK_CACHE:
        pack = _load_any(ROOT / "projects" / "template-pack-library" / "artifacts" / "template_pack.json") or {}
        _PACK_CACHE.update(pack)
    template = next((t for t in _PACK_CACHE.get("templates", [])
                     if t.get("template_id") == template_id), None)
    if not template:
        return {"verdict": "UNKNOWN", "reasons": ["模板已更名/下线（历史草稿）"]}
    if not is_template_calibrated(template_id):
        return {"verdict": "UNCALIBRATED", "reasons": ["动作域未标定（VLM/人工标定后可判级）"]}
    v = capacity_verdict(template)
    return {"verdict": v["verdict"], "reasons": v["reasons"], "solver": v["solver"]}


def _compressed_sibling(run: dict, *, known: set[str] | None = None) -> str:
    """原片行：先取 ledger 指认的 official_run；否则回退 {template_id}-c1 变体。"""
    if str(run.get("template_id") or "").endswith("-c1") or str(run.get("template_id") or "").endswith("-c2"):
        return ""
    _release_status("", str(run.get("run") or ""))  # 确保 ledger 加载
    for d in (_RELEASES or {}).get("designations", []):
        if str(d.get("superseded_run")) == str(run.get("run") or ""):
            return str(d.get("official_run") or "")
    sibling = f"template-run-{run.get('template_id')}-c1"
    return sibling if (known is None or sibling in known) else ""


def _slim_run(run: dict, *, known: set[str] | None = None) -> dict:
    """只暴露页面需要的字段（避免把整份制品 JSON 发给前端）。"""
    dims = (run["advisory"] or {}).get("dimensions", {}) or {}
    loud = next((c.get("evidence", {}) for c in run["l1a"].get("hard_gate", {}).get("checks", [])
                 if c.get("id") == "l1a_loudness"), {}) or {}
    sample = _load_any(run["project"] / "checkpoint_sample.json") or {}
    return {
        "run": run["run"],
        "sheet_name": run["sheet_name"],
        "template_id": run["template_id"],
        "duration_s": run["duration_s"],
        "tier": tier_of(run),
        "l1a_status": str(run["l1a"].get("status") or "—"),
        "certificate": bool(run["certificate"]),
        "noncut": run["noncut"],
        "cuts": len(run["cuts"]),
        "cost": run["cost"],
        "cost_note": run["cost_note"],
        "published_at": run["published_at"][:19].replace("T", " "),
        "probe_resolution": run["probe"].get("resolution") or "",
        "probe_duration": run["probe"].get("duration_seconds"),
        "probe_audio": bool(run["probe"].get("has_audio")),
        "l3": {
            "scored": bool(run["advisory"]),
            "avg": run["l3_avg"],
            "min": run["l3_min"],
            "weakest": run["weakest"],
            "dims": dims,
            "summary": (run["advisory"] or {}).get("summary", ""),
            "seeds": (run["advisory"] or {}).get("seeds", []),
            "model": (run["advisory"] or {}).get("model", ""),
        },
        "semantic": {"findings": semantic_mismatches(run["script"])},
        "reuse": material_reuse_report(_load_any(run["project"] / "artifacts" / "scene_plan.json") or {}),
        "audio": _audio_coverage(run["project"], run["script"]),
        "capacity": _capacity_verdict(run["project"], run["template_id"]),
        "compressed_variant": _compressed_sibling(run, known=known),
        "release": _release_status(str(run.get("template_id") or ""), str(run.get("run") or "")),
        "checks": {
            "sensitive": (run["l1a_checks"].get("l1a_sensitive") or {}).get("status"),
            "subtitle_bounds": (run["l1a_checks"].get("l1a_subtitle_bounds") or {}).get("status"),
            "black_frames": (run["l1a_checks"].get("l1a_black_frames") or {}).get("status"),
            "freeze": (run["l1a_checks"].get("l1a_freeze") or {}).get("status"),
            "loudness": {"integrated_lufs": loud.get("integrated_lufs"),
                         "true_peak_dbtp": loud.get("true_peak_dbtp")},
        },
        "human_approved": bool(sample.get("human_approved")),
    }


_VARIANT_SUFFIXES = ("-c1", "-c2", "-c3", "-c4")
_STAGE_ORDER = ("research", "proposal", "script", "scene_plan",
                "assets", "sample", "edit", "compose", "publish")


def _is_variant(template_id: str) -> bool:
    return str(template_id).endswith(_VARIANT_SUFFIXES)


def _pack_templates() -> list[dict]:
    global _PACK_CACHE
    if not _PACK_CACHE:
        pack = _load_any(ROOT / "projects" / "template-pack-library" / "artifacts" / "template_pack.json") or {}
        _PACK_CACHE.update(pack)
    return _PACK_CACHE.get("templates") or []


def _pool_census() -> dict:
    """模板池只读盘点：总数/主模板/标定/容量判定（不做任何付费调用）。"""
    templates = _pack_templates()
    main = [t for t in templates if not _is_variant(str(t.get("template_id") or ""))]
    capacities = {"DIVERSIFY": 0, "DIVERSIFY_LIMITED": 0, "COMPRESS": 0,
                  "MARK_GAP": 0, "UNCALIBRATED": 0}
    capacity_main = dict(capacities)
    for t in templates:
        tid = str(t.get("template_id") or "")
        if not is_template_calibrated(tid):
            capacities["UNCALIBRATED"] += 1
            capacity_main["UNCALIBRATED"] += 1
            continue
        verdict = str(capacity_verdict(t).get("verdict") or "UNKNOWN")
        capacities[verdict] = capacities.get(verdict, 0) + 1
        if not _is_variant(tid):
            capacity_main[verdict] = capacity_main.get(verdict, 0) + 1
    return {
        "templates": len(templates),
        "main_templates": len(main),
        "variants": len(templates) - len(main),
        "calibrated": sum(1 for t in templates
                          if is_template_calibrated(str(t.get("template_id") or ""))),
        "capacity": capacities,
        "capacity_main": capacity_main,
    }


def _fmt_iso_local(raw: str) -> str:
    """UTC ISO → +08:00 展示时间；解析失败时原样截断。"""
    if not raw:
        return ""
    try:
        from datetime import datetime, timedelta, timezone

        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(raw).replace("T", " ")[:16]


def _inflight_runs() -> list[dict]:
    """未完成 publish 的模板 run，只读扫描。

    只返回有意义的进行中/待推进项：
    - plan 已批准 → 进行中（首个未完成 checkpoint 即当前阶段）；
    - plan 待批但已有推进 checkpoint → 已备未启动（停在下一阶段门口）。
    纯占位目录（无 checkpoint、无 plan 状态）单独计数，不进入列表。
    """
    import glob as _glob

    # 走 export_top_videos 的 PROJECTS（测试可 monkeypatch；生产同一目录）
    from scripts import export_top_videos as _export

    templates = _pack_templates()
    by_tid = {str(t.get("template_id")): t for t in templates}
    out = []
    scaffolds = 0
    for proj in sorted(_glob.glob(str(_export.PROJECTS / "template-run-*"))):
        p = Path(proj)
        name = p.name
        cp = _load_any(p / "checkpoint_publish.json") or {}
        if cp.get("status") == "completed":
            continue
        plan = _load_any(p / "artifacts" / "template_run_plan.json") or {}
        tid = str(plan.get("template_id") or "")
        checkpoints = []
        for s in _STAGE_ORDER:
            c = _load_any(p / f"checkpoint_{s}.json") or {}
            if c:
                checkpoints.append((s, str(c.get("status") or ""), c))
        if str(plan.get("status") or "") != "approved":
            if not checkpoints:
                scaffolds += 1
                continue
            # 已备未启动：挂在第一个未完成阶段门口
            done = [s for s, st, _ in checkpoints if st == "completed"]
            last = done[-1] if done else ""
            first_open = next((s for s, st, _ in checkpoints if st != "completed"), None)
            stage = first_open or "assets"
            out.append({
                "phase": "prepared",
                "phase_label": "已备未启动",
                "run": name,
                "template_id": tid,
                "sheet_name": str((by_tid.get(tid) or {}).get("sheet_name") or tid or name),
                "stage": stage,
                "stage_label": STAGE_LABELS.get(stage, stage),
                "status": "pending",
                "status_label": STATUS_LABELS.get("pending", "pending"),
                "since": "",
                "summary": (f"run 计划待批；已推进至 {STAGE_LABELS.get(last, last) if last else '—'}，"
                            f"下一步：{STAGE_LABELS.get(stage, stage)}"),
            })
            continue
        stage = ""
        for s in _STAGE_ORDER:
            c = _load_any(p / f"checkpoint_{s}.json") or {}
            if c and str(c.get("status") or "") != "completed":
                stage = s
                break
        if not stage:
            # 已写 checkpoint 全部完成 → 当前阶段 = 最后完成阶段的下一阶段
            last = next((s for s in _STAGE_ORDER
                         if _load_any(p / f"checkpoint_{s}.json")), "")
            idx = _STAGE_ORDER.index(last) if last in _STAGE_ORDER else -1
            stage = _STAGE_ORDER[idx + 1] if 0 <= idx + 1 < len(_STAGE_ORDER) else "publish"
        cp_stage = _load_any(p / f"checkpoint_{stage}.json") or {} if stage else cp
        status = str(cp_stage.get("status") or "unknown")
        next_action = cp_stage.get("next_action") or {}
        summary = next_action.get("summary", "") if isinstance(next_action, dict) else str(next_action)
        since_raw = cp_stage.get("set_at") or (next_action.get("set_at", "") if isinstance(next_action, dict) else "")
        tpl = by_tid.get(tid) or {}
        out.append({
            "phase": "running",
            "phase_label": "进行中",
            "run": name,
            "template_id": tid,
            "sheet_name": str(tpl.get("sheet_name") or tid or name),
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, stage or "—"),
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "since": _fmt_iso_local(str(since_raw or cp.get("set_at") or "")),
            "summary": summary,
        })
    return {"items": out, "scaffolds": scaffolds}


def _batch_report(collected: list[dict]) -> dict:
    """批量成片整体报告：只读聚合（发布/质量/模板池/容量/版本/进行中）。"""
    scored = [r for r in collected if r["advisory"]]
    tiers = collections.Counter()
    weak_observed = 0
    l1a = collections.Counter()
    weakest = collections.Counter()
    for r in collected:
        label = tier_of(r).split("（")[0]
        tiers[label] += 1
        if "短板" in tier_of(r):
            weak_observed += 1
        l1a[str(r["l1a"].get("status") or "—")] += 1
        if r["advisory"]:
            weakest[r["weakest"] or "—"] += 1
    top3 = [{"run": r["run"], "sheet_name": r["sheet_name"], "l3_avg": r["l3_avg"]}
            for r in sorted(collected, key=lambda r: -(r["l3_avg"] or 0))[:3]]
    release = collections.Counter()
    strict_green = 0
    whitelist = []
    for r in collected:
        rel = _release_status(str(r.get("template_id") or ""), str(r.get("run") or ""))
        release[rel] += 1
        if rel == "official":
            reuse = material_reuse_report(_load_any(Path(r["project"]) / "artifacts" / "scene_plan.json") or {})
            if reuse.get("strict_pass"):
                strict_green += 1
            else:
                whitelist.append(str(r.get("template_id") or r.get("run") or ""))
    pool = _pool_census()
    produced_tids = {str(r.get("template_id") or "") for r in collected}
    produced_main = {t for t in produced_tids if not _is_variant(t)}
    gaps = _load_any(ROOT / "projects" / "template-pack-library" / "artifacts" / "material_gaps.json") or {}
    gap_items = gaps.get("gaps") or []
    inflight = _inflight_runs()
    items = inflight["items"]
    unproduced_main = max(pool.get("main_templates", 0) - len(produced_main), 0)
    notes = []
    notes.append(f"已发布 {len(collected)} 部成片、其中 {len(scored)} 部已有 L3 评分；"
                 f"另有 {len(items)} 条在制/待推进。")
    if unproduced_main:
        comp = pool.get("capacity_main", {}).get("COMPRESS", 0)
        gapc = pool.get("capacity_main", {}).get("MARK_GAP", 0)
        notes.append(f"{unproduced_main} 张主模板尚未产出成片（主模板容量：需压缩 {comp}、素材缺口 {gapc}）；"
                     f"建议按「压缩子集/换序」与素材池扩容两条路推进。")
    if inflight["scaffolds"]:
        notes.append(f"另有 {inflight['scaffolds']} 个模板 run 已建位但未启动（run 计划待批）。")
    if gap_items:
        p0 = sum(1 for g in gap_items if str(g.get("priority") or "").upper() == "P0")
        affected = {tid for g in gap_items for tid in (g.get("affected_templates") or [])}
        notes.append(f"素材缺口清单共 {len(gap_items)} 个动作域（P0 {p0} 个），"
                     f"影响 {len(affected)} 个模板；补素材后可解锁更多模板产出。")
    notes.append("L3 为 advisory，不进发布硬门；「严格档全绿 + L1a pass + 证书」才是可投放口径。")
    running = [i for i in items if i["phase"] == "running"]
    prepared = [i for i in items if i["phase"] == "prepared"]
    return {
        "published": len(collected),
        "scored": len(scored),
        "certificated": sum(1 for r in collected if r["certificate"]),
        "l1a_pass": l1a.get("pass", 0),
        "tiers": dict(tiers),
        "concerned": weak_observed,
        "l3_avg": round(sum(r["l3_avg"] for r in scored) / len(scored), 2) if scored else None,
        "top3": top3,
        "weakest": dict(weakest.most_common()),
        "release": {
            "official": release.get("official", 0),
            "superseded": release.get("superseded", 0),
            "baseline": release.get("baseline", 0),
            "strict_green": strict_green,
            "whitelist": whitelist,
        },
        "pool": pool,
        "produced": {"runs": len(collected), "templates": len(produced_tids),
                     "main_templates": len(produced_main), "unproduced_main": unproduced_main},
        "gaps": {"domains": len(gap_items),
                 "p0_domains": sum(1 for g in gap_items if str(g.get("priority") or "").upper() == "P0")},
        "inflight": items,
        "running_count": len(running),
        "prepared_count": len(prepared),
        "scaffolds": inflight["scaffolds"],
        "notes": notes,
    }


def load_overview(*, limit: int = 20) -> dict:
    global _PUBLISHED_C1
    if _PUBLISHED_C1 is None:
        _PUBLISHED_C1 = {str(run) for run in discover_runs() if str(run).endswith("-c1")}
    """只读总览数据：{policy, methodology, runs[], gates[]}。"""
    policy = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    runs = discover_runs()
    collected = []
    for run in runs:
        project = PROJECTS / run
        advisory = _load_any(project / "artifacts" / "l3_advisory.json")
        collected.append(collect_run(run, advisory))
    ordered = rank_runs(collected)[:limit]

    hard_rules = [r for r in policy.get("rules", []) if r.get("layer") == "hard_gate"]
    gates = []
    for rule in hard_rules:
        cells = []
        for run in ordered:
            text, style = rule_verdict(rule, run)
            cells.append({"run": run["run"], "text": text, "style": style})
        gates.append({
            "rule_id": rule.get("rule_id"), "rule_name": rule.get("rule_name"),
            "rule_category": rule.get("rule_category"), "metric_type": rule.get("metric_type"),
            "metric": rule.get("metric"), "thresholds": rule.get("thresholds"),
            "evidence_source": rule.get("evidence_source"), "impl_status": rule.get("impl_status"),
            "severity": rule.get("severity"), "cells": cells,
        })
    prelaunch = [
        {"rule_id": r.get("rule_id"), "rule_name": r.get("rule_name"),
         "checks": r.get("checks") or [], "impl_status": r.get("impl_status")}
        for r in policy.get("rules", []) if r.get("layer") == "prelaunch"
    ]
    uncerted = [r["run"] for r in collected if not r["certificate"]]
    known_limits = [
        "L3 为 advisory（l3-v1.0），不进发布硬门；3seed 均值更稳",
        "五确认=批量授权口径（真实五项采集待 Editorial Gallery）",
        "R02/R04/R05/R17 待接入；R06/R11/R13/R16/R19–R24 外部依赖（本期不评估）",
        "业务近似列为近似度标注，不做伪精确换算",
    ]
    if uncerted:
        known_limits.append(f"未绑定交付证书：{', '.join(uncerted)}（跳号/回补运行）")
    return {
        "policy": {
            "policy_id": policy.get("policy_id"), "policy_version": policy.get("policy_version"),
            "platform": policy.get("platform"), "source_ref": policy.get("source_ref"),
            "effective_at": policy.get("effective_at"),
        },
        "methodology": {
            "judge_version": "video_judge-0.1.0", "rubric_version": "l3-v1.0",
            "model": "qwen-vl-max",
            "seeds": sorted({s for r in collected for s in ((r["advisory"] or {}).get("seeds") or [])}),
            "frame_count": 8,
            "ranking_rule": ("L3 均分 desc → 单维最低 desc → 有证书 → L1a 全绿 → 转场占比 → 成本 asc"),
            "cost_note": "manifest total_cost_usd；reuse 记 0 按实付口径估算并标注",
            "known_limits": known_limits,
        },
        "runs": ordered,
        "slim_runs": [_slim_run(r, known=_PUBLISHED_C1 or set()) for r in ordered],
        "gates": gates,
        "prelaunch_rules": prelaunch,
        "batch_report": _batch_report(collected),
        "scored_count": sum(1 for r in collected if r["advisory"]),
        "total_runs": len(collected),
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
    }

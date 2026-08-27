"""历史成片总览：只读聚合（无付费、无评分执行；L3 分数仅读制品）。

复用 scripts.export_top_videos 的发现/收集/判定/排名逻辑（同一代码路径），
但**永不调用 video_judge**——L3 分数只读 artifacts/l3_advisory.json；
缺失时标记「未评分」，页面上提示由 export 脚本补分。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import yaml

from scripts.export_top_videos import (
    DEFAULT_POLICY,
    PROJECTS,
    collect_run,
    discover_runs,
    rank_runs,
    rule_verdict,
    tier_of,
)
from lib.template_source_match import (capacity_verdict, material_reuse_report,
                          semantic_mismatches)
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


def _capacity_verdict(project: Path, template_id: str) -> dict:
    """素材容量判定（P0-4）：只读计算，输出 verdict + reasons。"""
    global _PACK_CACHE
    if not _PACK_CACHE:
        pack = _load_any(ROOT / "projects" / "template-pack-library" / "artifacts" / "template_pack.json") or {}
        _PACK_CACHE.update(pack)
    template = next((t for t in _PACK_CACHE.get("templates", [])
                     if t.get("template_id") == template_id), None)
    if not template:
        return {"verdict": "UNKNOWN", "reasons": ["模板不在库中"]}
    v = capacity_verdict(template)
    return {"verdict": v["verdict"], "reasons": v["reasons"], "solver": v["solver"]}


def _slim_run(run: dict) -> dict:
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


def load_overview(*, limit: int = 10) -> dict:
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
            "known_limits": [
                "L3 为 advisory（l3-v1.0），不进发布硬门；3seed 均值更稳",
                "sheet-01/04 无交付证书且为探索期链路产物",
                "五确认=批量授权口径（真实五项采集待 Editorial Gallery）",
                "R02/R04/R05/R17 待接入；R06/R11/R13/R16/R19–R24 外部依赖（本期不评估）",
                "业务近似列为近似度标注，不做伪精确换算",
            ],
        },
        "runs": ordered,
        "slim_runs": [_slim_run(r) for r in ordered],
        "gates": gates,
        "prelaunch_rules": prelaunch,
        "scored_count": sum(1 for r in collected if r["advisory"]),
        "total_runs": len(collected),
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
    }

"""素材缺口账单（设计 §5 / 附录 A2-A3）：从 capacity_verdict + 窗口容量生成全景账单。

缺口头（CAP）字段带 capacity_basis（证据窗口/时长/步长/间隔），供业务按依据补素材；
账单落 `projects/template-pack-library/artifacts/material_gaps.json`，由 overview 展示。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from lib.template_source_match import capacity_verdict, window_capacity

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "projects" / "template-pack-library"
PACK_ARTIFACTS = PACK_DIR / "artifacts"
POLICY_REF = "docs/rules/business-policy.yaml"

_SUGGESTED = {
    "餐桌场景": [{"scene": "家庭餐桌近景·食物", "duration_s": 6, "framing": "近景"},
                 {"scene": "全景·家人入座", "duration_s": 6, "framing": "全景"}],
    "无甲醛检测": [{"scene": "检测仪读数特写", "duration_s": 6, "framing": "特写"},
                   {"scene": "边测边铺桌垫", "duration_s": 6, "framing": "中景"}],
    "桌角对齐-挤压不变形": [{"scene": "桌面下缘贴合特写", "duration_s": 5, "framing": "特写"},
                          {"scene": "挤压复原连拍", "duration_s": 5, "framing": "中景"}],
    "防刮": [{"scene": "金属刮擦特写", "duration_s": 5, "framing": "特写"},
             {"scene": "硬刷擦拭视角", "duration_s": 5, "framing": "中景"}],
    "防油易擦拭": [{"scene": "大面积污染演示", "duration_s": 6, "framing": "中景"},
                   {"scene": "单滴油污特写", "duration_s": 6, "framing": "特写"}],
    "自动铺开对齐": [{"scene": "俯拍自动铺开", "duration_s": 5, "framing": "俯拍"},
                    {"scene": "侧视张力对齐", "duration_s": 5, "framing": "侧视"}],
}


def build_document(pack: dict | None = None, *, policy_path: Path | None = None) -> dict:
    pack = pack or json.loads((PACK_ARTIFACTS / "template_pack.json").read_text(encoding="utf-8"))
    policy = Path(policy_path or ROOT / POLICY_REF)
    verdicts = []
    for template in pack.get("templates", []):
        v = capacity_verdict(template)
        verdicts.append((template, v))
    # 评审 P1-8：capacity_shots 使用每域**规范容量**（window_capacity 一次计算，所有模板同口径）；
    # needed 与 deficit 按模板逐项求和，并保留 per_template 明细（避免混合口径）。
    gaps: dict[str, dict] = {}
    for template, v in verdicts:
        for domain, deficit in v["deficits"].items():
            if deficit <= 0:
                continue
            tid = str(template.get("template_id") or "")
            entry = gaps.setdefault(domain, {
                "domain": domain, "affected_templates": [],
                "needed_shots": 0,
                "capacity_shots": window_capacity(domain, 2.0)["capacity"],
                "deficit": 0,
                "capacity_basis": window_capacity(domain, 2.0)["basis"],
                "suggested_shots": _SUGGESTED.get(domain, []),
                "priority": "P0", "per_template": [],
            })
            entry["affected_templates"].append(tid)
            entry["needed_shots"] += v["domain_counts"].get(domain, 0)
            entry["deficit"] += deficit
            entry["per_template"].append({"template_id": tid,
                                          "needed": v["domain_counts"].get(domain, 0),
                                          "deficit": deficit})
    return {
        "version": "1.1",
        "policy_ref": {"path": POLICY_REF,
                       "sha256": hashlib.sha256(policy.read_bytes()).hexdigest()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gaps": sorted(gaps.values(), key=lambda g: -g["deficit"]),
    }


def write_document(project: Path = PACK_DIR, *, sink=None) -> dict:
    """评审 P1-8：project 默认 = 模板库根（relative path 落 artifacts/ 不再双层嵌套）。"""
    from lib.artifact_io import write_artifact_atomic

    doc = build_document()
    return write_artifact_atomic("artifacts/material_gaps.json", "material_gaps", doc,
                                 project_dir=project, sink=sink)

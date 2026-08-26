"""人工门 + A/B 对比工具：新成片 vs 旧成片（batch-002），8 维逐项记录 + 汇总。

覆盖你 review 的 4 个问题（钩子/故事/花字/转场）+ 人工门基础 5 维（创意方向/钩子/
证明/节奏/可读性）。每维给 ``new``（pass/adjust/redirect）与 ``vs_old``（better/equal/worse）。
技术/效率提升看 evaluation_report/batch_quality_report 硬指标；创意提升靠本工具的人判断。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact

# (dim, label, 对应问题)
HUMAN_AB_DIMS: tuple[tuple[str, str, str], ...] = (
    ("creative_direction", "创意方向", "整体方向/表达"),
    ("hook", "钩子", "钩子"),
    ("proof", "证明", "核心证明是否成立"),
    ("pacing", "节奏", "节奏"),
    ("readability", "可读性", "画面与字幕可读"),
    ("story_structure", "故事结构", "故事/叙事结构"),
    ("caption_huazi", "花字效果", "花字/字幕效果"),
    ("transition_rhythm", "转场节奏", "转场/镜头切换"),
)


def build_human_ab_template(
    old_label: str, new_label: str, *, old_path: str | None = None, new_path: str | None = None
) -> dict[str, Any]:
    """生成待填写的 A/B 记录模板（dims 的 new/vs_old 待人工填写）。"""
    return {
        "version": "1.0",
        "project_id": "human-ab",
        "comparison": {
            "old_label": old_label, "old_path": old_path,
            "new_label": new_label, "new_path": new_path,
        },
        "dims": [
            {"dim": dim, "label": label, "new": None, "vs_old": None, "note": None}
            for dim, label, _ in HUMAN_AB_DIMS
        ],
        "overall": None,
        "issue_tags": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def record_human_ab(review: dict[str, Any], project_dir: str | Path) -> dict[str, Any]:
    """校验 + 落盘一条 A/B review，返回 sealed artifact。"""
    # 模板里的 dims 需填齐 new/vs_old 才可校验
    for d in review.get("dims") or []:
        if d.get("new") is None or d.get("vs_old") is None:
            raise ValueError(f"dim {d.get('dim')} 需填写 new 与 vs_old")
    sealed = attach_hashes(dict(review))
    validate_artifact("human_ab_review", sealed)
    project_dir = Path(project_dir)
    (project_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    from lib.artifact_io import write_artifact_atomic

    write_artifact_atomic("artifacts/human_ab_review.json", "human_ab_review", sealed, project_dir=project_dir)
    return sealed


def summarize_human_ab(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总多条 A/B review：每维 better/equal/worse + new pass/adjust/redirect 计数与 overall。"""
    summary: dict[str, Any] = {"total": len(reviews), "dims": {}, "overall": {"new_better": 0, "comparable": 0, "new_worse": 0}}
    for review in reviews:
        if review.get("overall"):
            summary["overall"][str(review["overall"])] += 1
        for d in review.get("dims") or []:
            dim = str(d.get("dim") or "")
            row = summary["dims"].setdefault(dim, {"better": 0, "equal": 0, "worse": 0, "pass": 0, "adjust": 0, "redirect": 0})
            row[str(d.get("vs_old") or "")] = row.get(str(d.get("vs_old") or ""), 0) + 1
            row[str(d.get("new") or "")] = row.get(str(d.get("new") or ""), 0) + 1
    return summary


def print_summary(reviews: list[dict[str, Any]]) -> str:
    s = summarize_human_ab(reviews)
    lines = [f"Human A/B 汇总（{s['total']} 条）："]
    for dim, label, _ in HUMAN_AB_DIMS:
        row = s["dims"].get(dim, {})
        lines.append(f"  {label}: vs_old 更好{row.get('better',0)}/持平{row.get('equal',0)}/更差{row.get('worse',0)}；new 通过{row.get('pass',0)}/调{row.get('adjust',0)}/改{row.get('redirect',0)}")
    lines.append(f"  整体：新更好 {s['overall']['new_better']} / 持平 {s['overall']['comparable']} / 更差 {s['overall']['new_worse']}")
    return "\n".join(lines)

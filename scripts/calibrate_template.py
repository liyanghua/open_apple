"""模板动作域标定流水线（策略 C：未标定=阻断，标定后解锁）。

用法：
  python -m scripts.calibrate_template --template sheet-02-video2-aks-zhuodian            # 生成标定工作单
  python -m scripts.calibrate_template --template … --apply 确认.csv                      # 应用（VLM 自动或人工确认）
  python -m scripts.calibrate_template --list                                             # 未标定清单 + 优先级提示

产出：
  - projects/template-pack-library/artifacts/calibration_workitems/<tid>.json（标定工作单：
    slot 清单 + 关键词初筛建议 + 6 域选项 + 每槽确认）
  - --apply 后：写入 lib/template_calibrations.py（_CALIBRATIONS + _CALIBRATION_META 增量）
    ——合并后即"标定"，readiness 解锁，容量判级转显式表。
Modes：
  - manual：对工作单逐槽填 [动作域, 置信度, 备注]，--apply 采用人工结果（来源=manual）；
  - vlm：TODO（VLM 语义匹配器投产位；当前以关键词初筛 + 人工复核替代）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
ROOT = Path(__file__).resolve().parents[1]

DOMAINS = ["防油易擦拭", "防刮", "无甲醛检测", "桌角对齐-挤压不变形", "自动铺开对齐", "餐桌场景"]
PACK_ARTIFACTS = ROOT / "projects/template-pack-library/artifacts"
CAL_FILE = ROOT / "lib/template_calibrations.py"


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_workitem(template_id: str) -> dict:
    import json

    pack = json.loads((ROOT / "projects/template-pack-library/artifacts/template_pack.json").read_text())
    t = next((x for x in pack["templates"] if x["template_id"] == template_id), None)
    if t is None:
        raise SystemExit(f"模板不存在: {template_id}")
    from lib.template_source_match import _best_action

    slots = []
    for s in t.get("slots") or []:
        hint = _best_action(s)
        slots.append({"slot_id": s.get("slot_id"), "ordinal": s.get("ordinal"),
                      "scene": str(s.get("scene") or "")[:24],
                      "dialogue": str(s.get("dialogue") or "")[:36],
                      "overlay_text": str(s.get("overlay_text") or "")[:20],
                      "keyword_hint": hint,
                      "confirmed_action": None, "confidence": None, "note": ""})
    return {"template_id": template_id, "slots": slots, "domains": DOMAINS,
            "mode": "manual", "reviewer": "", "calibrated_at": None}


def apply_workitem(workitem: dict) -> None:
    import datetime

    tid = workitem["template_id"]
    acts = [s["confirmed_action"] for s in workitem["slots"]]
    if not all(acts):
        raise SystemExit(f"{tid}: 存在未确认的槽位（confirmed_action 全填才能 apply）")
    unknown = [a for a in acts if a and a not in DOMAINS]
    if unknown:
        raise SystemExit(f"{tid}: 动作域不在规范内: {unknown[:3]}")
    meta = {"source": workitem.get("mode") or "manual", "version": "1.0",
            "calibrated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()[:19],
            "reviewer": workitem.get("reviewer") or "agent"}
    src = CAL_FILE.read_text(encoding="utf-8")
    import ast
    ns = {}
    exec(src, ns)
    cal = dict(ns["_CALIBRATIONS"])
    cal[tid] = acts
    block = "\n".join(f'    {tid!r}: {acts!r},' for tid, acts in cal.items())
    meta_block = "\n".join(f'    {k!r}: {v!r},' for k, v in dict(ns["_CALIBRATION_META"], **{tid: meta}).items())
    CAL_FILE.write_text(
        '"""模板动作域标定产物（策略 C：未标定=阻断）。\n\n'
        '由 scripts/calibrate_template.py 生成/维护：\n'
        '- `_CALIBRATIONS`：{template_id: [每 slot 动作域]}（合并后即"标定"）；\n'
        '- `_CALIBRATION_META`：审计元数据（source/version/calibrated_at/reviewer）。\n'
        '"""\nfrom __future__ import annotations\n\n\n'
        f'_CALIBRATIONS: dict[str, list[str]] = {{\n{block}\n}}\n\n'
        f'_CALIBRATION_META: dict[str, dict] = {{\n{meta_block}\n}}\n', encoding="utf-8")
    ast.parse(CAL_FILE.read_text(encoding="utf-8"))
    print(f"已标定并写入 {tid}（{len(acts)} 槽）→ readiness 解锁")


def main() -> None:
    import json

    p = argparse.ArgumentParser()
    p.add_argument("--template")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    if args.list:
        from lib.template_source_match import is_template_calibrated

        pack = json.loads((ROOT / "projects/template-pack-library/artifacts/template_pack.json").read_text())
        uncal = [t["template_id"] for t in pack["templates"]
                 if not is_template_calibrated(t["template_id"]) and not str(t.get("template_id") or "").endswith("-c1")]
        print(f"未标定模板数: {len(uncal)}")
        for tid in uncal[:20]:
            print("  ", tid)
        return
    if not args.template:
        raise SystemExit("--template 必填（或 --list）")
    out = PACK_ARTIFACTS / "calibration_workitems"
    out.mkdir(parents=True, exist_ok=True)
    wpath = out / f"{args.template}.json"
    if not args.apply:
        wi = build_workitem(args.template)
        wpath.write_text(json.dumps(wi, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"工作单已生成: {wpath}\n请逐槽填写 confirmed_action（选项: {DOMAINS}），然后 --apply")
        return
    wi = _load(wpath) or {}
    apply_workitem(wi)


if __name__ == "__main__":
    main()

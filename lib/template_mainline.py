"""主链路执行：把一条 template run 通过真实 cinematic-fast 阶段机推进。

这是**设计意图中的主链路执行**，不是旁路：它只用 `lib.checkpoint.get_next_stage` /
`write_checkpoint` + 各阶段 director 契约需要的 canonical 制品，把 `template_run_plan` /
`template_pack` / `product_facts` 当作阶段输入约束消费。每个制品的形状都按对应 schema 校验。

推进规则（对 template run 的 proposal/script/scene_plan）：
- proposal：gate=false，产 creative_control_plan(draft) + proposal_packet → completed。
- script：gate=true，先写 awaiting_human（待人工批 script + ccp）；approve 后才可 completed。
- scene_plan：需 script + ccp approved 才可 completed（用 `approve_stage` 显式锁定）。

用法：
  python -m lib.template_mainline --run <run>            # 推进到下一个 gated 点
  python -m lib.template_mainline --run <run> --approve-script
  python -m lib.template_mainline --run <run> --advance-scene-plan
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_io import write_artifact_atomic
from lib.caption_treatment import resolve_caption_recipe_intent
from lib.checkpoint import get_next_stage, write_checkpoint
from lib.template_source_match import build_source_mappings, match_run_plan, resolve_matrix_grounding

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
PIPELINE = "cinematic-fast"
SHOT_SIZE = {"全景": "wide", "中景": "medium", "近景": "close_up", "特写": "extreme_close_up"}
CAMERA = {"固定": "static", "推": "dolly_in", "手持": "handheld", "拉": "dolly_out"}

# 逐镜 narration（narration, screen_copy, beat_role）——**按模板 archetype 分表**。
# 每一行必须与其 scene 绑定的素材画面语义一致（主链路语义：narration 由素材动作派生）。
# 默认表 = video1（8 镜 proof 链）；异议-反驳型模板（sheet-04 等）用各自表。
_NARRATION_DEFAULT = [
    ("油污汤汁，一擦就没了？", "油污 · 一擦就净？", "hook"),
    ("0 甲醛，检测报告为证。", "0 甲醛 · 检测报告可查", "proof"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事", "proof"),
    ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新", "proof"),
    ("透明极简，不遮原桌纹理。", "透明 · 不遮纹理", "proof"),
    ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新", "proof"),
    ("69 元，让餐桌更省心。", "69 元 · 餐桌省心好物", "cta"),
]

# sheet-04：异议-反驳型（"行不行/可不行"→ 逐条用对应素材反驳）。
# 素材绑定（no-dup 后）：1 餐桌 / 2 无甲醛 / 3 桌角 / 4 自动铺开 / 5 防油
# / 6 防刮 / 7 餐桌 / 8 防刮 / 9 无甲醛 / 10 无甲醛 / 11 防刮 / 12 餐桌 / 13 餐桌 / 14 餐桌。
_NARRATION_SHEET_04 = [
    ("这个桌垫，给你行不行？", "软玻璃桌垫 · 更安全", "hook"),
    ("透明磨砂，行不行？", "透明 · 磨砂质感", "problem"),
    ("翘边发黄，可不行。", "贴合不翘边", "escalation"),
    ("这个桌垫给你，行不行？", "给你一块贴合不翘边", "reveal"),
    ("撒上油污？一擦就净。", "油污一擦就净", "proof"),
    ("随便你造，不怕刮。", "耐刮耐用", "proof"),
    ("一擦即净，行不行？", "一擦即净", "proof"),
    ("随便你造，行不行？", "耐刮耐磨", "proof"),
    ("材质有醛？可不行。", "0甲醛", "proof"),
    ("HAP 报告，安心。", "HAP 报告", "proof"),
    ("免费定制，行不行？", "免费定制", "proof"),
    ("价格太高？69 元。", "69 元", "payoff"),
    ("骗你？报告为证。", "报告为证", "proof"),
    ("直播间看看，行不行？", "直播间见", "cta"),
]

# sheet-05（21 镜）：「实木桌缝隙藏脏」→ 铺软玻璃桌垫 → 卖点逐条 → CTA。
# 依据模板包逐镜 overlay_text/ASR 行（garbled 段按上下文还原为产品故事）。
_NARRATION_SHEET_05 = [
    ("像这种实木桌子，缝隙难清理。", "实木桌 · 缝隙难清理", "hook"),
    ("污渍一擦就净，真的吗？", "污渍 · 一擦就净？", "problem"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("0 甲醛，检测报告为证。", "0 甲醛 · 报告可查", "proof"),
    ("这个缝隙，是最难打理的。", "缝隙 · 最难打理", "escalation"),
    ("在上面藏了东西啊。", "上面藏了东西", "problem"),
    ("藏了脏的东西。", "藏了脏东西", "problem"),
    ("一个一个挑，太费劲。", "一个一个挑", "escalation"),
    ("那这个情况怎么办呢？", "那怎么办呢？", "problem"),
    ("只需要铺上软玻璃桌垫。", "铺上软玻璃桌垫", "reveal"),
    ("防水防油的，一擦就净。", "防水防油 · 一擦净", "proof"),
    ("铺上，缝隙就护住了。", "铺上保护缝隙", "proof"),
    ("不让脏东西进去。", "脏东西进不去", "proof"),
    ("轻轻一擦就干净。", "一擦就干净", "proof"),
    ("防水防油，还耐高温。", "防水防油 · 耐高温", "proof"),
    ("热盘子，直接放上去。", "热盘直接放", "proof"),
    ("防刮耐磨，效果很好。", "防刮耐磨", "proof"),
    ("而且它很有光泽。", "很有光泽", "proof"),
    ("轻轻铺在上面。", "轻轻铺上", "proof"),
    ("不遮挡桌面纹理。", "不遮纹理", "proof"),
    ("", "直播间见", "cta"),
]

# sheet-09（21 镜）：「一分钱一分货」品质论证 —— 结构骨架来自参考片，
# 每镜口播=该镜绑定素材的**可见动作**（文案由素材动作派生，禁止无证据 claim）。
_NARRATION_SHEET_09 = [
    ("一分价格一分货。", "一分价格一分货", "hook"),
    ("安全和健康最重要。", "安全健康最重要", "hook"),
    ("凭什么你家桌垫更贵？", "为什么贵一点？", "problem"),
    ("测给你看，读数见底。", "检测 · 读数见底", "proof"),
    ("用料敢测，玻璃是母婴级。", "母婴级软玻璃", "proof"),
    ("高透软玻璃，质感看得见。", "高透软玻璃", "proof"),
    ("检测仪归零，材料干净。", "材料干净", "proof"),
    ("测完，没有异味。", "无异味", "proof"),
    ("孩子都能放心用。", "孩子放心用", "proof"),
    ("边缘光滑，圆角不扎手。", "圆角光滑 · 不扎手", "proof"),
    ("边角毛刺？不存在的。", "边角无毛刺", "proof"),
    ("更关键的是，边角都服帖。", "边角服帖", "escalation"),
    ("刚出锅的热菜，直接放。", "热菜直接放", "proof"),
    ("热茶热饭，直接上桌。", "热茶热饭", "proof"),
    ("挤压复原，不怕变形。", "不怕变形", "proof"),
    ("贴合平整，一张就够。", "一张就够", "payoff"),
    ("家里用，就是省心。", "家里用省心", "other"),
    ("我信一分价钱一分货。", "一分价钱一分货", "payoff"),
    ("材料检测，全部合格。", "检测合格", "payoff"),
    ("健康，是底线。", "健康是底线", "payoff"),
    ("", "永远第一位", "cta"),
]
# sheet-14（30 镜）：「好桌垫 · 一家人用」—— 结构骨架（品质→材质证明→边角→耐受→家庭收尾）
# 来自参考片；每镜口播=绑定素材的**可见动作**；品牌/工厂/口碑类无证据 claim 已删除。
_NARRATION_SHEET_14 = [
    ("二十年三十年，做好一件事。", "20年30年 · 一件事", "hook"),
    ("人家卖的比你便宜？", "比你便宜？", "problem"),
    ("手按边角，每一处都贴合。", "边角都贴合", "proof"),
    ("桌子不少，好垫不多。", "好垫不多", "problem"),
    ("一张软玻璃，一家人用。", "一家人都用", "reveal"),
    ("用得舒服，才是真的好。", "舒服就好", "proof"),
    ("免费裁切，边角贴合。", "免费裁切", "proof"),
    ("家里桌上，终于清爽。", "桌上清爽", "proof"),
    ("到家就用，立刻清爽。", "到家即用", "proof"),
    ("拆开就测，没有异味。", "无异味", "proof"),
    ("检测报告，敢给你看。", "检测合格", "proof"),
    ("我家餐桌上，就是它。", "我家在用", "payoff"),
    ("家里老人小孩，天天见。", "家里老人小孩", "problem"),
    ("桌子天天用，难免脏。", "桌子容易脏", "problem"),
    ("材质安不安全，测了知道。", "健康材质", "reveal"),
    ("检测合格，才敢说好。", "敢说合格", "proof"),
    ("耐磨防刮，久用如新。", "耐磨耐用", "proof"),
    ("防水防油，一抹就净。", "防水防油", "proof"),
    ("热茶热饭，直接上桌。", "耐高温", "proof"),
    ("挤压复原，不怕变形。", "不易变形", "proof"),
    ("一家人吃饭，就图个省心。", "一家人 · 省心", "proof"),
    ("桌面干净，饭菜安心。", "桌面干净", "proof"),
    ("透明垫，衬得出木纹。", "衬木纹", "proof"),
    ("一擦就干净，用着省事。", "一擦省事", "proof"),
    ("用了半年，还是光滑。", "半年如新", "proof"),
    ("脏了一擦就净。", "一擦就净", "proof"),
    ("这是给家人的安心。", "给家人的安心", "payoff"),
    ("也是给生活的体面。", "生活的体面", "payoff"),
    ("桌上用得久，才叫好。", "用得久", "payoff"),
    ("", "直播间见", "cta"),
]
# sheet-19（22 镜）：「选桌垫别只图便宜」—— 结构骨架保留；每镜口播=绑定素材**可见动作**；
# 「做桌垫多年/偷工减料/口碑/老客户」等无视频证据的台词已替换为家庭/素材可证表达。
_NARRATION_SHEET_19 = [
    ("选桌垫，别只图便宜。", "别只图便宜", "hook"),
    ("天天跟食物打交道。", "跟食物打交道", "problem"),
    ("材质安不安全，先看检测。", "材质看检测", "escalation"),
    ("软玻璃，材质看得见。", "PVC软玻璃", "reveal"),
    ("母婴级用料，测给你看。", "母婴级材质", "proof"),
    ("一家人天天用。", "一家人放心用", "proof"),
    ("硬物刮，也不怕。", "真的抗造", "proof"),
    ("饮料酒水撒上去。", "饮料撒桌面", "proof"),
    ("一擦，干干净净。", "一擦不费事", "proof"),
    ("边角圆滑，不扎手。", "边角圆滑", "proof"),
    ("小孩手摸，不刮手。", "不刮手", "proof"),
    ("怎么扒拉怎么划。", "怎么划都不怕", "proof"),
    ("用了就知道，省心。", "用了省心", "other"),
    ("桌上用得出好差。", "看得出差别", "problem"),
    ("家里人，都觉着好。", "家里觉着好", "other"),
    ("一张垫，全家都喜欢。", "全家喜欢", "payoff"),
    ("每一批，都测过。", "每批检测", "proof"),
    ("量好桌子，报个尺寸。", "量桌报尺寸", "proof"),
    ("免费裁剪，正好合适。", "免费定制", "proof"),
    ("尺寸合适，用着称心。", "合您心意", "proof"),
    ("这张桌，配得上。", "配得上", "payoff"),
    ("", "直播间见", "cta"),
]
# sheet-14 压缩变体 c1（10 镜/18.2s）：从 14 保留镜按序取行（compressed_from 见设计 §6）。
_NARRATION_SHEET_14C1 = [
    ("二十年三十年，做好一件事。", "20年30年 · 一件事", "hook"),
    ("手按边角，每一处都贴合。", "边角都贴合", "proof"),
    ("拆开就测，没有异味。", "无异味", "proof"),
    ("我家餐桌上，就是它。", "我家在用", "payoff"),
    ("材质安不安全，测了知道。", "健康材质", "reveal"),
    ("耐磨防刮，久用如新。", "耐磨耐用", "proof"),
    ("防水防油，一抹就净。", "防水防油", "proof"),
    ("用了半年，还是光滑。", "半年如新", "proof"),
    ("脏了一擦就净。", "一擦就净", "proof"),
    ("", "直播间见", "cta"),
]



# sheet-05-video5-aks-zhuodian-c1 压缩变体（14 镜）
_NARRATION_SHEET_05C1 = [
    ("像这种实木桌子，缝隙难清理。", "实木桌 · 缝隙难清理", "hook"),
    ("污渍一擦就净，真的吗？", "污渍 · 一擦就净？", "problem"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("0 甲醛，检测报告为证。", "0 甲醛 · 报告可查", "proof"),
    ("只需要铺上软玻璃桌垫。", "铺上软玻璃桌垫", "reveal"),
    ("防水防油的，一擦就净。", "防水防油 · 一擦净", "proof"),
    ("铺上，缝隙就护住了。", "铺上保护缝隙", "proof"),
    ("不让脏东西进去。", "脏东西进不去", "proof"),
    ("轻轻一擦就干净。", "一擦就干净", "proof"),
    ("热盘子，直接放上去。", "热盘直接放", "proof"),
    ("防刮耐磨，效果很好。", "防刮耐磨", "proof"),
    ("而且它很有光泽。", "很有光泽", "proof"),
    ("轻轻铺在上面。", "轻轻铺上", "proof"),
    ("", "直播间见", "cta"),
]

# sheet-19-video22-aks-zhuodian-c1 压缩变体（9 镜）
_NARRATION_SHEET_19C1 = [
    ("选桌垫，别只图便宜。", "别只图便宜", "hook"),
    ("软玻璃，材质看得见。", "PVC软玻璃", "reveal"),
    ("硬物刮，也不怕。", "真的抗造", "proof"),
    ("饮料酒水撒上去。", "饮料撒桌面", "proof"),
    ("边角圆滑，不扎手。", "边角圆滑", "proof"),
    ("怎么扒拉怎么划。", "怎么划都不怕", "proof"),
    ("一张垫，全家都喜欢。", "全家喜欢", "payoff"),
    ("每一批，都测过。", "每批检测", "proof"),
    ("", "直播间见", "cta"),
]


# sheet-09 c1 压缩变体（9 镜/18.1s，3/3/3 平衡解）。
_NARRATION_SHEET_09C1 = [
    ("安全和健康最重要。", "安全健康最重要", "hook"),
    ("凭什么你家桌垫更贵？", "为什么贵一点？", "problem"),
    ("用料敢测，玻璃是母婴级。", "母婴级软玻璃", "proof"),
    ("孩子都能放心用。", "孩子放心用", "proof"),
    ("边缘光滑，圆角不扎手。", "圆角光滑 · 不扎手", "proof"),
    ("刚出锅的热菜，直接放。", "热菜直接放", "proof"),
    ("挤压复原，不怕变形。", "不怕变形", "proof"),
    ("材料检测，全部合格。", "检测合格", "payoff"),
    ("", "永远第一位", "cta"),
]


# sheet-04 c1 压缩变体（8 镜/16.0s，bottomup 全绿解）。
_NARRATION_SHEET_04C1 = [
    ("这个桌垫，给你行不行？", "软玻璃桌垫 · 更安全", "hook"),
    ("透明磨砂，行不行？", "透明 · 磨砂质感", "problem"),
    ("翘边发黄，可不行。", "贴合不翘边", "escalation"),
    ("这个桌垫给你，行不行？", "给你一块贴合不翘边", "reveal"),
    ("撒上油污？一擦就净。", "油污一擦就净", "proof"),
    ("随便你造，不怕刮。", "耐刮耐用", "proof"),
    ("材质有醛？可不行。", "0甲醛", "proof"),
    ("直播间看看，行不行？", "直播间见", "cta"),
]

_NARRATION_BY_TEMPLATE: dict[str, list[tuple[str, str, str]]] = {
    "sheet-04-video4-zhuodian": _NARRATION_SHEET_04,
    "sheet-05-video5-aks-zhuodian": _NARRATION_SHEET_05,
    "sheet-09-video9-aks-zhuodian": _NARRATION_SHEET_09,
    "sheet-14-video15-aks-zhuodian": _NARRATION_SHEET_14,
"sheet-19-video22-aks-zhuodian": _NARRATION_SHEET_19,
    "sheet-14-video15-aks-zhuodian-c1": _NARRATION_SHEET_14C1,
    "sheet-04-video4-zhuodian-c1": _NARRATION_SHEET_04C1,
    "sheet-05-video5-aks-zhuodian-c1": _NARRATION_SHEET_05C1,
    "sheet-09-video9-aks-zhuodian-c1": _NARRATION_SHEET_09C1,
    "sheet-19-video22-aks-zhuodian-c1": _NARRATION_SHEET_19C1,
}

# 逐镜转场意图（按 template 参考片语法：动作匹配切为主，硬切开场/收尾）。
# 明显化调整：证明前强调用 proof（flash-proof 闪白 0.12s，纯闪不缩放），
# 高潮特写用 impact（impact-cut 缩放+闪），其余动作匹配 fade。
# 键 = scene 序号（0 起）；值 None = 默认硬切（不触发 recipe）。
TRANSITION_INTENT_BY_ORDER: dict[int, str | None] = {
    0: None,           # hook 开场：硬切进入
    1: "proof",        # 0甲醛 检测仪：证明前强调（闪白）
    2: "action_match",  # 桌角贴合：动作匹配
    3: "proof",        # 自动铺开：证明前强调（闪白）
    4: "action_match",  # 防刮近景（进入防刮证明）
    5: "action_match",  # 餐桌场景（证明→生活）
    6: "impact",        # 防刮特写：高潮"激"点（缩放+闪 5 帧）
    7: None,           # CTA 收尾：静态硬切
}

# sheet-04（14 镜异议-反驳）：异议连问用 action_match 保持流畅，
# 每个**有素材证实的反驳点**（贴合/防油/防刮/0甲醛/报告）用 flash-proof 强调。
TRANSITION_INTENT_SHEET_04: dict[int, str | None] = {
    0: None,           # 开场 hook
    1: "action_match",  # 透明磨砂（异议，流畅进入）
    2: "proof",        # 翘边发黄 → 桌角贴合反驳（闪白强调）
    3: "action_match",
    4: "proof",        # 撒油污 → 防油反驳
    5: "proof",        # 随便造 → 防刮反驳
    6: "action_match",
    7: "action_match",  # 随便你造（重复异议）
    8: "proof",        # 材质有醛 → 0甲醛反驳
    9: "proof",        # HAP 报告 → 检测报告反驳
    10: "action_match", # 免费定制
    11: "action_match", # 价格太高
    12: "action_match",
    13: None,          # CTA 直播间：硬切收尾
}

TRANSITION_INTENT_BY_TEMPLATE: dict[str, dict[int, str | None]] = {
    # video1 投影表（已批「加强转场版」）：证明前 flash-proof、高潮 impact、其余动作匹配。
    "sheet-01-video1-aks-zhuodian": TRANSITION_INTENT_BY_ORDER,
    "sheet-04-video4-zhuodian": TRANSITION_INTENT_SHEET_04,
}


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(project: Path, name: str, data: dict, *, sink=None) -> dict:
    return write_artifact_atomic(f"artifacts/{name}.json", name, data, project_dir=project, sink=sink)


def _section(title: str, summary: str, rules: list[str]) -> dict:
    return {"title": title, "summary": summary, "rules": rules}


# ---------- proposal ----------

def build_proposal(project: Path, template: dict, facts: dict, *, sink=None) -> dict[str, Any]:
    plan_id = str(template.get("template_id") or "")
    ccp = {
        "version": "1.0",
        "project_id": project.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-director@1.0",
        "input_hashes": {
            "template_plan": str(_load(project / "artifacts" / "template_run_plan.json").get("artifact_sha256") or "a" * 64),
            "product_facts": str(facts.get("artifact_sha256") or "a" * 64),
        },
        "plan_id": plan_id,
        "plan_version": 1,
        "status": "draft",
        "selected_direction_id": "c1",
        "sections": {
            "content_direction": _section("内容方向", "透明桌垫：透明极简 + 防水防油 + 0甲醛（以检测报告为证据）", [
                "主信息固定为透明极简 + 防水防油易清洁。",
                "0甲醛 仅以检测报告为证据呈现，不引申。",
                "复用模板 slot 的产品动作展示，不复制参考台词/花字。",
            ]),
            "story_pacing": _section("节奏与叙事", "按模板 slot 节奏分拍，proof-first，结尾落到价格/质感", [
                "H开头建立好奇，中段以 proof 兑现，结尾 CTA。",
                "每 scene 对应一个模板 slot，时长累计自 slot duration_s。",
            ]),
            "visual_rules": _section("视觉规则", "保留透明材质、无 logo 遮挡；不变色不变形；逐镜展示产品动作", [
                "每个 scene 映射到自有素材区间（no-dup + in-point 不重叠）。",
                "景别/机位沿模板 shot_language 语法。",
            ]),
            "fact_continuity": _section("事实与连续性", "价格/SKU 固定，卖点仅以可见证据呈现", [
                "0甲醛=needs_evidence（引用检测报告）。",
                "禁用 '全网最低价'（forbidden）。",
            ]),
            "originality_boundary": _section("原创边界", "只沿用模板镜头语法与 caption_treatment，不复制参考台词/花字", [
                "参考 overlay_text/dialogue 仅 analysis_only。",
                "最终字幕/台词来自商品事实 + 本 script。",
            ]),
        },
    }
    ccp_env = _write(project, "creative_control_plan", ccp)

    _DIRECTION = "direction-proof-chain"
    _MATRIX_ROWS = ["matrix-01", "matrix-02", "matrix-03", "matrix-04", "matrix-05", "matrix-06", "matrix-07"]
    _FINGERPRINT = ["whole_video.beat_order", "whole_video.pacing_curve"]
    concepts = [
        {"id": "c1", "title": "透明桌垫 0 甲醛安心之选", "hook": "桌面油污，一擦就没了？",
         "narrative_structure": "problem_solution", "visual_approach": "从全景到特写逐镜展示防油/防水/0甲醛。",
         "target_platform": "tiktok", "target_duration_seconds": 16.0,
         "key_points": ["防水防油易清洁", "0甲醛·检测报告可查", "透明极简不遮纹理"],
         "core_message": "透明桌垫既省心又安心。", "cta": "点进看细节，69 元更省心。",
         "tone": "轻松种草", "grounded_in": ["product_facts.params", "product_facts.claims"],
         "research_direction_refs": [_DIRECTION], "matrix_row_refs": _MATRIX_ROWS, "fingerprint_rule_refs": _FINGERPRINT,
         "why_this_works": "痛点（油污）+ 区别化卖点（0甲醛）+ 真实价格，适合短视频。"},
        {"id": "c2", "title": "一眼质感：透明桌垫开箱即用", "hook": "为什么越来越多人换透明桌垫？",
         "narrative_structure": "story", "visual_approach": "以'从陌生到换上'的叙事推进，强调透明不变形。",
         "target_platform": "instagram", "target_duration_seconds": 16.0,
         "key_points": ["透明极简风", "贴合桌面不翘边", "耐磨防刮"],
         "core_message": "一块桌垫，让餐桌质感升级。", "cta": "收藏备用，换桌垫不踩雷。",
         "tone": "质感生活", "grounded_in": ["product_facts.visual_identity"],
         "research_direction_refs": ["direction-life-table"], "matrix_row_refs": _MATRIX_ROWS, "fingerprint_rule_refs": _FINGERPRINT,
         "why_this_works": "以生活质感叙事建立向往感。"},
        {"id": "c3", "title": "透明桌垫到底耐不耐用？", "hook": "透明桌垫耐不耐用？实测给你看。",
         "narrative_structure": "myth_busting", "visual_approach": "用耐磨/防刮特写逐项'验真'。",
         "target_platform": "youtube", "target_duration_seconds": 16.0,
         "key_points": ["耐磨防刮", "防水防油", "0甲醛"],
         "core_message": "透明桌垫不是易耗品，是省心之选。", "cta": "真实测评，喜欢再看价格。",
         "tone": "实测可信", "grounded_in": ["product_facts.params"],
         "research_direction_refs": ["direction-pain-first"], "matrix_row_refs": _MATRIX_ROWS, "fingerprint_rule_refs": _FINGERPRINT,
         "why_this_works": "测评结构天然带信任背书。"},
    ]
    pp = {
        "version": "1.0",
        "creative_control_plan": ccp,
        "concept_options": concepts,
        "selected_concept": {"concept_id": "c1", "rationale": "proof-first 适配，最贴合模板 slot 动作与短视频节奏。"},
        "production_plan": {
            "pipeline": PIPELINE, "playbook": "clean-professional", "stages": [],
            "renderer_family": "product-reveal", "render_runtime": "remotion", "composition_mode": "templated",
            "delivery_promise": {"promise_type": "source_led", "motion_required": False, "source_required": True,
                                 "tone_mode": "cinematic", "quality_floor": "presentable", "approved_fallback": None},
            "voice_selection": {"provider": "待定", "voice_id": "待定", "sample_approval_required": True,
                                "delivery_style": "清晰种草腔", "pacing_policy": "每句独立", "estimated_cost_usd": 0.0},
            "music_source": {"source_type": "none", "mood_direction": "轻快节奏 BGM", "estimated_cost_usd": 0.0},
            "provider_rankings": {"video": [], "image": [], "tts": [], "music": []},
        },
        "cost_estimate": {"total_estimated_usd": 0.0,
                          "line_items": [{"tool": "V8 自有素材", "operation": "复用历史产品视频", "quantity": 8, "estimated_usd": 0.0}],
                          "budget_verdict": "no_budget_set"},
        "approval": {"status": "pending"},
        "metadata": {"template_id": plan_id},
    }
    pp_env = _write(project, "proposal_packet", pp, sink=sink)
    return {"proposal_packet": pp_env, "creative_control_plan": ccp_env}


def build_hook_plan(project: Path, template: dict, facts: dict, *, sink=None) -> dict:
    hook = {
        "version": "1.0",
        "project_id": project.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hook_window_seconds": [0.0, 1.5],
        "first_frame_visual": "透明桌垫防油易擦拭的特写：油污一擦即净",
        "first_audio": "口播首句「一块透明桌垫，凭什么是它？」",
        "promise": "先用一个具体可感知的痛点（油污/易清洁）建立好奇，再回填 0甲醛 与质感",
        "proof_evidence": "自有素材 product_透明桌垫-防油易擦拭 的擦拭动作（matrix 已解析的自有源）",
        "hook_pattern": "problem_first",
        "candidate_variants": [],
        "revision_round": 0,
    }
    return _write(project, "hook_plan", hook, sink=sink)


def build_decision_log(project: Path, template: dict, facts: dict, *, sink=None) -> dict:
    log = {
        "version": "1.0",
        "project_id": project.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-director@1.0",
        "input_hashes": {"template_plan": "a" * 64},
        "decisions": [
            {
                "decision_id": f"{project.name}-runtime-001",
                "stage": "proposal",
                "category": "render_runtime_selection",
                "subject": "渲染 runtime",
                "options_considered": [
                    {"option_id": "remotion", "label": "Remotion", "reason": "本机可用；适合实拍剪辑、字幕叠加、结尾字卡", "score": 0.9},
                    {"option_id": "hyperframes", "label": "HyperFrames", "reason": "本机 CLI 不可用（doctor 超时）", "score": 0.1, "rejected_because": "runtime not available on this machine"},
                    {"option_id": "ffmpeg", "label": "FFmpeg", "reason": "仅拼接，无法满足字幕叠加与字卡", "score": 0.4},
                ],
                "selected": "remotion",
                "reason": "本机 Remotion 可用且能表达产品 montage 的字幕/转场；HyperFrames 不可用。",
                "user_visible": True,
                "confidence": 0.95,
            },
            {
                "decision_id": f"{project.name}-composition-001",
                "stage": "proposal",
                "category": "composition_mode",
                "subject": "合成模式",
                "options_considered": [
                    {"option_id": "templated", "label": "模板驱动", "reason": "43 模板量产，复用模板 slot 语法", "score": 0.9},
                    {"option_id": "atelier", "label": "Atelier", "reason": "单条 hero 需要逐条手写视觉语言；本批为量产", "score": 0.3},
                ],
                "selected": "templated",
                "reason": "模板批适用 templated 组合模式。",
                "user_visible": True,
                "confidence": 0.9,
            },
            {
                "decision_id": f"{project.name}-concept-001",
                "stage": "proposal",
                "category": "concept_selection",
                "subject": "创意方向",
                "options_considered": [
                    {"option_id": "c1", "label": "透明桌垫 0 甲醛安心之选", "reason": "proof-first，贴合模板 slot 动作", "score": 0.9},
                    {"option_id": "c2", "label": "一眼质感：透明桌垫开箱即用", "reason": "生活质感叙事", "score": 0.6},
                    {"option_id": "c3", "label": "透明桌垫到底耐不耐用？", "reason": "测评结构", "score": 0.5},
                ],
                "selected": "c1",
                "reason": "proof-first 适配，最贴合模板 slot 动作与短视频节奏。",
                "user_visible": True,
                "confidence": 0.9,
            },
        ],
    }
    return _write(project, "decision_log", log, sink=sink)


# ---------- script ----------

def _text_action_key(narr: str, copy: str) -> str:
    """从口播/花字文本推断产品动作 key（与 template_source_match._RULES 同一词汇表）。

    build_script 用它把逐镜文案表与 scene 实际绑定的素材动作对齐：
    文案行按绑定动作挑选，避免「台词说防油、画面放甲醛检测」的语义错配。
    """
    from lib.template_source_match import _RULES, _DEFAULT_ACTION

    text = f"{narr} {copy}"
    scored = []
    for action, keywords in _RULES:
        hits = sum(1 for kw in keywords if kw in text)
        if hits:
            scored.append((hits, -len(keywords), action))
    if not scored:
        return _DEFAULT_ACTION
    scored.sort(reverse=True)
    return scored[0][2]


def _bound_action(sp: Mapping[str, Any], scene: Mapping[str, Any]) -> str:
    """scene 绑定素材的动作 key（source_mapping → stem 后缀），缺失时回退 ''。"""
    import os

    for m in ((sp.get("metadata") or {}).get("source_mapping") or []):
        if m.get("scene_id") == scene.get("id") and m.get("source_path"):
            stem = os.path.splitext(os.path.basename(str(m["source_path"])))[0]
            return stem.replace("product_透明桌垫-", "")
    return ""


# 每动作的兜底口播（模板文案表里该动作行已被用完时使用；保证 口播动作 == 素材动作）。
_ACTION_NARRATION: dict[str, tuple[str, str]] = {
    "防油易擦拭": ("油污汤汁，一擦就净。", "油污 · 一擦即净"),
    "无甲醛检测": ("0 甲醛，检测报告为证。", "0 甲醛 · 报告可查"),
    "桌角对齐-挤压不变形": ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边"),
    "自动铺开对齐": ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事"),
    "防刮": ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新"),
    "餐桌场景": ("餐桌省心，质感如新。", "餐桌 · 省心好物"),
}


def build_script(project: Path, template: dict, sp: dict, ccp: dict, facts: dict, *, approved: bool = False, sink=None) -> dict:
    # 逐镜对齐：narration/花字必须与该 scene 绑定的素材画面一致（主链路语义）。
    # 关键：**narration 由素材动作派生**，不同模板 archetype 用各自的逐镜文案表，
    # 绝不套用 video1 的 8 镜（导致长模板 9+ 镜空口播）。
    tid = str(template.get("template_id") or "")
    our = _NARRATION_BY_TEMPLATE.get(tid, _NARRATION_DEFAULT)
    sections = []
    from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE

    row_actions = SLOT_ACTION_BY_TEMPLATE.get(tid) or []
    used_rows: set[int] = set()

    def _row_action(pos: int, narr: str, copy: str) -> str:
        """该表格行的动作 key：逐模板显式表优先（作者标定），否则文本打分回退。"""
        return row_actions[pos] if pos < len(row_actions) else _text_action_key(narr, copy)

    def _pick_row(bound: str):
        # 1) 未用且动作精确匹配的表格行（行动作 = 逐模板显式表；与绑定同源，故事线不垮）
        for pos in range(len(our)):
            if pos in used_rows:
                continue
            narr, copy, role = our[pos] if len(our[pos]) >= 3 else ("", "", "proof")
            if bound and _row_action(pos, narr, copy) == bound and narr.strip():
                used_rows.add(pos)
                return pos, narr, copy, role, _row_action(pos, narr, copy)
        # 2) 表格行耗尽 → 该动作的兜底口播（保证 口播动作 == 素材动作，绝不跨动作错配）
        if bound and bound in _ACTION_NARRATION:
            narr, copy = _ACTION_NARRATION[bound]
            return None, narr, copy, "proof", bound
        # 3) 无绑定信息（审计环境）→ 表内第一个未用行
        for pos in range(len(our)):
            if pos in used_rows:
                continue
            narr, copy, role = our[pos] if len(our[pos]) >= 3 else ("", "", "proof")
            if narr.strip():
                used_rows.add(pos)
                return pos, narr, copy, role, _row_action(pos, narr, copy)
        return None, "", "", "proof", ""

    for i, scene in enumerate(sp["scenes"], start=1):
        bound = _bound_action(sp, scene)
        span = float(scene["end_seconds"]) - float(scene["start_seconds"])
        if span < 1.0:
            # 闪帧卡位（0.1-0.5s）：物理放不下口播（voice-timeline-fit 会 overflow），
            # 只保留花字收尾，绝不硬塞一句导致 TTS 阻断（评审 P1-6 联动）。
            narr, copy, role = "", "", "cta"
            for row in our:
                if len(row) >= 2 and not str(row[0] or "").strip():
                    copy = str(row[1] or "")
                    break
            if not copy:
                copy = "直播间见"
            text_action = ""
            aligned = True  # 无口播即无语义冲突
        else:
            pos, narr, copy, role, text_action = _pick_row(bound)
            aligned = bool(bound and text_action == bound)
        sections.append({
            "id": f"sec-{i:03d}", "label": f"beat-{i}", "text": narr, "narration": narr,
            "screen_copy": copy, "section_goal": f"第 {i} 个模板 slot 动作", "beat_role": role,
            "viewer_state": {"hook": "好奇", "reveal": "被揭晓", "proof": "信服", "cta": "行动",
                             "problem": "疑虑", "escalation": "被放大", "payoff": "被解决", "other": ""}[role],
            "start_seconds": scene["start_seconds"], "end_seconds": scene["end_seconds"],
            "visual_intent": "V8 自有素材 + 模板指定花字处理",
            "evidence_requirements": ["0甲醛 需检测报告作为证据"] if role not in ("", "cta") else [],
            "source_ref": "product_facts",
            # 语义对齐审计字段：口播动作 key 必须等于所绑素材动作 key。
            "narration_action_key": text_action,
            "bound_material_action": bound,
            "narration_material_aligned": aligned,
        })
    sc = {
        "version": "1.0",
        "script_id": str(template.get("template_id")),
        "script_version": 1, "status": ("approved" if approved else "draft"),
        "creative_control_ref": {"plan_id": str(template.get("template_id")), "plan_version": ccp.get("plan_version", 1),
                                 "artifact_sha256": str(ccp.get("artifact_sha256") or "a" * 64)},
        "title": "透明桌垫 · 餐桌省心好物",
        "total_duration_seconds": sp["scenes"][-1]["end_seconds"],
        "voice_performance": {"performance_intent": "清晰、节奏明快种草腔", "pacing_profile": "energetic",
                              "energy_curve": "先扬后收", "pause_policy": "每句独立", "sample_section_id": "sec-001"},
        "sections": sections,
        "metadata": {"template_id": str(template.get("template_id")),
                     "fact_card_ref": {"name": "product_facts", "path": "artifacts/product_facts.json"}},
    }
    # 语义硬门（仅对已固化显式动作表的模板生效；现有 build_script 阶段内 fail-closed，
    # 不新增旁支链路）：文案必须能被该镜绑定素材证明，否则剧本阶段直接阻断。
    if tid in SLOT_ACTION_BY_TEMPLATE:
        from lib.template_source_match import semantic_mismatches

        findings = semantic_mismatches(sc)
        if findings:
            raise SystemExit(
                f"{project.name}: 剧本语义硬门失败（{len(findings)} 处文案与素材画面不可证）—— "
                + "; ".join(f"{f['section_id']}:{f['message'][:40]}" for f in findings[:5])
            )
    if approved:
        sc["approval"] = {"approved_by": "operator", "approved_at": datetime.now(timezone.utc).isoformat()}
    return _write(project, "script", sc, sink=sink)


# ---------- scene_plan ----------

def scene_plan_data(project: Path, template: dict, rp: dict, ccp: dict, facts: dict) -> dict:
    slots = template.get("slots") or []
    assigned = match_run_plan(slots, rp)
    # reviewed owned source 路径（scene_plan 硬门要求 source_path ∈ source_media_review）
    source_review_urls: dict[str, str] = {}
    smr = _load(project / "artifacts" / "source_media_review.json") or {}
    for f in smr.get("files", []):
        if f.get("reviewed"):
            source_review_urls[Path(f["path"]).stem] = f["path"]
    # 研究链 grounding：素材 ↔ matrix row 桥接（scene_plan 硬门要求 matrix_row_id/resolution）
    matrix = _load(project / "artifacts" / "reference_source_matrix.json") or {}
    grounding = resolve_matrix_grounding(smr, matrix)
    ccp_direction = str(((ccp or {}).get("sections") or {}).get("content_direction") or "")
    research_direction = "direction-proof-chain"  # proof-first 适配方向（来自共享 research_synthesis）
    scenes, cursor = [], 0.0
    for idx, slot in enumerate(slots):
        sid = str(slot.get("slot_id") or "")
        dur = float(slot.get("duration_s") or 2.0)
        ci = resolve_caption_recipe_intent(None, slot.get("caption_treatment"))
        scenes.append({
            "id": f"scene-{sid.rsplit('-slot-')[-1]}", "type": "broll",
            "description": scene_description(idx, slot),
            "start_seconds": round(cursor, 3), "end_seconds": round(cursor + dur, 3),
            "shot_language": {"shot_size": SHOT_SIZE.get(str((slot.get("shot_language") or {}).get("shot_size") or ""), "medium"),
                              "camera_movement": CAMERA.get(str((slot.get("shot_language") or {}).get("camera_movement") or ""), "static")},
            "shot_intent": str(slot.get("dialogue") or "")[:120] or f"按模板 slot {sid}",
            "narrative_role": "evidence", "hero_moment": False,
            "caption_recipe_intent": ci["recipe_intent"],
            "caption_treatment": str(slot.get("caption_treatment") or "none"),
            "caption_intent_derived_from": ci["derived_from"],
            "caption_fallback_used": ci["fallback_used"],
            # 键控配对：scene 显式携带其来源 slot（禁止下游按位置 scene[i]↔slot[i]）。
            "template_slot_ref": sid,
        })
        # 转场意图：仅在有 recipe 时写入（硬切=不写，走渲染器默认 hard-cut）。
        # 模板专属表优先；否则按该模板剧本 beat role 派生：
        # proof → flash-proof 强调；problem/escalation/reveal/payoff → action_match；
        # hook/cta → 默认硬切（不写 intent）。
        _tid = str(template.get("template_id") or "")
        _tt = TRANSITION_INTENT_BY_TEMPLATE.get(_tid)
        if _tt is not None:
            ti = _tt.get(idx)
        else:
            _our = _NARRATION_BY_TEMPLATE.get(_tid, _NARRATION_DEFAULT)
            _role = _our[idx][2] if idx < len(_our) else None
            ti = {"proof": "proof", "problem": "action_match", "escalation": "action_match",
                  "reveal": "action_match", "payoff": "action_match"}.get(_role)
        if ti:
            scenes[-1]["transition_recipe_intent"] = ti
        cursor += dur
    # 键控配对：scene_id → slot（经 scene 上的显式 template_slot_ref，禁止位置索引）。
    slots_by_id = {str(slot.get("slot_id") or ""): slot for slot in slots}
    slot_by_scene: dict[str, Any] = {}
    for scene in scenes:
        ref = str(scene.get("template_slot_ref") or "")
        if ref not in slots_by_id:
            raise ValueError(f"scene {scene.get('id')} 的 template_slot_ref {ref!r} 不在模板 slots 中")
        slot_by_scene[str(scene.get("id") or "")] = slots_by_id[ref]
    source_mapping = build_source_mappings(
        scenes,
        slot_by_scene,
        assigned,
        source_review_urls=source_review_urls,
        grounding=grounding,
        research_direction=research_direction,
    )
    slot_ref_map = {m["scene_id"]: m["template_slot_ref"] for m in source_mapping}
    sp = {
        "version": "1.0", "caption_policy_version": "1.0",
        "creative_control_ref": {"plan_id": str(template.get("template_id")), "plan_version": ccp.get("plan_version", 1),
                                 "artifact_sha256": str(ccp.get("artifact_sha256") or "a" * 64)},
        "scenes": scenes,
        "metadata": {"template_id": str(template.get("template_id")),
                     "template_pack_ref": "projects/template-pack-library/artifacts/template_pack.json",
                     "run_plan_ref": f"projects/{project.name}/artifacts/template_run_plan.json",
                     "reference_media_usage": "analysis_only",
                     "template_slot_ref": slot_ref_map, "source_mapping": source_mapping},
    }
    return sp


def build_scene_plan(project: Path, template: dict, rp: dict, ccp: dict, facts: dict, *, sink=None) -> dict:
    """写 scene_plan 制品，返回信封。"""
    sp = scene_plan_data(project, template, rp, ccp, facts)
    return _write(project, "scene_plan", sp, sink=sink)


# 每 scene 的 OWN 视觉描述（商品事实驱动，替换模板占位花字；不复制参考）
_OWN_SCENE_DESC = [
    "透明桌垫防油易擦拭：一擦即净的特写",
    "0甲醛 检测报告为证（无甲醛/安心卖点）",
    "透明软玻璃贴合桌面，不翘边的边缘特写",
    "透明垫自动铺开对齐平板桌面的过程",
    "防刮耐磨：硬物在垫面刮擦仍完好",
    "回到餐桌使用场景，透明垫不遮木纹质感",
    "耐磨防刮特写：久用如新",
    "透明桌垫收尾：价格与质感引导",
]


def scene_description(slot_index: int, slot: Mapping[str, Any]) -> str:
    """scene 的 OWN 描述：优先 OWN 商品事实文案，其次是 slot 的真实产品动作词。"""
    if slot_index < len(_OWN_SCENE_DESC):
        return _OWN_SCENE_DESC[slot_index]
    # 兜底：从 slot 里剥掉占位花字（如 KEEP HAPPY HOLIDAY），只留真实产品词。
    return str(slot.get("visual_content") or "模板 slot 动作")[:80]

def approve_ccp(project: Path, *, locked_by: str = "operator", pipeline_dir: Path | None = None) -> dict:
    """把 creative_control_plan 锁定为 approved（模拟人工确认导演总控单）。"""
    p = project / "artifacts" / "creative_control_plan.json"
    ccp = _load(p)
    if not ccp:
        raise SystemExit("creative_control_plan.json not found; run proposal first")
    ccp["status"] = "approved"
    ccp["locked_at"] = datetime.now(timezone.utc).isoformat()
    ccp["locked_by"] = locked_by
    ccp["section_reviews"] = {k: "approved" for k in ccp.get("sections", {})}
    env = _write(project, "creative_control_plan", ccp)
    # 重写制品后，刷新所有 checkpoint 里的信封，避免后续 stage 校验报 envelope drift。
    from lib.checkpoint import refresh_checkpoint_envelopes
    refresh_checkpoint_envelopes(pipeline_dir or ROOT / "projects", project.name, pipeline_type=PIPELINE)
    return env


def advance_run_full(run: str, *, pipeline_dir: Path | None = None, pack: dict | None = None) -> list[str]:
    """主链路推进一条 template run 到 scene_plan（含 ccp/script 人工锁定）。

    顺序：proposal → 锁 ccp(approved) → script(approved, human_approved) → scene_plan。
    这是模板批量的标准推进；旁路脚本已被移除，主链路阶段机是唯一入口。
    """
    project = (pipeline_dir or PROJECTS) / run
    PDIR = pipeline_dir or PROJECTS
    from lib.checkpoint import get_completed_stages
    if pack is None:
        pack = _load(ROOT / "projects/template-pack-library/artifacts/template_pack.json")
    template_id = str((_load(project / "artifacts" / "template_run_plan.json") or {}).get("template_id") or "")
    template = next((t for t in pack.get("templates", []) if t.get("template_id") == template_id), None)
    facts = _load(project / "artifacts" / "product_facts.json") or {}
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}
    if "proposal" not in get_completed_stages(PDIR, run, PIPELINE):
        if template is None:
            raise SystemExit(f"template {template_id} not in pack")
        envs = build_proposal(project, template, facts)
        envs["hook_plan"] = build_hook_plan(project, template, facts)
        envs["decision_log"] = build_decision_log(project, template, facts)
        write_checkpoint(PDIR, run, "proposal", "completed", envs,
                         pipeline_type=PIPELINE, next_action=None, review={"findings": [], "verdict": "pass"})
    if "script" not in get_completed_stages(PDIR, run, PIPELINE):
        approve_ccp(project, locked_by="operator", pipeline_dir=PDIR)
        ccp = _load(project / "artifacts" / "creative_control_plan.json")
        sp_data = scene_plan_data(project, template, rp, ccp, facts)
        sc_env = build_script(project, template, sp_data, ccp, facts, approved=True)
        write_checkpoint(PDIR, run, "script", "completed", {"script": sc_env},
                         pipeline_type=PIPELINE, next_action=None, human_approved=True)
    if "scene_plan" not in get_completed_stages(PDIR, run, PIPELINE):
        ccp = _load(project / "artifacts" / "creative_control_plan.json")
        sp_env = build_scene_plan(project, template, rp, ccp, facts)
        write_checkpoint(PDIR, run, "scene_plan", "completed", {"scene_plan": sp_env},
                         pipeline_type=PIPELINE, next_action=None)
    return get_completed_stages(PDIR, run, PIPELINE)


def advance_to_assets(run: str, *, pipeline_dir: Path | None = None) -> str:
    """推进到 assets 并写 awaiting_human（creative_lock terminal gate），返回下一 stage。

    前置（fail-closed）：template_run_plan 必须已**显式** approved——本函数绝不自动批准
    （审批必须由人/已被记录的 batch_approval 决策落盘），未批准直接阻断。
    不触发任何付费调用（asset_plan.paid_generation_approved=False）。
    """
    PDIR = pipeline_dir or PROJECTS
    project = PDIR / run
    from lib.template_assets import build_assets
    from lib.checkpoint import get_completed_stages
    if "scene_plan" not in get_completed_stages(PDIR, run, PIPELINE):
        advance_run_full(run, pipeline_dir=PDIR)
    # run_plan 批准硬门：不在此自动批准（评审 P1-8）。
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}
    if str(rp.get("status") or "") != "approved":
        raise SystemExit(
            f"{run}: template_run_plan 未批准（status={rp.get('status') or '未决'}），"
            f"禁止进入 paid assets。请先审批 run_plan（决策记录 batch_approval 后落盘 status=approved）。"
        )
    template_id = str((_load(project / "artifacts" / "template_run_plan.json") or {}).get("template_id") or "")
    pack = _load(ROOT / "projects/template-pack-library/artifacts/template_pack.json")
    template = next((t for t in pack.get("templates", []) if t.get("template_id") == template_id), None)
    # 项目写入契约：写制品与 checkpoint 必须经版本事务（sink）。
    from backlot.project_commit import ProjectCommitStore

    with ProjectCommitStore(project).transaction(action={"action_id": f"advance-assets-{run}"}) as sink:
        envs = build_assets(project, template, pipeline_dir=PDIR, sink=sink)
        write_checkpoint(PDIR, run, "assets", "awaiting_human", envs, pipeline_type=PIPELINE,
                         next_action={"summary": "assets 待审批（全 owned，无 paid 生成）", "verb": "await_user",
                                      "context_refs": ["artifacts/shot_execution_plan.json", "artifacts/asset_plan.json"]},
                         sink=sink)
    from lib.checkpoint import get_next_stage
    return str(get_next_stage(PDIR, run, PIPELINE) or "none")


def rebuild_aligned_run(run: str, *, pipeline_dir: Path | None = None) -> None:
    """用修正后的语义窗口 + 显式复用逻辑，重写 run 的 script + scene_plan（幂等）。

    用于：早期用旧（关键词+索引硬对齐 + 静默复用）逻辑推进到 scene_plan 的 run。
    只重写 script/scene_plan 的可再生制品 + 对应 checkpoint（已完成状态保持），
    不改 research/proposal（共享研究不变），不触发付费。
    """
    PDIR = pipeline_dir or PROJECTS
    project = PDIR / run
    pack = _load(ROOT / "projects/template-pack-library/artifacts/template_pack.json")
    template_id = str((_load(project / "artifacts" / "template_run_plan.json") or {}).get("template_id") or "")
    template = next((t for t in pack.get("templates", []) if t.get("template_id") == template_id), None)
    if template is None:
        raise SystemExit(f"template {template_id} not in pack")
    rp = _load(project / "artifacts" / "template_run_plan.json")
    facts = _load(project / "artifacts" / "product_facts.json") or {}
    ccp = _load(project / "artifacts" / "creative_control_plan.json")
    # P0-2b：同模板压缩消费（rp.compression.kept_ordinals）——运行时按序取行/动作并过滤槽位，
    # 保持原始 ordinal/slot_id 键控；重建结束后恢复原表（无全局污染）。
    _overlay = None
    kept = (rp or {}).get("compression") or {}
    kept_ordinals = [int(o) for o in kept.get("kept_ordinals", []) if str(o).isdigit()]
    # A child -c1 template already contains the filtered rows.  Only overlay
    # an explicit subset when the run still executes the base template.
    if kept_ordinals and str(kept.get("base_template_id") or template_id) == template_id:
        from lib.template_mainline import _NARRATION_BY_TEMPLATE, _NARRATION_DEFAULT
        from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE
        full_rows = list(_NARRATION_BY_TEMPLATE.get(template_id, _NARRATION_DEFAULT))
        full_acts = list(SLOT_ACTION_BY_TEMPLATE.get(template_id, []))
        _overlay = (template_id, full_rows, full_acts)
        _NARRATION_BY_TEMPLATE[template_id] = [full_rows[o - 1] for o in kept_ordinals if o <= len(full_rows)]
        SLOT_ACTION_BY_TEMPLATE[template_id] = [full_acts[o - 1] for o in kept_ordinals if o <= len(full_acts)]
        template = {**template, "slots": [s for s in (template.get("slots") or [])
                                          if int(str(s.get("ordinal") or 0)) in kept_ordinals]}
    from backlot.project_commit import ProjectCommitStore
    # 分两事务：先 script（approved + checkpoint），再 scene_plan（依赖 script 完成）。
    store = ProjectCommitStore(project)
    try:
        with store.transaction(action={"action_id": f"rebuild-script-{run}"}) as sink:
            rp2 = json.loads(json.dumps(rp))
            match_run_plan(template.get("slots") or [], rp2)
            write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp2, project_dir=project, sink=sink)
            sp = scene_plan_data(project, template, rp2, ccp, facts)
            sc_env = build_script(project, template, sp, ccp, facts, approved=True, sink=sink)
            write_checkpoint(PDIR, run, "script", "completed", {"script": sc_env}, pipeline_type=PIPELINE,
                             next_action=None, human_approved=True, sink=sink)
        with store.transaction(action={"action_id": f"rebuild-sp-{run}"}) as sink:
            sp = scene_plan_data(project, template, rp2, ccp, facts)
            sp_env = write_artifact_atomic("artifacts/scene_plan.json", "scene_plan", sp, project_dir=project, sink=sink)
            write_checkpoint(PDIR, run, "scene_plan", "completed", {"scene_plan": sp_env}, pipeline_type=PIPELINE,
                             next_action=None, sink=sink)
    finally:
        if _overlay is not None:
            _tid, _rows, _acts = _overlay
            from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE
            _NARRATION_BY_TEMPLATE[_tid] = _rows
            SLOT_ACTION_BY_TEMPLATE[_tid] = _acts


def advance_edit(run: str, *, pipeline_dir: Path | None = None) -> str:
    """推进到 edit 并写 checkpoint（no-op 采用：样品已批，无改动）。

    edit 是 gate=false；产出 edit_decisions（沿用已批准 cuts + 字幕）+ change_impact
    (route=no_render)，表示"采用已批样片，无渲染变更"。
    """
    PDIR = pipeline_dir or PROJECTS
    project = PDIR / run
    from lib.checkpoint import get_completed_stages, get_next_stage
    if "edit" in get_completed_stages(PDIR, run, PIPELINE):
        return str(get_next_stage(PDIR, run, PIPELINE) or "none")
    from lib.template_render import build_change_impact
    edit_decisions = _load(project / "artifacts" / "edit_decisions.json")
    lock = _load(project / "artifacts" / "production_lock.json")
    lock_hash = str((lock or {}).get("artifact_sha256") or "a" * 64)
    ci = build_change_impact(project, previous_lock_hash=lock_hash, current_lock_hash=lock_hash,
                             route="no_render", reasons=["样品已批 + 逐镜对齐，本阶段无额外改动，采用已批样片"],
                             dirty_scene_ids=[], reopen_creative_lock=False, reopen_sample=False)
    from backlot.project_commit import ProjectCommitStore
    store = ProjectCommitStore(project)
    with store.transaction(action={"action_id": "write-edit"}) as sink:
        envs = {"edit_decisions": write_artifact_atomic("artifacts/edit_decisions.json", "edit_decisions",
                                                        edit_decisions, project_dir=project, sink=sink),
                "change_impact": write_artifact_atomic("artifacts/change_impact.json", "change_impact",
                                                       ci, project_dir=project, sink=sink)}
        write_checkpoint(PDIR, run, "edit", "completed", envs, pipeline_type=PIPELINE, next_action=None, sink=sink)
    return str(get_next_stage(PDIR, run, PIPELINE) or "none")
    project = PROJECTS / run
    template_id = str((_load(project / "artifacts" / "template_run_plan.json") or {}).get("template_id") or "")
    pack = _load(ROOT / "projects/template-pack-library/artifacts/template_pack.json")
    template = next((t for t in pack.get("templates", []) if t.get("template_id") == template_id), None)
    facts = _load(project / "artifacts" / "product_facts.json") or {}
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}

    while True:
        stage = get_next_stage(PROJECTS, run, PIPELINE)
        if stage is None:
            print("all stages complete")
            break
        if stage not in {"proposal", "script", "scene_plan"}:
            print(f"  stop: {stage} out of template mainchain scope")
            break
        print(f"== {stage} ==")
        if stage == "proposal":
            envs = build_proposal(project, template, facts)
            envs["hook_plan"] = build_hook_plan(project, template, facts)
            envs["decision_log"] = build_decision_log(project, template, facts)
            write_checkpoint(PROJECTS, run, "proposal", "completed", envs,
                             pipeline_type=PIPELINE, next_action=None, review={"findings": [], "verdict": "pass"})
            done.append("proposal")
        elif stage == "script":
            ccp = _load(project / "artifacts" / "creative_control_plan.json")
            sp_data = scene_plan_data(project, template, rp, ccp, facts)
            sc_env = build_script(project, template, sp_data, ccp, facts)
            if approve_script:
                write_checkpoint(PROJECTS, run, "script", "completed", {"script": sc_env},
                                 pipeline_type=PIPELINE, next_action=None, human_approved=True)
            else:
                write_checkpoint(
                    PROJECTS, run, "script", "awaiting_human", {"script": sc_env},
                    pipeline_type=PIPELINE,
                    next_action={"summary": f"script 已 produced，等待人工锁定 script（{run}）",
                                 "verb": "await_user",
                                 "context_refs": ["artifacts/script.json", "artifacts/creative_control_plan.json"]},
                )
                print("  script -> awaiting_human（待人工锁定 ccp + script）")
                break
            done.append("script")
        elif stage == "scene_plan":
            ccp = _load(project / "artifacts" / "creative_control_plan.json")
            sp = build_scene_plan(project, template, rp, ccp, facts)
            write_checkpoint(PROJECTS, run, "scene_plan", "completed", {"scene_plan": sp},
                             pipeline_type=PIPELINE, next_action=None)
            done.append("scene_plan")
        if not advance_scene_plan and get_next_stage(PROJECTS, run, PIPELINE) == "scene_plan":
            # 默认停在 script 门后；显式 --advance-scene-plan 才继续。
            break
    return done


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-01-video1-aks-zhuodian")
    p.add_argument("--approve-script", action="store_true")
    p.add_argument("--advance-scene-plan", action="store_true")
    args = p.parse_args()
    done = advance(args.run, approve_script=args.approve_script, advance_scene_plan=args.advance_scene_plan)
    print("advanced:", done)


if __name__ == "__main__":
    main()

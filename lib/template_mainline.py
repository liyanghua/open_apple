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


# sheet-09 c1/v2 压缩变体（8 镜/16.0s：4 域×2，严格档全绿 — S2' 25% 需 ≥4 域）。
_NARRATION_SHEET_09C2 = [
    ("安全和健康最重要。", "安全健康最重要", "hook"),
    ("凭什么你家桌垫更贵？", "为什么贵一点？", "problem"),
    ("边缘光滑，圆角不扎手。", "圆角光滑 · 不扎手", "proof"),
    ("硬物刮，也不怕。", "真的抗造", "proof"),
    ("用料敢测，玻璃是母婴级。", "母婴级软玻璃", "proof"),
    ("孩子都能放心用。", "孩子放心用", "proof"),
    ("挤压复原，不怕变形。", "不怕变形", "proof"),
    ("怎么扒拉怎么划。", "永远第一位", "cta"),
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


# sheet-14-video15-aks-zhuodian-c3 换序改写变体（严格预检全绿）。
_NARRATION_SHEET_14C3 = [
    ("二十年三十年，做好一件事。", "20年30年 · 一件事", "hook"),
    ("拆开就测，没有异味。", "无异味", "proof"),
    ("耐磨防刮，久用如新。", "耐磨耐用", "proof"),
    ("防水防油，一抹就净。", "防水防油", "proof"),
    ("手按边角，每一处都贴合。", "边角都贴合", "proof"),
    ("我家餐桌上，就是它。", "我家在用", "payoff"),
    ("材质安不安全，测了知道。", "健康材质", "reveal"),
    ("用了半年，还是光滑。", "半年如新", "proof"),
    ("脏了一擦就净。", "直播间见", "cta"),
]


# sheet-19-video22-aks-zhuodian-c4 换序改写变体（严格预检全绿）。
_NARRATION_SHEET_19C4 = [
    ("软玻璃，材质看得见。", "PVC软玻璃", "reveal"),
    ("硬物刮，也不怕。", "真的抗造", "proof"),
    ("选桌垫，别只图便宜。", "别只图便宜", "hook"),
    ("饮料酒水撒上去。", "饮料撒桌面", "proof"),
    ("边角圆滑，不扎手。", "边角圆滑", "proof"),
    ("每一批，都测过。", "每批检测", "proof"),
    ("怎么扒拉怎么划。", "怎么划都不怕", "proof"),
    ("脏了一擦就净。", "直播间见", "cta"),
]


# sheet-15-video17-aks-zhuodian（VLM 标定生成口播行）。
_NARRATION_SHEET_15 = [
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事", "proof"),
    ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("0 甲醛，检测报告为证。", "0 甲醛 · 报告可查", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
]


# sheet-20-video23-aks-zhuodian（VLM 标定生成口播行）。
_NARRATION_SHEET_20 = [
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新", "proof"),
    ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("0 甲醛，检测报告为证。", "0 甲醛 · 报告可查", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
]


# sheet-22-video27-aks-zhuodian（VLM 标定生成口播行）。
_NARRATION_SHEET_22 = [
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
]


# sheet-42-video48-yanban-zhuojia（VLM 标定生成口播行）。
_NARRATION_SHEET_42 = [
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
    ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
    ("0 甲醛，检测报告为证。", "0 甲醛 · 报告可查", "proof"),
    ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边", "proof"),
    ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事", "proof"),
    ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事", "proof"),
    ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事", "proof"),
    ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新", "proof"),
    ("油污汤汁，一擦就净。", "油污 · 一擦即净", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
    ("餐桌省心，质感如新。", "餐桌 · 省心好物", "proof"),
]

_NARRATION_BY_TEMPLATE: dict[str, list[tuple[str, str, str]]] = {
    "sheet-04-video4-zhuodian": _NARRATION_SHEET_04,
    "sheet-05-video5-aks-zhuodian": _NARRATION_SHEET_05,
    "sheet-09-video9-aks-zhuodian": _NARRATION_SHEET_09,
    "sheet-14-video15-aks-zhuodian": _NARRATION_SHEET_14,
"sheet-19-video22-aks-zhuodian": _NARRATION_SHEET_19,
    "sheet-15-video17-aks-zhuodian": _NARRATION_SHEET_15,
    "sheet-20-video23-aks-zhuodian": _NARRATION_SHEET_20,
    "sheet-22-video27-aks-zhuodian": _NARRATION_SHEET_22,
    "sheet-42-video48-yanban-zhuojia": _NARRATION_SHEET_42,
    "sheet-14-video15-aks-zhuodian-c1": _NARRATION_SHEET_14C1,
    "sheet-04-video4-zhuodian-c1": _NARRATION_SHEET_04C1,
    "sheet-05-video5-aks-zhuodian-c1": _NARRATION_SHEET_05C1,
    "sheet-09-video9-aks-zhuodian-c2": _NARRATION_SHEET_09C2,
    "sheet-19-video22-aks-zhuodian-c4": _NARRATION_SHEET_19C4,
    "sheet-14-video15-aks-zhuodian-c3": _NARRATION_SHEET_14C3,
    "sheet-19-video22-aks-zhuodian-c1": _NARRATION_SHEET_19C1,
}

from lib.template_calibrations import _GENERATED_ROWS as _GEN_ROWS
_NARRATION_BY_TEMPLATE.update(_GEN_ROWS)

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


def _template_for_project(
    project: Path,
    template_id: str,
    *,
    pack: Mapping[str, Any] | None = None,
) -> dict | None:
    """Resolve a run's template from its canonical local pack before globals.

    Source-led pilots may use an aligned template that deliberately is not in
    the reference-derived global library.  The run-local pack is the artifact
    already bound into that run, so it is authoritative for resumption.
    """
    packs: list[Mapping[str, Any]] = []
    if pack is not None:
        packs.append(pack)
    else:
        local_pack = _load(project / "artifacts" / "template_pack.json")
        global_pack = _load(ROOT / "projects/template-pack-library/artifacts/template_pack.json")
        if isinstance(local_pack, Mapping):
            packs.append(local_pack)
        if isinstance(global_pack, Mapping):
            packs.append(global_pack)
    for candidate_pack in packs:
        template = next(
            (item for item in (candidate_pack.get("templates") or [])
             if isinstance(item, Mapping)
             and str(item.get("template_id") or "") == template_id),
            None,
        )
        if template is not None:
            return dict(template)
    return None


def _write(project: Path, name: str, data: dict, *, sink=None) -> dict:
    return write_artifact_atomic(f"artifacts/{name}.json", name, data, project_dir=project, sink=sink)


def _section(title: str, summary: str, rules: list[str]) -> dict:
    return {"title": title, "summary": summary, "rules": rules}


def _source_led_research_context(project: Path) -> tuple[str | None, list[dict], list[dict]]:
    matrix = _load(project / "artifacts" / "reference_source_matrix.json") or {}
    mode = matrix.get("matrix_mode")
    if mode not in {"source_led", "source_led_template"}:
        return None, [], []
    rows = [
        row for row in matrix.get("rows", [])
        if isinstance(row, dict) and row.get("resolution") == "accept"
    ]
    synthesis = _load(project / "artifacts" / "research_synthesis.json") or {}
    directions = [
        item for item in synthesis.get("differentiation_directions", [])
        if isinstance(item, dict) and item.get("direction_id")
    ]
    if not rows or not directions:
        raise ValueError("source-led proposal requires accepted evidence rows and research directions")
    return str(mode), rows, directions


def _source_led_product_display_name(facts: Mapping[str, Any], fallback: str) -> str:
    """Prefer the curated identity line over a merchant SEO title.

    Marketplace titles often bundle unqualified benefit claims (for example
    antibacterial or odor prevention).  The first fact-card param is the
    deliberately curated identity wording and is safe for proposal/script
    titles; the raw product_name remains provenance, not automatic copy.
    """
    params = facts.get("params")
    if isinstance(params, list):
        for value in params:
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(facts.get("product_name") or facts.get("title") or fallback).strip()


def _source_led_target_platform(project: Path) -> str:
    """Resolve the operator-approved distribution platform for source-led runs."""
    project_data = _load(project / "project.json") or {}
    product_input = project_data.get("product_input") or {}
    configured = str(product_input.get("target_platform") or "").strip().lower()
    if configured:
        return configured
    product_url = str(product_input.get("product_url") or "").lower()
    if "tmall.com" in product_url or "taobao.com" in product_url:
        return "taobao"
    return "generic"


# ---------- proposal ----------

def build_proposal(project: Path, template: dict, facts: dict, *, sink=None) -> dict[str, Any]:
    plan_id = str(template.get("template_id") or "")
    run_plan = _load(project / "artifacts" / "template_run_plan.json") or {}
    differentiation_plan_ref = run_plan.get("differentiation_plan_ref")
    source_mode, source_rows, source_directions = _source_led_research_context(project)
    if source_mode:
        target_platform = _source_led_target_platform(project)
        selected = source_directions[0]
        selected_id = str(selected["direction_id"])
        selected_title = str(selected.get("title") or selected_id)
        selected_promise = str(selected.get("promise") or "自有素材证据决定逐镜表达")
        product_name = _source_led_product_display_name(facts, project.name)
        all_row_ids = [str(row.get("matrix_row_id")) for row in source_rows]
        all_allowed = [
            str(value) for row in source_rows for value in row.get("allowed_wording", [])
            if str(value).strip()
        ]
        ccp = {
            "version": "1.0", "project_id": project.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "producer": "template-director@source-led-1.0",
            "input_hashes": {
                "template_plan": str(run_plan.get("artifact_sha256") or "a" * 64),
                "product_facts": str(facts.get("artifact_sha256") or "b" * 64),
            },
            "plan_id": plan_id, "plan_version": 1, "status": "draft",
            "selected_direction_id": selected_id,
            "target_platform": target_platform,
            "sections": {
                "content_direction": _section("内容方向", f"{product_name}：{selected_title}", [
                    selected_promise,
                    "每句口播和花字只能取自 accepted 证据行的 allowed_wording。",
                    "requires_visible_result 的镜头必须保留动作前、动作中、结果态。",
                ]),
                "story_pacing": _section("节奏与叙事", "模板仅提供顺序与节奏先验，证据镜头时长优先", [
                    "动态证明镜头不得为迁就模板时长而截掉结果。",
                    "其余动作镜头在已审核语义窗口内裁切。",
                ]),
                "visual_rules": _section("视觉规则", "中心裁切到 3:4，主体完整优先", [
                    "逐镜使用 source_semantic_index 已确认可用的自有素材。",
                    "商品页主图只作身份或参数锚点，不替代动态效果证明。",
                ]),
                "fact_continuity": _section("事实与连续性", "商品事实与画面事实分层表达", [
                    "页面声明必须明确为商品页标注，不能升级为独立检测结论。",
                    "无对应证据行的卖点不得进入口播、字幕或场景描述。",
                ]),
                "originality_boundary": _section("原创边界", "不使用外部参考内容；模板只保留结构先验", [
                    "不复制模板原台词、花字和商品语义。",
                    "镜头主体、动作、文案均来自本项目研究产物。",
                ]),
            },
        }
        ccp_env = _write(project, "creative_control_plan", ccp, sink=sink)
        direction_pool = source_directions[:3]
        while len(direction_pool) < 3:
            direction_pool.append(selected)
        structures = ["problem_solution", "story", "tutorial"]
        concepts = []
        for index, direction in enumerate(direction_pool[:3], start=1):
            refs = [
                str(value) for value in direction.get("matrix_row_refs", [])
                if str(value) in all_row_ids
            ] or all_row_ids[:1]
            key_points = []
            for row in source_rows:
                if str(row.get("matrix_row_id")) in refs:
                    key_points.extend(str(value) for value in row.get("allowed_wording", []) if str(value).strip())
            key_points = list(dict.fromkeys(key_points))
            while len(key_points) < 2:
                key_points.append(product_name if key_points else (all_allowed[0] if all_allowed else product_name))
            title_text = str(direction.get("title") or f"证据方向 {index}")
            promise = str(direction.get("promise") or "用自有素材动作建立可信表达")
            concepts.append({
                "id": f"c{index}", "title": f"{product_name} · {title_text}",
                "hook": key_points[0][:20], "narrative_structure": structures[index - 1],
                "visual_approach": promise, "target_platform": target_platform,
                "target_duration_seconds": 30.0, "key_points": key_points[:4],
                "core_message": promise, "cta": "查看商品详情",
                "tone": "克制、可信、生活化", "grounded_in": ["source_semantic_index", "product_facts"],
                "research_direction_refs": [str(direction["direction_id"])],
                "matrix_row_refs": refs,
                "fingerprint_rule_refs": ["source-led.structure-only"],
                "why_this_works": promise,
            })
        pp = {
            "version": "1.0", "creative_control_plan": ccp,
            **({"differentiation_plan_ref": dict(differentiation_plan_ref)} if isinstance(differentiation_plan_ref, dict) else {}),
            "concept_options": concepts,
            "selected_concept": {"concept_id": "c1", "rationale": f"优先采用研究方向“{selected_title}”，先保证证据闭环。"},
            "production_plan": {
                "pipeline": PIPELINE, "playbook": "clean-professional", "stages": [],
                "renderer_family": "product-reveal", "render_runtime": "remotion", "composition_mode": "templated",
                "delivery_promise": {"promise_type": "source_led", "motion_required": False, "source_required": True,
                                     "tone_mode": "cinematic", "quality_floor": "presentable", "approved_fallback": None},
                "voice_selection": {"provider": "待定", "voice_id": "待定", "sample_approval_required": True,
                                    "delivery_style": "清晰克制的电商口播", "pacing_policy": "逐镜停连", "estimated_cost_usd": 0.0},
                "music_source": {"source_type": "none", "mood_direction": "轻快但不抢口播", "estimated_cost_usd": 0.0},
                "provider_rankings": {"video": [], "image": [], "tts": [], "music": []},
            },
            "cost_estimate": {"total_estimated_usd": 0.0,
                              "line_items": [{"tool": "自有素材", "operation": "研究与剪辑规划", "quantity": len(source_rows), "estimated_usd": 0.0}],
                              "budget_verdict": "no_budget_set"},
            "approval": {"status": "pending"},
            "metadata": {"template_id": plan_id, "input_mode": source_mode},
        }
        pp_env = _write(project, "proposal_packet", pp, sink=sink)
        return {"proposal_packet": pp_env, "creative_control_plan": ccp_env}
    ccp = {
        "version": "1.0",
        "project_id": project.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-director@1.0",
        "input_hashes": {
            "template_plan": str(_load(project / "artifacts" / "template_run_plan.json").get("artifact_sha256") or "a" * 64),
            "product_facts": str(facts.get("artifact_sha256") or "a" * 64),
            **({"differentiation_plan": str(differentiation_plan_ref.get("artifact_sha256"))}
               if isinstance(differentiation_plan_ref, dict) and differentiation_plan_ref.get("artifact_sha256") else {}),
        },
        **({"differentiation_plan_ref": dict(differentiation_plan_ref)} if isinstance(differentiation_plan_ref, dict) else {}),
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
    ccp_env = _write(project, "creative_control_plan", ccp, sink=sink)

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
        **({"differentiation_plan_ref": dict(differentiation_plan_ref)} if isinstance(differentiation_plan_ref, dict) else {}),
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
    source_mode, rows, directions = _source_led_research_context(project)
    if source_mode:
        first = rows[0]
        allowed = [str(value) for value in first.get("allowed_wording", []) if str(value).strip()]
        lead = allowed[0]
        hook = {
            "version": "1.0", "project_id": project.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hook_window_seconds": [0.0, min(1.5, float((first.get("source_time_range") or {}).get("end_seconds_exclusive") or 1.5))],
            "first_frame_visual": lead,
            "first_audio": f"口播首句「{lead}」",
            "promise": str(directions[0].get("promise") or lead),
            "proof_evidence": f"accepted 自有素材证据行 {first.get('matrix_row_id')} / {first.get('source_media_id')}",
            "hook_pattern": "result_first", "candidate_variants": [], "revision_round": 0,
        }
        return _write(project, "hook_plan", hook, sink=sink)
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
    source_mode, _rows, directions = _source_led_research_context(project)
    if source_mode:
        target_platform = _source_led_target_platform(project)
        options = []
        pool = list(directions[:3])
        while len(pool) < 3:
            pool.append(directions[0])
        for index, direction in enumerate(pool[:3], start=1):
            options.append({
                "option_id": f"c{index}",
                "label": str(direction.get("title") or direction["direction_id"]),
                "reason": str(direction.get("promise") or "自有素材证据闭环"),
                "score": round(0.9 - (index - 1) * 0.1, 2),
            })
        log["decisions"][1]["options_considered"][0].update(
            label="结构模板驱动",
            reason="只复用镜头顺序、景别、节奏与字幕处理，商品语义来自 source-led evidence rows",
        )
        log["decisions"][1]["reason"] = "source-led-template 仅消费结构先验，所有商品文案重新生成。"
        log["decisions"][2]["options_considered"] = options
        log["decisions"][2]["selected"] = "c1"
        log["decisions"][2]["reason"] = str(
            directions[0].get("promise") or "优先选择证据闭环最完整的方向"
        )
        platform_options = [
            {
                "option_id": "taobao",
                "label": "淘宝平台种草视频",
                "reason": "适配商品详情页主图视频的购买决策语境",
                "score": 0.95 if target_platform == "taobao" else 0.5,
            },
            {
                "option_id": "generic",
                "label": "通用竖版短视频",
                "reason": "跨平台兼容，但弱化淘宝详情页转化语境",
                "score": 0.8 if target_platform == "generic" else 0.5,
            },
            {
                "option_id": "tiktok",
                "label": "TikTok 短视频",
                "reason": "面向内容流量，不是当前商品详情页交付目标",
                "score": 0.2 if target_platform != "tiktok" else 0.9,
            },
        ]
        for option in platform_options:
            if option["option_id"] != target_platform:
                option["rejected_because"] = "不符合本项目已确认的发布平台"
        log["decisions"].append({
            "decision_id": f"{project.name}-platform-001",
            "stage": "proposal",
            "category": "concept_selection",
            "subject": "目标发布平台",
            "options_considered": platform_options,
            "selected": target_platform,
            "reason": "采用项目输入和运营人员确认的发布平台，不套用模板默认平台。",
            "user_visible": True,
            "confidence": 1.0,
        })
    return _write(project, "decision_log", log, sink=sink)


# ---------- script ----------

def rows_for_template(template_id: str) -> list[tuple[str, str, str]]:
    """口播行解析（本轮② 接线统一）：优先命名表 → 无表时按标定动作域生成（VLM 模板零接线）。"""
    rows = _NARRATION_BY_TEMPLATE.get(template_id)
    if rows:
        return list(rows)
    from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE

    acts = SLOT_ACTION_BY_TEMPLATE.get(template_id)
    if not acts:
        return list(_NARRATION_DEFAULT)
    generated = []
    for action in acts:
        if action in _ACTION_NARRATION:
            narr, copy = _ACTION_NARRATION[action]
        else:
            narr, copy = "", " "
        generated.append((narr, copy, "proof"))
    return generated


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


def _section_id_for_scene(scene_id: str) -> str:
    """Derive a stable section key from the explicit scene key, never position."""
    suffix = scene_id.removeprefix("scene-")
    return f"sec-{suffix}" if suffix else f"sec-{scene_id}"


def _source_led_matrix_rows(project: Path) -> tuple[str | None, dict[str, Mapping[str, Any]]]:
    matrix = _load(project / "artifacts" / "reference_source_matrix.json") or {}
    mode = matrix.get("matrix_mode")
    rows = {
        str(row.get("matrix_row_id")): row
        for row in matrix.get("rows", [])
        if isinstance(row, Mapping) and row.get("matrix_row_id")
    }
    return (str(mode) if mode in {"source_led", "source_led_template"} else None), rows


def _source_led_copy(
    mapping: Mapping[str, Any], rows_by_id: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str, dict[str, list[str]]]:
    evidence_ids = [
        str(value) for value in mapping.get("evidence_row_ids", []) if str(value).strip()
    ]
    if not evidence_ids and mapping.get("matrix_row_id"):
        evidence_ids = [str(mapping["matrix_row_id"])]
    if not evidence_ids:
        raise ValueError(f"scene {mapping.get('scene_id')!r} has no evidence_row_ids")
    rows = []
    for row_id in evidence_ids:
        row = rows_by_id.get(row_id)
        if row is None or row.get("resolution") != "accept":
            raise ValueError(f"scene {mapping.get('scene_id')!r} has unresolved evidence row {row_id!r}")
        rows.append(row)
    claim_ids = list(dict.fromkeys(
        str(value) for row in rows for value in row.get("claim_ids", []) if str(value).strip()
    ))
    action_keys = list(dict.fromkeys(
        str(value) for row in rows for value in row.get("action_keys", []) if str(value).strip()
    ))
    allowed = list(dict.fromkeys(
        str(value) for row in rows for value in row.get("allowed_wording", []) if str(value).strip()
    ))
    if not claim_ids or not action_keys or not allowed:
        raise ValueError(f"scene {mapping.get('scene_id')!r} evidence row is incomplete")
    visual_routes = {
        str(row.get("visual_route") or "owned_source") for row in rows
    }
    if len(visual_routes) != 1:
        raise ValueError(
            f"scene {mapping.get('scene_id')!r} cannot mix visual routes"
        )
    visual_route = next(iter(visual_routes))
    if visual_route == "omit":
        raise ValueError(f"scene {mapping.get('scene_id')!r} cannot use omitted evidence")
    propagated = {
        "claim_ids": claim_ids,
        "action_keys": action_keys,
        "evidence_row_ids": evidence_ids,
        "product_fact_refs": list(dict.fromkeys(
            str(value) for row in rows for value in row.get("product_fact_refs", [])
            if str(value).strip()
        )),
        "product_page_refs": list(dict.fromkeys(
            str(value) for row in rows for value in row.get("product_page_refs", [])
            if str(value).strip()
        )),
        "page_asset_ids": list(dict.fromkeys(
            str(value) for row in rows for value in row.get("page_asset_ids", [])
            if str(value).strip()
        )),
        "page_evidence_ids": list(dict.fromkeys(
            str(value) for row in rows for value in row.get("page_evidence_ids", [])
            if str(value).strip()
        )),
        "visual_route": visual_route,
        "claim_visual_requirements": dict(
            rows[0].get("claim_visual_requirements") or {}
        ),
        "generation_reference": (
            dict(rows[0]["generation_reference"])
            if isinstance(rows[0].get("generation_reference"), Mapping)
            else None
        ),
    }
    narration = allowed[0]
    screen_copy = allowed[1] if len(allowed) > 1 else allowed[0]
    return narration, screen_copy, propagated


def _source_led_rows_for_slots(
    slots: list[Mapping[str, Any]],
    run_plan: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Resolve every source-led slot to one explicit accepted evidence row.

    A media id can legitimately have multiple claim rows.  In that case the
    binding must name ``evidence_row_ids`` so scene planning never guesses
    which claim/copy contract the shot is meant to carry.
    """
    rows_by_id = {
        str(row.get("matrix_row_id") or ""): row
        for row in matrix.get("rows", [])
        if isinstance(row, Mapping) and row.get("resolution") == "accept"
    }
    rows_by_media: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows_by_id.values():
        rows_by_media.setdefault(str(row.get("source_media_id") or ""), []).append(row)
    bindings = {
        str(binding.get("slot_id") or ""): binding
        for binding in run_plan.get("slot_bindings", [])
        if isinstance(binding, Mapping)
    }
    resolved: dict[str, Mapping[str, Any]] = {}
    for slot in slots:
        slot_id = str(slot.get("slot_id") or "")
        binding = bindings.get(slot_id)
        if binding is None:
            raise ValueError(f"source-led slot {slot_id!r} has no explicit binding")
        explicit_ids = [
            str(value) for value in binding.get("evidence_row_ids", []) if str(value).strip()
        ]
        if not explicit_ids and binding.get("matrix_row_id"):
            explicit_ids = [str(binding["matrix_row_id"])]
        if explicit_ids:
            candidates = [rows_by_id.get(row_id) for row_id in explicit_ids]
            if len(candidates) != 1 or candidates[0] is None:
                raise ValueError(
                    f"source-led slot {slot_id!r} must bind exactly one accepted evidence row"
                )
        else:
            media_id = str(binding.get("source_media_id") or "")
            candidates = rows_by_media.get(media_id, [])
            if len(candidates) != 1:
                raise ValueError(
                    f"source-led slot {slot_id!r} has {len(candidates)} accepted rows for "
                    f"media {media_id!r}; bind evidence_row_ids explicitly"
                )
        row = candidates[0]
        visual_route = str(row.get("visual_route") or "owned_source")
        binding_source = str(binding.get("source") or "")
        if visual_route == "owned_source":
            if binding_source != "owned" or (
                str(binding.get("source_media_id") or "")
                != str(row.get("source_media_id") or "")
            ):
                raise ValueError(
                    f"source-led slot {slot_id!r} owned media does not match its evidence row"
                )
        elif visual_route == "generated_from_product_image":
            if (
                binding_source != "generate"
                or str(binding.get("source_media_id") or "").strip()
                or str(binding.get("asset_type") or "") != "generated_video"
            ):
                raise ValueError(
                    f"source-led slot {slot_id!r} generated route requires generated_video without source media"
                )
        else:
            raise ValueError(
                f"source-led slot {slot_id!r} cannot bind omitted evidence row"
            )
        resolved[slot_id] = row
    return resolved


def _source_led_interval(row: Mapping[str, Any], requested_duration: float) -> tuple[float, float]:
    source_range = row.get("source_time_range") or {}
    start = float(source_range.get("start_seconds") or 0.0)
    end = float(source_range.get("end_seconds_exclusive") or 0.0)
    if end <= start:
        raise ValueError(f"evidence row {row.get('matrix_row_id')!r} has an invalid source range")
    if row.get("requires_visible_result") is True:
        temporal = row.get("temporal_evidence")
        if not isinstance(temporal, Mapping):
            raise ValueError(
                f"evidence row {row.get('matrix_row_id')!r} requires before/action/result"
            )
        starts = [float((temporal.get(phase) or {}).get("start_seconds")) for phase in ("before", "action", "result")]
        ends = [float((temporal.get(phase) or {}).get("end_seconds_exclusive")) for phase in ("before", "action", "result")]
        return min(starts), max(ends)
    duration = min(max(requested_duration, 0.1), end - start)
    return start, start + duration


def _source_led_direction_for_row(
    row_id: str, synthesis: Mapping[str, Any]
) -> str:
    directions = [
        item for item in synthesis.get("differentiation_directions", [])
        if isinstance(item, Mapping) and str(item.get("direction_id") or "")
    ]
    for direction in directions:
        if row_id in direction.get("matrix_row_refs", []):
            return str(direction["direction_id"])
    if directions:
        return str(directions[0]["direction_id"])
    raise ValueError(f"evidence row {row_id!r} is not assigned to a research direction")


def _build_source_led_mappings(
    scenes: list[dict[str, Any]],
    slot_by_scene: Mapping[str, Mapping[str, Any]],
    assigned: Mapping[str, str],
    rows_by_slot: Mapping[str, Mapping[str, Any]],
    source_review: Mapping[str, Any],
    source_semantic_index: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    *,
    matrix_mode: str,
) -> list[dict[str, Any]]:
    reviewed = {
        str(item.get("media_id") or ""): item
        for item in source_review.get("files", [])
        if isinstance(item, Mapping) and item.get("reviewed") is True
    }
    semantic_by_media = {
        str(item.get("media_id") or ""): item
        for item in source_semantic_index.get("entries", [])
        if isinstance(item, Mapping) and str(item.get("media_id") or "")
    }
    mappings: list[dict[str, Any]] = []
    for scene in scenes:
        scene_id = str(scene.get("id") or "")
        slot = slot_by_scene.get(scene_id)
        if slot is None:
            raise ValueError(f"source-led scene {scene_id!r} has no template slot")
        slot_id = str(slot.get("slot_id") or "")
        row = rows_by_slot[slot_id]
        visual_route = str(row.get("visual_route") or "owned_source")
        row_id = str(row.get("matrix_row_id") or "")
        action_keys = [str(value) for value in row.get("action_keys", []) if str(value).strip()]
        claim_ids = [str(value) for value in row.get("claim_ids", []) if str(value).strip()]
        allowed = [str(value) for value in row.get("allowed_wording", []) if str(value).strip()]
        if not row_id or not action_keys or not claim_ids or not allowed:
            raise ValueError(f"source-led evidence row {row_id!r} is incomplete")
        reference_evidence = {"mode": "none"}
        if matrix_mode == "source_led_template":
            reference_evidence = {
                "mode": "structural_only",
                "mechanism": "仅沿用模板的镜头顺序、景别与字幕处理",
                "rationale": "商品语义、口播和证据时间窗全部由自有素材研究矩阵决定",
            }
        contract = {
            "script_section_id": _section_id_for_scene(scene_id),
            "claim_ids": claim_ids,
            "action_keys": action_keys,
            "evidence_row_ids": [row_id],
            "visual_route": visual_route,
            "claim_visual_requirements": dict(
                row.get("claim_visual_requirements") or {}
            ),
            "generation_reference": (
                dict(row["generation_reference"])
                if isinstance(row.get("generation_reference"), Mapping)
                else None
            ),
        }
        scene.update(contract)
        scene["description"] = allowed[0]
        scene["shot_intent"] = f"完整呈现 {'、'.join(action_keys)}；画面只支撑：{allowed[0]}"
        mapping = {
            "scene_id": scene_id,
            "template_slot_ref": slot_id,
            "timeline_interval": {
                "start_seconds": scene["start_seconds"],
                "end_seconds_exclusive": scene["end_seconds"],
            },
            "reference_evidence": reference_evidence,
            "matrix_row_id": row_id,
            "matrix_resolution_id": str(row.get("resolution") or ""),
            "research_direction_ref": _source_led_direction_for_row(row_id, synthesis),
            **contract,
        }
        if visual_route == "owned_source":
            media_id = str(assigned.get(slot_id) or "")
            source = reviewed.get(media_id)
            if source is None or not str(source.get("path") or ""):
                raise ValueError(
                    f"source-led evidence {media_id!r} is not a reviewed owned source"
                )
            semantic = semantic_by_media.get(media_id)
            crop_safety = semantic.get("crop_safety") if isinstance(semantic, Mapping) else None
            if not isinstance(crop_safety, Mapping):
                raise ValueError(f"source-led evidence {media_id!r} is missing crop safety evidence")
            if crop_safety.get("subject_complete_in_3_4") is not True:
                raise ValueError(f"source-led evidence {media_id!r} is not complete in 3:4")
            safe_regions = [
                str(value) for value in crop_safety.get("safe_caption_regions", [])
                if str(value).strip()
            ]
            if not safe_regions:
                raise ValueError(f"source-led evidence {media_id!r} has no caption-safe region")
            source_start, source_end = _source_led_interval(
                row, float(scene["end_seconds"]) - float(scene["start_seconds"])
            )
            mapping.update({
                "source_path": str(source["path"]),
                "source_interval": {
                    "start_seconds": round(source_start, 3),
                    "end_seconds_exclusive": round(source_end, 3),
                },
                "source_hash": str(row.get("source_hash") or ""),
                "reference_basis": "source-led 自有素材研究矩阵",
                "source_fit": f"动作 {'、'.join(action_keys)} 与证据行逐项一致",
                "mapping_reason": f"使用 accepted owned evidence row {row_id}",
                "originality_note": "商品、动作和文案均来自本项目自有素材；模板只提供结构先验",
                "subject_completeness": "complete",
                "crop_strategy": "center crop with protected subject bounds",
                "caption_safe_zone": safe_regions[0],
            })
        elif visual_route == "generated_from_product_image":
            generation_reference = mapping.get("generation_reference")
            generation_spec = row.get("generation_spec")
            if not isinstance(generation_reference, Mapping) or not isinstance(generation_spec, Mapping):
                raise ValueError(
                    f"source-led generated evidence row {row_id!r} requires generation reference and spec"
                )
            mapping.update({
                "generation_spec": dict(generation_spec),
                "reference_basis": "商品页事实声明 + 已审核纯产品参考图",
                "source_fit": "无合格自有素材；使用图生视频表达，不作为商品事实证明",
                "mapping_reason": str(row.get("route_reason") or "图生视频补足视觉缺口"),
                "originality_note": "产品身份来自本商品参考图；模板只提供结构先验",
                "subject_completeness": "planned_for_generation",
                "crop_strategy": "generate for 3:4 protected product safe area",
                "caption_safe_zone": "top",
            })
        else:
            raise ValueError(f"source-led evidence row {row_id!r} is omitted")
        mappings.append(mapping)
    return mappings


def _source_led_beat_role(position: int, total: int) -> str:
    if position == 1:
        return "hook"
    if position == total:
        return "cta"
    if position == 2:
        return "reveal"
    if total >= 5 and position == total - 1:
        return "payoff"
    return "proof"


# 每动作的兜底口播（模板文案表里该动作行已被用完时使用；保证 口播动作 == 素材动作）。
_ACTION_NARRATION: dict[str, tuple[str, str]] = {
    "防油易擦拭": ("油污汤汁，一擦就净。", "油污 · 一擦即净"),
    "无甲醛检测": ("0 甲醛，检测报告为证。", "0 甲醛 · 报告可查"),
    "桌角对齐-挤压不变形": ("软玻璃贴合桌面，不翘边。", "贴合 · 不翘边"),
    "自动铺开对齐": ("自动铺开，轻松对齐。", "自动铺开 · 对齐省事"),
    "防刮": ("耐磨防刮，久用如新。", "耐刮耐磨 · 久用如新"),
    "餐桌场景": ("餐桌省心，质感如新。", "餐桌 · 省心好物"),
}


def build_script(project: Path, template: dict, sp: dict, ccp: dict, facts: dict, *,
                 approved: bool = False, title: str | None = None, sink=None) -> dict:
    # 逐镜对齐：narration/花字必须与该 scene 绑定的素材画面一致（主链路语义）。
    # 关键：**narration 由素材动作派生**，不同模板 archetype 用各自的逐镜文案表，
    # 绝不套用 video1 的 8 镜（导致长模板 9+ 镜空口播）。
    tid = str(template.get("template_id") or "")
    rows = rows_for_template(tid)
    sections = []
    from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE

    row_actions = SLOT_ACTION_BY_TEMPLATE.get(tid) or []
    used_rows: set[int] = set()
    source_led_mode, evidence_rows = _source_led_matrix_rows(project)
    mapping_by_scene = {
        str(mapping.get("scene_id")): mapping
        for mapping in ((sp.get("metadata") or {}).get("source_mapping") or [])
        if isinstance(mapping, Mapping) and mapping.get("scene_id")
    }

    def _row_action(pos: int, narr: str, copy: str) -> str:
        """该表格行的动作 key：逐模板显式表优先（作者标定），否则文本打分回退。"""
        return row_actions[pos] if pos < len(row_actions) else _text_action_key(narr, copy)

    def _pick_row(bound: str):
        # 1) 未用且动作精确匹配的表格行（行动作 = 逐模板显式表；与绑定同源，故事线不垮）
        for pos in range(len(rows)):
            if pos in used_rows:
                continue
            narr, copy, role = rows[pos] if len(rows[pos]) >= 3 else ("", "", "proof")
            if bound and _row_action(pos, narr, copy) == bound and narr.strip():
                used_rows.add(pos)
                return pos, narr, copy, role, _row_action(pos, narr, copy)
        # 2) 表格行耗尽 → 该动作的兜底口播（保证 口播动作 == 素材动作，绝不跨动作错配）
        if bound and bound in _ACTION_NARRATION:
            narr, copy = _ACTION_NARRATION[bound]
            return None, narr, copy, "proof", bound
        # 3) 无绑定信息（审计环境）→ 表内第一个未用行
        for pos in range(len(rows)):
            if pos in used_rows:
                continue
            narr, copy, role = rows[pos] if len(rows[pos]) >= 3 else ("", "", "proof")
            if narr.strip():
                used_rows.add(pos)
                return pos, narr, copy, role, _row_action(pos, narr, copy)
        return None, "", "", "proof", ""

    for i, scene in enumerate(sp["scenes"], start=1):
        bound = _bound_action(sp, scene)
        span = float(scene["end_seconds"]) - float(scene["start_seconds"])
        evidence_contract: dict[str, Any] = {}
        visual_intent = "V8 自有素材 + 模板指定花字处理"
        evidence_requirements = ["0甲醛 需检测报告作为证据"]
        if source_led_mode:
            mapping = mapping_by_scene.get(str(scene.get("id") or ""))
            if mapping is None:
                raise ValueError(f"scene {scene.get('id')!r} has no explicit source mapping")
            narr, copy, evidence_contract = _source_led_copy(
                mapping, evidence_rows
            )
            role = _source_led_beat_role(i, len(sp["scenes"]))
            text_action = evidence_contract["action_keys"][0]
            bound = text_action
            aligned = True
            evidence_row_ids = evidence_contract["evidence_row_ids"]
            selected_rows = [evidence_rows[row_id] for row_id in evidence_row_ids]
            evidence_requirements = list(dict.fromkeys(
                str(row.get("required_evidence_class") or row.get("evidence_class") or "")
                for row in selected_rows
                if str(row.get("required_evidence_class") or row.get("evidence_class") or "").strip()
            ))
            if any(row.get("requires_visible_result") is True for row in selected_rows):
                evidence_requirements.append("必须看见动作前、动作中和结果态")
            visual_intent = str(scene.get("shot_intent") or scene.get("description") or "")
            pacing = (
                "保留完整动作前、动作中与结果态，不为模板节拍截断证据"
                if any(row.get("requires_visible_result") is True for row in selected_rows)
                else "一镜一证据，口播在动作可见时进入"
            )
            control_rule_refs = [
                "creative_control_plan.content_direction",
                "creative_control_plan.fact_continuity",
                "reference_source_matrix.allowed_wording",
            ]
        elif span < 1.0:
            # 闪帧卡位（0.1-0.5s）：物理放不下口播（voice-timeline-fit 会 overflow），
            # 只保留花字收尾，绝不硬塞一句导致 TTS 阻断（评审 P1-6 联动）。
            narr, copy, role = "", "", "cta"
            for row in rows:
                if len(row) >= 2 and not str(row[0] or "").strip():
                    copy = str(row[1] or "")
                    break
            if not copy:
                copy = "直播间见"
            text_action = ""
            aligned = True  # 无口播即无语义冲突
            pacing = "闪帧收尾"
            control_rule_refs = []
        else:
            pos, narr, copy, role, text_action = _pick_row(bound)
            aligned = bool(bound and text_action == bound)
            pacing = "按模板节拍推进"
            control_rule_refs = []
        sections.append({
            "id": str(scene.get("script_section_id") or _section_id_for_scene(str(scene.get("id") or ""))),
            "label": f"beat-{i}", "text": narr, "narration": narr,
            "scene_id": str(scene.get("id") or ""),
            "screen_copy": copy,
            "section_goal": (
                f"用 accepted 证据呈现 {'、'.join(evidence_contract.get('action_keys', []))}"
                if source_led_mode else f"第 {i} 个模板 slot 动作"
            ),
            "beat_role": role,
            "viewer_state": {"hook": "好奇", "reveal": "被揭晓", "proof": "信服", "cta": "行动",
                             "problem": "疑虑", "escalation": "被放大", "payoff": "被解决", "other": ""}[role],
            "start_seconds": scene["start_seconds"], "end_seconds": scene["end_seconds"],
            "visual_intent": visual_intent,
            "evidence_requirements": evidence_requirements if role not in ("", "cta") else [],
            "pacing": pacing,
            "control_rule_refs": control_rule_refs,
            "review": "pending",
            "feedback": "",
            "source_ref": "product_facts",
            # 语义对齐审计字段：口播动作 key 必须等于所绑素材动作 key。
            "narration_action_key": text_action,
            "bound_material_action": bound,
            "narration_material_aligned": aligned,
            **evidence_contract,
        })
    sc = {
        "version": "1.0",
        "script_id": str(template.get("template_id")),
        "script_version": 1, "status": ("approved" if approved else "draft"),
        "creative_control_ref": {"plan_id": str(template.get("template_id")), "plan_version": ccp.get("plan_version", 1),
                                 "artifact_sha256": str(ccp.get("artifact_sha256") or "a" * 64)},
        "title": title or (
            _source_led_product_display_name(facts, project.name)
            if source_led_mode else "透明桌垫 · 餐桌省心好物"
        ),
        "total_duration_seconds": sp["scenes"][-1]["end_seconds"],
        "voice_performance": {"performance_intent": "清晰、节奏明快种草腔", "pacing_profile": "energetic",
                              "energy_curve": "先扬后收", "pause_policy": "每句独立", "sample_section_id": "sec-001"},
        "sections": sections,
        "metadata": {"template_id": str(template.get("template_id")),
                     "fact_card_ref": {"name": "product_facts", "path": "artifacts/product_facts.json"},
                     **({"target_platform": _source_led_target_platform(project)} if source_led_mode else {}),
                     **({
                         "beat_map": [section["beat_role"] for section in sections],
                         "primary_claim_id": sections[0]["claim_ids"][0],
                         "template_text_usage": "analysis_only",
                     } if source_led_mode and sections else {})},
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
    matrix = _load(project / "artifacts" / "reference_source_matrix.json") or {}
    matrix_mode = matrix.get("matrix_mode")
    source_led_mode = matrix_mode in {"source_led", "source_led_template"}
    assigned = match_run_plan(
        slots,
        rp,
        preserve_existing=source_led_mode,
    )
    source_led_rows = (
        _source_led_rows_for_slots(slots, rp, matrix) if source_led_mode else {}
    )
    # reviewed owned source 路径（scene_plan 硬门要求 source_path ∈ source_media_review）
    source_review_urls: dict[str, str] = {}
    smr = _load(project / "artifacts" / "source_media_review.json") or {}
    for f in smr.get("files", []):
        if f.get("reviewed"):
            source_review_urls[Path(f["path"]).stem] = f["path"]
    # 研究链 grounding：素材 ↔ matrix row 桥接（scene_plan 硬门要求 matrix_row_id/resolution）
    grounding = resolve_matrix_grounding(smr, matrix)
    ccp_direction = str(((ccp or {}).get("sections") or {}).get("content_direction") or "")
    research_direction = "direction-proof-chain"  # proof-first 适配方向（来自共享 research_synthesis）
    scenes, cursor = [], 0.0
    for idx, slot in enumerate(slots):
        sid = str(slot.get("slot_id") or "")
        dur = float(slot.get("duration_s") or 2.0)
        if source_led_mode and str(
            source_led_rows[sid].get("visual_route") or "owned_source"
        ) == "owned_source":
            source_start, source_end = _source_led_interval(source_led_rows[sid], dur)
            dur = source_end - source_start
        ci = resolve_caption_recipe_intent(None, slot.get("caption_treatment"))
        row = source_led_rows.get(sid)
        allowed = [str(value) for value in (row or {}).get("allowed_wording", []) if str(value).strip()]
        action_keys = [str(value) for value in (row or {}).get("action_keys", []) if str(value).strip()]
        description = (
            allowed[0] if source_led_mode and allowed else scene_description(idx, slot)
        )
        shot_intent = (
            f"完整呈现 {'、'.join(action_keys)}；画面只支撑：{allowed[0]}"
            if source_led_mode and allowed and action_keys
            else str(slot.get("dialogue") or "")[:120] or f"按模板 slot {sid}"
        )
        scenes.append({
            "id": f"scene-{sid.rsplit('-slot-')[-1]}", "type": "broll",
            "description": description,
            "start_seconds": round(cursor, 3), "end_seconds": round(cursor + dur, 3),
            "shot_language": {"shot_size": SHOT_SIZE.get(str((slot.get("shot_language") or {}).get("shot_size") or ""), "medium"),
                              "camera_movement": CAMERA.get(str((slot.get("shot_language") or {}).get("camera_movement") or ""), "static")},
            "shot_intent": shot_intent,
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
    if source_led_mode:
        source_semantic_index = _load(
            project / "artifacts" / "source_semantic_index.json"
        ) or {}
        synthesis = _load(project / "artifacts" / "research_synthesis.json") or {
            "differentiation_directions": [{
                "direction_id": research_direction,
                "matrix_row_refs": [
                    str(row.get("matrix_row_id") or "") for row in source_led_rows.values()
                ],
            }]
        }
        source_mapping = _build_source_led_mappings(
            scenes, slot_by_scene, assigned, source_led_rows, smr,
            source_semantic_index, synthesis,
            matrix_mode=str(matrix_mode),
        )
    else:
        source_mapping = build_source_mappings(
            scenes,
            slot_by_scene,
            assigned,
            source_review_urls=source_review_urls,
            grounding=grounding,
            research_direction=research_direction,
        )
    if source_led_mode:
        rows_by_id = {
            str(row.get("matrix_row_id")): row
            for row in matrix.get("rows", [])
            if isinstance(row, Mapping) and row.get("matrix_row_id")
        }
        scenes_by_id = {str(scene.get("id")): scene for scene in scenes}
        for mapping in source_mapping:
            scene_id = str(mapping.get("scene_id") or "")
            row_id = str(mapping.get("matrix_row_id") or "")
            row = rows_by_id.get(row_id)
            if row is None or row.get("resolution") != "accept":
                raise ValueError(
                    f"source-led scene {scene_id!r} requires an accepted canonical evidence row"
                )
            contract = {
                "script_section_id": _section_id_for_scene(scene_id),
                "claim_ids": list(row.get("claim_ids") or []),
                "action_keys": list(row.get("action_keys") or []),
                "evidence_row_ids": [row_id],
                "product_fact_refs": list(row.get("product_fact_refs") or []),
                "product_page_refs": list(row.get("product_page_refs") or []),
                "page_asset_ids": list(row.get("page_asset_ids") or []),
                "page_evidence_ids": list(row.get("page_evidence_ids") or []),
                "visual_route": str(row.get("visual_route") or "owned_source"),
                "claim_visual_requirements": dict(
                    row.get("claim_visual_requirements") or {}
                ),
                "generation_reference": (
                    dict(row["generation_reference"])
                    if isinstance(row.get("generation_reference"), Mapping)
                    else None
                ),
            }
            if not contract["claim_ids"] or not contract["action_keys"]:
                raise ValueError(f"source-led evidence row {row_id!r} is incomplete")
            mapping.update(contract)
            if contract["visual_route"] == "owned_source":
                mapping["source_hash"] = str(row.get("source_hash") or "")
            else:
                for field in ("source_path", "source_interval", "source_hash"):
                    mapping.pop(field, None)
            if matrix_mode == "source_led":
                mapping["reference_evidence"] = {"mode": "none"}
            scene = scenes_by_id.get(scene_id)
            if scene is None:
                raise ValueError(f"source mapping references unknown scene {scene_id!r}")
            scene.update(contract)
    slot_ref_map = {m["scene_id"]: m["template_slot_ref"] for m in source_mapping}
    sp = {
        "version": "1.0", "caption_policy_version": "1.0",
        "creative_control_ref": {"plan_id": str(template.get("template_id")), "plan_version": ccp.get("plan_version", 1),
                                 "artifact_sha256": str(ccp.get("artifact_sha256") or "a" * 64)},
        "scenes": scenes,
        "metadata": {"template_id": str(template.get("template_id")),
                     "template_pack_ref": "projects/template-pack-library/artifacts/template_pack.json",
                     "run_plan_ref": f"projects/{project.name}/artifacts/template_run_plan.json",
                     "reference_media_usage": (
                         "not_applicable"
                         if matrix_mode in {"source_led", "source_led_template"}
                         else "analysis_only"
                     ),
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

def approve_ccp(
    project: Path,
    *,
    locked_by: str = "operator",
    pipeline_dir: Path | None = None,
    sink=None,
) -> dict:
    """把 creative_control_plan 锁定为 approved（模拟人工确认导演总控单）。"""
    p = project / "artifacts" / "creative_control_plan.json"
    ccp = _load(p)
    if not ccp:
        raise SystemExit("creative_control_plan.json not found; run proposal first")
    locked_at = datetime.now(timezone.utc).isoformat()
    ccp["status"] = "approved"
    ccp["locked_at"] = locked_at
    ccp["locked_by"] = locked_by
    ccp["section_reviews"] = {k: "approved" for k in ccp.get("sections", {})}
    env = _write(project, "creative_control_plan", ccp, sink=sink)
    proposal = _load(project / "artifacts" / "proposal_packet.json")
    if proposal:
        embedded = proposal.get("creative_control_plan") or {}
        embedded.update({
            "status": "approved",
            "locked_at": locked_at,
            "locked_by": locked_by,
            "section_reviews": dict(ccp["section_reviews"]),
        })
        if ccp.get("target_platform"):
            embedded["target_platform"] = ccp["target_platform"]
        proposal["creative_control_plan"] = embedded
        proposal["approval"] = {"status": "approved"}
        _write(project, "proposal_packet", proposal, sink=sink)
    # 重写制品后，刷新所有 checkpoint 里的信封，避免后续 stage 校验报 envelope drift。
    if sink is None:
        from lib.checkpoint import refresh_checkpoint_envelopes
        refresh_checkpoint_envelopes(pipeline_dir or ROOT / "projects", project.name, pipeline_type=PIPELINE)
    return env


def advance_run_full(
    run: str,
    *,
    pipeline_dir: Path | None = None,
    pack: dict | None = None,
    approve_control_plan: bool = False,
    approve_script: bool = False,
) -> list[str]:
    """主链路推进一条 template run 到 scene_plan（含 ccp/script 人工锁定）。

    顺序：proposal + CCP(draft) →（显式 approve_control_plan）→
    script(awaiting_human) →（显式 approve_script）→ scene_plan。
    每个人工门至少跨一次调用，不能用一个命令跳过两道审批。
    """
    project = (pipeline_dir or PROJECTS) / run
    PDIR = pipeline_dir or PROJECTS
    from lib.checkpoint import get_completed_stages
    template_id = str((_load(project / "artifacts" / "template_run_plan.json") or {}).get("template_id") or "")
    template = _template_for_project(project, template_id, pack=pack)
    facts = _load(project / "artifacts" / "product_facts.json") or {}
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}
    operator_managed = (project / "operator" / "operator-managed").exists()
    if operator_managed:
        from backlot.project_commit import ProjectCommitStore
    if "proposal" not in get_completed_stages(PDIR, run, PIPELINE):
        if template is None:
            raise SystemExit(f"template {template_id} not in pack")
        if operator_managed:
            with ProjectCommitStore(project).transaction(action={"action_id": f"advance-proposal-{run}"}) as sink:
                envs = build_proposal(project, template, facts, sink=sink)
                envs["hook_plan"] = build_hook_plan(project, template, facts, sink=sink)
                envs["decision_log"] = build_decision_log(project, template, facts, sink=sink)
                envs["template_run_plan"] = write_artifact_atomic(
                    "artifacts/template_run_plan.json", "template_run_plan", rp,
                    project_dir=project, sink=sink,
                )
                write_checkpoint(PDIR, run, "proposal", "completed", envs,
                                 pipeline_type=PIPELINE, next_action=None,
                                 review={"findings": [], "verdict": "pass"}, sink=sink)
        else:
            envs = build_proposal(project, template, facts)
            envs["hook_plan"] = build_hook_plan(project, template, facts)
            envs["decision_log"] = build_decision_log(project, template, facts)
            envs["template_run_plan"] = write_artifact_atomic(
                "artifacts/template_run_plan.json", "template_run_plan", rp,
                project_dir=project,
            )
            write_checkpoint(PDIR, run, "proposal", "completed", envs,
                             pipeline_type=PIPELINE, next_action=None,
                             review={"findings": [], "verdict": "pass"})
    ccp = _load(project / "artifacts" / "creative_control_plan.json") or {}
    if ccp.get("status") != "approved":
        if approve_script:
            raise SystemExit(
                f"{run}: creative_control_plan 尚未人工确认；"
                "不能用 approve_script 跳过导演总控单审批"
            )
        if not approve_control_plan:
            return get_completed_stages(PDIR, run, PIPELINE)
        if operator_managed:
            with ProjectCommitStore(project).transaction(action={"action_id": f"approve-ccp-{run}"}) as sink:
                approve_ccp(project, locked_by="operator", pipeline_dir=PDIR, sink=sink)
            from lib.checkpoint import refresh_checkpoint_envelopes
            with ProjectCommitStore(project).transaction(action={"action_id": f"refresh-ccp-{run}"}) as sink:
                refresh_checkpoint_envelopes(PDIR, run, pipeline_type=PIPELINE, sink=sink)
        else:
            approve_ccp(project, locked_by="operator", pipeline_dir=PDIR)
        ccp = _load(project / "artifacts" / "creative_control_plan.json") or {}
    if "script" not in get_completed_stages(PDIR, run, PIPELINE):
        script_checkpoint = _load(project / "checkpoint_script.json") or {}
        if script_checkpoint.get("status") != "awaiting_human":
            sp_data = scene_plan_data(project, template, rp, ccp, facts)
            if operator_managed:
                with ProjectCommitStore(project).transaction(action={"action_id": f"draft-script-{run}"}) as sink:
                    sc_env = build_script(project, template, sp_data, ccp, facts, approved=False, sink=sink)
                    write_checkpoint(
                        PDIR, run, "script", "awaiting_human", {"script": sc_env},
                        pipeline_type=PIPELINE,
                        next_action={
                            "summary": "script 已生成，等待人工确认后继续 scene_plan",
                            "verb": "await_user",
                            "context_refs": ["artifacts/script.json", "artifacts/creative_control_plan.json"],
                        },
                        human_approved=False,
                        sink=sink,
                    )
            else:
                sc_env = build_script(project, template, sp_data, ccp, facts, approved=False)
                write_checkpoint(
                    PDIR, run, "script", "awaiting_human", {"script": sc_env},
                    pipeline_type=PIPELINE,
                    next_action={
                        "summary": "script 已生成，等待人工确认后继续 scene_plan",
                        "verb": "await_user",
                        "context_refs": ["artifacts/script.json", "artifacts/creative_control_plan.json"],
                    },
                    human_approved=False,
                )
            if operator_managed:
                from backlot.operator_reviews import ReviewService
                ReviewService(project).ensure_script_review_for_checkpoint()
            return get_completed_stages(PDIR, run, PIPELINE)
        if not approve_script:
            return get_completed_stages(PDIR, run, PIPELINE)
        sp_data = scene_plan_data(project, template, rp, ccp, facts)
        if operator_managed:
            with ProjectCommitStore(project).transaction(action={"action_id": f"approve-script-{run}"}) as sink:
                sc_env = build_script(project, template, sp_data, ccp, facts, approved=True, sink=sink)
                write_checkpoint(PDIR, run, "script", "completed", {"script": sc_env},
                                 pipeline_type=PIPELINE, next_action=None,
                                 human_approved=True, sink=sink)
        else:
            sc_env = build_script(project, template, sp_data, ccp, facts, approved=True)
            write_checkpoint(PDIR, run, "script", "completed", {"script": sc_env},
                             pipeline_type=PIPELINE, next_action=None, human_approved=True)
    if "scene_plan" not in get_completed_stages(PDIR, run, PIPELINE):
        ccp = _load(project / "artifacts" / "creative_control_plan.json")
        if operator_managed:
            with ProjectCommitStore(project).transaction(action={"action_id": f"advance-scene-plan-{run}"}) as sink:
                sp_env = build_scene_plan(project, template, rp, ccp, facts, sink=sink)
                write_checkpoint(PDIR, run, "scene_plan", "completed", {"scene_plan": sp_env},
                                 pipeline_type=PIPELINE, next_action=None, sink=sink)
        else:
            sp_env = build_scene_plan(project, template, rp, ccp, facts)
            write_checkpoint(PDIR, run, "scene_plan", "completed", {"scene_plan": sp_env},
                             pipeline_type=PIPELINE, next_action=None)
    return get_completed_stages(PDIR, run, PIPELINE)


def advance_to_assets(run: str, *, pipeline_dir: Path | None = None,
                      output_profile: str | None = None,
                      approve_script: bool = False) -> str:
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
        advance_run_full(run, pipeline_dir=PDIR, approve_script=approve_script)
        if "scene_plan" not in get_completed_stages(PDIR, run, PIPELINE):
            raise SystemExit(
                f"{run}: script 尚未完成人工确认，禁止进入 assets；"
                "请先确认 script 后以 approve_script=True 继续。"
            )
    # run_plan 批准硬门：不在此自动批准（评审 P1-8）。
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}
    if str(rp.get("status") or "") != "approved":
        raise SystemExit(
            f"{run}: template_run_plan 未批准（status={rp.get('status') or '未决'}），"
            f"禁止进入 paid assets。请先审批 run_plan（决策记录 batch_approval 后落盘 status=approved）。"
        )
    template_id = str((_load(project / "artifacts" / "template_run_plan.json") or {}).get("template_id") or "")
    template = _template_for_project(project, template_id)
    if template is None:
        raise SystemExit(f"template {template_id} not found in run-local or global template pack")
    # 项目写入契约：写制品与 checkpoint 必须经版本事务（sink）。
    from backlot.operator_reviews import ReviewService
    from backlot.project_commit import ProjectCommitStore

    store = ProjectCommitStore(project)
    reviews = ReviewService(project, store=store)
    with store.transaction(action={"action_id": f"advance-assets-{run}"}) as sink:
        envs = build_assets(project, template, pipeline_dir=PDIR, sink=sink,
                            output_profile=output_profile)
        bundle = envs["approval_bundle"]["data"]
        write_checkpoint(PDIR, run, "assets", "awaiting_human", envs, pipeline_type=PIPELINE,
                         next_action={"summary": "assets 待审批（全 owned，无 paid 生成）", "verb": "await_user",
                                      "context_refs": ["artifacts/shot_execution_plan.json", "artifacts/asset_plan.json"]},
                         sink=sink)
        reviews.stage_create(
            sink,
            kind="creative_lock",
            subject_id=str(bundle["bundle_id"]),
            subject_version=int(bundle["bundle_version"]),
            subject_hash=str(envs["approval_bundle"]["semantic_sha256"]),
            submitted_by="cinematic-fast-assets",
            approval_scope=str(bundle.get("approval_scope") or "") or None,
            approval_subject_hashes=[
                str(value) for value in bundle.get("approval_subject_hashes") or []
            ],
        )
    from lib.checkpoint import get_next_stage
    return str(get_next_stage(PDIR, run, PIPELINE) or "none")


def rebuild_aligned_run(run: str, *, pipeline_dir: Path | None = None) -> None:
    """用修正后的语义窗口重写 draft script，并重新打开人工门。

    用于：早期用旧（关键词+索引硬对齐 + 静默复用）逻辑推进到 scene_plan 的 run。
    新语义意味着旧人工批准已经失效，因此本函数绝不继承 approved 状态，也不重建
    scene_plan。它写入新的 draft script/awaiting_human checkpoint，并原子失效所有
    script 下游 checkpoint；人工重新确认后才可继续。不改 research/proposal，不触发付费。
    """
    PDIR = pipeline_dir or PROJECTS
    project = PDIR / run
    template_id = str((_load(project / "artifacts" / "template_run_plan.json") or {}).get("template_id") or "")
    template = _template_for_project(project, template_id)
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
    store = ProjectCommitStore(project)
    operator_managed = (project / "operator" / "operator-managed").exists()
    try:
        with store.transaction(action={"action_id": f"rebuild-script-{run}"}) as sink:
            rp2 = json.loads(json.dumps(rp))
            matrix = _load(project / "artifacts" / "reference_source_matrix.json") or {}
            match_run_plan(
                template.get("slots") or [], rp2,
                preserve_existing=matrix.get("matrix_mode") in {"source_led", "source_led_template"},
            )
            write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp2, project_dir=project, sink=sink)
            sp = scene_plan_data(project, template, rp2, ccp, facts)
            sc_env = build_script(project, template, sp, ccp, facts, approved=False, sink=sink)
            for stage in ("scene_plan", "assets", "sample", "edit", "compose", "publish"):
                sink.stage_delete(f"checkpoint_{stage}.json")
            sink.stage_delete("artifacts/scene_plan.json")
            write_checkpoint(
                PDIR, run, "script", "awaiting_human", {"script": sc_env},
                pipeline_type=PIPELINE, human_approved=False,
                next_action={
                    "summary": "语义对齐已重建，script 等待重新人工确认",
                    "verb": "await_user",
                    "context_refs": ["artifacts/script.json", "artifacts/reference_source_matrix.json"],
                },
                sink=sink,
            )
            if operator_managed:
                from backlot.operator_reviews import ReviewService

                reviews = ReviewService(project, store=store)
                reviews.stage_supersede_pending(
                    sink,
                    kinds={"creative_lock", "sample"},
                    decided_by="cinematic-fast-rebuild",
                    reason="上游语义或脚本已重建，下游审核失效",
                )
                reviews.stage_create(
                    sink,
                    kind="script_lock",
                    subject_id="script-v1",
                    subject_version=1,
                    subject_hash=str(sc_env["semantic_sha256"]),
                    submitted_by="cinematic-fast-rebuild",
                )
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


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-01-video1-aks-zhuodian")
    p.add_argument("--approve-control-plan", action="store_true")
    p.add_argument("--approve-script", action="store_true")
    args = p.parse_args()
    done = advance_run_full(
        args.run,
        approve_control_plan=args.approve_control_plan,
        approve_script=args.approve_script,
    )
    print("advanced:", done)


if __name__ == "__main__":
    main()

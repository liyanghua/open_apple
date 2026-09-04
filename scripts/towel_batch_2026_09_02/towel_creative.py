"""毛巾批量混剪 2026-09-02 — 创作数据（商品事实 + 16 条模板脚本）。

4 产品 × 4 钩子方向（测评证明/痛点反转/卖点罗列/场景种草），每条 12 镜、约 28.5~30s。
口播与花字按"动作-画面一致性"原则起草：每镜 narration 必须能被该镜绑定的素材动作域证明。
事实口径：仅采用素材画面可见文字（包装/吊牌）+ 产品名；价格/SKU 未知，script 门请用户确认。
"""

PRODUCT_KEYS = ["yinlizi", "tiansi", "chenxu", "yujin"]

PRODUCTS = {
    "yinlizi": {
        "name": "银离子毛巾",
        "slug": "yinlizi",
        "facts": {
            "product_name": "银离子毛巾",
            "claims": [
                {"claim": "银离子抗菌，久用少异味", "evidence_ref": "素材 抗菌标识 1 段（包装标识文字）", "status": "draft"},
                {"claim": "吸水快干", "evidence_ref": "素材 吸水演示 2 段（倒水/擦拭画面）", "status": "draft"},
                {"claim": "亲肤柔软", "evidence_ref": "素材 亲肤柔软 5 段（贴肤/揉搓画面）", "status": "draft"},
                {"claim": "克重足、厚实", "evidence_ref": "素材 厚度克重 1 段（称重画面 0.00 克）", "status": "draft"},
            ],
            "params": {"尺寸": None, "克重": None, "材质": "未在画面明确"},
            "sku": None,
            "price": None,
            "notes": "银离子抗菌为功效表述：仅按包装标识文字口径，检测报告/抑菌率数字未见于素材，未写入文案；如需投放放大请先补资质。",
        },
    },
    "tiansi": {
        "name": "天丝莱赛尔毛巾",
        "slug": "tiansi",
        "facts": {
            "product_name": "天丝莱赛尔毛巾",
            "claims": [
                {"claim": "天丝莱赛尔纤维，丝滑亲肤", "evidence_ref": "素材 材质细节 6 段 + 画面 LEICOUT 字样", "status": "draft"},
                {"claim": "吸水速干", "evidence_ref": "素材 吸水演示 4 段", "status": "draft"},
                {"claim": "顺滑不扎、敏感肌友好", "evidence_ref": "素材 亲肤柔软 4 段", "status": "draft"},
                {"claim": "轻薄透气", "evidence_ref": "素材 厚度克重 1 段 + 材质细节", "status": "draft"},
            ],
            "params": {"尺寸": None, "克重": None, "材质": "天丝莱赛尔（兰精纤维品牌，画面 LEICOUT 字样待确认）"},
            "sku": None,
            "price": None,
            "notes": "“天丝”为纤维品牌名：文案口径与商品页一致后再投流；LEICOUT 字样来源待 script 门确认。",
        },
    },
    "chenxu": {
        "name": "沉序毛巾",
        "slug": "chenxu",
        "facts": {
            "product_name": "沉序毛巾",
            "claims": [
                {"claim": "阿克苏长绒棉、100%棉", "evidence_ref": "素材画面文字「阿克苏长绒棉 7A级抗菌 100%棉 80cm×40cm」", "status": "draft"},
                {"claim": "7A级抗菌", "evidence_ref": "素材画面文字「7A级抗菌」（抗菌标识 3 段）", "status": "draft"},
                {"claim": "无荧光", "evidence_ref": "素材画面文字「无荧光长绒棉」", "status": "draft"},
                {"claim": "80cm×40cm 大尺寸", "evidence_ref": "素材画面文字「80cm×40cm」+ 尺寸对比 2 段", "status": "draft"},
                {"claim": "吸水快", "evidence_ref": "素材 吸水演示 4 段", "status": "draft"},
            ],
            "params": {"尺寸": "80cm×40cm（画面文字）", "克重": None, "材质": "100%棉 阿克苏长绒棉（画面文字）"},
            "sku": None,
            "price": None,
            "notes": "7A级抗菌为画面标识口径；抗菌级别标准表述请与商品页核对。",
        },
    },
    "yujin": {
        "name": "沉序浴巾",
        "slug": "yujin",
        "facts": {
            "product_name": "沉序浴巾",
            "claims": [
                {"claim": "长绒棉厚实线圈", "evidence_ref": "素材 材质细节 2 段 + 画面文字「长绒棉」", "status": "draft"},
                {"claim": "10A级抗菌", "evidence_ref": "素材画面文字「…长绒棉 10A级抗菌」（OCR 存疑：疑似“阿克苏长绒棉 10A级抗菌”，待确认）", "status": "draft"},
                {"claim": "可机洗", "evidence_ref": "素材画面文字「可机洗长绒棉」", "status": "draft"},
                {"claim": "克重 104.3g/㎡", "evidence_ref": "素材画面文字「104.3G/㎡」", "status": "draft"},
                {"claim": "吸水力强、一裹就干", "evidence_ref": "素材 吸水演示 4 段", "status": "draft"},
            ],
            "params": {"尺寸": None, "克重": "104.3g/㎡（画面文字）", "材质": "长绒棉（画面文字）"},
            "sku": None,
            "price": None,
            "notes": "10A级抗菌为画面标识 OCR 口径（“阿玛苏/阿克苏”字样存疑），请以商品页为准确认后再投流。",
        },
    },
}

# 12 镜骨架：每镜 role + duration + 动作域（按产品可用域做绑定；scene_plan 阶段给精确窗口）
# narration=口播；copy=花字。
SKELETON = {
    "A": [  # 测评证明型
        ("hook", 2.5, "使用场景", "这条{product}，到底值不值？", "{product} · 实测来了"),
        ("proof-1", 3.0, "吸水演示", "{absorb}", "倒水实测"),
        ("proof-1b", 2.5, "吸水演示", "{absorb2}", "秒吸水"),
        ("detail", 2.5, "材质细节", "{texture}", "{texture_copy}"),
        ("proof-2", 2.5, "proof2域", "{proof2}", "{proof2_copy}"),
        ("soft", 2.5, "亲肤柔软", "{soft}", "{soft_copy}"),
        ("scene-1", 2.5, "使用场景", "{scene1}", "{scene1_copy}"),
        ("size", 2.0, "尺寸域", "{size}", "{size_copy}"),
        ("color", 2.0, "色彩域", "{color}", "{color_copy}"),
        ("scene-2", 2.5, "使用场景", "{scene2}", "{scene2_copy}"),
        ("cta", 2.5, "使用场景", "点这里，把它带回家。", "点击带回家"),
        ("tail", 1.0, "色彩域", "", "{product}"),
    ],
    "B": [  # 痛点反转型
        ("hook", 2.5, "使用场景", "{pain_hook}", "{pain_copy1}"),
        ("pain-2", 2.0, "使用场景", "{pain2}", "{pain_copy2}"),
        ("turn", 2.0, "材质细节", "{turn}", "{turn_copy}"),
        ("reveal", 2.5, "色彩域", "{reveal}", "{product}"),
        ("proof-1", 2.5, "吸水演示", "{absorb}", "{absorb_copy}"),
        ("proof-2", 2.5, "proof2域", "{proof2}", "{proof2_copy}"),
        ("detail", 2.5, "材质细节", "{texture}", "{texture_copy}"),
        ("soft", 2.5, "亲肤柔软", "{soft}", "{soft_copy}"),
        ("size", 2.0, "尺寸域", "{size}", "{size_copy}"),
        ("scene", 2.5, "使用场景", "{scene1}", "{scene1_copy}"),
        ("cta", 2.5, "使用场景", "点这里，好价带走。", "点击下单"),
        ("tail", 1.0, "尺寸域", "", "{tail_copy}"),
    ],
    "C": [  # 卖点罗列型
        ("hook", 2.0, "使用场景", "{list_hook}", "{list_hook_copy}"),
        ("sell-1", 3.0, "材质细节", "{sell1}", "{sell1_copy}"),
        ("sell-2", 2.5, "吸水演示", "{sell2}", "{sell2_copy}"),
        ("sell-3", 2.5, "proof2域", "{sell3}", "{sell3_copy}"),
        ("sell-4", 2.5, "尺寸域", "{sell4}", "{sell4_copy}"),
        ("detail", 2.5, "材质细节", "{texture}", "{texture_copy}"),
        ("scene-1", 2.5, "使用场景", "{scene1}", "{scene1_copy}"),
        ("color", 2.0, "色彩域", "{color}", "{color_copy}"),
        ("soft", 2.5, "亲肤柔软", "{soft}", "{soft_copy}"),
        ("summary", 2.5, "使用场景", "{summary}", "{summary_copy}"),
        ("cta", 2.5, "使用场景", "点这里，带它回家。", "点击带走"),
        ("tail", 1.0, "尺寸域", "", "{product}"),
    ],
    "D": [  # 场景种草型
        ("hook", 2.5, "使用场景", "{life_hook}", "{life_hook_copy}"),
        ("scene-1", 3.0, "使用场景", "{scene1}", "{scene1_copy}"),
        ("soft", 2.5, "亲肤柔软", "{soft}", "{soft_copy}"),
        ("detail", 2.5, "材质细节", "{texture}", "{texture_copy}"),
        ("proof", 3.0, "吸水演示", "{absorb}", "{absorb_copy}"),
        ("proof-2", 2.5, "proof2域", "{proof2}", "{proof2_copy}"),
        ("detail-2", 2.0, "材质细节", "{texture2}", "{texture2_copy}"),
        ("size", 2.5, "尺寸域", "{size}", "{size_copy}"),
        ("color", 2.0, "色彩域", "{color}", "{color_copy}"),
        ("scene-2", 2.5, "使用场景", "{scene2}", "{scene2_copy}"),
        ("cta", 2.5, "使用场景", "点这里，同款带回家。", "点击带回家"),
        ("tail", 1.0, "使用场景", "", "{product}"),
    ],
}

# 每产品 × 每方向：文案填充（{product} 之外的占位值）。proof2域/尺寸域/色彩域按产品可用域指定。
COPY = {
    "yinlizi": {
        "proof2域": "抗菌标识", "尺寸域": "厚度克重", "色彩域": "色彩质感",
        "A": {
            "absorb": "整杯水泼上去，瞬间吸走。", "absorb2": "表面不挂水，一擦即干。",
            "texture": "细密毛圈，织得又厚又匀。", "texture_copy": "细密毛圈",
            "proof2": "银离子抗菌，久用没异味。", "proof2_copy": "银离子 · 防异味",
            "soft": "贴上皮肤，软乎乎不扎人。", "soft_copy": "亲肤不扎",
            "scene1": "早晚洗脸，用着都顺手。", "scene1_copy": "早晚都好用",
            "size": "克重足，手感厚实。", "size_copy": "克重足",
            "color": "配色干净，挂哪都好看。", "color_copy": "高颜值",
            "scene2": "浴室放一条，全家都爱用。", "scene2_copy": "全家适用",
        },
        "B": {
            "pain_hook": "毛巾发硬、有异味，你遇到过吗？", "pain_copy1": "毛巾越用越硬？",
            "pain2": "晒干像砂纸，擦脸都疼。", "pain_copy2": "硬邦邦 · 有异味",
            "turn": "换这条，情况就不一样。", "turn_copy": "换一条试试",
            "reveal": "银离子毛巾，柔到想贴脸。",
            "absorb": "吸水快，一擦就干。", "absorb_copy": "吸水快",
            "proof2": "银离子抗菌，异味少多了。", "proof2_copy": "银离子防异味",
            "texture": "毛圈细密，摸着厚实。", "texture_copy": "细密厚实",
            "soft": "软得不像新毛巾。", "soft_copy": "软糯亲肤",
            "size": "克重实在，不偷工。", "size_copy": "克重实在",
            "scene1": "换掉旧毛巾，就现在。", "scene1_copy": "今晚就换",
            "tail_copy": "告别发硬异味",
        },
        "C": {
            "list_hook": "一条好毛巾，就看这几点。", "list_hook_copy": "好毛巾 · 看这几点",
            "sell1": "一看材质，细密毛圈不塌。", "sell1_copy": "材质过关",
            "sell2": "二看吸水，倒水秒吸。", "sell2_copy": "吸水快",
            "sell3": "三看触感，贴脸软糯。", "sell3_copy": "亲肤软糯",
            "sell4": "四看克重，厚实耐用。", "sell4_copy": "克重足",
            "texture": "细节做工，锁边平整。", "texture_copy": "做工精致",
            "scene1": "浴室阳台，随手好用。", "scene1_copy": "随手好用",
            "color": "配色清爽，颜值在线。", "color_copy": "颜值在线",
            "soft": "擦脸擦手，都舒服。", "soft_copy": "擦什么都舒服",
            "summary": "一条全占，才叫好毛巾。", "summary_copy": "一条全占",
        },
        "D": {
            "life_hook": "浴室里缺的那条毛巾，找到了。", "life_hook_copy": "浴室好物",
            "scene1": "挂上它，浴室都亮了几分。", "scene1_copy": "挂上就好看",
            "soft": "摸一把，软到不想放手。", "soft_copy": "软到不想放手",
            "texture": "细密毛圈，吸水更给力。", "texture_copy": "细密毛圈",
            "absorb": "倒水实测，秒吸不挂水。", "absorb_copy": "倒水实测",
            "proof2": "银离子抗菌，干净更安心。", "proof2_copy": "银离子 · 更安心",
            "texture2": "贴脸擦，一点不扎。", "texture2_copy": "贴脸不扎",
            "size": "克重足，天天用也耐用。", "size_copy": "耐用厚实",
            "color": "清爽配色，怎么拍都好看。", "color_copy": "怎么拍都好看",
            "scene2": "洗漱时光，也变得温柔。", "scene2_copy": "温柔洗漱时光",
        },
    },
    "tiansi": {
        "proof2域": "亲肤柔软", "尺寸域": "厚度克重", "色彩域": "色彩质感",
        "A": {
            "absorb": "倒水一测，吸得又快又稳。", "absorb2": "拿起来，表面不挂水。",
            "texture": "天丝纤维，丝滑又细腻。", "texture_copy": "天丝纤维",
            "proof2": "贴脸一擦，顺滑不磨。", "proof2_copy": "顺滑不磨",
            "soft": "像丝绸一样滑过皮肤。", "soft_copy": "丝绸触感",
            "scene1": "洗脸擦手，都舍不得放。", "scene1_copy": "日常好用",
            "size": "厚度刚好，透气不闷。", "size_copy": "透气不闷",
            "color": "光泽柔和，高级感拉满。", "color_copy": "高级光泽",
            "scene2": "挂在家里，就是精致。", "scene2_copy": "精致生活",
        },
        "B": {
            "pain_hook": "毛巾扎脸、掉毛，烦不烦？", "pain_copy1": "毛巾扎脸掉毛？",
            "pain2": "擦个脸，又痒又不舒服。", "pain_copy2": "又痒又不舒服",
            "turn": "试试天丝，真不一样。", "turn_copy": "试试天丝",
            "reveal": "丝滑垂顺，一摸就懂。",
            "absorb": "吸水快，还不掉毛。", "absorb_copy": "吸水不掉毛",
            "proof2": "顺滑贴肤，敏感肌也友好。", "proof2_copy": "敏感肌友好",
            "texture": "纤维细密，光泽自然。", "texture_copy": "细密光泽",
            "soft": "软滑像第二层皮肤。", "soft_copy": "第二层皮肤",
            "size": "轻薄透气，干得快。", "size_copy": "轻薄速干",
            "scene1": "从洗脸开始，对自己好点。", "scene1_copy": "对自己好点",
            "tail_copy": "告别扎脸掉毛",
        },
        "C": {
            "list_hook": "天丝毛巾好在哪里？", "list_hook_copy": "天丝好在哪",
            "sell1": "好在材质，植物纤维更亲肤。", "sell1_copy": "植物纤维",
            "sell2": "好在吸水，秒吸速干。", "sell2_copy": "秒吸速干",
            "sell3": "好在手感，丝滑不磨。", "sell3_copy": "丝滑不磨",
            "sell4": "好在厚度，透气不闷汗。", "sell4_copy": "透气不闷",
            "texture": "纤维细密，光泽高级。", "texture_copy": "细密高级",
            "scene1": "浴室卧室，随手好用。", "scene1_copy": "随手好用",
            "color": "配色温柔，颜值能打。", "color_copy": "颜值能打",
            "soft": "擦脸擦手，都很舒服。", "soft_copy": "擦着舒服",
            "summary": "好用不贵，才值得囤。", "summary_copy": "好用不贵",
        },
        "D": {
            "life_hook": "会生活的家，都有一条天丝毛巾。", "life_hook_copy": "精致生活好物",
            "scene1": "挂在浴室，温柔又有质感。", "scene1_copy": "温柔有质感",
            "soft": "摸上去，滑得像丝绸。", "soft_copy": "滑得像丝绸",
            "texture": "天丝纤维，细腻到反光。", "texture_copy": "细腻光泽",
            "absorb": "倒水实测，秒吸不挂水。", "absorb_copy": "倒水实测",
            "proof2": "贴脸擦拭，顺滑不扎。", "proof2_copy": "顺滑不扎",
            "texture2": "细看纤维，密实不掉毛。", "texture2_copy": "密实不掉毛",
            "size": "轻薄透气，速干没闷味。", "size_copy": "轻薄速干",
            "color": "颜色温柔，怎么搭都好看。", "color_copy": "怎么搭都好看",
            "scene2": "每天用它，都是小享受。", "scene2_copy": "每天的小享受",
        },
    },
    "chenxu": {
        "proof2域": "抗菌标识", "尺寸域": "尺寸对比", "色彩域": "使用场景",
        "A": {
            "absorb": "倒水一测，吸得干干净净。", "absorb2": "拿起来不滴水，擦哪都利落。",
            "texture": "阿克苏长绒棉，纤维细又长。", "texture_copy": "阿克苏长绒棉",
            "proof2": "7A 级抗菌，标得明明白白。", "proof2_copy": "7A级抗菌",
            "soft": "上脸软糯，一点不磨。", "soft_copy": "软糯不磨",
            "scene1": "早晚洗漱，用它正合适。", "scene1_copy": "早晚都好用",
            "size": "80×40 大尺寸，擦脸擦手都够。", "size_copy": "80×40 大尺寸",
            "color": "100% 棉，颜色正、看着舒服。", "color_copy": "100%棉",
            "scene2": "家里备几条，替换不将就。", "scene2_copy": "备几条不将就",
        },
        "B": {
            "pain_hook": "毛巾有异味、发硬，你忍多久了？", "pain_copy1": "毛巾异味发硬？",
            "pain2": "洗不净的味儿，擦脸都膈应。", "pain_copy2": "洗不净的味",
            "turn": "换沉序这条，真不一样。", "turn_copy": "换一条试试",
            "reveal": "长绒棉配 7A 抗菌，稳了。",
            "absorb": "吸水快，用得干净利落。", "absorb_copy": "吸水快",
            "proof2": "7A 抗菌，异味自然少。", "proof2_copy": "7A抗菌 少异味",
            "texture": "100% 棉，无荧光，更安心。", "texture_copy": "100%棉 无荧光",
            "soft": "上脸软糯，越用越舒服。", "soft_copy": "越用越软",
            "size": "80×40，够大够用。", "size_copy": "尺寸够大",
            "scene1": "今晚就换，别再忍。", "scene1_copy": "今晚就换",
            "tail_copy": "告别异味发硬",
        },
        "C": {
            "list_hook": "挑毛巾，认准这几点。", "list_hook_copy": "挑毛巾看这几点",
            "sell1": "一看棉，阿克苏长绒棉。", "sell1_copy": "长绒棉",
            "sell2": "二看吸水，倒水秒吸。", "sell2_copy": "倒水秒吸",
            "sell3": "三看抗菌，7A 级有标识。", "sell3_copy": "7A级抗菌",
            "sell4": "四看尺寸，80×40 用着爽。", "sell4_copy": "80×40",
            "texture": "100% 棉无荧光，用着安心。", "texture_copy": "无荧光 · 更安心",
            "scene1": "家里随手一挂，都顺眼。", "scene1_copy": "随手好用",
            "color": "颜色干净，颜值过关。", "color_copy": "颜色干净",
            "soft": "擦脸擦手，软糯舒服。", "soft_copy": "软糯舒服",
            "summary": "条条达标，闭眼入。", "summary_copy": "闭眼入",
        },
        "D": {
            "life_hook": "洗漱台边，就该有一条这样的毛巾。", "life_hook_copy": "洗漱台好物",
            "scene1": "挂上它，台面都清爽了。", "scene1_copy": "挂上就清爽",
            "soft": "摸一把，软糯像云朵。", "soft_copy": "软糯像云朵",
            "texture": "长绒棉纤维，细密看得见。", "texture_copy": "细密长绒棉",
            "absorb": "倒水实测，吸水不拖沓。", "absorb_copy": "倒水实测",
            "proof2": "7A 抗菌，天天用更安心。", "proof2_copy": "7A抗菌 · 安心",
            "texture2": "100% 棉无荧光，贴身也放心。", "texture2_copy": "无荧光放心用",
            "size": "80×40，擦脸擦手都够。", "size_copy": "大尺寸够用",
            "color": "颜色舒服，看着就干净。", "color_copy": "看着就干净",
            "scene2": "每天洗漱，心情都变好。", "scene2_copy": "洗漱心情好",
        },
    },
    "yujin": {
        "proof2域": "抗菌标识", "尺寸域": "厚度克重", "色彩域": "色彩质感",
        "A": {
            "absorb": "整盆水倒下去，看看表现。", "absorb2": "裹上身，秒吸不滴水。",
            "texture": "长绒棉线圈，细密又厚实。", "texture_copy": "长绒棉线圈",
            "proof2": "10A 级抗菌，标识在包装上。", "proof2_copy": "10A级抗菌",
            "soft": "裹着像被云包住。", "soft_copy": "云朵般柔软",
            "scene1": "洗完澡一裹，干爽利落。", "scene1_copy": "洗完就裹",
            "size": "克重足，厚实有分量。", "size_copy": "克重 104.3g/㎡",
            "color": "颜色干净，浴室更好看。", "color_copy": "高颜值",
            "scene2": "家里备两条，替换不愁。", "scene2_copy": "备两条不愁",
        },
        "B": {
            "pain_hook": "浴巾越洗越硬，擦不干水？", "pain_copy1": "浴巾发硬擦不干？",
            "pain2": "洗完澡越擦越冷，太难受。", "pain_copy2": "越擦越冷",
            "turn": "换这条，洗完舒服多了。", "turn_copy": "换一条试试",
            "reveal": "沉序浴巾，厚实又能吸。",
            "absorb": "吸水力强，一裹就干。", "absorb_copy": "一裹就干",
            "proof2": "10A 抗菌，用着更安心。", "proof2_copy": "10A抗菌",
            "texture": "长绒棉线圈，细密不掉絮。", "texture_copy": "细密不掉絮",
            "soft": "软乎厚实，像裹着被子。", "soft_copy": "像裹被子",
            "size": "克重足，机器洗也抗造。", "size_copy": "可机洗 · 抗造",
            "scene1": "今晚洗澡，就换它。", "scene1_copy": "今晚就换",
            "tail_copy": "告别发硬浴巾",
        },
        "C": {
            "list_hook": "好浴巾，就看这几点。", "list_hook_copy": "好浴巾看这几点",
            "sell1": "一看材质，长绒棉线圈。", "sell1_copy": "长绒棉",
            "sell2": "二看吸水，一裹就干。", "sell2_copy": "一裹就干",
            "sell3": "三看抗菌，10A 级标识。", "sell3_copy": "10A级抗菌",
            "sell4": "四看克重，104.3g/㎡ 厚实。", "sell4_copy": "克重104.3g/㎡",
            "texture": "线圈细密，可机洗耐造。", "texture_copy": "可机洗耐造",
            "scene1": "浴室一挂，档次就上来了。", "scene1_copy": "浴室显档次",
            "color": "颜色干净，怎么拍都好看。", "color_copy": "颜色干净",
            "soft": "裹身上，软乎又暖和。", "soft_copy": "软乎暖和",
            "summary": "条条过关，闭眼入。", "summary_copy": "闭眼入",
        },
        "D": {
            "life_hook": "洗澡后的幸福感，一半是浴巾给的。", "life_hook_copy": "洗澡幸福感",
            "scene1": "裹上它，整个人都松弛了。", "scene1_copy": "裹上就松弛",
            "soft": "软乎乎厚实，像云朵包裹。", "soft_copy": "云朵包裹",
            "texture": "长绒棉线圈，细密看得见。", "texture_copy": "细密长绒棉",
            "absorb": "吸水实测，一裹就干爽。", "absorb_copy": "吸水实测",
            "proof2": "10A 抗菌，天天用安心。", "proof2_copy": "10A抗菌安心",
            "texture2": "贴肤柔软，不扎不掉絮。", "texture2_copy": "不扎不掉絮",
            "size": "克重足，裹着踏实。", "size_copy": "厚实踏实",
            "color": "颜色清爽，浴室都亮了。", "color_copy": "浴室都亮了",
            "scene2": "每天洗完澡，都是享受。", "scene2_copy": "每天都是享受",
        },
    },
}


ARCHETYPE_LABEL = {"A": "测评证明型", "B": "痛点反转型", "C": "卖点罗列型", "D": "场景种草型"}

# ============ 内容对位终稿（基于全量逐镜审计） ============
# 原则：口播只描述绑定素材画面实际可见的内容；标签类 claim 强制绑定确认有文字的素材；
# 无画面证据的 claim（银离子抗菌标识/发硬异味/裹身/不掉絮等）一律改写或删除。
# pin_stem = 强制素材（标签类用）；格式与 OVERRIDES/ALIGN_FIXES 相同。
_STEM_DOMAIN = {
    "product_沉序毛巾-抗菌标识": "抗菌标识",
    "product_沉序毛巾-抗菌标识-2": "抗菌标识",
    "product_沉序毛巾-抗菌标识-3": "抗菌标识",
    "product_沉序浴巾-抗菌标识": "抗菌标识",
    "product_沉序浴巾-抗菌标识-2": "抗菌标识",
    "product_银离子毛巾-吸水演示": "吸水演示",
    "product_银离子毛巾-吸水演示-2": "吸水演示",
    "product_天丝莱赛尔毛巾-吸水演示-3": "吸水演示",
    "product_沉序毛巾-亲肤柔软-2": "亲肤柔软",
    "product_天丝莱赛尔毛巾-材质细节-2": "材质细节",
}

CONTENT_FIXES = {
    # ---------------- 银离子毛巾（抗菌 claim 无画面证据 → 产品名+可证卖点） ----------------
    ("yinlizi","A","proof-1b"): {"narration":"滚筒一滚，吸得干爽。","copy":"滚筒吸水","pin_stem":"product_银离子毛巾-吸水演示"},
    ("yinlizi","A","detail"): {"narration":"软到想用棉花来比。","copy":"棉花般软"},
    ("yinlizi","A","proof-2"): {"domain":"亲肤柔软","narration":"轻轻一举，软得垂下来。","copy":"柔软垂坠"},
    ("yinlizi","A","soft"): {"narration":"举起来看，软得有感觉。","copy":"软乎乎"},
    ("yinlizi","A","scene-1"): {"narration":"挂浴室，早晚随手用。","copy":"浴室常备"},
    ("yinlizi","A","size"): {"narration":"克重一测，厚实有数。","copy":"克重视测"},
    ("yinlizi","A","scene-2"): {"narration":"一条挂浴室，干净又安心。","copy":"干净安心"},
    ("yinlizi","B","hook"): {"narration":"旧毛巾，是时候换了。","copy":"该换新毛巾"},
    ("yinlizi","B","pain-2"): {"narration":"天天见它，早该换了。","copy":"早该换了"},
    ("yinlizi","B","turn"): {"narration":"换上它，软得不一样。","copy":"换这条"},
    ("yinlizi","B","reveal"): {"narration":"银离子毛巾，看着就软。","copy":"银离子毛巾"},
    ("yinlizi","B","proof-1"): {"narration":"滚筒一滚，水就吸干。","copy":"滚筒吸水","pin_stem":"product_银离子毛巾-吸水演示"},
    ("yinlizi","B","proof-2"): {"domain":"吸水演示","narration":"水一沾，就被吸进去了。","copy":"吸水看得见","pin_stem":"product_银离子毛巾-吸水演示-2"},
    ("yinlizi","B","size"): {"narration":"克重一测，实在。","copy":"克重视测"},
    ("yinlizi","B","scene"): {"narration":"新毛巾，就摆在面前。","copy":"现在换新"},
    ("yinlizi","B","tail"): {"copy":"告别旧毛巾"},
    ("yinlizi","C","sell-4"): {"narration":"四看厚度，一按就知道。","copy":"按得出厚度"},
    ("yinlizi","C","detail"): {"narration":"纹理细密，一看就懂。","copy":"纹理细密"},
    ("yinlizi","C","summary"): {"narration":"要换，就换条好的。","copy":"换条好的"},
    ("yinlizi","D","scene-1"): {"narration":"一挂上，浴室就有样了。","copy":"挂上就有样"},
    ("yinlizi","D","detail"): {"narration":"细密柔软，看着就稳。","copy":"细密柔软"},
    # ---------------- 天丝莱赛尔毛巾 ----------------
    ("tiansi","A","detail"): {"narration":"细密纤维，软绵可见。","copy":"细密纤维"},
    ("tiansi","A","soft"): {"narration":"轻靠上去，整个人都松了。","copy":"放松一靠"},
    ("tiansi","A","scene-1"): {"narration":"挂浴室，随手就用。","copy":"随手就用"},
    ("tiansi","A","size"): {"narration":"厚度一测，心里有数。","copy":"厚度合格"},
    ("tiansi","B","hook"): {"narration":"毛巾用旧了，该换就换。","copy":"旧毛巾该换了"},
    ("tiansi","B","pain-2"): {"narration":"挂着旧了，看着都糙。","copy":"看着都旧了"},
    ("tiansi","B","turn"): {"narration":"试试天丝，软得不一样。","copy":"试试天丝"},
    ("tiansi","B","reveal"): {"narration":"垂感自然，一眼高级。","copy":"垂感高级"},
    ("tiansi","B","proof-1"): {"narration":"吸水快，吸得利落。","copy":"吸水力","pin_stem":"product_天丝莱赛尔毛巾-吸水演示-3"},
    ("tiansi","B","proof-2"): {"narration":"一靠上去，整个人都放松。","copy":"放松"},
    ("tiansi","B","soft"): {"narration":"软得靠上去不想动。","copy":"软靠"},
    ("tiansi","B","size"): {"narration":"轻软不闷，摸着就懂。","copy":"轻薄"},
    ("tiansi","B","scene"): {"narration":"浴室这件事，别将就。","copy":"浴室讲究"},
    ("tiansi","B","tail"): {"copy":"告别旧毛巾"},
    ("tiansi","C","sell-1"): {"narration":"好在绒感，软绵在线。","copy":"软绵看得见","pin_stem":"product_天丝莱赛尔毛巾-材质细节-2"},
    ("tiansi","C","sell-3"): {"narration":"好在一靠，就不想走。","copy":"一靠就松"},
    ("tiansi","C","sell-4"): {"narration":"好在一测，厚度达标。","copy":"厚度达标"},
    ("tiansi","C","scene-1"): {"narration":"浴室常驻，随手就用。","copy":"随手就用"},
    ("tiansi","C","summary"): {"narration":"一条换新，不将就。","copy":"换新不将就"},
    ("tiansi","D","hook"): {"narration":"棉花般的软，值得来一条。","copy":"值得来一条"},
    ("tiansi","D","soft"): {"narration":"摸上去，软到心里。","copy":"软到心里"},
    ("tiansi","D","detail"): {"narration":"丝丝纤维，摸着就软。","copy":"细软纤维"},
    ("tiansi","D","proof-2"): {"narration":"配上棉朵，软感加成。","copy":"软感加成"},
    ("tiansi","D","detail-2"): {"narration":"细看纤维，密而软。","copy":"细软"},
    ("tiansi","D","size"): {"narration":"挂浴室，清清爽爽。","copy":"清清爽爽"},
    # ---------------- 沉序毛巾 ----------------
    ("chenxu","A","detail"): {"narration":"阿克苏长绒棉，都在标签上。","copy":"阿克苏长绒棉","pin_stem":"product_沉序毛巾-抗菌标识"},
    ("chenxu","A","soft"): {"narration":"拿起来，轻轻一晃都是软的。","copy":"软得晃人","pin_stem":"product_沉序毛巾-亲肤柔软-2"},
    ("chenxu","A","scene-1"): {"narration":"浴室挂着，早晚都好用。","copy":"早晚好用"},
    ("chenxu","A","size"): {"narration":"80cm×40cm，标签写得清。","copy":"80×40 标签可见","pin_stem":"product_沉序毛巾-抗菌标识-2"},
    ("chenxu","A","color"): {"narration":"100% 棉，成分写清楚。","copy":"100%棉","pin_stem":"product_沉序毛巾-抗菌标识-2"},
    ("chenxu","B","hook"): {"narration":"毛巾用久了，看着就该换。","copy":"该换新了"},
    ("chenxu","B","pain-2"): {"narration":"挂着旧了，没几条像样的。","copy":"旧了不像样"},
    ("chenxu","B","turn"): {"narration":"换上这条，软度不一样。","copy":"换这条"},
    ("chenxu","B","reveal"): {"narration":"长绒棉 + 7A，标签写得明白。","copy":"长绒棉7A抗菌","pin_stem":"product_沉序毛巾-抗菌标识"},
    ("chenxu","B","proof-2"): {"narration":"7A 抗菌，标得明白。","copy":"7A级抗菌","pin_stem":"product_沉序毛巾-抗菌标识-2"},
    ("chenxu","B","detail"): {"narration":"无荧光长绒棉，标签有写。","copy":"无荧光","pin_stem":"product_沉序毛巾-抗菌标识-3"},
    ("chenxu","B","soft"): {"narration":"拿起来一晃，软得不行。","copy":"软得不行","pin_stem":"product_沉序毛巾-亲肤柔软-2"},
    ("chenxu","B","size"): {"narration":"80cm×40cm，够大够用。","copy":"80×40","pin_stem":"product_沉序毛巾-抗菌标识-2"},
    ("chenxu","B","scene"): {"narration":"今晚就换，不将就。","copy":"今晚就换"},
    ("chenxu","B","tail"): {"copy":"告别旧毛巾"},
    ("chenxu","C","sell-1"): {"narration":"阿克苏长绒棉，标签写着。","copy":"阿克苏长绒棉","pin_stem":"product_沉序毛巾-抗菌标识"},
    ("chenxu","C","sell-3"): {"narration":"三看抗菌，7A 级有标识。","copy":"7A级抗菌","pin_stem":"product_沉序毛巾-抗菌标识-2"},
    ("chenxu","C","sell-4"): {"narration":"80cm×40cm，标得清楚。","copy":"80×40","pin_stem":"product_沉序毛巾-抗菌标识"},
    ("chenxu","C","detail"): {"narration":"无荧光长绒棉，用着安心。","copy":"无荧光安心","pin_stem":"product_沉序毛巾-抗菌标识-3","duration_s":2.5},
    ("chenxu","C","color"): {"narration":"挂起来，颜色就干净。","copy":"颜色干净"},
    ("chenxu","C","soft"): {"narration":"拿着晃，软得明显。","copy":"软乎乎","pin_stem":"product_沉序毛巾-亲肤柔软-2"},
    ("chenxu","C","summary"): {},
    ("chenxu","D","soft"): {"narration":"拿起来，软到没边。","copy":"软到没边","pin_stem":"product_沉序毛巾-亲肤柔软-2"},
    ("chenxu","D","proof-2"): {"pin_stem":"product_沉序毛巾-抗菌标识-2"},
    ("chenxu","D","detail-2"): {"narration":"棉纱细腻，贴身放心。","copy":"棉纱细腻"},
    ("chenxu","D","size"): {"narration":"80cm×40cm，标签可见。","copy":"80×40","pin_stem":"product_沉序毛巾-抗菌标识"},
    ("chenxu","D","color"): {"pin_stem":"product_沉序毛巾-抗菌标识-2"},
    ("chenxu","D","scene"): {"narration":"挂着，看着就舒心。","copy":"看着舒心"},
    # ---------------- 沉序浴巾 ----------------
    ("yujin","A","scene-1"): {"narration":"洗完澡，它就在手边。","copy":"就在手边"},
    ("yujin","A","size"): {"narration":"一按就知道，厚实。","copy":"按得出厚度"},
    ("yujin","A","color"): {"narration":"摆浴室，看着就舒服。","copy":"看着舒服"},
    ("yujin","A","proof-2"): {"pin_stem":"product_沉序浴巾-抗菌标识-2"},
    ("yujin","B","hook"): {"narration":"浴巾用久了，该换新的。","copy":"该换新浴巾"},
    ("yujin","B","pain-2"): {"narration":"旧的不换，看着将就。","copy":"别将就"},
    ("yujin","B","turn"): {"narration":"换上这条，软乎很多。","copy":"换这条"},
    ("yujin","B","reveal"): {"narration":"沉序浴巾，厚实看得见。","copy":"沉序浴巾"},
    ("yujin","B","proof-1"): {"narration":"滚筒一滚，水就吸干。","copy":"滚筒吸水","pin_stem":"product_沉序浴巾-吸水演示"},
    ("yujin","B","proof-2"): {"pin_stem":"product_沉序浴巾-抗菌标识-2"},
    ("yujin","B","size"): {"narration":"一按就知道，厚实。","copy":"按得出厚度"},
    ("yujin","B","scene"): {"narration":"点个蜡烛，好好泡个澡。","copy":"泡澡氛围"},
    ("yujin","B","tail"): {"copy":"告别旧浴巾"},
    ("yujin","C","sell-4"): {"narration":"104.3g/㎡，标签写着。","copy":"克重104.3g/㎡","pin_stem":"product_沉序浴巾-抗菌标识"},
    ("yujin","C","detail"): {"narration":"线圈细密，摸得出来。","copy":"线圈细密"},
    ("yujin","C","scene-1"): {"narration":"展开来，质感在线。","copy":"质感在线"},
    ("yujin","C","soft"): {"narration":"软乎厚实，摸着舒服。","copy":"软乎舒服"},
    ("yujin","D","hook"): {"narration":"一条软乎浴巾，一半幸福感。","copy":"幸福感"},
    ("yujin","D","detail-2"): {"narration":"手指轻抚，软得顺心。","copy":"软顺"},
    ("yujin","D","color"): {"narration":"一挂进浴室，氛围就有了。","copy":"氛围拉满"},
    ("yujin","D","scene-2"): {"narration":"摆在浴室，就是享受。","copy":"就是享受"},
    # ---------------- 装置对齐（计时器/吸尘器/电子秤实拍画面） ----------------
    ("tiansi","A","proof-1"): {"narration":"计时开测，倒水就吸。","copy":"计时实测","pin_stem":"product_天丝莱赛尔毛巾-吸水演示-3"},
    ("tiansi","D","proof"): {"narration":"计时开测，倒水就吸。","copy":"计时实测"},
    ("tiansi","B","proof-1"): {"narration":"计时一试，吸得利落。","copy":"计时一试"},
    ("tiansi","C","sell-2"): {"narration":"好在吸水，计时就来。","copy":"计时吸水"},
    ("yujin","A","proof-1b"): {"narration":"吸头一过，水就吸走。","copy":"真空吸水"},
    ("yinlizi","A","proof-2"): {"narration":"垂下来软，称出来有分量。","copy":"软有分量"},
}


# 画面对齐修正（用户反馈"口播与画面对不上"后的逐镜改写）：
# 口播只描述素材证据窗内实际可见的动作；误标域已重分类，通用槽位不再占用稀缺动作域。
ALIGN_FIXES = {
    ("yinlizi", "A", "proof-1"): {"narration": "水滴一沾上，就被吸了进去。", "copy": "吸水看得见"},
    ("yinlizi", "A", "proof-1b"): {"narration": "来回一擦，表面就干了。", "copy": "一擦即干"},
    ("yinlizi", "A", "detail"): {"narration": "细密毛圈，看得清清楚楚。", "copy": "细密毛圈"},
    ("yinlizi", "A", "soft"): {"narration": "摸着软乎乎，一点不扎人。", "copy": "亲肤不扎"},
    ("yinlizi", "C", "sell-2"): {"narration": "二看吸水，沾水即吸。", "copy": "沾水即吸"},
    ("yinlizi", "C", "sell-3"): {"narration": "三看触感，软糯亲肤。", "copy": "软糯亲肤"},
    ("yinlizi", "C", "soft"): {"narration": "摸着软乎，用着舒服。", "copy": "用着舒服"},
    ("yinlizi", "D", "proof"): {"narration": "沾水实测，秒吸看得见。", "copy": "沾水实测"},
    ("yinlizi", "D", "proof-2"): {"narration": "摸着柔软，用着安心。", "copy": "软糯安心"},
    ("tiansi", "A", "proof-1b"): {"narration": "水滴渗进去，吸得稳稳当当。", "copy": "渗透看得见"},
    ("tiansi", "A", "proof-2"): {"narration": "摸着顺滑，一点不磨。", "copy": "顺滑不磨"},
    ("tiansi", "B", "proof-2"): {"narration": "摸着顺滑，敏感肌也友好。", "copy": "敏感肌友好"},
    ("tiansi", "B", "tail"): {"domain": "材质细节", "duration_s": 2.0},
    ("tiansi", "C", "hook"): {"domain": "使用场景"},
    ("tiansi", "C", "soft"): {"narration": "摸着丝滑，用着舒服。", "copy": "用着舒服"},
    ("tiansi", "C", "summary"): {"domain": "使用场景", "duration_s": 2.0},
    ("tiansi", "D", "proof"): {"narration": "倒水实测，吸得又快又稳。", "copy": "倒水实测"},
    ("tiansi", "D", "proof-2"): {"narration": "摸着顺滑，一点不扎。", "copy": "顺滑不扎"},
    ("tiansi", "D", "size"): {"domain": "使用场景"},
    ("chenxu", "A", "proof-1b"): {"narration": "水一倒上去，吸得干干净净。", "copy": "倒水就吸"},
    ("chenxu", "A", "soft"): {"narration": "摸着软糯，一点不磨。", "copy": "软糯不磨"},
    ("chenxu", "B", "soft"): {"narration": "摸着软糯，越用越舒服。", "copy": "越用越软"},
    ("chenxu", "C", "color"): {"domain": "使用场景", "narration": "颜色干净，用得舒服。", "copy": "颜色干净"},
    ("chenxu", "C", "soft"): {"narration": "摸着软糯，用着舒服。", "copy": "软糯舒服"},
    ("chenxu", "D", "proof"): {"narration": "倒水实测，吸水不拖沓。", "copy": "倒水实测"},
    ("yujin", "A", "proof-1"): {"narration": "水一倒下去，看看它的表现。", "copy": "倒水实测"},
    ("yujin", "A", "proof-1b"): {"narration": "水滴一接触，就被吸走了。", "copy": "接触即吸"},
    ("yujin", "A", "proof-2"): {"narration": "10A 级抗菌，标签写得清楚。", "copy": "10A级抗菌"},
    ("yujin", "A", "soft"): {"narration": "软乎厚实，像被云包住。", "copy": "云朵般柔软"},
    ("yujin", "B", "proof-1"): {"narration": "来回一擦，水就干了。", "copy": "一擦即干"},
    ("yujin", "B", "tail"): {"domain": "使用场景"},
    ("yujin", "C", "sell-2"): {"narration": "二看吸水，一沾即吸。", "copy": "一沾即吸"},
    ("yujin", "C", "soft"): {"narration": "软乎厚实，摸着就暖和。", "copy": "软乎暖和"},
    ("yujin", "D", "proof"): {"narration": "沾水实测，一沾就吸干。", "copy": "沾水实测"},
    ("yujin", "D", "proof-2"): {"narration": "摸着柔软，天天用安心。", "copy": "贴肤安心"},
    ("yujin", "D", "detail-2"): {"narration": "摸着柔软，不扎不掉絮。", "copy": "不扎不掉絮"},
}

# 域容量再平衡（吸水域剔除误标素材后供给变化）：
BALANCE_FIXES = {
    ("chenxu", "C", "tail"): {"duration_s": 1.5},
}


# 稀缺域容量再平衡：(product, arch, role) → slot 覆盖。
# 原则：稀缺动作域（抗菌标识/厚度克重/尺寸对比/色彩质感）只在供给允许的 slot 使用；
# 被换域的 slot 口播改为新域画面可证的表述。
OVERRIDES = {
    ("yinlizi", "A", "proof-1"): {"duration_s": 2.5},
    ("yinlizi", "A", "proof-1b"): {"duration_s": 2.0},
    ("yinlizi", "B", "size"): {"domain": "材质细节", "narration": "锁边工整，经得起用。", "copy": "做工扎实"},
    ("yinlizi", "B", "turn"): {"domain": "使用场景"},
    ("yinlizi", "B", "tail"): {"domain": "使用场景"},
    ("yinlizi", "C", "sell-1"): {"duration_s": 2.5},
    ("yinlizi", "C", "sell-3"): {"domain": "亲肤柔软"},
    ("yinlizi", "C", "sell-4"): {"duration_s": 2.3},
    ("yinlizi", "C", "tail"): {"domain": "使用场景"},
    ("yinlizi", "D", "proof-2"): {"domain": "亲肤柔软", "narration": "贴肤柔软，用着安心。", "copy": "软糯安心"},
    ("yinlizi", "D", "detail-2"): {"domain": "使用场景", "narration": "擦完挂好，整整齐齐。", "copy": "擦完挂好"},
    ("yinlizi", "D", "size"): {"domain": "使用场景", "narration": "挂进浴室，每天都想用。", "copy": "每天都想用"},
    ("tiansi", "A", "scene-2"): {"domain": "使用场景", "narration": "光泽柔和，挂家里就是精致。"},
    ("tiansi", "D", "color"): {"domain": "材质细节", "narration": "细看质感，清爽好看。", "copy": "质感清爽"},
    ("tiansi", "B", "pain-2"): {"duration_s": 1.5},
    ("tiansi", "B", "size"): {"domain": "材质细节", "narration": "轻薄透气，干得快。", "copy": "轻薄速干"},
    ("tiansi", "B", "tail"): {"domain": "吸水演示"},
    ("tiansi", "C", "hook"): {"domain": "吸水演示"},
    ("tiansi", "C", "summary"): {"domain": "吸水演示", "duration_s": 2.0},
    ("tiansi", "C", "sell-4"): {"duration_s": 2.3},
    ("tiansi", "C", "tail"): {"domain": "吸水演示"},
    ("tiansi", "D", "scene-1"): {"domain": "色彩质感", "duration_s": 2.5, "narration": "颜色温柔，挂哪都有质感。"},
    ("tiansi", "D", "hook"): {"domain": "材质细节"},
    ("tiansi", "D", "proof-2"): {"duration_s": 2.0},
    ("tiansi", "D", "size"): {"domain": "吸水演示", "narration": "日常用起来，清清爽爽。", "copy": "清爽好用"},
    ("tiansi", "D", "scene-2"): {"domain": "色彩质感", "narration": "颜色温柔，每天用都是小享受。"},
    ("tiansi", "D", "tail"): {"domain": "使用场景"},
    ("tiansi", "B", "tail"): {"domain": "吸水演示", "duration_s": 2.0},
    ("tiansi", "C", "tail"): {"domain": "材质细节"},
    ("chenxu", "A", "color"): {"domain": "抗菌标识", "duration_s": 1.5},
    ("chenxu", "A", "tail"): {"domain": "使用场景"},
    ("chenxu", "B", "reveal"): {"domain": "材质细节"},
    ("chenxu", "B", "tail"): {"domain": "抗菌标识", "duration_s": 2.0},
    ("chenxu", "C", "sell-4"): {"duration_s": 2.5},
    ("chenxu", "C", "color"): {"domain": "吸水演示", "narration": "擦完干爽，用得舒服。", "copy": "干爽好用"},
    ("chenxu", "C", "summary"): {"domain": "抗菌标识"},
    ("chenxu", "C", "tail"): {"domain": "吸水演示"},
    ("chenxu", "D", "hook"): {"domain": "材质细节"},
    ("chenxu", "D", "scene-1"): {"duration_s": 2.5},
    ("chenxu", "D", "color"): {"domain": "抗菌标识", "narration": "7A 抗菌，看着就安心。", "copy": "7A抗菌 安心", "duration_s": 1.5},
    ("chenxu", "D", "size"): {"duration_s": 2.0},
    ("chenxu", "D", "cta"): {"duration_s": 2.0},
    ("chenxu", "D", "tail"): {"domain": "材质细节"},
    ("yujin", "A", "proof-2"): {"duration_s": 2.0},
    ("yujin", "A", "color"): {"domain": "使用场景", "narration": "挂在浴室，看着就舒服。", "copy": "浴室更好看"},
    ("yujin", "A", "tail"): {"domain": "使用场景"},
    ("yujin", "B", "proof-2"): {"duration_s": 2.0},
    ("yujin", "B", "reveal"): {"domain": "使用场景"},
    ("yujin", "B", "turn"): {"domain": "亲肤柔软"},
    ("yujin", "B", "tail"): {"domain": "吸水演示"},
    ("yujin", "B", "size"): {"duration_s": 2.5},
    ("yujin", "C", "sell-4"): {"duration_s": 2.0},
    ("yujin", "C", "sell-1"): {"domain": "使用场景", "narration": "一看实物，质感在线。", "copy": "质感在线"},
    ("yujin", "C", "sell-3"): {"domain": "亲肤柔软", "narration": "三看手感，软乎厚实。", "copy": "软乎厚实"},
    ("yujin", "C", "tail"): {"domain": "使用场景"},
    ("yujin", "D", "proof-2"): {"domain": "亲肤柔软", "narration": "贴肤柔软，天天用安心。", "copy": "贴肤安心"},
    ("yujin", "D", "detail-2"): {"domain": "亲肤柔软"},
    ("yujin", "D", "color"): {"domain": "使用场景", "narration": "挂进浴室，氛围都亮了。", "copy": "氛围感拉满"},
}


def build_templates() -> dict[str, list[dict]]:
    """把 SKELETON + COPY 展开成 16 条模板（每条 12 slots），再应用稀缺域再平衡。"""
    out: dict[str, list[dict]] = {}
    for pk in PRODUCT_KEYS:
        pname = PRODUCTS[pk]["name"]
        templates = []
        for arch in "ABCD":
            slots = []
            for (role, dur, domain, narr_tpl, copy_tpl) in SKELETON[arch]:
                ctx = COPY[pk].get(arch, {})
                domain = domain.replace("proof2域", COPY[pk].get("proof2域", "抗菌标识"))
                domain = domain.replace("尺寸域", COPY[pk].get("尺寸域", "使用场景"))
                domain = domain.replace("色彩域", COPY[pk].get("色彩域", "使用场景"))
                narr = narr_tpl.format(product=pname, **ctx)
                copy = copy_tpl.format(product=pname, **ctx)
                slot = {
                    "role": role,
                    "duration_s": dur,
                    "domain": domain,
                    "narration": narr,
                    "copy": copy,
                }
                ov = OVERRIDES.get((pk, arch, role))
                if ov:
                    for k, v in ov.items():
                        slot[k] = v
                af = ALIGN_FIXES.get((pk, arch, role))
                if af:
                    for k, v in af.items():
                        slot[k] = v
                cf = CONTENT_FIXES.get((pk, arch, role))
                if cf:
                    for k, v in cf.items():
                        slot[k] = v
                # pin 素材的域自动对齐（标签类槽位：台词/域随标签素材走）
                if slot.get("pin_stem"):
                    _pd = _STEM_DOMAIN.get(slot["pin_stem"])
                    if _pd and slot["domain"] != _pd:
                        slot["domain"] = _pd
                bf = BALANCE_FIXES.get((pk, arch, role))
                if bf:
                    for k, v in bf.items():
                        slot[k] = v
                slots.append(slot)
            # 尾帧补时长：把总时长补到 29.5s（尾帧为花字品牌卡，无口播）；
            # 若该尾帧已由 OVERRIDES 显式设定时长/域，则尊重显式值。
            total = sum(s["duration_s"] for s in slots)
            tail = slots[-1]
            if tail["role"] == "tail" and "duration_s" not in OVERRIDES.get((pk, arch, "tail"), {}):
                need = 29.5 - (total - tail["duration_s"])
                tail["duration_s"] = round(min(max(need, 1.0), 3.0), 2)
            templates.append({
                "template_id": f"{pk}-{arch}",
                "archetype": ARCHETYPE_LABEL[arch],
                "slots": slots,
            })
        out[pk] = templates
    return out

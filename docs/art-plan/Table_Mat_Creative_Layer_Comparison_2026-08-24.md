# 透明桌垫混剪：创作层优化前后对比报告（2026-08-24）

> 对比对象：batch-002（旧，卖点清单直给）vs 按本轮新 skill 重跑的创作层制品（新）。
> 范围：创作层（research_critique / proposal / script / scene_plan），**不含渲染**。
> 结论先行：故事结构、钩子、参考批判、recipe 意图四层都有可机器验证的提升；花字/转场的**画面效果**仍需渲染组件实现（见 §4 诚实边界）。

## 1. 总览对比

| 维度 | batch-002（旧） | 本轮（新） | 变化 |
|---|---|---|---|
| 参考处理 | 直接复刻 reference_fingerprint | 先批判：`reference_ceiling=medium` + keep/improve/replace/do_not_copy | ✅ 新增 |
| 脚本结构 | 卖点清单（6 段全是卖点） | beat map（hook→problem→escalation→reveal→proof→payoff/cta）| ✅ 重构 |
| 结构可验证 | 无 beat_role/viewer_state 字段 | 每段带 `beat_role` + `viewer_state` | ✅ 新增 |
| 钩子 | 功能直给（"保护到位，木纹也还在"） | 反常识/痛点/悬念（"你家的桌垫，正在偷偷吸油"）| ✅ 升级 |
| concept 差异 | 3 个但结构趋同 | 3 个不同 `narrative_structure` + `visual_approach` + `hook_pattern` | ✅ 机器可校验 |
| scene_plan 意图 | `transition_in=''`，无 recipe 意图 | `caption_recipe_intent` + `transition_recipe_intent` | ✅ 新增 |

## 2. 逐项证据

### 2.1 ReferenceCritique（新增）

```json
{
  "reference_ceiling": "medium",
  "keep": ["动作-结果证明对", "第一秒直接给动作", "近景动作证明"],
  "improve": ["钩子加冲突/反常识", "加入故事结构", "花字动效 + 转场节奏"],
  "replace": [
    "卖点清单式叙事 → beat map（hook→escalation→reveal→proof→payoff）",
    "功能直给开场 → 冲突/反常识开场"
  ],
  "do_not_copy": ["品牌/水印/账号身份", "参考片原字卡布局", "参考片原文案"]
}
```

> 旧：无此层，`reference_fingerprint → 直接生成 → 复制`（参考片被当处方全抄）。

### 2.2 脚本结构（旧 vs 新）

**旧（c1，卖点清单，无 beat_role）**

| id | label | narration |
|---|---|---|
| s01 | 结果先行 | 保护到位，木纹也还在。 |
| s02 | 自动铺开 | 铺开就位，先看见产品。 |
| s03 | 桌角贴合 | 一铺一按，边缘贴得更服帖。 |
| s04 | 防刮证据 | 日常刮擦，垫面先接住。 |
| s05 | 防油易擦拭 | 油污和水渍，擦一擦就好打理。 |
| s06 | 原创收尾 | 给餐桌，多一层日常保护。 |

**新（beat map，每段带 beat_role + viewer_state）**

| id | beat_role | narration | viewer_state |
|---|---|---|---|
| s01 | hook | 你家的桌垫，正在偷偷吸油。 | 好奇 → 警觉 |
| s02 | problem | 天天吃饭，油污早就渗进去了。 | 警觉 → 焦虑 |
| s03 | escalation | 换一张，还是继续忍？ | 焦虑 → 张力 |
| s04 | reveal | 透明保护层，先接住再说。 | 张力 → 被解答 |
| s05 | proof | 刮一下、倒一点、擦一擦。 | 被解答 → 信服 |
| s06 | payoff/cta | 给餐桌，多一层日常保护。 | 信服 → 行动 |

> 变化：从"6 段平铺卖点"变成"有起承转合的叙事弧"；`beat_role`/`viewer_state` 使结构可机器校验（不再是主观"像不像故事"）。

### 2.3 钩子（旧 vs 新）

| 项 | 旧 | 新 |
|---|---|---|
| hook_pattern | `result_first` | `contradiction`（反常识）|
| 首句 | 保护到位，木纹也还在。 | 你家的桌垫，正在偷偷吸油。 |
| 效果 | 功能直给（给结果） | 制造反常识悬念（"吸油"触发警觉）|

### 2.4 三个 concept（结构差异可机器校验）

| concept | narrative_structure | visual_approach | hook_pattern | hook |
|---|---|---|---|---|
| c1 | problem_solution | 真实测试+短字幕（痛点→解决→结果） | contradiction | 你家的桌垫，正在偷偷吸油。 |
| c2 | story | 产品质感+氛围（一天餐桌场景） | scene_pain | 从早餐到深夜，这张桌子经历了一切。 |
| c3 | data_narrative | 快剪+证据字卡（三连证） | contrast | 三个动作，证明一张桌垫。 |

> 旧：3 个 concept 的 `narrative_structure`/`visual_approach` 趋同，只有钩子措辞不同。
> 新：`lib.candidate_diversity.proposal_concept_diversity` 校验通过（3 个不同 narrative_structure + 3 个不同 visual_approach）。

### 2.5 scene_plan recipe 意图（旧 vs 新）

| shot | 旧 transition_in | 旧 caption_recipe_intent | 新 transition_recipe_intent | 新 caption_recipe_intent |
|---|---|---|---|---|
| shot-01 | `''` | 无 | impact | hook |
| shot-02 | `''` | 无 | soft | label |
| shot-03 | `''` | 无 | impact | hook |
| shot-04 | `''` | 无 | proof | reveal |
| shot-05 | `''` | 无 | proof | proof |
| shot-06 | `''` | 无 | soft | label |

> 变化：场景现在声明**语义意图**（`impact/proof/soft` + `hook/reveal/proof/label`），由 `lib.recipe_router` 解析到 runtime 无关的 recipe（含能力检查/回退）。旧的 `transition_in=''`（硬切）与无 recipe 意图 → 现在可路由。

## 3. 提升点清单（本轮优化带来的）

1. **参考片从"处方"变"证据"**：新增 ReferenceCritique，明确参考片天花板（medium）+ 保/改/换/禁，阻断"高保真复刻平庸"。
2. **脚本从"卖点清单"变"叙事弧"**：beat map 强制 hook→escalation→reveal→payoff，且 `beat_role`/`viewer_state` 可机器校验。
3. **钩子从"功能直给"变"反常识/痛点/悬念"**：hook_pattern 用满（contradiction/scene_pain/contrast），不再 result_first 直给。
4. **concept 差异可机器校验**：3 个 concept 结构维度（narrative_structure + visual_approach）≥2 个不同，拒绝"同结构换钩子"。
5. **花字/转场从"无意图"变"语义意图 + runtime 无关路由"**：scene_plan 声明 `caption_recipe_intent`/`transition_recipe_intent`，recipe router 做能力检查/回退。
6. **ProductBible 前置硬门**：SKU/价格/claims/视觉真实性约束前置，`product_truth` 有判定基础。

## 4. 诚实边界（已更新）

- **创作层**（故事结构、钩子、参考批判、recipe 意图）：已落地、可机器验证。
- **渲染组件**（花字 recipe + 转场 recipe）：**已完成** + **画面验证通过**（见 §6）。Python 全量 1929 passed，TypeScript 编译通过。

## 5. B 方案渲染验证结论（2026-08-25 补充）

真跑 1 个候选（`table-mat-batch-002-c1`）做渲染验证，产出两条片：

| 片 | 路径 | 合成器 | 验证 |
|---|---|---|---|
| 旧基线 | `renders/final.mp4` | Explainer | batch-002 原始（白字+硬切）|
| 花字验证 | `renders/final-recipe.mp4` | Explainer + caption recipe | ✅ 花字生效 |
| 花字+转场验证 | `renders/final-cinematic.mp4` | CinematicRenderer + caption/transition recipe | ✅ 花字+转场生效 |

### 验证证据

- **#1 花字**：hook 帧（1.2s）新旧 PSNR **29.5 dB**（字幕区域可见差异），全片 SSIM 0.987（仅字幕处理变化）。
- **#2 转场**：shot-04 边界（7.0s）出现**白闪**，亮度 YAVG **212→95** 尖峰（修复前是黑帧淡入 YAVG=16）。

### 为让效果真正上画面补的 4 处接线

| 改动 | 文件 | 作用 |
|---|---|---|
| 真实渲染路径接入 recipe | `lib/sample_payload.py` | scene_plan → `captionRecipes`/`transitionRecipes` 进 `build_sample_render_payload`（生产实际路径）|
| CinematicRenderer 字幕形状包装 | `tools/video/video_compose.py` | 平铺 captions → `{words}`，修 CinematicRenderer 字幕丢失 |
| Explainer 的 CaptionOverlay 传 recipe | `remotion-composer/src/Explainer.tsx` | 花字在 Explainer 路径也生效 |
| 转场禁用淡入 | `remotion-composer/src/CinematicRenderer.tsx` | cut/impact/flash 不从黑淡入，否则白闪被 opacity=0 吃掉 |

### 诚实提醒

渲染时出现 `Slideshow risk score 3.6/5.0 (verdict: revise)` 警告——源素材近景固定机位、镜头静态感偏强，属「镜头动感/素材多样性」维度，不在本轮花字/转场范围。

## 6. 如何查看成片效果

三条片都在 `projects/table-mat-batch-002-c1/renders/`：

- 直接打开文件（对比观感）：
  - 旧：`renders/final.mp4`
  - 花字：`renders/final-recipe.mp4`
  - 花字+转场：`renders/final-cinematic.mp4`
- 或经 Backlot 工作台 `/p/table-mat-batch-002-c1` 的 renders 面板查看（需 Backlot server 在 4750 端口运行）。

推荐对比顺序：先看旧 `final.mp4`（白字+硬切），再看 `final-cinematic.mp4`（花字 pop/underline + 转场白闪/impact）。

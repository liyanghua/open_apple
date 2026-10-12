# 从300条内容规划到单条视频生成：OpenMontage主干升级实施方案

版本：V1.0<br>
日期：2026-09-22<br>
状态：实施基线文档，尚未声明全部代码已完成<br>
适用范围：花花公子毛巾300条内容规划、P1/P2 60条前置试点、OpenMontage `cinematic-fast / source_led_template` 主线

## 1. 文档目的

本文件把《完整方案_300条_V2》中的内容经营规划，与OpenMontage已经存在的生产能力连接起来，回答三个问题：

1. 300条内容规划如何进入系统，而不是停留在排期表和创意文档中。
2. 一条视频如何从商品事实、内容类型、素材和脚本，走到TTS、BGM、Remotion成片和审核交付。
3. 当前系统哪些能力已经可以复用，哪些能力只是部分存在，哪些能力必须补齐后才能稳定支撑批量生产。

本文件是实施基线。它不把文档中的计划、样片或页面抓取结果表述为已经发布、已经验证或已经产生经营结果。

## 2. 结论与实施边界

### 2.1 总体结论

现有主线已经具备单条视频生产的主要技术零件：阶段式pipeline、商品事实卡、source-led素材链、模板批次、差异度检查、Remotion/FFmpeg合成、TTS、音频混合、checkpoint和QA。

当前缺口在于这些能力还没有被同一个业务主键串起来，尤其缺少：

- 300条计划到单个内容槽位的映射；
- 六类视频类型到脚本、镜头和审核规则的映射；
- 商品事实版本、证据和素材授权的冻结快照；
- Seedance动作片任务与素材池状态；
- 单条视频的父版本、控制变量、成本和发布数据追踪；
- 事实变化后对受影响成片的识别与阻断。

因此本次升级不是另建一条生成链，而是给现有 `cinematic-fast` 主线增加campaign、内容配方和业务准入，并把已经验证的样片规则固化为模板和QA契约。

### 2.2 已确认的实施边界

- P1/P2 60条是300条计划的前置试点，使用同一套campaign和slot模型。
- 首期继续扩展 `cinematic-fast / source_led_template`，不新建第二套电商Pipeline。
- 飞书首期采用人工导入导出，不把自动双向同步作为生产前置条件。
- 商品主体优先使用真实商品图片、视频和实拍动作；Seedance只补动作素材缺口。
- Doubao负责口播，SUNO负责BGM，Remotion负责品牌图层、字幕和时间线合成。
- 首期不自动发布、不自动投放、不自动修改飞书商品事实。
- 60条试点通过后，再扩展到完整300条的方向配额和更多SKU。

## 3. 300条方案如何转成系统对象

《完整方案_300条_V2》中的四种数量口径不能相加，系统必须分开保存：

| 业务口径 | 系统对象 | 说明 |
|---|---|---|
| 4周 × 每周75条 | `campaign_plan` / `production_wave` | 计划交付量和波次排期 |
| 240条实验 + 60条支持 | `support_type` | 任务属性，不是第七种视频类型 |
| 六个主方向配额 | `direction_id` | 内容经营方向 |
| 300个去重成片槽位 | `content_slot_id` | 交付计数的最小单位 |

### 3.1 Campaign层级

```text
campaign
  ├── campaign_plan
  ├── fact_snapshot / availability_snapshot
  ├── production_wave
  │     └── template_batch
  │           └── content_project
  │                 ├── script
  │                 ├── scene_plan
  │                 ├── asset_manifest
  │                 ├── edit_decisions
  │                 ├── render_report
  │                 └── delivery_version
  ├── publication_registry
  └── performance_import / experiment_readout
```

对象职责必须分开：

- `campaign`：管理300条计划、配额、事实快照、预算和汇总。
- `production_wave`：管理某一周、某个SKU、某个事实版本下的一批任务。
- `template_batch`：管理一批可并行的单片生产任务。
- `content_slot`：管理计划中的一个交付位置。
- `content_version`：管理一个实质创意版本；技术重试不增加交付数量。
- `delivery_version`：管理实际通过QA的不可变交付版本。
- `publication_registry`：管理外部平台发布或广告素材映射。

### 3.2 内容槽位与版本

```json
{
  "campaign_id": "playboy-towel-300-v1",
  "content_slot_id": "P1-W1-A03",
  "content_version_id": "P1-W1-A03-v001",
  "parent_content_version_id": null,
  "direction_id": "test_selection",
  "structure_id": "P1",
  "support_type": "experiment",
  "sku": "yb-bb-03",
  "status": "planned"
}
```

规则：

- 同一slot的技术重试只增加`attempt`，不新增交付计数。
- 实质修改开场、结构、证据排列或生活情境时，生成新的`content_version_id`。
- 同一slot最终只能有一个计数交付版本；被替代版本保留原因和历史。
- 仅换文件名、封面、编码或重新上传，不视为新内容。

## 4. 六类视频类型的系统化表达

类型必须进入内容配方、脚本、分镜、素材槽位、QA和数据复盘，而不能只保存为标签。

### 4.1 统一字段

```json
{
  "direction_id": "test_selection",
  "structure_id": "P1",
  "support_type": "experiment",
  "need_id": "D01",
  "content_role": "product_evidence",
  "recipe_id": "P1-weave-selection-v1"
}
```

固定枚举：

```text
direction_id:
  test_selection       实测与选购
  healing_ritual       治愈微仪式
  relationship_story   关系微故事
  space_play           空间与玩趣
  comment_faq          真实评论与答疑
  transaction          交易与直播承接

support_type:
  experiment           有明确父版本和控制变量
  trust                补充商品细节和信任证据
  faq                  回答真实问题
  transaction          讲清当前商品和去向

content_role:
  product_evidence     承载商品事实和证据
  life_context         承载真实生活动作和情境
  graphic_support      承载说明、字幕和氛围辅助
```

### 4.2 类型、结构和素材映射

| 类型 | 常用结构 | 必需素材/动作 | 口播功能 | 主要质量门 |
|---|---|---|---|---|
| 实测与选购 | P1、P6 | 全貌、标签、尺寸、织纹、页面字段、选择动作 | 条件、证据、边界、建议 | 不能把页面宣称写成检测结论 |
| 治愈微仪式 | P2 | 展开、触摸、擦拭、折叠、挂好 | 生活动作和感受 | 商品必须参与动作，不能只有氛围 |
| 关系微故事 | P3 | 准备、取出、留挂位、递给他人 | 关系行为与落点 | 不能用关系焦虑逼单 |
| 空间与玩趣 | P4、P5 | 同机位前后、配色、收纳、局部变化 | 变化前后和轻玩趣 | 不能同时改变多个变量后归因给毛巾 |
| 评论与答疑 | P1、P2、P6 | 真实评论、对应商品细节、回答动作 | 复述问题并回答 | 必须有真实问题来源 |
| 交易承接 | P6 | 当前商品页、规格、颜色、使用结果、品牌收尾 | 当前可购买信息和下一步 | 价格、库存、优惠必须为最新快照 |

### 4.3 类型约束

系统在Scene Plan阶段做类型检查：

- `test_selection`必须至少包含一个证据或选购动作。
- `healing_ritual`必须至少包含一个真实生活动作，且不允许用氛围素材替代商品动作。
- `relationship_story`必须有关系行为和商品参与点。
- `space_play`必须记录前后对照条件和改变变量。
- `comment_faq`必须绑定评论、客服或搜索问题来源。
- `transaction`必须绑定当前规格、颜色或商品页快照。

类型检查失败时进入`review_required`，不能靠补字幕绕过。

## 5. 商品事实、证据和权利准入

### 5.1 商品事实快照

现有`product_facts`继续作为单片事实输入，但campaign模式必须增加快照语义：

- `fact_snapshot_id`、`product_id`、`sku`；
- `source_record_id`、`source_hash`；
- `approved_by`、`approved_at`；
- `effective_from`、`effective_until`；
- `claims[]`和`availability_status`。

每个claim至少包含：

```json
{
  "claim_id": "P2-C03",
  "claim": "长绒棉材质",
  "status": "authorized",
  "evidence_status": "page_claim",
  "allowed_wording": ["长绒棉材质"],
  "forbidden_wording": ["一定更吸水", "检测级柔软"],
  "evidence_ids": ["P2-E01"]
}
```

### 5.2 证据类型分离

证据区分为：`page_claim`、`visually_observed`、`qualified_report`、`comment_source`、`needs_human_confirmation`、`restricted/forbidden`。

页面写有某个卖点，不等于已经有检测证据。系统必须保留来源类型，禁止把所有来源压成同一种“事实”。

### 5.3 四处事实门

1. 释放任务前：商品ID、SKU、事实负责人、授权和预算齐全。
2. Research到Script/Scene：每个强声明都有claim/evidence引用。
3. 付费资产前：事实快照仍有效，素材和声明没有撤回。
4. 交付和发布包前：重新检查价格、库存、优惠、规格和授权有效期。

事实未确认、证据过期、权利不清或SKU不匹配时，状态只能是`blocked`或`review_required`。

## 6. 素材和Seedance动作片链路

### 6.1 素材优先级

```text
已有核验素材
→ 页面主图/详情图中可授权的商品事实素材
→ 实拍补拍
→ Seedance动作片补位
→ 删除或改写该镜头
```

AI生成不能代替商品事实、颜色、Logo、包装、规格、检测结果和价格证据。

统一动作槽位：

```text
product_full_view
weave_macro
touch_brush
lift_unfold
fold_fall
color_reveal
use_context
```

每个素材槽位绑定SKU、用途、claim/evidence、允许动作、禁止动作、参考图、授权状态和已使用次数。

### 6.2 Seedance任务对象

每个任务保存：`motion_task_id`、`content_version_id`、`asset_slot_id`、`reference_asset_id`、`fact_snapshot_id`、`prompt_version`、`provider/model`、`duration/resolution/aspect_ratio`、`provider_job_id`、`cost_reservation_id`、`failure_class`、`identity_score`、`action_score`和`pool_status`。

失败分类至少包括：输入比例错误、真人隐私拦截、商品身份漂移、构图失败、动作不完整、纹理/颜色变化、供应商错误。

默认动作片3–5秒，推荐4秒。重试只能针对明确失败原因修改Prompt或输入，不允许无原因重复调用。

## 7. 单条视频的完整生成链

### 7.1 Research

输入事实快照、素材索引、页面快照和参考视频分析；输出研究摘要、证据矩阵、素材语义索引、类型候选和缺口清单。

参考视频只用于研究结构和节奏，不能直接作为商用素材。

### 7.2 Proposal

输出`direction_id`、`structure_id`、`support_type`、`recipe_id`、差异化Hook、主卖点、证据、预算和工具计划。

Remotion和HyperFrames都必须在Proposal阶段展示可用性、优点和代价。当前试点建议Remotion，但不能静默切换runtime；选择结果写入`decision_log`。

### 7.3 Script

脚本绑定`claim_id`、`evidence_id`、`asset_id`、`content_role`、口播、字幕、CTA和预计时长。脚本通过事实冲突检查后才能进入Scene Plan。

### 7.4 Scene Plan

每个镜头写清首帧、Hook、source asset或Seedance任务、时间码、动作、字幕安全区、口播时间、claim/evidence、类型必需动作和差异维度。

### 7.5 Assets和Creative Lock

锁定商品事实版本、素材槽位、Seedance任务、Doubao声线和语速、SUNO BGM、Remotion/FFmpeg输出方案、字幕、Logo、CTA、成本、并发和重试上限。锁定前不调用付费生成服务。

### 7.6 Sample、Edit和Compose

P1/P2各制作一条样片，检查商品身份、事实边界、口播、字幕、动作、声音和编码；通过后释放对应15条波次。

Remotion四层结构：

```text
BrandLayer     Logo、字体、字号、安全区、品牌收尾
ShotLayer      动作片、切换、裁剪、速度和交叉淡化
SpeechLayer    TTS、时间戳、字幕
AudioLayer     人声、BGM、ducking、淡入淡出
```

高密度版本默认单卖点镜头1.5–2.2秒，使用4–6个动作镜头，片尾0.8–1.2秒，口播结束后至少0.5秒余量，字幕由TTS时间戳驱动。

### 7.7 Delivery

通过QA后生成不可变`delivery_version`，绑定`content_version_id`、`fact_snapshot_id`、素材hash、脚本hash、分镜hash、render_report、final_review、technical_qa和human_review。

任何事实、素材或脚本实质变化都生成新版本，不覆盖已交付版本。

## 8. 批量差异性和实验控制

每条视频保存六维差异指纹：

```text
hook_type
narrative_structure
visual_grammar
pacing_profile
evidence_strategy
asset_strategy
```

可变项包括开场、第一动作、镜头排列、口播密度、生活情境、字幕节奏、BGM节奏和CTA位置。

固定项包括主SKU、事实版本、主体证据、颜色和规格事实、Logo/字体/安全区、交易承诺和输出规格。

同一实验组一次只改变一个主要变量。相似度检查在脚本、Scene Plan和成片三个阶段执行。

## 9. P1/P2 60条试点排期

| 阶段 | P1 | P2 | 目标 |
|---|---:|---:|---|
| W0准入 | 1条样片 | 1条样片 | 事实、素材、声音、字幕、编码门 |
| W1 | 8条 | 7条 | 实物证据和基础生活场景 |
| W2 | 7条 | 8条 | 生活场景和高频疑问 |
| W3 | 8条 | 7条 | 单变量复验 |
| W4 | 7条 | 8条 | 路径比较、补缺和复盘 |
| 合计 | 30条 | 30条 | 60条审核去重成片 |

每周15条拆成3个5条小批，每个小批完整经过脚本锁、素材锁、合成、QA和人工审核。

## 10. 质量门和验收标准

### 10.1 五类硬门

1. 事实门：SKU、规格、颜色、价格、声明与事实版本一致。
2. 证据门：强卖点有页面、实物、报告或真实问题来源。
3. 视觉/动作门：Logo和字幕不重叠，商品不变形、不变色、不串SKU，切换不闪烁。
4. 音频门：口播完整、字幕同步、人声清楚、BGM不盖人声。
5. 技术门：H.264、`yuv420p`、AAC-LC、1080×1920、30fps、MP4可播放。

任一硬门失败，不能以综合评分覆盖。

### 10.2 单条评分

| 维度 | 分值 |
|---|---:|
| 商品真实与证据 | 30 |
| 画面与剪辑 | 25 |
| 叙事与表达 | 20 |
| 技术质量 | 15 |
| 商品承接 | 10 |
| 合计 | 100 |

85分以上且无硬门失败，进入发布候选；75–84分回到Edit；低于75分回到Script或Scene Plan。

### 10.3 批量验收

60条试点完成后必须能追溯所属方向、结构、SKU、事实版本、父版本、改变变量、素材、动作片、证据、TTS、BGM、渲染参数、QA、返工原因、成本、发布ID和数据窗口。

## 11. 现有系统实施顺序

### P0：契约和准入

- 扩展campaign、slot、recipe和事实快照对象。
- 将六类视频类型接入artifact schema。
- 增加类型必需动作和内容角色校验。
- 增加P1/P2事实隔离、claim/evidence准入和有效期检查。
- 增加campaign级预算、状态和幂等检查。

### P1：60条试点

- 建立P1/P2两个事实快照和60个slot。
- 跑通各一条样片。
- 跑通Seedance动作补位、Doubao、SUNO和Remotion。
- 输出五层QA和不可变delivery。
- 完成一次人工飞书导入导出和复盘回写。

### P2：批量稳定化

- 增加campaign级差异矩阵和疲劳控制。
- 增加Seedance失败分类和素材池回收。
- 增加发布登记、经营数据导入和实验结论。
- 增加跨事实版本影响分析。
- 60条稳定后，再评估常驻批量runner和飞书自动同步。

### P3：扩展到300条

- 释放剩余方向、支持内容和SKU。
- 按周执行240条实验和60条支持内容。
- 每周复盘后再释放下一波槽位。
- 不使用低价值重复内容填补缺额。
- 对取消、延期、缺证据和暂停内容保留原因。

## 12. 测试计划

### Schema和单元测试

- 六类类型枚举和类型字段校验。
- P1/P2事实不能交叉引用。
- 无证据claim不能进入付费资产阶段。
- 重试不增加slot计数。
- 事实版本变化能定位受影响成片。
- 类型必需动作缺失时阻断Scene Plan。
- 过期价格、库存和优惠阻断发布包。

### 集成测试

- P1实测视频端到端生成。
- P2生活场景视频端到端生成。
- Seedance参考图到动作片入池。
- Doubao时间戳到字幕对齐。
- SUNO BGM到人声ducking混音。
- Remotion多镜头自然切换和片尾延长。
- 最终MP4在目标播放器打开。

### 故障测试

- Seedance商品身份漂移；
- TTS口播超过画面时长；
- 字幕超出安全区；
- 事实快照过期；
- 远程任务超时但结果未知；
- 渲染失败后恢复；
- 重复导入同一批次；
- 飞书导入字段缺失或无法映射。

## 13. 300条扩展的放行条件

60条试点满足以下条件后，才进入300条正式扩展：

- 六类视频类型已经至少有可运行的类型模板或明确的候选路径；
- P1/P2事实、证据、素材和授权链稳定；
- 单条视频可以从事实卡追溯到delivery；
- 批次中断可以恢复，不重复计数；
- 相似度检查能识别机械重复；
- QA、人工审核和返工原因已结构化记录；
- 成本、等待、失败和返工数据已真实采集；
- 至少完成一轮发布登记和经营数据导入；
- 复盘能够决定继续、修改、暂停或淘汰内容配方。

## 14. 当前实现状态

### 已实现或可直接复用

- `cinematic-fast`阶段式主线；
- `source_led_template`输入模式；
- `product_facts`事实卡校验；
- `template_batch`批次管理；
- `differentiation_plan`差异分析；
- checkpoint、人工审批和成本跟踪；
- Remotion、FFmpeg、Doubao TTS、SUNO和视频QA工具；
- P1/P2项目事实卡、素材清单和视觉规范。

### 已有但需要campaign接入

- 商品claim到脚本/分镜的稳定ID映射（已建立slot→recipe→fact snapshot关联，仍需接入正式脚本/分镜）；
- 素材SKU、证据用途和授权过滤（已有素材清单和证据角色，授权字段仍待人工确认）；
- 批次级差异阈值和疲劳控制（保留原有differentiation_plan，尚未接入60条准入报告）；
- TTS、BGM、动作片和delivery的统一追溯（现有样片可追溯音视频文件，尚缺canonical执行卡）；
- 发布和经营数据的外环登记。

### 尚需实施

- 六类类型的正式Scene Plan模板和必需动作检查；
- fact_snapshot的有效期、availability和证据记录联动；
- Seedance MotionGenerationTask与实际provider调用的完整入池和失败回收；
- 60条试点的人工飞书导入导出闭环；
- 60条完成后的300条扩展运行器评估。

## 15. 最终验收定义

主干升级完成的定义不是“批量生成了很多MP4”，而是：

> 任意一条视频，都能从300条规划中的方向和槽位出发，追溯到唯一商品事实版本、内容配方、证据、素材、动作片、口播、BGM、渲染参数、QA、人工审核、发布记录和经营结论；任意一个事实或权利变化，都能准确找到受影响的版本；任意一次失败，都能按原因恢复或重做，而不会污染计数和历史。

## 16. 2026-09-22 实施进度

本轮已经落地P0契约层，并通过新增契约测试和相关既有测试：

- 新增 `campaign_plan`、`content_recipe`、`fact_snapshot`、`campaign_content_link`、`motion_generation_task` 五个artifact schema。
- 新增 `lib/campaign_contracts.py`，提供campaign计划、事实快照、内容关联、动作任务的确定性构建和语义校验。
- `template_batch` 支持可选 `campaign_ref`，`template_run_plan` 支持可选 `campaign_content_ref`。
- `creative_control_plan`、`script`、`scene_plan`支持统一的`content_context`字段。
- campaign关联的run在进入付费素材前，会检查方向、结构、支持属性和内容版本字段。
- 新增测试覆盖slot去重、pilot计数、事实审批、控制变量、动作任务失败分类、版本影响范围和批次关联。
- 已将现有P1/P2 60条工作计划归一化为 `projects/playboy-towel-p1p2-v1/artifacts/campaign_plan.json`，并生成60个ContentRecipe、60个Campaign Content Link和P1/P2待业务确认的事实快照。
- 已加入跨文件campaign准入器：视觉样片允许使用待确认事实卡，付费准入会阻断未批准事实卡。
- 已对现有Remotion/Doubao/SUNO样片运行FinalQA和L1a：技术检查通过，报告写入`artifacts/evaluation_report.sample.json`。
- 已证明当前样片可以用于人工审核，但因尚未绑定script、scene_plan、shot_execution_plan、final_props和sample_execution_trace，升级门状态为`revise`，不能直接作为批量放行依据。

当前仍未宣称完成的部分：

- 六类视频的Scene Plan必需动作自动检查（当前已在recipe层做基础动作约束，尚未接到Scene Plan gate）；
- Seedance任务与实际provider调用的完整入池和失败回收；
- 飞书人工导入导出闭环；
- 60条试点之后的发布数据、经营复盘和300条扩展运行器；
- 单条样片的script/scene/shot execution/final props语义对齐闭环。

## 17. 下一阶段执行结论（2026-09-22）

当前可以给出审核样片，推荐使用：

`projects/playboy-towel-p1p2-v1/assets/video/generated/P1-MultiShot-3x4s-voice-bgm.mp4`

此前的P2-S01 12秒文件是旧的单品正式片，不能作为“单个动作镜头”；本轮已改为3个约4秒动作镜头拼接，单镜头约束由代码校验，且接入Doubao口播、SUNO BGM、格式兼容化和`sample_execution_trace`。该文件已通过1080×1920、30fps、H.264/AAC、解码、黑帧、冻结帧、响度和P1事实卡L1a检查；评估报告仍为`revise`，原因只剩script、scene_plan、shot_execution_plan和final_props尚未绑定，下一步应补齐这些canonical制品后再跑alignment和video_judge。

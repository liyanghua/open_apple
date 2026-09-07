# Cinematic Fast 商品主图卖点覆盖与图生视频补缺设计

> 日期：2026-09-07  
> 状态：已由用户确认，进入 TDD 实施
> 适用范围：`cinematic-fast` 的 `source_led` 与 `source_led_template`  
> 关联设计：[`2026-09-03-cinematic-fast-input-modes.md`](../plans/2026-09-03-cinematic-fast-input-modes.md)
> 实施计划：[`2026-09-07-product-image-coverage-routing.md`](../plans/2026-09-07-product-image-coverage-routing.md)

## 1. 背景

现有 source-led 主链已能完成商品页取证、商品事实调和、自有素材语义索引，以及事实—画面—口播—字幕的逐镜血缘传递。但商品主图目前只以 `composition_reference` 登记，所选 SKU 图只以 `identity_anchor` 登记；Scene Plan 和 Asset Plan 仍假设每个镜头都已有 owned source，因此没有把“主图定义卖点、自有素材优先、图生视频补缺”落实为可执行路由。

本设计解决以下问题：

1. 商品主图是卖点视觉表达的重要输入，而不只是附件。
2. 已有自有素材完整覆盖卖点时，继续优先使用真实素材。
3. 没有合格自有素材时，先从商品图产生可控的纯产品参考图，再用图生视频补足镜头。
4. 图生视频不能把商品页声明伪装成实拍或独立检测证据。
5. 全过程必须复用现有 Script、Creative Lock、Sample、L1a、alignment 和 final QA，不建立旁路。

## 2. 核心决定

### 2.1 不新增输入模式

商品图片是本商品的事实与生成参考资产，不是外部参考视频。因此：

- 有外部参考视频复刻时仍是 `reference_driven`；
- 只有自有素材和商品图时仍是 `source_led`；
- 只有自有素材、商品图和内部节奏模板时仍是 `source_led_template`。

不得因为使用主图做图生视频而把 run 标成 `reference_driven`，也不得创建独立的 product-image pipeline。

### 2.2 主链采用三态覆盖路由

用户提出的两种使用方式构成前两级；主链必须增加第三个 fail-closed 结果：

1. `owned_source`：自有素材完整包含要求的主体、动作和可见结果；
2. `generated_from_product_image`：未找到合格自有素材，使用纯产品参考图生成镜头；
3. `omit`：商品事实、SKU、参考图或生成风险不满足要求，不生成、不猜测、不把无关镜头硬配给卖点。

这三态是同一条 canonical mainline 的视觉覆盖决策，不是三条生产链。

## 3. 设计原则

### 3.1 事实证据与视觉表达分层

商品页、检测报告和人工确认决定“能说什么”；自有视频或生成视频决定“画面如何表达”。

- owned source 可以成为“画面观察证据”，但不能自动证明超出画面范围的功效；
- generated video 只能成为“视觉表达资产”，不能升级为商品功效的独立事实证据；
- 不可见功效（如抗菌等级、安全类别、材质成分）必须继续以商品页声明或合格报告为事实来源；
- 口播和字幕必须使用对应事实的 `allowed_wording`，不能复用主图中被禁止或未确认的烧录文案。

### 3.2 商品身份优先于动作丰富度

图生视频首先要保持商品外观、颜色、纹理、品牌和 SKU 一致，其次才追求运镜和动作。任何生成结果出现颜色漂移、结构变化、品牌错字或毛巾形态失真，都不得进入 Sample。

### 3.3 自有素材优先，但不迁就弱匹配

“素材存在”不等于“卖点已覆盖”。只有主体、动作、结果、时间区间和 3:4 构图都满足要求，才允许选择 `owned_source`。弱匹配必须进入生成补缺或 `omit`，不能用滚动、测量、摆拍等不相干动作顶替卖点。

## 4. Canonical 数据流

```text
product_page_capture + product_asset_ledger + product_facts
                         ↓
              claim_visual_requirements
         （主体 / 动作 / 结果 / SKU / 风险）
                         ↓
source_semantic_index → coverage router
                         ├─ owned_source
                         ├─ generated_from_product_image
                         └─ omit
                         ↓
reference_source_matrix（唯一 evidence matrix）
                         ↓
Script → Scene Plan → Shot Execution Plan → Asset Plan
                         ↓
Creative Lock（显示参考图、路由、prompt、provider、费用）
                         ↓
clean reference → image-to-video → TTS/BGM → Sample
                         ↓
L1a + identity QA + temporal alignment + 3:4 QA + human sample review
```

## 5. 商品图语义和纯产品参考图

### 5.1 原始资产不改写

商品页下载的原始主图和 SKU 图保持不可变，并继续记录 URL、页面位置、尺寸、mime、SHA-256 和 SKU scope。所有清洗结果均作为派生资产写入 ledger，不能覆盖原图。

### 5.2 纯产品参考图生成顺序

1. 优先选择与目标 SKU 精确一致、无风险文字遮挡的 SKU 图；
2. 若主图更能表达目标卖点，则先执行确定性裁切或遮罩，移除烧录文字和无关检测截图；
3. 若裁切会破坏产品主体，可执行受控的图像修复/扩图；
4. 任何生成式清洗均必须保持产品结构、颜色、纹理、品牌标识和 SKU 特征；
5. 清洗后运行 OCR、图像尺寸、主体完整性和身份一致性检查；
6. 检查失败时状态为 `needs_human` 或 `rejected`，不得直接送入图生视频。

纯产品参考图建议 ledger 结构：

```json
{
  "asset_id": "page-asset-main-03-clean-v1",
  "asset_role": "derived_clean_reference",
  "usage_role": "generation_reference",
  "parent_asset_id": "page-asset-main-03",
  "claim_refs": ["product_facts.claims[12]"],
  "sku_scope": ["6276962282892"],
  "transforms": [
    {"operation": "text_region_removal", "input_hash": "...", "output_hash": "..."}
  ],
  "clean_reference_status": "ready",
  "ocr_residual_text": [],
  "identity_check": {"status": "pass"}
}
```

### 5.3 付费清洗的审批边界

- 本地确定性裁切/遮罩可在 Assets 计划阶段生成审片代理，费用为零；
- 如果必须调用付费图像编辑模型，Creative Lock 首次只批准“纯产品参考图”生成；
- 纯产品参考图生成后重开同一 Assets gate 的新 revision，用户确认参考图后才允许图生视频；
- 不得在用户尚未看见清洗结果时串行消耗图像生成和视频生成两笔费用。

## 6. 卖点视觉要求

每个准备进入视频的商品事实必须编译为 `claim_visual_requirements`：

```json
{
  "product_fact_ref": "product_facts.claims[12]",
  "claim_id": "page-claim-absorb-dry",
  "visualizability": "observable",
  "required_subjects": ["target_product"],
  "required_actions": ["continuous_pour_water", "water_contacts_towel"],
  "required_results": ["visible_water_contact_result"],
  "forbidden_substitutions": ["roller_only", "single_droplet_only"],
  "allowed_wording": ["一股水浇下，湿润范围清楚可见"],
  "prohibited_wording": ["一触即收", "瞬间吸干"],
  "candidate_page_asset_ids": ["page-asset-main-03"],
  "sku_scope": ["6276962282892"]
}
```

`visualizability` 分为：

- `observable`：动作与结果可以直接拍摄或生成，如倒水、触摸纹理、叠放厚度；
- `contextual`：画面只能做场景支撑，如尺寸、材质、颜色；
- `non_observable`：抗菌等级、安全类别、检测结论等，生成画面不能充当证明，只能配合明确的商品页/报告声明。

## 7. Coverage Router

### 7.1 `owned_source` 准入

只有同时满足以下条件才能使用自有素材：

- 目标商品或可确认的同 SKU 主体存在；
- `required_actions` 均落在选定时间区间；
- 对 `requires_visible_result=true` 的卖点，要求结果态可见；
- 不包含 `forbidden_substitutions`；
- source hash、时间区间、代表帧和 crop safety 完整；
- 3:4 裁切后主体与动作结果仍完整；
- evidence strength 达到该事实所需等级。

### 7.2 `generated_from_product_image` 准入

当不存在合格的 owned source 时，只有满足以下条件才能生成：

- 商品事实已确认且 SKU scope 与 run 一致；
- 至少一个 `generation_reference` 状态为 `ready`；
- prompt 只使用 `allowed_wording` 和要求动作，不包含主图的风险烧录文字；
- provider 明确支持 `image_to_video` 和目标画幅或安全裁切；
- 计划中写明参考图 hash、动作、结果、负面约束、时长、费用和重试上限；
- Creative Lock 已批准当前 subject hash。

### 7.3 `omit` 条件

以下任一情况必须 `omit` 或回到人工修订：

- 商品事实未确认或 SKU 冲突；
- 只有高风险页面宣传，且没有允许使用的表述；
- 没有可安全清洗的商品图；
- 生成视频无法保持商品身份；
- 该事实本质不可见，却被要求生成“证明效果”的画面；
- 预算、provider 或重试上限不允许继续。

## 8. Artifact 扩展

### 8.1 `product_asset_ledger`

在现有原图字段上增加：

- `claim_refs[]`
- `derived_asset_ids[]`
- `clean_reference_status`
- `ocr_regions[]` / `ocr_residual_text[]`
- `identity_check`
- `transforms[]`
- `generation_eligibility`

### 8.2 `reference_source_matrix`

仍是唯一 canonical evidence matrix，不新增第二套矩阵。source-led row 增加：

```text
visual_route: owned_source | generated_from_product_image | omit
claim_visual_requirements
owned_candidates[]
selected_source（仅 owned_source）
generation_reference（仅 generated_from_product_image）
route_reason
```

`owned_source` 行要求 source media/hash/interval；`generated_from_product_image` 行禁止伪造 source interval，改为要求 page asset、clean reference hash 和 generation specification。

### 8.3 `scene_plan`

`metadata.source_mapping[]` 改成按 `visual_route` 区分的条件结构：

- `owned_source`：保留 source path/hash/interval；
- `generated_from_product_image`：绑定 clean reference、prompt contract、预期动作/结果和 provider capability；
- `omit`：不得进入已批准 Script/Scene，必须先改写或移除对应 section。

### 8.4 `shot_execution_plan`

复用现有 `coverage_status`、`gap_strategy`、`generation_proposals`，但让它们真正参与执行：

- owned：`coverage_status=enough`、`gap_strategy=none`；
- generated：`coverage_status=gap`、`gap_strategy=generate_from_product_image`，且至少有一个 proposal；
- proposal 必须绑定 fact、reference image、prompt、provider/model shortlist、成本和 approval subject hash。

### 8.5 `asset_plan`

新增条件资产类型：

- `video_proxy`：已有自有素材的本地代理；
- `clean_product_reference`：纯产品参考图；
- `generated_video`：已批准的图生视频任务。

`paid_generation_approved=false` 时，所有付费资产都必须 `exists=false`，现有门控继续有效。

## 9. 工作台设计

Assets 审核页按“一个卖点一张覆盖卡”展示：

1. 商品事实：事实原文、SKU、风险、允许/禁止表达；
2. 商品主图：原图、纯产品参考图、清洗方式与身份检查；
3. 自有素材检索：候选视频、动作/结果覆盖、未采用原因；
4. 路由结论：使用自有素材、图生视频或放弃；
5. 成片表达：口播、字幕、画面动作和时间位置；
6. 生成计划：provider、模型、prompt 摘要、时长、比例、预计费用和重试上限。

工作台必须明确区分：

- “商品页声明”；
- “自有素材可见结果”；
- “AI 生成的视觉表达”。

不得把生成视频标为事实证明，也不得只显示“待生成”而不告诉运营生成什么、依据哪张图、如何验收。

## 10. Provider 与运行时

主链继续通过 registry/selector 选择支持 `image_to_video` 的 provider，不在 schema 或业务代码中硬编码厂商。Asset Plan 必须锁定本次实际 provider/model，并在调用前向用户说明。

当前机器的能力快照显示视频生成 provider 为 8/22 configured，已有多个支持 image-to-video 的候选；这是运行时信息，不写死进设计契约。具体选择需基于：

- 本地参考图输入能力；
- 商品身份保持能力；
- 3:4 或中心安全构图；
- 时长和成本；
- 当前可用性与配额。

最终合成继续使用 run 已批准的 render runtime。本设计不改变 Remotion/HyperFrames/FFmpeg 的选择规则。

## 11. 生成与 QA

### 11.1 生成 prompt 合同

prompt 必须包含：

- 商品身份与参考图保持要求；
- 单一、可验证的动作；
- 必须出现的结果态；
- 镜头和光线；
- 3:4 主体安全区；
- 禁止新增文字、logo、包装、人物肢体异常和颜色漂移；
- 不得加入 `prohibited_wording` 对应的夸张效果。

### 11.2 生成结果准入

进入 Sample 前逐条检查：

- reference image hash 与任务一致；
- 商品身份、颜色、纹理和结构没有漂移；
- 动作与结果完整覆盖；
- 没有模型生成文字或错误品牌；
- 3:4 裁切主体完整；
- 与口播/字幕的 claim/action/evidence 合同一致；
- 成本和重试次数在批准范围内。

失败结果不得由普通人工“通过”覆盖 known fail；只能重试、改写或 `omit`。

## 12. 银离子毛巾 Pilot 预期路由

| 卖点/镜头职责 | 当前预期路由 | 说明 |
|---|---|---|
| 吸水过程 | `owned_source` | 已有连续倒水且接触结果可见的素材 |
| 双面毛圈 | `owned_source` | 已有毛圈微距素材；文案只描述可见纹理和商品页参数 |
| 蓬软/亲肤 | `owned_source` | 已有轻抚和轻揉两种动作；不得用棉花道具替代证明 |
| 加厚款 | `owned_source` | 使用叠放厚度层次，不使用无效量具读数 |
| AG+ 银离子/10A 抗菌 | `generated_from_product_image` 或信息卡 | 属于不可见功效；生成画面只能做商品视觉表达，事实仍标注为商品页声明 |
| 柔胭粉 32×72cm/120g | SKU identity card | 使用选中 SKU 图确认身份和参数，不冒充动作证明 |
| 日常洁面/取用/挂放 | context shot | 只描述可见动作，不强行绑定性能卖点 |

Pilot 在新的 Assets gate 中展示最终路由；表中是设计预期，不替代运行时检索与人工审核。

## 13. 失败处理与恢复

- owned candidate 失配：保留拒绝原因，改走生成，不删除原始分析；
- 清洗参考图失败：同一 Assets gate 新 revision，等待人工更换图片或允许付费清洗；
- provider 不可用：结构化报告 provider/auth/quota 问题，不静默换厂商；
- 生成身份漂移：按批准的重试上限重试，超过上限回到 Assets；
- 高风险事实缺乏合格表述：`omit`，不得用生成画面补事实；
- checkpoint 恢复：`next_action` 必须记录当前 route、reference asset 和未完成任务，不重新猜测。

## 14. 兼容性和迁移

- 现有全 owned source 项目继续产生 `video_proxy`，行为和 hash 规则保持兼容；
- 旧 evidence rows 没有 `visual_route` 时，只有 source/hash/interval 完整才迁移为 `owned_source`；
- 缺少 source 的旧行不能自动迁移为生成路由，必须重新运行 Research coverage router；
- 毛巾 wrapper 继续只调用 canonical builder，不实现自己的图生视频判断；
- 不改变 `reference_driven` 对真实外部参考视频的约束。

## 15. 测试策略

### 15.1 Contract tests

- 自有素材完整覆盖时选择 `owned_source`，不产生付费任务；
- 缺少 owned source 且 clean reference 就绪时选择 `generated_from_product_image`；
- 生成行不得伪造 source media/hash/interval；
- 生成行必须绑定 fact、page asset、clean reference hash、动作、结果和费用；
- 不可见高风险事实不得把生成视频标记为事实证据；
- 不安全主图、SKU 冲突或残留风险文字时只能 `needs_human/rejected/omit`；
- Creative Lock 前 provider 调用次数为零。

### 15.2 Integration tests

- product URL → 主图/SKU → clean reference → coverage route → Script → Scene → Assets；
- owned match 和 generated fallback 可在同一 run 混合；
- 付费 clean-reference 场景会重开 Assets revision，未审核前不调用图生视频；
- 生成结果 identity/alignment fail 时不能进入 Sample；
- 无商品 URL 时，仅在用户上传并确认商品图后允许相同 fallback。

### 15.3 银离子 Golden cases

- 连续倒水匹配吸水过程；单水滴和滚筒不得通过；
- 棉花道具不得证明亲肤柔软；
- `0.00` 量具读数不得证明厚度或克重；
- 抗菌/安全类生成镜头不得升级为独立功效证据；
- 所选 SKU 图必须保持柔胭粉、32×72cm、120g 的范围，不得把其他颜色当作当前 SKU。

## 16. 验收标准

设计实施完成需同时满足：

1. 商品主图能够以 claim-level reference 进入 Research，而非只登记不消费；
2. 每个卖点都有可解释的 `owned_source/generated_from_product_image/omit` 决策；
3. 自有素材匹配依赖主体、动作、结果和 3:4 安全性，不以文件名或单帧相似代替；
4. 没有自有素材时能生成纯产品参考图并在人工可见后执行图生视频；
5. 所有付费调用都发生在对应 Creative Lock 之后；
6. 生成镜头完整继承 fact/page asset/action/copy/hash 血缘；
7. 生成资产不被当作事实或检测证据；
8. 工作台能说明每个镜头“为什么用、为什么生成、依据哪张图、说什么、花多少钱”；
9. 银离子毛巾全长 3:4 样片通过身份、构图、L1a、时序 alignment 和人工效果检查；
10. 全 owned source 的既有项目无需迁移即可继续运行。

## 17. 明确不做

- 不创建独立的商品图生视频旁路；
- 不把主图原有文字直接复制进最终字幕；
- 不允许生成视频证明不可见功效；
- 不在 Research 或 Creative Lock 前调用付费 provider；
- 不为了填满时长而给每个场景镜头强行分配卖点；
- 不在本设计阶段锁定具体厂商或绕过现有 provider selection/decision log。

# Source-led 淘宝 3:4 种草视频升级规范 v1.0

> 状态：设计规范，待实施评审
> 适用链路：`cinematic-fast` / `source_led` / `source_led_template`
> 适用平台：淘宝详情页种草视频
> 目标画幅：3:4（样片 540×720、上传版 1080×1440、主片 2160×2880）
>
> 本规范把已通过的银离子毛巾样片经验固化为主链约束。它不创建旁路，所有商品图补镜、字幕调整和审核动作必须回到 canonical mainline。

## 1. 规范等级

文中使用以下关键词：

- **MUST**：硬性契约；不满足时阻断下游阶段。
- **SHOULD**：默认策略；有明确理由时可由 Agent 覆盖，但必须写入 decision log。
- **MAY**：可选实现，不改变事实、审批和溯源契约。

## 2. 主链与输入模式

生产必须沿用：

```text
research → proposal → script → scene_plan → assets → edit → compose
→ sample → final_qa → L1a → publish
```

输入模式必须显式记录：

| 模式 | 触发条件 | 约束 |
|---|---|---|
| `reference_driven` | 用户提供外部参考视频 | 参考片只提供结构、节奏、镜头语法和风格依据 |
| `source_led` | 有商品事实和自有素材，无外部参考视频 | 自有素材和商品页资产是证据源 |
| `source_led_template` | `source_led` 加内部模板包 | 模板只提供节奏、结构和槽位，不提供商品事实 |
| `template_led` | 无自有视频，只有模板和商品图 | 可生成视觉表达，但必须遵守商品身份和事实边界 |

商品主图、SKU 图、详情图或纯产品参考图 **MUST NOT** 将任务标记为 `reference_driven`。

## 3. 商品事实契约

### 3.1 商品页采集

提供商品 URL 时，浏览器采集 **MUST** 生成并持久化：

```text
product_page_capture.json
product_asset_ledger.json
product_facts.json
```

采集版本使用 `ProductPageCapture 1.1`。只有以下页面面均有证据时，`acquisition_status` 才能为 `complete`：

1. 商品身份；
2. URL 对应的选中 SKU；
3. 参数表；
4. 完整主图组；
5. 详情内容。

主图和详情图中的烧录文案可以进入事实候选，但默认等级为 `page_claim`，不能直接升级为检测事实。价格、库存、优惠和时效必须标记 `volatile=true`，默认不得进入可复用口播。

### 3.2 事实等级

每个事实 **MUST** 标记来源和允许口径：

| 等级 | 例子 | 使用边界 |
|---|---|---|
| `verified_report` | 报告正文和适用 SKU 明确 | 可进入口播和字幕 |
| `page_fact` | 材质、尺寸、颜色、页面参数 | 经人工确认后使用 |
| `visual_observation` | 视频中真实可见的动作和结果 | 只能描述可见内容 |
| `generated_expression` | 图生视频创造的视觉表现 | 不是独立事实证明 |
| `volatile` | 价格、库存、活动 | 默认不进入复用脚本 |
| `unverified_claim` | 无报告支撑的高风险功效 | 禁止直接使用 |

### 3.3 卖点视觉要求

进入脚本的每个卖点 **MUST** 编译为 `claim_visual_requirements`，至少包含：

```json
{
  "claim_id": "claim-absorb-dry",
  "product_fact_ref": "product_facts.claims[12]",
  "visualizability": "observable",
  "required_subjects": ["target_product"],
  "required_actions": ["continuous_pour_water"],
  "required_results": ["visible_water_contact_result"],
  "forbidden_substitutions": ["roller_only", "single_droplet_only"],
  "allowed_wording": ["水流接触后，湿润范围清楚可见"],
  "prohibited_wording": ["一触即收", "瞬间吸干"],
  "sku_scope": ["sku-id"],
  "candidate_page_asset_ids": []
}
```

口播写“连续倒水”，镜头 **MUST** 出现连续倒水；滚动、称重、摆拍等动作不得作为隐式替代。不可见功效（如抗菌等级、安全类别、检测结论）只能由商品页或报告支撑，不能由生成画面补成“已证明”。

## 4. 素材覆盖路由

每个卖点/镜头只能选择以下三态之一：

```text
owned_source | generated_from_product_image | omit
```

### 4.1 `owned_source`

必须同时满足：

- 商品主体或同 SKU 可确认；
- 所有必需动作落在选定时间窗；
- 需要结果的卖点有可见结果态；
- 素材 hash、时间窗、代表帧和 crop safety 完整；
- 3:4 中心裁切后主体和结果仍完整；
- 不命中 `forbidden_substitutions`；
- 证据强度达到该事实要求。

### 4.2 `generated_from_product_image`

必须同时满足：

- 事实已确认且 SKU scope 与 run 一致；
- 至少一张 `generation_reference=ready` 的纯产品参考图；
- 参考图通过 OCR、主体完整性和身份一致性检查；
- prompt 只使用 `allowed_wording` 和动作/结果要求；
- 计划写明参考图 hash、动作、结果、负面约束、时长、费用和重试上限；
- Creative Lock 已批准当前 approval subject hash；
- provider 能力支持 image-to-video 和目标画幅。

生成视频是视觉表达资产，**MUST NOT** 被写入事实证据字段。

### 4.3 `omit`

出现以下任一情况必须省略卖点或回到人工修订：事实未确认、SKU 冲突、参考图不安全、生成身份漂移、不可见功效要求生成证明、预算或 provider 不允许继续。

## 5. 逐镜血缘与对齐

跨阶段引用 **MUST** 使用键控关系，不得依赖数组位置：

```text
product_fact
→ claim_visual_requirement
→ script.section
→ scene_plan.scene
→ shot_execution_plan.shot
→ asset_plan.asset
→ narration/caption asset
→ sample frame
```

每个 shot 至少保存：`section_id`、`scene_id`、`claim_refs`、`visual_route`、素材或参考图 hash、时间窗/生成规格、`narration`、`screen_copy`、`evidence_type`、`crop_safety` 和 `alignment_status`。

硬门要求：

- `script.section.scene_id`、`scene_plan.scene.id`、`shot.section_id` 必须闭合；
- 口播开始时间不得早于动作证据窗口；
- 花字、口播和画面必须表达同一主要卖点；
- `alignment_status` 非 `pass` 不得进入 final render；
- `omit` 行不得进入已批准 Script。

## 6. 淘宝 3:4 字幕 Treatment

字幕规范必须作为版本化制品 `caption_treatment_profile.json` 保存，不得只存在于代码默认值中。默认 profile：`taobao_detail_3_4_v1`。

### 6.1 左上卖点花字

MUST：

- 位于左上安全区；
- 大号字体、竖排展示；
- 每镜最多一个主要卖点；
- 默认 4 至 8 个字；
- 有描边和轻量入场特效；
- 不遮挡商品主体、动作和结果；
- 不承载完整口播句。

推荐：`吸水快`、`柔软亲肤`、`加厚不透`、`干湿分离`。

### 6.2 底部口播字幕

MUST：

- 位于淘宝 3:4 底部安全区；
- 一行展示，不换行；
- 不截断、不使用省略号；
- 与实际 TTS 文本完全一致；
- 超出安全宽度时回到 Script 改写，不强行缩小到不可读。

### 6.3 修改影响矩阵

| 修改 | 最小重跑范围 |
|---|---|
| 颜色、描边、位置、入场 | 全量 Sample 重渲染并重开审核 |
| 花字文本 | Script → TTS/字幕 → Sample |
| 口播文本 | Script → TTS → 字幕 → Sample |
| 仅音量/混音 | 可 `mux_only`，但必须重做响度 QA |
| 卖点、事实、故事顺序 | 回 Research/Script |

## 7. Profile、渲染与缓存

| profile | 尺寸 | 用途 |
|---|---:|---|
| `sample` | 540×720 | 人审样片 |
| `upload` | 1080×1440 | 淘宝上传版 |
| `master` | 2160×2880 | 主片交付 |

渲染结果 **MUST** 记录计划尺寸、实际尺寸、fps、profile hash 和 caption profile id。文件名必须由实际 profile 派生，例如：

```text
silver-towel-a-sample-540x720.mp4
silver-towel-a-upload-1080x1440.mp4
silver-towel-a-master-2160x2880.mp4
```

缓存复用前必须再次校验 profile、实际宽高、script/scene/asset/TTS fingerprint 和 caption profile hash。文件名与实际尺寸不一致时硬拦。

## 8. 审核工作台与审批事务

Assets 卡片不得只显示“源素材代理 / 待生成”。每张卡必须显示：卖点事实、SKU、允许/禁止口径、原始主图、纯产品参考图、候选素材及拒绝原因、选定路由、动作/结果、口播、花字、provider、3:4 目标、预计费用和重试上限。

生成资产必须显式标注：`AI 视觉表达，不是商品事实证明`。

点击审核通过时必须原子完成：

```text
approval decision
→ artifact revision
→ checkpoint
→ decision_log
→ next_action
```

接口必须支持幂等提交、stale revision 检查、半提交恢复，并展示 `approved_at`、`approved_by`、`approval_revision`。任一步失败不得显示“已通过”。

## 9. 质量门

### Research

商品采集完整、SKU 一致、主图/SKU 台账完整、高风险事实已分级。

### Script

每个卖点有视觉要求和允许口径；每镜一个主要卖点；用户已确认。

### Scene/Assets

路由可解释；时间窗有效；3:4 crop safety 通过；生成任务有参考图、费用、provider 能力和审批 hash。

### Sample

实际尺寸正确；主体完整；左上花字大号竖排；底部口播单行；TTS 完整；逐镜画面/花字/口播对齐通过。

### Final QA/L1a

商品身份、SKU、事实口径、画面匹配、3:4 构图、字幕、口播、响度、生成血缘、文件命名和交付目录全部通过。

## 10. 代码、Skill 与 Agent 的边界

### 10.1 固化为代码

输入模式、商品事实 schema、素材 ledger、Coverage Router、键控血缘、caption profile、单行布局、安全区、profile/缓存校验、审批事务、alignment gate、L1a/final QA 和交付命名。

### 10.2 固化为 Skills

建议提供以下可复用技能：

- `source-led-ecommerce-montage`：事实分级、主图/SKU 选择、素材优先、补镜和 omit。
- `taobao-detail-3-4-review`：主体完整性、花字/口播规范、商品身份、L1a 审核。
- `caption-revision-loop`：字幕/口播修改的影响范围和重渲染策略。
- `sample-profile-verification`：渲染前后 profile、尺寸和缓存检查。

### 10.3 保留给 Agent 的判断

Agent 负责选择本条视频的 3 至 5 个卖点、判断镜头是否真正证明口播、安排变体差异、决定补镜价值和表达边界。每项判断必须写入 `decision_log`、`creative_control_plan` 或 `alignment_review`，不得只留在对话上下文。

## 11. 验收指标

一条视频只有同时满足以下条件才算通过：

1. 商品事实来源和 SKU 可追溯；
2. 每镜有唯一事实、视觉要求和覆盖路由；
3. 自有素材命中时优先使用，未命中才补镜；
4. 生成画面不冒充事实证明；
5. 左上花字大号、竖排、有特效；
6. 底部口播一行、不换行、不截断；
7. 文件名、profile 和实际分辨率一致；
8. 审批状态与 checkpoint 一致；
9. 逐镜画面、花字、口播通过 alignment；
10. L1a、final QA 和交付记录完整。

## 12. 实施优先级

### P0

1. `caption_treatment_profile` 制品化；
2. 字幕视觉回归（540×720、1080×1440、2160×2880）；
3. 样片实际 profile/文件名绑定；
4. 审批事务化；
5. 工作台显示实际 profile、关键帧和逐镜对照。

### P1

1. Coverage Router 接入全部 `source_led_template`；
2. 主图/SKU 图进入 claim-level requirements；
3. 纯产品参考图清洗、OCR 和身份检查；
4. 图生视频任务的授权、费用和重试控制；
5. alignment review 人工通道。

### P2

1. 四产品 × 四变体批量运行；
2. 运营工作台可编辑 profile；
3. 卖点—镜头—审核结果回流；
4. 淘宝、抖音、小红书 profile 参数分离。

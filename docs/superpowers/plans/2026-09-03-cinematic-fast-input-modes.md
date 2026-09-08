# Cinematic Fast Input Modes and Source-Led Semantic Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `cinematic-fast` 统一为一条主干，同时明确区分“有外部参考视频”和“仅自有素材（可选内部模板先验）”两种输入模式；当用户提供商品链接时，Research 必须先通过浏览器采集商品事实、当前 SKU 与主图证据，再把画面—口播—花字匹配、素材理解和成片去重固化到 Research → Script → Scene Plan → Sample 契约中。

**Architecture:** 保留 `cinematic-fast` 的阶段和 checkpoint，不新增毛巾专用 production path。新增显式 `input_mode`、browser-first product acquisition 与 evidence contract：Research 先固化商品页、SKU、主图及来源，再判断自有素材能证明什么；Script 只能使用被 Research 接受的 claim/action，Scene Plan 必须把 section 映射到自有素材证据区间，Assets 和 Sample 通过 hash、ID 和渲染后时序语义检查阻止漂移。外部参考只影响 `reference_driven` 模式；商品主图提供商品身份和信息证据；模板包在 `source_led_template` 模式中只能作为结构先验，不能成为商品文案或事实来源。

**Tech Stack:** Python tools and artifact builders, YAML pipeline manifests, JSON Schema, `lib.checkpoint`, `lib.artifact_io`, existing `cinematic-fast` directors, `template_pack/template_run_plan`, Remotion/HyperFrames composition, `final_qa`, `technical_validator`, `video_judge`, pytest.

---

## 1. Decision Summary

本次毛巾任务的正式归类：

```yaml
pipeline: cinematic-fast
input_mode: source_led_template
external_reference: false
template_prior: structural_only
source_of_truth: operator_confirmed_product_facts + owned_source_media
product_page_evidence: browser_capture_when_url_present
dedup_scope: product + candidate_batch
```

### 1.1 2026-09-06 复审修订：商品页取证与时序对齐

四条真实样片暴露出“结构闭合但语义仍错”的问题。以银离子样片为例：连续倒水被写成“水滴一沾上”；滚筒经过被写成“吸得干爽”，但画面没有出现吸收结果；棉花道具被当成柔软事实；显示 `0.00 N` 的测量画面被写成“称出来有分量”。现有抽帧报告虽然能产生 `partial`/`fail`，但后续仍可通过人工候选选择，说明 gate 仍然 fail-open。

本修订锁定四项升级：

1. 用户给出 `product_url` 时，浏览器采集成为 Research 必经子阶段，不能靠标题猜测、旧模板或批次脚本补事实。
2. 商品页内容按“商家页面声明”管理，不自动等同于独立检测证据；涉及功效结果的文案还必须由自有视频中的连续动作和结果，或合格报告支撑。
3. 逐镜匹配从单帧、宽泛动作域升级为“主体 + 精确动作 + 可见结果 + 时间覆盖”的时序证据；已知语义失败不得被普通 sample approval 覆盖。
4. 浏览器采集、事实确认、逐镜预检、低清全长样片均通过后，才允许调用付费 TTS 或进入正式渲染。

本修订优先级高于 2026-09-02 的阶段性“Task 1-7 完成”结论；旧结论只证明当时的契约测试通过，不再代表真实样片可合并或可运营。

### 1.2 当前银离子链接的浏览器验证记录

2026-09-06 已用浏览器打开用户提供的天猫详情页，并验证该采集方案可以获得以下信号：

- 页面：`item_id=1060430166297`，URL `skuId=6276962282892`，页面当前选中规格为“柔胭粉”。
- 标题：`【银离子抗菌】花花公子纯棉100全棉毛巾吸水防臭不掉毛成人面巾`。
- 可见参数包括：A 类、纯棉、棉含量 100%、吸水性等级 5s–10s、双面毛圈、抗菌处理、品牌 PLAYBOY/花花公子、荧光剂未检出、纤维配比 100% 新疆长绒棉、货号 `yb-bb-03`、2026 年上市。
- 页面暴露 5 张 1440×1920 主图缩略图、1 张 1000×1000 当前主图，以及一组 1200px 宽详情图，可进入资产台账。

这些内容目前只标记为 `page_claim`/`identity_anchor`，并非已批准成片文案。例如“抗菌处理”“荧光剂未检出”仍需核对页面资质材料、适用 SKU 和允许表述；“吸水性等级 5s–10s”不能让滚筒经过或连续倒水画面自动成立。价格/优惠虽可见，但按易变事实排除在本次通用文案之外。

三种输入模式共用一条主干：

| `input_mode` | 输入 | Research 任务 | Scene Plan 允许的 `reference_evidence` |
|---|---|---|---|
| `reference_driven` | 外部参考视频 + 自有素材 | 分析参考片的结构、节奏、镜头机制，再寻找自有素材的等价证据 | `direct_segment`、`structural_only`、`none` |
| `source_led` | 只有自有素材 | 理解素材主体、动作、结果、可说事实、构图安全性和素材相似性 | 仅 `none` |
| `source_led_template` | 自有素材 + 内部 `template_pack` | 以自有素材为语义来源，以模板提供节奏/镜头/字幕结构先验 | `structural_only`、`none`；禁止外部 reference interval |

模式由项目输入契约决定，不能由脚本目录名或是否存在 `stage50` 判断。没有外部参考时，不能把 `template_pack` 伪装成参考视频，也不能生成带虚构 `reference_scene_id` 的映射。

## 2. Scope and Non-Goals

### In scope

- 为 `cinematic-fast` 增加输入模式选择和 Research 分支。
- 将素材语义理解、claim/evidence/action 绑定、逐镜匹配和跨候选去重纳入主干 artifact。
- 保留模板批量能力，但把 `template_pack/template_run_plan` 限定为结构先验。
- 让 TTS、字幕、proxy、render payload 和 alignment report 绑定同一组 artifact hashes。
- 将当前毛巾批次的 `stage25/30/40/50/51` 改成 canonical builder 的迁移包装器。

### Out of scope

- 本设计不立即重跑 16 条最终主片。
- 不在生产关键路径中新增付费 provider、替换 TTS/BGM provider 或改变 Remotion/HyperFrames 选择。
- 不要求 Research 阶段用 VLM 取代确定性 ID/hash/事实硬门。
- 不把外部模板或参考片的台词、花字、字体、音乐或 logo 复制进最终资产。

## 3. Current-State Diagnosis

已有修复解决了结构漂移问题：`section_id`、`scene_id`、TTS binding、sample/script hash、3:4 profile 和 alignment hard gate 已存在。但语义链仍不完整：

```text
research_breakdown / semantic_map
        ↓（目前由批次脚本重新解释）
template slot / script narration
        ↓
scene/source mapping
        ↓
TTS + captions + render
```

风险是“结构 ID 正确但语义错误”：口播说吸水，画面只是平铺；花字说亲肤，画面展示包装；四条候选只换模板包装而复用相同动作顺序。根因是 claim/action/evidence 没有成为 Script 和 Scene Plan 的必填前向约束，去重也未在 Research/Proposal 建模。

2026-09-06 对当前实现的复核进一步确认：

- `stage25_research_artifacts.py` 仍可能按观察顺序绑定商品 claim，而不是按精确主体/动作/结果语义绑定。
- `stage30_build_batch.py` 在找不到精确 `sub_action` 时仍保留宽泛候选，导致“滚动”可被误选为“吸水结果”。
- `stage51_verify_alignment.py` 只覆盖样片前若干段并对每镜取单个中点帧，无法证明倒水→吸收或测量→读数这样的时序结果。
- alignment 已识别的关键失败仍可被路由为 `revise`；批量候选只要求 evaluation report 存在，没有要求 evaluation/alignment 真正为 `pass`。
- 当前银离子 research artifact 缺少 browser-captured 商品页 provenance 和完整 `claim_ids/action_keys/allowed_wording`，说明这四条样片尚未真正从 canonical Research 闭环重建。

因此升级不是继续在 `towel_creative.py` 增加文案 override，而是修复主干 artifact 所有权和 fail-closed gate；毛巾脚本只保留兼容入口。

## 4. Canonical Stage Mapping

| Stage | `reference_driven` | `source_led` / `source_led_template` | Canonical hard gate |
|---|---|---|---|
| `research` | 有商品链接则先做浏览器商品页/SKU/主图采集；分析外部参考；建立 reference fingerprint；分析自有素材；生成参考×素材矩阵 | 有商品链接则先做浏览器商品页/SKU/主图采集；跳过外部参考分析；建立 source semantic index、统一 evidence matrix、source grammar fingerprint | 商品页 provenance 与 SKU 唯一；所有自有素材可追溯；外部 reference 与 owned source 路径分离；每条 evidence 有区间、证据帧、confidence、resolution |
| `proposal` | 从参考机制中选保留项并锁定差异方向 | 从素材供给和跨候选相似性中锁定差异方向；模板仅提供节奏骨架 | 至少 3 个方向；每个方向有不同 hook/证据动作/节奏或场景；无付费调用 |
| `script` | 文案受 product facts + evidence 约束，可借鉴参考机制但不借参考文字 | 文案完全由 product facts + source evidence 约束；模板文字仅 `analysis_only` | 每段有 `claim_ids/action_keys/evidence_row_ids`；口播和花字均通过事实检查；人工锁定 |
| `scene_plan` | 自有素材承担最终画面；可记录 `direct_segment` 或 `structural_only` | 仅 `none` 或模板结构先验的 `structural_only`；禁止 reference interval | 每段映射到 approved matrix row 和自有素材半开区间；主体完整性、安全区、裁切策略明确 |
| `assets` | 按 locked plan 生成 TTS/proxy/BGM/captions | 同左；不得用模板台词/花字生成资产 | shot 绑定 source/narration/copy/timing hashes；付费前 lock 完整 |
| `sample` | 验证参考机制是否转译为自有素材 | 验证画面是否支持口播/花字、3:4 构图和候选去重 | final QA + L1a + 语义 alignment + 五项人工效果检查 |
| `edit` | 记录参考适配或内容修改影响 | 记录 source/evidence/script/crop 修改影响 | 修改路由明确；需要时重新打开 Script/Scene Plan/creative lock |
| `compose` | 使用同一 canonical timeline 完整渲染 | 同左 | final QA、alignment hash、L1a、输出 profile 全通过 |
| `publish` | 发布本地交付包 | 同左 | `publish_log` 包含模式、hash、QA、交付尺寸和目录校验 |

## 5. Input-Mode Contract

### 5.1 Project-level metadata

唯一 canonical 落点是项目 marker `projects/<id>/project.json`；`brief.metadata` 只做可读镜像。`init_project()` 在创建 marker 时写入 `input_mode`、`external_reference`、`template_prior` 和 `owned_source_root`，后续 checkpoint/loader 均从 marker 读取，不通过文件名推断。

在项目初始化或 `brief.metadata` 中增加：

```json
{
  "pipeline_type": "cinematic-fast",
  "input_mode": "source_led_template",
  "external_reference": {
    "present": false,
    "paths": [],
    "usage": "not_applicable"
  },
  "template_prior": {
    "present": true,
    "usage": "structural_only",
    "template_pack_ref": "..."
  },
  "product_input": {
    "product_url": "https://detail.tmall.com/item.htm?id=...&skuId=...",
    "browser_acquisition": "required_when_url_present",
    "selected_sku_confirmation": "required"
  },
  "owned_source_root": "inputs/source"
}
```

Validation rules:

- `reference_driven` 必须有至少一个可解析的外部 reference path。
- `source_led` 必须没有外部 reference path。
- `source_led_template` 可以有 `template_pack`，但其 `usage` 必须为 `structural_only`。
- 提供 `product_url` 时，必须生成成功的浏览器采集 artifact；未提供 URL 时才允许走人工录入/上传资料分支。
- 商品 URL 含 `skuId` 时仍需从页面可见选中状态核对 SKU 文本；URL 参数、页面选中项和运营指定 SKU 冲突时停在 Research。
- 所有最终 `source_path` 必须位于项目 owned source set。
- `reference_media_usage` 在无参考模式固定为 `not_applicable` 或 `analysis_only`，不得进入 assets/render。

实现落点：`lib/checkpoint.py:init_project()` 写 marker；`lib/pipeline_loader.py` 提供 `load_input_context(project_dir)`；所有 cinematic-fast stage validation 接收该 context。manifest 的静态 `required_artifacts_in` 不能单独表达模式条件，因此由 loader 解析 `mode_requirements` 扩展：选中模式的 `*_required` **替换**静态数组中的 reference-only 条目，再补充通用必需项；source-led 的 resolved requirements 明确不含 `video_analysis_brief`/`reference_fingerprint`。旧 manifest 无该字段时按 `reference_driven` 兼容。

manifest 目标形状：

```yaml
mode_requirements:
  reference_driven:
    research_required: [video_analysis_brief, reference_fingerprint, reference_source_matrix]
    scene_plan_required: [video_analysis_brief, reference_source_matrix]
  source_led:
    research_required: [source_media_review, media_index, research_breakdown, source_semantic_index, reference_source_matrix]
    scene_plan_required: [source_media_review, reference_source_matrix]
  source_led_template:
    research_required: [source_media_review, media_index, research_breakdown, source_semantic_index, reference_source_matrix, template_pack]
    scene_plan_required: [source_media_review, reference_source_matrix, template_run_plan]
  all_modes:
    proposal_produces: [proposal_packet, creative_control_plan, hook_plan]
  batch_root:
    produces: [differentiation_plan]
```

loader 在上述 mode requirements 之外再应用 `product_url` 条件：URL 存在时向 Research requirements 增加 `product_page_capture`、`product_asset_ledger` 和已确认 `product_facts`；URL 不存在时要求 `product_facts.provenance` 指向人工输入或上传材料，不能伪造 browser capture。

source-led 的 `reference_source_matrix` 仍是 canonical evidence matrix，但其 `matrix_mode` 必须是 `source_led` 或 `source_led_template`；它不代表存在外部参考。`differentiation_plan` 的唯一 owner 是批根 `template_batch`/`candidate_batch` 控制面，不是每个 run 的 Proposal artifact；每个 `template_run_plan` 增加 `differentiation_plan_ref`，run 的 Proposal/Script 通过该 ref 消费批根计划。checkpoint 只在批根控制面持久化一次，run 级只持有 ref。

### 5.2 商品链接的浏览器采集契约

当 `product_input.product_url` 存在时，Research 按以下顺序执行：

```text
product_url
  → 浏览器打开最终落地页并核对 item/SKU
  → 采集可见标题、参数、声明、资质说明、主图/规格图/详情图
  → product_page_capture + product_asset_ledger
  → 运营确认 SKU 与高风险事实
  → product_facts 标准化
  → owned source semantic research
  → evidence matrix 将商品声明与可见动作/结果闭合
```

浏览器采集规则：

- 优先使用页面可见 DOM 和当前选中状态；需要确认构图或图中文字时再读取截图/页面资产。
- 记录最终 canonical URL、`item_id`、URL `skuId`、页面选中 SKU 文本、标题、店铺/品牌、参数、卖点声明、资质/检测入口和采集时间。
- 主图按 `main_gallery`、`selected_sku`、`sku_option`、`detail`、`qualification`、`review` 分类，不能把评论图或推荐商品图混入商品主图。
- 每个页面图片记录原始 URL、页面角色、像素尺寸、内容 hash、落盘路径和衍生链；原图只读保存，裁切/去字/放大版本必须另存并指向 `parent_asset_id`。
- 价格、优惠、库存、发货时效属于易变事实，只能作为“采集时页面状态”；发布前未复核不得写入可复用脚本或模板。
- 登录过期、验证码、安全拦截、页面未完整加载或 SKU 无法唯一识别时，写入 `acquisition_status=awaiting_human` 并停在 Research；不得改用搜索摘要、猜测接口或历史模板静默补全。
- 选中 SKU、至少一张可识别主图和核心参数是硬门；详情长图可标记 partial，但缺口必须进入人工确认卡。

事实与证据等级：

| 来源 | 允许用途 | 不允许自动推导 |
|---|---|---|
| 商品标题/参数/详情页 | 记录“商品页标注”的身份、材质、规格和商家卖点 | 独立检测结论、量化效果、竞品优越性 |
| 商品主图/规格图 | 商品身份、颜色、纹理、包装和构图参考 | 吸水、抗菌、防臭等动态结果 |
| 自有视频连续区间 | 画面中真实可见的主体、动作与结果 | 画面未出现的功效或数值 |
| 合格检测/资质材料 | 在材料范围和有效期内支持对应声明 | 超出样品、SKU、机构结论或有效期的表述 |
| 评论/问大家 | 消费者语言和问题线索，默认 `analysis_only` | 商品事实或普遍效果证明 |

每条标准化 claim 至少包含：

```text
claim_id
statement
claim_class: feature | advantage | benefit | evidence
sku_scope
evidence_status: page_claim | visually_observed | qualified_report | needs_human_confirmation | restricted | forbidden
provenance_refs
required_visual_evidence
allowed_wording
prohibited_wording
risk_level
```

来源优先级为：运营明确确认的目标 SKU > 页面当前选中 SKU > 同一 item 的可见参数/详情 > 人工补充材料。不同 item、不同产品或无法证明同 SKU 的事实禁止合并。

`reference_source_matrix.rows[]` 在 v1 使用条件 schema：

```json
{
  "matrix_mode": "source_led_template",
  "matrix_row_id": "evidence-023",
  "reference_intent": "source-led evidence: visible absorption action",
  "reference_scene_id": null,
  "reference_time_range": null,
  "source_media_id": "towel-023",
  "source_time_range": {"start_seconds": 1.2, "end_seconds_exclusive": 4.8},
  "match_reason": "倒水后水面明显减少，直接支撑可见吸水过程",
  "confidence": 0.92,
  "claim_ids": ["absorb-visible"],
  "action_keys": ["pour_water", "absorb"],
  "allowed_wording": ["可见吸水过程"],
  "evidence_frames": ["analysis/media/towel-023/frame_0001.jpg"],
  "unmatched_gap": null,
  "resolution": "accept"
}
```

`reference_driven` 行仍要求真实 `reference_scene_id/reference_time_range`；source-led 行禁止伪造值，validator 按 `matrix_mode` 选择分支。

### 5.3 Artifact ownership

- 产品级 Research：`product_page_capture`、`product_asset_ledger`、`source_media_review`、`media_index`、`research_breakdown`、`reference_source_matrix`、`research_synthesis`、`research_scorecard`、`source_semantic_index`，位于每个产品的 research root。前两个仅在有商品链接时为必需；无链接时记录明确的人工资料来源。
- 批根级 Proposal：`differentiation_plan`，汇总 4 个产品及其候选片的相似性预算和差异轴。
- Run 级：`template_run_plan`、`script`、`scene_plan`、`shot_execution_plan`、`final_props`、`render_plan`、`evaluation_report`。

四个产品分别完成 source-led Research；批根不复制研究事实，只引用产品级 artifact hashes 并生成跨产品 dedup 计划。这与模板模式“共享模板包、产品素材研究按产品落盘”的边界一致。

### 5.4 Evidence vocabulary

Research 输出的语义单元必须区分观察和推断：

```text
observed_subject      画面实际出现的主体
observed_action       画面实际发生的动作
observed_result       画面可见的结果
allowed_claim         由 product_facts 或画面证据允许的表达
required_action_key   Script/Scene Plan 必须兑现的动作
crop_safety           3:4 裁切后主体和证据是否完整
```

禁止把“素材存在”自动推导成“功效成立”。例如“倒水后水面减少”可以支持“可见吸水过程”，不自动支持“吸水率 99%”。

## 6. Canonical Artifacts

优先扩展现有 artifact，只有在字段会破坏兼容性时才新增文件。

### 6.1 `product_page_capture`（有商品链接时新增且必需）

位置：`projects/<id>/artifacts/product_page_capture.json`。

职责：保存浏览器对商品页的可复现采集结果，不直接充当最终 `product_facts`。建议结构：

```json
{
  "version": "1.0",
  "acquisition_status": "complete",
  "requested_url": "https://detail.tmall.com/item.htm?id=...&skuId=...",
  "canonical_url": "https://detail.tmall.com/item.htm?id=...&skuId=...",
  "captured_at": "2026-09-06T...+08:00",
  "page_identity": {
    "platform": "tmall",
    "item_id": "1060430166297",
    "url_sku_id": "6276962282892",
    "selected_sku_text": "柔胭粉",
    "title": "【银离子抗菌】花花公子纯棉100全棉毛巾吸水防臭不掉毛成人面巾"
  },
  "fact_candidates": [],
  "asset_refs": [],
  "capture_evidence": {
    "dom_snapshot_sha256": "...",
    "screenshots": [],
    "page_state": "authenticated|public|partial"
  },
  "gaps": []
}
```

`page_state` 不保存 cookie、token 或账号信息。页面事实必须带 DOM/截图/图片来源引用，不能只保存模型摘要。

### 6.2 `product_asset_ledger`（有商品链接时新增且必需）

位置：`projects/<id>/artifacts/product_asset_ledger.json`。

职责：管理商品主图和详情资产的来源、分类和衍生关系。每项至少包含：

```text
asset_id
source_page_ref
asset_role: main_gallery | selected_sku | sku_option | detail | qualification | review
usage_role: identity_anchor | composition_reference | information_evidence | analysis_only | forbidden
original_url
local_path
width / height / mime_type / sha256
sku_scope
parent_asset_id / transforms[]
```

页面图片不得直接替代 owned source video 的动作证据。若作为视频内的信息卡或商品锚点使用，Scene Plan 必须显式写入 `page_asset_id` 和使用目的。

### 6.3 `source_semantic_index`（建议新增）

位置：`projects/<id>/artifacts/source_semantic_index.json`。

职责：统一记录每个 owned source 的语义、证据窗口、构图安全性和相似性指纹。建议结构：

```json
{
  "version": "1.0",
  "project_id": "...",
  "input_mode": "source_led_template",
  "entries": [
    {
      "media_id": "towel-023",
      "source_hash": "<sha256>",
      "interval": {"start_seconds": 1.2, "end_seconds_exclusive": 4.8},
      "observed_subject": ["毛巾", "水流", "手部"],
      "observed_actions": ["pour_water", "absorb"],
      "observed_results": ["水面明显减少"],
      "allowed_claim_ids": ["absorb-visible"],
      "crop_safety": {
        "subject_complete_in_3_4": true,
        "safe_caption_regions": ["top", "bottom"]
      },
      "quality": {"usable": true, "confidence": 0.92},
      "representative_frames": ["analysis/media/.../frame_0001.jpg"]
    }
  ]
}
```

### 6.4 Evidence matrix（v1 以 `reference_source_matrix` 为唯一 canonical）

v1 不建立第二套真相。现有 `reference_source_matrix` 扩展为统一 evidence matrix，新增 `matrix_mode: reference|source_led|source_led_template`、`claim_ids`、`action_keys`、`allowed_wording`、`prohibited_wording` 和 `evidence_strength`。`source_evidence_matrix` 只是逻辑视图/适配器名称，不能作为独立 checkpoint artifact；如果未来需要拆文件，必须先完成双读单写迁移。

职责：把商品事实和素材证据绑定成 Script 可消费的 claim contract。

```json
{
  "claim_id": "absorb-visible",
  "product_fact_ref": "product_facts.claims[0]",
  "page_claim_ref": "product_page_capture.fact_candidates[3]",
  "allowed_wording": ["可见吸水过程", "水分快速被带走"],
  "required_action_keys": ["pour_water", "absorb"],
  "evidence_refs": [
    {
      "media_id": "towel-023",
      "interval": {"start_seconds": 1.2, "end_seconds_exclusive": 4.8},
      "strength": "strong",
      "resolution": "accept"
    }
  ],
  "prohibited_wording": ["吸水率99%"]
}
```

### 6.5 `differentiation_plan`（建议新增；批根级）

职责：在 Proposal 前锁定产品级和候选片级差异。

必备维度：

- `candidate_id` / `product_id`
- `hook_pattern`
- `primary_action_keys`
- `beat_order`
- `scene_context`
- `pacing_curve`
- `caption_strategy`
- `audio_strategy`
- `forbidden_repeats`
- `sibling_similarity_budget`
- `matrix_row_refs`

### 6.6 现有 artifact 的字段扩展

`script.sections[]` 增加：

```json
{
  "claim_ids": ["absorb-visible"],
  "action_keys": ["pour_water", "absorb"],
  "evidence_row_ids": ["evidence-023"],
  "product_page_refs": ["product_page_capture.fact_candidates[3]"],
  "visual_intent": "用真实倒水动作证明吸水过程"
}
```

`scene_plan.scenes[]` / `metadata.source_mapping[]` 增加或强制：

```text
script_section_id
claim_ids
action_keys
evidence_row_ids
page_asset_ids
subject_completeness
crop_strategy
caption_safe_zone
```

`shot_execution_plan.shots[]` 绑定：

```text
scene_id
section_id
source_hash
source_interval
narration_hash
screen_copy_hash
tts_asset_hash
tts_measured_duration
caption_timeline_hash
```

`evaluation_report` 增加 `alignment` 区块，并绑定：

```text
script_hash
scene_plan_hash
shot_execution_plan_hash
final_props_hash
render_hash
per_shot_results[]
```

建议的 schema 形状：

```json
{
  "alignment": {
    "scope": "sample",
    "status": "pass|revise|fail",
    "input_hashes": {
      "script": "...",
      "scene_plan": "...",
      "shot_execution_plan": "...",
      "final_props": "...",
      "render": "..."
    },
    "per_shot_results": [
      {
        "scene_id": "scene-003",
        "action_match": "pass",
        "result_support": "pass",
        "narration_caption_match": "pass",
        "crop_completeness": "pass",
        "status": "pass",
        "evidence_refs": ["analysis/alignment/scene-003.jpg"]
      }
    ],
    "repair_targets": []
  }
}
```

`alignment.status=fail` 或 `evaluation_report.status=fail` 直接阻止 sample/compose/publish；`revise` 只能进入 edit/reopen 路由；`pass` 不替代五项人工效果检查。sample 只报告 sample window，final compose 重新写 `scope=final`，并且必须使用新的 render hash。

### 6.7 Reference artifacts 的模式化要求

- `reference_driven`：生成真实 `video_analysis_brief`、`reference_fingerprint` 和 reference/source matrix。
- `source_led`：canonical Research 不产出、也不要求 `video_analysis_brief` 或 `reference_fingerprint`。旧 wrapper 如必须保留兼容文件，只能作为不参与校验和下游读取的 legacy export，并明确 `analysis_mode=source_led`；不能修改现有 reference schema 以伪造参考片。
- `source_led_template`：`template_pack` 进入 provenance；模板 slot 的 dialogue/overlay_text 必须保持 `analysis_only`，不得进入 script/assets。

`research_brief` 在三种模式中仍保留，但职责不同：source-led 模式仍可使用现有 web/行业研究字段（满足当前 schema 的 `landscape/data_points/sources` 要求），这里只是不要求“外部参考视频”。真正的前向事实来自 `source_media_review`、`media_index`、`research_breakdown` 和统一 evidence matrix。`research_scorecard` 的 `input_coverage`、`evidence_traceability` 和 `source_matching` 检查必须按模式重算，不能把“没有参考视频”判为缺失。

## 7. Semantic Alignment Contract

### 7.1 Deterministic hard gate

以下条件必须全部通过：

1. 有 `product_url` 时，`product_page_capture.acquisition_status=complete`，item/SKU 唯一且已确认，核心页面资产具备来源和 hash。
2. `product_facts` 只能由当前 browser capture、运营确认材料和 owned source evidence 标准化生成，且 claim 的 SKU scope 无冲突。
3. section、scene、shot ID 唯一且可解析。
4. 每个 section 至少引用一个已 `accept` 的 evidence row。
5. source interval 在 evidence row 批准区间内，且不越界。
6. source path 属于 owned source set。
7. product identity 与 product facts 一致。
8. TTS、screen copy、captions、timing 的 hash 与当前 script/shot plan 一致。
9. TTS 实测时长驱动字幕和音频时间轴，禁止静默压缩。
10. 无参考模式不存在外部 reference path、伪造 reference interval 或参考花字资产。
11. 3:4 crop、安全区、主体完整性字段齐全。
12. 页面 claim 若要求动态结果，必须同时绑定包含动作前、动作中和结果态的 owned source evidence；仅有商品主图或道具同框不通过。

### 7.2 Semantic review gate

对低清全长 sample 和实际音频运行逐镜审核。单个 midpoint frame 只能做构图辅助，不能承担动作/结果证明；关键 proof shot 至少检查动作前、动作中、结果态三点，必要时直接审核短视频区间：

```text
product_identity_match
action_match
result_support
narration_caption_match
temporal_coverage
crop_completeness
conflict_free
page_claim_scope_match
```

判定：

- 产品身份错误、关键动作完全不出现、口播与花字冲突：`fail`。
- 动作存在但结果未出现、量具读数不支持文案、将道具/隐喻当事实、页面声明超出 SKU scope：`fail`。
- 只有低置信度或可解释的窗口边界问题：`revise`，写入 `repair_targets`；已知的 `action_missing`、`result_unsupported`、`caption_conflict`、`crop_incomplete` 不得降级为可普通批准的 `revise`。
- 只有字体、节奏、包装问题：进入 sample 人审或 edit，不改变 Research 事实。

自动修复最多两轮，顺序固定为：重选 accepted evidence interval → 在 `allowed_wording` 内改写 → 替换/删除镜头。两轮后仍不闭合则回到 Script/Scene Plan 人工处理；禁止靠扩大动作同义词表或直接覆盖 alignment 状态放行。

sample 人工审批只能在 `alignment.status=pass` 后确认审美和业务表达。后端选择资格必须同时要求 `evaluation_report.status=pass` 和 `alignment.status=pass`；“报告存在”不等于通过。

VLM 只判语义，不能替代确定性 hash、时间轴、事实和路径硬门。

无参考模式仍要求现有映射解释字段不为空，但使用固定 provenance：

```json
{
  "reference_evidence": {
    "mode": "none",
    "mechanism": "source-led composition",
    "rationale": "无外部参考；镜头由自有素材证据和候选差异计划决定"
  },
  "reference_basis": "none: owned-source evidence only",
  "originality_note": "无外部参考；模板仅作结构先验"
}
```

`source_fit`、`mapping_reason` 仍需解释“该自有素材为何能证明当前 section”；validator 只放宽 reference interval/scene 的解析，不放宽证据说明字段。

## 8. Deduplication Strategy

### Research

为每条素材建立内容 hash、动作域、构图、主体位置、场景/光线、代表帧 embedding 和适合承担的叙事角色，形成“同动作不同素材”的簇。

### Proposal

每个候选至少锁定两个不同轴：

- hook pattern
- primary evidence action
- beat order
- scene context
- pacing curve
- caption/audio treatment

只更换模板标题、颜色或字体不算差异化。

### Scene Plan

- 同一候选内：`media_id + in_point` 不重复。
- 跨候选复用素材时，必须改变时间窗口、镜头角色、裁切/运动或前后 beat 关系中的至少一项。
- 稀缺动作域复用时记录 `reuse_reason`，不能静默重复。

### Sample / batch review

比较片头 3 秒结构、shot/action 序列、口播 n-gram、字幕节奏和转场序列。超过批根阈值的候选退回 Proposal 或 Script，不等到最终 compose 后补救。

v1 使用可复现的纯 Python baseline：

```python
compare_candidates(a: CandidateSignature, b: CandidateSignature) -> SimilarityResult
```

- `action_jaccard = len(set(a.action_keys) & set(b.action_keys)) / len(set(a.action_keys) | set(b.action_keys))`；空集合按 `0.0` 处理。
- 文本先做 Unicode NFKC、中文/英文小写、去标点和连续空白归一化，再按中文单字 + 英文/数字 token 生成 2-gram；`copy_ngram_similarity` 使用 Dice 系数 `2*|A∩B|/(|A|+|B|)`。
- `beat_duration_delta = sum(abs(ai-bi) for ai,bi in zip_longest(a.normalized_beats, b.normalized_beats, fillvalue=0)) / max(sum(a.normalized_beats), sum(b.normalized_beats), 1)`，其中每条 beat 时长先除以候选总时长。
- 同一 `product_id` 的候选两两比较；跨产品只比较片头 hook 和主证据动作，用于发现批次级重复。
- `action_jaccard >= 0.80` 且 `copy_ngram_similarity >= 0.85` 且 `beat_duration_delta <= 0.15` 时标记 `high_similarity`；任意两个主差异轴相同则标记 `needs_redesign`。

固定 fixture：A/B 共享 4/5 动作、复制 90% 字幕 n-gram、归一化 beat 差 0.08，期望 `high_similarity`；A/C 共享 1/5 动作、文本 Dice 0.20、beat 差 0.32，期望 `distinct`。输出写入 `differentiation_plan.sibling_comparisons[]` 和 `batch_quality_report.dedup`。embedding/VLM 只作为后续 advisory，不改变 v1 的确定性 gate。

`batch_quality_report.dedup` 最小结构：

```json
{
  "thresholds": {"action_jaccard": 0.8, "copy_ngram_dice": 0.85, "beat_duration_delta": 0.15},
  "comparisons": [
    {"candidate_a": "yinlizi-01", "candidate_b": "yinlizi-02", "action_jaccard": 0.8,
     "copy_ngram_dice": 0.9, "beat_duration_delta": 0.08, "status": "high_similarity"}
  ],
  "status": "pass|needs_redesign"
}
```

## 9. Template Separation Rules

在 `source_led_template` 模式中，`template_pack/template_run_plan` 只负责：

- slot 时长和节奏拍点
- shot size、camera movement、camera angle
- caption treatment 的表现提示
- audio layer 和 music profile
- 结构性 transition/caption intent fallback

不得负责：

- 商品事实
- 最终 narration
- 最终 screen_copy
- source evidence 选择
- 参考视频关系

正确顺序：

```text
Research 先判断素材能证明什么
→ Proposal 选择差异化叙事
→ Script 写被证据允许的口播/花字
→ Scene Plan 选择证明该文案的素材窗口
→ template_run_plan 只提供节奏和镜头语法
```

## 10. Code Change Map

### Pipeline and skills

- Modify: `pipeline_defs/cinematic-fast.yaml`
  - 增加 `input_mode` 语义说明、source-led Research outputs 和 mode-specific success criteria；把 reference artifacts 的 required/optional 关系改成按模式解析。
- Modify: `schemas/pipelines/pipeline_manifest.schema.json`
  - 注册 `mode_requirements`，定义 `research_required`/`scene_plan_required` 数组及其与静态 `required_artifacts_in` 的合并优先级。
- Modify: `lib/pipeline_loader.py`
  - 解析 manifest 的 mode-aware artifact requirements，并向 checkpoint/阶段 director 提供统一上下文。
- Modify: `lib/checkpoint.py`
  - 按 `project.json.input_mode` 选择 Research handoff；source-led 不读取 reference duration，改读统一 evidence matrix；注册新 artifact 并保证 stage/checkpoint 恢复；批根 differentiation 只持久化一次。
- Modify: `skills/pipelines/cinematic-fast/research-director.md`
  - 增加三种模式的分支、无参考时禁止伪造 reference artifacts、source semantic/evidence 产物要求；有商品 URL 时先按浏览器可见页面采集 item/SKU/参数/主图，受阻则返回 `awaiting_human`。
- Modify: `skills/pipelines/cinematic-fast/proposal-director.md`
  - 从统一 evidence matrix 和 `differentiation_plan` 选择方向；模板只作为结构先验。
- Modify: `skills/pipelines/cinematic-fast/script-director.md`
  - 强制 section-level `claim_ids/action_keys/evidence_row_ids`，并说明无参考模式的文案来源。
- Modify: `skills/pipelines/cinematic-fast/scene-director.md`
  - 强制 evidence row 内的 source interval；按 input mode 限制 `reference_evidence.mode`。
- Modify: `skills/pipelines/cinematic-fast/asset-director.md`
  - 将 source/narration/copy/timing hash 纳入 shot execution lock。
- Modify: `skills/pipelines/cinematic-fast/sample-director.md`
  - 将语义 alignment 和 batch dedup 作为正式 sample 产物与 gate。
- Modify: `skills/pipelines/cinematic-fast/publish-director.md`
  - 交付清单记录 input mode、alignment/evaluation hashes 和输出 profile。

### Libraries and schemas

- Create: `lib/product_fact_reconciliation.py` — 将 browser capture、运营确认和 owned source observation 标准化为 SKU-scoped `product_facts`；不负责浏览器抓取。
- Create: `schemas/artifacts/product_page_capture.schema.json`。
- Create: `schemas/artifacts/product_asset_ledger.schema.json`。
- Create: `lib/source_semantics.py` — source semantic index/evidence row helpers。
- Create: `lib/differentiation.py` — candidate-level and batch-level dedup scoring/thresholds。
- Promote/refactor: `lib/template_alignment.py` — 改名或扩展为通用 alignment library，保留兼容导入。
- Modify: `lib/cinematic_fast_validation.py` — input mode、evidence row、reference mode 和 crop completeness validation。
- Modify: `lib/template_assets.py` / `lib/template_render.py` — 消费 canonical hashes，不重新解释语义。
- Create: `schemas/artifacts/source_semantic_index.schema.json`。
- Modify: `schemas/artifacts/reference_source_matrix.schema.json` — 扩展为三模式统一 evidence matrix；不新增第二套 matrix schema。
- Modify: `schemas/artifacts/__init__.py` — 注册 `product_page_capture`、`product_asset_ledger`、`source_semantic_index` 与 `differentiation_plan`。
- Modify: `lib/research_validation.py` — 按 `matrix_mode` 校验 source-only rows 和 proposal handoff。
- Modify: `lib/checkpoint.py` — 将新增 artifact 纳入 `SUPPLEMENTARY_ARTIFACTS`/`FASTLINE_ARTIFACTS` 和 stage artifact maps；确保 transaction stage、unwrap、恢复和 Backlot 可见；URL 采集受阻时生成可恢复的 `awaiting_human` checkpoint。
- Modify: `schemas/artifacts/template_batch.schema.json`、`schemas/artifacts/candidate_batch.schema.json`、`schemas/artifacts/template_run_plan.schema.json` — 批根持有 `differentiation_plan`，run 只持有 `differentiation_plan_ref`。
- Create: `schemas/artifacts/differentiation_plan.schema.json`。
- Modify: `schemas/artifacts/script.schema.json`、`scene_plan.schema.json`、`shot_execution_plan.schema.json`、`evaluation_report.schema.json`。

### Operator workbench

- Modify: `backlot/operator_state.py` / `backlot/batch_state.py`
  - 投影商品页采集状态、目标 SKU、claim provenance、页面主图和逐镜 action/result；候选选择要求 evaluation 与 alignment 都为 `pass`。
- Modify: `backlot/ui/operator/app.js`
  - 增加商品事实卡和逐镜证据卡：左侧页面 claim/主图，中间自有素材动作与结果，右侧口播/花字和 gate 结论。
- Modify: Research editor projection
  - 运营可确认/拒绝事实、SKU 和页面资产用途；确认绑定 artifact hash，SKU 或页面重新采集后自动失效。

### Batch migration wrappers

- Modify: `scripts/towel_batch_2026_09_02/stage25_research_artifacts.py`
  - 只调用 canonical source research builder；保留批次目录兼容输出。
- Modify: `scripts/towel_batch_2026_09_02/stage30_build_batch.py`
  - 只调用 canonical differentiation/template run builder。
- Modify: `scripts/towel_batch_2026_09_02/stage40_scene_assets.py`
  - 只消费 approved script/scene plan/evidence rows，不自行选择语义。
- Modify: `scripts/towel_batch_2026_09_02/stage50_sample.py`
  - 只调用 canonical sample materialization/render/alignment。
- Modify: `scripts/towel_batch_2026_09_02/stage51_verify_alignment.py`
  - 变为通用 alignment CLI 的兼容入口，不能生成独立事实或时间轴。

## 11. Migration and Rollout

### Phase 0 — Contract freeze

- 明确 `source_led_template` 为本次毛巾批次模式。
- 为现有研究根项目补齐 `input_mode`、template provenance 和 source ownership 元数据。
- 将当前最小修复的 hash/ID 逻辑视为过渡实现，停止新增旁路字段。

### Phase 1 — Source-led Research

- 商品 URL 存在时，先由浏览器生成 `product_page_capture` 和 `product_asset_ledger`，运营确认当前 SKU、高风险 claim 和可用主图。
- 由 reconciliation 生成 SKU-scoped `product_facts`；页面声明、自有画面观察和检测材料保持不同 evidence status。
- 生成 `source_semantic_index`，并扩展 `reference_source_matrix` 作为统一 evidence matrix。
- 将 `research_breakdown` / `research_synthesis` 的模板兼容数据标记为 source-led，移除“伪参考”语义。
- 生成批根 `differentiation_plan`，覆盖 4 产品 × 4 候选。
- 通过 Research scorecard 后才进入 Proposal/Script。

### Phase 2 — Script/Scene contract

- 为每个 section 写入 claim/action/evidence IDs。
- Scene Plan 只能在批准证据区间内选择素材。
- Script 人审需同时确认文案事实和画面证明要求。

### Phase 3 — Canonical assets/sample

- 将 TTS、字幕、proxy、BGM 和 render payload 全部从 canonical plan 物化。
- 付费 TTS 前先运行浏览器事实/SKU gate 和逐镜 evidence preflight。
- sample 必须为覆盖全部镜头的低清全长版，输出 `alignment` 和 `sample_execution_trace`，通过 3:4 主体完整性、L1a、时序语义对齐和五项效果检查。
- 先用一个产品的一条候选做 pilot，再扩展同产品其余三条，最后扩展另外三个产品。

### Phase 4 — Remove semantic bypass

- 保留 `stage25/30/40/50/51` 作为兼容 CLI，但内部只调用主干 builder。
- 当 canonical tests 和 pilot 验收完成后，禁止批次脚本直接重建 narration/source mapping/render payload。

## 12. Test Plan

### Contract tests

- `tests/contracts/test_product_page_acquisition.py`
  - URL 存在时 browser capture/asset ledger 必需；无 URL 时只允许人工 provenance。
  - item/SKU 冲突、采集受阻和核心主图缺失均停在 Research。
  - 页面 claim 不能自动升级为 qualified report 或 owned-video result evidence。
- `tests/contracts/test_cinematic_fast_input_modes.py`
  - 三种模式的合法/非法输入。
  - 无参考模式禁止 `direct_segment` 和外部 source path。
  - 模板文字不能进入 script/assets。
- `tests/contracts/test_source_evidence_contract.py`
  - claim/action/evidence 必须闭合。
  - source interval 必须落在 accepted evidence interval 内。

### Unit tests

- `tests/lib/test_product_fact_reconciliation.py`
  - SKU scope、事实来源优先级、易变价格和 capture hash 失效。
- `tests/lib/test_source_semantics.py`
  - source hash、动作域、crop safety 和 evidence row 构建。
- `tests/lib/test_differentiation.py`
  - hook/action/beat/口播相似性计算和阈值。
- 扩展现有 `tests/lib/test_template_alignment.py`
  - hash 绑定、mode-specific reference gate、语义结果 fail-closed。

### Integration tests

- 浏览器采集成功 fixture：商品页 → SKU/主图/参数 → 事实确认 → source research → script preflight。
- 浏览器登录/验证码受阻 fixture：Research 返回 `awaiting_human`，不产生猜测事实，不调用付费 TTS。
- SKU 变化 fixture：旧 product facts、script approval、page asset selection 和下游 hashes 全部失效。
- source-led 无参考 fixture：research → proposal → script → scene_plan → assets → sample preflight。
- source-led-template fixture：template pack 只贡献节奏，最终 narration/screen_copy 来自 product facts/evidence。
- reference-driven fixture：保留 direct reference mapping，但最终 source path 仍是 owned source。
- 旧毛巾 wrapper 回归：输出 artifact hashes 与 canonical builder 一致。
- 银离子 golden cases：连续倒水不得匹配“水滴一沾上”；滚筒经过不得匹配“吸得干爽”；棉花道具不得证明毛巾柔软；`0.00 N` 画面不得匹配“称出来有分量”。

### Visual acceptance

- 每个候选抽查片头、核心 proof、CTA 三个窗口。
- 先审覆盖全部镜头的低清全长样片，不再只审前五段或 12 秒截取。
- 重点检查 3:4 裁切后主体和动作结果是否完整。
- 逐镜记录“口播说什么 / 花字写什么 / 画面证明什么”。
- 批量比较片头 3 秒、动作序列、口播结构和字幕节奏，发现重复时退回 Proposal/Script。

## 13. Acceptance Criteria

设计实施完成后，以下条件必须满足：

- `cinematic-fast` 能根据显式 `input_mode` 正确选择 Research 行为。
- 有商品链接时，浏览器采集的 item、选中 SKU、事实候选和主图均可追溯；受阻时停在 Research，不静默降级。
- `product_facts` 能区分页面声明、画面观察和合格报告，且所有 claim 均限定到目标 SKU。
- 无外部参考的任务不会生成伪造的 reference scene/interval，也不会把模板文案带入最终资产。
- 每个 Script section 都有可解析的 `claim_ids/action_keys/evidence_row_ids`。
- 每个 Scene Plan shot 都绑定 owned source interval、证据行、裁切策略和 3:4 主体完整性。
- TTS、字幕、画面和 render timeline 均由同一 canonical plan/hash 生成。
- Sample 覆盖完整时间线；alignment report 同时通过确定性硬门和时序语义审核；旧报告不能污染新样片，已知 fail 不能被人工普通批准覆盖。
- 同片不重复 `media_id + in_point`，跨候选有明确差异轴和相似性预算。
- final QA、L1a、alignment、人工 sample review 全部通过后才允许 compose/publish。
- 毛巾批次脚本不再自行重建语义关系，只作为 canonical 主干的兼容入口。
- 未通过商品页事实/SKU gate、Script 人审和逐镜 evidence preflight 时，不产生付费 TTS。

## 14. Implementation Tasks

### Task 1: Freeze the mode contract

**Files:**
- Modify: `pipeline_defs/cinematic-fast.yaml`
- Modify: `lib/pipeline_loader.py`
- Modify: `schemas/pipelines/pipeline_manifest.schema.json`
- Modify: `lib/checkpoint.py`
- Modify: `schemas/checkpoints/checkpoint.schema.json`
- Modify: `schemas/artifacts/research_brief.schema.json`
- Create: `tests/contracts/test_cinematic_fast_input_modes.py`

- [ ] 写三种 `input_mode` 的 schema/manifest contract test。
- [ ] 在 `init_project()` 写入 `project.json.input_mode`，并实现 `load_input_context(project_dir)`。
- [ ] 实现 manifest mode requirements 和 checkpoint mode-aware gating；source-led 不读取 reference duration。
- [ ] 将 `video_analyzer` 在 source-led/source_led_template 中改为可选或跳过；`scene_plan` validator 不再无条件读取 `video_analysis_brief.source.duration_seconds`。
- [ ] 验证无参考模式拒绝外部 reference mapping，旧项目无 `input_mode` 时按 `reference_driven` 兼容。
- [ ] 运行 `pytest tests/contracts/test_cinematic_fast_input_modes.py -v`。

### Task 1A: Browser product acquisition and fact reconciliation

**Files:**
- Modify: `skills/pipelines/cinematic-fast/research-director.md`
- Create: `lib/product_fact_reconciliation.py`
- Create: `schemas/artifacts/product_page_capture.schema.json`
- Create: `schemas/artifacts/product_asset_ledger.schema.json`
- Modify: `schemas/artifacts/product_facts.schema.json`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `lib/checkpoint.py`
- Modify: `backlot/operator_state.py`
- Modify: `backlot/ui/operator/app.js`
- Create: `tests/contracts/test_product_page_acquisition.py`
- Create: `tests/lib/test_product_fact_reconciliation.py`

- [ ] 先写 URL 存在/不存在、页面受阻、SKU 冲突和 SKU 变化的失败测试。
- [ ] 在 Research director 中规定浏览器可见页面采集，不实现独立 Python 爬虫，也不绕过登录/验证码。
- [ ] 写 `product_page_capture` / `product_asset_ledger`，固化 page/SKU/主图 provenance 和 hash。
- [ ] 实现 page claim、visual observation、qualified report 的事实调和及 `allowed_wording`。
- [ ] 在工作台增加 SKU、事实和主图人工确认；确认绑定 capture hash。
- [ ] 验证 gate 未通过时停在 `research: awaiting_human`，并且 paid TTS 调用次数为 0。

### Task 2: Canonical source research artifacts

完成 Task 1A 后再执行以下 source semantics 工作。

**Files:**
- Create: `lib/source_semantics.py`
- Create: `schemas/artifacts/source_semantic_index.schema.json`
- Modify: `schemas/artifacts/reference_source_matrix.schema.json`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `lib/checkpoint.py`
- Create: `tests/lib/test_source_semantics.py`
- Modify: `skills/pipelines/cinematic-fast/research-director.md`

- [ ] 先写 source-led fixture 的失败测试。
- [ ] 实现 source semantic index builder，并把 evidence rows 写入 canonical `reference_source_matrix`。
- [ ] 将 product facts、观察结果、动作域和 crop safety 绑定。
- [ ] 运行对应单测和 artifact schema tests。

### Task 3: Candidate differentiation

**Files:**
- Create: `lib/differentiation.py`
- Create: `schemas/artifacts/differentiation_plan.schema.json`
- Modify: `schemas/artifacts/batch_quality_report.schema.json`
- Modify: `schemas/artifacts/template_batch.schema.json`
- Modify: `schemas/artifacts/candidate_batch.schema.json`
- Modify: `schemas/artifacts/template_run_plan.schema.json`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `lib/checkpoint.py`
- Modify: `lib/template_batch.py` / `lib/candidate_batch.py`
- Create: `tests/lib/test_differentiation.py`
- Modify: `skills/pipelines/cinematic-fast/proposal-director.md`

- [ ] 写确定性 baseline 测试：动作序列 Jaccard、字符/词 n-gram 相似度、beat 时长差；默认告警阈值分别为 `0.80`、`0.85`、`0.15`。
- [ ] 实现纯 Python 产品级/候选级去重计划生成；embedding/VLM 仅作为后续 advisory，不阻塞 v1。
- [ ] 将 `sibling_comparisons[]` 写入 `differentiation_plan`，并将批次汇总写入 `batch_quality_report.dedup`。
- [ ] 由 `template_batch`/`candidate_batch` 持有唯一 `differentiation_plan_ref`；每个 `template_run_plan` 写入同一 ref，run Proposal/Script 只读该引用。
- [ ] 将差异计划引用写入 `proposal_packet`/`creative_control_plan`。
- [ ] 验证 proposal 不触发 paid tools。

### Task 4: Script and Scene evidence closure

**Files:**
- Modify: `schemas/artifacts/script.schema.json`
- Modify: `schemas/artifacts/scene_plan.schema.json`
- Modify: `lib/cinematic_fast_validation.py`
- Modify: `skills/pipelines/cinematic-fast/script-director.md`
- Modify: `skills/pipelines/cinematic-fast/scene-director.md`
- Create: `tests/contracts/test_source_evidence_contract.py`

- [ ] 为 section/scene 增加 claim/action/evidence 字段。
- [ ] 实现 evidence row、source interval、mode-specific reference gate。
- [ ] 验证脚本事实、花字和画面证据闭合。
- [ ] 运行 contract tests 和现有 cinematic-fast validation tests。

### Task 5: Canonical sample alignment

**Files:**
- Modify: `lib/template_alignment.py`
- Modify: `lib/sample_execution_trace.py`
- Modify: `schemas/artifacts/evaluation_report.schema.json`
- Modify: `skills/pipelines/cinematic-fast/sample-director.md`
- Create: `tests/integration/test_source_led_sample_alignment.py`

- [ ] 将确定性 hash gate 和语义 alignment 统一到主干 sample。
- [ ] 将 alignment 输入 hashes 写入 `evaluation_report`。
- [ ] 对关键动作缺失、结果不成立、产品身份错误、量具读数冲突和 caption conflict 实现 fail-closed。
- [ ] 用动作前/中/结果态或短区间审核替换单一 midpoint frame；sample 覆盖完整时间线。
- [ ] 修改候选选择资格：`evaluation_report.status` 与 `alignment.status` 必须同时为 `pass`，人工审批不能覆盖 known fail。
- [ ] 运行 sample integration test。

### Task 6: Migrate towel wrappers

**Files:**
- Modify: `scripts/towel_batch_2026_09_02/stage25_research_artifacts.py`
- Modify: `scripts/towel_batch_2026_09_02/stage30_build_batch.py`
- Modify: `scripts/towel_batch_2026_09_02/stage40_scene_assets.py`
- Modify: `scripts/towel_batch_2026_09_02/stage50_sample.py`
- Modify: `scripts/towel_batch_2026_09_02/stage51_verify_alignment.py`
- Create: `tests/integration/test_towel_wrapper_uses_canonical_path.py`

- [ ] 将 wrapper 的语义选择、TTS、render payload 和 alignment 逻辑替换为 canonical 调用。
- [ ] 保留旧 CLI 参数和输出路径，避免破坏已有样片目录。
- [ ] 验证 wrapper 产物 hash 与 canonical builder 一致。
- [ ] 运行毛巾批次回归测试；不在本任务中重新渲染 16 条主片。

### Task 7: Documentation and rollout gate

**Files:**
- Modify: `docs/EVALUATION_SYSTEM.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `skills/pipelines/cinematic-fast/executive-producer.md`

- [ ] 将输入模式、evidence contract、dedup gate 和迁移状态写入架构/评价文档。
- [ ] 增加 pilot → batch 的推进条件。
- [ ] 运行完整相关测试、`git diff --check` 和 schema validation。

## 15. Open Decisions Before Implementation

以下不阻塞本设计成立，但在 Task 1 开始前需要确认默认值：

1. `source_semantic_index` 与 `research_breakdown` 是并存一版，还是先扩展后者再迁移。
2. VLM 语义 alignment 是否作为 sample 必选门，还是首版只对关键 proof shot 启用。
3. 是否在首版将 `differentiation_plan` 直接汇总到既有 `batch_quality_report`，还是先只保留批根计划。
4. 商品详情长图首版是否全部下载，还是仅登记 URL 并下载被选为事实/构图证据的 Top-K；默认建议 Top-K 落盘、其余只登记，避免 Research 体积失控。

本设计已锁定的默认值：统一 evidence matrix 由 `reference_source_matrix` 承载；source-led canonical Research 不产出或读取 reference artifacts；商品链接使用浏览器可见页面采集，不新增独立爬虫旁路；商品页声明不自动升级为独立证明；相似度采用“动作序列 + 文本 n-gram + 时间结构”的纯 Python baseline；四个产品各自完成产品级 Research，批根只汇总去重。

# Cinematic Fast Input Modes and Source-Led Semantic Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `cinematic-fast` 统一为一条主干，同时明确区分“有外部参考视频”和“仅自有素材（可选内部模板先验）”两种输入模式，并把画面—口播—花字匹配、素材理解和成片去重固化到 Research → Script → Scene Plan → Sample 契约中。

**Architecture:** 保留 `cinematic-fast` 的阶段和 checkpoint，不新增毛巾专用 production path。新增显式 `input_mode` 与 evidence contract：Research 负责判断自有素材能证明什么，Script 只能使用被 Research 接受的 claim/action，Scene Plan 必须把 section 映射到自有素材证据区间，Assets 和 Sample 通过 hash、ID 和渲染后语义检查阻止漂移。外部参考只影响 `reference_driven` 模式；模板包在 `source_led_template` 模式中只能作为结构先验，不能成为商品文案或事实来源。

**Tech Stack:** Python tools and artifact builders, YAML pipeline manifests, JSON Schema, `lib.checkpoint`, `lib.artifact_io`, existing `cinematic-fast` directors, `template_pack/template_run_plan`, Remotion/HyperFrames composition, `final_qa`, `technical_validator`, `video_judge`, pytest.

---

## 1. Decision Summary

本次毛巾任务的正式归类：

```yaml
pipeline: cinematic-fast
input_mode: source_led_template
external_reference: false
template_prior: structural_only
source_of_truth: owned_source_media + product_facts
dedup_scope: product + candidate_batch
```

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

## 4. Canonical Stage Mapping

| Stage | `reference_driven` | `source_led` / `source_led_template` | Canonical hard gate |
|---|---|---|---|
| `research` | 分析外部参考；建立 reference fingerprint；分析自有素材；生成参考×素材矩阵 | 跳过外部参考分析；建立 source semantic index、统一 evidence matrix、source grammar fingerprint | 所有自有素材可追溯；外部 reference 与 owned source 路径分离；每条 evidence 有区间、证据帧、confidence、resolution |
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
  "owned_source_root": "inputs/source"
}
```

Validation rules:

- `reference_driven` 必须有至少一个可解析的外部 reference path。
- `source_led` 必须没有外部 reference path。
- `source_led_template` 可以有 `template_pack`，但其 `usage` 必须为 `structural_only`。
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

source-led 的 `reference_source_matrix` 仍是 canonical evidence matrix，但其 `matrix_mode` 必须是 `source_led` 或 `source_led_template`；它不代表存在外部参考。`differentiation_plan` 的唯一 owner 是批根 `template_batch`/`candidate_batch` 控制面，不是每个 run 的 Proposal artifact；每个 `template_run_plan` 增加 `differentiation_plan_ref`，run 的 Proposal/Script 通过该 ref 消费批根计划。checkpoint 只在批根控制面持久化一次，run 级只持有 ref。

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

- 产品级 Research：`source_media_review`、`media_index`、`research_breakdown`、`reference_source_matrix`、`research_synthesis`、`research_scorecard`、`source_semantic_index`，位于每个产品的 research root。
- 批根级 Proposal：`differentiation_plan`，汇总 4 个产品及其候选片的相似性预算和差异轴。
- Run 级：`template_run_plan`、`script`、`scene_plan`、`shot_execution_plan`、`final_props`、`render_plan`、`evaluation_report`。

四个产品分别完成 source-led Research；批根不复制研究事实，只引用产品级 artifact hashes 并生成跨产品 dedup 计划。这与模板模式“共享模板包、产品素材研究按产品落盘”的边界一致。

### 5.2 Evidence vocabulary

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

### 6.1 `source_semantic_index`（建议新增）

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

### 6.2 Evidence matrix（v1 以 `reference_source_matrix` 为唯一 canonical）

v1 不建立第二套真相。现有 `reference_source_matrix` 扩展为统一 evidence matrix，新增 `matrix_mode: reference|source_led|source_led_template`、`claim_ids`、`action_keys`、`allowed_wording`、`prohibited_wording` 和 `evidence_strength`。`source_evidence_matrix` 只是逻辑视图/适配器名称，不能作为独立 checkpoint artifact；如果未来需要拆文件，必须先完成双读单写迁移。

职责：把商品事实和素材证据绑定成 Script 可消费的 claim contract。

```json
{
  "claim_id": "absorb-visible",
  "product_fact_ref": "product_facts.claims[0]",
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

### 6.3 `differentiation_plan`（建议新增；批根级）

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

### 6.4 现有 artifact 的字段扩展

`script.sections[]` 增加：

```json
{
  "claim_ids": ["absorb-visible"],
  "action_keys": ["pour_water", "absorb"],
  "evidence_row_ids": ["evidence-023"],
  "visual_intent": "用真实倒水动作证明吸水过程"
}
```

`scene_plan.scenes[]` / `metadata.source_mapping[]` 增加或强制：

```text
script_section_id
claim_ids
action_keys
evidence_row_ids
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

### 6.5 Reference artifacts 的模式化要求

- `reference_driven`：生成真实 `video_analysis_brief`、`reference_fingerprint` 和 reference/source matrix。
- `source_led`：canonical Research 不产出、也不要求 `video_analysis_brief` 或 `reference_fingerprint`。旧 wrapper 如必须保留兼容文件，只能作为不参与校验和下游读取的 legacy export，并明确 `analysis_mode=source_led`；不能修改现有 reference schema 以伪造参考片。
- `source_led_template`：`template_pack` 进入 provenance；模板 slot 的 dialogue/overlay_text 必须保持 `analysis_only`，不得进入 script/assets。

`research_brief` 在三种模式中仍保留，但职责不同：source-led 模式仍可使用现有 web/行业研究字段（满足当前 schema 的 `landscape/data_points/sources` 要求），这里只是不要求“外部参考视频”。真正的前向事实来自 `source_media_review`、`media_index`、`research_breakdown` 和统一 evidence matrix。`research_scorecard` 的 `input_coverage`、`evidence_traceability` 和 `source_matching` 检查必须按模式重算，不能把“没有参考视频”判为缺失。

## 7. Semantic Alignment Contract

### 7.1 Deterministic hard gate

以下条件必须全部通过：

1. section、scene、shot ID 唯一且可解析。
2. 每个 section 至少引用一个已 `accept` 的 evidence row。
3. source interval 在 evidence row 批准区间内，且不越界。
4. source path 属于 owned source set。
5. product identity 与 product facts 一致。
6. TTS、screen copy、captions、timing 的 hash 与当前 script/shot plan 一致。
7. TTS 实测时长驱动字幕和音频时间轴，禁止静默压缩。
8. 无参考模式不存在外部 reference path、伪造 reference interval 或参考花字资产。
9. 3:4 crop、安全区、主体完整性字段齐全。

### 7.2 Semantic review gate

对 sample 抽帧和实际音频运行逐镜审核：

```text
product_identity_match
action_match
result_support
narration_caption_match
temporal_coverage
crop_completeness
conflict_free
```

判定：

- 产品身份错误、关键动作完全不出现、口播与花字冲突：`fail`。
- 证据弱但可通过改窗口、改文案或改镜头修复：`revise`，写入 `repair_targets`。
- 只有字体、节奏、包装问题：进入 sample 人审或 edit，不改变 Research 事实。

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
  - 增加三种模式的分支、无参考时禁止伪造 reference artifacts、source semantic/evidence 产物要求。
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

- Create: `lib/source_semantics.py` — source semantic index/evidence row helpers。
- Create: `lib/differentiation.py` — candidate-level and batch-level dedup scoring/thresholds。
- Promote/refactor: `lib/template_alignment.py` — 改名或扩展为通用 alignment library，保留兼容导入。
- Modify: `lib/cinematic_fast_validation.py` — input mode、evidence row、reference mode 和 crop completeness validation。
- Modify: `lib/template_assets.py` / `lib/template_render.py` — 消费 canonical hashes，不重新解释语义。
- Create: `schemas/artifacts/source_semantic_index.schema.json`。
- Modify: `schemas/artifacts/reference_source_matrix.schema.json` — 扩展为三模式统一 evidence matrix；不新增第二套 matrix schema。
- Modify: `schemas/artifacts/__init__.py` — 注册 `source_semantic_index` 与 `differentiation_plan`。
- Modify: `lib/research_validation.py` — 按 `matrix_mode` 校验 source-only rows 和 proposal handoff。
- Modify: `lib/checkpoint.py` — 将两个 artifact 纳入 `SUPPLEMENTARY_ARTIFACTS`/`FASTLINE_ARTIFACTS` 和 stage artifact maps；确保 transaction stage、unwrap、恢复和 Backlot 可见。
- Modify: `schemas/artifacts/template_batch.schema.json`、`schemas/artifacts/candidate_batch.schema.json`、`schemas/artifacts/template_run_plan.schema.json` — 批根持有 `differentiation_plan`，run 只持有 `differentiation_plan_ref`。
- Create: `schemas/artifacts/differentiation_plan.schema.json`。
- Modify: `schemas/artifacts/script.schema.json`、`scene_plan.schema.json`、`shot_execution_plan.schema.json`、`evaluation_report.schema.json`。

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
- sample 输出 `alignment` 和 `sample_execution_trace`，通过 3:4 主体完整性、L1a、语义对齐和五项效果检查。
- 先用一个产品的一条候选做 pilot，再扩展同产品其余三条，最后扩展另外三个产品。

### Phase 4 — Remove semantic bypass

- 保留 `stage25/30/40/50/51` 作为兼容 CLI，但内部只调用主干 builder。
- 当 canonical tests 和 pilot 验收完成后，禁止批次脚本直接重建 narration/source mapping/render payload。

## 12. Test Plan

### Contract tests

- `tests/contracts/test_cinematic_fast_input_modes.py`
  - 三种模式的合法/非法输入。
  - 无参考模式禁止 `direct_segment` 和外部 source path。
  - 模板文字不能进入 script/assets。
- `tests/contracts/test_source_evidence_contract.py`
  - claim/action/evidence 必须闭合。
  - source interval 必须落在 accepted evidence interval 内。

### Unit tests

- `tests/lib/test_source_semantics.py`
  - source hash、动作域、crop safety 和 evidence row 构建。
- `tests/lib/test_differentiation.py`
  - hook/action/beat/口播相似性计算和阈值。
- 扩展现有 `tests/lib/test_template_alignment.py`
  - hash 绑定、mode-specific reference gate、语义结果 fail-closed。

### Integration tests

- source-led 无参考 fixture：research → proposal → script → scene_plan → assets → sample preflight。
- source-led-template fixture：template pack 只贡献节奏，最终 narration/screen_copy 来自 product facts/evidence。
- reference-driven fixture：保留 direct reference mapping，但最终 source path 仍是 owned source。
- 旧毛巾 wrapper 回归：输出 artifact hashes 与 canonical builder 一致。

### Visual acceptance

- 每个候选抽查片头、核心 proof、CTA 三个窗口。
- 重点检查 3:4 裁切后主体和动作结果是否完整。
- 逐镜记录“口播说什么 / 花字写什么 / 画面证明什么”。
- 批量比较片头 3 秒、动作序列、口播结构和字幕节奏，发现重复时退回 Proposal/Script。

## 13. Acceptance Criteria

设计实施完成后，以下条件必须满足：

- `cinematic-fast` 能根据显式 `input_mode` 正确选择 Research 行为。
- 无外部参考的任务不会生成伪造的 reference scene/interval，也不会把模板文案带入最终资产。
- 每个 Script section 都有可解析的 `claim_ids/action_keys/evidence_row_ids`。
- 每个 Scene Plan shot 都绑定 owned source interval、证据行、裁切策略和 3:4 主体完整性。
- TTS、字幕、画面和 render timeline 均由同一 canonical plan/hash 生成。
- Sample 的 alignment report 同时通过确定性硬门和语义审核；旧报告不能污染新样片。
- 同片不重复 `media_id + in_point`，跨候选有明确差异轴和相似性预算。
- final QA、L1a、alignment、人工 sample review 全部通过后才允许 compose/publish。
- 毛巾批次脚本不再自行重建语义关系，只作为 canonical 主干的兼容入口。

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

### Task 2: Canonical source research artifacts

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
- [ ] 对关键动作缺失、产品身份错误、caption conflict 实现 fail-closed。
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

本设计已锁定的默认值：统一 evidence matrix 由 `reference_source_matrix` 承载；source-led canonical Research 不产出或读取 reference artifacts；相似度采用“动作序列 + 文本 n-gram + 时间结构”的纯 Python baseline；四个产品各自完成产品级 Research，批根只汇总去重。

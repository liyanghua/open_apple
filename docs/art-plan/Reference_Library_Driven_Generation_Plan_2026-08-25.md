# 参考库驱动量产：43 条人工模板适配与批量混剪方案（2026-08-25）

> 输入：`docs/insight_source/视频分镜拆解_2026-08-15.xlsx`（43 个 sheet，每条模板 14 列人工拆解）
>
> 结论：**生产链路统一，模板适配模式和 43 项批量控制面单独建模。** 不新建一套重复的 render/edit pipeline，也不把 43 条任务硬塞进现有 5-10 候选的 `candidate_batch`。

## 0. 架构决策

### 0.1 什么统一，什么分离

| 层 | 决策 | 原因 |
|---|---|---|
| 生产阶段 | 统一复用 `cinematic-fast`：`research → proposal → script → scene_plan → assets → sample → edit → compose → publish` | 现有链路已经有 evidence、原创边界、审批、成本、QA、checkpoint 和 render runtime 约束 |
| 模板知识 | 新增 `template_pack`（模板包）作为只读输入 | 43 条人工拆解不是一次普通参考视频分析，而是可复用的结构化先验 |
| 单条适配 | 新增 `template_run_plan`，每条输出记录模板、商品事实、素材替换和差异策略 | 保持每条视频独立可回溯，不改写共享模板 |
| 批量编排 | 新增 `template_batch` 控制面 | 43 条超出现有 `candidate_batch` 的 10 条上限；其“每条模板都要产出”也不同于候选批只选 1-2 条 |
| 渲染与质量 | 统一使用现有 `video_compose`、`final_qa`、`technical_validator`、`video_judge` | 不重复实现工具、runtime 和质量门 |

因此这是**同一生产链的第二种执行模式**，不是第二条内容生产链：

```text
template_pack（一次导入、锁定）
  → template_batch（43 个独立 run + 并发/预算/发布策略）
  → 每个 run 复用 cinematic-fast 阶段
  → template_run_plan + scene_plan + assets + sample + final QA
```

### 0.2 为什么不能直接复用 `candidate_batch`

现有 `candidate_batch` 的契约是“共享一次研究，最多 10 个创意候选，最终人工选择 1-2 条精剪”；其最大候选数和选择规则见 `schemas/artifacts/candidate_batch.schema.json` 与 `skills/meta/batch-producer.md`。43 模板批量生产需要：

- 允许 43 个 template runs，仍限制实际并发为 2-3；
- 每个模板有稳定的 `template_id`/`slot_id` lineage，而不是 hook/pacing 等候选差异轴；
- 支持 `publish_policy: all_qa_passed | selective`，不能默认套用“只选 1-2 条”；
- 某条失败时可重试或暂停该条，不污染其他 run；
- 批根统一锁定 template pack、商品事实、provider/model/runtime 和预算。

可以复用 `candidate_batch` 的持久化、成本和报告实现，但不能复用其语义和硬约束。

## 1. 模板包：把人工拆解变成可版本化输入

### 1.1 稳定身份与 provenance

43 个 sheet 是 43 个模板，但名称中的视频编号并不连续（例如存在 `视频47`、`视频48`、`视频49`）。因此不能用 `v01` 等推断 ID。导入时生成：

```json
{
  "template_id": "sheet-01-video1-aks-zhuodian",
  "sheet_name": "视频1_AKS桌垫",
  "source_document": {
    "path": "docs/insight_source/视频分镜拆解_2026-08-15.xlsx",
    "sha256": "...",
    "parser_version": "xlsx-template-import@1"
  },
  "slots": [
    {
      "slot_id": "sheet-01-video1-aks-zhuodian-slot-001",
      "ordinal": 1,
      "duration_s": 2.4,
      "shot_language": {"shot_size": "近景", "camera_movement": "固定", "camera_angle": "俯拍"},
      "visual_content": "产品铺开并贴合桌面",
      "overlay_text": "贴合桌面",
      "caption_treatment": "animated",
      "effect_treatment": "字幕动画",
      "audio_layers": ["动作声"],
      "music_profile": "轻快短促"
    }
  ]
}
```

`overlay_text` 是参考证据，不是可复制文案；模板包还必须保存源文件 hash、sheet 名、slot 数量、原始行号或单元格范围、规范化版本和导入 warnings，保证重跑幂等、可审计。

### 1.2 Excel 字段映射（必须修正）

Excel 的 H 列是“花字”（文字内容），I 列是“特效”（处理方式）。不能从 H 列推断 treatment。

| Excel 列 | 目标字段 | 规则 |
|---|---|---|
| H `花字` | `overlay_text` | 保留人工拆解文本；空值为 `null`/空字符串 |
| I `特效=字幕` | `caption_treatment: subtitle` | 普通字幕/静态字幕 |
| I `特效=字幕动画` | `caption_treatment: animated` | 动效字幕 |
| I `特效=淡入` | `caption_treatment: fade_in` | 淡入 |
| I `特效=淡出` | `caption_treatment: fade_out` | 淡出，不能丢失 |
| I 为空且 H 为空 | `caption_treatment: none` | 该镜无花字处理 |
| I 为空但 H 非空 | `caption_treatment: static` | 有花字但未记录动画 |
| 其他值 | `caption_treatment: unknown` + warning | 进入人工复核，不静默归类 |

### 1.3 与 `research_breakdown` 的兼容方式

当前 `ecommerce-storyboard-cn@1.0` profile 固定 14 个维度，校验要求每个 observation 的 `values` key 集合与 profile 完全一致。因此不能直接把 `caption_treatment`、`caption_text` 塞进 `research_breakdown.reference_shots[].values`，也不能重复造一个 `caption_text`（已有 `overlay_text`）。

采用两层模型：

1. `research_breakdown` 继续保存 14 维观察：H 列写入已有 `overlay_text`，I 列规范化后写入已有 `effect_treatment`。
2. `template_pack.slots[].caption_treatment` 保存模板特有的处理枚举；如未来要让所有研究 profile 都支持它，再新建 profile `ecommerce-storyboard-cn@1.1`，同步升级 profile digest、projection cache key、schema fixtures 和测试。

模板包导入是人工数据的**事实锁定**，不是让 `video_analyzer` 重新猜测人工列。若后续用视频分析校验模板，只能生成 warning/置信度，不覆盖人工值。

## 2. 参考 treatment 如何进入自有视频

### 2.1 不直接继承 recipe intent

参考的 `caption_treatment` 和自有视频的 `caption_recipe_intent` 是不同层级：

- `caption_treatment`：参考模板“用了什么表现方式”；
- `caption_recipe_intent`：自有镜头“为什么需要这种字幕意图”，由自有 shot 的 `narrative_role`/`shot_intent` 决定。

默认规则：

```text
自有 shot_intent/narrative_role → caption_recipe_intent → recipe_router(runtime)
参考 caption_treatment → 风格约束/候选提示，不覆盖自有语义
```

只有自有镜头没有显式 intent 时，才允许使用以下**带 fallback 标记**的提示映射：`animated→hook`、`fade_in→reveal`、`subtitle/static/none→label`、`fade_out→label`。映射结果必须记录 `derived_from: template_treatment` 和 `fallback_used: true`，不能在验收中声称“与参考花字列一致”就代表语义正确。

参考花字文本不得进入最终字幕；最终文案来自商品事实卡、批准的 script 和本项目 caption policy。参考片只允许 `analysis_only` 使用，不能复制参考视频、字幕素材、字体文件或成片片段。

## 3. 适配原链路：阶段映射

| 原链路阶段 | 模板模式的输入/动作 | 产出与硬门 |
|---|---|---|
| `research` | 一次性导入并校验 `template_pack`；分析自有素材、商品事实、版权边界。无需对 43 条模板重复跑完整视频分析 | 共享 `research_breakdown`、`source_media_review`、`media_index`、`reference_source_matrix`、`research_scorecard`；模板包 hash 进入 provenance |
| `proposal` | 批根锁定 43 个模板的适配范围、3 个可复用差异策略、商品事实和原创规则；为每条 run 选择一个 `template_id` | `template_batch` + `template_run_plan`；不为每条模板重新发明一个概念 |
| `script` | 读取模板的 slot 节奏/叙事角色，重写为本商品事实；不得复制参考台词、花字或 claims | 每条独立 `script`，含 `template_id` 和商品事实引用；仍需 script approval |
| `scene_plan` | 将模板 slot 当作结构约束，把每个 slot 映射到自有素材或批准的生成素材；保留 `template_slot_ref`、替换原因和原创说明 | 复用现有 `metadata.source_mapping`、`matrix_row_id`、`reference_media_usage: analysis_only`；每个 scene 必须有自有 source/生成路径 |
| `assets` | 先用自有素材；缺口进入现有 TTS/BGM/图像/视频生成能力。所有付费调用仍在 creative lock 后 | 每条 `asset_plan`、`shot_execution_plan`、成本估算和审批 bundle |
| `sample` | 先做 5-10 条 pilot，至少覆盖不同 archetype、素材缺口和字幕 treatment；模板结构相同的 run 可复用静态准备，但不能复用成片 | 每条样片独立 QA、evaluation report；失败只阻塞该 run |
| `edit` | 沿模板 slot 顺序组装，但允许在批准的范围内替换素材、调整时长和删减不可行 slot | `edit_decisions` + `change_impact`，不得静默改变 template lock |
| `compose` | 复用现有 recipe router、Remotion/HyperFrames 选择和 render QA | 每条独立 render report、final review、evaluation report |
| `publish` | 按批根 `publish_policy` 发布：用户明确要求全量时才允许 `all_qa_passed`；否则为 `selective` | 每条输出必须通过版权、技术和内容 QA，批根汇总失败/跳过/发布状态 |

关键变化是：**模板只约束 slot 的结构、节奏和表现语法；商品事实、脚本、素材、字幕文本和最终画面仍属于每个自有 run。**

## 4. 三个新增契约

### 4.1 `template_pack`

只读、内容寻址的模板库 artifact。至少包含：`source_document`、`templates[43]`、每个模板的 `slots`、`caption_treatment`、`archetype`、`normalization_warnings`、`taxonomy_version`。必须登记到 `schemas/artifacts/__init__.py`、`backlot/state.py`，并可被 checkpoint envelope 校验。

### 4.2 `template_run_plan`

单条输出的不可变适配计划：

```json
{
  "template_id": "sheet-01-video1-aks-zhuodian",
  "template_pack_ref": {"artifact_sha256": "...", "version": "1.0"},
  "product_facts_ref": {"artifact_sha256": "..."},
  "adaptation_policy": "proof-first",
  "slot_bindings": [
    {"slot_id": "...-slot-001", "source": "owned", "source_media_id": "source-12", "reason": "自有素材展示同一产品动作"},
    {"slot_id": "...-slot-002", "source": "generate", "asset_type": "video", "reason": "自有素材缺失，按模板镜头语法补齐"}
  ],
  "caption_policy": {"reference_text": "analysis_only", "copy_reference_caption": false},
  "status": "awaiting_human"
}
```

`slot_bindings` 是资产和 scene_plan 的共同输入；没有绑定、没有来源或没有替换理由的 slot 不能进入 paid assets。

### 4.3 `template_batch`

批根控制面至少包含：

- `template_pack_ref`、`product_facts_ref`、`shared_research_refs`；
- 43 个 `runs[]`，每个有 `template_id`、`project_id`、`template_run_plan_ref`、状态、成本、重试次数和失败原因；
- `concurrency.max_parallel`（默认 2-3）、`budget.max_cost_usd`、`max_retries_per_run`；
- 固定的 provider/model/render runtime 与版本；
- `pilot_run_ids`、`publish_policy`、`selection` 和批级报告引用。

批量状态必须能区分 `planned / awaiting_human / in_progress / sampled / evaluated / failed / published / skipped`。批量编排器只调度和汇总，不把创意决策或 provider API 调用写进 Python 工具。

## 5. 43 条模板的 archetype 用法

“43 条模板”与“archetype 聚类”不是同一个对象：

- `template_id`：可执行的具体 slot 序列，必须保留 43 个；
- `archetype_id`：对表达/节奏/叙事的归纳，用于筛选、pilot 覆盖和推荐，可一对多；
- 聚类不能删除或合并模板，也不能让聚类结果覆盖人工 slot。

第一版允许人工指定 archetype；自动聚类必须保存 `clustering_version`、特征来源、置信度和人工修订记录。聚类失败不阻塞按具体模板执行。

## 6. 素材缺口与原创边界

| 情况 | 允许做法 | 必须记录 |
|---|---|---|
| 自有素材可覆盖 | 使用项目 owned source set，按模板 slot 选择区间 | source media、时间码、source_fit |
| 只有模式没有素材 | 生成新素材，沿用景别/机位/节奏等抽象语法 | provider/model、prompt/version、成本、生成原因 |
| 只有参考截图/成片 | 仅作为 analysis evidence | `reference_media_usage: analysis_only`，禁止进 assets/render |
| 参考片带文字、logo、音乐或字体 | 不复制；用商品事实和批准素材重做 | rights/copy/claim review、replacement reason |

“借鉴模板素材”只能表示借鉴模式，不能表示复用模板文件。若法务或版权状态不明确，run 进入 `awaiting_human`，不能自行选择替代 provider 或素材。

## 7. 落地顺序

1. **先修正导入语义**：确认 H/I 列映射，建立稳定 `template_id`，输出 43 条 slot，保存 xlsx hash 和 warnings。
2. **建立 `template_pack` contract**：不改动现有 14 维 research profile；将 treatment 放到模板包，补 schema、registry、Backlot、envelope 和幂等导入测试。
3. **建立单条 `template_run_plan`**：先用 1 条模板走通现有 `cinematic-fast`，验证 slot binding、原创边界、caption policy 和 recipe fallback。
4. **建立 `template_batch` 控制面**：复用 candidate batch 的成本/报告代码，但新增 43-run 调度、失败隔离、全量/选择性发布策略和批级 checkpoint。
5. **5-10 条 pilot**：覆盖主要 archetype、至少一种素材缺口、`subtitle/animated/fade_in/fade_out/none` treatment；比较质量、成本、时延和人工返工率。
6. **扩展到 43 条**：pilot 的硬门通过后再全量，禁止在关键路径临时发明工具或静默替换 provider/model/runtime。

建议涉及的实现文件：

- 新增：`schemas/artifacts/template_pack.schema.json`、`template_run_plan.schema.json`、`template_batch.schema.json`；
- 新增：`lib/template_import.py`、`lib/template_batch.py`；
- 修改：`schemas/artifacts/__init__.py`、`backlot/state.py`、`pipeline_defs/cinematic-fast.yaml`；
- 修改导演契约：`skills/pipelines/cinematic-fast/research-director.md`、`proposal-director.md`、`script-director.md`、`scene-director.md`、`asset-director.md`；
- 测试：导入幂等/hash、43 条覆盖、slot lineage、reference caption 禁止、批量并发/预算/失败隔离、checkpoint 恢复和全量发布策略。

## 8. 验收

### 模板包

- xlsx 解析得到 43 个稳定 `template_id`，每个 slot 可回到 sheet/行；
- H 列进入 `overlay_text`，I 列进入规范化 `caption_treatment`，`淡出` 和未知值不丢失；
- 重复导入同一 source hash 结果一致，source hash 或 parser/taxonomy version 变化会产生新 artifact hash；
- `template_pack` 注册到 artifact/checkpoint/Backlot，能独立恢复和审计。

### 单条适配

- `template_run_plan` 能把每个模板 slot 绑定到 owned 或 generated 素材；
- 自有 `caption_recipe_intent` 由 shot intent 派生，参考 treatment 仅作为有 provenance 的提示；
- 参考花字、视频、字体、logo、音乐不会进入最终资产；
- scene mapping、caption policy、成本和 provider/model/runtime 都可追溯。

### 批量生产

- `template_batch` 能管理 43 个 run，限制并发、预算和重试，并隔离单条失败；
- pilot 5-10 条通过后才能扩展全量；
- 每条 run 都有独立 sample/QA/evaluation，批根可汇总成功、失败、跳过、发布；
- `publish_policy=all_qa_passed` 只有在用户明确要求全量时启用，不能继承现有 candidate batch 的“自动选 1-2 条”语义。

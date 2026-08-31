# 单条审批工作台九阶段产物完整性升级实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让单条审批工作台完整保留老工作台九个阶段的关键业务产物，并以一线人员能直接理解的结构呈现，避免字段取错、内容丢失、重复展示和工程字段回流。

**Scope:** `research / proposal / script / scene_plan / assets / sample / edit / compose / publish` 九阶段的 operator-state 投影、审批适配器、详情渲染器、业务字段测试和手动验收准备。

**Non-goals:** 不新增审批事实、不改变 `subject_hash`/`workflow_revision`/`evaluation_hash` 协议、不实现编辑工作室、修改并重跑、批量生成调度或新的审批门。

## 文档关系与当前基线

| 文档 | 作用 | 本次调整 |
|---|---|---|
| `docs/superpowers/specs/2026-08-28-backlot-business-language-workbench-design.md` | 业务目标、九步流程、页面和数据约束 | 增加九阶段产物完整性契约，状态改为“基础展示已实施、产物整改中” |
| `docs/superpowers/plans/2026-08-28-backlot-business-language-workbench-plan.md` | 批量/单条事实、审批门和一致性实施计划 | 保留 Phase 0–5 历史完成记录，新增产物完整性后续阶段 |
| `docs/superpowers/plans/2026-08-28-single-review-workbench-visual-upgrade.md` | 单条审批壳、导航、视觉和手动验收 | 明确九阶段适配器仍需专项整改，手动验收依赖本计划 |
| `docs/reports/2026-08-26-analysis-readonly-workbench-run-report.md` | 实施和回归记录 | 新增 2026-08-31 阶段产物审查结论与当前阻塞项 |
| `docs/reports/2026-08-28-single-review-manual-acceptance-checklist.md` | 业务方手动验收步骤 | 增加阶段产物完整性前置检查 |

当前实现边界：`backlot/ui/operator/approval_model.js` 负责把 `operator-state` 转为材料模型，`backlot/ui/operator/approval.js` 负责审批壳和材料详情，`backlot/operator_state.py` 负责公开字段投影，旧阶段 renderer 仍保留在 `backlot/ui/operator/app.js` 作为对照和后续 Studio 入口。

## Chunk 0：锁定产物契约和命名

### Task 0.1：统一阶段材料 ID

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `tests/backlot/test_operator_artifact_model.py`
- Modify: `docs/superpowers/specs/2026-08-28-backlot-business-language-workbench-design.md`

- [x] 记录九阶段每个材料的稳定 ID、业务标题、必备字段和允许的媒体动作（已落 spec §9.5 契约表）。
- [x] 解决 `risks` / `source_risks` 命名漂移，更新测试和文档后只保留一个规范 ID（规范 ID = `source_risks`）。
- [x] 增加“同一事实只能在一个主材料中呈现，摘要卡不得重复完整正文”的契约。
- [x] 运行 `PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot/test_operator_artifact_model.py`（8 passed；全量 349 passed, 1 skipped）。

## Chunk 1：阶段级业务适配器

### Task 1.1：补齐 proposal 和 script

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `tests/backlot/test_operator_artifact_model.py`

- [x] 新增 `compactProposal()`：采用方向、备选方向、卖点、目标人群、语气、视觉方法、有效原因、行动引导、预计成本和导演总控单均可读（新增 `control_plan`、`production_budget` 材料）。
- [x] 新增 `compactScript()`：按开场/正文/结尾输出口播、字幕、段落目标、画面重点、节奏、证明要求；`control_rule_refs`、review 和 feedback 进入制作记录或单独状态区。
- [x] 避免“制作脚本 / 口播 / 屏幕文字”重复渲染完整相同内容；摘要卡只保留数量和入口（`narration`/`on_screen_text` 只输出 `section_count/total_seconds/source`）。
- [x] 测试工程字段不出现在主 payload，业务字段不为空时不会被通用 fallback 覆盖（`test_proposal_adapter_reads_direction_fields_control_plan_and_budget`、`test_script_adapter_structures_sections_and_drops_engineering_fields`）。

### Task 1.2：补齐 scene_plan 和 assets

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `tests/backlot/test_operator_artifact_model.py`

- [x] 新增 `compactScenePlan()`：每镜包含镜头目的、参考依据、自有素材、源素材区间、成片时间轴、素材能证明什么、画面重点和安排理由。
- [x] 明确 `timeline_in_seconds/out` 与 `source_in_seconds/out` 的语义，禁止交叉使用（`action_timing` 只输出时间轴字段，允许回退到投影中同为时间轴语义的 `in/out`，禁止回退到源区间）。
- [x] 新增 `compactAssets()`：生成清单、素材状态、生成任务、预览、失败原因、预计费用/已用费用和口播字幕状态统一输出（新增 `generation_tasks` 材料）。
- [x] 预览和下载地址作为受控媒体动作保留，不作为普通文本字段递归输出（分镜 `preview_url/poster_url` 随 payload 传递，模型名/provider 排除出主 payload）。

### Task 1.3：补齐 sample、edit、compose、publish

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `backlot/operator_state.py`
- Modify: `schemas/backlot/operator_state.schema.json`
- Modify: `tests/backlot/test_operator_artifact_model.py`
- Modify: `tests/backlot/test_operator_state.py`

- [x] sample：完整输出计划/实际镜头对照、口播、字幕、音轨、字幕差异、导演规则差异、检查结论和恢复提示。
- [x] edit：输出精剪状态、修改前样片、影响镜头、声音字幕结果和“是否可以进入成片检查”（新增 `compose_readiness`）；审批页不暴露编辑能力入口。
- [x] compose：输出完整视频、版本变化、画面/声音/字幕时间轴、硬性检查、观感结论和待处理问题（新增 `version_history`、`pending_changes`）。
- [x] publish：输出当前版本、平台 entries、导出状态、文件清单、下载动作、失败原因和 QA 证据（新增 `delivery_package`、`qa_evidence`）。
- [x] 如 operator-state 缺少口播或 `caption_diff/creative_rule_diff`，只扩展只读投影字段，不改变审批 API（`_sample_editor` 补逐镜口播与两个 diff，schema 同步，`test_operator_state.py` 覆盖）。

## Chunk 2：阶段专用详情阅读器

### Task 2.1：建立详情组件分流

**Files:**

- Modify: `backlot/ui/operator/approval.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`

- [x] 保留统一三栏壳和 `selectedStageId/selectedArtifactId` 浏览状态。
- [x] 增加阶段级详情分流：研究步骤、创意方案、脚本、分镜、制作准备、样片对照、精剪状态、成片检查、交付信息（`STAGE_DETAIL_READERS` 按材料 ID 分流，35+ 阅读器）。
- [x] `renderArtifactValue()` 只作为低风险纯文本 fallback，不再承担镜头、时间轴、检查项、交付文件和生成任务的主渲染。
- [x] 技术字段进入“制作记录”，媒体字段转成播放器、预览、下载等业务动作（`mediaVideo/mediaDownload`，平台导出与交付文件提供下载动作）。

### Task 2.2：统一空态、失败态和状态摘要

**Files:**

- Modify: `backlot/ui/operator/approval.js`
- Modify: `backlot/ui/operator/language.js`
- Test: `tests/backlot/test_operator_single_review.py`

- [x] 统一“未生成 / 正在准备 / 资料异常 / 播放失败 / 报告不完整”的中文状态和恢复动作。
- [x] 阶段摘要显示业务结果，不显示对象数量代替结论（脚本/分镜/清单/样片等摘要已改为“N 段/个镜头/条素材 + 结果”，条目式摘要保留“数量 + 入口”）。
- [x] 当前待确认阶段显示确认动作；历史阶段、后续阶段和精剪阶段保持只读。

## Chunk 3：去重、业务语言和可访问性回归

### Task 3.1：文案与重复内容扫描

**Files:**

- Modify: `tests/backlot/test_business_language_contract.py`
- Modify: `tests/backlot/test_operator_single_review.py`

- [x] 禁止主界面出现 `plan_id`、`control_rule_refs`、`runtime`、`revision`、`source_media_id`、模型名、文件路径等内部字段（模型级工程字段契约测试 + UI 层 token 只允许出现在 `isTechnicalArtifactKey` 过滤函数内 + HTML 可见文字禁词扫描）。
- [x] 增加重复内容断言：脚本文案、字幕、样片镜头对照不能在多个主卡片完整重复（脚本完整正文唯一出现在 `production_script`；样片字幕/口播唯一出现在 `captions_voice`，`shot_comparison` 只保留差异与素材身份）。
- [x] 保留制作记录中的必要技术信息，但不作为一线审批依据（交付路径/导出路径保留在 payload 供下载动作使用，不作为正文渲染）。

### Task 3.2：交互和无障碍回归

**Files:**

- Modify: `tests/backlot/test_operator_single_review.py`
- Modify: `backlot/ui/operator/approval.js`

- [x] 阶段、材料、时间片段、预览和下载动作均可通过键盘操作（阶段/材料/跳转均为原生 button，下载为原生 anchor）。
- [x] 媒体失败、刷新和审批错误使用 `aria-live="polite"`（播放器错误、异步状态均有 polite live region）。
- [x] 所有材料卡保留 `aria-current` 和稳定 `data-testid`（`approval-artifact-<id>`）。

## Chunk 4：验证和手动验收准备

### Task 4.1：九阶段完整性测试

**Files:**

- Modify: `tests/backlot/test_operator_artifact_model.py`
- Modify: `tests/backlot/test_operator_state.py`
- Modify: `tests/backlot/test_operator_single_review.py`

- [x] 为九个阶段各准备最小 fixture，断言老工作台关键业务字段在新审批材料中至少出现一次（`test_nine_stage_minimal_fixture_keeps_legacy_business_fields`，29 项断言）。
- [x] 增加字段语义测试：分镜时间轴、样片口播、成片检查、交付下载不可为空或错位（`action_timing` 只含时间轴、`captions_voice` 含实际口播、`final_video`/`quality_conclusion`、`delivery_package`/`qa_evidence` 下载动作）。
- [x] 增加缺失/处理中/失败/报告不完整/权限变化 fixture，确认只读降级不伪造结果（`test_degraded_states_never_fabricate_results` + `test_compose_and_publish_degrade_honestly_when_render_missing`；空数据不再产生“ready”空 payload）。

### Task 4.2：三档手动验收

**Files:**

- Modify: `docs/reports/2026-08-26-analysis-readonly-workbench-run-report.md`
- Modify: `docs/reports/2026-08-28-single-review-manual-acceptance-checklist.md`

- [ ] 先走查九阶段材料，再走查 1180px、900px、390px 布局。
- [ ] 逐个点击九个阶段和每阶段材料，确认标题、摘要、中间详情、右侧状态一致。
- [ ] 样片阶段逐个检查样片、镜头对照、字幕和口播、声音、系统检查、系统建议、制作依据。
- [ ] 通过批量候选 → 单条复核 → 返回批量 → 刷新，确认浏览状态和审批事实不混淆。

## 回归命令

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot
node --check backlot/ui/operator/store.js
node --check backlot/ui/operator/approval_model.js
node --check backlot/ui/operator/approval.js
node --check backlot/ui/operator/app.js
```

## 停止条件

1. Chunk 1 未完成前，不把九阶段材料标记为完整，不进行最终业务验收。
2. 任一阶段出现字段错位、关键产物缺失或审批依据不完整，保留只读查看并阻止对应审批动作。
3. 任一审批一致性测试失败，不显示“已通过”，只提供重新拉取和事实说明。
4. 编辑工作室和修改并重跑继续独立，不因补齐只读产物而开放编辑入口。

## 完成标准

- [x] 九阶段均有稳定、可读、非重复的业务材料。
- [x] 老工作台的关键产物没有因统一适配器而丢失。
- [x] 分镜、样片、成片、交付的媒体和检查信息可直接操作或查看。
- [x] 主界面不出现工程字段，制作记录仍可追溯必要技术事实。
- [ ] `tests/backlot`、前端语法检查和三档手动验收全部通过（代码与测试已通过：375 passed / 1 skipped / 0 failed + `node --check`；三档手动验收待业务方执行）。

## 修订记录（2026-08-31 第二轮：真实数据联调修复）

第一轮把“适配器 fixture 通过”当作“真实链路完成”，review 发现 4 个 P1 与 2 个 P2 真实数据断链。本轮全部修复，并以真实投影集成测试闭环：

| # | 问题 | 修复 | 回归测试 |
|---|---|---|---|
| P1-1 | 生成任务只读 `generation_proposals`，看不到真实任务 | `compactGenerationTasks` 优先读取 `execution_plan.generation_tasks`，按 `proposal_id + shot_id` 关联方案，输出状态/质量/预览/实际费用/失败原因；`selected_generation_task_id` 与 `task_id` 比较；有方案无任务显示“尚未生成” | `test_generation_tasks_cover_failed_and_unstarted_states` + 集成测试 |
| P1-2 | 实际口播缺失时静默回退计划口播 | `compactCaptionsVoice` 计划/实际分开（`planned_*/actual_*`），缺失保持 null；阅读器显示“实际口播未提供/实际字幕未提供”；音轨存在时提示文本核对入口 | `test_sample_actual_narration_missing_is_never_replaced_by_plan` + 集成测试 |
| P1-3 | 直接参考片段证据被丢弃 | `compactScenePlan` 保留 `description/start_seconds/end_seconds/preview_url/poster_url`；阅读器“参考片段预览”与“自有素材预览”两个媒体动作 | `test_scene_plan_keeps_reference_segment_evidence_distinct_from_source_preview`（两 URL 必须不同）+ 集成测试 |
| P1-4 | 未选方向时默认取第一个方向并派生卖点 | `selected_id` 匹配才产出“采用方向”，否则 summary=“尚未选定方向”；全部方向进“备选方向”；未选方向不生成卖点 | `test_proposal_without_selected_direction_never_fabricates_first_concept` + 集成测试 |
| P2-5 | 预计/已用费用共用字段 | `_asset_editor` 拆为 `estimated_cost_usd`（清单预计总额）+ `spent_cost_usd`（实际已用），schema 与阅读器同步 | 更新 `test_assets_adapter_...` |
| P2-6 | 脚本入口 payload 含 `source: "production_script"` | 删除 `source` 字段，摘要入口只保留数量与时长 | 更新 `test_script_adapter_...` |

**集成测试**：`test_real_operator_state_flows_through_approval_adapter` 走真实 `project_operator_state` 投影 + `_inject_generation_tasks`（与 `load_operator_state` 共享同一注入函数，真实任务目录读取）→ node `buildApprovalStages`，断言四个 P1 字段端到端不丢、不伪造。

**验证**：`PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot` → **375 passed, 1 skipped, 0 failed**；`node --check` 与 `git diff --check` 通过。

**状态收窄声明**：完成标准 1–4 仅在“适配器 fixture + 真实投影集成测试”双重证据下勾选；`test_nine_stage_minimal_fixture_keeps_legacy_business_fields` 是适配器层测试，不单独作为真实产物完整性证据。三档视觉验收仍待业务方在产物完整性走查（清单步骤 0）通过后执行。

## 修订记录（2026-08-31 第三轮：5 个 P1 + 3 个 P2）

第二轮后 review 确认 `3c089e7` 修复有效，但测试全绿仍未覆盖复合键冲突、矛盾质量结论、空集合语义和九阶段全空数据，5 个 P1 使页面呈现与真实业务结论不符。本轮全部闭环：

| # | 问题 | 修复 | 回归测试 |
|---|---|---|---|
| P1-1 | 检查结论互相冲突（“检查通过，可以交付”与 revise/repair、硬门失败并存） | 新增 `_merge_qa_with_evaluation`：文件/渲染检查与内容质量评价按更严格结果归约（`status∈{revise,fail}`、`recommended_action∈{repair,reject}`、硬门失败非空 → “需要调整”）；sample 与 compose/publish 的 `qa_status` 统一走该函数 | `test_sample_qa_status_merges_evaluation_failures`、`test_compose_qa_status_merges_final_evaluation_failures` |
| P1-2 | 生成任务关联键不完整（proposal_id 复用导致任务挂错镜头） | `compactGenerationTasks` 改用 `(shot_id, proposal_id)` 复合键，proposal 唯一时回退按 proposal 匹配，再回退按 shot 匹配；pending 行同样按复合键去重 | `test_generation_tasks_join_uses_composite_shot_proposal_key` |
| P1-3 | 缺少口播仍显示已配好（口播轨存在但 state 非 present / 文本来自计划字幕） | `sampleFacts.narrationText/captionText` 只取 `actual.narration/actual.screen_copy`；门结论改为 `narrationReady && captionsReady` 双条件，否则显示“口播或字幕还没有完整核对” | `test_sample_gate_narration_copy_uses_actual_not_planned` |
| P1-4 | 原声状态无法正确表达（固定 planned=False 导致 present 也显示未安排；缺失信号默认 True） | `_audio_tracks` 原声改为 presence-only：present→“present”、False→“not_planned”、缺失→“unknown”，不再默认 True；schema `state` 枚举加 `unknown`；阅读器原声标签（有原声/未保留原声/原声状态未记录） | `test_original_sound_state_is_presence_based_not_planned`、`test_original_sound_state_has_business_labels` |
| P1-5 | 未开始阶段伪造已准备产物（edit_result/quality_conclusion 空数据仍 ready） | `compactEditResult`/`compactQualityConclusion`/`compactComposeReadiness`/`compactSources` 无业务字段时返回 null；`compose_readiness` 空态文案“尚未开始精剪” | `test_empty_stages_never_fabricate_ready_materials` |
| P2-6 | 合法空集合被当成资料缺失 | `artifactModel` 不再折叠空数组；`source_risks=[]`→“未发现风险”、`pending_changes=[]`→“没有待处理问题”、`qa_evidence=[]`→“未提供 QA 附件”，health=ready；详情页空集合显示业务文案 | `test_legitimate_empty_collections_are_not_missing` |
| P2-7 | 素材名称显示内部哈希 | research 素材 `label` 优先取原始文件名 stem，`media_id` 只留在 `id`/制作记录 | `test_source_label_prefers_file_name_over_media_id_hash` |
| P2-8 | 业务界面泄漏内部枚举 | 集中映射 `TASK_QUALITY_LABELS`（fast/standard）、`GENERATION_OPERATION_LABELS`（text_to_video/image_to_video 等）、`EVALUATION_DIMENSION_LABELS`（八维中文）；`displayValue` 补 revise/repair/reject/proceed/fail | `test_business_enum_maps_cover_tasks_operations_and_dimensions` |

**顺带修复**：`_evaluation_summary` 的 `status/recommended_action/judge_version/name/message/note` 全部 `_safe_text` 化——此前评价报告缺 `judge_version` 等字段时会产出 None 并违反 operator_state schema（新测试暴露的真实缺陷）。

**验证**：`PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot` → **385 passed, 1 skipped, 0 failed**；`node --check`、`git diff --check` 通过。覆盖缺口（复合键冲突、矛盾质量结论、空集合语义、九阶段全空数据）已由本轮测试补齐；三档手动验收仍待业务方执行。

## 修订记录（2026-08-31 第四轮：审批动作与运行时边界 8 P1 + 4 P2）

第三轮后 review 指出测试仍偏静态契约，未覆盖审批动作与运行时边界。本轮闭环：

| # | 问题 | 修复 | 回归测试 |
|---|---|---|---|
| P1-1 | 脚本/制作准备退回必失败（issueTags 恒为 null，后端强制 ≥1 标签） | `renderConfirmationSimple` 增加门级原因标签选择器（`GATE_ISSUE_TAG_OPTIONS`，script/assets 各一组业务中文标签），退回必须 ≥1 标签才提交，标签随 `decideReview` 传入 | `test_simple_gate_reject_requires_issue_tags` |
| P1-2 | 材料缺失/报告不完整时审批按钮仍可用 | 新增 `gateMaterialsReady`：门关键材料（制作脚本/生成清单/样片）health 必须 ready，样片门还要求系统检查（评价报告）ready，阶段失败即阻断；`renderConfirmation` 依据不完整时显示只读说明与“重新拉取” | `test_confirmation_gated_by_material_and_report_completeness` |
| P1-3 | 失败阶段残留 payload 仍显示已准备 | `statusHealth` 制作中一律 processing；`artifactModel` 阶段 failed/processing 优先于 payload | `test_failed_stage_with_stale_payload_never_shows_ready` |
| P1-4 | 报告 pass 但媒体文件缺失仍判通过 | 新增 `_render_file_present`（限定项目目录内真实文件核对）；sample/compose 的 `qa_status` 在文件缺失时归约“需要调整”，`preview_url/download_url` 置空 | `test_missing_render_file_never_reports_qa_pass` |
| P1-5 | 查看 compose 时右侧事实来自 publish | `factsForGate` 拆分 done/publish：检查成片只读 compose 数据，确认交付才读 publish 数据 | `factsForGate` 同源（静态） |
| P1-6 | 成片完成面板硬编码“检查通过” | `renderConfirmationDone` 按 `qa_status` 条件呈现：未通过显示“检查还有问题 · 请先查看检查结果并处理” | `test_done_panel_never_claims_pass_when_qa_requires_adjustment` |
| P1-7 | 镜头未完整执行仍绿色完成 | 样片说明按 `executed/partial/added/not_in_sample` 与 `planned_shot_count` 判定完整执行，未完整时黄色提示“N 个镜头未完整进入样片” | `test_sample_gate_copy_acknowledges_incomplete_shots` |
| P1-8 | 时间轴片段按钮无实际行为 | 从镜头对照打开时中间区无播放器：时间轴自带 `approval-timeline-video` 播放器并绑定跳转；无样片时明示“暂不能跳转” | `test_timeline_embeds_player_when_media_area_has_no_video` |
| P2-9 | 系统建议忽略评价结论 | 建议卡在 `revise/fail` 或 `repair/reject` 时显示“系统建议修改后再确认” | `test_system_suggestion_respects_evaluation_conclusion` |
| P2-10 | 真实维度名（Hook Clarity）显示英文 | 新增 `evaluationDimensionLabel` 归一化（去空格/下划线/连字符小写）后查中文表 | `test_evaluation_dimension_labels_normalize_real_report_titles` |
| P2-11 | 工程枚举直接进界面 | 时长检查 `payload.status` 与制作记录 `recommended_action` 均经 `displayValue` 中文映射 | `test_technical_enums_never_render_raw` |
| P2-12 | 刷新过度清除浏览位置 | `store.setProject` 只在当前确认门或 `subject_hash` 变化时重置；纯 revision、其他阶段版本变化不打断浏览；仅正在查看的阶段自身版本变化回到确认门 | `test_store_preserves_valid_selection_and_resets_on_revision_or_subject_change`（语义更新） |

**顺带验证**：P1-4 的存在性核对在 `.backlot/review-stage` fixture 上复核——`review-sample-gate` 的 `renders/sample-v1.mp4` 真实存在，qa 仍为“检查通过”且预览正常；`review-missing` 的“样片缺失”语义保持一致。

**验证**：`PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot` → **395 passed, 1 skipped, 0 failed**；`node --check`、`git diff --check` 通过。三档手动验收仍待业务方执行。

# 批量混剪运营工作台交互设计（2026-08-23）

> 日期：2026-08-23
> 版本：v1.2
> 状态：批量驾驶舱已落地；Editorial Gallery 真实数据接入待实施
> 范围：OpenMontage `cinematic-fast` 批量混剪模式的运营工作台（`/p/<project-id>`）交互设计；候选单任务工作台保留不变
> 依赖文档：`Design_Review_2026-08-22.md`（评价/批量数据层）、`Autoresearch_Video_Remix_Integration_Design_2026-08-23.md`（优化闭环）、`skills/pipelines/cinematic-fast/optimize-director.md`（批量编排 runbook）
> 必须先满足的实现契约：[`Batch_Workbench_Aggregate_State_Event_Contract_2026-08-23.md`](./Batch_Workbench_Aggregate_State_Event_Contract_2026-08-23.md)、[`Batch_Workbench_Cross_Project_Approval_Consistency_Contract_2026-08-23.md`](./Batch_Workbench_Cross_Project_Approval_Consistency_Contract_2026-08-23.md)
> Editorial Gallery 接入计划：[`2026-08-24-editorial-gallery-real-data-integration.md`](../superpowers/plans/2026-08-24-editorial-gallery-real-data-integration.md)

## 0. 背景与已确认决策

用户核心目标：**先人工 review 的批量混剪生产**，评价体系稳固后再用 autoresearch 机制自动迭代。

本轮已确认的四项决策（本设计的执行依据）：

| 决策项 | 结论 |
|---|---|
| 工作台形态 | 完整批级驾驶舱（批级轨道 + 候选矩阵 + 评分对比 + 人工选择 + 预算面板） |
| 审批密度 | 批级一键通过（每个门一次批操作，逐候选列表可展开复核、单独驳回） |
| 优化模式 | 纯人工 review：`optimization_policy.enabled=false`，不显示迭代面板、不自动 mutation |
| 首轮启动参数 | 默认值：沿用 v8 透明桌垫素材池 / 5 默认方向 / 抖音 9:16 竖屏 15s / 预算 30 USD |
| 样片质量底线 | 字幕缺失、候选结构同质化、开场画面与首段口播冲突时，样片只能停在质量阻塞，不得进入候选选择 |
| 编辑室入口 | 批级样片门完成后，用户选择 1–2 个已评估候选，才进入对应候选的最新终稿编辑室 |

架构边界（不因本设计改变）：不新增第二套 orchestrator；`candidate_batch` 只是索引；每个候选是独立项目（独立 artifact/checkpoint/decision_log）；`decision_log` 是追加式审计；所有写入经 ProjectCommitStore 事务或原子写入。

## 1. 现状与差距

### 1.1 现有能力（已投产）

- 单任务运营工作台：9 阶段轨道 + 每阶段 editor（research/proposal/script/shot/assets/sample/edit/delivery）+ `pending_review`（script_lock/creative_lock/sample 三种门审批，`ReviewService`）。
- 数据层：`candidate_batch` 状态机（planned→in_progress→sampled→evaluated→failed→selected_for_edit）、`optimization_policy/optimization_run`、统一分数聚合（`lib/optimization_scoring`）、`lib/batch_fork`（一次研究分叉候选项目）、scoped `evaluation_report.sample/.final`、样片页评价卡 + 三轨音频。
- 诊断板 `/diagnostics/p/<id>` 有 `candidate_batch` 静态索引卡。

### 1.2 差距（为什么需要本设计）

| # | 差距 | 用户影响 |
|---|---|---|
| 1 | `batch-<id>` 的运营页没有批级投影 | 打开批项目页看不到任何批进度 |
| 2 | 候选进度散落在 5 个独立项目页 | 要开 5 个标签页才能拼出全局进度 |
| 3 | 无横向评分对比 UI | "选 1–2 条进精剪"没有可操作的载体 |
| 4 | 无批级门审批 | 每候选 3 个门 × 5 候选 = 15 次重复确认 |
| 5 | 无预算/并发可视化 | 批量跑超预算时用户无感 |

## 2. 信息架构：批级驾驶舱

入口：`/p/<batch-id>`（候选项目各自的 `/p/<candidate-id>` 页保持单任务形态，用于深挖与单候选驳回）。

### 2.1 批级阶段轨道（6 相）

| 相 | 判定规则（由 `candidate_batch` 聚合） | 完成条件 |
|---|---|---|
| 建批 | batch 已存在 | 5 候选项目已分叉 |
| 首轮样片 | 任一候选 in_progress | 全部候选 ∈ {sampled, failed} |
| 评分 | 任一候选 sampled | 全部存活候选 evaluated |
| 人工选择 | 全部可继续候选 `evaluated` 且样片效果门完成 | `selection.selected_candidate_ids` 非空 |
| 精剪 | 有选中候选 | 选中候选完成 edit+compose |
| 发布 | 选中候选已交付 | 全部选中候选 publish 完成 |

失败候选在矩阵中灰显（保留留档），不阻塞其它候选的轨道推进。

### 2.2 候选矩阵

5 列（候选）× 阶段行（proposal/script/scene_plan/assets/sample/evaluated/selected），每格状态芯片；点击任意格深链到该候选工作台的对应阶段页。候选列头显示：方向标签、项目链接、成本、重试次数。

### 2.3 评分对比卡（人工选择的载体）

横向 5 列，每列：

- 前 3 秒样片缩略/播放（复用样片预览链接）；
- 评价卡（L1a 状态 + 8 维 L3 分数带颜色，与成片评价卡同款渲染）；
- 三轨音频状态（口播/BGM/原声）；
- 成本（USD）与失败原因（技术失败与质量失败分开显示）；
- 差异证据：相对批次基线的差异镜头数、差异类型（顺序/素材窗口/时长/视觉处理）；
- 开场证据：前 3 秒样片与首段口播的「一致 / 需确认 / 冲突」结论；
- 字幕状态：`已就绪`、`待补齐` 或 `已确认无字幕`，不得把空值渲染为 `undefined`；
- optimization 启用时追加：加权总分、达标标记（本轮不启用，不显示）。

### 2.3.1 样片质量预检与候选差异

每个候选在进入「样片效果确认」前必须生成 `sample_quality_preflight`，并把结果投影到批页。预检至少包含：

| 检查 | 规则 | 失败处理 |
|---|---|---|
| `caption_integrity` | 每条可见字幕必须是非空字符串；缺失字段显式标记 `missing`，渲染层不得直接插值空值 | 阻塞样片门，显示「字幕待补齐」 |
| `opening_alignment` | `00:00–00:03` 的主要视觉动作/构图必须与首段口播意图一致；低置信度进入人工确认，语义冲突直接阻塞 | 阻塞样片门，显示证据帧和首段口播 |
| `candidate_divergence` | 每个候选相对批次基线至少有 3 个镜头在顺序、素材窗口、时长或视觉处理上发生结构化差异；候选间不得共享同一差异指纹 | 阻塞该候选，不能只靠改标题或首句口播通过 |

共享素材池是允许的，但必须通过 `candidate_variant_plan` 记录每个候选的镜头级变体和差异原因。预检结果和证据引用进入候选 revision，不能由 UI 临时计算后丢弃。

### 2.3.2 候选差异矩阵与报告摘要

批页在评分对比卡下方增加一块“表达差异”矩阵，行/列为候选，单元格显示：变更维度数、结构差异镜头数、结构状态、视觉相似度风险和证据引用。矩阵必须把“结构完全相同”和“视觉相似度过高”分成两种结论；缺少 `candidate_variant_plan` 时显示“差异证据缺失”，不能推断为通过。

批页同时显示两个只读报告摘要：

- **运行效率**：总耗时、最慢阶段、排队/执行/人工等待、重试率、缓存命中率、总成本和三段业务周期（启动→样片、样片→可选、选择→交付）。
- **成片效果**：L1a 事实覆盖、技术 QA、VLM 维度、五项人工确认、返工次数、阻塞项和下一步建议。

摘要必须带报告时间、输入哈希状态和 `rubric_version`；事件缺失、成本不一致或 VLM 未运行时用“数据不完整/已降级”表达，禁止 UI 临时补算成 0。

### 2.3.3 报告/一致性状态的可见契约

批页消费的是批根 `batch_review.data.reports` 的只读 DTO，不从 UI 状态重新计算业务指标。两个报告的 canonical 文件固定为：

```text
projects/<batch-id>/artifacts/batch_run_report.json
projects/<batch-id>/artifacts/batch_quality_report.json
```

两个 DTO 必须包含 `report_revision`、`run_id`、`generated_at`、`semantic_sha256`、`input_hashes`、`source_refs` 和 `data_quality`。`generated_at` 只用于显示新鲜度，不参与 `semantic_sha256`；同一 `run_id + input_hashes` 重建时，报告正文和 semantic hash 必须稳定。

批页只展示以下业务字段：运行效率（总耗时、最慢阶段、人工等待、重试率、缓存命中率、成本和三段里程碑）、成片效果（硬门结论、VLM 维度、五项确认、差异风险、返工次数和推荐动作）以及数据质量（`complete`、`partial`、`degraded`、`missing` 与结构化 warning）。

`report_revision`、`aggregate_revision` 或任一候选 `child_revision` 与当前批快照不一致时，页面进入“报告待刷新”状态：保留证据查看，禁用“批量通过/进入精剪”等事实写入动作；只显示「重新拉取报告」或「回到当前快照」。事件缺口、来源 hash 缺失、成本对账不一致和 VLM 缺失必须分别显示，不能统一压成“评分较低”。

### 2.3.4 跨项目审批的用户可见状态

批级审批在 UI 上表现为一个动作，但状态必须映射 coordinator record：

| 协调状态 | 页面表达 | 可用动作 |
|---|---|---|
| `preparing` / `prepared` | 正在核对候选快照 | 关闭抽屉；不可重复提交 |
| `committing` | 正在写入 N 个候选 | 只读；显示已准备/待提交数量 |
| `committed` | 已通过 N 个候选 | 继续评分或进入选择 |
| `rejected` / `stale` | 快照过期或校验未通过 | 重新拉取并逐候选查看冲突 |
| `needs_recovery` | 需要恢复，未视为通过 | 仅查看恢复详情；禁止进入下一阶段 |
| `replayed` | 已返回原动作结果 | 不新增审批记录 |

批量审批请求必须携带 `aggregate_revision` 与每个候选的 `review_id/subject_version/subject_hash`；任一候选权限或快照不一致，整批动作在 prepare 阶段拒绝，不留下部分批准。

### 2.4 人工选择区

- 显示评分排序后的候选顺序；
- 只有样片门已完成、候选已 `evaluated` 且 `sample_quality_preflight` 通过的候选可勾选；
- 勾选 1–2 条 → 「进入终稿编辑室」按钮 → `batch_select_for_edit` 动作（写 `candidate_batch.selection` + decision_log，`select_for_edit` 校验 evaluated + 评价引用）；
- 选中前，精剪/发布相关入口不可用。

### 2.4.1 从批量工作台进入终稿编辑室

终稿编辑室不是批量生产的替代页面，而是批量样片门之后的单候选深加工页面。入口必须同时满足：

1. 批次中可继续处理的候选已完成样片门；技术失败候选保留留档，不得伪装成完成；
2. 用户已查看批级差异、开场一致性和字幕状态，并完成样片效果确认；
3. 用户选择 1–2 个候选，且每个候选都有有效的评价引用和当前 revision；
4. 系统为每个选中候选生成深链 `/p/<candidate-id>`，进入该候选的最新可用 revision，而不是新建项目或打开旧 draft。

批页仍是批级审批、对比和回退的事实入口；编辑室只负责选中候选的局部修改、最小重跑和终稿交付。若候选在进入编辑室前 revision 变化，入口显示「需要重新确认」，不得静默带入旧评价或旧定位。

### 2.4.2 Editorial Gallery 真实产物接入边界（2026-08-24）

正式入口使用 Backlot 同源页面 `/studio/<batch-id>`，默认读取 `GET /api/v2/projects/<batch-id>/editorial-gallery`；静态 mockup 只保留显式 `?fixture=1` 的视觉回归用途。真实 API 失败时必须显示错误和重试，不得自动回退到假候选、假评分或假差异结论。

首期接入只开放“查看真实中间产物 + 生成最小重跑计划”：候选抽屉展示真实媒体、九阶段 checkpoint、中间制品、批级报告、评价与人工确认；`POST .../editorial-gallery/rerun-plan` 只计算计划并固定返回 `execution_allowed=false`，不得创建 run、修改 revision 或写入项目事实。真正的 preview/promote/discard 在后续 R3 执行阶段开放。

`table-mat-batch-001` 是历史验收样本：无 `candidate_variant_plan` 时显示“差异证据缺失”，质量报告 `partial` 时保留“部分数据”，不得推断为通过。普通单视频工作台不出现该批级入口，也不增加差异化或跨项目依赖。

### 2.5 预算/并发面板

- 已花费 vs 预算上限（`candidate_batch.budget.max_cost_usd` 与各候选 `cost_usd` 汇总）；
- 当前并行候选数 vs `max_parallel`；
- 技术失败候选与剩余重试次数。
- 同一区域提供效率报告入口，但只读报告制品，不把 provider/model/runtime 放入判断层；技术细节放入候选抽屉的证据层。

### 2.6 迭代面板（仅 `optimization_policy.enabled=true` 时显示）

轮次 / best 候选 / 失败维度 / mutation 指纹 / 停止原因 / 两次确认状态。本轮（人工 review）不渲染。

### 2.7 候选九阶段与最小重跑

批页顶部的 6 相轨道是候选集合的聚合进度；候选抽屉内另行显示 9 个执行阶段：`research → proposal → script → scene_plan → assets → sample → edit → compose → publish`。评分、音轨和五项确认属于当前样片产物的质量证据，不替代阶段状态。

候选级「修改并重跑」采用意图驱动：用户选择节奏/镜头、口播/字幕、画面/素材或技术修复，系统根据候选当前阶段、revision 和 artifact 依赖计算最小路径，返回起始阶段、重跑阶段、保留阶段、成本和新 revision。候选项目不变，但每次修改创建独立的 `rerun_run` 执行记录；`candidate_id` 保持不变，旧 revision 继续作为当前可用版本，目标 revision 先以 draft 形式生成。revision 在规划期间变化时返回 `stale`，前端先补拉候选状态再重新计算路径。

### 2.7.1 重跑任务、预览门与版本回退

重跑不是把当前候选直接覆盖成“重跑中”，而是一个可取消、可审阅的运行状态机：

```text
draft_plan
  → preview_running
  → awaiting_preview_review
  → full_running
  → awaiting_final_review
  → promoted | discarded
```

`rerun_run` 至少绑定 `candidate_id`、`base_revision`、`target_revision`、`change_set`、`rerun_plan`、`preview_stop_stage`、`expectation` 和进度事件。它仍复用候选自己的九阶段执行图，只执行受影响的最小子图，不新建第二个候选项目，也不覆盖当前 revision。

确认修改后先进入预览门：节奏/镜头类默认先跑到 `compose` 生成低成本短预览；口播/字幕、画面/素材类先跑到 `sample`；技术修复只重试失败阶段。预览区必须同时显示当前版与新版本、`base → target` revision、预计质量变化、用户修改预期和将保留的内容。用户可以「接受预览，继续完整重跑」「调整修改范围」或「不满意，保留当前版」，因此长时间完整生成不会成为不可逆等待。

完整成片生成后仍停在 `awaiting_final_review`，只有用户点击「采用新版本」才提升 `target_revision` 为当前版本。技术修复只有一个受影响阶段时，修复结果直接进入同一个最终复核状态，不再重复跑 compose。用户放弃或取消时清理 draft 运行记录，恢复到 `base_revision`；下一次修改默认基于最后接受版本，不继承被放弃版本的审批结果。旧版与每次 `rerun_run` 的事件、成本和决策记录保留在历史中。

渲染引擎在 proposal 阶段从 Remotion 与 HyperFrames 中选择，并写入 `proposal_packet.production_plan.render_runtime` 和 `edit_decisions.render_runtime`。局部重跑默认沿用已锁定引擎，确保新旧版本可比；用户可以显式切换，但这属于高影响变更，工作台必须重算路径/成本、再次确认，并向 decision log 追加同一 `render_runtime_selection` subject 的修订记录。系统不得在运行失败时静默切换引擎。

### 2.8 局部修改意图的表达与定位

局部修改不从空白文本框开始，而是采用「定位 → 描述 → 复述」三步：

1. **定位**：用户先点选时间段、镜头、质量维度或失败阶段，例如「00:00–00:03 · 开头钩子」「镜头节奏」「口播字幕」。入口由当前播放器、评分项和阶段状态带入，避免用户回忆内部阶段 id。
2. **描述**：系统提供四类修改类型作为快捷分类；用户可补充一句自然语言，推荐句式为「位置 + 问题 + 目标」，例如「前 3 秒直接进入产品动作，删掉第一段铺垫」。
3. **复述**：提交前先显示摘要，把时间/镜头锚点、目标和影响范围复述给用户；用户没有改写模型草稿时标记为「系统草稿」，用户实际补充后才标记为「已理解」。若描述缺少目标或存在歧义，只追问一个最小澄清项，不让用户填写完整表单。

系统将定位锚点和自然语言描述一起写入只读 `rerun_plan`，再计算最小路径。锚点必须绑定当前 `child_revision`；revision 变化时计划失效并要求重新定位，不能把旧时间段或旧镜头静默套到新版本。

### 2.9 VLM 低分建议与用户确认范围

VLM 评分只负责发现问题和提出建议，不直接触发重跑。候选抽屉打开「修改并重跑」后，若存在低于阈值的评分维度，面板按维度展示：分数、证据定位、建议动作和对应锚点。用户勾选本次要处理的低分项，系统将建议转成可编辑的自然语言草稿；用户可以删改草稿、取消某个建议或手动扩大/缩小定位范围。

重跑计划必须同时显示两类来源：`VLM 建议范围` 与 `用户补充范围`。只有用户勾选的建议和用户输入都通过一致性检查后，确认按钮才可提交。多个建议的影响阶段取依赖闭包并集，不能只按第一条建议规划；没有低分建议时仍保留手动定位入口。

## 3. 审批与确认流（批级一键通过模式）

### 3.1 审批清单

| 时点 | 用户动作 | 载体 | 频次 |
|---|---|---|---|
| 启动前 | 批准批量模式：方向/素材池/平台时长/预算/provider/model/runtime/优化模式 | decision_log + 批页确认 | 1 |
| 每候选 script 锁 | 剧本确认 | 批页 `batch_approve_gate("script")` | 1（批级） |
| 每候选 素材创意锁 | 付费调用前素材批准 | 批页 `batch_approve_gate("assets")` | 1（批级） |
| 每候选 样片效果确认 | 五项确认 | 批页 `batch_approve_gate("sample")` | 1（批级） |
| 批级评分后 | 选 1–2 条进精剪 | 批页选择区 | 1 |
| 选中候选交付 | 成片确认 | 候选单任务页（沿用现有交付页） | 1–2 |
| （若启用自动优化） | 一次性批准 rubric/阈值/预算/自动 mutation（校准达标才可开自动门禁） | decision_log | 1 |

### 3.2 批级一键通过与单候选驳回的兼容

- `batch_approve_gate(gate, candidate_ids)`：对每个候选复用既有 `ReviewService.decide` 审批通道，**每条批准仍落在该候选自己的 review/decision_log**（审计不合并、不丢失）；
- 批页该门渲染「逐候选列表 + 一键全部通过」：用户可先展开任一候选复核，单独驳回后，一键通过只作用于剩余候选；
- 候选单任务页的 `pending_review` 保持不变——被批级驳回的候选在自家页面按原样走单任务审批。

## 4. 后端投影与动作设计（代码落点）

### 4.1 状态投影（`backlot/operator_state.py`）

- 新增 `_batch_editor(board)`：当项目 artifacts 含 `candidate_batch` 时，`project_operator_state` 走批级分支，`workspace.editor = {"type": "batch_review", "data": ...}`；
- `data` 内容：`phase`、`candidates[]`（跨项目读取各候选项目的 `evaluation_report.sample`、`sample_execution_trace`、`sample_report`，组装对比卡数据）、`budget`、`selection`、`pending_gates`（每个门列出候选清单与状态）；
- 跨项目读取走 `load_board_state(project_dir.parent / candidate_project_id)`，缺失项目/损坏制品降级为空列，不崩溃；
- `schemas/backlot/operator_state.schema.json` 注册 `batch_review` editor `$def` 与 `pending_review.kind: "batch_gate"`。

### 4.2 操作（`backlot/operator_actions.py` + `operator_routes.py`）

- `batch_select_for_edit(batch_id, candidate_ids≤2, reason)`：事务内 `lib.candidate_batch.select_for_edit` + 原子写 + decision_log（`category: "concept_selection"`）；
- `batch_approve_gate(gate∈{script,assets,sample}, candidate_ids)`：逐候选调 `ReviewService.decide(approve)`，幂等键去重，任一步失败整体回滚（事务）；
- 路由：`POST /api/v2/projects/{batch_id}/batch/select`、`POST /api/v2/projects/{batch_id}/batch/approve-gate`。

### 4.3 前端（`backlot/ui/operator/app.js` + `api.js` + `styles.css`）

- `renderBatch(container, data, {project})`：按 §2 布局渲染；评分对比卡复用 `renderEvaluationCard` 与三轨渲染；选择区与门审批按钮走 `api.js` 新端点；
- 诊断板 `board.js` 的候选卡保留（诊断视图）。

## 5. 首轮生产默认参数与流程（阶段二，驾驶舱上线后执行）

| 参数 | 默认值 |
|---|---|
| 素材池 | 沿用 v8 透明桌垫自有素材（`projects/table-mat-mix-v8/inputs/...`） |
| 候选方向 | 结果先行 / 痛点先行 / 证据链先行 / 高密度快剪 / 产品质感版 |
| 平台/时长 | 抖音 9:16 竖屏，15s |
| 预算 | 30 USD（cost_tracker 为准，candidate_batch 只做索引） |
| provider/model/runtime | 提案阶段同时评估 Remotion / HyperFrames；用户确认后锁定 `render_runtime`，局部重跑默认沿用该引擎 |
| 优化模式 | `optimization_policy.enabled=false`（纯人工 review） |

生产流程：`build_default_optimization_policy(enabled=false)` → `create_candidate_batch`（`source_media_refs` 指向素材池）→ `batch_fork.fork_candidate_projects` → 逐候选 proposal→script→scene_plan→assets→sample（并发 ≤3、技术失败按 `max_retries_per_candidate` 重试、provider 全程固定、失败候选留档）→ 全部评分后停在「人工选择」等待用户。

## 6. 分阶段实施与验收

### 阶段一：驾驶舱（本设计）

- [ ] 批页投影：批级轨道 + 候选矩阵 + 评分对比 + 选择区 + 预算面板
- [ ] `batch_approve_gate` 与 `batch_select_for_edit` 动作（事务 + 幂等 + 审计）
- [ ] 候选单任务页零回归（现有 248 个 backlot 测试全过）
- [ ] 契约/单测/UI 契约测试齐备；全量回归全绿

### 阶段二：首轮真实批量生产

- [ ] 5 个候选项目分叉完成，共享研究 + 派生证据完整（B3 门）
- [ ] 每个候选样片带真实口播/BGM/参考字幕（voice-timeline-fit 纪律）
- [ ] 全部候选 `final_qa` + `technical_validator` + `video_judge`（l3-v1.0）评分完成
- [ ] 批页可见 5 候选矩阵与评分对比，等待用户选择 1–2 条
- [ ] 失败候选完整留档；成本在预算内且可追溯

## 7. 测试与回归

- 投影：批项目 fixture（batch + 2 个候选子项目）→ `batch_review` payload 契约测试
- 动作：`batch_select_for_edit`（非法候选/超 2 条拒绝）与 `batch_approve_gate`（幂等/回滚/审计）单测
- UI：`renderBatch` 关键文案与样式契约测试（沿用 `test_operator_ui_contract.py` 模式）
- 质量预检：字幕缺失/空值、开场语义冲突、候选差异不足均阻塞样片门，并输出可定位证据；正常样片不得出现 `undefined` 字幕文本
- 候选变体：`candidate_variant_plan` 可重放、共享素材池不误判为同质化、同一差异指纹被拒绝
- 编辑室入口：未完成样片门、未评估、缺少评价引用或超过 2 个候选时拒绝进入；通过后深链到选中候选当前 revision
- 全量回归：现有 1798 例全绿 + 新增用例

## 8. 风险与边界

- **跨项目读取性能**：批页每次打开读取 N 个候选项目；先用直接读 + 只读必要制品（evaluation/trace/sample_report），后续再考虑缓存。
- **审批审计**：批级一键通过不合并审计——每条批准仍写入对应候选的 review/decision_log。
- **事务兼容**：候选项目已启用 operator generations 的，`batch_approve_gate` 必须经 `ProjectCommitStore` 事务，失败整体回滚。
- **失败候选**：只灰显留档，绝不删除；「失败候选不会成为 best」由 `record_candidate_result` 与 `select_for_edit` 双重保证。
- **自动迭代边界**：本轮 `enabled=false`，迭代面板与 mutation 能力不渲染、不执行；未来启用需先过 Gold Set release gate。

## 9. 契约落地顺序

1. 先实现批级聚合状态与事件契约，确定 `aggregate_revision`、候选 N、相位归约、事件补拉和 `batch_review` schema。
2. 再实现跨项目审批一致性契约，完成 coordinator record、prepare/commit/recovery、幂等和逐候选权限校验。
3. 只有两份契约的故障注入、stale、重放和多候选回归测试通过后，才进入批页 UI 和首轮真实批量生产。

## 10. 当前接入阻塞（2026-08-23 review）

本设计和 mockup 的视觉/交互方向已冻结，但生产接入暂不宣称完成。以下问题必须在 schema、投影和测试中闭合后，才能把 mockup fake adapter 替换为真实动作：

1. **报告快照 envelope**：`batch_run_report` 与 `batch_quality_report` 需要共同的 `batch_generation_id`、`aggregate_revision`、候选 `child_revision` 快照、必填 `report_revision`/`semantic_sha256` 和 `data_quality=missing` 语义；`generated_at` 必须排除在 semantic hash 外。
2. **事实绑定**：事件去重键必须包含 `source_project_id/candidate_id`，不能只用 `(run_id,event_seq)`；成本必须声明 batch root 预留与 child 实际扣费的 owner/去重规则。
3. **变体接入**：明确 variant-plan writer、checkpoint/revision/ref 结构和 assets/sample 前置读取；六维模型与旧五轴只做兼容映射，不得由 UI 推断。pairwise 必须以“相对 baseline 的差异 + 差异指纹唯一性”为事实，不用 shot-id 交集替代。
4. **只读投影**：聚合读取不得写 batch event 或 ensure review；事件应由事实提交后的 outbox 发布，历史回填只允许写 canonical report 文件。
5. **闭合质量门**：五项确认固定为 `creative_direction/hook/proof/pacing/readability` 且值只能为 `pass/revise/fail`；报告必须独立承载 L1a、technical QA、VLM advisory 和 hard-gate 结论。

在这些项通过前，`design-demos/editorial-gallery/index.html` 只作为可浏览高保真原型，URL 参数 `?outcome=stale|forbidden|validation_failed|needs_recovery|replayed` 用于演示一致性失败态，不调用生产 API。

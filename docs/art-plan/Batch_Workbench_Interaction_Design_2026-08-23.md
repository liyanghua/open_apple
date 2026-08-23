# 批量混剪运营工作台交互设计（2026-08-23）

> 日期：2026-08-23
> 版本：v1.0
> 状态：设计稿，待实施
> 范围：OpenMontage `cinematic-fast` 批量混剪模式的运营工作台（`/p/<project-id>`）交互设计；候选单任务工作台保留不变
> 依赖文档：`Design_Review_2026-08-22.md`（评价/批量数据层）、`Autoresearch_Video_Remix_Integration_Design_2026-08-23.md`（优化闭环）、`skills/pipelines/cinematic-fast/optimize-director.md`（批量编排 runbook）
> 必须先满足的实现契约：[`Batch_Workbench_Aggregate_State_Event_Contract_2026-08-23.md`](./Batch_Workbench_Aggregate_State_Event_Contract_2026-08-23.md)、[`Batch_Workbench_Cross_Project_Approval_Consistency_Contract_2026-08-23.md`](./Batch_Workbench_Cross_Project_Approval_Consistency_Contract_2026-08-23.md)

## 0. 背景与已确认决策

用户核心目标：**先人工 review 的批量混剪生产**，评价体系稳固后再用 autoresearch 机制自动迭代。

本轮已确认的四项决策（本设计的执行依据）：

| 决策项 | 结论 |
|---|---|
| 工作台形态 | 完整批级驾驶舱（批级轨道 + 候选矩阵 + 评分对比 + 人工选择 + 预算面板） |
| 审批密度 | 批级一键通过（每个门一次批操作，逐候选列表可展开复核、单独驳回） |
| 优化模式 | 纯人工 review：`optimization_policy.enabled=false`，不显示迭代面板、不自动 mutation |
| 首轮启动参数 | 默认值：沿用 v8 透明桌垫素材池 / 5 默认方向 / 抖音 9:16 竖屏 15s / 预算 30 USD |

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
| 人工选择 | 全部 evaluated | `selection.selected_candidate_ids` 非空 |
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
- optimization 启用时追加：加权总分、达标标记（本轮不启用，不显示）。

### 2.4 人工选择区

- 显示评分排序后的候选顺序；
- 勾选 1–2 条 → 「进入精剪」按钮 → `batch_select_for_edit` 动作（写 `candidate_batch.selection` + decision_log，`select_for_edit` 校验 evaluated + 评价引用）；
- 选中前，精剪/发布相关入口不可用。

### 2.5 预算/并发面板

- 已花费 vs 预算上限（`candidate_batch.budget.max_cost_usd` 与各候选 `cost_usd` 汇总）；
- 当前并行候选数 vs `max_parallel`；
- 技术失败候选与剩余重试次数。

### 2.6 迭代面板（仅 `optimization_policy.enabled=true` 时显示）

轮次 / best 候选 / 失败维度 / mutation 指纹 / 停止原因 / 两次确认状态。本轮（人工 review）不渲染。

### 2.7 候选九阶段与最小重跑

批页顶部的 6 相轨道是候选集合的聚合进度；候选抽屉内另行显示 9 个执行阶段：`research → proposal → script → scene_plan → assets → sample → edit → compose → publish`。评分、音轨和五项确认属于当前样片产物的质量证据，不替代阶段状态。

候选级「修改并重跑」采用意图驱动：用户选择节奏/镜头、口播/字幕、画面/素材或技术修复，系统根据候选当前阶段、revision 和 artifact 依赖计算最小路径，返回起始阶段、重跑阶段、保留阶段、成本和新 revision。用户确认后才创建重跑任务；重跑期间候选阶段回退为 `in_progress`，旧版本审批失效但历史保留。revision 在规划期间变化时返回 `stale`，前端先补拉候选状态再重新计算路径。

### 2.8 局部修改意图的表达与定位

局部修改不从空白文本框开始，而是采用「定位 → 描述 → 复述」三步：

1. **定位**：用户先点选时间段、镜头、质量维度或失败阶段，例如「00:00–00:03 · 开头钩子」「镜头节奏」「口播字幕」。入口由当前播放器、评分项和阶段状态带入，避免用户回忆内部阶段 id。
2. **描述**：系统提供四类修改类型作为快捷分类；用户可补充一句自然语言，推荐句式为「位置 + 问题 + 目标」，例如「前 3 秒直接进入产品动作，删掉第一段铺垫」。
3. **复述**：提交前先显示「已理解」摘要，把时间/镜头锚点、目标和影响范围复述给用户；若描述缺少目标或存在歧义，只追问一个最小澄清项，不让用户填写完整表单。

系统将定位锚点和自然语言描述一起写入只读 `rerun_plan`，再计算最小路径。锚点必须绑定当前 `child_revision`；revision 变化时计划失效并要求重新定位，不能把旧时间段或旧镜头静默套到新版本。

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
| provider/model/runtime | 沿用 v8：豆包 TTS（seed-tts-2.0）+ pixabay BGM + Remotion |
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

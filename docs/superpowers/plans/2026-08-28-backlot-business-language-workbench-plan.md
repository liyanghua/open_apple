# 视频审批工作台业务语言与批单串联实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有批量驾驶舱和单条审批台收敛为一条真实生产主线，用一线业务中文呈现视频生成、人审、产物和批量提交。

**Architecture:** 保留现有批次根项目与候选子项目模型。批量总览只读聚合批次和候选快照；单条复核继续读取候选项目事实；两者通过导航上下文和共享审批 API 串联。三个人审门仍是脚本、制作准备、样片，批量操作分为“批量确认当前门”和“选择 1–2 条进入精剪”两步；本轮不实现编辑工作室。

**Tech Stack:** Python 3.10+, FastAPI, JSON Schema, 原生 JavaScript/CSS, pytest, 现有 Backlot operator API 和浏览器 smoke 测试。

**Reference:** `docs/superpowers/specs/2026-08-28-backlot-business-language-workbench-design.md`

> **状态更新（2026-08-31）**：Phase 0–3 的审批事实、批量一致性和业务字段已完成；Phase 4–5 的连接契约、文案扫描和前端语法检查已完成，视觉验收按约定由业务方手动执行。单条审批壳、统一浏览状态和九阶段适配器已接入，但阶段产物仍有字段取错、关键信息缺失、重复和工程字段回流问题，不能标记为最终完成。产物整改转入专项计划：`docs/superpowers/plans/2026-08-31-single-review-artifact-completeness.md`。

---

## Chunk 1: 业务文案与状态投影

### Task 1: 固化九步业务语言映射

**Files:**
- Modify: `backlot/operator_language.py`
- Modify: `backlot/operator_state.py`
- Modify: `schemas/backlot/operator_state.schema.json`
- Test: `tests/backlot/test_operator_state.py`
- Test: `tests/backlot/test_operator_ui_contract.py`

- [ ] **Step 1: 写失败测试，锁定九步业务名称和状态文案。**

断言 `research` 到 `publish` 映射为“了解任务、看创意方案、确认脚本、看分镜、确认制作准备、查看样片、完成剪辑、检查成片、确认交付”，并断言页面不输出内部枚举给一线用户。

- [ ] **Step 2: 运行测试确认失败。**

Run: `pytest -q tests/backlot/test_operator_state.py tests/backlot/test_operator_ui_contract.py`

Expected: FAIL，当前映射仍包含“参考解析与素材体检”“剧本生成”等旧文案，且批量页文案未覆盖返回上下文。

- [ ] **Step 3: 实现最小映射改动。**

在 `operator_language.py` 集中维护页面标签、状态、确认门和产物标签；`operator_state.py` 只引用映射，不在投影函数内拼装英文阶段名。保持内部 stage id、schema 字段和事件字段不变。

- [ ] **Step 4: 运行测试确认通过。**

Run: `pytest -q tests/backlot/test_operator_state.py tests/backlot/test_operator_ui_contract.py`

Expected: PASS。

- [ ] **Step 5: 提交。**

```bash
git add backlot/operator_language.py backlot/operator_state.py schemas/backlot/operator_state.schema.json tests/backlot/test_operator_state.py tests/backlot/test_operator_ui_contract.py
git commit -m "feat(backlot): align operator language with business workflow"
```

### Task 2: 为候选投影补齐“当前产物”和返回上下文

**Files:**
- Modify: `backlot/batch_state.py`
- Modify: `backlot/operator_state.py`
- Modify: `schemas/backlot/operator_state.schema.json`
- Test: `tests/backlot/test_batch_workbench.py`
- Test: `tests/backlot/test_batch_reporting_projection.py`

- [ ] **Step 1: 写失败测试。**

覆盖有样片、等待脚本、等待制作准备、技术失败和缺失候选五种 fixture，断言每个候选都有 `current_step`、`current_artifact`、`review_status`、`preview_url`、`stage_states` 和 `links.project_page`；批量数据有 `batch_context`，包含 `batch_id`、返回地址和 `aggregate_revision`。

- [ ] **Step 2: 运行测试确认失败。**

Run: `pytest -q tests/backlot/test_batch_workbench.py tests/backlot/test_batch_reporting_projection.py`

Expected: FAIL，当前候选只有技术字段和项目链接，没有可直接渲染的当前产物/业务状态字段。

- [ ] **Step 3: 实现只读派生。**

在 `batch_state.py` 根据现有 checkpoint、sample report、evaluation 和 pending review 派生业务字段；增加 `subject_hash`（当前或最近一次可审内容快照）、`workflow_revision`（审批/checkpoint 版本）、`current_step`、`current_artifact`、`review_status`、`artifact_health`、`selection_eligible` 和 `selection_block_reason`。缺失或损坏时返回明确状态，不在读取函数内创建 review、写事件或修改 checkpoint。`operator_state.py` 将批级上下文投影到 operator state，并保持 revision 计算稳定；批展示 schema 升为 1.1，旧客户端只读兼容。

- [ ] **Step 4: 更新 schema 并运行测试。**

Run: `pytest -q tests/backlot/test_batch_workbench.py tests/backlot/test_batch_reporting_projection.py`

Expected: PASS。

- [ ] **Step 5: 提交。**

```bash
git add backlot/batch_state.py backlot/operator_state.py schemas/backlot/operator_state.schema.json tests/backlot/test_batch_workbench.py tests/backlot/test_batch_reporting_projection.py
git commit -m "feat(backlot): project business-ready candidate artifacts"
```

## Chunk 2: 批量总览与单条复核串联

### Task 3: 增加批量来源和返回入口

**Files:**
- Modify: `backlot/ui/operator.html`
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/store.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_ui_contract.py`
- Create: `tests/backlot/test_operator_navigation.py`
- Modify: `backlot/ui/operator/store.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_ui_contract.py`
- Test: `tests/backlot/test_operator_navigation.py` (create if absent)

- [ ] **Step 1: 写失败测试。**

断言批量候选入口带 `from=batch` 和 `batch_id`；单条页面出现“返回批量总览”；返回时恢复批次地址、候选选择和滚动位置；没有批次来源的普通单条项目不显示返回入口；快速查看抽屉只能读，不能提交审批。

- [ ] **Step 2: 运行测试确认失败。**

Run: `pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_navigation.py`

Expected: FAIL，当前只生成 `/p/<candidate-id>` 链接，未携带批次上下文，也没有返回状态。

- [ ] **Step 3: 实现导航上下文。**

在 store 中解析 URL 查询参数并保存 `batch_id`、`return_url`、候选 ID 和滚动位置；在批量卡片和复核抽屉分别提供“快速查看”和“打开单条复核”；快速查看复用只读产物组件，不渲染通过/退回/选择按钮；单条页面只显示“返回批量总览”，不复制批量审批控件。

- [ ] **Step 4: 增加状态变化处理。**

返回批量前重新拉取 operator state；若候选 `subject_hash` 变化或候选资格变化，清除受影响选择并显示“这条视频有新版本，请重新看一遍”；仅审批/checkpoint 的 `workflow_revision` 变化不得清除选择。`aggregate_revision` 变化时按候选 hash 和资格逐项对账。浏览器返回、关闭抽屉和 Escape 都不得丢失上下文。

- [ ] **Step 5: 运行测试并提交。**

Run: `pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_navigation.py`

Expected: PASS。

```bash
git add backlot/ui/operator.html backlot/ui/operator/app.js backlot/ui/operator/store.js backlot/ui/operator/styles.css tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_navigation.py
git commit -m "feat(backlot): connect batch and single review views"
```

### Task 4: 重排单条复核的产物呈现

**Files:**
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/editors.js`
- Modify: `backlot/ui/operator/styles.css`
- Modify: `backlot/ui/operator/language.js`
- Test: `tests/backlot/test_operator_ui_contract.py`
- Test: `tests/backlot/test_operator_single_review.py` (create if absent)

- [ ] **Step 1: 写失败测试。**

检查单条复核存在“视频播放器、当前步骤、制作脚本/镜头安排/制作清单/样片效果、通过这一条、退回并说明原因、制作记录”；同时断言不存在品牌词、内部英文阶段名、文件路径和 JSON 编辑入口。

- [ ] **Step 2: 运行测试确认失败。**

Run: `pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_single_review.py`

Expected: FAIL，当前单条页面仍按编辑器类型展开，批量来源和业务产物顺序不完整。

- [ ] **Step 3: 实现只读复核面板。**

将当前 `renderBatch` 和样片/交付渲染拆为可复用的 `renderCandidateSummary`、`renderCandidateProgress`、`renderCandidateArtifacts`、`renderReviewActions`；技术字段放入折叠区。保留已有播放器、评价卡、音轨和五项样片确认逻辑，不增加编辑动作。

- [ ] **Step 4: 加入失败和缺失状态。**

真实媒体缺失显示“样片未生成”，技术失败显示原因和“查看处理记录”，报告不完整显示“重新拉取最新结果”；不得用假图、空白卡或颜色单独表达状态。

- [ ] **Step 5: 运行测试并提交。**

Run: `pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_single_review.py`

Expected: PASS。

```bash
git add backlot/ui/operator/app.js backlot/ui/operator/editors.js backlot/ui/operator/styles.css backlot/ui/operator/language.js tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_single_review.py
git commit -m "feat(backlot): present single review artifacts in business order"
```

## Chunk 3: 批量两步审批和一致性反馈

### Task 5: 把批量门审批改成业务动作

**Files:**
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/api.js`
- Modify: `backlot/batch_actions.py`
- Modify: `backlot/batch_state.py`
- Modify: `backlot/project_commit.py`
- Modify: `backlot/operator_routes.py`
- Test: `tests/backlot/test_batch_actions.py`
- Test: `tests/backlot/test_project_commit.py`
- Test: `tests/backlot/test_operator_ui_contract.py`

- [ ] **Step 1: 写失败测试。**

覆盖“批量通过已勾选的脚本/制作准备/样片”、单条通过、混合阶段、退回、样片五项确认不完整、权限不足、revision 过期、重复提交和中途故障恢复。断言批量失败不留下部分审批，成功时每个候选有独立 review/decision log；失败响应包含 participant 错误、当前版本和可重试标记；同幂等键重放不新增记录。

- [ ] **Step 2: 运行测试确认失败。**

Run: `pytest -q tests/backlot/test_batch_actions.py tests/backlot/test_operator_ui_contract.py`

Expected: FAIL，现有按钮和错误文案仍以技术动作表达，测试需要固定业务结果和协调状态。

- [ ] **Step 3: 固化 prepare/commit 文案和状态。**

保留现有 `aggregate_revision`、participants、幂等键和 recovery 合同；验证并补齐 staged generation、稳定锁顺序、commit marker、批动作 `visibility_fence`、fence 放行前的 outbox 暂缓、CAS 补偿回滚和 `replayed/idempotency_conflict` 响应。增加故障注入测试：逐个 pointer 切换期间所有读取仍见旧事实，全部 marker 齐全后整批可见；补偿只修改仍匹配 coordinator marker 的 pointer，不能覆盖并发新事实。主按钮按“脚本 → 制作准备 → 样片”的固定顺序选择最早待确认门，错误映射为“结果有更新，请重新拉取”“没有审批权限”“有一项确认未通过”“需要恢复这次提交”。

- [ ] **Step 4: 确认批量两步边界。**

第一步只处理当前门；第二步只在所有存活候选完成评分或进入终态、至少一条候选 `selection_eligible=true` 且报告完整时显示选择托盘。选择动作仍限制 1–2 条并提交 evaluation snapshot/hash，写入 `concept_selection`，不启动编辑器。退回/失败/缺失/损坏/排除候选不阻塞其他候选。

- [ ] **Step 5: 运行测试并提交。**

Run: `pytest -q tests/backlot/test_batch_actions.py tests/backlot/test_operator_ui_contract.py`

Expected: PASS。

```bash
git add backlot/ui/operator/app.js backlot/ui/operator/api.js backlot/batch_actions.py backlot/batch_state.py backlot/project_commit.py backlot/operator_routes.py tests/backlot/test_batch_actions.py tests/backlot/test_project_commit.py tests/backlot/test_operator_ui_contract.py
git commit -m "feat(backlot): clarify batch approval actions and outcomes"
```

### Task 6: 补齐交互契约与手动验收准备

**Files:**
- Modify: `tests/backlot/test_operator_ui_contract.py`
- Modify: `tests/backlot/test_business_language_contract.py`
- Modify: `design-demos/editorial-gallery/index.html` only if the fixture is kept as a visual regression page
- Modify: `backlot/ui/operator/styles.css`

- [ ] **Step 1: 写静态交互契约。**

覆盖批量首屏、只读候选抽屉、进入单条、返回批量、批量门确认、选择托盘、混合阶段、退回/失败候选、无合格候选和报告降级。服务端 fixture 还必须覆盖批次/候选不匹配、候选删除或归档、预览 URL 失效、媒体播放失败、状态刷新超时和加载后权限撤销；测试断言动作被禁用或服务端拒绝，并出现规格中的中文恢复入口。

- [ ] **Step 2: 运行契约测试确认缺口。**

Run: `pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_business_language_contract.py`

Expected: FAIL，直到页面具备稳定的 data attributes、返回上下文和业务文案。

- [ ] **Step 3: 增加稳定选择器和响应式样式。**

为批次来源、返回按钮、候选卡、当前产物、主动作、选择托盘和错误提示添加稳定 `data-testid`；检查 1180px、900px、390px 三个宽度无横向溢出，底部操作条不遮挡内容。

- [ ] **Step 4: 运行契约测试、完成三档手动检查并提交。**

Run: `pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_business_language_contract.py`

Expected: PASS。随后由业务方在 1180px、900px、390px 手动检查桌面/平板/移动布局，确认没有品牌词、内部英文词、横向溢出或遮挡。

```bash
git add tests/backlot/test_operator_ui_contract.py tests/backlot/test_business_language_contract.py backlot/ui/operator/styles.css design-demos/editorial-gallery/index.html
git commit -m "test(backlot): prepare connected workbench manual acceptance"
```

## Chunk 4: 回归与上线门槛

### Task 7: 全量契约回归和文案扫描

**Files:**
- Modify: `tests/backlot/test_operator_ui_contract.py`
- Create: `tests/backlot/test_business_language_contract.py`
- Modify: `docs/reports/2026-08-26-analysis-readonly-workbench-run-report.md`，记录实施结果

- [ ] **Step 1: 写文案扫描测试。**

扫描用户可见 HTML/JS 文案，禁止 `OPENMONTAGE`、`OpenMontage`、`Editorial Gallery`、`runtime`、`revision`、`creative_lock`、`script_lock`、`undefined` 等内部词直接出现在一线页面；允许 API 字段、schema 和测试注释使用内部名。扫描同时覆盖直接访问、批次/候选不匹配、媒体失效、刷新超时和权限变化提示。

- [ ] **Step 2: 运行扫描确认现状缺口。**

Run: `pytest -q tests/backlot/test_business_language_contract.py`

Expected: FAIL，列出仍需替换的页面文案和 fixture 文案。

- [ ] **Step 3: 清理用户可见词并保留技术折叠区。**

把页面主文案改为规格中的业务语言；技术字段只在“制作记录”中以中文标签呈现。同步更新 Demo 的 title、brand、按钮和提示，避免用户看到产品品牌词。

- [ ] **Step 4: 执行回归。**

Run: `pytest -q tests/backlot tests/lib`

Expected: PASS。

Run: `node --check backlot/ui/operator/app.js && node --check backlot/ui/operator/api.js && node --check backlot/ui/operator/store.js`

Expected: PASS。

- [ ] **Step 5: 记录验收并提交。**

```bash
git add tests/backlot/test_operator_ui_contract.py tests/backlot/test_business_language_contract.py docs/reports/2026-08-26-analysis-readonly-workbench-run-report.md
git commit -m "docs(backlot): record business-language workbench rollout"
```

## 实施顺序和停止条件

1. 先完成 Task 1–2，确保状态和产物有稳定业务字段；
2. 再完成 Task 3–4，建立批量与单条的可逆导航；
3. 完成 Task 5 后才能开放批量确认和批量选择；
4. Task 6–7 通过后，才把真实批量页面作为一线审批入口；
5. 任一一致性测试失败时，保留只读查看和重新拉取，不显示“已通过”；
6. 编辑工作室、修改并重跑和完整交付确认另立设计与实施计划，不在本计划中临时扩展。

## 最终验收清单

- [ ] 一线人员无需知道内部阶段名即可完成三次确认。
- [ ] 批量总览 → 单条复核 → 返回批量的上下文保持稳定。
- [ ] 批量审批两步可解释：当前门确认、选择 1–2 条进入精剪。
- [ ] 单条通过和批量通过写入同一套审批事实，不重复、不丢审计。
- [ ] 失败、缺失、过期和降级状态均有中文原因和下一步。
- [ ] 页面不出现 OPENMONTAGE 等品牌词或内部技术词。
- [ ] 既有批量、单条、审批一致性和前端构建回归全部通过。

---

## 修订附录（2026-08-28 评审定案，覆盖/修正正文对应任务）

### A1. 五个问题的定案

| 问题 | 定案 |
|---|---|
| `subject_hash` | **不采用五类拼接总哈希**。复用现有 review 规范 hash：当前有待确认内容→pending review 的 hash；无待确认→最近一次**已决** review 的 hash；尚无可审内容→`null`+`not_ready`。脚本/制作准备/样片各自绑定对应门的内容（现 `operator_reviews.py:188` 的机制继续沿用），不新造算法。 |
| `evaluation_hash` | = `evaluation_report.artifact_sha256`（报告本身的 hash，不与报告内被评媒体的 subject_hash 混用）。批量选择时服务端**重新读取报告**并校验 artifact_sha256 / scope / 候选绑定 / 报告完整性；旧报告缺字段→只读展示，不得参与写操作。 |
| `batch_actions.py` | **不重构，补强**。现有已有 coordinator、prepare 校验、参与者状态、幂等重放、commit marker、needs_recovery（事务/恢复测试 19 passed）。缺口=每个候选**单独提交 pointer + 立即 drain outbox**（`project_commit.py:350`），第二候选提交前读取方可见第一候选已通过。→ 新增 **visibility_fence**：fence 未放行前，批量投影与候选单条页**读取旧事实**；全部 marker 齐全后才切 fence、统一放行 outbox。 |
| 单条页编辑控件 | **保留代码不删除**；审批视图中不渲染、不授权。`renderTypedEditor`/draft/revision/restore 留后续编辑工作室。审批页使用**独立 approval/只读模式**（不能只依赖 `canEdit` 权限判断——有编辑权限用户仍会看到修改控件）。 |
| 浏览器验收 | **最终定案见 A4**：本轮不引入 Playwright 依赖；保留静态契约和 `data-testid`，由业务方按三档宽度手动验收。 |

### A2. 两个落库前的既有差异（纳入 Task1/Task2 前置）

1. **样片五项最后一项**：规格文案「字幕」，代码内部最后一项是 `readability`（`operator_reviews.py:27`）。兼容映射：UI 显示「字幕」，内部暂用旧枚举，待后续正式改字段；文档与契约测试锁定「五项=方向/开场/证明/节奏/字幕」，代码侧 `readability` 作为兼容别名。
2. **`load_operator_state()` 的写副作用**：读取时会 `ensure_*_review_for_checkpoint()`（`operator_state.py:1992`）可能创建 review——与「投影只读」冲突。→ 把补建动作**限制在明确的迁移/写路径**（批量事实准备期/显式数据修复脚本），读取路径不落任何 write。

### A3. 修订后执行顺序（覆盖原文「实施顺序和停止条件」）

```
Phase 0  契约审计（哈希与五项）：subject_hash 沿用 review 规范 的确认性审计
        + evaluation_hash 读取/校验路径审计 + readability↔字幕 兼容映射落文档与契约测试
Phase 1  业务语言映射 + 候选投影业务字段（schema 1.1；读取路径去写副作用）
Phase 2  visibility_fence + 审批独副本模式（单条只读+通过/退回；不渲染编辑控件）
        + 批量投影/单条页在 fence 未放行前读旧事实 + outbox 统一放行
Phase 3  批量两步（确认当前门 → 选择 1–2 条）+ 原子协调补强测试（故障注入/幂等/并发）
Phase 4  静态交互契约 + 稳定 data-testid + 1180/900/390 三档业务方手动验收
Phase 5  全量回归 + 文案扫描 + 报告 §6.6 记录
```

停止条件不变：任一一致性测试失败→保留只读+重新拉取，不显示「已通过」；Phase 3 前不开放批量写；编辑工作室另立计划。

### A4. 验收方式调整（2026-08-28）

根据本轮实施确认，Phase 4 不再以 Playwright 自动化作为完成门。本轮保留稳定 `data-testid`、导航/异常状态静态契约和响应式 CSS，由业务方在实现完成后按 1180px、900px、390px 三档手动验收；依赖安装、Chromium 下载和浏览器测试文件不进入本轮提交。Phase 5 的后端回归、文案扫描与前端语法检查仍为必需门。

### A5. 实施状态与剩余工作（2026-08-28）

| 阶段 | 状态 | 证据/说明 |
|---|---|---|
| Phase 0 契约审计 | ✅ 完成 | `subject_hash` 沿用 review hash；`evaluation_hash` 重读校验；五项确认映射已锁定 |
| Phase 1 业务投影 | ✅ 完成 | 九步业务文案、候选业务字段、schema 1.1、读取纯净性已落地 |
| Phase 2 一致性与审批模式 | ✅ 完成 | visibility fence、统一 outbox 放行、审批只读模式已落地 |
| Phase 3 批量两步 | ✅ 完成 | participants + evaluation hash 重读；prepare 只校验不创建 |
| Phase 4 连接与异常契约 | ✅ 完成 | 批单导航、快速查看、异常提示、`data-testid` 和响应式规则已落地；改为手动验收 |
| Phase 5 回归与文案扫描 | ✅ 完成 | `tests/backlot` 通过，前端模块语法检查通过 |
| 单条视觉升级 | ⏳ 基础壳已接入，产物整改中 | 统一浏览状态、审批三栏和材料入口已落地；九阶段产物完整性见 A7 |

“Phase 0–5 完成”不等于“单条视觉升级完成”。专项计划完成前，不能把当前真实单条页描述为已达到原型设计。

### A6. 单条视觉升级状态更新（2026-08-30）

专项计划已完成 Task 1–7 的基础实现：单条审批入口、统一浏览状态、九阶段材料适配入口、审批三栏、只读确认和异常恢复均已接入；但本次阶段产物回访发现“适配器已接入”不等于“老工作台关键产物已完整迁移”。三档视觉走查必须等待产物完整性专项完成后执行，不能仅凭基础壳已渲染关闭专项计划。

### A7. 九阶段产物完整性整改（2026-08-31）

本次回访确认的剩余工作不改变审批事实和批量协议，专门补齐展示层与只读投影：

| 项目 | 当前状态 | 后续动作 |
|---|---|---|
| 统一材料契约 | ⬜ 命名存在漂移，阶段 payload 仍有 fallback | 统一材料 ID，锁定必备业务字段 |
| 阶段级适配器 | ⬜ proposal/script/scene_plan/assets/sample/compose/publish 尚不完整 | 按阶段增加 compact adapter，修复字段语义和媒体动作 |
| 阶段详情渲染 | ⬜ 仍以通用递归渲染为主 | 增加九类只读业务阅读器，通用 renderer 只做 fallback |
| 业务语言与去重 | ⬜ 脚本、字幕、口播存在重复和工程字段风险 | 增加重复内容及工程字段契约测试 |
| 手动验收 | ⬜ 暂缓 | 产物完整性测试通过后，再执行 1180/900/390 三档走查 |

执行计划：`docs/superpowers/plans/2026-08-31-single-review-artifact-completeness.md`。在该计划完成前，主计划的“最终验收”保持未完成。

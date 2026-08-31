# 单条视频审批工作台视觉升级实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将真实单条视频页面从旧的项目进度详情页升级为原型中的审批阅读工作台，让一线人员围绕“现在看什么、判断什么、确认后发生什么”完成一次复核。

**Architecture:** 保留 `/p/<project-id>` 路由、现有 operator state、`subject_hash`/`workflow_revision` 和审批 API。新增单条复核专用渲染壳：`workspace.view_mode=approval`、存在 `pending_review`，或页面带合法批次导航上下文时均进入新壳；因此从批量进入的已完成候选也不会退回旧项目详情页。是否展示编辑器不再由 `canEdit` 推断。页面只读展示候选事实，单条通过/退回继续写入现有 review 服务；批量总览仍是横向比较和统一提交入口。

**Tech Stack:** 原生 HTML、JavaScript modules、CSS、现有 Backlot operator API、pytest 静态契约测试；不新增浏览器自动化依赖，完成后由业务方手动验收。

> **实施状态（2026-08-31）**：Task 1–7 的基础代码与契约测试已完成。单条审批页现由统一浏览状态和九阶段产物适配入口驱动，阶段/材料切换、历史只读、审批门权限、异常提示与 URL 恢复已接入；未引入浏览器自动化。但阶段产物回访发现 proposal/script/scene_plan/assets/sample/compose/publish 仍存在字段取错、关键产物缺失、重复展示和工程字段回流风险，Task 8（三档视觉和主线走查）必须等待产物完整性专项完成后执行。专项计划：`docs/superpowers/plans/2026-08-31-single-review-artifact-completeness.md`。

**References:**

- 原型：`.superpowers/brainstorm/49441-1787886628/actual-mainline-review.html`
- 业务规范：`docs/superpowers/specs/2026-08-28-backlot-business-language-workbench-design.md`
- 前置实施计划：`docs/superpowers/plans/2026-08-28-backlot-business-language-workbench-plan.md`
- 产物完整性专项：`docs/superpowers/plans/2026-08-31-single-review-artifact-completeness.md`

---

## 现状与设计决定

当前页面仍由 `backlot/ui/operator.html` 的固定三栏壳渲染：左侧九步导航、中间阶段内容、右侧“当前需要处理”。`backlot/ui/operator/app.js` 还会根据阶段渲染编辑器、交付编辑、快速决策和技术评价。数据与审批契约已经完成，本计划只重排展示层和动作入口。

原型要求的单条首屏顺序如下：

```text
批次/任务上下文 + 当前状态
  ↓
候选标题 + 当前确认说明
  ↓
轻量九步进度（3 个人审门高亮）
  ↓
本次确认材料 | 视频与说明 | 五项确认与主动作
  ↓
确认后会怎样 / 退回后会怎样
  ↓
制作记录（默认收起）
```

不改动的边界：不新增编辑器、不实现修改并重跑、不改变批量 coordinator、不复制单条审批事实、不在本轮开放编辑工作室。

## Chunk 1: 审批视图入口与业务语言

### Task 1: 增加单条审批专用渲染入口

**Files:**
- Modify: `backlot/ui/operator.html`
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/store.js`
- Test: `tests/backlot/test_operator_ui_contract.py`
- Create: `tests/backlot/test_operator_single_review.py`

- [ ] **Step 1: 写失败测试，锁定审批视图入口。**

断言带 `pending_review`、`workspace.view_mode=approval` 或合法 `from=batch&batch_id=` 上下文的单条项目渲染新复核工作台；其中必须覆盖“从批量进入、候选已完成”的当前真实场景。普通直接访问项目仍可只读查看。复核视图不得出现 `renderTypedEditor`、草稿、恢复版本、暂存修改或影响预览入口。

- [ ] **Step 2: 运行测试确认当前差距。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_single_review.py`

Expected: FAIL，当前页面仍使用固定 `stage-panel/workspace-panel/next-panel` 壳，审批内容未成为独立视图。

- [ ] **Step 3: 实现最小渲染分流。**

在 `app.js` 增加 `renderApprovalWorkbench(container, project, snapshot)`，由 `render()` 在审批模式优先调用；保留现有阶段编辑渲染作为后续编辑室路径。审批模式只接收候选事实、当前门、预览媒体、五项确认和审批动作。

- [ ] **Step 4: 运行测试确认通过。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_single_review.py`

Expected: PASS。

- [ ] **Step 5: 提交。**

```bash
git add backlot/ui/operator.html backlot/ui/operator/app.js backlot/ui/operator/store.js tests/backlot/test_operator_ui_contract.py tests/backlot/test_operator_single_review.py
git commit -m "feat(backlot): add approval workbench render mode"
```

### Task 2: 收敛前端业务语言

**Files:**
- Modify: `backlot/ui/operator/language.js`
- Modify: `backlot/ui/operator/app.js`
- Test: `tests/backlot/test_business_language_contract.py`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] **Step 1: 写失败测试。**

锁定原型中的业务标题和动作：`商品视频制作工作台`、`当前需要你确认`、`本次确认材料`、`请看样片，并确认 5 件事`、`退回修改`、`确认通过，继续制作`、`查看制作记录`。同时禁止主界面出现 `result_first`、`judge`、`L1a`、`VLM advisory`、`runtime`、`revision`、文件路径和 JSON 编辑入口。

- [ ] **Step 2: 实现集中映射。**

在 `language.js` 增加九步显示名、三个人审门标题、五项确认标题、状态和恢复提示。`app.js` 只消费映射，不直接拼接内部阶段名；技术字段仅可进入“制作记录”折叠区。

- [ ] **Step 3: 运行测试。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_business_language_contract.py tests/backlot/test_operator_single_review.py`

Expected: PASS。

- [ ] **Step 4: 提交。**

```bash
git add backlot/ui/operator/language.js backlot/ui/operator/app.js tests/backlot/test_business_language_contract.py tests/backlot/test_operator_single_review.py
git commit -m "feat(backlot): align single review copy with prototype"
```

## Chunk 2: 原型信息架构与视觉壳

### Task 3: 重做顶部上下文和九步进度

**Files:**
- Modify: `backlot/ui/operator.html`
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] **Step 1: 写失败测试。**

断言首屏出现批次/任务上下文、候选标题、当前确认说明、历史版本和查看全部材料入口；九步进度是横向轻量 rail，只有脚本/制作准备/样片三个人审门使用高强调状态，不能以左侧九步永久导航占据主布局。

- [ ] **Step 2: 实现顶部和进度 rail。**

把 `project-header` 改为审批上下文头，移除项目进度/效率承诺作为首屏主标题；增加 `approval-topbar`、`approval-hero`、`approval-rail` 结构。阶段仍从 `project.stages` 来，状态和顺序不从 UI 猜测。

- [ ] **Step 3: 加入批次返回。**

沿用已有 `return-to-batch` 和 `store.parseBatchContext()`，在顶部固定展示“返回批量总览”；无 `from=batch` 时不渲染该入口。

- [ ] **Step 4: 运行测试并提交。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_single_review.py tests/backlot/test_operator_ui_contract.py`

Expected: PASS。

```bash
git add backlot/ui/operator.html backlot/ui/operator/app.js backlot/ui/operator/styles.css tests/backlot/test_operator_single_review.py
git commit -m "feat(backlot): add prototype approval header and progress rail"
```

### Task 4: 实现审批三栏布局和视觉层级

**Files:**
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] **Step 1: 写失败测试。**

锁定稳定结构：`approval-materials`、`approval-main`、`approval-confirmation`、`approval-activity`；媒体容器有稳定宽高比，确认面板不被技术评价卡挤出首屏。

- [ ] **Step 2: 实现视觉壳。**

复用批量原型的绿色通过、赭色重点、珊瑚风险语义；单条页按最终原型使用深色中性工作台、浅色正文和高对比视频区域，卡片圆角不超过 8px。不要把批量页的暖浅底直接套到单条页，也不要新增渐变、品牌标识或紫色霓虹装饰。

- [ ] **Step 3: 实现响应式断点。**

桌面使用材料/主内容/确认三栏；900px 收为主内容加确认区；390px 改为单列，确认动作固定在内容之后并预留底部空间。所有按钮、标题和材料说明允许换行，不出现横向滚动。

- [ ] **Step 4: 运行测试并提交。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_single_review.py`

Expected: PASS。

```bash
git add backlot/ui/operator/app.js backlot/ui/operator/styles.css tests/backlot/test_operator_single_review.py
git commit -m "feat(backlot): style single review as editorial approval workspace"
```

## Chunk 3: 产物、确认和异常状态

### Task 5: 按“看什么 / 判断什么 / 之后发生什么”重排产物

**Files:**
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] **Step 1: 写失败测试。**

断言样片门按以下顺序出现：样片播放器、镜头对照、字幕和口播、声音效果、系统检查、系统建议、制作依据；存在“画面和声音对照”时间线以及“确认通过后/退回修改后”两张流程说明。

- [ ] **Step 2: 实现只读产物卡。**

从现有 `sample_review`、`delivery_review` 和候选投影复用媒体、音轨、评价和报告数据；统一实现 `renderApprovalMaterials`、`renderApprovalMedia`、`renderApprovalOutcome`。技术诊断、成本、模型、哈希和路径进入 `<details>`“制作记录”。

- [ ] **Step 3: 处理不同当前门。**

脚本门显示制作脚本和确认文案；制作准备门显示生成清单；样片门显示播放器和五项确认；已完成候选显示成片和只读检查，不强行展示样片审批动作。

- [ ] **Step 4: 运行测试并提交。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_single_review.py tests/backlot/test_business_language_contract.py`

Expected: PASS。

```bash
git add backlot/ui/operator/app.js backlot/ui/operator/styles.css tests/backlot/test_operator_single_review.py tests/backlot/test_business_language_contract.py
git commit -m "feat(backlot): organize single review artifacts by decision flow"
```

### Task 6: 固化五项确认和单条审批动作

**Files:**
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/api.js` only if action payload adaptation is needed
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`
- Test: `tests/backlot/test_operator_actions.py`

- [ ] **Step 1: 写失败测试。**

锁定五项显示为“创意方向、开头、证明、节奏、字幕”，值显示为“通过 / 需要修改 / 不通过”；未全通过时主确认按钮不可提交。审批模式只出现“退回修改”和“确认通过，继续制作”。

- [ ] **Step 2: 复用现有审批 API。**

调用 `decideReview()` 写入 `review_id + subject_hash + subject_version + effect_confirmations`；退回时收集一线说明和结构化问题标签；成功后刷新当前候选状态，不直接修改批量投影。

- [ ] **Step 3: 处理并发和权限结果。**

将 `stale` 映射为“结果有更新，请重新拉取”，`forbidden` 映射为“没有审批权限”，`validation_failed` 映射为“有一项确认未通过”；提交失败时不显示“已通过”，保留重新拉取入口。

- [ ] **Step 4: 运行测试并提交。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_single_review.py tests/backlot/test_operator_actions.py`

Expected: PASS。

```bash
git add backlot/ui/operator/app.js backlot/ui/operator/api.js backlot/ui/operator/styles.css tests/backlot/test_operator_single_review.py tests/backlot/test_operator_actions.py
git commit -m "feat(backlot): make single review actions approval-only"
```

### Task 7: 覆盖失败、缺失、播放失败和直接访问

**Files:**
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] **Step 1: 写失败场景测试。**

覆盖候选项目不存在、批次与候选不匹配、样片缺失、预览播放失败、报告不完整、加载后权限收回、无批次参数直接访问。断言每种状态都有中文原因和下一步，审批按钮按资格禁用。

- [ ] **Step 2: 实现诚实的降级状态。**

媒体失败显示“样片无法播放，请重新拉取最新结果”，缺失显示“样片未生成”，候选不可用显示“候选已不可用”；不得用假海报或空白区域掩盖事实。

- [ ] **Step 3: 运行测试并提交。**

Run: `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_single_review.py`

Expected: PASS。

```bash
git add backlot/ui/operator/app.js backlot/ui/operator/styles.css tests/backlot/test_operator_single_review.py
git commit -m "feat(backlot): handle single review degraded states"
```

## Chunk 4: 手动验收与回归

### Task 8: 做三档手动验收并记录结果

**Files:**
- Modify: `docs/reports/2026-08-26-analysis-readonly-workbench-run-report.md`
- Modify: `docs/superpowers/specs/2026-08-28-backlot-business-language-workbench-design.md`

- [ ] **Step 1: 启动现有工作台并准备 fixture。**

使用现有本地服务和候选项目，至少准备“等待样片、等待脚本、等待制作准备、已完成、失败/缺失”五种状态；不修改真实审批事实，仅使用现有只读 fixture 或临时副本。

- [ ] **Step 2: 按 1180px、900px、390px 检查布局。**

逐档确认标题、九步 rail、材料列表、播放器、五项确认和底部动作无重叠、无横向溢出、长中文不截断；确认移动端动作不会遮挡最后一项确认。

- [ ] **Step 3: 手动走通主线。**

批量候选 → 快速查看 → 打开单条复核 → 返回批量；单条通过/退回；subject hash 变化提示重新确认；失败/权限/报告异常显示恢复入口。

- [ ] **Step 4: 记录验收。**

在报告中记录每个场景的通过/不通过、发现的问题、截图路径和修复提交；只有全部场景通过后，才把真实单条页标记为原型对齐完成。

## 停止条件

1. 单条审批视图未完成前，不宣称真实页面已达到原型，不开放新的编辑入口。
2. 任何审批事实或一致性测试失败时，保留只读查看和“重新拉取最新结果”，不显示“已通过”。
3. 技术字段可以继续存在于 API、schema 和“制作记录”，但不得回流到主界面。
4. 手动验收未覆盖 1180px、900px、390px 三档或五种候选状态时，升级计划保持未完成。

## 完成标准

- [x] 首屏能直接回答当前候选要确认什么。
- [x] 原型三栏结构和轻量九步进度在真实单条页可见。
- [x] 视频、产物、五项确认和主动作按固定阅读顺序呈现。
- [x] 审批模式不显示编辑器、暂存修改、影响预览和技术枚举。
- [x] 批量来源/返回批量上下文不丢失，单条事实与批量事实一致。
- [x] 失败、缺失、播放失败、报告不完整、权限变化均有中文恢复路径。
- [ ] 三档手动验收全部通过，且 `tests/backlot` 与前端语法检查通过。

## 补充 Chunk 5：九阶段产物完整性整改（2026-08-31）

Task 1–7 解决的是审批壳、浏览状态、导航和动作边界；本 Chunk 解决的是“老工作台关键产物是否完整迁移到新审批页”。在本 Chunk 完成前，不得把九阶段材料适配标记为完成，也不得只凭页面能切换阶段就开始最终业务验收。

### Task 9：阶段材料契约与适配器补齐

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `backlot/operator_state.py`（仅补只读投影字段）
- Modify: `schemas/backlot/operator_state.schema.json`
- Test: `tests/backlot/test_operator_artifact_model.py`
- Test: `tests/backlot/test_operator_state.py`

- [ ] 统一九阶段材料 ID，解决 `risks/source_risks` 命名漂移。
- [ ] proposal 增加导演总控单和成本；script 改成业务化分段结构并消除口播/字幕重复。
- [ ] scene_plan 同时保留参考依据、自有素材、源素材区间、成片时间轴、素材证明关系和安排理由；禁止 source/timeline 字段混用。
- [ ] assets 增加生成任务状态、预览、失败原因、费用和口播字幕状态。
- [ ] sample 增加口播、字幕差异和导演规则差异；edit/compose/publish 增加状态、检查、版本、平台和下载信息。

### Task 10：阶段专用只读详情

**Files:**

- Modify: `backlot/ui/operator/approval.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] 增加创意方案、脚本、分镜、制作准备、样片对照、精剪状态、成片检查、交付信息等阶段详情组件。
- [ ] `renderArtifactValue()` 只作为纯文本 fallback，不再渲染镜头、时间轴、检查项、生成任务和交付文件主内容。
- [ ] 预览和下载 URL 转成播放器/下载按钮；技术字段仅进入制作记录。
- [ ] 所有阶段继续复用 `selectedStageId/selectedArtifactId`，不新增审批事实。

### Task 11：完整性测试与验收门

**Files:**

- Modify: `tests/backlot/test_operator_artifact_model.py`
- Modify: `tests/backlot/test_operator_single_review.py`
- Modify: `docs/reports/2026-08-26-analysis-readonly-workbench-run-report.md`
- Modify: `docs/reports/2026-08-28-single-review-manual-acceptance-checklist.md`

- [ ] 九阶段各有最小 fixture，断言旧工作台关键产物至少出现一次且不重复完整正文。
- [ ] 增加分镜时间轴、样片口播、成片检查、交付下载的语义测试。
- [ ] 先通过完整性测试，再按 1180px、900px、390px 做手动走查。
- [ ] 任何阶段产物缺失、错位或工程字段回流，均阻止最终验收并保留只读状态。

补充 Chunk 的详细实施拆解见：`docs/superpowers/plans/2026-08-31-single-review-artifact-completeness.md`。

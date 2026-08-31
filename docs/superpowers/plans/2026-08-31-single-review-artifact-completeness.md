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

- [ ] 记录九阶段每个材料的稳定 ID、业务标题、必备字段和允许的媒体动作。
- [ ] 解决 `risks` / `source_risks` 命名漂移，更新测试和文档后只保留一个规范 ID。
- [ ] 增加“同一事实只能在一个主材料中呈现，摘要卡不得重复完整正文”的契约。
- [ ] 运行 `PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot/test_operator_artifact_model.py`。

## Chunk 1：阶段级业务适配器

### Task 1.1：补齐 proposal 和 script

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `tests/backlot/test_operator_artifact_model.py`

- [ ] 新增 `compactProposal()`：采用方向、备选方向、卖点、目标人群、语气、视觉方法、有效原因、行动引导、预计成本和导演总控单均可读。
- [ ] 新增 `compactScript()`：按开场/正文/结尾输出口播、字幕、段落目标、画面重点、节奏、证明要求；`control_rule_refs`、review 和 feedback 进入制作记录或单独状态区。
- [ ] 避免“制作脚本 / 口播 / 屏幕文字”重复渲染完整相同内容；摘要卡只保留数量和入口。
- [ ] 测试工程字段不出现在主 payload，业务字段不为空时不会被通用 fallback 覆盖。

### Task 1.2：补齐 scene_plan 和 assets

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `tests/backlot/test_operator_artifact_model.py`

- [ ] 新增 `compactScenePlan()`：每镜包含镜头目的、参考依据、自有素材、源素材区间、成片时间轴、素材能证明什么、画面重点和安排理由。
- [ ] 明确 `timeline_in_seconds/out` 与 `source_in_seconds/out` 的语义，禁止交叉使用。
- [ ] 新增 `compactAssets()`：生成清单、素材状态、生成任务、预览、失败原因、预计费用/已用费用和口播字幕状态统一输出。
- [ ] 预览和下载地址作为受控媒体动作保留，不作为普通文本字段递归输出。

### Task 1.3：补齐 sample、edit、compose、publish

**Files:**

- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `backlot/operator_state.py`
- Modify: `schemas/backlot/operator_state.schema.json`
- Modify: `tests/backlot/test_operator_artifact_model.py`
- Modify: `tests/backlot/test_operator_state.py`

- [ ] sample：完整输出计划/实际镜头对照、口播、字幕、音轨、字幕差异、导演规则差异、检查结论和恢复提示。
- [ ] edit：输出精剪状态、修改前样片、影响镜头、声音字幕结果和“是否可以进入成片检查”；审批页不暴露编辑能力入口。
- [ ] compose：输出完整视频、版本变化、画面/声音/字幕时间轴、硬性检查、观感结论和待处理问题。
- [ ] publish：输出当前版本、平台 entries、导出状态、文件清单、下载动作、失败原因和 QA 证据。
- [ ] 如 operator-state 缺少口播或 `caption_diff/creative_rule_diff`，只扩展只读投影字段，不改变审批 API。

## Chunk 2：阶段专用详情阅读器

### Task 2.1：建立详情组件分流

**Files:**

- Modify: `backlot/ui/operator/approval.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] 保留统一三栏壳和 `selectedStageId/selectedArtifactId` 浏览状态。
- [ ] 增加阶段级详情分流：研究步骤、创意方案、脚本、分镜、制作准备、样片对照、精剪状态、成片检查、交付信息。
- [ ] `renderArtifactValue()` 只作为低风险纯文本 fallback，不再承担镜头、时间轴、检查项、交付文件和生成任务的主渲染。
- [ ] 技术字段进入“制作记录”，媒体字段转成播放器、预览、下载等业务动作。

### Task 2.2：统一空态、失败态和状态摘要

**Files:**

- Modify: `backlot/ui/operator/approval.js`
- Modify: `backlot/ui/operator/language.js`
- Test: `tests/backlot/test_operator_single_review.py`

- [ ] 统一“未生成 / 正在准备 / 资料异常 / 播放失败 / 报告不完整”的中文状态和恢复动作。
- [ ] 阶段摘要显示业务结果，不显示对象数量代替结论。
- [ ] 当前待确认阶段显示确认动作；历史阶段、后续阶段和精剪阶段保持只读。

## Chunk 3：去重、业务语言和可访问性回归

### Task 3.1：文案与重复内容扫描

**Files:**

- Modify: `tests/backlot/test_business_language_contract.py`
- Modify: `tests/backlot/test_operator_single_review.py`

- [ ] 禁止主界面出现 `plan_id`、`control_rule_refs`、`runtime`、`revision`、`source_media_id`、模型名、文件路径等内部字段。
- [ ] 增加重复内容断言：脚本文案、字幕、样片镜头对照不能在多个主卡片完整重复。
- [ ] 保留制作记录中的必要技术信息，但不作为一线审批依据。

### Task 3.2：交互和无障碍回归

**Files:**

- Modify: `tests/backlot/test_operator_single_review.py`
- Modify: `backlot/ui/operator/approval.js`

- [ ] 阶段、材料、时间片段、预览和下载动作均可通过键盘操作。
- [ ] 媒体失败、刷新和审批错误使用 `aria-live="polite"`。
- [ ] 所有材料卡保留 `aria-current` 和稳定 `data-testid`。

## Chunk 4：验证和手动验收准备

### Task 4.1：九阶段完整性测试

**Files:**

- Modify: `tests/backlot/test_operator_artifact_model.py`
- Modify: `tests/backlot/test_operator_state.py`
- Modify: `tests/backlot/test_operator_single_review.py`

- [ ] 为九个阶段各准备最小 fixture，断言老工作台关键业务字段在新审批材料中至少出现一次。
- [ ] 增加字段语义测试：分镜时间轴、样片口播、成片检查、交付下载不可为空或错位。
- [ ] 增加缺失/处理中/失败/报告不完整/权限变化 fixture，确认只读降级不伪造结果。

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

- [ ] 九阶段均有稳定、可读、非重复的业务材料。
- [ ] 老工作台的关键产物没有因统一适配器而丢失。
- [ ] 分镜、样片、成片、交付的媒体和检查信息可直接操作或查看。
- [ ] 主界面不出现工程字段，制作记录仍可追溯必要技术事实。
- [ ] `tests/backlot`、前端语法检查和三档手动验收全部通过。

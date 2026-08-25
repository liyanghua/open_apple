# Reference-driven 创意升级 + 运营执行闭环：决策与优先级（2026-08-24）

> 对照：`openmontage-reference-driven-ecommerce-adaptation.md`
> 修订：v1.2（P0-1 执行闭环**最后做**、暂用 Code Agent 驱动生产；其余 P0-2/P1/P2/P3 先实现）
> 状态：开始实施（先实现非 P0-1 项）

## 0. 结论修正

1. **创意升级方向正确、五层架构不推翻** —— 保留初版判断。
2. **但优先级错了**：初版 P0-P3 是"质量增强路线"，达不成"一线运营自助批量生产"。真 P0 是**运营执行闭环**：运营从上传素材，到建批/启动/恢复/重试/改后重生成，全程不离开工作台。
3. **路线定为垂直闭环**：固定 `ecommerce-viral-remix + cinematic-fast + 一个 agent adapter`，先跑通一条垂直链路，再抽象多 Agent。不是"质量优先"，也不是"完整多 Agent 平台"。
4. **核心原则保留**：`Reference is Evidence, not Prescription`（参考片是证据不是处方）——但落地方式从"新建独立 ReferenceCritique artifact"改为"扩展现有 ResearchSynthesis"。

## 1. 修正后的优先级

| 优先级 | 核心交付 | 类型 | 说明 |
|---|---|---|---|
| **P0-1** | 运营执行闭环：工作台直连 Agent/Job Runner，支持建批/启动/暂停/恢复/取消/重试/改后重生成 | 新增（Execution Bridge）| 当前驾驶舱能审批选片，但没有从 UI 创建并实际运行批次的入口（`app.js` 仍让运营"复制给 Code Agent"）|
| **P0-2** | ProductBible 前置采集并成为批次共享硬约束 | 前置 + 硬门 | 新建项目页采集 SKU/价格/claims/视觉约束；加 `must_preserve`/logo/颜色/形态；**事实卡不可跳过**；否则 `product_truth≥8.5` 无判定基础 |
| **P1-1** | 在现有 ResearchSynthesis 内加 ReferenceCritique | 扩展（非新建 artifact）| `differentiation_directions` 已有 `keep_from_reference/change_for_project/avoid`；补 `reference_ceiling` + 明确 `KEEP/IMPROVE/REPLACE/DO_NOT_COPY` 枚举 |
| **P1-2** | BeatScript schema + concept 差异机器校验 | 扩展 schema/validator | script schema 无 `beat_role/viewer_state/setup/payoff`；hook_plan 默认 `other`；需加字段 + 校验"至少 2 个结构维度不同" |
| **P1-3** | 扩展现有 evaluation/repair contract + 接通局部重跑 | 扩展 + 执行器 | `evaluation_report` 已有 `creative_advisory + repair_targets`；缺的是**修复执行器**（rerun API 只建 `draft_plan`，无 persist+execute）|
| **P1-4** | 运营微调：文案/口播、镜头替换、裁切时长、字幕 recipe、转场 recipe | 执行 + UI | Editorial Gallery 的"最后一公里"真实化 |
| **P2** | Runtime 无关的 Caption/Transition Recipe Router | 扩展（不绑 Remotion）| `intent → canonical recipe → runtime adapter → capability check/fallback`（Remotion/HyperFrames/FFmpeg）；首批各 4 个高频 recipe |
| **P3** | 真实运营 Gold Set 校准 | 数据 + 评测 | 校准阈值、排序权重、recipe 扩展 |

## 2. 初版文档的 4 处不准确（已修正）

| 初版判断 | 事实 | 修正 |
|---|---|---|
| "BeatScript 已内置" | skill 层有 beat map，但 script schema 无 `beat_role/viewer_state`；hook_plan 默认 `other`；无机器可验证的 concept 差异 | **部分具备**，需 schema + validator + batch diversity gate 同步升级 |
| "ReferenceCritique 需新增 artifact" | `research_synthesis.differentiation_directions` 已有 `keep_from_reference/change_for_project/avoid` | **扩展 ResearchSynthesis**，不造独立 artifact（避免补 producer/consumer/handoff/fork/projection 而无消费方）|
| "CreativeJudge + RepairPlan 需新建" | `evaluation_report` 已有 `creative_advisory + repair_targets`；rerun API 只建 `draft_plan` | **扩展现有 contract**，真正缺的是"修复执行器"（persist + execute + 回写新版本）|
| "Recipe Router 直接路由到 Remotion" | 管线支持 Remotion / HyperFrames / FFmpeg | **runtime 无关**：intent → canonical recipe → runtime adapter → capability check/fallback |

## 3. 定量验收指标（替换主观标准）

不再用"不再是卖点清单""不再功能直给"当发布门，改为：

| 指标 | 定义 |
|---|---|
| 自动可用率 | 无需"复制给 Code Agent"即完成建批→成片的批次占比 |
| 可交付批次率 | 至少 1 个候选可交付的批次占比 |
| 产品事实错误数 | L1a fatal 中 product_truth 相关错误数（目标 0）|
| 单批运营操作时长 | 运营从上传素材到拿到成片的主动操作时长 |
| 局部修复成功率 | 修复成功 / 修复请求（含成本、耗时）|
| 失败恢复率 | 失败任务可恢复并完成的占比 |

## 4. 四个问题 → 修正后映射

| 问题 | 根因 | 修正后归属 | 顺序 |
|---|---|---|---|
| #1 花字不匹配 | caption 静态 fingerprint | Caption Recipe Router（runtime 无关）| P2 |
| #2 硬切无转场 | transition 自由字符串 + 参考片本就硬切 | Transition Recipe Router（runtime 无关）| P2 |
| #3 无故事结构 | script schema 无 beat 结构字段 | BeatScript schema（beat_role/viewer_state）| P1-2 |
| #4 钩子不出彩 | hook_plan 默认 other + 功能直给 | concept 差异校验 + hook_pattern 用满 | P1-2 |
| （新增）运营不能自助生产 | 工作台无执行入口 | 执行闭环（Agent/Job Runner）| P0-1 |
| （新增）商品真实性无判定基础 | product_facts 太薄 + 可跳过 | ProductBible 前置硬门 | P0-2 |

## 5. 裁剪 / 推迟（保留初版，补一条）

- 不新建 `reference-commerce` pipeline（扩展 cinematic-fast）。
- Recipe 先各 4 个（review 建议），不做 10+10。
- CreativeScore 加权公式推迟（P3 用 Gold Set 校准）。
- 全量 Backlot / Provider 市场 / 多 Runtime 管理：**可推迟**。
- 执行桥（建批/启动/恢复/取消/重试/改后重生成）：**不可推迟**（P0-1）。

## 6. License + Git 状态

- 借鉴思想/协议，不 Copy 源码；商业部署前法务确认 AGPL 义务。
- 本决策文档（及此前新增的文档/代码）当前为**未跟踪文件**，尚未纳入 Git；下一步应提交或明确暂不提交。

## 7. 落地顺序（v1.2 最终）

```text
P0-2 ProductBible 前置硬门（schema + skill；UI 采集随 P0-1 一起）
  → P1-1 ResearchSynthesis 扩展 ReferenceCritique
  → P1-2 BeatScript schema + concept 差异校验
  → P1-3 修复执行器（局部重跑 + 回写）
  → P1-4 运营微调（EG 最后一公里，需 P0-1 执行桥）
  → P2 Runtime 无关 Recipe Router
  → P3 Gold Set 校准
  → P0-1 执行闭环（最后做；当前由 Code Agent 驱动生产）
```

验收门：P0-2 完成后，产品事实卡不可跳过、含视觉真实性约束；P1 完成后，创意升级可机器验证（beat 字段 + 差异校验 + 修复执行）；P0-1 最后接入执行桥，让运营全程不离开工作台。

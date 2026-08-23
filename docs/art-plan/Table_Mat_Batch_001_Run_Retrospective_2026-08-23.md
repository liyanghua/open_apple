# table-mat-batch-001 批次复盘与固化清单（2026-08-23）

> **状态说明**：下文第 1–5 节记录批次运行时的历史事实和当时暴露的问题，不因后续修复改写。代码修复后的最新进度见本页“后续实现更新”，可执行验收见 [`Table_Mat_Batch_001_Batch_Acceptance_Record_2026-08-23.md`](./Table_Mat_Batch_001_Batch_Acceptance_Record_2026-08-23.md)。

## 后续实现更新（代码修复后）

已吸收的事项：

1. `create_candidate_batch()` 现在保留 `variant_plan_ref` 并写入 `diversity_mode`；新批次默认 `warning`，历史批次缺省按 `legacy_read_only` 兼容。
2. pairwise 差异从结构镜头 ID 交集改为结构签名差异；批级 `eligible_candidate_ids` 在 `hard_gate` 下消费 pairwise 失败结果。
3. `sample_preflight` 与 `batch_approve_gate` 在 `hard_gate` 下对缺失差异计划前置阻塞；历史批次不被追溯阻塞。
4. `batch_run_report` / `batch_quality_report` 读取真实运行事件、项目根 `cost_log.json`、评价报告和 sample review；VLM 未评分会标记 `partial` 并给出恢复提示。
5. 批页把报告/差异事实纳入 `aggregate_revision`；报告 `missing/partial/degraded` 时禁用选择和发布；跨候选读取增加 projects-root containment。
6. 新批主链路已接入默认差异策略：建批自动补 `variant_plan_ref`，分叉自动写入 `candidate_variant_plan.json`，creative lock bundle 直接携带差异计划哈希并等待人工审批；本历史批次不回填、不追溯阻塞。

仍未完成的事项：VLM provider 配置与完整评分、voice-fit 阶梯正式 stage service、R3 预览/提升/丢弃 UI 流程，以及通过新五候选 smoke 后将默认模式提升为 `hard_gate`。默认差异策略已固化为 `skills/meta/candidate-diversity-producer.md`，并纳入 `batch-producer` 与 `cinematic-fast/optimize-director`。

> 状态：批次已完结交付（选中 c2/c3）
> 关联设计：`Batch_Production_Recovery_and_Formalization_Plan_2026-08-23.md`（R0–R3）、
> `Batch_Workbench_Cross_Project_Approval_Consistency_Contract_2026-08-23.md`、
> `Batch_Workbench_Interaction_Design_2026-08-23.md`
> 结论速览：**批流程设计是好路线，但本轮大量执行绕开了批级契约（临时发挥），并暴露了 3 个系统契约缺口。**

---

## 0. 批次完结确认（交付）

- 5 候选均完成全量成片（`sample → edit → compose → publish` 全部 `completed`）。
- 人工选择：**c2 / c3**（`selected_for_edit`）；c1 / c4 / c5 保留 `evaluated`。
- 交付物（c2/c3）：`renders/final.mp4`，1080×1920 / 30fps / 15.018s / 含音轨，全量 QA `pass`。
- 批级相位：`completed · 100%`，`selection` 记录 reason「先说痛点，有证据更能建立信任」。
- L1a 均为 `revise`（coverage 7/11 < 9，SKU/价格/参数缺事实）——按计划 R0 保留、不作自动排名依据；发布前已按 publish-director 追加 `downgrade_approval` 决策确认。

---

## 1. 复盘：可固化的（沉淀进 skills / 工具 / 流程）

| 项 | 现状 | 建议固化到 |
|---|---|---|
| **累计时间轴 / 源裁剪分离派生**（`lib/sample_payload.py`） | 已实现，含时间轴重叠/空洞/源裁剪钳制校验 | `sample-director`/`compose-director` 的正式 render-payload 契约；补 skill 文档 |
| **`lib/sample_recovery.py`**：`repair_source_windows` + `build_reuse_assets_sample_input` + 持久化修复后的 final_props | 已实现 | R1「样片 stage 服务」库化；补「修复须落盘 + 刷新 final_props_hash」说明 |
| **字幕 shape 归一化**（`{text,startMs,endMs}`→`{word,...}` + `captionWordsPerPage=1`）| 已实现 | compose-director 的 Remotion CaptionOverlay 契约（`WordCaption{word}`） |
| **音频保真**：reuse-assets 渲染须取 `asset_manifest` 的混音产物（`bgm-ducked.mp3`）而非原始源 + 自然音量 | 已实现 | compose-director「严格复用已批准混音」规则 |
| **样片窗口缓存 key 加入内容哈希**（`edit_decisions_hash`）| 已实现（`video_compose._render_framed_window`）| 固化：内容一变缓存即失效，避免复用旧渲染 |
| **「追加 decision_log 会漂移信包裹 → 必须 refresh_checkpoint_envelopes」** | 本轮多次踩坑 | 写入 checkpoint-protocol / 审计流程 |
| **sample 与 compose 按作用域拆分制品文件**（`render_plan_full.json`/`evaluation_report_final.json`）| 本轮临时绕开 | 见「待修复」#1 —— 应上升为 schema/命名约定，而非脚本约定 |

## 2. 复盘：临时发挥（agent 现场拍板，建议评估后吸收）

1. **样片批准绕开 `batch_approve_gate`**：用 `advance_gates` 逐候选 `write_checkpoint(sample,completed,human_approved=True)` 完成批准，而非契约要求的「coordinator 准备/提交 + 五项效果确认 + 可恢复」跨项目 all-or-nothing。功能上可行，但没有协调记录、没有 five-effect 校验、没有 stale 保护。
2. **一键全量成片（先产 5 个再选择）**：跳过了设计预期「先评估→选 1–2→精剪」的顺序，导致 `compute_phase` 无法归约（见「待修复」#2）。
3. **sample/compose 同名制品覆盖**：用 `render_plan_full.json` 等别名绕开，属 band-aid。
4. **手写 `continue_compose.py`/`continue_finalize.py`**：按批目录一次性脚本实现，未走 sample-director/compose-director/publish-director 的库化服务。
5. **downgrade_approval 决策手工写 decision_log**：未调用决策封装的 `write_artifact_atomic` 重封哈希（导致多次哈希漂移坑）。

## 3. 复盘：待修复的问题

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| 1 | **sample 与 compose 共用 `render_plan.json`/`evaluation_report.json` 文件名**，compose 覆盖 sample 作用域 → sample checkpoint 失效 | 高 | 按作用域/阶段后缀分区（如 `_final`/`_sample`）或版式文件名；或 schema 增加 `scope` 字段，`write_artifact_atomic` 据此落盘 |
| 2 | **`compute_phase` 对「`composed`/`published` 且未选择」无分支**，回退到默认 `sampling` | 中 | 补相位分支：无选择且全 `composed`→`selection`/`evaluated`；部分 `composed`→混合态提示 |
| 3 | **信封漂移**：追加 decision_log / 覆盖同 scope 制品后，前面 checkpoint 失效 | 高 | 决策/制品写入统一走 `write_artifact_atomic`（自动重封哈希）+ 提交后自动 `refresh_checkpoint_envelopes`；或让 checkpoint 引用可重放路径而非固定哈希 |
| 4 | **final_props 的 `sourceInSeconds`/`sourceOutSeconds` 是「原素材坐标」，代理片是「场景等长」**，直接当代理 seek 会越界 | 中 | 明确「素材坐标 vs 代理坐标」语义；渲染用代理坐标（0..timeline），数据里保留素材坐标并注释 |
| 5 | **L1a coverage 7/11 持续 revise**：SKU/价格/参数/字幕渲染模式缺 `expected_facts`/声明导致 skip | 中 | 接入产品事实档案；或对「事实未提供」的 skip 项豁免 coverage 阈值，避免合法 revise 卡发布 |
| 6 | **`caption_style` 未从 `caption_style_fingerprint` 派生**，字幕渲染为 cyan 而非规范的「白字黑描边」 | 低 | 按 compose-director 用 `lib.caption_style.to_overlay_spec()` 写入 render payload |
| 7 | **VLM 创意评审（`video_judge`）未运行**：creative_advisory 为空 | 低-中 | 配置 `DASHSCOPE_API_KEY` 启用 l3-v1.0 评分，供精剪选择参考 |

## 4. 复盘：需要升级的（对应 R1–R3）

| R | 项 | 状态 | 说明 |
|---|---|---|---|
| R1 | asset_plan 增 `audio_plan`，import 到 production_lock | 部分（代码已加） | 已有 `asset_plan.audio_plan` + `production_lock` 优先读取；新生产需从 `script.metadata.audio_plan` 迁移 |
| R1 | voice-timeline-fit 阶梯（1.0→1.1→1.2→1.5）库化 | 未固化 | 本轮仍是 `continue_sample.py` 内临时实现 |
| R1 | 样片 stage 服务（纯构建库 + 幂等持久化服务）| 部分 | 新 `lib/sample_payload.py`/`sample_recovery.py` 可作起点，仍需 stage skill + 服务封装 |
| R2 | `batch_approve_gate` prepare/commit + coordinator record + 恢复 | **未实现（本轮绕开）** | 本批用了简化的逐候选批准；契约要求 all-or-nothing + 可恢复 |
| R2 | `candidate_batch` 同步（sample/成本/运行时/eval 引用）| 部分 | 本轮 `continue_finalize._sync_batch_index` 简单同步为 `evaluated`；缺 prepare/commit/故障注入 |
| R3 | `rerun_plan`/`rerun_run` + preview/promote/discard | 代码已有 | `lib/rerun_plan.py` + schemas；未接 UI/API。已加 `rerun_plan`/`rerun_run` 到 `ARTIFACT_NAMES` |
| — | optimization 门禁（`optimization_policy`/`optimization_run`/评分）| 未接 | publish-director 里已列条件，未实现流程 |

---

## 5. 下一步优化计划（按优先级）

### P0（契约/正确性，影响批量稳定性）
1. **修复 sample/compose 同名制品冲突**：schema 增加 `scope`（`sample`/`final`）或按作用域后缀分区，`write_artifact_atomic` 据此落盘；废弃 `render_plan_full.json` 等临时别名。同时把 `compute_phase` 补上 `composed`/`published` 无选择分支。
2. **信封漂移根治**：决策/制品写入统一重封哈希 + 提交后自动 refresh；或 checkpoint 引用改用可重放路径。

### P1（批级契约正式化）
3. 实现 **`batch_approve_gate` 的 prepare/commit + coordinator record + 恢复器**（契约 §3–4），替换本轮的简化逐候选批准；接入 5 项效果确认与 stale/幂等。
4. `candidate_batch` 同步接入 prepare/commit，补故障注入 / stale / 多候选恢复测试。

### P2（可复用能力）
5. 把 `continue_compose.py`/`continue_finalize.py` 提炼为 **compose-director / publish-director 的库 + CLI**；voice-fit 阶梯、caption_style 派生、expected_facts 接入入库。
6. 接入 `video_judge`（DASHSCOPE_API_KEY）与 `optimization` 门禁，为精剪/发布提供评分依据。
7. R3 `rerun_plan`/`rerun_run` 接入工作台（定位→描述→复述→预览→promote/discard）。

### P3（打磨）
8. 修 caption_style 白字黑描边；注明 final_props 素材坐标 vs 代理坐标语义。

> 验收建议：P0 两项后，先跑 1 个候选走**契约内** `batch_approve_gate`（含故障注入）→ `sample`(五项确认) → `select` → 精剪 → `publish` 全链，再推广到批。

## 6. 专项复盘：候选同质化与结构化报告缺失

### 6.1 候选多样性问题

本批候选虽然登记了 hook/pacing/packaging 等方向轴，但没有在进入素材和样片生产前形成可校验的 `candidate_variant_plan`。因此“方向不同”没有被落实为镜头结构、画面语法、节奏和证据组织的差异，存在只改变开场几秒、主体镜头仍高度复用的风险。共享素材池本身不是问题，缺少镜头级差异证据才是问题。

后续批次必须先写变体计划，再执行生产：六个维度（hook、叙事结构、视觉语法、节奏、证据策略、素材策略）至少改变三个；候选对之间至少有三个结构镜头差异；结构同质化与视觉相似度分开报出，不能合并成一个“同质化”分数。

### 6.2 效率与效果报告缺失

本批可以从事件、成本和评价制品事后拼出部分耗时与质量信息，但没有稳定的批级报告制品，无法回答“最慢阶段是什么、重试花了多少、候选为什么低分、哪条返工最值得做、成本是否被缓存降低”等决策问题。批页若自行计算这些指标，还会在事件缺失或成本索引漂移时给出虚假的 `$0` 或成功状态。

正式化后由 `batch_run_report` 记录运行效率/成本，由 `batch_quality_report` 记录事实覆盖、技术 QA、VLM、人工确认、差异矩阵和返工建议；两个报告都保存输入哈希与评分 rubric 版本。历史批次只允许只读回填，不得为了补报告重新生产。

### 6.3 与下一批的关系

实施任务与验收命令已写入
[`2026-08-23-batch-diversity-and-reporting.md`](../superpowers/plans/2026-08-23-batch-diversity-and-reporting.md)。在这两条路线的契约测试、五候选 fixture 和重启/缺失事件回归通过前，不提升自动排名，也不把批页的“推荐”当成自动选择依据。

---

# 二次重跑摘要（2026-08-23，批次已完结后）

> 背景：批次完成后又问「能否干净重跑一次」；盘点后做了两处修正，以使重跑能真正吃到 P0/P1 修复的红利。

## 追加修正（重跑前置）
1. **样片渲染路由**：`continue_sample.py` 的样片渲染从旧 `build_sample_edit_decisions`（`in_seconds=0` 黑屏根源）改为 `lib.sample_payload.build_sample_render_payload`（累计时间轴 + 源裁剪分离 + 字幕 word shape + 混音音频）。→ 样片一次正确，不再黑屏 / undefined。
2. **scoped 命名统一**：`continue_compose.py`/`continue_finalize.py` 的 `evaluation_report_final.json` → `evaluation_report.final.json`（点号）；`render_plan` 已为 `.final`/`.sample`，与 `backlot/state.py` 的 `SCOPED_ARTIFACTS` 投影一致。

## 与上次重跑相比的改进（已落地）
| 域 | 上次 | 现在 |
|---|---|---|
| 样片渲染 | 黑屏（`in_seconds=0`）| 累计时间轴 + `source_in/out` 分离 + 钳制 |
| 字幕 | 字面 `undefined` | word shape + 缺字段阻塞 |
| 音频 | 取错原始源 | `asset_manifest` 混音产物（`bgm-ducked`）|
| 源窗口 | 需手修 | `repair_source_windows` + 落盘 + 刷新 hash |
| 前置校验 | 仅时间轴 | `caption_integrity`/`opening_alignment`/`candidate_divergence` |
| 制品冲突 | 同名 `render_plan.json` 覆盖 | `render_plan` 纳入 `SCOPED_ARTIFACTS`（`.sample`/`.final`）|
| 信封漂移 | 追加决策后 checkpoint 失效 | `decide(batch_decision)` 原子化 + 恢复不误判 stale |
| 批相位 | composed/published 无选择→`sampling` | `compute_phase` 已处理 |
| 选择门 | 只查 evaluated+eval_ref | `selection_quality_failures`（字幕/开场/差异度/致命评估）|
| 跨引擎源裁剪 | 三引擎不一致 | ffmpeg/hyperframes 统一读 `source_in/out_seconds` |
| 渲染缓存 | 内容变仍复用 | 缓存键含 `edit_decisions_hash` |
| R3 重跑 | 库+schema | 字段对齐契约 + `candidate_rerun`/`batch_rerun` 路由 |
| 运行时读取 | 硬编码 remotion | 读 `production_lock.locked_values.render_runtime` |

## 干净重跑链路（Runbook）
1. **样片**：`continue_sample.py --dry-run`（校验）→ `continue_sample.py`（实时，需素材创意锁已批准；并行 ≤3）。
2. **样片审批**：驾驶舱「一键通过」（五项效果确认）。
3. **全量成片**：`continue_compose.py --all` → `renders/final.mp4` + `render_plan.final.json` + `evaluation_report.final.json` + `checkpoint_compose`。
4. **收尾**：`continue_finalize.py` → `checkpoint_publish` + `downgrade_approval` + `candidate_batch` 同步 `evaluated`。
5. **人工选择**（驾驶舱）→ `batch/select`（走质量门，拒绝不合格候选）。
6. **重跑（R3，可选）**：`POST /api/v2/projects/{id}/candidate-rerun` / `batch/rerun`。

## 诚实提醒（重跑仍缺）
- **R2 `batch_approve_gate` 协调层未实现**：上面审批是「逐候选原子」，非整批 all-or-nothing（含 coordinator record + 跨候选故障恢复）。若要整批回滚语义，需做 R2。
- R1 剩余（voice-fit 阶梯库化 / 样片 stage 服务）、`asset_plan.audio_plan` 必填、`video_judge`(VLM) 与 `optimization` 门禁、R3 preview/promote/discard 完整流转未装。

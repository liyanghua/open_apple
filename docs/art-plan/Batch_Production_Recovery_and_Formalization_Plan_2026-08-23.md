# 批量样片恢复与正式化实施方案（2026-08-23）

> 状态：已确认，待实施
> 适用批次：`table-mat-batch-001`
> 目标：先无付费恢复五个样片，再将样片生产、声音锁定、批量审批恢复、候选差异校验与可逆重跑纳入正式工作台。
>
> **实现进度（2026-08-23 批次已完结）**：详见
> [`Table_Mat_Batch_001_Run_Retrospective_2026-08-23.md`](./Table_Mat_Batch_001_Run_Retrospective_2026-08-23.md)。
> 本轮落地 R0（新增 `lib/sample_payload.py` / `lib/sample_recovery.py`；5 候选全量成片，
> `sample→edit→compose→publish` completed；批尾人工选择 c2/c3，批相位 completed/100%）。
> **未按批级契约执行**：样片批准绕开 `batch_approve_gate`（R2 未实现，无 prepare/commit/coordinator/恢复）。
> 待修：**P0 已落地（2026-08-23）**——sample/compose 同名制品冲突（`render_plan` 已纳入 `SCOPED_ARTIFACTS`，
> 按 `render_plan.sample/final.json` 分区）、`compute_phase` 乱序归约、信封漂移（`decide(batch_decision)` 原子化 +
> 恢复不再误判 stale）。
> **P1 已落地（2026-08-23）**——`batch_select_for_edit` 效果门+质量预检（`selection_quality_failures`）、
> `sample_preflight` 增 `caption_integrity`/`opening_alignment`/`candidate_divergence`、`sample_payload` 缺字幕改阻塞、
> 旧批页 `undefined` 占位、`sample_recovery` 读锁定 `render_runtime`、跨引擎统一 `source_in/out_seconds` 裁剪坐标、
> R3 `rerun_plan` 字段对齐契约（`vlm_finding_ids`/`confirmed_scope`/`from_stage`/`render_runtime`）+ 接 `candidate_rerun`/`batch_rerun` 路由。
> 剩余：正式化 R1（voice-fit 阶梯库化/样片 stage 服务）、R2（`batch_approve_gate` prepare/commit/coordinator/恢复）、
> R3 preview/promote/discard 完整流转、`asset_plan.audio_plan` 必填、`video_judge`(VLM) 与 optimization 门禁。

## 1. 已确认决策

| 决策 | 结论 |
|---|---|
| 发布方式 | 双轨：当前批次恢复与平台正式化独立交付 |
| 当前批次声音/素材 | 严格复用已批准的豆包 TTS、SUNO BGM、混音和代理视频；不发起新的付费调用 |
| 当前批次目标 | 先修复时间轴并重新 QA/VLM 复评；不同时进行创意重剪 |
| 产品事实 | 暂不补 SKU、价格、参数；L1a 可以保持 `revise`，不得自动进入候选选择 |
| 人工门 | 恢复完成后继续停在 `sample / awaiting_human`，不得自动批准 |

当前样片的黑屏不是素材、TTS、BGM 或 Remotion 可用性问题。根因是临时脚本将每个镜头的 `edit_decisions.cuts[].in_seconds` 都写为 `0`，但 Remotion `Explainer` 把该字段视为 `Sequence` 的时间轴起点；所有镜头因此在第 0 秒叠放，首镜结束后没有活动画面。

正确约定为：

- `in_seconds` / `out_seconds` 表示成片累计时间轴；
- `source_in_seconds` / `source_out_seconds` 表示源素材裁剪点；
- 样片的实际时间轴以 `final_props` 为唯一事实来源；
- 运行时 payload 是由 canonical artifacts 派生的临时输入，不得由项目脚本私自定义第二套语义。

## 2. 交付顺序

### R0：时间轴安全与当前批次恢复

**范围**

1. 为 `video_compose` 增加正式的 `sample_payload` 输入。它由 `final_props`、`asset_manifest`、`render_plan`、已有音频和词级字幕构建，适用于 Remotion 样片渲染；`edit_decisions` 仍只属于 edit/compose 阶段。
2. 新建纯函数适配层，将 `final_props.scenes` 派生为 Explainer 所需的顺序 cuts：累计 timeline 与源素材 trim 分离。
3. 扩展 `lib/sample_preflight.py`，在调用 Remotion 前拒绝以下情况：首镜不从 0 开始、主镜头重叠、时间轴空洞、镜头未覆盖样片窗口、源素材时长不足、`final_props` 与 payload 的时间轴不一致。
4. 在样片预检中增加 `caption_integrity`、`opening_alignment`、`candidate_divergence`：字幕缺失不得渲染为 `undefined`；前 3 秒须与首段口播意图一致；每候选至少 3 个镜头发生结构化差异。
5. 为 5 个候选执行 `reuse-assets` 样片恢复：只重新构建运行时 payload、重渲 `sample-v1.mp4`、运行 quick QA、`technical_validator` 与 `video_judge`。
6. 记录一次结构化 `rework_cause`：`issue_tags=["blank_frame", "render_failure"]`。重写 `final_props`、`render_plan`、`sample_report`、`sample_execution_trace`、`evaluation_report` 和 sample checkpoint 的同一 revision。

**不可做的事**

- 不调用 TTS、音乐、代理或其他付费生成工具；
- 不更换 provider/model/runtime，不重开 creative lock；
- 不创建新候选项目，不自动把候选写为 `evaluated`；
- 不自动执行样片效果确认。

**R0 验收**

- 五个输出均为 `10.05s / 540x960 / 30fps`；
- 从第一个镜头结束到样片窗口结束不存在非预期长黑帧；
- 7 个镜头的 source trim 与 `shot_execution_plan` 一致，前 10 秒按顺序包含前四个镜头；
- 每个候选存在可追溯的 `candidate_variant_plan`；差异预检显示至少 3 个镜头差异，且不是只改变首句口播；
- `caption_integrity` 无 `missing`；`opening_alignment` 为 `pass` 或明确进入人工确认，不得静默放行冲突；
- TTS、BGM、代理素材和混音文件的 SHA-256 在恢复前后不变；
- 样片仍处于 `awaiting_human`，L1a 的产品事实缺项被如实保留。

### R1：样片生产与声音锁定正式化

**声音时间轴**

1. 将 `voice-timeline-fit` 的尝试阶梯固化为纯库函数：`1.0 -> 1.1 -> 1.2 -> 1.5`，基于每段真实探测时长做决策。
2. 样片 stage 负责执行 provider 调用、记录尝试结果与写入审计；库函数只负责选择下一次 speech rate 和判断是否需要改写/调整分镜。
3. 混音输入统一使用 `start_seconds`，禁止通过脚本私有字段转换；所有段落必须在混音前通过无重叠、时长适配检查。

**音频锁定**

1. 扩展 `asset_plan` 增加正式 `audio_plan`：narration provider/model/voice、BGM provider/model/profile、mix 策略、预估成本。
2. `build_production_lock()` 优先且在新生产中强制从 `asset_plan.audio_plan` 写入 `locked_values.tts/bgm/mix`；不再从 `script.metadata.audio_plan` 隐式兜底。
3. 旧项目通过显式迁移保留兼容，而不是修改其既有审计历史。
4. 将 BGM/provider 修订做成批级动作：追加同一 subject 的 decision revision，重建 lock 和 approval bundle，重开 creative lock，批准后才允许新的付费调用。

**样片 stage 服务**

1. 将 `continue_sample.py` 的可复用部分拆分为样片 stage skill、纯构建库和幂等持久化服务。
2. Agent 仍是 pipeline 的阶段编排者；服务仅负责验证、恢复已存在资产、写入 canonical artifacts 和事务提交，不建立第二套 orchestrator。
3. 为 resume/reuse-assets 提供正式操作路径，以后样片渲染失败不得依赖 gitignored 脚本。

### R2：批级事实、成本与审批恢复

**批级投影**

1. 候选样片提交后同步批根 `candidate_batch`：`sample_ref`、真实成本、provider/model/runtime、尝试次数和样片状态。
2. 只有 L1a 合法通过且 `evaluation_report_ref` 已存在时，候选才能转为 `evaluated`；选择 API 继续拒绝不满足此条件的候选。
3. 工作台必须单独呈现“样片生成中”“样片已出待人工确认”“质量/事实评分阻塞”。`checkpoint_sample.awaiting_human` 不得显示为“尚未完成样片”。
4. 预算以 cost tracker 为主；缺失时汇总子项目 `asset_manifest.total_cost_usd`，与批根不一致时展示 degraded warning，不得显示虚假的 `$0`。

**跨项目审批恢复**

1. 将 `batch_approve_gate` 改为 prepare/commit：prepare generation 包含 review、checkpoint transition、候选 decision log 和 checkpoint envelope refresh，但不更新 current pointer。
2. coordinator record 为每个参与者记录 `old_generation`、`prepared_generation`、commit marker、错误状态；完成 prepare 后才允许固定顺序 commit。
3. 恢复器在任一点中断后要么补齐剩余 commit，要么按 `old_generation` 创建补偿恢复 generation；不得把“review 已提交但 child decision 未写入”错误判断为不可恢复 stale。
4. 移除 `_append_child_decision` 的第二次独立事务：审批事实、审计和 envelope refresh 必须在同一个候选 generation 中提交。
5. 批级样片门完成后才开放终稿编辑室：用户选择 1–2 个 `evaluated` 且通过质量预检的候选，系统深链到其当前 revision 的 `/p/<candidate-id>`；失败、未评估或 revision 过期的候选不得进入。

### R3：意图驱动的局部修改与可逆重跑

1. 新增 `rerun_plan` 和 `rerun_run` 契约及候选级 API。计划请求必须包含 `child_revision`、定位锚点、用户指令、确认的 VLM finding、最小受影响阶段、保留阶段、成本预估和已锁定的 runtime。
2. `rerun_run` 固定状态机：`draft_plan -> preview_running -> awaiting_preview_review -> full_running -> awaiting_final_review -> promoted | discarded`。
3. 技术修复只运行受影响阶段；镜头/节奏改动先停在低成本 compose 预览；字幕/口播/素材改动先停在 sample 预览。
4. 旧 revision 始终是 current 可用版本，只有 `promoted` 更新 current pointer；预览放弃、取消和 discarded 保留历史但不覆盖当前版本。
5. 批页候选抽屉实现“定位 -> 描述 -> 复述 -> 预览”流程。多个 VLM 建议取依赖闭包并集，revision 改变则返回 `stale` 并要求重新定位。
6. 切换 Remotion/HyperFrames 属于高影响修改：必须重算路径和成本、追加 `render_runtime_selection` 修订并重新确认；失败时禁止静默换引擎。

## 3. 公共契约变化

| 契约 | 变化 |
|---|---|
| `video_compose` | `operation=render` 支持受验证的 `sample_payload`；payload 为运行时输入，不替代 `edit_decisions` |
| `asset_plan` | 增加 `audio_plan`，成为 production lock 的声音选择来源 |
| `production_lock` | 新生产强制使用 `asset_plan.audio_plan`；旧项目显式迁移兼容 |
| `candidate_batch` | 样片、成本、运行时与评估引用在候选提交时同步，选择仍以 `evaluated + evaluation_ref` 为硬条件 |
| `candidate_variant_plan` | 记录候选镜头级变体、差异类型、批次基线和差异指纹；作为 `candidate_divergence` 的唯一事实来源 |
| `sample_quality_preflight` | 统一产出 `caption_integrity`、`opening_alignment`、`candidate_divergence` 与证据引用，未通过时保持样片门阻塞 |
| batch action | prepare generation/commit marker/recovery 变为必填事实，而非空占位 |
| rerun | 新增 `rerun_plan`、`rerun_run` 与 preview/promote/discard 操作 |

## 4. 测试计划

### 时间轴与样片

- 7 镜头顺序 payload：首镜为 0、每镜起点等于前镜终点、无 overlap、source trim 保持原选择。
- Remotion integration fixture：在第一个镜头结束后仍有活动画面；black-frame 检测可捕获旧错误。
- `sample_preflight` 对时间轴空洞、累计时长错误、源片不足和 `final_props` 漂移全部 fail fast。
- R0 恢复前后断言现有 TTS/BGM/代理/混音 hash 不变，且 mock provider 零调用。
- 字幕字段为 `missing/null/empty` 时，预检阻塞且 UI 显示业务状态，不出现 `undefined`；显式无字幕时使用 `intentionally_empty`。
- `opening_alignment` 对首段口播与前 3 秒视觉冲突、低置信度和通过三种结果分别断言。
- `candidate_divergence` 对共享素材池、仅首镜变化、至少 3 镜头变化和重复差异指纹分别断言。

### 声音与锁

- voice-fit 阶梯、实测时长、混音无重叠、`start_seconds` 字段和 loudness 回归。
- 有口播却缺 `asset_plan.audio_plan.tts` 的新生产被拒绝。
- BGM 修订必须产生 decision revision、重开 creative lock；不允许跳过批准直接使用新文件。

### 批级与重跑

- 样片完成但待审批的候选投影为正确状态；成本同步和成本不一致 warning。
- 故障注入覆盖：prepare 失败、首个 pointer commit 后中断、review 已 staged 但审计尚未标记、全部 marker 已写但 coordinator 未完成。
- 重跑覆盖 stale revision、VLM anchor 失效、多个 finding 的依赖闭包、预览接受/放弃、promote/discard 与 runtime 切换确认。
- 编辑室门禁覆盖：样片门未完成、质量预检失败、未评估、无评价引用、选择超过 2 个均拒绝；通过后只返回选中候选当前 revision 的深链。

## 5. 发布门

1. R0 的时间轴/Remotion/当前批次恢复测试全部通过后，才允许重新打开 `table-mat-batch-001` 的样片门。
2. R1 的新样片能力在独立 fixture 和至少一个非当前批次 smoke project 验证后，才能替代临时脚本。
3. R2 的故障注入、stale、重放和多候选恢复测试通过后，批级驾驶舱才可作为唯一审批入口。
4. R3 的 preview/promote/discard 回归通过后，才开放工作台的“修改并重跑”按钮。
5. `caption_integrity`、`opening_alignment`、`candidate_divergence` 和编辑室门禁通过批量 fixture 回归后，才允许把批量工作台作为终稿编辑室的正式入口。

产品 SKU、价格和参数的权威档案不在本次恢复范围内；在该档案提供并接入前，任何修复后的样片只能用于人工审看与创意复评，不能用于自动排名或进入精剪选择。

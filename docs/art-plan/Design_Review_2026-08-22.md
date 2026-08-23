# 设计评审、版本复盘与下一步实施基线（2026-08-22）

> 本文是后续 coding agent 的单一执行依据。它评审并裁剪以下历史设计：`AutoDesign_to_Video_Growth_Harness_Technical_Design_v1.0.md`、`Video_Judge_OpenSource_Research_2026-08-21.md`、`Three_Track_Integration_Plan_2026-08-22.md`。历史文档保留背景和论证，不再直接作为实施清单。
>
> 现状基线：`projects/table-mat-mix-v7` 已跑通 research → proposal → script → scene_plan → assets → sample → edit → compose → publish，能够下载成片；但这证明的是“链路可运行”，还没有证明“成片效果可评价、可比较、可解释”。

## 0. 结论与边界

三份设计文档的方向基本正确，但主文档约 60% 是商业部署和在线增长的远期架构。当前版本只建立一个可复用的制作闭环：

1. 研究结果可追溯，形成 `Reference Fingerprint`、素材映射和差异化方向。
2. 第二步锁定“导演总控单”，作为创意合同，统一内容方向、故事和节奏、视觉规则、事实与连续性、原创边界五类约束。
3. 后续剧本、镜头执行单、样片和成片都能回指这份合同，并展示“计划 vs 实际”。
4. 样片不是只给一个视频，而是给用户一个可判断的效果卡：钩子、节奏、字幕、画面切换、口播、音乐，以及未按计划执行的项目。
5. 先用评价体系选出更好的候选，再扩大到 5–10 个创意方向；没有评分就批量，只会更快地产生无法比较的片子。

本轮不改变以下架构原则：Agent 负责判断和编排；Python 负责工具与持久化；artifact 是阶段之间的合同；checkpoint 是用户决策边界；`decision_log` 是追加式历史；不新增第二套 orchestrator。

## 1. 已完成版本：从项目开始到成片下载

| 阶段 | 用户看到的名称 | 固化的中间产物 | 用户要确认的事 | 对下一步的影响 |
|---|---|---|---|---|
| research | 参考素材与素材体验 | 参考片拆解、`Reference Fingerprint`、自有素材理解、映射表、差异化方向 | 借鉴什么、保留什么、哪些必须用真实素材 | 决定创意合同的边界，避免后面照搬或跑偏 |
| proposal | 创意方案 / 导演总控单 | 五类导演规则、钩子方向、原创边界、候选创意 | 这条片到底要讲什么、用什么方式讲 | 锁定剧本的内容和视觉方向 |
| script | 剧本生成 | 制作剧本：段落、口播、字幕意图、节奏、事实证据 | 段落是否成立，信息是否完整 | 形成镜头拆解的唯一上游 |
| scene_plan | 镜头执行单 | 每个镜头的画面、时长、素材来源、字幕、口播、音效/音乐意图 | 哪些镜头用真实素材，哪些允许生成补位 | 形成制作准备和样片的执行清单 |
| assets | 制作准备 | 源素材代理、补位素材、音频和字幕所需的输入 | 素材是否齐，缺口如何补 | 允许进入样片，不再重复解释前面已确认的素材映射 |
| sample | 样片生成 | 样片、执行对照、评价卡、问题和修复建议 | 最核心的钩子、节奏、字幕、画面切换、口播和音乐是否有效 | 只有确认效果后才进入精剪 |
| edit / compose | 修改和精剪 / 成片生成 | 修改记录、最终时间线、渲染 QA、成片 | 修改是否解决了评价卡中的问题 | 通过技术与效果门后进入交付 |
| publish | 交付下载 | 导出文件、平台信息、交付说明、QA 证据 | 是否作为最终交付版本 | 形成可下载、可追溯的交付包 |

这条链路中，`制作准备` 的职责是“确认输入已就绪”，不是再次列一遍镜头执行单；`样片` 的职责是让用户判断效果，而不是让用户重新审阅所有前置内容。

## 2. 什么已经固化，什么仍是临时发挥

### 2.1 已固化，应该继续作为产品能力

| 层面 | 已固化内容 | 继续保持的理由 |
|---|---|---|
| 架构 | Agent-first；research → proposal → script → scene_plan → assets → sample → edit → compose → publish | 创意判断集中在 Agent，工具层不偷偷改变用户已确认的方向 |
| 数据 | 阶段 artifact、`decision_log`、checkpoint、production lock | 每一步有证据、有版本，能恢复、能解释、能审计 |
| 一致性 | 导演总控单作为创意合同；剧本和镜头执行单必须回指合同 | 防止 research、创意、剧本、分镜各自“重新发挥” |
| UI | 九个大制作阶段固定展示；阶段内看子阶段和中间产物；分镜、候选和评价卡使用横向滚动卡片 | 用户按制作链路理解进度，不被长页面淹没 |
| 交互 | 锁定、确认、提交、下一步是明确状态；无参考片阶段置灰并说明原因 | 避免“待确认/已确认”反复跳变和误操作 |
| 渲染 | 统一 composition、素材 staging、QA、publish 交付包 | 减少 Agent 手工补参数和重复排障 |
| 参考复刻 | 研究参考片的内容、结构、节奏、视觉机制和原创边界 | 借鉴“为什么有效”，不复制成片内容 |

### 2.2 部分固化，首期需要补齐

- 评价目前只有技术健康检查，没有“这条片为什么有效”的效果评价。
- `voice_performance` 和 `music_profile` 能被计划出来，但 v7 没有真正进入混音；“没有口播/BGM”不能继续作为无理由默认值。
- 钩子生成、字幕风格复刻、样片执行差异还依赖 Agent 临时整理，尚未形成统一 artifact 和 UI。
- 批量候选只有数据模型，没有共享研究、分叉、并发限流、评分排序的执行机制。

### 2.3 临时发挥，不应继续作为产品设计

- Agent 临时决定钩子、节奏、字幕样式，却没有把决定写回创意合同或剧本。
- Agent 手工把 `content_direction.rules[0]` 等内部路径翻译到页面，导致用户看不懂“遵守的导演规则”。页面必须展示自然语言摘要和影响，不展示 JSON 路径。
- 每次缺素材都临时改提示词、换模型、手工重试，未形成“缺口 → 可选补位方案 → 用户选择 → 影响”的记录。
- 样片只交最终视频，用户无法知道哪些镜头按计划执行、哪些是新增、哪些没有执行。
- 为了推进流程，Agent 在没有明确用户决策的情况下默认为无口播、无音乐，或直接替用户切换 provider / render path。
- 通过回到 code Agent 手工输入下一步指令来推进流程。短期可以提示用户，长期应由审核台生成结构化的下一步指令和执行上下文。

这些行为可以作为一次运行的 `decision_log` 或 `capability_extension`，不能再沉淀成第二套流程或隐藏规则。

## 3. 四个核心问题的统一方案

### 3.1 评价体系：先让用户“有体感”

首期建立一个 `evaluation_report`，同时服务 Agent、审核台和后续批量排序。

- **L1a 确定性门**：时长、分辨率、帧率、音视频可播放、字幕是否越界、素材是否存在、关键事实是否有证据、成片是否能渲染。失败时阻止 publish。
- **L3 VLM advisory**：钩子清晰度、信息理解、节奏、画面与口播匹配、字幕可读性、视觉一致性、产品证据、音频质量。它给建议和分数，不在首期直接阻止发布。
- **人工效果确认**：用户用自然语言确认“钩子是否抓人、节奏是否顺、字幕是否像参考片、口播和音乐是否合适”。确认结果写入 `decision_log`，并与样片版本绑定。

审核台不只显示总分，还必须显示：

1. 哪些前置规则已执行；
2. 哪些镜头或音频没有按计划执行；
3. 新增了什么、删掉了什么、为什么；
4. 最值得修改的前三项，以及修改后会影响哪些镜头和阶段。

### 3.2 并行混剪：一次研究，多个创意方向

批量候选共享同一份 `Reference Fingerprint`、事实证据、素材清单和原创边界，只在以下维度分叉：

- 钩子：问题型、结果先行、反常识、对比型、场景痛点型；
- 故事节奏：快切证明、问题—解决、三点清单、使用场景推进；
- 包装：字幕主导、口播主导、画面主导；
- 目标人群或时长：例如新客/老客、15 秒/30 秒。

每个候选拥有独立的创意合同、剧本、镜头执行单、样片和 `evaluation_report`，但引用同一份共享研究 artifact。首期先验证 5 条，系统并发限制为 2–3 条；评分和成本稳定后再放到 10 条。最终不是自动发布 10 条，而是排序后由用户选择 1–2 条进入精剪和交付。

### 3.3 钩子和参考字幕风格

钩子必须从“Agent 觉得不错”变成可比较的 `Hook Plan`。每个候选至少记录：前 1–1.5 秒发生什么、观众看到/听到什么、承诺解决什么问题、用哪条真实证据兑现、与其他候选的差异。样片阶段优先让用户确认钩子和前 3 秒，而不是先审完整片。

参考片字幕不能只记录“白字、黑描边”。新增 `CaptionStyleFingerprint`，抽取并允许人工修正：

- 字体类别和风格近似、字号层级、字重；
- 填充色、描边、阴影、背景条、透明度；
- 屏幕位置、安全区、每行字数和断行方式；
- 入场/出场、逐字/整句、强调词、跟随画面或跟随口播的动效；
- 哪些规则是品牌/产品必须保留，哪些只是参考片的表现手法。

实现上用可用的开源字体或风格近似，不搬运参考片字体文件或素材；样式规则进入字幕渲染 artifact，Remotion 只负责按规则执行。

### 3.4 口播和背景音乐

有口播或音乐的创意，默认必须生成并进入样片；如果用户选择无口播/无音乐，必须写出理由。TTS 的真实时长驱动字幕和镜头时间轴，不能先按估算时长排完再硬塞音频。

- 口播：沿用剧本中的 `voice_performance`，记录声音、语速、情绪、实际音频时长和字幕对齐结果。
- BGM：沿用参考片 `music_profile`，映射到可用的生成或素材 provider；记录节奏、情绪、段落变化、音量和 ducking。
- 审核台：单独显示口播、BGM、原声三条轨及其状态；用户能快速判断“有声音但听不清”还是“根本没生成”。

## 4. P0 / P1 / P2 优先级与验收

### P0：让一次运行可评价、可解释、可交付

1. `evaluation_report` + L1a `technical_validator` + scorecard UI；v7 能生成第一张完整评价卡。
2. 样片页增加“执行对照”：规则已执行、未执行、新增项、影响镜头、建议动作。
3. 口播和 BGM 进入真实样片；无音频时必须有明确的用户可见原因。
4. 固化样片效果确认：用户确认后才能进入 edit；确认失败时给出局部修改入口。

P0 验收：同一项目刷新或恢复后状态不丢失；L1a 失败阻止 publish；用户不用读内部字段即可回答“这条片是否按计划做了、最该改什么、改完影响什么”。

### P1：让创意可比较、可批量

1. `Hook Plan` 和 `CaptionStyleFingerprint` 的提取、人工修正和渲染落地。
2. 批量候选编排：共享 research，分叉 5 个创意方向，2–3 并发，统一 scorecard 排序。
3. 审核台提供候选横向卡片、前 3 秒对比、评分差异和“选中后进入精剪”。
4. 局部修复先支持四种：`rewrite_hook`、`edit_caption`、`replace_asset`、`shorten_shot`，每次修复都显示影响范围。

P1 验收：一次研究能稳定产出 5 个可比较候选；每个候选都能回指同一份事实和原创边界；用户能在一个页面选出 1–2 条，不需要回到 code Agent 手工拼指令。

### P2：形成可学习的质量闭环

1. 10 候选批量、成本/时延预算和失败重试策略。
2. Gold / Silver / Bad / Hard Negative 样本集、judge/rubric 版本治理、replay scoring 和人工一致性校准。
3. 线上发布数据和人工评价的回流；只在数据足够后做自动学习或奖励建模。
4. 更细粒度的局部修复、shotopt 桥、剪映读回和跨项目经验复用。

P2 验收：评价版本可重放、评分变化可解释；模型或规则升级不会悄悄降低事实一致性和硬门通过率；线上数据只作为后验反馈，不替代前置人工确认。

## 5. 代码、UI、Skill、架构的实施清单

### 代码与 schema

- 新增唯一评价产物 `evaluation_report`，不再另起平行 GrowthBench schema。
- 抽取公共 `lib/qa_checks.py`；`composition_validator` 只做渲染前 props，`final_qa` 只做渲染后技术健康，未来 `technical_validator` 做电商内容 L1a。
- 补 `HookPlan`、`CaptionStyleFingerprint`、候选批次和执行对照的最小 schema；先不实现 `asset_binding`、`timeline_ir` 等大 IR。
- 继续使用 `decision_log` 追加更新和 checkpoint 原子前进；不得通过修改旧记录来覆盖历史选择。

### 审核台 UI

- 固定九个大阶段，阶段内用子阶段卡片和中间产物抽屉；分镜、候选和评价卡使用横向滚动卡片。
- 页面用“已按计划执行 / 有差异 / 待确认 / 不适用”四种稳定状态，不展示内部 JSON 路径。
- 样片页面默认展示播放器、评价卡、执行对照、音频轨和下一步动作；前置内容通过引用和差异展开，不重复堆叠。
- 下一步先生成结构化指令和上下文摘要，提示用户切换 code Agent；后续再自动唤起 Agent，不在本轮偷偷增加直连通道。

### Skills

- 研究：`Reference Fingerprint`、行业拆解维度输入模板、素材映射和差异化方向。
- 创意：导演总控单 / 创意合同、Hook Plan、五类一致性规则。
- 剧本与镜头：制作剧本、镜头执行单、真实素材优先和生成演示标记。
- 样片：执行对照、评价卡、音频混音、用户效果确认。
- 修复：四种局部修复及影响预估。

Skill 负责指导 Agent 的判断和表达；不得把创意决策硬编码进 Python orchestrator。

## 6. 具体实施计划、优先级与验收标准

本节是执行顺序，不是新的架构。当前代码已经具备 Research 九制品、导演总控单、制作剧本、镜头执行单、`sample_execution_trace` 和五项样片效果确认；实施时只补缺口，不重复建设这些能力。

### P0：一条片可评价、可解释、可交付

#### P0-0 先冻结评价契约

- 新增唯一 `evaluation_report` artifact，至少绑定 `subject_ref`、`subject_version`、`subject_hash`、`hard_gate`、`creative_advisory`、`execution_diff_ref`、`repair_targets` 和 `judge_version`。
- 将它注册到 artifact registry、`cinematic-fast` 的 sample/compose/publish 合同、checkpoint 校验和 Backlot 状态投影。
- 旧项目缺失时从现有 render、props、QA 和 sample trace 回填；不得删除或覆盖历史制品。

#### P0-1 L1a 确定性质量门

- 把公共检查抽到 `lib/qa_checks.py`；`final_qa` 保留渲染后技术健康，新增 `technical_validator` 负责 L1a 业务门。
- 固化十项检查：SKU、价格、参数、敏感词、字幕越界、黑帧、静帧异常、音画缺失、时长、音量。
- 每个失败项都返回业务可读的错误、证据位置、影响镜头和是否可修复；L1a 失败时 publish 不得通过。

#### P0-2 样片执行对照与效果确认

- 复用现有 `sample_execution_trace`，补齐音频、字幕和创意规则的计划/实际差异。
- 样片审核台固定显示播放器、评价卡、执行对照、三条音频轨和下一步动作。
- 五项效果确认保持全量 `pass` 才能进入 edit；`adjust` 进入局部修改，`redirect` 回到创意方向。
- 页面展示自然语言摘要，不展示 `content_direction.rules[0]` 等内部路径。

#### P0-3 口播与 BGM 真正执行

- `production_lock` 中的口播和 BGM 必须是“已选择并生成”或“无音频且有原因”。
- TTS 实际时长驱动字幕和时间轴；BGM 记录节奏、情绪、音量和 ducking。
- 已选择口播/BGM 但没有实际音轨时，sample 不得标记完成。

**P0 验收：** v7 能生成 sample 和 final 两个范围的 `evaluation_report`；L1a 失败阻止 publish；用户无需读内部字段即可回答“是否按计划、哪里新增、最该改什么、影响什么”；刷新、重启和恢复后确认状态不丢失；口播/BGM 选择与样片实际音轨一致；现有 Backlot、compose、publish 回归测试通过。

### P1：创意可比较、可批量、可局部修改

#### P1-1 Hook Plan 与参考字幕风格

- 将 Hook Plan 写入 proposal / creative control plan：前 1–1.5 秒画面、第一听觉信息、承诺、真实证据和候选差异。
- 新增 `CaptionStyleFingerprint`：字体风格、字号、字重、描边、位置、安全区、断行和入场动效；没有参考片时标记“不适用”。
- Remotion 只按样式制品渲染，不复制参考片字体文件或素材。

#### P1-2 五条候选编排

- 新增 `candidate_batch` 索引；候选独立保存 proposal、script、scene_plan、sample 和 `evaluation_report`。
- Research、事实证据、素材清单和原创边界共享；只在钩子、节奏、包装、人群或时长上分叉。
- 首期 5 条，最大并发 2–3 条；统一比较评分、成本、失败原因和执行差异。
- 用户选择 1–2 条后才能进入精剪，不自动发布全部候选。

#### P1-3 四种局部修复

先支持 `rewrite_hook`、`edit_caption`、`replace_asset`、`shorten_shot`。每次修复都生成新版本、追加 `decision_log`、生成 `change_impact`，并按影响范围选择 still、sample 或 full render。

**P1 验收：** 一次 Research 稳定产出 5 个候选；候选共享同一事实和原创边界且有独立版本；审核台能横向比较前 3 秒、评分、音频和差异；用户可在一个页面选 1–2 条进入精剪；局部修改不清空镜头、不回退阶段、不静默改变锁定规则。

### P2：质量学习与十条候选

- 候选扩展到 10 条，增加成本、时延和失败重试预算。
- 建立 Gold / Silver / Bad / Hard Negative 样本集、`judge_version` / `rubric_version`、replay scoring 和人工一致性校准。
- 回流线上发布数据和人工评价；只有数据稳定后才考虑自动学习或奖励建模。

**P2 验收：** 评价版本可重放，评分变化可解释；规则或模型升级不会降低事实一致性和硬门通过率；线上数据只作为后验反馈，不替代前置人工确认。

### 实施顺序与测试门

1. 先完成 P0-0/P0-1，并用 v7 生成第一张完整评价卡。
2. 再完成 P0-2/P0-3，确认样片真正成为 edit 的进入门。
3. P0 全部回归通过后实施 P1-1，再实施 P1-2，最后实施 P1-3。
4. P2 必须在至少一轮 5 候选比较稳定后启动。

每个实现 PR 必须同时提供 schema/contract 测试、核心单元测试、v7 集成回归和 UI 契约测试。重点覆盖：L1a 失败、缺音频、无参考片、候选失败、重复提交、服务重启、效果确认未完成和局部修改影响传播。

## 7. 裁剪与封存清单

以下内容从当前实施范围移出，只保留概念或接口占位：

1. Phase 4 Market Loop、Phase 5 MetaGrowthHarness；
2. Uplift、总 Reward 在线项、Canary/Rollback 全套；
3. L5/L6、F/G/H 失败类、完整 Train/Dev/Test 纪律；
4. Acceptance Gate 全文、Gold Set 在线 CTR/residual/uplift 字段；
5. 14 张增长轨迹表、完整 Harness Component Registry；
6. `asset_binding` / `timeline_ir` 等大 IR，当前只保留 CreativeBrief、ScriptIR、ShotIR；
7. Top-K exploration、70/20/10 和自动发布，当前只做 Top-1/Top-2 人工放行；
8. `jianying-poc` 的历史 `make_draft.py` / `make_draft_v2.py` 归档，主路径收敛到 exporter → jy CLI。

清理代码时不得删除仍被 v7 或审核台引用的 artifact、checkpoint、QA 和渲染路径；先确认调用关系，再归档历史脚本。

## 8. 文档治理与实施纪律

- 本文只记录当前裁定、实施顺序和验收标准；历史文档保留研究依据，不重复维护另一份优先级。
- 每个实现 PR 必须标注对应的 P0/P1/P2 条目、artifact/schema 变化、用户可见变化和回归测试。
- 生产关键路径发现能力缺口时，先写入 `decision_log` 的 `capability_extension`，继续使用已批准路径；确实阻塞交付才暂停并升级。
- 评价、批量、字体和音频是相互依赖的，但不要一次性建设完整增长平台：先让一条片可评价，再让五条片可比较，最后才做十条片和线上学习。

## 修订记录

- **v2.20（2026-08-23）跨项目审批一致性契约落地（契约 B）**：
  - `operator_review` schema kind += `script_lock`；`ReviewService.ensure_script_review_for_checkpoint`（检查点派生 formal review，script 门必须引用 script_lock review）+ `decide` 支持 script_lock（stage=script，检查点直批 + 下阶段推进）；load_operator_state 在 script 阶段自动补 review；
  - `backlot/batch_actions.py` 重写为协调器：`batch_approve_gate`/`batch_select_for_edit` 请求携带 `aggregate_revision` + participants（review 快照；script 门空快照由服务端从检查点派生回填）；协调记录 `operator/batch-actions/<id>.json` 状态机（preparing/prepared/committing/committed/rejected/needs_recovery/replayed + 参与者状态与 commit marker）；prepare 阶段校验批级+逐候选 review 权限、归属 containment、快照服务端重读（不信任客户端）、sample 五项确认必须全 pass；commit 逐候选原子提交 + 每候选 decision_log 追加 `batch_approval`（新类别，带 batch_action_id + review_snapshot）；崩溃后 `recover_batch_action` 续跑（`POST /batch/actions/{id}/recover`），无法继续 → `needs_recovery`(503) 绝不静默覆盖；
  - `OperatorError` 支持 `details`（失败响应携带 batch_action_id/participant_errors/current_revisions/retryable）；新增错误码 `stale`(409)/`needs_recovery`(503)；
  - 幂等：同 key+digest → `replayed`（状态弹出避免覆盖）；同 key 异 digest → 409；replay 检查先于 revision 校验（提交后重放不受 revision 前进影响）；
  - 前端 api.js/renderBatch 对齐契约（aggregate_revision、participants 快照、needs_recovery 续跑按钮、stale 自动刷新）；
  - 故障注入测试 11 例：prepare 快照不匹配无副作用（rejected 记录）、确认项非全 pass 拒绝、单候选无权限整体拒绝、commit 中途注入故障 → needs_recovery → recover 续跑完成、提交后重放 replayed、key 复用冲突、stale、script 检查点派生审批、审计追溯（候选 decision_log batch_action_id）。

- **v2.19（2026-08-23）批级聚合状态与事件契约落地（契约 A）**：
  - 新增 `backlot/batch_state.py`：批级只读投影——`batch_review` 载荷按契约 §2（schema_version/kind/batch_id/aggregate_revision/snapshot_at/consistency/phase 八态/phase_reason/rail 六相/candidates[status 保留原始值 + candidate_phase 机器值 + child_revision + stage_states + pending_reviews + score/media/cost/links/failure]/budget[cost_tracker 权威 + 索引比对降级]/concurrency/selection[eligible_candidate_ids]/pending_gates/warnings）；相位归约按 §3（失败/缺失候选不阻塞相位；over_budget 或全灭才 blocked；rework 相位回退 → aggregate_revision 变化）；一致性 stable/unstable（读取期间二次复核）/degraded（缺失/损坏/预算不一致/超预算）；
  - 新增 `backlot/batch_events.py`：append-only `operator/batch-events.jsonl` 事件流（8 类事件、event_seq 严格递增、event_id 去重、detect_gap 缺口检测、last-snapshot 去重的 publish_snapshot：变化候选发 candidate_changed + snapshot_published；修复 flock 重入死锁）；`GET /api/v2/projects/{id}/batch/events?after_seq=` 补拉端点；批页每次拉取 operator-state 即发布快照事件；
  - 修复 script 门审批路径（ReviewService 只有 creative_lock/sample review：script 门直批 awaiting_human script 检查点，assets/sample 门走 ReviewService.decide，不匹配/已决 → 跳过而非失败）；
  - 验收测试：1/2/5/10 候选矩阵、全失败 blocked、缺失/损坏降级 + warning、预算不一致 degraded（以 cost_tracker 为准）、读取期间子项目变化 unstable、相位回退 revision 变化、事件去重/递增/缺口/快照发布去重（21 例批级 + backlot 全量 271 passed）。

- **v2.18（2026-08-23）代码评审 3 个 P1 门禁漏洞修复**：
  - **P1-① accepted/passed 重算验证**：`lib/optimization_run` 新增 `_verify_pass`——`record_iteration(outcome="accepted")` 与 `record_confirmation(passed=True)` 按冻结 `policy_snapshot` 重算（weighted_total≥阈值、无 failure_dimensions、`dimension_scores` 必填且 required 维度齐全、每维≥单维阈值），不达标抛 `ValueError` 拒绝（此前只信调用方，weighted_total=0 也能 accepted）；
  - **P1-② 确认失败立即 repair**：`record_confirmation` 任一次 `passed=False` 立即切回 `running`（失败维度保存在 `confirmation.runs[-1]`），不再执行下一次确认；修复后需 `start_confirmation(reset=True)` 重新确认；
  - **P1-③ 校准门覆盖全部维度**：`calibration_report`/`is_judge_releasable`/`assert_judge_releasable` 新增 `required_dimensions`（policy/rubric 完整必评维度集）——未覆盖维度显式 `total=0/sufficient=false`，未覆盖全部维度不得 releasable（此前只校验 Gold Set 中实际出现的维度，两维达标即可放行）；
  - 技能文档同步：optimize-director 校准门（assert + required_dimensions）与 record_iteration/record_confirmation 新契约；
  - 测试：状态机 +6（accepted 不达标拒绝×5、确认重验、首次失败立即 running）、校准 +2（缺维阻断、断言升级）；全量回归 **1802 passed / 11 skipped / 0 failed**。

- **v2.17（2026-08-23）批量混剪闭环补齐（Autoresearch 落地方向 + 评审缺口 #1-#8）**：
  - **① 优化数据层**：新增 `optimization_policy`（权重和=1.0、阈值、beam/并发/迭代/预算/plateau，enabled=false 默认=人工 review 优先）与 `optimization_run`（planned/running/awaiting_confirmation/passed/exhausted/blocked/failed 状态机 + policy 冻结快照 + history/mutation 指纹 + confirmation）schema + 规范校验；`lib/optimization_scoring`（统一分数聚合：非法分拒绝、缺维失败、7.99/8.49 边界、rubric 一致、judge 未校准 → shadow mode）；`evaluation_report.optimization` 区块 + `candidate_batch` §3.3 扩展（source_media_refs/iteration/lineage/mutation/维度分/加权总分/provider/model/runtime/output_ref）；`lib/optimization_run` 状态机（max_iterations→exhausted、失败候选不成 best、plateau/预算停止、两次确认全过→passed）；
  - **② judge fail-closed + L1a 补齐**：`video_judge` v0.2——非法分数/缺维直接拒绝（不再钳 0.0/静默跳过），rubric 感知（l3-v1.0 / ecommerce-remix-v1.0 各固定维度集），seed 可传；接入 sample/compose `required_tools` + director 契约；L1a 新增 `l1a_resolution`/`l1a_fps`（12 项，覆盖率阈值 7→9）；
  - **③ publish 三态语义**：fatal 一律阻止（checkpoint 硬门）、revise 需用户确认 + `downgrade_approval` 决策、optimization 启用时需 run passed + optimization.passed 双门（publish optional_artifacts_in: optimization_policy/optimization_run）；publish-director 重写；
  - **④ 批量编排机制**：`lib/batch_fork`（一次研究分叉 N 候选项目：共享制品 + analysis/ 派生证据 + completed research 检查点 + 候选元数据）；`lib/render_payload`（确定性 render payload assembler，captionStyle/audio.mix/captionWordsPerPage 派生字段）；`lib/music_profile`（music_profile→检索词映射，含 v8 Indie Acoustic 用例）；`optimize-director` skill（人工 review 优先 runbook + 自动迭代纪律 + 停止条件 + 并发/预算）；
  - **⑤ 样片审核页**：`_sample_editor` payload 增加 sample 范围评价卡（复用 `_evaluation_summary`）与口播/BGM/原声三轨（audio_diff 驱动）；operator_state schema + app.js 渲染 + CSS；board 投影对旧式无后缀报告按内嵌 scope 别名（v8 实况验证）；
  - **⑥ Gold Set release gate + 修复回评**：`gold_set.py` 新增 `per_dimension_stats`/`calibration_report`/`is_judge_releasable`/`assert_judge_releasable`（每维 n≥100 + 双人标注 + kappa≥0.6 才允许生产门禁，否则 shadow mode）；`repair.py` 新增 §5 维度→修复动作映射（音频/原创维度明确需 rework）与 `keep_or_rollback`（总分提升且目标维度不倒退才保留）；
  - **小件**：`python -m backlot validate <project> [--refresh]`（信封/schema/派生文件全链校验，v8 实测 9 检查点 VALID）；`skills/meta/voice-timeline-fit.md`（v8 TTS 实测时长适配流程固化）并挂入 sample-director；
  - 验证：全量回归 **1798 passed / 11 skipped / 0 failed**（较 v2.16 净增 70 例）；v8 样片页实况投影出评价卡 + 三轨音频。Autoresearch 文档标注为"设计稿，待实现"的核心数据层（policy/run/scoring）已落地；真实 5 候选批量生产与 Gold Set 标注仍为用户发起项。

- **v2.16（2026-08-22）代码评审 P2 六项 + v7/v8 存量契约修复**：
  - **#10 SUNO callBackUrl 配置化**：`suno_music` 不再硬编码占位回调——`SUNO_CALLBACK_URL` 环境变量可覆盖，缺省为明确标记的 `suno-callback.invalid` 占位域名（轮询模式不会被真正调用），install_instructions 同步说明（+2 测试）；
  - **#11 回填幂等/原子/事务**：`backfill_evaluation_report.py` 全部写入走 `write_artifact_atomic`（优先 ProjectCommitStore 事务 sink，失败回退直接原子写）；scoped 文件已存在即跳过、decision_log 回填条目按 decision_id 幂等去重（+5 测试）；
  - **#12 subject_hash 非空约束**：`evaluation_report` schema 的 `subject_hash` 要求 64 位 hex；`technical_validator` 缺失/非法即 fail fast（不产出无版本报告）；v8 两份空 subject_hash 报告经 `--repair` 从 subject artifact 的 semantic_sha256 确定性回填，其余字段不动（+3 测试 + v8 实修）；
  - **B1 checkpoint 信封自动刷新**：`lib.checkpoint` 新增 `refresh_checkpoint_envelopes`（全项目）/ `sync_checkpoint_envelopes`（单检查点）/ `persist_checkpoint_atomic`（只校验本检查点+前置，不做 decision_log 全量 resync）——从磁盘制品重建全部 v2 信封、按阶段序原子写回（history 归档），信封漂移一键修复（+3 测试）；
  - **B2 像素归一化补全**：`VideoCompose._normalize_to_yuv420p`（yuvj420p→yuv420p/tv 原地重编码，ffmpeg 失败不阻断渲染）接入 `_render_via_atelier` 无 profile 路径并记录 `post_encode`（`_render` 高路径的 `_normalize_render_to_profile` 此前已固化）（+3 测试）；
  - **B3 research 派生文件完整性**：`validate_research_derived_files`——research 制品（breakdown/matrix/fingerprint 的 evidence_frames/evidence_refs）引用的 `analysis/` 派生证据帧缺失即门失败；接入 cinematic-fast research completed 检查点校验（v8 analysis/ 迁移事故的代码级防护）（+3 测试）；
  - **v7/v8 存量修复（9+9 检查点恢复 VALID）**：v8 → `--repair` 回填 2 份报告 subject_hash + 信封刷新；v7 → 契约回填 `research+caption_style_fingerprint`（由 research_breakdown 重建）、`proposal+hook_plan`（由 creative_control_plan+script 重建）、`sample/compose+evaluation_report`（scoped 文件信封），全部经 store 事务原子写回；审核台成片评价卡恢复（final 报告带真实 subject_hash）；
  - 验证：全量回归 **1728 passed / 11 skipped / 0 failed**（较 v2.15 净增 17 例）；v7/v8 各 9 个检查点 `read_checkpoint` 全部 VALID。

- **v2.15（2026-08-22）代码评审 P1 八项修复（门安全 + 契约 + 接线）**：
  - **#4 production_lock 绕过**：`build_production_lock` 建锁前校验输入——完整 v2 信封的哈希必须与其内嵌 content 一致（伪造"声明哈希 + 篡改 data"被拒）、带 `data` 的非完整信封拒绝、`_unwrap` 只解包完整信封；`lib/artifact_hashing.canonical_bytes` 新增路径化 JSON 纯值检查，callable/自定义对象等对象脚本输入抛带路径的 TypeError（+4 测试）；
  - **#5 L1a skip→pass 覆盖阈值**：`technical_validator` 新增 `MIN_EXECUTED_CHECKS=7`——非 skip 执行数不足时追加 `l1a_coverage` 可修复检查项，报告转 revise（不再 pass）；`evaluation_report` schema `hard_gate.coverage`（executed/total/minimum/sufficient）+ 规范校验（coverage 不足时 status/hard_gate.pass 不得为 pass）（+2 测试）；
  - **#6 批次总额预算**：`record_candidate_result` 由"每候选 vs 整批上限"改为"批总额 + 增量 vs max_cost_usd"（+1 测试）；**#7 候选状态伪造**：状态转移表（planned→in_progress→sampled→evaluated→failed 回 in_progress；selected_for_edit 仅经 select_for_edit）、evaluated 必须带 evaluation_report_ref / sampled 必须带 sample_ref、select_for_edit 拒绝无评价引用的 evaluated（+4 测试）；
  - **#3 evaluation_report 命名不互踩**：`lib/artifact_io.scoped_artifact_path/relative_path`（SCOPED_ARTIFACTS：evaluation_report×sample/final）；`backlot/state._collect_artifacts` 独立投影 `evaluation_report.sample/.final` 键，默认键取 final；`operator_state._delivery_editor` 优先读 `evaluation_report.final`（v8 实况修复：默认键此前读到 sample 范围报告）（+3 测试）；
  - **#8 trace 误报匹配**：`_matches_plan` 的代理路径判定由"任意含 shot 标记+proxy 子串"收紧为证据驱动——计划文件词干（≥3 字符）出现在代理文件词干，或代理文件词干精确等于规范 `<marker>-proxy`（v8 真实 shot-01-proxy 命名保持 executed；`backup-shot-01-proxy-old` 之类误判为 partial）（+3 测试）；
  - **#9a 指纹管线接线**：cinematic-fast sample/compose `required_artifacts_in += caption_style_fingerprint`；compose-director 契约段明确"必读指纹→`to_overlay_spec`→render payload，not_applicable 才省略"（管线契约断言 +2）；
  - **#9b 安全区单一数据源（120 vs 300）**：指纹 `style.bottom_offset_px`（缺省 120）→ `to_overlay_spec.bottomOffsetPx` → `CaptionStyleSpec.bottomOffsetPx`/`CaptionOverlay` paddingBottom（替代硬编码 120）→ QA 侧 `caption_box_for_cue`/`is_inside_safe_zone`/`boxes_in_social_safe_zone` 支持 `bottom_margin_px` 覆盖（替代硬编码 300）；`final_qa`/`technical_validator` 的 caption_declaration 携带 `bottom_offset_px` 时盒计算与校验同源（`final_review.caption_render` 记录该值）；顺带修复 `layout_captions.bottom_margin` 死参数；
  - 验证：全量回归 **1711 passed / 11 skipped / 0 failed**；tsc --noEmit 通过；vitest 9/9 通过；E2E（cinematic-fast 集成）与 v7 回填报告兼容（coverage 为可选字段，旧报告仍合法）。存量项目（v7/v8）不动：旧报告无 bottom_offset_px 时 QA 保持平台默认 300 行为。

- **v2.14（2026-08-22）代码评审 P0 两项修复（final_qa 门语义）**：
  - P0#1 `final_qa` 返回语义：`ToolResult.success` 由 `status != "fail"` 改为 `status == "pass"`（原实现中 status 只有 pass/revise 两态，`!= "fail"` 恒为 True，revise 结果也返回 success=True，下游无法区分）；
  - P0#2 字幕声明但成片无证据：`subtitles_expected and not subtitles_present` 时新增 issue `"subtitles declared but not present in render"` → status 由 pass 转 revise（此前字幕声明了但渲染无字幕流/无像素证据仍判 pass）；status 计算点随之下移（先完成全部 issue 采集再定级）；
  - 测试：`test_subtitle_stream_declared_but_missing_from_render_revises` 按新语义断言 revise + 不 success + issue 出现；全量回归 1689 passed / 11 skipped / 0 failed。

- **v2.13（2026-08-22）修复"成片评价卡不可见"（页面路由根因）**：
  - 根因：用户审核台为 `/p/<id>`（operator.html 运营工作台），而此前评价卡加在 `board.js`（挂在 `/diagnostics/p/<id>` 的诊断板）——用户看不到属页面归属错误；
  - 修复：① 后端 `operator_state._delivery_editor` 在 compose/publish 成片 payload 增加 `evaluation`（final 范围评价卡：status/recommended_action/judge_version/hard_gate_fails/L3 八维）② 前端 `operator/app.js` 的 `renderDelivery` 在成片播放器下方渲染"成片评价卡"（状态色、失败项、八维分数带颜色与理由）③ `operator_state.schema.json` 注册 `delivery_evaluation`（含 test fixture 兼容）；
  - 验证：payload 实查 status=revise、8 维、1 个 fixable 失败项；operator 契约测试 36 例通过；全量 1689 passed / 0 failed；服务器已重启。
- **v2.12（2026-08-22）成片阶段评价卡展示**：审核台 `renderRenders`（compose 成片生成视图）在成片视频下方新增"成片评价卡"——final 范围 `evaluation_report`（L1a 门状态 + 修复建议 + L3 八维分数带颜色与理由 + judge 版本）；`renderEvaluationCard` 增强维度分数渲染（≥8 绿 / ≥6 黄 / <6 红）；`node --check` 通过。
- **v2.11（2026-08-22）成片质量评估补全：L3 VLM advisory 落地**：
  - 新增 `tools/analysis/video_judge.py`（DashScope Qwen-VL：均匀抽帧 → L3 八维 rubric 打分 0-10 + 每维理由 + 总结；输出 `creative_advisory`，advisory 不进硬门）+ 3 单测（分数钳制/维度过滤/非 JSON 报错）+ dashscope 发现契约更新；
  - 对 v8 成片实跑：Hook Clarity 7.0（钩子略平淡，可行动洞察）、Visual Hierarchy 9.0、Rhythm 8.5、Shot Quality 9.0、Story Coherence 9.0、Audio Quality 8.0、Text Readability 8.5、Product Presence 9.0；
  - `evaluation_report.final.json` 合并 advisory（judge_version = technical_validator-0.1.0 + video_judge-0.1.0），compose 检查点信封刷新，九检查点全链 VALID；
  - 全量回归 1689 passed / 11 skipped / 0 failed。
- **v2.10（2026-08-22）v8 全链路收官（P0-3 完整达成）**：
  - 用户"样片通过"→ edit（change_impact no_render，忠实记录零变更）→ compose（全片 15s 1080×1920 带音频渲染：豆包口播混音 + Indie Acoustic BGM + 硬切字卡；修复交付像素格式 yuvj420p→yuv420p 使 final_qa 由 revise 转 **pass**）→ publish（本地交付包 + 标题/描述/话题）；
  - final 范围评价卡：L1a 无 fatal（仅字幕像素级证据缺失 fixable，publish 决策记录放行）；final_review pass；九个检查点全部 completed 且 VALID；
  - 全量回归 1686 passed / 11 skipped / 0 failed。**P0 全项（含 P0-3 实机验收）完成。**
- **v2.9（2026-08-22）参考字幕样式 1:1 复刻（样片 v3）+ 用户确认**：
  - 从参考片研究拆解提取真实样式：短促卖点字卡（贴合桌面/防刮耐磨/防水防油…）、硬切随动作出现（effect_treatment：硬切；动作先行/动作跟随/动作匹配切）、无背景块；关键帧颜色网格采样确认白字区域；
  - 修复两处渲染缺陷：① `_map_entrance` 增加"硬切"→`none`（无淡入/弹出，瞬时出现）② `CaptionOverlay` 有 captionStyle 时 null 背景不再落入主题背景条（此前"大方块"根因：transparent 被 `??` 回退成主题背景色块）；
  - 指纹更新（硬切/无背景块/白字黑描边/Noto Sans CJK SC 近似），样片 v3 重渲染 + 全制品刷新；**用户确认：白字黑描边 + 该字体即为参考样式**；
  - 测试：tsc 全绿、vitest 全过、python 全量 1686 passed / 0 failed；sample v3 重新 awaiting_human 等五项效果确认。
- **v2.8（2026-08-22）修复审核台 research/分镜切片黑屏**：
  - 根因：v8 复用 v7 研究时仅复制了 JSON 制品与输入媒体，遗漏 `analysis/` 目录（research_breakdown 引用 32 个证据帧路径，如 analysis/reference/keyframes/frame_*.jpg）→ 审核台预览指向不存在的文件 → 黑屏；
  - 修复：将 v7 `analysis/`（29MB，同参考片同素材的派生证据）完整复制到 v8；确认板上所有媒体均为浏览器可解码格式（参考片/样片/代理均为 h264 yuv420p 系）；分镜卡 scene_id 与素材 scene_id 对齐（shot-01..07）；
  - 复用纪律教训：研究制品复用必须连同其派生的 evidence/analysis 文件一起迁移（已记入 research 复用决策的范围说明）。
- **v2.7（2026-08-22）P1-3 生产实战：样片 v2 三项修复**：
  - 用户反馈三项：① 字幕居中挡画面 ② 多条字幕挤在一起 ③ BGM 偏摇滚不像参考片；
  - 修复：① CaptionOverlay bottom 位置贴底（paddingBottom 300→120，不挡主体）② Explainer 新增 `captionWordsPerPage`（=1：每屏一条卖点）③ BGM 换 pixabay "Indie Acoustic" 30s 暖色调；
  - 按 P1-3 实战走完整修复流：`repair_caption_001`（edit_caption/caption_overlap）+ `repair_bgm_001`（replace_asset/**新增 issue_tag `music_tone_mismatch`** 枚举扩展）+ decision_log 两条 rework_cause + 指纹位置更新 + 样片重渲染 + 全制品/检查点刷新（research/proposal 信封因下游 artifact 更新同步刷新）；tsc/vitest/全量 1686 passed 全绿；sample v2 重新 awaiting_human。
- **v2.6（2026-08-22）P0-3 音频信号级验收 + P1-2 真实数据演练**：
  - 样片音频分段能量验证：s01-s04 口播窗口 RMS -28.8/-24.2/-21.6/-31.0 dB（口播实落在段落时间点），全片 -16.4 LUFS / Peak -3.2 dBFS（loudnorm 生效）——与 audio_diff=executed 构成"选择与音轨一致"的双重证据；
  - P1-2 真实数据演练：`projects/batch-table-mat-demo/candidate_batch.json` 注册两真实候选（C1=v7 无音频画面主导/evaluated，C2=v8 口播+BGM+参考字幕/sampled，共享研究 refs，packaging 轴分叉），selection 留空待 v8 样片确认后由用户选择——演示了批索引、状态机与"不自动发布"纪律。
- **v2.5（2026-08-22）P0-3 实机验收达成（v8 样片带音频闭环）**：
  - 创意锁批准 → 素材落地：7 段代理（复用 v7 同源）+ 豆包 TTS 口播 6 段（实测时长驱动，语速调优后全部落入段落槽位：s01 1.99s/2.3s、s02 2.04s/2.4s、s03 2.04s/2.3s、s04 2.06s/3.4s、s05 2.62s/2.7s、s06 1.70s/1.9s）+ pixabay BGM 18s；口播混音 15s 按段落起点 adelay 对齐 + loudnorm -16 LUFS；
  - 样片渲染成功：`renders/sample-v1.mp4`（540×960，10.05s，300 帧，AAC 双声道；字幕按参考指纹 Noto Sans CJK SC 近似/白字黑描边/淡入）；final_qa pass；
  - **执行对照 audio_diff=executed**（口播：计划有/实际有；BGM：计划有/实际有）——P0 验收"口播/BGM 选择与样片实际音轨一致"成立；evaluation_report=revise（仅 l1a_subtitle_bounds 像素级证据缺失一项 fixable，与 v7 同源的历史 gap）；
  - v8 管线现停 **sample awaiting_human（五项效果确认）**，随后 edit → compose（全片带音频）→ publish 完成 P0-3 全链路。
- **v2.4（2026-08-22）BGM 路径实机验证**：pixabay 音乐检索冒烟通过（"upbeat light electronic" → 18s 曲目，Pixabay Content License 免费无署名要求，min/max_duration 过滤生效）；sample 阶段三个音频/视觉依赖全部就绪（豆包 TTS 词级时间戳 ✅、pixabay BGM ✅、参考字幕样式渲染 ✅）。v8 当前停在 assets 创意锁 awaiting_human（等"批准素材"）。
- **v2.3（2026-08-22）P1-1 渲染通道实机验证通过**：Remotion 真实渲染冒烟（3s/90 帧，captionStyle：Noto Sans CJK SC + 48/58 字号 + 白字黑描边 3px + fade + bottom）——渲染成功 586KB mp4，帧亮度对比（下 1/3 YAVG=41.8 vs 上 1/3 YAVG=34.8）确认字幕按样式落在底部。v8 状态：research/proposal 完成，**script awaiting_human 已等 3 轮**；BGM 待用户决策（SUNO credits 不足）。
- **v2.2（2026-08-22）测试套件首次全绿**：
  - 修复 `tests/integration/test_cinematic_fast_end_to_end.py` 的存量失败与 P1 契约引发的 fixture 缺口：E2E 研究/proposal/sample/compose/publish 检查点补入新制品（caption_style_fingerprint / hook_plan / sample_execution_trace / evaluation_report）并新增对应 fixture；`source_media_review` 文件补 `media_id`（source-1/source-2）以桥接 `_matches_matrix_source` 的研究矩阵源校验；
  - 全量回归 **1686 passed / 11 skipped / 0 failed**（首次无失败，此前唯一的存量失败已消除）。
- **v2.1（2026-08-22）v8 生产验证启动 + SUNO 工具修复**：
  - `projects/table-mat-mix-v8` 启动（cinematic-fast，P0-3 实机验证载体）：research 复用 v7 九制品 + 新建 `caption_style_fingerprint`（needs_review，Noto Sans CJK SC 近似/白字黑描边 3px/整句淡入，`to_overlay_spec` 映射已验证）→ proposal 完成（hook_plan result_first + 决策：口播=豆包 TTS、BGM=SUNO）→ **script awaiting_human**（六段证据链沿用 v7 + 音频计划）；
  - `suno_music` 工具修复三处（冒烟暴露）：① `data:null` 响应 None 崩溃 → None 安全解析并透出 API 原始错误；② callBackUrl 必填（sunoapi.org 400）→ 轮询模式用占位回调；③ 音轨列表防御解析 `_extract_tracks`（data.data / response.sunoData / response.tracks 多形状）+ 3 单测；
  - **阻塞**：SUNO 账户 credits 不足（API 429），BGM 待用户决策（充值 SUNO / 批准换 pixabay / 暂缓）；全量回归 1685 passed / 11 skipped / 1 failed（唯一失败仍为存量基线集成测试）。
- **v2.0（2026-08-22）P2 数据层与校准协议已落地**：
  - `candidate_batch` 扩展 P2 预算契约：`budget`（max_cost_usd / max_latency_minutes / max_retries_per_candidate）+ 候选 `attempts` 计数；`record_candidate_result` 拒绝超预算成本与超限重试（`is_retry=True` 计数）；max_candidates 上限 10、max_parallel 上限 5 已支持；
  - 新增 `gold_sample` artifact：四层样本（gold/silver/bad/hard_negative）+ group_key（Group Split 防同模板泄漏）+ labels（pointwise/pairwise_refs/claims_qa 含时间戳证据/failure_tags/expert_reason/human_adoption/online_outcome 接口占位）+ 双人标注 annotators + split；规范校验：样本 id 唯一、hard_negative 必须带 failure_tags；
  - 新增 `lib/gold_set.py`：create/add_sample（硬负样本强制 failure_tags）、`assign_group_split`（固定 seed 按组整体切分，可复现）、`cohens_kappa`（双标注 IRR）、`bootstrap_ci`（分位数 bootstrap）、`replay_score`（judge 版本重放：stored vs judged 分数差 + hard_gate_failure_increase 退化标记）；
  - 新增 `skills/meta/judge-calibration.md`（n≥100/维、双人+仲裁、kappa≥0.6 起步、分维 bootstrap CI、replay 退化不发布、线上数据仅后验）与 batch-producer P2 段（10 候选 + 预算纪律）；
  - 审核台 board.js 新增 gold_sample 卡（四层计数 + judge/rubric 版本）；测试 9 例（含预算与重试拒绝）；全量回归 1682 passed / 11 skipped / 1 failed（唯一失败仍为存量基线集成测试）。
- **v1.9（2026-08-22）P1-3 已落地（P1 全部完成）**：
  - 新增 `repair` artifact：四种动作 rewrite_hook/edit_caption/replace_asset/shorten_shot × 默认最小渲染路线（sample/still/sample/full_render）× 目标清单 × issue_tags（决策契约枚举）× production_lock_hash + lock_compliant × affected_shot_ids/affected_stages；规范校验：lock_compliant 必须为 true、shorten_shot 必须 full_render；
  - 新增 `lib/repair.py`：`plan_repair`（动作/目标/路线校验、issue_tags 默认映射 weak_hook/caption_overlap/cover_mismatch/slow_start）、`assert_lock_unchanged`（锁 hash 不符 → 报错要求走重新审批而非修复）、`repair_decision_entry`（category=rework_cause + issue_tags + rework_round 的 decision_log 条目）；
  - 新增 `skills/meta/repair.md`：四种动作影响范围、五条纪律（不动锁/不清空/不回退/留痕/复审不劣化）、修复流程；
  - 审核台 board.js 新增 repair 卡（动作/渲染路线/轮次/目标/问题标签/影响阶段，`node --check` 通过）；
  - 测试：6 例（默认路线表、非法动作、shorten_shot 路线强制、锁不变校验、decision 条目形状）；全量回归 1673 passed / 11 skipped / 1 failed（唯一失败仍为存量基线集成测试）。
- **v1.8（2026-08-22）P1-2 已落地（数据层 + 编排技能 + 审核台卡）**：
  - 新增 `candidate_batch` artifact（batch 索引：共享研究 refs、并发配置 max_candidates≤10/max_parallel≤5、五轴分叉 hook/pacing/packaging/audience/duration、候选状态机 planned→in_progress→sampled→evaluated/failed→selected_for_edit、selection≤2）+ 规范校验（候选数≤上限、id 唯一、被选候选必须 evaluated/selected_for_edit）；
  - 新增 `lib/candidate_batch.py`：create / record_candidate_result（成本累加、失败记录）/ select_for_edit（≤2 且必须 evaluated，拒绝自动发布）；
  - 新增 `skills/meta/batch-producer.md`：一次研究 → 建批 → 分叉 N 候选独立项目（各自 hook_plan/合同/checkpoint）→ 2-3 并发纪律 → 统一 scorecard 排序 → 人工选 1-2 条精剪；共享研究只读纪律；
  - 审核台 board.js 新增 `candidate_batch` 对比卡（候选状态/方向轴/成本/失败/评价卡与样片引用/已选标记，`node --check` 通过）；
  - 测试：builder+契约 8 例；全量回归 1667 passed / 11 skipped / 1 failed（唯一失败仍为存量基线集成测试）。**真实 5 候选生产运行属编排执行（依赖 P0-3 音频与人工 gates），留待用户启动批量项目时验证。**
- **v1.7（2026-08-22）P1-1 渲染参数化收尾（P1-1 全部完成）**：
  - Remotion 字幕样式通道：`SafeCaptionTrack.tsx` 新增 `CaptionStyleSpec` + `resolveCaptionOverlayStyle()`；`CaptionOverlay.tsx` 按样式渲染（fontFamily/fontSize/强调字号/字重/填充/描边 WebkitTextStroke/背景条/透明度/位置 bottom|center|top/入场 pop|fade|slide_up|none）；`Explainer`（v7 的 product-reveal → Explainer 路径）与 `CinematicRenderer` 均透传 `captionStyle`；
  - Python 侧 `lib.caption_style.to_overlay_spec(style)` 产出与 TS `CaptionStyleSpec` 同构的规范（position/entrance/weight 枚举映射），compose-director 明确 `caption_style` 为 render-payload 派生字段（不进 canonical edit_decisions），不搬运参考字体文件；
  - 测试：python +2（to_overlay_spec 映射与最小输入）+ vitest +2（默认值与 Python 映射镜像）；`tsc --noEmit` 通过；全量回归 1659 passed / 11 skipped / 1 failed（唯一失败仍为存量基线集成测试）。
- **v1.6（2026-08-22）P1-1 已落地**：
  - 新增 `hook_plan` artifact（hook 窗口/前 1-1.5s 画面/第一听觉/承诺/真实证据/hook_pattern 枚举/候选差异，全部自然语言）+ 规范校验（窗口 ≤5s、end>start、画面与听觉非空）；`creative_control_plan` 增加可选 `hook_plan_ref`（向后兼容）；
  - 新增 `caption_style_fingerprint` artifact（applicability: extracted/needs_review/not_applicable；字体族/字号层级/字重/填充/描边/阴影/背景条/位置/安全区/断行/入场与强调动效/同步模式；binding 区分品牌必须保留规则与参考片表现手法）+ 规范校验（extracted/needs_review 必须带 font_family 与 size_hierarchy）；Remotion 只按样式制品渲染、不搬运参考字体文件的约束写入 schema 描述；
  - 构建器 `lib/hook_plan.py`（从创意合同+剧本派生，overrides 优先，非法 pattern 报错）与 `lib/caption_style.py`（从 research_breakdown 的 overlay_text/evidence_frames/effect_treatment 种子提取，无字幕参考 → not_applicable，有字幕 → needs_review 待人工修正字体度量；overrides 深度合并）；
  - 管线接线：cinematic-fast research `produces += caption_style_fingerprint`、proposal `produces += hook_plan`；research/proposal director 技能补 P1-1 契约段；集成测试研究夹具补 fingerprint 制品；
  - 测试：契约 8 例 + 构建器 5 例 + 管线断言 2 处；全量回归 1657 passed / 11 skipped / 1 failed（唯一失败仍为存量基线集成测试）。**P1-1 的 Remotion 渲染参数化（按样式制品渲染字幕）留待下一步。**
- **v1.5（2026-08-22）P0-3 音频方案决策**：口播 provider = **豆包 TTS**（用户确认）。实机冒烟验证通过：seed-tts-2.0 / zh_female_vv_uranus_bigtts，13 字 → 2.86s 音频，返回词级时间戳（0.205s–2.505s，逐字 startTime/endTime），可直接驱动"TTS 实测时长驱动字幕/时间轴"（§6.4 契约）。BGM 待用户选择（建议 SUNO 生成或 pixabay 检索，key 均已配）；真实带音频样片将在下一个生产项目 sample 阶段生成验证。
- **v1.4（2026-08-22）P0-2/P0-3（契约部分）已落地**：
  - `sample_execution_trace` 扩展三类计划/实际差异（schema + builder 均向后兼容）：`audio_diff`（口播/BGM/原声，识别"计划了口播但实际无音轨"）、`caption_diff`（字幕数量与时间轴漂移）、`creative_rule_diff`（导演总控单规则的自然语言文本 + bound/not_in_sample/not_checked 状态，不暴露 `rules[0]` 等内部路径）；构建器输入集扩为含 creative_control_plan/research_breakdown；
  - 审核台 board.js 新增两卡渲染：`evaluation_report`（硬门状态、未通过项+影响镜头、修复建议、advisory 摘要、judge/rubric 版本）与 `sample_execution_trace`（音频轨/字幕/导演规则/镜头执行对照），替代原始 JSON dump（`node --check` 通过）；
  - P0-3 契约：`production_lock` 校验新增规则——存在口播文案时必须已选 TTS（provider/voice/selected）或 mix 带无音频理由（reason/no_audio_reason/note），否则锁不合法；sample-director 补"已选音频必须有真实音轨、无音频须有理由、TTS 实测时长驱动时间轴"契约段；
  - 测试：trace 三类 diff 4 例 + production_lock 音频规则 4 例 + 既有 lock 测试夹具按新契约更新；全量回归 1643 passed / 11 skipped / 1 failed（唯一失败仍为存量集成测试，基线同样失败）。
- **v1.3（2026-08-22）P0-0/P0-1 已落地**：
  - 新增 `schemas/artifacts/evaluation_report.schema.json`（subject_ref/scope/hard_gate/creative_advisory/execution_diff_ref/repair_targets/judge_version + v2 哈希信封），注册进 `ARTIFACT_NAMES` 并加三条规范校验（pass↔hard_gate 一致性、fail 须含 fatal、recommended_action 与 status 绑定）；
  - 新增 `tools/analysis/technical_validator.py`（L1a 十项：SKU/价格/参数/敏感词/字幕越界/黑帧/静帧/音画缺失/时长/音量；失败项带业务可读错误、证据位置、影响镜头、可修复性；fatal 阻止 publish）；
  - 抽取 `lib/qa_checks.py` 共享层（probe/decode/black/freeze/loudness/ranges），`final_qa` 委托共享层、行为不变（顺带修复原解析器只认 `key=value` 导致黑帧/静帧检测失效的问题，现兼容 `key:value`；-inf 响度归一化）；
  - `cinematic-fast` 契约：sample/compose `produces += evaluation_report` 且 `required_tools += technical_validator`；publish `required_artifacts_in += evaluation_report`；三个 director 技能补 gate 契约段；
  - 新增 `scripts/backfill_evaluation_report.py`：v7 已回填 `evaluation_report.sample.json`（status=revise：字幕像素证据缺失、响度 -70 LUFS 近静音）与 `evaluation_report.final.json`（status=revise：字幕像素证据缺失），decision_log 追加 capability_extension 条目，历史制品与 checkpoint 未改动；
  - 测试门：新增 3 个测试文件（契约/工具/共享层，共 19 例）；全量回归 1635 passed / 11 skipped / 1 failed——唯一失败 `tests/integration/test_cinematic_fast_end_to_end.py` 经 stash 对照验证为**存量失败**（基线 HEAD 同样失败，与本次改动无关）。
- **v1.2（2026-08-22）**：新增具体实施顺序、P0/P1/P2 子任务、接口落点、迁移兼容策略、测试门和可执行验收标准；明确已有能力不重复建设。
- **v1.1（2026-08-22）**：在初稿基础上补充 v7 从 research 到 publish 的完整复盘；明确已固化能力、部分固化能力和 Agent 临时发挥；补充评价体系、批量候选、Hook Plan、CaptionStyleFingerprint、口播/BGM、执行对照和用户决策链路；将 P0/P1/P2 改为带验收标准的实施入口，并收敛代码、UI、Skill、架构和文档治理边界。
- **v1.0（2026-08-22）**：基于三份设计文档的全文评审、四个关切裁定、17 项裁剪、8 处矛盾裁定和 v7 代码级核查形成初稿。

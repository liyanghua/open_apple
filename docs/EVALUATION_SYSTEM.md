# OpenMontage 总体评价体系

> 状态：Current Baseline
> 基线日期：2026-08-25
> 适用范围：OpenMontage 全部视频生产 pipeline、Backlot 审核台、批量候选与后续质量优化
> 文档角色：评价体系统一入口。历史设计稿保留论证和演进记录；发生冲突时，以代码、schema、pipeline manifest 和本文件标注的“当前实现边界”为准。

## 1. 目标与边界

OpenMontage 的评价体系不是一个“视频总分”，而是一组分层、可追溯、可执行的判断：

1. 当前阶段的产物是否满足合同；
2. 渲染结果是否技术可用、事实正确、合规且可交付；
3. 视频在创意和表达上是否值得继续；
4. 用户是否认可样片和最终版本；
5. 多个候选中哪个更适合进入精剪；
6. 发布后的真实业务表现是否有效；
7. 评价器本身是否经过校准、可比较、可升级。

当前代码已经较完整地覆盖前五项中的基础能力；第六项主要停留在业务设计；第七项已具备数据结构、统计 helper 和发布纪律，但还没有形成经过真实 Gold Set 校准的生产 judge。

本体系坚持以下边界：

- 质量、用户接受、线上表现和归因是不同事实，不互相替代；
- 技术或事实硬门失败，不能被创意高分抵消；
- VLM 分数不能替代人的效果确认；
- 样片评价不能无条件冒充成片评价；
- 单条视频的结果可以触发局部修复，不能直接改变全局生产策略；
- 线上结果是后验反馈，不替代发布前质量门和人工批准；
- Agent 负责审美、语义和编排判断，Python 负责确定性检查、schema、状态和持久化。

## 2. 核心原则

### 2.1 分层判断，不做万能总分

评价按以下层次依次发生：

```text
输入与研究质量
  -> 阶段产物质量
  -> 渲染技术健康
  -> L1a 事实/合规/交付硬门
  -> L3 创意质量建议
  -> 人工效果确认
  -> 候选比较与选择
  -> 发布后业务效果
```

任何下游分数都不能覆盖上游硬失败。例如：一条片即使 Hook 得分很高，只要价格错误、出现违规词或视频无法播放，就不能发布。

### 2.2 硬门先于软评分

- **硬门**处理可确定、不可妥协的问题，例如事实错误、媒体损坏、字幕越界和关键合规风险。
- **软评分**处理审美、节奏、表达、原创性等连续变量，用于建议、排序和优化。
- **人工门**处理最终效果、方向取舍、品牌判断和重大生产决策。

### 2.3 评价必须绑定版本和证据

每份评价都应回答：

- 评价对象是什么；
- 是样片还是成片；
- 对象的版本和 hash 是什么；
- 使用了哪个 judge 和 rubric；
- 证据位于哪个文件、字段、帧或时间段；
- 问题影响哪些镜头；
- 应从哪个阶段、以什么范围修复。

`evaluation_report.subject_hash` 是当前统一评价产物的最低版本绑定要求。跨样片、成片或候选复用评价时，还应同时校验 scope、candidate revision、rubric version 和媒体身份。

### 2.4 失败必须可行动

评价的目的不是描述“好或不好”，而是驱动下一步动作。每个关键问题至少应包含：

- 业务可读的问题描述；
- 证据；
- 影响范围；
- 严重程度；
- 是否可修复；
- 具体修改建议；
- 上游阶段和重跑范围；
- 必要时的成本预估。

### 2.5 数据不足不是通过，也不是质量失败

没有执行足够检查时，系统不能因为“没有发现问题”就判定通过。当前 L1a 使用 coverage gate：实际执行项不足时，评价进入 `revise`，而不是 `pass`。

在线上业务评价中，样本不足也必须单列为 `insufficient_data`，不能按业务失败或成功结算。

## 3. 评价架构

### 3.1 阶段级 Agent 自评

每个 pipeline stage 在写 checkpoint 前执行 Reviewer 协议：

1. 读取当前 stage 的 `review_focus`；
2. 读取 `success_criteria`；
3. 校验 canonical artifact schema；
4. 检查 style playbook 的 `quality_rules`；
5. 记录 critical、suggestion、nitpick 等问题；
6. critical 问题修复后复评，最多两轮；
7. 写入 checkpoint review，并按 manifest 决定是否等待人工批准。

该层适合判断：剧本时长、叙事结构、镜头覆盖、素材可行性、风格一致性、运行时选择、delivery promise 和 atelier distinctness 等。

当前 Reviewer 是 instruction-driven 自评，不是独立 Python reviewer。它本身是 advisory；真正的代码级阻断由 schema、checkpoint、approval 和 publish gate 承担。

### 3.2 Research 质量门

`research_scorecard` 对研究阶段做 10 分制检查，包含五项固定维度：

| 维度 | 判断内容 |
|---|---|
| `input_coverage` | 输入、参考片和自有素材是否覆盖 |
| `evidence_traceability` | 结论是否能回指来源和证据 |
| `source_matching` | 参考机制与可用源素材是否正确映射 |
| `production_readiness` | 是否足以支持后续方案和制作 |
| `execution_discipline` | 是否遵守研究流程和版权边界 |

当前 `cinematic-fast` 要求总分至少 8/10、所有检查为 pass、无 hard failure 才能完成 research。

### 3.3 渲染后技术健康检查

`final_qa` 负责渲染输出本身的技术健康，当前包括：

- ffprobe 容器和流检查；
- H.264/AAC、pixel format、采样率和声道；
- 分辨率和 profile；
- 完整解码 smoke test；
- full 模式下的黑帧、冻结和 EBU R128 响度；
- 字幕渲染声明、像素证据和安全区；
- `final_review` v2 结构化输出。

`final_qa` 与 L1a validator 共用 `lib/qa_checks.py`，避免 probe、黑帧、冻结和响度实现漂移。

### 3.4 L1a 确定性硬门

`technical_validator` 负责成片的业务和交付硬门。当前主要检查：

| 检查 | 当前实现 |
|---|---|
| SKU 一致性 | 基于 product fact card 与结构化文字源 |
| 价格一致性 | 基于 product fact card 与结构化文字源 |
| 产品参数一致性 | 基于 product fact card 与结构化文字源 |
| 敏感词 | 默认词表，可由输入扩展 |
| 字幕安全区 | 基于 caption declaration、computed boxes 和 props hash |
| 黑帧 | FFmpeg `blackdetect` |
| 静帧异常 | FFmpeg `freezedetect` |
| 音视频完整 | 流存在性与完整解码 |
| 时长 | 期望时长与容差 |
| 响度 | integrated LUFS 与 true peak |
| 分辨率 | 对比交付 profile |
| 帧率 | 对比交付 profile |

此外还有两个数据质量检查：

- 产品事实卡存在但无效时，记录 `l1a_facts_invalid`；
- 执行检查数不足时，记录 `l1a_coverage`。

严重性规则：

- SKU、价格、参数、敏感词冲突属于 fatal；
- 字幕、黑帧、冻结、时长等通常属于可修复 warning；
- fatal 失败产生 `status=fail`、`recommended_action=reject`；
- 只有可修复失败产生 `status=revise`、`recommended_action=repair`；
- 无失败且 coverage 足够才产生 `status=pass`、`recommended_action=proceed`。

### 3.5 L3 VLM 创意评价

`video_judge` 对均匀抽取的视频帧调用 DashScope Qwen-VL。它是随机评价器，因此必须记录 model、judge version、rubric version 和 seed。

当前有两套 rubric。

#### `l3-v1.0`

用于一般电商短视频 advisory：

1. Hook Clarity；
2. Visual Hierarchy；
3. Rhythm；
4. Shot Quality；
5. Story Coherence；
6. Audio Quality；
7. Text Readability；
8. Product Presence。

#### `ecommerce-remix-v1.0`

用于候选优化和电商 remix 比较：

1. Hook Clarity；
2. Reference Mechanism Fidelity；
3. Product Evidence；
4. Rhythm Pacing；
5. Visual Coherence；
6. Caption Readability；
7. Audio Quality；
8. Commercial Originality。

Judge 对非法分数、超出 0-10、重复维度和必评维度缺失实行 fail-closed。不同 `rubric_version` 或 `judge_version` 的分数不可直接比较。

当前 `l3-v1.0` 默认只提供建议，不直接阻止发布。`ecommerce-remix-v1.0` 只有在 optimization policy 显式开启且 judge 完成校准后，才可以成为优化门的一部分。

### 3.6 人工效果确认

样片人工门包含五项：

| Key | 用户判断 |
|---|---|
| `creative_direction` | 创意方向是否正确 |
| `hook` | 开场是否抓人 |
| `proof` | 核心证明是否成立 |
| `pacing` | 节奏是否合适 |
| `readability` | 画面与字幕是否可读 |

每项可选择 `pass`、`adjust`、`redirect`。只有五项全部 `pass` 才能批准样片并进入下一阶段。拒绝或返工必须携带结构化 `issue_tags`，形成可统计的质量反馈，而不是只保存自由文本。

### 3.7 批量候选评价

批量评价建立在单候选评价之上：

- 候选必须有独立的 sample 和 `evaluation_report_ref`；
- 只有 `evaluated` 候选才可以进入选择；
- 选择前检查 L1a、必要视觉质量条件和人工确认；
- `batch_quality_report` 汇总硬门、VLM 维度、人工确认、warnings 和推荐动作；
- 用户最终选择 1-2 个候选进入精剪，不自动发布所有候选。

批量报告是 persisted facts 的只读聚合，不应在构建报告时调用生成、渲染或 VLM。

### 3.8 优化评价

`optimization_policy` 和 `optimization_run` 支持自动研究式候选优化，但默认关闭。

当前默认策略：

- 分数范围 0-10；
- 8 个必评维度；
- 单维最低 8.0；
- 加权总分最低 8.5；
- beam width 5；
- 最大并发 3；
- 最大 6 次迭代；
- 最终确认 2 次；
- 包含预算、plateau 和重复 mutation 停止条件。

优化通过必须同时满足：

```text
L1a hard_gate.pass
AND L1a coverage.sufficient
AND 所有必评维度 >= 单维阈值
AND weighted_total >= 总分阈值
AND judge 已校准可发布
```

默认 `enabled=false`，意味着系统只能生成比较报告，不能宣称自动达标。

### 3.9 发布后业务评价

目标业务漏斗为：

```text
generation success
  -> quality pass
  -> user acceptance
  -> publication
  -> sufficient data
  -> business effectiveness
```

业务评价应分别记录：

- 内在视频质量；
- 用户接受或拒绝；
- 是否实际发布；
- 曝光、开播、留存、完播、互动、CTA、转化和成本；
- 基准 cohort；
- 外部投放、落地页、价格和产品等归因。

北极星指标是“有效视频率”，但必须与结算覆盖率和数据不足数量同屏展示。该层当前主要是设计目标，尚未形成完整生产闭环。

## 4. 统一评价产物

### 4.1 `review`

用途：保存单个 stage 的 Reviewer findings 和 Agent disposition。

当前问题：Reviewer skill 已要求 `investigation`、`proposed_fix` 和 `proposed_change`，但 `review.schema.json` 尚未完整表达这些字段，存在契约漂移。

### 4.2 `research_scorecard`

用途：研究阶段的结构化质量门。当前主要由 `cinematic-fast` 使用。

### 4.3 `final_review`

用途：证明 Agent 或工具检查了实际渲染结果，而不是只检查 render plan。包含技术、视觉、音频、delivery promise、字幕和 atelier 等检查。

注意：`final_review` 是渲染自审产物，不应代替统一业务评价，也不应代替 `evaluation_report`。

### 4.4 `evaluation_report`

用途：样片或成片的统一评价产物，是当前评价体系的核心合同。

主要字段：

```text
scope
subject_ref / subject_version / subject_hash
judge_version / rubric_version
hard_gate
creative_advisory
execution_diff_ref
repair_targets
status / recommended_action
optimization
```

样片与成片分别保存为：

```text
artifacts/evaluation_report.sample.json
artifacts/evaluation_report.final.json
```

不得用同一个无 scope 文件静默覆盖两者。

### 4.5 `delivery_review`

用途：保存运营人员针对一个基础成片版本选择的封面、Hook、BGM、结尾和文案覆盖。它是“交付版本修改决策”，不是质量分数。

### 4.6 `batch_quality_report`

用途：把多个候选的评价、人工确认和数据质量汇总为可比较报告。它不替代每个候选自己的 `evaluation_report`。

### 4.7 `gold_sample`

用途：保存 judge 校准和升级回放数据。样本分为：

- Gold；
- Silver；
- Bad；
- Hard Negative。

每个样本应记录 pointwise、pairwise、claims/QA、时间戳证据、failure tags、专家理由、人工采纳和 online outcome 占位，并使用 `group_key` 防止同模板泄漏到不同数据集 split。

## 5. 状态和判定语义

### 5.1 Stage Reviewer

| 决定 | 含义 | 行为 |
|---|---|---|
| `PASS` | 无 critical | 进入 checkpoint |
| `REVISE` | 有 critical | 修复后复评 |
| `PASS_WITH_WARNINGS` | 两轮后仍有问题 | 记录 warning 后继续；不得冒充硬门通过 |

### 5.2 `final_review`

| 状态 | 含义 | 推荐行为 |
|---|---|---|
| `pass` | 可向用户展示 | `present_to_user` |
| `revise` | 可修复问题 | re-render 或回到 edit/assets |
| `fail` | 严重问题 | block 或重新制作 |

### 5.3 `evaluation_report`

| 状态 | `hard_gate.pass` | 推荐动作 | 发布语义 |
|---|---:|---|---|
| `pass` | true | `proceed` | 可进入后续门 |
| `revise` | false | `repair` | 不应宣称质量通过；按 pipeline 策略人工降级或修复 |
| `fail` | false | `reject` | fatal L1a，必须阻止 publish |

### 5.4 人工样片确认

`adjust` 表示方向基本成立但需要局部修改；`redirect` 表示方向不成立，应回到上游创意。两者都不能被 API 当作批准。

### 5.5 发布门

目标统一规则：

```text
final_review.status == pass
AND evaluation_report.status != fail
AND 必需人工门已批准
AND 若 optimization_policy.enabled，则 optimization 双门通过
```

当前代码中，完整的 `evaluation_report` publish gate 主要落在 `cinematic-fast`。其他 pipeline 尚未统一到该规则，这是当前最重要的系统差距。

## 6. Pipeline 覆盖现状

截至 2026-08-25：

| Pipeline | Stage review | `final_review` | `evaluation_report` | 专项评价 | 当前成熟度 |
|---|---:|---:|---:|---|---|
| `cinematic-fast` | 是 | 是 | sample + final | research scorecard、L1a、VLM、人工样片门、batch | 当前最完整 |
| `character-animation` | 是 | 是 | 否 | `character_qa_report` | 专项 QA 已有，未并入统一评价 |
| `animated-explainer` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `animation` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `avatar-spokesperson` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `cinematic` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `clip-factory` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `hybrid` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `localization-dub` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `podcast-repurpose` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `screen-demo` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `talking-head` | 是 | 是 | 否 | 无统一专项报告 | 部分实现 |
| `documentary-montage` | 是 | manifest 未声明 | 否 | 无 | 评价合同缺口较大 |
| `framework-smoke` | 最小 | 否 | 否 | 仅框架测试 | 不属于生产评价 |

## 7. 当前实现边界

### 7.1 已实现并有测试覆盖

- stage manifest 的 `review_focus`、`success_criteria` 和人工 gate；
- artifact schema 与 checkpoint 校验；
- `research_scorecard` 语义检查；
- `final_qa` quick/full 技术检查；
- L1a `technical_validator` 与 coverage gate；
- scoped `evaluation_report.sample/final`；
- VLM 两套 rubric 和 fail-closed 解析；
- `judge_with_average()` helper；
- 样片五项人工确认和结构化拒绝标签；
- candidate batch、batch quality report 和选择 gate；
- optimization scoring/run 状态机；
- Gold Set、Group Split、kappa、bootstrap 和 replay helper；
- Backlot 样片/成片评价卡投影；
- legacy evaluation report 回填脚本。

### 7.2 部分实现

- `evaluation_report` 只在 `cinematic-fast` 成为正式 pipeline 合同；
- `judge_with_average()` 已在 skill 中规定用于候选排序，但尚未收口成统一 stage service；
- final VLM 评分在部分路径缺失，批报告可能展示带明确标记的 sample advisory；
- product facts 已有卡片和文本检查，但像素内事实仍缺统一 OCR；
- repair targets 和 repair artifact 已有，但局部修复尚未覆盖所有失败类型和 pipeline；
- Backlot 能展示评价卡，但还不是完整的跨 pipeline 评价工作台；
- `final_review` 包含视觉字段，但部分字段仍依赖 Agent 填写，工具没有完成真实逐帧视觉验证；
- judge calibration 有代码框架，没有真实、足量、双标注数据集证明其可发布。

### 7.3 仅设计或接口占位

- 完整线上发布数据采集；
- production order 级业务状态机；
- cohort benchmark 和账户历史基准；
- Effective Video Rate 自动结算；
- 线上留存、CTA、转化、成本和归因；
- Spearman/Kendall、Critical FAR/FRR 等完整 judge 发布报告；
- 自动策略学习、reward modeling 和增量 uplift；
- 经校准后默认启用的创意自动门。

## 8. 已知差距

### P0：统一交付评价合同

1. 所有生产 pipeline 的 compose 至少产出 `final_review + evaluation_report.final`；
2. 所有 publish stage 使用统一 publish gate，而不是 pipeline 特判；
3. 样片型 pipeline 统一 `evaluation_report.sample + human effect confirmation`；
4. `documentary-montage` 补齐 final review 和评价合同；
5. 专项 QA 通过 extension block 或引用并入统一评价，而不是形成互不关联的平行结论。

### P0：修复 Reviewer 契约漂移

`reviewer.md` 与 `review.schema.json` 当前不一致。需要统一：

- 是否支持 `investigation`；
- critical 的 `proposed_fix`；
- suggestion 的 `proposed_change`；
- finding 的 evidence refs；
- review decision 和 unresolved warning；
- research/proposal/sample 等当前 schema 未覆盖的 stage 名称。

### P0：让最终视觉检查真正有证据

当前 `final_qa` 更接近技术 QA。需要补齐：

- 自动抽取 opening、middle、climax、ending 代表帧；
- 记录 `frames_sampled` 和 `frame_paths`；
- 检查 missing asset、broken overlay、unreadable text；
- delivery promise 与实际 cuts/runtime 的真实对照；
- 没有 production-lock 上下文时不得默认 `delivery_promise_honored=true`；
- atelier scene distinctness、字幕重复和品牌独特性保留人工证据。

### P1：稳定并统一 VLM 生产接入

1. 候选排序统一使用多次评分，而不是单次随机分数；
2. 每次 run 保存 seed、model、rubric、维度和原始结果；
3. sample/final 分数严格分开；
4. 合并或继承 advisory 时验证 scope、revision、rubric、subject hash 和媒体身份；
5. VLM 不可用时明确 `scored=false`，不得用空分数参与排名；
6. 建立 provider 不可用、超时和非法返回的统一降级语义。

### P1：加强事实与证据评价

1. 对烧录字幕、包装、价格和 SKU 接入 OCR；
2. 建立 claim-evidence 对照，而不是只查文字冲突；
3. 产品外观、Logo、颜色和形态加入视觉一致性检查；
4. 对商品变形、错误交互和不合理物理建立专项 evaluator；
5. 每个关键事实失败回指时间戳和镜头。

### P1：完善修复闭环

当前 schema 支持四种基础动作：

- `rewrite_hook`；
- `edit_caption`；
- `replace_asset`；
- `shorten_shot`。

后续需要：

- 音频重混、口播重录和 BGM 调整；
- 事实冲突必须升级人工处理，不允许自动猜正确值；
- repair 前后按同一 rubric 回评；
- 目标维度提升且其他关键维度不退步才保留修复；
- 所有修复追加 decision log 和 rework tags。

### P2：完成 Judge 校准和版本治理

生产 judge 发布前至少需要：

- 每个必评维度足量样本，起步参考 n >= 100；
- 双人独立标注和仲裁；
- Cohen's kappa 达到批准阈值；
- 每维 Spearman/Kendall 和 bootstrap 95% CI；
- Critical FAR/FRR；
- Hard Negative 覆盖；
- 旧版本轨迹 replay；
- hard gate failure increase 和 grounding drop 均为 false；
- 跨 judge version 不直接比较分数。

校准不足时只能 shadow mode，不能作为发布硬门或自动优化成功依据。

### P2：接入线上业务闭环

需要补齐以下稳定数据对象及服务：

- `production_order`；
- `video_version`；
- `quality_evaluation`；
- `user_decision`；
- `publication`；
- `performance_snapshot`；
- `benchmark_record`；
- `effectiveness_evaluation`；
- `evaluation_policy`；
- `settlement_policy`。

线上评价必须按平台、目标、账号规模、内容类型、时长、受众和付费/自然流量做同类比较。

## 9. 推荐实施顺序

### Phase 1：统一“可交付”

1. 抽取 pipeline-neutral publish gate；
2. 所有生产 pipeline 接入 final-scope evaluation；
3. 对齐 Reviewer skill 和 schema；
4. 补真实抽帧视觉证据；
5. 建立跨 pipeline contract tests。

完成标准：任一 pipeline 都不能在 final review 或 fatal L1a 失败时被标记为可交付。

### Phase 2：统一“可比较”

1. 收口 sample evaluation service；
2. 多跑 VLM 与完整 provenance；
3. 批量 scorecard 按相同 rubric 比较；
4. 完成局部 repair 和回评；
5. 统一 Backlot 单条/批量评价视图。

完成标准：一次研究可产出 5 个有独立评价的候选，用户能基于同口径证据选出 1-2 个进入精剪。

### Phase 3：统一“可学习”

1. 建立真实 Gold Set；
2. 完成 judge 校准报告和 release gate；
3. 扩展 10 候选和优化预算；
4. 接入发布数据与 cohort benchmark；
5. 建立 Effective Video Rate 和归因报告。

完成标准：评价版本可重放、阈值有数据依据、judge 升级不降低事实一致性或硬门质量，线上反馈不会绕过人工批准。

## 10. 测试与验收要求

每次评价体系变更至少覆盖：

### Contract tests

- schema required fields 和 enum；
- subject hash 与 scoped artifact；
- status、hard gate 和 recommended action 一致性；
- fatal、revise、coverage 和 optimization 边界；
- sample/final provenance；
- pipeline produces/required_artifacts_in 合同。

### Unit tests

- probe、decode、black、freeze、loudness；
- product facts 和文本冲突；
- VLM 非法值、缺维、重复维度和未知 rubric；
- 多跑均值和 seed；
- weighted threshold 的 7.99、8.49、8.50 边界；
- repair mapping 和 rerun scope；
- Gold Set split、kappa、bootstrap 和 replay。

### Integration tests

- sample -> evaluation -> human gate -> edit；
- compose -> final review -> evaluation -> publish；
- fatal L1a 阻止 publish；
- coverage 不足不得 pass；
- VLM 不可用时 advisory 明确降级；
- legacy evaluation 回填；
- 多候选失败、选择、重复提交和恢复；
- 服务重启后评价和批准状态不丢失。

### Visual acceptance

- 实际观看样片和成片；
- 检查代表帧、字幕安全区和移动端可读性；
- 检查音画同步、口播清晰度、BGM ducking 和响度；
- 检查 delivery promise、品牌独特性和参考机制借鉴边界；
- 记录人工结论和证据，不以“测试通过”代替观看。

## 11. 文档治理

本文件维护“当前统一口径”，不记录每次实现过程。更新规则：

1. schema、pipeline contract 或 gate 语义变化时同步更新本文件；
2. 已实现与仅设计必须明确区分；
3. 历史评审结论若已修复，应在历史文档保留原记录，在本文件更新当前状态；
4. judge/rubric 升级必须记录版本、校准依据和不可比边界；
5. 不新增与 `evaluation_report` 平行且语义重叠的统一评价产物；
6. 专项 QA 应被引用或组合进统一评价，而不是各自定义“最终通过”。

## 12. 关键文件

### 规范与设计

- `AGENT_GUIDE.md`：阶段 Reviewer、人工 checkpoint 和生产治理总规则；
- `skills/meta/reviewer.md`：阶段自评协议；
- `skills/meta/judge-calibration.md`：judge 校准与升级纪律；
- `docs/art-plan/Design_Review_2026-08-22.md`：评价体系 P0/P1/P2 实施基线；
- `docs/art-plan/Video_Judge_OpenSource_Research_2026-08-21.md`：Video Judge 调研和长期 Evaluation Plane；
- `docs/superpowers/specs/2026-08-16-video-quality-business-feedback-design.md`：业务质量、线上效果和归因设计；
- `docs/reports/2026-08-24-operator-delivery-and-agent-architecture-review.md`：当前接入和生产风险复核。
- `docs/insight_source/AI短视频规范监控_规则量化指标对照_表格.csv`：业务规则来源；接入评估见第 13 节。

### Schema

- `schemas/artifacts/review.schema.json`；
- `schemas/artifacts/research_scorecard.schema.json`；
- `schemas/artifacts/final_review.schema.json`；
- `schemas/artifacts/evaluation_report.schema.json`；
- `schemas/artifacts/delivery_review.schema.json`；
- `schemas/artifacts/batch_quality_report.schema.json`；
- `schemas/artifacts/optimization_policy.schema.json`；
- `schemas/artifacts/optimization_run.schema.json`；
- `schemas/artifacts/gold_sample.schema.json`。

### 实现

- `lib/qa_checks.py`；
- `tools/video/final_qa.py`；
- `tools/analysis/technical_validator.py`；
- `tools/analysis/video_judge.py`；
- `lib/optimization_scoring.py`；
- `lib/optimization_run.py`；
- `lib/batch_reporting.py`；
- `lib/gold_set.py`；
- `lib/repair.py`；
- `lib/checkpoint.py`；
- `backlot/operator_reviews.py`；
- `backlot/operator_state.py`；
- `backlot/batch_actions.py`。

## 13. 业务册规范接入评估

### 13.1 来源与判断边界

业务侧附件 `docs/insight_source/AI短视频规范监控_规则量化指标对照_表格.csv` 共 24 条规则。它不是现有代码的执行契约，而是业务规则来源；规则中的“取数方式”和“阈值/评分标准”需要经过版本化、证据化后，才能成为 `evaluation_report` 的可执行检查。

这 24 条规则混合了五种不同问题：

1. 内容与平台合规：能否发布，属于硬门；
2. 成片质量：视频本身是否清楚、可信、有信息量，属于发布前质量评价；
3. 发布准备度：封面、标题、商品描述、投放素材是否可用，属于交付前运营门；
4. 发布后效果：留存、完播、CTR、曝光、消耗、转化，属于线上效果评价；
5. 商品和账号资格：商品评分、精选联盟、重复铺货、账号健康分，属于输入资格或外部平台状态。

因此，业务册不能直接作为一个总分相加。推荐的总判定顺序是：

```text
输入资格门
  -> 成片合规/交付硬门
  -> 发布前内容质量与发布准备度
  -> 人工接受
  -> 发布
  -> 数据充足性门
  -> 发布后业务效果
```

业务规则包应至少具备 `policy_id`、`policy_version`、`platform`、`category`、`rule_id`、`metric_definition`、`evidence_source`、`thresholds`、`severity`、`effective_at` 和 `source_ref`。CSV 原文应作为 `source_ref` 保存，不能把附件中的阈值直接散落到 Python 常量或 prompt 中。

下文的 R01-R24 是按 CSV 数据行顺序临时分配的分析编号，源文件本身没有稳定规则 ID。正式接入时必须在规则包中固化 ID，不能长期依赖行号。

### 13.2 规则映射与当前状态

状态含义：

- **已具备基础**：已有稳定的字段、工具或门，但不代表完全覆盖业务规则；
- **部分实现**：能检查一部分证据，仍缺关键取数能力、视觉证据或业务适配；
- **待接入**：规则语义已能定义，但当前没有生产级取数或判定闭环；
- **外部依赖**：必须依赖抖音/千川/商品或账号接口，不能在渲染阶段推断。

| 业务册规则 | 应进入的评价层 | 当前实现状态与依据 |
|---|---|---|
| 内容合规、违规词/虚假承诺、站外联系方式（R01/R03/R05） | L1a 合规硬门 | **部分实现**：`technical_validator` 已有敏感词、文本来源、产品事实冲突检查；尚缺 CV 多标签、OCR 像素文字、虚假/夸大/引流语义分类和完整联系方式规则。 |
| 封面合规、封面大字报、危险/低质画面（R02/R04） | 封面/画面合规硬门 | **待接入**：现有 `final_qa`/L1a 不能对封面独立取证，也没有低质搬运指纹、对比强度和禁限售视觉分类。 |
| 账号健康分（R06） | 输入资格门 | **外部依赖**：必须在生产前读取平台账号状态；不能从视频质量报告推断。 |
| 前 3 秒开场、信息密度、痛点开场、实景演示、基础商品信息（R07/R08/R12） | 发布前业务质量 + L3 advisory | **部分实现**：脚本、ASR、产品事实卡和 `video_judge` 可提供事实与创意线索；尚未形成 3 秒留存/信息密度/演示占比/材质尺寸价格场景完整度的确定性 evaluator。 |
| 画质、主体占比、亮度、BGM 合规、时长、水印（R09/R15） | L1a 交付硬门 | **部分实现**：`final_qa` 与 `technical_validator` 已覆盖容器、解码、分辨率、帧率、时长、响度、黑帧、冻结、字幕安全区；主体占比、亮度、水印、封面标题规范和 BGM 版权/业务合规尚未统一接入。 |
| 真实可信、信息价值、专业有趣、声画体验、合规（R10/R14） | 发布前质量 rubric | **部分实现**：`video_judge` 的 `l3-v1.0` 已有 Hook、层级、节奏、镜头、连贯性、音频、文字、商品露出等 8 维，但目前是 advisory，且没有业务册五维的固定映射和 Gold Set 校准。 |
| 推荐流量重点、封面标题吸引力、实景/演示/对比占比、详情页一致度、差评率（R11） | 发布准备度 + 发布后效果 | **部分实现/外部依赖**：视觉与文本部分可由 L3/事实卡辅助；点击、转化、差评和详情页一致度需要平台与商品数据，不能在成片阶段硬判。 |
| 千川素材三优：声画、互动、跑量（R13） | 发布前质量 + 发布后效果 | **部分实现/外部依赖**：声画可复用 L1a/L3；互动和跑量必须在投放后采集，不能把三项压成一个渲染分数。 |
| 播放量与完播率门槛（R16） | 发布后数据充足性/流量表现 | **外部依赖**：必须读取发布后的平台数据；“不入推荐池”是平台结果，不是成片技术失败。 |
| 产品外观、画面文案一致、排版美观（R17） | 发布准备度 | **部分实现**：L3 可辅助判断层级、可读性和商品露出，产品事实卡可提供视觉约束；尚缺产品外观 CV、一致性 OCR 和经校准的排版评分。 |
| 商品描述与品牌调性一致（R18） | 产品事实/品牌发布准备度 | **部分实现**：`product_facts` 已支持 SKU、价格、参数、主张和视觉真实性；像素级 OCR、商品页对照和品牌调性 profile 尚未形成统一门。 |
| 热点/活动、DOU+ 计划、跑量、持续投放（R19/R20/R21/R22） | 发布后运营策略与效果 | **待接入/外部依赖**：属于运营动作或投放结果，不应影响视频内在质量分；应进入 `performance_snapshot`、投放计划或运营记录。 |
| 商品入池、商品信息完整/重复铺货/混淆信息（R23/R24） | 输入资格门 | **待接入/外部依赖**：需要商品平台接口；失败应阻止进入生产或投放，不应等成片生成后才扣分。 |

### 13.3 推荐的评价层设计

#### A. 输入资格门

在 `idea/proposal` 之前或之中执行：账号健康、商品评分、精选联盟、商品信息完整度、重复铺货、混淆信息、产品事实卡和品牌规则。状态建议使用 `eligible`、`ineligible`、`unknown`，其中 `unknown` 不能自动当作通过。

#### B. L1a 业务合规与交付硬门

继续使用 `evaluation_report.hard_gate`，把业务册中的内容合规、违禁词、站外引流、虚假/夸大承诺、SKU/价格/参数、封面合规、水印、分辨率、时长和字幕安全区纳入确定性检查。规则命中语义建议如下：

```text
明确违规/事实冲突 -> fail，阻止 publish
证据不足但可补取 -> revise，不能宣称通过
检查未执行 -> insufficient_data，不能当作 pass
```

其中“疑似扣 10 分”“任一扣 20 分”等业务册规则应先落成 `warning` 和 `repair_target`，只有完成误报率、漏报率和人工一致性校准后，才考虑升级为硬门。

#### C. 发布前内容质量与准备度

保留业务册的 20/13/6 档位作为业务展示层，但内部统一为 0-100 或 0-1 的版本化维度分，不直接累加不同规则的原始分。首版建议维度为：

| 维度 | 主要来源 | 建议首版语义 |
|---|---|---|
| 真实可信 | 产品事实、claim-evidence、ASR/OCR、人工确认 | 事实一致、主张有证据、无夸大 |
| 信息价值 | ASR/NLP、脚本和 scene plan | 卖点、方法、参数、场景信息是否完整 |
| Hook 与节奏 | 3 秒结构、抽帧、L3、人工确认 | 前 3 秒是否明确痛点/利益点，节奏是否支撑留存 |
| 视觉与演示 | CV、素材证据、L3 | 商品露出、实景/演示/对比、主体占比和可读性 |
| 声画体验 | `final_qa`、响度、L3、人工确认 | 音画同步、口播清晰、BGM 不遮挡、字幕可读 |
| 商业准备度 | 封面标题、商品描述、品牌 profile、人工确认 | 是否可投放、是否与详情页和品牌调性一致 |

业务册的“优/良/差”可以映射为 `>=80 / 60-79.9 / <60`，但阈值只能在 Gold Set 和真实业务样本校准后成为自动门。L3 分数在校准前只能作为 advisory，不能覆盖 L1a 失败。

#### D. 发布后效果评价

3 秒留存、跳出、播放量、完播、CTR、曝光、消耗、转化、差评率和商品入池后的表现，统一进入发布后评价，不回写成片的内在质量分。每次快照必须带：平台、账号/商品范围、发布时间、统计窗口、样本量、指标值、基准 cohort、投放条件和数据完整性。

数据不足时使用 `insufficient_data`，至少区分“尚未发布”“窗口未到”“样本量不足”“平台接口失败”和“归因条件不完整”。只有达到预先定义的样本量和窗口后，才计算业务效果等级。

### 13.4 对现有评价合同的改造建议

不新增与 `evaluation_report` 竞争的“业务总评价报告”。按生命周期拆成三个不重叠的对象：

1. 生产前 `eligibility_assessment`：记录账号、商品和事实输入资格，供 proposal/publish 引用；
2. 成片 `evaluation_report`：继续绑定 sample/final 的媒体 hash，增加版本化业务扩展；
3. 发布后 `performance_snapshot + effectiveness_evaluation`：追加线上事实和业务结算，不回写已冻结的成片评价。

`evaluation_report` 的业务扩展建议包括：

```text
policy_refs[]              # 业务规则包及版本
eligibility_ref            # 生产前资格评估引用，不复制或改写资格事实
business_compliance        # R01-R05 与 R18 中可自动核验的合规/事实规则
delivery_quality           # R09、R15 的确定性交付检查
content_quality            # 版本化维度分和 raw evidence refs
distribution_readiness     # 封面/标题/投放素材准备度
```

`hard_gate` 仍是发布阻断依据；`content_quality` 和 `distribution_readiness` 是发布前评价。`delivery_review` 继续保存运营人员对封面、Hook、BGM、结尾和文案的交付选择，不把运营选择伪装成模型分数。`performance_snapshot` 与 `effectiveness_evaluation` 只引用成片/发布版本，不能反向修改该版本的内在质量结论。

### 13.5 差距与优先级

**P0：先把不可违规和不可交付的部分接入。**

- 建立 `business_policy_profile`（平台、品类、规则版本、阈值和来源）；
- 将 R01-R05 中可确定核验的合规规则和 R15 交付检查映射到 L1a；R17/R18 分别进入发布准备度和事实一致性检查；
- 增加封面单独的 OCR/CV 合规检查；
- 将 `unknown`、`insufficient_data` 和 `skip` 分开，禁止缺数据自动通过；
- 所有生产 pipeline 使用同一 `evaluation_report` publish gate。

**P1：补齐发布前业务质量证据。**

- 信息密度、3 秒结构、痛点开场、实景/演示占比、基础商品信息完整度；
- 主体占比、亮度、水印、封面标题和 BGM 合规；
- 产品视觉身份、claim-evidence 和 OCR 像素事实；
- 将业务册五维与 `l3-v1.0` 建立明确映射，并用 Gold Set 校准。

**P2：打通发布后效果闭环。**

- 平台/投放/商品接口和 `performance_snapshot`；
- cohort 基准、窗口和样本量门；
- CTR、留存、完播、转化、消耗和差评的归因；
- Effective Video Rate 与业务规则版本的回放比较。

### 13.6 接入验收标准

业务规范真正接入的最低验收不是“报告里出现了几个分数”，而是：

1. 每条规则都有唯一 `rule_id`、版本、来源、取数方式、证据位置和判定状态；
2. 明确标记规则属于输入资格、L1a、发布前质量还是发布后效果；
3. 命中硬门能阻止 publish，修复项能生成 `repair_target`，数据不足不能伪装成通过；
4. 同一视频在 sample/final、不同 pipeline 和不同规则版本下可追溯且不可混比；
5. 发布后指标具备平台、窗口、样本量和 cohort，不能把投放结果反推为视频质量事实；
6. 业务阈值调整有 policy 版本、回放结果和人工批准记录。

## 14. 总结

OpenMontage 当前已经不是“渲染成功就算完成”的系统。它已经具备阶段审查、技术 QA、事实硬门、VLM 创意建议、人工样片确认、候选比较、修复目标和 judge 治理基础。

当前最关键的下一步不是继续增加新的分数，而是完成三件事：

1. 把 `cinematic-fast` 已形成的统一评价合同推广到所有生产 pipeline；
2. 让每一个通过或失败结论都有真实证据、版本绑定和可执行修复路径；
3. 在真实 Gold Set 校准和线上闭环完成前，坚持把 VLM 当作 advisory 或 shadow signal，而不是未经验证的自动裁判。

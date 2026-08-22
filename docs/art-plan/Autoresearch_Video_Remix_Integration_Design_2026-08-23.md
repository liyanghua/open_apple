# Autoresearch 视频复刻混剪集成技术设计

> 日期：2026-08-23  
> 版本：v1.0  
> 状态：设计稿，待实现  
> 适用范围：OpenMontage `cinematic-fast`、电商视频复刻、多源素材混剪

## 0. 文档定位与约束

本文件把用户提出的 Autoresearch 机制落到 OpenMontage 现有的 pipeline、artifact、评价和成本治理体系中。

用户本次新增要求是：

1. 多个自有视频组成素材池并进行混剪；
2. 一次生成多个混剪候选；
3. 基于评价维度和总分自动比较；
4. 任一 required dimension 低于 8 分，或总分低于阈值，自动进入下一轮；
5. 达标后再进行最终成片确认。

现有 [`Three_Track_Integration_Plan_2026-08-22.md`](./Three_Track_Integration_Plan_2026-08-22.md) 作为兼容约束，而不是新的用户指令。以下既有决策保持不变：

- `evaluation_report` 是唯一评价工件；
- L1a 确定性门禁与 VLM 创意评价分层；
- `candidate_batch` 负责多候选索引；
- OpenMontage 是生产生成的唯一入口；
- 现有生产项目不因本 capability extension 被改写；
- 最终 publish 仍受人工批准和 hard gate 约束。

不复制外部 `autoresearch` 仓库代码，只采用其可迁移机制：固定目标、单点修改、机械验证、保留改进、记录失败、有限迭代和自动停止。

## 1. 目标架构

### 1.1 运行模型

```text
多个自有源视频
        |
        v
source_media_review + media_index
        |
        v
共享研究、事实、素材清单、原创边界
        |
        +--> candidate-01: 结果先行
        +--> candidate-02: 痛点先行
        +--> candidate-03: 证据链先行
        +--> candidate-04: 高密度快剪
        +--> candidate-05: 产品质感版
                    |
                    v
          sample render + L1a + video_judge
                    |
          +---------+---------+
          |                   |
        达标                未达标
          |                   |
          v                   v
  full render              最低维度分析
          |                   |
          v                   v
  两次确认评分          单一最小 mutation
          |                   |
          +--------<----------+
                    |
                    v
           passed / exhausted / blocked
```

### 1.2 Autoresearch 概念映射

| Autoresearch 概念 | OpenMontage 实现 |
|---|---|
| Goal | `optimization_policy` |
| Metric | `evaluation_report.optimization.weighted_total` 与各维度分数 |
| Scope | 固定 research、事实、素材授权、production constraints |
| One focused change | 由失败维度决定的单一 mutation |
| Verify | sample/full render、`technical_validator`、`video_judge` |
| Keep / discard | 更新 `optimization_run.best_candidate_id`，不删除失败媒体 |
| Git memory | `optimization_run.history` + mutation fingerprint |
| Guard | L1a hard gate、预算、provider/model/runtime 锁定 |
| Bounded loop | 最大迭代、最大成本、最大重试、plateau 停止 |

## 2. 评分与通过契约

### 2.1 Rubric 版本

现有 `l3-v1.0` 继续服务旧项目和 advisory 展示。Autoresearch 使用独立且固定的：

```text
rubric_version = ecommerce-remix-v1.0
score_scale = 0-10
```

首期维度和权重如下：

| ID | 维度 | 权重 |
|---|---|---:|
| `hook_clarity` | 前 1-3 秒钩子是否清晰 | 15% |
| `reference_mechanism_fidelity` | 是否复刻参考片的有效机制而非像素 | 20% |
| `product_evidence` | 产品证明是否充分、及时、可信 | 20% |
| `rhythm_pacing` | 镜头密度、切点和节奏 | 15% |
| `visual_coherence` | 构图、裁切、转场和连续性 | 10% |
| `caption_readability` | 字幕可读性和安全区 | 10% |
| `audio_quality` | 旁白、BGM、ducking 和响度 | 5% |
| `commercial_originality` | 商业表达的差异化和原创边界 | 5% |

权重必须在 policy 中声明且总和为 1.0，运行中不可修改。

### 2.2 通过条件

候选只有同时满足以下条件才算优化通过：

```text
technical_validator.hard_gate.pass == true
所有 required dimensions 均已评分且 score >= 8.0
weighted_total >= 8.5
没有 fatal L1a finding
evaluation_report coverage 足够
judge_version / rubric_version 一致
```

精确边界：

- 任一维度 `7.99`：失败；
- 所有维度 `>= 8.0` 但总分 `8.49`：失败；
- 所有维度 `>= 8.0` 且总分 `8.50`：通过；
- 缺失或 skip 的 required dimension：失败；
- 分数不在 `[0, 10]`：拒绝该报告。

### 2.3 VLM 随机性

VLM 是 stochastic judge，不能只用一次评分决定最终候选。

- 样片阶段：每候选至少一次评分，用于预筛和 mutation；
- 最终阶段：最佳候选执行两次 confirmation run；
- 两次 confirmation 均必须满足全部单维和总分门槛；
- 记录 `model`、`judge_version`、`rubric_version`、配置和随机种子；
- 没有 `video_judge` 时只能生成比较报告，不能宣称自动达标。

## 3. Artifact 与接口设计

### 3.1 `optimization_policy`

新增：

```text
schemas/artifacts/optimization_policy.schema.json
```

核心字段：

```json
{
  "version": "1.0",
  "enabled": true,
  "score_scale": "0-10",
  "rubric_version": "ecommerce-remix-v1.0",
  "per_dimension_min": 8.0,
  "weighted_total_min": 8.5,
  "required_dimensions": [],
  "weights": {},
  "beam_width": 5,
  "max_parallel": 3,
  "max_iterations": 6,
  "max_retries_per_candidate": 2,
  "confirmation_runs": 2,
  "max_total_cost_usd": 0,
  "plateau_delta": 0.1
}
```

`max_total_cost_usd: 0` 表示由项目预算注入，实际扣费必须经过 `cost_tracker`，不表示无限预算。

### 3.2 `optimization_run`

新增：

```text
schemas/artifacts/optimization_run.schema.json
lib/optimization_run.py
```

状态：

```text
planned | running | awaiting_confirmation | passed | exhausted | blocked | failed
```

示例：

```json
{
  "run_id": "autoresearch-mix-001",
  "project_id": "table-mat-remix-001",
  "status": "running",
  "phase": "sample",
  "baseline_candidate_id": "candidate-01",
  "best_candidate_id": "candidate-03",
  "iteration": 2,
  "policy_ref": {
    "name": "optimization_policy",
    "path": "artifacts/optimization_policy.json"
  },
  "history": [
    {
      "iteration": 1,
      "candidate_ids": ["candidate-01", "candidate-02"],
      "winner": "candidate-02",
      "outcome": "rejected",
      "failure_dimensions": ["product_evidence"],
      "weighted_total": 7.82,
      "mutation_fingerprint": "sha256:..."
    }
  ],
  "confirmation": {
    "required_runs": 2,
    "completed_runs": 0,
    "passed": false
  },
  "stop_reason": null
}
```

`history` 是运行记忆。失败候选的媒体、评价报告和项目目录必须保留，不能用删除文件实现回滚。

### 3.3 `candidate_batch` 扩展

现有 `candidate_batch` 增加以下字段：

- batch 级 `source_media_refs`；
- candidate 级 `iteration`；
- `parent_candidate_id`；
- `mutation`；
- `mutation_fingerprint`；
- `changed_dimensions`；
- `failure_dimensions`；
- `dimension_scores`；
- `weighted_total`；
- `provider`、`model`、`render_runtime`；
- `output_ref`。

每个候选仍保持独立项目、artifact、checkpoint 和 decision log。`candidate_batch` 只是索引，不承载完整候选内容。

### 3.4 `evaluation_report` 扩展

保留现有 `hard_gate`、`creative_advisory`、`status` 和 `recommended_action` 语义，新增可选的 `optimization` 区块：

```json
{
  "optimization": {
    "run_id": "autoresearch-mix-001",
    "candidate_id": "candidate-03",
    "iteration": 2,
    "parent_candidate_id": "candidate-01",
    "dimension_scores": {},
    "weighted_total": 8.63,
    "thresholds": {
      "per_dimension_min": 8.0,
      "weighted_total_min": 8.5
    },
    "passed": true,
    "failure_dimensions": [],
    "confirmation_index": 1
  }
}
```

`evaluation_report.status` 表达 L1a 状态；`optimization.passed` 表达创意优化门禁，二者不可互相替代。

## 4. 多视频素材与候选模型

### 4.1 素材池

输入必须是多个自有或已授权视频：

```text
source_video_01
source_video_02
source_video_03
        |
        v
source_media_review + media_index
```

每个候选必须能追溯到具体源视频和时间区间：

```json
{
  "candidate_id": "candidate-03",
  "source_refs": [
    "inputs/source/video-01.mp4",
    "inputs/source/video-02.mp4"
  ],
  "shot_sources": {
    "shot-01": "video-02:12.4-15.1",
    "shot-02": "video-01:03.0-06.2"
  }
}
```

参考视频只能用于分析，不能进入 `shot_sources`。素材授权、SKU 和产品事实必须在 research 阶段固定。

### 4.2 首轮候选

默认生成 5 个明确不同的候选：

1. 结果先行；
2. 痛点先行；
3. 证据链先行；
4. 高密度快剪；
5. 产品质感版。

候选之间共享 research、事实、素材清单、原创边界和生产基础设施；只在 hook、镜头顺序、节奏、字幕包装和 CTA 表达上分叉。

## 5. Mutation 规则

一轮只允许一个聚焦修改。导演 skill 负责选择 mutation，Python 只负责校验和持久化。

| 失败维度 | 允许修改 |
|---|---|
| `hook_clarity` | 前 1-2 个镜头、开场顺序、首句文案 |
| `reference_mechanism_fidelity` | 机制对应镜头、动作顺序、参考节奏结构 |
| `product_evidence` | 产品证明镜头、证据片段区间、产品特写 |
| `rhythm_pacing` | shot duration、切点、镜头密度 |
| `visual_coherence` | crop、transition、色彩和画面连续性 |
| `caption_readability` | 字幕长度、字号、位置、安全区 |
| `audio_quality` | 旁白/BGM 音量、ducking、淡入淡出 |
| `commercial_originality` | CTA 结构、表达方式、视觉处理 |

禁止在同一 mutation 中同时修改整套脚本、provider、model、render runtime、产品事实或 production lock。

以下变化必须重新人工审批：

- 更换 provider/model/runtime；
- 修改 SKU、价格、参数或核心 claim；
- 改变已批准的创意主方向；
- 从自有素材切换为生成素材；
- 从视频-led 切换为 still-led。

## 6. 迭代状态机

### 6.1 样片搜索

```text
冻结 optimization_policy
  -> 建立 source pool
  -> 生成首轮候选
  -> 并行 sample render
  -> final_qa + technical_validator
  -> video_judge
  -> 分数聚合
  -> 更新 best_candidate
  -> 达标则进入最终候选
  -> 未达标则按最低维度生成下一轮
```

技术失败和质量失败必须分开记录：

- provider/render 失败：记录为执行失败，可按 retry policy 重试；
- 质量失败：记录 `failure_dimensions`，生成最小 mutation；
- 不能把 provider 错误伪装成低分。

### 6.2 最终确认

对样片阶段排名最高且通过门槛的 1–2 个候选执行完整成片。最终候选执行两次确认：

```text
confirmation-1 -> 所有维度 >= 8 且总分 >= 8.5
confirmation-2 -> 所有维度 >= 8 且总分 >= 8.5
```

任一次失败时，只针对失败维度生成 repair；不直接整片随机重生成。

### 6.3 停止条件

提前停止条件：

- 两次最终确认均通过；
- 达到最大迭代数；
- 达到总成本或时延预算；
- 连续两轮总分提升小于 `0.1`；
- 最低维度没有提升；
- mutation fingerprint 已经执行过；
- 所有允许的 mutation 都失败。

未达标停止时：

```text
optimization_run.status = exhausted
publish = blocked
best_candidate = 当前最高分候选
```

最佳候选可以展示给用户，但不能标记为自动通过。

## 7. Pipeline 接入

启用该功能的 `cinematic-fast` 流程为：

```text
research
  -> proposal
  -> script
  -> scene_plan
  -> assets
  -> sample
  -> optimize_sample
  -> edit
  -> compose
  -> optimize_final
  -> publish
```

### 7.1 `optimize_sample`

输入：

- `candidate_batch`；
- `evaluation_report`；
- `production_lock`；
- `scene_plan`；
- `optimization_policy`。

输出：

- `optimization_run`；
- 更新后的 `candidate_batch`；
- 每个候选的 `evaluation_report`；
- 选中的 1–2 个候选。

行为：

1. 并行渲染候选样片；
2. 先执行确定性技术检查；
3. 技术通过后执行 video judge；
4. 统一 rubric、版本和权重；
5. 只有当前 beam 全部评分后才比较；
6. 没有候选达标时生成下一轮 mutation；
7. 有候选达标时停止产生不必要的新候选，进入最终渲染。

### 7.2 `optimize_final`

输入：

- `render_report`；
- `final_review`；
- final-scope `evaluation_report`；
- `optimization_run`。

输出：

- 更新后的 `optimization_run`；
- confirmation evaluation reports；
- final optimization decision。

publish 前必须同时满足：

```text
evaluation_report.hard_gate.pass == true
optimization_run.status == passed
```

当 `optimization_policy.enabled=false` 时，旧项目保持原有 pipeline 行为。

## 8. 成本、并发和决策治理

每轮成本顺序：

```text
静态 scene/mix 检查
  -> sample render
  -> technical_validator
  -> video_judge
  -> 仅对最终候选 full render
```

要求：

- `cost_tracker` 是实际预算来源；
- `candidate_batch.cost_usd` 只做候选索引；
- 候选级并行最多 3 个；
- 超出预算不得发起新的付费调用；
- provider/model/runtime 在一次 run 内固定；
- 所有 capability extension 写入 `decision_log`；
- 失败候选和报告必须保留，便于后续分析。

优化循环开始前需要一次人工批准：

- rubric 和阈值；
- 候选数量和预算；
- provider、model、runtime；
- 是否允许自动 mutation。

批准后，循环可以在锁定范围内自动运行；不需要每轮单独批准。最终 publish 仍沿用现有人工审批。

## 9. 实施文件

新增或扩展：

- `schemas/artifacts/optimization_policy.schema.json`；
- `schemas/artifacts/optimization_run.schema.json`；
- `schemas/artifacts/evaluation_report.schema.json`；
- `schemas/artifacts/candidate_batch.schema.json`；
- `schemas/artifacts/__init__.py`；
- `lib/optimization_run.py`；
- `lib/optimization_scoring.py`；
- `tools/analysis/video_judge.py`；
- `pipeline_defs/cinematic-fast.yaml`；
- `skills/pipelines/cinematic-fast/optimize-director.md`；
- `skills/pipelines/cinematic-fast/compose-director.md`；
- `skills/pipelines/cinematic-fast/publish-director.md`。

Python 只负责 schema 校验、分数聚合、状态转换、fingerprint 去重、预算限制和 artifact 持久化。候选选择、失败解释、mutation 选择和阶段推进仍由 director skill 编排。

## 10. 测试与验收

### 10.1 评分测试

- 任一维度 `7.99` 即失败；
- 总分 `8.49` 即失败；
- 边界值 `8.0` 和 `8.5` 正确通过；
- fatal L1a 存在时优化失败；
- required dimension 缺失或 skip 时失败；
- 非法分数被拒绝；
- judge/rubric 版本不一致时不可比较；
- 任一次 confirmation 失败时最终失败。

### 10.2 状态与预算测试

- 失败候选不会成为 best；
- rejected 媒体和报告仍然存在；
- 相同 mutation fingerprint 不重复；
- parent/child lineage 正确；
- 超预算后不再发起付费调用；
- provider 失败与质量失败分开记录；
- 最大迭代后状态为 `exhausted`；
- 旧版 artifact 仍可读取。

### 10.3 端到端验收

使用三个真实自有视频：

```text
video-01 / video-02 / video-03
```

验收结果必须包括：

1. 首轮 5 个不同混剪候选；
2. 每个候选有跨源镜头映射；
3. 样片先经过 L1a，再进入 VLM 评分；
4. 未达标时只针对最低维度生成下一轮；
5. 达标候选进入完整渲染；
6. 最终候选完成两次确认；
7. `optimization_policy`、`optimization_run`、`candidate_batch` 和评价报告均 schema-valid；
8. 失败候选完整留档；
9. 只有通过候选允许进入 publish。

正式启用自动门禁前，必须完成现有 judge calibration：每维度至少 100 个校准样本、双人标注与仲裁、Group Split、版本 replay 和随机性记录。校准不足时只能运行 shadow mode。

## 11. 分阶段落地顺序

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 冻结 rubric、阈值、权重和 policy schema | 边界测试通过 |
| P1 | 扩展 `evaluation_report` 和 `candidate_batch` | 旧 artifact 兼容，新增字段 schema-valid |
| P2 | 新增 `optimization_run` 和 score aggregation | 状态、预算、fingerprint 测试通过 |
| P3 | 新增 `optimize_sample` director 和候选 mutation | 三视频 mock 流程跑通 |
| P4 | 接入 final confirmation 和 publish gate | 任一确认失败均阻止 publish |
| P5 | Gold Set 校准和 shadow mode | 校准报告可复现 |
| P6 | 小预算真实 provider 试运行 | 失败候选留档，成本可追溯 |
| P7 | 按项目 policy 开启自动优化 | 旧项目行为不变 |

## 12. 默认假设

- 单维最低分采用 `8.0`；
- 加权总分阈值采用 `8.5/10`；
- 首轮 beam width 为 5，并发上限为 3；
- 最多 6 轮迭代，每候选最多 2 次重试；
- 最终确认执行 2 次；
- 质量 gate 只对新启用 `optimization_policy` 的项目生效；
- `table-mat-mix-v7` 等已有项目不受影响；
- 自动优化不得绕过现有人工审批、L1a hard gate 和发布契约。

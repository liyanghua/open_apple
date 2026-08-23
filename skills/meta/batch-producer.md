# Batch Producer（5 候选批量编排）

Before following this runbook, read `skills/meta/candidate-diversity-producer.md`.
Every new batch must materialize and obtain human approval for a candidate
variant plan before entering assets or sample.

> Design_Review_2026-08-22.md P1-2。本技能指导 Agent 完成"一次研究、五个创意方向、统一评分排序、人工选 1-2 条精剪"。编排判断属于 Agent；Python 只提供 `lib/candidate_batch.py` 的持久化与规则校验。

## 适用条件

- 一次 reference-driven 电商复刻任务，用户要求并行产出多个可比较候选；
- 首期 5 个候选，最大并发 2-3 条；评分与成本稳定后再扩展到 10（P2）。

## 编排流程

1. **共享研究（一次）**：跑一次 `cinematic-fast` research，产出九制品 +
   `caption_style_fingerprint`。共享边界（候选不得重做或偏离）：
   `reference_fingerprint`、`research_breakdown`、`reference_source_matrix`、
   `source_media_review`、`media_index`、`research_scorecard`、
   `caption_style_fingerprint`，以及事实证据与原创边界。
2. **建批**：`lib.candidate_batch.create_candidate_batch(...)` 写入
   `projects/batch-<batch_id>/candidate_batch.json`（batch 工作区，共享研究
   refs 记录在内）。库会为缺失 `variant_plan_ref` 的候选分配默认差异策略；
   分叉轴只允许：钩子 / 节奏 / 包装 / 人群 / 时长。
3. **分叉**：为每个候选创建独立项目（`projects/<project_id>`），分叉函数先
   落盘 `candidate_variant_plan.json`；proposal 阶段必须产出独立的 `hook_plan`
   （差异写入 candidate_variants）与独立创意合同；
   script / scene_plan / assets / sample 独立推进；研究制品以共享 refs 引用，
   不复制重做。
4. **审批门**：creative lock bundle 必须包含候选差异计划；计划状态为
   `awaiting_human` 时不得进入付费素材或样片调用。warning 模式只放宽差异
   不足的阻塞，不放宽人工审批。
5. **并发纪律**：同一时刻最多 `concurrency.max_parallel`（2-3）个候选在跑；
   每个候选的 sample 完成即 `record_candidate_result(status="sampled")`，
   `evaluation_report` 产出后 `record_candidate_result(status="evaluated",
   evaluation_report_ref=..., cost_usd=...)`；失败候选记录 failure 与失败原因。
6. **排序**：统一比较各候选 evaluation_report（hard_gate / 分数 / 失败项）、
   成本、执行差异与样片前 3 秒；排序结果写入 batch notes（或审核台展示）。
7. **人工选择**：用户在审核台选 1-2 条 → `select_for_edit(...)`（规则：必须
   `evaluated`、最多 2 条）→ 被选候选进入 edit/compose/publish。**绝不自动
   发布全部候选。**

## 纪律

- 共享研究只读：候选不得改写共享研究制品，差异只能出现在分叉轴内；
- 每个候选保留独立 artifact/checkpoint/decision_log（各自项目目录），
  `candidate_batch.json` 只是索引；
- 候选失败不清空其他候选，不静默重跑付费步骤（重试须用户确认）；
- 排序依据必须是同版本 judge（judge_version 一致，见评价体系契约）。

## P2：扩展到 10 候选与预算

- 五候选评分与成本稳定后，同流程扩展到 10（`max_candidates: 10`，
  `max_parallel` 仍限 2-3）；
- 建批时必带 `budget`：`max_cost_usd`（整批成本上限）、
  `max_latency_minutes`、`max_retries_per_candidate`；
  `record_candidate_result` 会拒绝超预算成本与超限重试（重试走
  `is_retry=True`，每次重试计数）；
- 排序依据必须同版本 judge（judge_version 一致），版本治理与校准见
  `skills/meta/judge-calibration.md`。

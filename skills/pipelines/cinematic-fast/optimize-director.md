# Optimize Director - Cinematic Fastline（批量混剪 + 可选自动迭代）

Read `skills/meta/batch-producer.md`、`skills/meta/judge-calibration.md` 与
`docs/art-plan/Autoresearch_Video_Remix_Integration_Design_2026-08-23.md`
before acting. Python owns schema 校验、分数聚合、状态转换、指纹去重与预算；
**候选选择、失败解释、mutation 选择和阶段推进由本 skill 编排**——不新增第二
套 orchestrator。

核心纪律（用户核心目标）：**先人工 review**。默认 `optimization_policy.
enabled=false`：一次研究 → 5 个候选 → 样片评分 → 用户选 1–2 条进精剪。
只有用户在 decision_log 里批准"启用自动优化"（rubric/阈值/候选数/预算/
provider/model/runtime/是否允许自动 mutation，见 Autoresearch §8）后，才把
policy 置为 enabled=true 进入自动迭代。

## 0. 前置（人工批准后才开始）

1. 素材池：多个自有/已授权视频，`source_media_review` + `media_index`
   完成；参考视频只用于分析，绝不进入 `shot_sources`。
2. 用户批准批量模式：候选方向、平台/时长、预算上限、provider/model/runtime。
   追加 decision_log（`category: "concept_selection"`）。
3. 冻结 `optimization_policy`：`lib.optimization_scoring.
   build_default_optimization_policy(project_id)`，enabled 按用户批准与否；
   写入 `artifacts/optimization_policy.json`。policy 一经运行不得修改。

## 1. 首轮：建批 → 分叉 → 并行样片（人工 review 模式）

1. `lib.candidate_batch.create_candidate_batch(batch_id, shared_research_refs=…,
   candidates=…, source_media_refs=…)` —— 5 个方向互不相同：结果先行 /
   痛点先行 / 证据链先行 / 高密度快剪 / 产品质感版；写入
   `batch-<id>/artifacts/candidate_batch.json`。
2. `lib.batch_fork.fork_candidate_projects(batch, source_project_dir=…,
   pipeline_dir=…)` —— 每个候选独立项目 + 共享研究制品 + analysis/ 派生
   证据 + completed research 检查点（B3 门会校验派生文件）。
3. 每个候选项目走 proposal → script → scene_plan → assets → sample：
   - **并发上限 2–3**（batch.concurrency.max_parallel），同一时刻不超过；
   - render payload 一律经 `lib.render_payload.build_render_payload(...)`
     组装，禁止手工拼 JSON；
   - BGM 检索词经 `lib.music_profile.music_profile_to_search_terms(
     research_breakdown.music_profile)` 映射；
   - 技术失败（provider/render）≠ 质量失败：按
     `max_retries_per_candidate` 重试，记录 `technical_failures`，绝不伪装
     成低分。
4. 每候选样片：`final_qa` → `technical_validator`（scope=sample）→
   `video_judge`（rubric `l3-v1.0`）。judge fail-closed：缺维/非法分直接
   失败重试；judge 不可用 → `scored=false`，不得宣称达标。
5. `lib.candidate_batch.record_candidate_result(...)` 回写
   `evaluation_report_ref` / `dimension_scores` / 成本。
6. 向用户呈现 scorecard（评价卡 + 前 3 秒对比 + 三轨音频）；用户选 1–2 条
   （`lib.candidate_batch.select_for_edit`，evaluated + 评价引用才可选）。
   选中候选各自 edit → compose → publish（publish 三态门见 publish-director）。

## 2. 自动迭代（仅 policy.enabled=true，且已人工批准）

0. **校准门**：启用前必须 `lib.gold_set.assert_judge_releasable(goldset,
   annotator_b=…, required_dimensions=policy["required_dimensions"])`——
   required 维度未全部覆盖（每维 n≥100）或双人 kappa 不达标一律拒绝，只能
   shadow mode。
1. `lib.optimization_run.create_optimization_run(...)`（冻结 policy 快照）→
   `begin_iteration(run, candidate_ids)`。
2. 本轮全部候选：technical_validator → video_judge（rubric
   `ecommerce-remix-v1.0`）→ `lib.optimization_scoring.
   aggregate_optimization_scores(policy, dims, hard_gate_pass=…,
   coverage_sufficient=…, rubric_version=…)` → 写入
   `evaluation_report.optimization` 区块 + candidate 分数。
3. `record_iteration(...)`：必须携带 `aggregate_optimization_scores` 产出的
   完整 block（`dimension_scores` + `weighted_total` + `failure_dimensions`）。
   状态机按冻结 `policy_snapshot` 重算达标性——总分/失败维度/required 维度
   任一不达标，`outcome="accepted"` 会被拒绝（不能只信调用方）。winner 必须
   达标才成 best（失败候选不会成为 best）；`technical_failures` 与
   `failure_dimensions` 分开记录。
4. 停止条件（`lib.optimization_run`）：`check_budget` / `plateau_reached` /
   `mutation_seen` / max_iterations（begin_iteration 自动 exhausted）。
   停止时 best_candidate 可展示，**不得标记为自动通过**。
5. 未达标 → 只按最低失败维度生成单一 mutation（Autoresearch §5 映射表）：
   一轮一个聚焦修改；改 provider/model/runtime/事实/主方向必须重新人工
   审批。mutation 指纹重复 → `stop_run("mutation_fingerprint_duplicate")`。
6. 达标 → `start_confirmation` + `record_confirmation`（§2.3 VLM 随机
   性）。`record_confirmation(passed=True)` 同样需携带完整
   `dimension_scores`，状态机会重算验证；**任一次失败立即切回 running**，
   只对失败维度生成 repair——不再执行下一次确认；修复后
   `start_confirmation(reset=True)` 重新开始确认。两次全过 →
   status=passed，方可 publish（publish 门会硬校验）。

## 3. 预算与治理

- `cost_tracker` 是实际预算来源；`candidate_batch.cost_usd` 只是索引。
- 超出预算不得发起新的付费调用（`check_budget`）。
- provider/model/runtime 一次 run 内固定；换任一须重新人工审批。
- 失败候选的媒体、报告、项目目录**保留**，回滚绝不删文件。
- 全部 capability extension 写入 decision_log。

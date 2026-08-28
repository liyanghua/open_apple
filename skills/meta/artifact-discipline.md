# 制品与事务纪律（Artifact & Transaction Discipline）

> 适用：任何对 template run / pack-library 制品的写入、重建、变体引导、跨 run 复制。
> 来源：c1/c2/c3/c4 变体流水线已踩且修复的真实坑（2026-08-28 归档）。

## 1. 事务边界（ProjectCommitStore）

1. **fork 必须先于项目中任何事务写入**：`fork_template_run` 内部写研究制品且不接受 sink——一旦项目有了 commit-store 标记（任何一次 `with ProjectCommitStore(...)` 成功写入后），后续 fork/裸写全部报「必须通过版本事务提交」。正确顺序：`mkdirt → fork（无事务进程内最先执行）→ 再进事务`；重复引导时跳过 fork（`checkpoint_research.json` 已存在即已播种）；
2. **staged 文件不可读**：事务内 `write_artifact_atomic` 写入是**暂存**，同一事务内 `json.load(场景文件)` 会 FileNotFoundError。需要读回 → **拆两个事务**（写事务提交后再读）；
3. **每写必带 sink**：事务内所有 `write_artifact_atomic(..., project_dir=..., sink=sink)`；事务外写库（pack/ledger）同样包事务（`ProjectCommitStore(pack_dir).transaction`）。

## 2. 制品一致性（哈希/信封）

4. **改数据必须重挂哈希**：手工 `json.dump` 修改制品（矩阵区间、账本字段）后，磁盘文件的 `artifact_sha256/semantic_sha256` 过期 → 任何 `validate_checkpoint/unwrap` 失败。正确姿势：`attach_hashes(dict(data))` + `write_artifact_atomic`（自带校验）；
5. **改制品后同步信封**：引用它的 checkpoint（研究包引 reference_source_matrix 等）必须 `refresh_checkpoint_envelopes` 或内联更新 envelope（`data` + 双哈希）后 `persist_checkpoint_atomic`；否则 READINESS/review 层报「Artifact disk data does not match embedded checkpoint data」；
6. **跨 run 复制 = 重基**：从父 run 复制 asset_plan/production_lock/approval_bundle 必须改 `project_id`（子 run）+ `input_hashes.base_run_plan_sha`（父计划真实 sha，64hex），再 attach_hashes——否则审批包证明的是父版本（P0-3 评审项）；
7. **schema 变更同步**：新增制品字段（per_template/strict_required/compression 契约）同时改 `schemas/artifacts/*.json`，否则 validate 直接抛错。

## 3. 重压/变体引导（rebuild → 发布）

8. **rebuild 后**：script/scene_plan 变化 ⇒ shot_execution_plan 漂移 ⇒ 先 `sync_assets_artifacts`（或让 prep 漂移同步），再进渲染；
9. **sample/edit 前**：先 `refresh_checkpoint_envelopes`（决策日志/提案包被 approve 脚本改写后必刷），否则「PREREQUISITE VIOLATION: research/proposal missing」假阳性；
10. **发布门**：正式版走 `strict_gate`（strict_required + strict_pass）；重压发布=新准入；已发布不追溯但重发布会被门拦截（这是特性）。

## 4. 反例速查（症状→根因）

| 症状 | 根因（本仓库实例） |
|---|---|
| 必须通过版本事务提交 | fork/裸写发生在项目已有 commit-store 标记之后 |
| staged 文件 FileNotFoundError | 同事务内读回自己刚写的文件 |
| Artifact disk data does not match | 手工改文件未重挂哈希，或 checkpoint envelope 未同步 |
| PREREQUISITE VIOLATION: missing ['research','proposal'] | 决定档/提案制品哈希变旧（approve 改写决策日志后未刷新信封） |
| 发布阻断: strict_gate | 正式版严格档未过（默认 05c1/14c1/19c1 曾触发） |
| scene ids must be unique | 克隆槽位 slot_id 尾号与既有槽位重复（scene id 从尾号派生） |
| 模板 slot 绑定旧值 | 改 pack 槽位后未重生成 run plan（match_run_plan 重新跑） |

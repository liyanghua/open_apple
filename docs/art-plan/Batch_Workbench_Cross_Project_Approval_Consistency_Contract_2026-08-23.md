# 批量工作台跨项目审批一致性契约

> 日期：2026-08-23
> 版本：v1.0
> 状态：实施前契约
> 适用动作：`batch_approve_gate`、`batch_select_for_edit`、`candidate_rerun`、`batch_rerun`
> 上游设计：[`Batch_Workbench_Interaction_Design_2026-08-23.md`](./Batch_Workbench_Interaction_Design_2026-08-23.md)

本契约定义批根项目与候选项目同时参与时的权限、幂等、乐观并发、提交和故障恢复。它不把多个单项目 `ProjectCommitStore` 调用伪装成一个事务。

## 1. 一致性目标

1. 批级审批对用户表现为 all-or-nothing：返回 `committed` 前，所有目标候选的 review、checkpoint、审批 bundle 和 decision log 都已提交。
2. 任一参与者 stale、无权限、校验失败或无法准备时，所有参与者仍保持原状态，动作返回结构化失败。
3. 提交后进程崩溃时，协调日志必须允许恢复器继续完成或回滚动作；不能留下“批页显示成功但候选状态不齐”的永久半提交。
4. 每个候选仍保留自己的 review 和 decision log；批级协调记录只建立关联，不合并审计。

## 2. 参与者与动作请求

批根项目是 coordinator participant；每个目标候选项目是 child participant。请求必须携带批级乐观并发和每个候选的审批快照：

```json
{
  "action_type": "batch_approve_gate",
  "gate": "sample",
  "aggregate_revision": "<64-hex>",
  "reason": "批量确认样片",
  "participants": [
    {
      "candidate_id": "direction-result-first",
      "project_id": "table-mat-mix-001-result-first",
      "review_id": "candidate-sample-v2-abc",
      "subject_version": 2,
      "subject_hash": "<64-hex>",
      "effect_confirmations": {
        "creative_direction": "pass",
        "hook": "pass",
        "proof": "pass",
        "pacing": "pass",
        "readability": "pass"
      }
    }
  ]
}
```

`script` 必须引用 `script_lock` review，`assets` 必须引用 `creative_lock` review，`sample` 必须引用 `sample` review 并提交五项确认。服务端仍需从候选项目重新读取并校验这些值，不能信任批页传回的展示数据。

`batch_select_for_edit` 只允许选择 1–2 个已 `evaluated` 候选；它必须携带 `aggregate_revision`、候选 evaluation revision/hash 和 reason。该动作只提交批根项目时，不需要 child commit，但必须重新确认候选仍可选。

局部修改先产生只读的 `rerun_plan`，再提交 `candidate_rerun` 或 `batch_rerun`。请求必须携带候选读取时的 `child_revision`、用户可读的 `intent_anchor`（时间段/镜头/质量维度/失败阶段）、自然语言 `instruction`、修改意图、系统计算的 `from_stage`、排序后的 `affected_stages`、`kept_stages`、预计成本和幂等键。服务端必须重新校验锚点仍属于该 revision，并重新计算依赖闭包与客户端计划比对；不一致返回 `validation_failed`，revision 变化返回 `stale`。重跑提交生成新 revision，旧版审批不继承，历史与 decision log 保留。

## 3. 协调记录

每个动作在批根项目创建一份 append-only coordinator record：

```json
{
  "schema_version": "1.0",
  "batch_action_id": "batch-action-uuid",
  "idempotency_key": "client-key",
  "request_digest": "<64-hex>",
  "action_type": "batch_approve_gate",
  "status": "preparing",
  "actor_id": "user-123",
  "aggregate_revision": "<64-hex>",
  "participants": [],
  "created_at": "2026-08-23T10:00:00Z",
  "updated_at": "2026-08-23T10:00:01Z",
  "recovery": {"required": false, "last_error": null}
}
```

参与者状态为 `pending`、`prepared`、`committing`、`committed`、`rolled_back`、`failed`。协调记录必须包含每个参与者的旧 generation、prepared generation、commit marker 和错误信息。

协调记录自身的 `status` 允许：`preparing`、`prepared`、`committing`、`committed`、`rejected`、`rolled_back`、`needs_recovery`、`replayed`。`rejected` 表示 prepare 阶段没有任何用户可见事实提交；`rolled_back` 表示 commit 曾经推进但已完成补偿恢复。

## 4. 提交协议

现有 `ReviewService.decide()` 会直接进入一个候选项目的 `ProjectCommitStore` transaction；它不能直接承担跨项目动作。实现必须增加 coordinator/prepare 能力，或允许 review service 把写入 staged sink，而不是在循环中逐个提交。

### 4.1 Prepare 阶段

1. 校验批根 `review` 权限，并逐个校验候选项目的 `review` 权限、候选归属和路径 containment。
2. 按规范化 `project_id` 排序获取参与者锁，避免锁顺序导致死锁。
3. 检查 `aggregate_revision`、每个 `review_id`、`subject_version`、`subject_hash` 和 review kind；任一不匹配返回 `stale`/`validation_failed`。
4. 检查 gate 专属前置条件：样片五项确认必须全部 `pass`；拒绝动作必须携带结构化 `issue_tags`。
5. 在每个参与者生成 prepared generation，暂存 review 状态、checkpoint、approval bundle、decision log 和 outbox 事件，但不更新 current-generation pointer。
6. 所有参与者准备成功后，协调记录进入 `prepared`；任何一个失败都清理未提交 generation，动作进入 `rejected`，不产生用户可见审批结果。

### 4.2 Commit 阶段

1. 协调器将记录标记为 `committing`，并按固定顺序提交各 prepared generation。
2. 每次 pointer 成功更新后写入参与者 `commit marker`。批根 coordinator record 只有在所有 marker 齐全后才进入 `committed`。
3. `committed` 结果包含批 action id、每个候选的 review id、候选新 revision 和批新 aggregate revision。
4. 提交成功后再通过 outbox/hub 发布 `gate_changed`；通知失败不回滚已提交事实，消费者可重新拉取状态。

### 4.3 崩溃与恢复

- `prepared`：恢复器可以安全地继续 commit 或清理 prepared generation。
- `committing` 且部分 marker 存在：恢复器读取 coordinator record，继续完成剩余 commit；若某参与者发生外部修改，动作转为 `needs_recovery`，禁止静默覆盖。
- 所有 marker 存在但 coordinator 尚未写入 `committed`：恢复器补写 `committed`，结果可安全重放。
- 无法完成继续提交时，按记录中的旧 generation 回滚已提交参与者；回滚本身生成新的恢复 generation，并写入审计，不删除历史。

恢复期间 API 返回 `503 needs_recovery`，批页显示“需要恢复”，不得显示为“已通过”。

## 5. 幂等、重放与冲突

1. `Idempotency-Key` 的作用域是批项目；`request_digest` 必须包含动作类型、gate、排序后的 participants、review 快照、确认项、reason 和 actor。
2. 同一 key + 同一 digest：返回原动作结果，状态为 `replayed`，不重复写 review 或 decision log。
3. 同一 key + 不同 digest：返回 409 `idempotency_conflict`。
4. aggregate revision 或任一 subject hash 变化：返回 409 `stale`，结果必须列出冲突候选及当前 revision；客户端重新拉取后重新发起新 key。
5. 已批准 review 的重放只能引用同一个 `batch_action_id`；不能因为“状态已经 approved”而把另一个批动作伪装成成功。

## 6. 审计与权限

每个成功候选至少写入：

- 候选自身 `operator/reviews/<review_id>.json`；
- 候选自身 `decision_log`，保留 `category`、`subject`、`batch_action_id`、actor 和 review 快照；
- 批根 coordinator record，记录 participant 状态和最终 aggregate revision；
- 批根 audit 事件，记录动作摘要，不复制候选详细决策。

拒绝仍沿用候选项目的结构化 `issue_tags` 和 `rework_round` 规则。批根权限不能替代候选权限；操作者必须同时拥有批级 review 权限和每个目标候选的 review 权限，否则整个动作在 prepare 阶段拒绝。

## 7. API 结果契约

| 状态 | HTTP | 含义 |
|---|---:|---|
| `committed` | 200 | 所有参与者已提交 |
| `replayed` | 200 | 幂等重放，返回原结果 |
| `stale` | 409 | 批 revision 或候选 review 快照过期 |
| `idempotency_conflict` | 409 | key 被不同请求复用 |
| `validation_failed` | 422 | gate、候选集合或确认项无效 |
| `forbidden` | 403 | 批或任一候选缺少 review 权限 |
| `needs_recovery` | 503 | 协调记录存在未完成提交，需要恢复 |

失败响应必须包含 `batch_action_id`（若已创建）、`participant_errors[]`、`current_revisions` 和 `retryable`，不能只返回一条“操作失败”。

## 8. 验收测试

- 参与者 1、2、N 个时，任一 prepare 失败都不会改变任何候选 review/checkpoint。
- commit 中途注入故障，恢复器能继续完成或按旧 generation 回滚，并留下完整 coordinator/audit 记录。
- 重复请求返回 `replayed`，不同正文复用 key 返回 409。
- 任一候选 review version/hash 过期时，整个动作返回 `stale`，其它候选不被批准。
- sample gate 缺少确认项或存在非 `pass` 值时，prepare 阶段拒绝。
- 批用户有权限但某个候选无权限时，整个动作拒绝且无副作用。
- 候选 decision log、review 文件、checkpoint 和批 coordinator record 的 action id 可互相追溯。

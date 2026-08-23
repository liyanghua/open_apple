# 批量工作台批级聚合状态与事件契约

> 日期：2026-08-23  
> 版本：v1.0  
> 状态：实施前契约  
> 适用范围：`candidate_batch` 根项目 `/p/<batch-id>` 的批级驾驶舱  
> 上游设计：[`Batch_Workbench_Interaction_Design_2026-08-23.md`](./Batch_Workbench_Interaction_Design_2026-08-23.md)

本契约解决两个问题：批页如何从批索引和候选子项目得到一个确定的批级状态；候选项目发生变化时，批页如何收到可去重、可补拉的更新通知。

## 1. 事实来源与边界

1. `candidate_batch` 是批级索引、候选成员清单、预算配置和选择结果的事实来源。它不复制候选项目的阶段、审批或评分详情。
2. 候选项目的当前 checkpoint、stage rail、pending review、evaluation artifact、sample trace 和 cost snapshot 是候选状态的事实来源。
3. 批级投影是只读派生数据。任何批级动作必须先写入相应事实来源，再重新计算投影；不得直接编辑投影字段。
4. 候选数量取 `candidate_batch.candidates.length`，不硬编码为 5。缺失项目、损坏制品和不一致 revision 必须保留为可见的降级状态，不能静默删除候选。

## 2. 批级状态载荷

`project_operator_state()` 对批项目仍返回既有顶层结构；当 `workspace.editor.type == "batch_review"` 时，`workspace.editor.data` 必须满足以下字段契约。字段名使用机器值，展示文案由前端本地化。

```json
{
  "schema_version": "1.0",
  "kind": "batch_review",
  "batch_id": "table-mat-mix-001",
  "aggregate_revision": "<64-hex>",
  "snapshot_at": "2026-08-23T10:00:00Z",
  "consistency": "stable",
  "phase": "scoring",
  "phase_reason": "3 个候选已完成样片，2 个候选等待评分",
  "rail": [],
  "candidates": [],
  "budget": {},
  "concurrency": {},
  "selection": {},
  "pending_gates": [],
  "warnings": []
}
```

### 2.1 顶层字段

| 字段 | 类型 | 约束 |
|---|---|---|
| `aggregate_revision` | string | 当前批快照的 SHA-256；由规范化的批 generation、候选 revision、选择和预算摘要计算 |
| `consistency` | enum | `stable`、`unstable`、`degraded` |
| `phase` | enum | `building`、`sampling`、`scoring`、`selection`、`editing`、`publishing`、`completed`、`blocked` |
| `rail` | array | 固定 6 个批级相位：`building`、`sampling`、`scoring`、`selection`、`editing`、`publishing` |
| `warnings` | array | 机器可读 `code`、候选 id、说明和建议动作；缺失/损坏候选不得只靠灰色样式表达 |

### 2.2 候选字段

每个 `candidates[]` 项必须包含：

```json
{
  "candidate_id": "direction-result-first",
  "project_id": "table-mat-mix-001-result-first",
  "label": "结果先行",
  "status": "evaluated",
  "candidate_phase": "evaluated",
  "child_revision": "<64-hex>",
  "stage_states": [],
  "pending_reviews": [],
  "score": {},
  "media": {},
  "cost": {},
  "links": {},
  "failure": null
}
```

`candidate_phase` 的机器值为：`planned`、`forking`、`sampling`、`sampled`、`evaluating`、`evaluated`、`selected`、`editing`、`composed`、`published`、`failed`、`missing`、`corrupt`。`status` 保留 `candidate_batch` 的原始状态，便于审计，不能用投影状态覆盖它。

`stage_states[]` 至少包含 `stage_id`、`status`、`version`、`updated_at`；`pending_reviews[]` 至少包含 `review_id`、`kind`、`subject_version`、`subject_hash`、`actions`。批页不得从“当前最新 review”猜测候选门状态。

### 2.3 预算、并发和选择

```json
{
  "budget": {
    "max_cost_usd": 30.0,
    "spent_usd": 8.2,
    "reserved_usd": 4.5,
    "remaining_usd": 17.3,
    "over_budget": false,
    "source": "cost_tracker"
  },
  "concurrency": {
    "max_parallel": 3,
    "active_count": 2,
    "active_candidate_ids": ["direction-a", "direction-b"]
  },
  "selection": {
    "selected_candidate_ids": [],
    "selected_at": null,
    "reason": "",
    "eligible_candidate_ids": ["direction-a", "direction-b"]
  }
}
```

`cost_tracker` 是预算数值的权威来源；`candidate_batch.candidates[].cost_usd` 只作为候选索引和显示回溯。若两者不一致，投影保留 `consistency=degraded` 和 `budget_mismatch` warning，不得把索引值当成已结算金额。

## 3. 相位归约规则

归约输入是批成员集合 `C`、每个候选的子项目快照和批级选择/预算事实。失败候选不阻塞仍有可选候选的相位，但会进入 warning 和候选留档。

1. `building`：批索引不存在、候选清单为空，或仍有候选项目缺失/未完成 fork。
2. `sampling`：至少一个候选尚未达到 `sampled`、`evaluated` 或 `failed`，且没有预算/权限/数据完整性阻塞。
3. `scoring`：所有存活候选均有样片，但至少一个存活候选尚未 `evaluated`。
4. `selection`：所有存活候选均 `evaluated`，存在至少一个可选候选，且尚未写入 `selection.selected_candidate_ids`。
5. `editing`：存在选中候选，且至少一个选中候选尚未完成 `edit` 与 `compose`。
6. `publishing`：所有选中候选均已完成 `compose`，但至少一个尚未完成 `publish`。
7. `completed`：所有选中候选均已完成 `publish`。
8. `blocked`：没有可选候选，且所有候选均为 `failed`、`missing` 或 `corrupt`；或预算、权限、恢复状态阻止继续推进。

相位判定必须同时输出 `phase_reason` 和候选明细。相位可以因 retry 或 rework 回退；`aggregate_revision` 必须变化，事件流记录 `phase_changed`，不能用 UI 层的单调进度假设掩盖回退。

## 4. Revision 与一致性

1. 候选快照读取后记录其 `child_revision`。批根项目记录 `batch_generation_id`。
2. `aggregate_revision = sha256(canonical_json({batch_generation_id, candidates:[candidate_id, project_id, child_revision, candidate_phase], selection, budget_summary}))`。
3. 组装期间若任一候选 revision 改变，响应仍可返回，但必须标记 `consistency=unstable`，并附 `snapshot_changed_during_read`；客户端收到后重新拉取完整状态。
4. `aggregate_revision` 是批动作的乐观并发前置条件。批级选择和门审批必须提交读取时的 revision，revision 不匹配返回 409，不得覆盖新状态。
5. 子项目路径必须经过项目 resolver 和 projects 根目录 containment 校验；不得直接拼接不受约束的 `candidate.project_id`。

## 5. 批级事件契约

批事件是批根项目的 append-only `operator/batch-events.jsonl` 事件流。事件不是状态真相；事件丢失时，客户端必须通过 operator-state 重新拉取。

```json
{
  "schema_version": "1.0",
  "event_id": "batch-event-000042",
  "event_seq": 42,
  "ts": "2026-08-23T10:00:00Z",
  "batch_id": "table-mat-mix-001",
  "type": "candidate_changed",
  "aggregate_revision": "<64-hex>",
  "candidate_id": "direction-result-first",
  "candidate_revision": "<64-hex>",
  "phase": "scoring",
  "payload": {"changed_fields": ["status", "score"]}
}
```

`type` 只允许：`snapshot_published`、`phase_changed`、`candidate_changed`、`gate_changed`、`selection_changed`、`budget_changed`、`consistency_warning`、`action_recovered`。同一批的 `event_seq` 严格递增；消费者以 `event_id` 去重，以 `event_seq` 检测缺口。检测到缺口、revision 不匹配或 SSE 重连时，先 GET 完整 operator state，再继续监听。

候选项目提交成功后，通过 outbox/事件 hub 向批根项目发布 `candidate_changed`；批页不能只监听批根项目自身的 SSE。事件投递失败不回滚候选事实提交，批投影读取必须能从候选项目恢复最新状态。

## 6. 验收测试

- 1、2、5、10 个候选均能正确生成矩阵和相位，不出现固定 5 列。
- 全部候选失败、部分失败、缺失项目、损坏制品、预算超限分别得到预期 `blocked/degraded` 状态。
- 候选 retry/rework 导致相位回退时，revision 变化且产生 `phase_changed`。
- 任一候选在聚合读取期间 revision 改变时返回 `unstable`，客户端可通过 revision 补拉收敛。
- 同一 `event_id` 重放不重复处理；event sequence 出现缺口时触发完整状态拉取。
- 候选项目事件能唤醒批页；批项目自身无新文件时也能收到子项目变化通知。

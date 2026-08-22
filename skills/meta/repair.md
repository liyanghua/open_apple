# Repair（四种局部修复）

> Design_Review_2026-08-22.md P1-3。修复是 edit 阶段内的局部变更，不是重跑
> 管线。判断由 Agent 做出；`lib/repair.py` 提供规则与持久化。

## 四种动作与最小渲染路线

| 动作 | 针对 | 默认渲染路线 | 影响范围 |
|---|---|---|---|
| `rewrite_hook` | 前 1-1.5s 钩子（口播首句/首帧画面） | `sample` | 样片窗口 + hook_plan 新版本 |
| `edit_caption` | 字幕样式/文案（在 `caption_style_fingerprint` binding 内） | `still`（动效改动时 `sample`） | 单帧字幕检查 / 样片 |
| `replace_asset` | 单镜头素材替换（同 shot_intent 内换源） | `sample` | 该镜头 + 样片窗口 |
| `shorten_shot` | 压缩镜头时长 | `full_render`（时间轴位移） | 后续所有镜头 |

## 纪律（不可违反）

1. **不动锁**：修复的 `production_lock_hash` 必须等于当前
   `production_lock.artifact_sha256`，`assert_lock_unchanged` 校验；任何触及
   锁定规则的变化走重新审批，不走 repair。
2. **不清空**：targets 必须显式列目标；不得"顺手"重建其他镜头。
3. **不回退**：repair 不使更早阶段失效；影响范围记录在
   `affected_stages` / `affected_shot_ids`，并按路线选择 still / sample /
   full 重渲染。
4. **留痕**：每次修复 = 新 `repair` artifact（rework_round 递增）+
   `decision_log` 追加 `category: "rework_cause"`（带 `issue_tags` 与
   `rework_round`，见决策契约） + `change_impact` 由既有 edit 机制生成。

## 流程

```text
evaluation_report / 五项效果确认发现问题
  → plan_repair(action, targets, evaluation_report_ref, production_lock_hash)
  → assert_lock_unchanged(repair, current_lock_hash)
  → 执行变更（hook_plan/captions/asset_manifest/edit_decisions 对应子集）
  → 按 render_route 重渲染（still=单帧检查, sample=样片窗口, full=全片）
  → repair_decision_entry + decision_log 追加
  → 复审（评价卡重跑：hard_gate 必须不劣化，repair_targets 清零或更新）
```

# 素材容量与长片压缩设计（Material Capacity & Long-Form Compression）

> 日期：2026-08-27
> 状态：技术设计（待评审）
> 依据：`skills/meta/template-platform-standards.md`（H1-H4 标准）、`skills/meta/template-material-pool-design.md`（6×2 最小可证明集）
> 触发：>30s 长片在 6 素材池下重复率超标（H3 完全重复窗口最高 92 处 / H2 占片最高 59%）

---

## 1. 背景与问题定义

**现状**：6 素材池（每动作域仅 1 支）× 43 模板。30+ 镜长模板（21-30 镜）中，故事强绑定导致：
- 同一素材被复用 6-18 次（14 片「餐桌场景」18 镜 / 占片 59%）；
- 复用窗口回落时产生**完全重复窗口**（同一 2s 片段逐帧复用，14 片 92 处）；
- H1（相邻同素材）与 H2（占比 ≤33%）在 6 池下对 N>12 镜结构**数学上不可满足**。

**约束**：现有架构内优化（同一主链路/制品/看板），不新增旁支链路；语义一致性（文案=绑定素材可见动作）为硬门，不允许牺牲。

## 2. 目标与成功标准

| 目标 | 标准 |
|---|---|
| 可判定 | 每个模板起片前，自动输出「策略选择 + 理由」（材料充足度数学判定） |
| 可行动 | 素材不足 → 权威缺口账单（模板/域/需求/容量/建议镜位）；允许缩短 → 压缩方案（非删即选） |
| 可验收 | 压缩/多样化后的成片：H1-H4 全过、语义 0、时长 ∈ [15,60]s、证书+发布门全绿 |
| 可追溯 | before/after 报告（镜数/时长/H1-H4/占比/成本）+ overview 对照 + decision_log 记录 |

## 3. 判定模型（容量可行性）

```
输入：模板 T（N 镜；每镜动作域 d[i]，来自 SLOT_ACTION_BY_TEMPLATE 或 _best_action）
      素材池 P（各域素材数 m[域]）
输出：verdict ∈ {DIVERSIFY, COMPRESS, MARK_GAP} + 理由

FEASIBLE1(diversify 前提) = ∀域∈d[T]: m[域] ≥ 2
FEASIBLE2(H1/H2 可满足)   = ∀域∈d[T]: count_域[T] ≤ 2×m[域]
                           且 max_域(count_域[T]) / N ≤ 1/3

verdict:
  FEASIBLE1 ∧ FEASIBLE2          → DIVERSIFY（策略 1 多样化分配）
  ¬FEASIBLE2 ∧ 业务允许压缩时长   → COMPRESS（策略 2b，默认优先）
  ¬FEASIBLE2 ∧ 不允许压缩         → MARK_GAP（策略 2a，标缺口/挂起）
```

> 判定计算复用 `material_reuse_report` 的数学部分（N/M 上限、占比下限），
> 输出 `material_capacity_verdict()` 供起片前调用（research/script 阶段 gate）。

## 4. 策略 1：多样化优先分配（DIVERSIFY）

**前提**：池达标（每域 ≥2 支）。分配升级（现有 `match_run_plan` + 窗口分配器之上）：

1. **域外不同优先**：每镜优先取「未用过的动作域」素材；同一域多次使用时**负载均衡**（选使用次数最少的素材）；
2. **邻镜冲突消除（H1）**：若相邻两镜同域 → 在「其后 ≤2 镜内同动作域的另一支素材」处做**语义等价交换**（仅换素材/窗口，文案不动）；再冲突才认 H1；
3. **窗口最大差异化（H3/H4）**：已有分配器保证（无重叠位时取与已用窗口起点距离最远）；
4. **相似度度量**：
   - 本期近似：入池标准强制「域内多镜 = 不同机位/景别」+ H4 窗口起点差（现有）；
   - P2 升级：VLM 帧 embedding 相似度阈值（同素材多窗口画面相似度 ≤ 0.85），替代起点差近似。

## 5. 策略 2a：素材缺口标记（MARK_GAP）

**容量预检（绑定前，fail-fast）**：
- 每个动作域：`需求 count_域[T]` vs `容量 2×m[域]`；不足 ⇒ 该域超出部分镜降级 `source=generate`，
  `reason = "素材缺口：<域> 需 N 镜，池内仅 M×2 容量"`；
- 输出**权威账单**：`projects/template-pack-library/artifacts/material_gaps.json`：

```jsonc
{
  "version": "1.0",
  "policy_ref": "docs/rules/business-policy.yaml",
  "generated_at": "…",
  "gaps": [
    {
      "domain": "餐桌场景", "affected_templates": ["sheet-14-…", "sheet-19-…"],
      "needed_shots": 4, "capacity_shots": 2, "deficit": 2,
      "suggested_shots": [
        {"scene": "家庭餐桌近景·食物", "duration_s": 6, "framing": "近景"},
        {"scene": "全景·家人入座", "duration_s": 6, "framing": "全景"}
      ],
      "priority": "P0"
    }
  ]
}
```

- 消费方：overview 页「素材缺口」展示（红标+账单链接）；批量计划按缺口排序（先补资后跑片）；
- 判定语义：缺口镜若为**尾部 CTA/重复卖点**且无独立叙事价值 → 建议删除（转 2b），不进入付费生成清单。

## 6. 策略 2b：压缩时长 + 剧本结构重排（COMPRESS，默认路径）

**目标**：不重写文案的前提下，通过「删重复镜」得到满足 H1-H4 的长度（业务 R15 ≥15s）。

**压缩器**（`scripts/compress_template_run.py`，输出为新 run 计划变体）：

```
输入：模板 slots（镜序/时长/域/叙事角色）、目标时长（或目标镜数）
S1 配额：每域 q(域) = min(count_域, ceil(目标镜数 × 1/M))    # H2 ≤ 1/3 自动满足
S2 骨架（强制保留）：hook 首镜 · 每域首个代表镜 · proof 域各保留 1 · payoff/cta 尾镜
S3 贪心删减：按「重复度效用」删——每域超出 q 的部分，优先删「与前镜同域」
   且 narration 最短的镜像行；叙事弧顺序不动（跳过而非重写）
S4 时长重算：保留镜 duration 不变；总长 = Σ；校验 15s ≤ 总长 ≤ 60s；超 60 → 继续删最低效用行
S5 输出：`template_run_plan.compressed.json`（新 run 计划：{base_run_plan_ref,
   kept_slot_indices[], durations[], total_duration_seconds, quota_report,
   h_feasibility{material_reuse_report 判定}}）
S6 链路：kept_slot_indices → 复用现有 rebuild/script(取对应行)/assets/prep/render/QA/证书/发布
   —— 全程零文案重写；原 30 镜版本保留（历史/对照）
```

**示例**：sheet-14（30 镜/58s，餐桌场景 18 镜）→ 目标 18 镜/36s：
- 配额：6 域 × ≤3（`ceil(18/6)=3`）；S2 骨架 = hook/20年、免费裁切-桌角、检测-无甲醛、防刮、防油、家庭代表 2、CTA；
- 删 12 个重复家庭镜；结果 H1/H2 自动通过（正反例在验收矩阵验证）。

**业务约束**：压缩不得删证据链（每域 ≥1 代表）；如业务不允许缩短 → 该模板锁定 2a。

## 7. 数据契约

| 制品 | 说明 | 校验 |
|---|---|---|
| `material_capacity_verdict()` | 起片前判定（函数，不落盘） | 单元测试：3 个 verdict 分支 |
| `material_gaps.json`（新 schema） | 缺口账单（§5） | schema + 非负/模板关联校验 |
| `template_run_plan.compressed.json`（新 schema） | 压缩计划变体（§6 S5） | schema + 保留行可回溯 + H 判定 |
| `scene_plan/script/shot_execution_plan` | 复用现有键控/语义字段 | 现有不变量全量回归 |

## 8. 实施任务拆分（P0/P1/P2）

| # | 任务 | 文件 | 依赖 |
|---|---|---|---|
| P0-1 | `material_capacity_verdict` + 单元测试（3 分支） | `lib/template_source_match.py` + tests | 无 |
| P0-2 | 容量预检接入 `check_template_run_plan_ready`（fail-closed 缺口即阻断付费） | `lib/template_run_plan.py` | P0-1 |
| P0-3 | `material_gaps.json` 账单生成 + schema | 新 `lib/material_gaps.py` + `schemas/artifacts/material_gaps.schema.json` | P0-1 |
| P0-4 | overview「素材缺口」展示 | `backlot/overview_state.py` + `overview.js` | P0-3 |
| P1-1 | 压缩器脚本 + 压缩变体 schema + tests | `scripts/compress_template_run.py` + schema | P0-1 |
| P1-2 | 压缩变体 → 主链路（rebuild 消费 kept_slot_indices） | `lib/template_mainline.py` | P1-1 |
| P1-3 | 4 片存量方案输出（用 09/14/19/05 出压缩候选，业务选版） | 报告 | P1-1 |
| P2-1 | 分配器多样化升级（负载均衡 + H1 邻镜等价交换） | `lib/template_source_match.py` | 池达标后 |
| P2-2 | VLM 相似度阈值（帧 embedding） | 新分析步骤 | P2-1 |

## 9. 验收矩阵

| 门 | 要求 |
|---|---|
| 判定正确 | 3 个 verdict 分支各有反例测试（构造成片/长片/缺口） |
| 缺口账单 | deficit>0 模板全部被列出；列出的缺口对应 2×m 容量计算正确 |
| 压缩正确 | 18 镜示例：保留骨架齐全、H1-H4 全过、语义 0、时长 36s、原 30 镜版保留 |
| 全链回归 | `tests/lib/test_template_invariants.py` 全绿 + 现有 713 passed 不回退 |
| 业务可见 | overview 增加「素材缺口」列/面板；压缩前后对照报告可导出 |

## 10. 非目标（本期）

- 不自动重写文案（压缩只删行；文案语义违规走现有 semantic gate）；
- 不自动触发付费生成补缺（只标记账单，生成由人决策）；
- 不做 VLM 相似度评分（P2）；
- 不做 43 模板全量判定（先 6 张已固化 + 长模板族）。

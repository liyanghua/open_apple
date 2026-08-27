# 素材容量与长片压缩设计（Material Capacity & Long-Form Compression）

> 日期：2026-08-27
> 状态：技术设计（修订待评审）
> 依据：`skills/meta/template-platform-standards.md`（H1-H4 标准）、`skills/meta/template-material-pool-design.md`（6×2 最小可证明集）
> 触发：>30s 长片在 6 素材池下重复率超标（H3 完全重复窗口最高 92 处 / H2 占片最高 59%）

---

## 1. 背景与问题定义

**现状**：当前池为 6 个动作域各 1 支素材，覆盖 43 个模板。长模板中，模板结构把多个 slot 集中到同一动作域，导致同一素材被复用 6-18 次；窗口耗尽后还会出现完全重复窗口（14 片最高 92 处），单素材时长占比最高 59%。

这里要区分四个对象：

- **slot `i`**：模板中的一个镜头位置，带时长、动作域、叙事角色和原始文案行引用；
- **动作域 `d`**：素材可以证明的语义动作，如“防刮”“餐桌场景”；
- **素材 `a`**：一支物理源视频，素材可属于一个或多个动作域；
- **证据窗口 `w`**：素材内可证明该 slot 动作的合法区间，窗口长度必须覆盖 slot 时长。

H1/H2 的困难不是“镜头数 N>12 就必然不可行”。例如 6 个素材按 `A,B,C,D,E,F` 循环，任意 N 都可以满足 H1/H2。真正的可行性取决于：

1. 最终保留序列中的相邻关系；
2. 单个素材的加权时长占比；
3. 每支素材的合法证据窗口和 H3/H4 间隔；
4. 语义、叙事骨架、口播时长和业务时长门。

**约束**：继续使用现有主链路、制品和看板；语义一致性（文案必须由绑定素材证明）为硬门；缺口不能静默替换为其他动作素材，也不能在未授权时触发付费生成。

## 2. 目标与成功标准

| 目标 | 标准 |
|---|---|
| 可判定 | 起片前输出全量分配是否可行、压缩是否可行、或缺口原因；结果带输入版本和策略理由 |
| 可行动 | 不可行时输出素材/窗口缺口账单；可删镜时输出可回溯的 slot 子集 |
| 可验收 | 最终成片通过 H1-H4、语义硬门、口播覆盖、TTS 时间适配、时长 `[15,60]s`、证书和发布门 |
| 可追溯 | 保存 before/after 镜数、时长、每素材占比、窗口、H1-H4、成本、输入 hash 和决策记录 |

## 3. 判定模型与约束优化

### 3.1 标准化输入

优化器不能直接依赖散落在 Python 中的关键词猜测。每个模板先生成版本化的 `slot_semantics`：

```text
slot_id, ordinal, duration_s, action_domain, beat_role,
source_section_ref, utility, required_group, predecessor_refs,
candidate_assets[], candidate_windows[]
```

`candidate_assets/windows` 必须来自已审核素材和语义证据窗口；不兼容的素材不进入候选集。`action_domain` 和 `beat_role` 不能只存在于 `SLOT_ACTION_BY_TEMPLATE` 或按位置推导的脚本表中。

### 3.2 决策变量

设 `I` 为原始 slot 集合，`A` 为素材集合，`W(i,a)` 为 slot `i` 使用素材 `a` 的合法窗口候选：

```text
y_i       ∈ {0,1}       # slot i 是否保留（压缩时可为 0）
x_i,a,w   ∈ {0,1}       # slot i 是否绑定素材 a 的窗口 w
p_i,j     ∈ {0,1}       # i、j 是否为最终保留序列中的相邻 slot
```

基本绑定约束：

```text
Σ(a,w) x_i,a,w = y_i
```

`p_i,j` 只允许在 `i<j` 时取 1，并表示 `i、j` 是删除 slot 后的最终相邻对：

```text
p_i,j ≤ y_i, p_i,j ≤ y_j
p_i,j ≤ 1-y_l                 for every i<l<j
每个保留的非末 slot 恰有一个 successor；每个保留的非首 slot 恰有一个 predecessor
```

实现可以用首/末哨兵变量完成“恰有一个”的边界约束；不能把原始 `i,i+1` 直接当成最终相邻关系。

### 3.3 目标函数

采用词典序目标，避免用未经校准的权重掩盖硬门失败：

1. 满足全部硬约束；
2. 最大化保留 slot 的叙事/证据效用 `Σ utility_i * y_i`；
3. 最小化目标时长偏差。若目标时长为 `D*`，引入 `Δ_T≥0`，约束 `D-D*≤Δ_T`、`D*-D≤Δ_T`，目标最小化 `Δ_T`；
4. 最小化同素材视觉相似度、素材负载不均和可选生成成本。

“重复度效用”“narration 最短”必须落成可计算字段或相似度函数，不能只写成自然语言规则。

### 3.4 硬约束

- **语义**：`x_i,a,w=0` 当素材 `a/w` 不能证明 slot `i` 的动作；保留的 narrated slot 必须满足实测 TTS 时长不超过 slot 时长；
- **H1**：对最终保留序列中的每个相邻对 `(i,j)`，不能绑定同一素材；删除 slot 后产生的新相邻关系也必须检查；
- **H2**：令 `L_a = Σ(i,w) duration_i * x_i,a,w`，`D = Σ_i duration_i * y_i`，每支素材满足 `L_a ≤ D/3`。这是素材级、时长加权约束，不是动作域镜头数约束；
- **H3**：同一素材不能使用完全相同的 `(start,end)` 窗口；
- **H4**：按最终时间轴中同一素材的使用顺序，相邻窗口起点差至少 `0.75s`；若业务要求窗口不重叠，必须另列为独立硬约束。H4 在发布标准中属于硬门时，代码中的 `REUSE_SOFT` 命名必须同步修正，不能让“软指标”与 `hard_pass` 语义冲突；
- **骨架**：Hook、每个必需证据域、payoff、CTA 的最小数量和顺序由 `required_group/predecessor_refs` 定义；
- **时长**：`15 ≤ D ≤ 60`，并以实际保留 slot 时长求和为准；不允许用“目标镜数”代替时长；
- **来源**：COMPRESS 只允许已审核 owned 素材；MARK_GAP 状态下不得自动把缺口改成 `generate`。

### 3.5 三步判定

定义：

```text
F_full = 上述模型在 y_i=1、仅使用 owned 素材时有解
F_comp = 上述模型在 y_i 可删、仅使用 owned 素材时有解
```

判定顺序：

```text
F_full 且满足域内多样化政策       → DIVERSIFY
F_full 但不满足域内多样化政策      → DIVERSIFY_LIMITED（H1/H2 已通过但池不足以多视角）
非 F_full 且允许压缩且 F_comp       → COMPRESS
否则                               → MARK_GAP
```

`DIVERSIFY_LIMITED` 是质量告警，不得被误报成 H1/H2 数学不可行。若产品坚持只保留三个状态，必须把该状态明确映射为 `DIVERSIFY` 加结构化 warning。

## 4. 策略 1：多样化分配（DIVERSIFY）

DIVERSIFY 是 `F_full` 的一个可行绑定解，不是简单的“每域至少 2 支素材”判断：

1. 仅从 slot 的兼容素材集合中分配；
2. 在满足 H1/H2 后，最小化每支素材的负载方差，并优先不同机位/景别；
3. 对最终时间轴检查 H1，不能只检查原始 slot 的相邻位置；
4. 从已标定证据窗口生成候选起点，显式检查 H3/H4；候选耗尽时返回无解，不允许静默接受违规窗口；
5. 现阶段用入池机位/景别差异 + 窗口起点差作为近似，P2 再引入经标定的帧 embedding 相似度。

素材“容量”定义为窗口级容量，而不是固定的 `2×素材数`。对素材 `a`、slot 时长 `l` 和 H4 间隔 `δ`，应从离散到帧的合法候选窗口计算 `C(a,l,δ)`；不同 slot 时长、不同证据窗口的容量可以不同。

## 5. 策略 2a：素材缺口标记（MARK_GAP）

MARK_GAP 表示“全量分配和允许删镜的 owned-only 模型均无解”，输出账单并阻断当前 run 的付费资产阶段。

账单建议为 `projects/template-pack-library/artifacts/material_gaps.json`，至少包含：

```jsonc
{
  "version": "1.1",
  "policy_ref": {"path": "docs/rules/business-policy.yaml", "sha256": "…"},
  "generated_at": "…",
  "gaps": [
    {
      "domain": "餐桌场景",
      "affected_templates": ["sheet-14-…"],
      "needed_shots": 8,
      "capacity_shots": 6,
      "deficit": 2,
      "capacity_basis": "合法证据窗口 + H3/H4 + slot duration",
      "suggested_shots": [
        {"scene": "家庭餐桌近景·食物", "duration_s": 6, "framing": "近景"}
      ],
      "priority": "P0"
    }
  ]
}
```

缺口 slot 在当前 run 中保持 `unbound` 或 `capacity_gate=blocked`，不能写成可直接付费的 `generate`。人批准补缺后，必须创建新版本 run plan，显式记录生成 slot、成本和批准决策；否则继续走 COMPRESS 或挂起。

如果缺口 slot 是尾部 CTA/重复卖点，删除建议必须作为 COMPRESS 候选重新求解，不能直接从账单推断“删除后必然可行”。

## 6. 策略 2b：压缩时长与 slot 子集优化（COMPRESS）

目标是在不重写文案的前提下，选择一个满足硬约束的保留 slot 子集。压缩不是固定域配额，而是上述模型中 `y_i` 可变的子集优化。

流程：

```text
S1 读取标准化 slot_semantics、合法素材窗口和目标时长区间
S2 强制保留 required_group 中的 hook/证据/payoff/cta，并满足 predecessor_refs
S3 求解 y_i、x_i,a,w；删除后的最终相邻关系重新检查 H1-H4
S4 按实际 duration 求和，校验 15-60s、TTS fit 和证据覆盖
S5 输出 compressed plan、solver_version、输入 hash、保留 slot_id 和原始 section 引用
S6 主链路只消费保留 slot；原始 run plan 保留用于历史和 before/after 对照
```

`kept_slot_indices` 可以保留作便捷字段，但权威键应是稳定的 `kept_slot_ids[]`；每个保留 slot 必须带 `base_section_ref`，保证“零文案重写”可审计。

### sheet-14 数字校正

当前 sheet-14 是 30 个 slot、总时长约 58.2s，其中动作域计数为：餐桌 18、检测 4、桌角 3、防油 3、防刮 2、铺开 0。旧的 `ceil(target_mirror_count/M)` 配额在目标 18 镜时最多只能保留 14 镜，因此不能作为压缩算法。

若保留 CTA 尾闪（约 0.2s）且其它保留镜头维持 2s，18 镜的实际时长应按所选 slot 求和；“17 个 2s 镜头 + 0.2s CTA”是 34.2s，不是 36s。若业务要求 36s，必须明确允许保留 18 个 2s 镜头再加 CTA（19 个 slot，约 36.2s），或明确允许调整时长；当前设计不允许把 36s 写成固定验收结果。

## 7. 数据契约

| 制品 | 说明 | 校验 |
|---|---|---|
| `slot_semantics` | slot 的动作域、叙事角色、文案行、效用、依赖和候选窗口 | schema、slot_id 唯一、引用可回溯 |
| `material_capacity_verdict` | 全量/压缩模型的结构化结果 | 三种主状态 + `DIVERSIFY_LIMITED`、输入 hash、失败约束 |
| `material_gaps.json` | 窗口级缺口账单 | schema、非负、模板关联、policy snapshot |
| `template_run_plan.compressed.json` | 原计划的可回溯 slot 子集 | base hash、kept slot_id、section ref、时长、quota_report（如仅作统计）、H 判定 |
| `scene_plan/script/shot_execution_plan` | 由保留 slot 重新生成的主链路制品 | 键控引用、语义、TTS fit、现有不变量全量回归 |

## 8. 实施任务拆分（P0/P1/P2）

| # | 任务 | 文件 | 依赖 |
|---|---|---|---|
| P0-1 | 标准化 `slot_semantics`、窗口候选和素材级 H1/H2/H3/H4 可行性判定 | `lib/template_source_match.py` + tests | 无 |
| P0-2 | 将全量/压缩判定接入 `check_template_run_plan_ready`；缺口 fail-closed，禁止默认素材回退 | `lib/template_run_plan.py`、`lib/template_mainline.py` | P0-1 |
| P0-3 | 生成带窗口容量依据和 policy snapshot 的缺口账单 | 新 `lib/material_gaps.py` + schema | P0-1 |
| P0-4 | overview 展示 verdict、缺口、阻断原因和 before/after 引用 | `backlot/overview_state.py` + `overview.js` | P0-3 |
| P1-1 | 子集压缩器（确定性求解/枚举）、压缩 schema 和测试 | `scripts/compress_template_run.py` + schema | P0-1 |
| P1-2 | 主链路按 `kept_slot_ids` 消费，script 保留 `base_section_ref`，禁止按位置重配文案 | `lib/template_mainline.py` | P1-1 |
| P1-3 | 对 09/14/19/05 生成压缩候选和无解报告，业务选版 | 报告 | P1-1 |
| P2-1 | DIVERSIFY 的负载均衡、最终序列 H1 和窗口候选优化 | `lib/template_source_match.py` | 池达标后 |
| P2-2 | 经校准的 VLM/帧 embedding 相似度 | 新分析步骤 | P2-1 |

## 9. 验收矩阵

| 门 | 要求 |
|---|---|
| 判定正确 | 覆盖 `DIVERSIFY`、`DIVERSIFY_LIMITED`、`COMPRESS`、`MARK_GAP`；包含 `FEASIBLE1=false 但 H1/H2 可行` 的反例 |
| H1/H2 建模 | 18/30 同域、2 个素材交替的场景不得被误判；变化 slot 时长按时长占比判定 |
| 压缩正确 | 删除后产生的新相邻关系重新检查；骨架、前置依赖、语义、TTS fit、15-60s 全通过 |
| sheet-14 | 不再使用 14 镜配额结论；输出实际保留 slot、真实总时长和无解原因 |
| 缺口安全 | MARK_GAP 不得进入 paid assets；不得把空绑定回退为默认动作素材；补缺需新 run plan + 人工决策 |
| 窗口正确 | H3/H4 在帧精度候选上可复现；候选耗尽时返回无解而非接受违规窗口 |
| 全链回归 | `tests/lib/test_template_invariants.py` 全绿，现有 713 passed 不回退 |
| 可见性 | overview 展示 verdict、容量依据、缺口、压缩前后对照和 artifact hash |

## 10. 非目标（本期）

- 不自动重写文案；文案语义违规继续走现有 semantic gate；
- 不在 MARK_GAP 中自动触发付费生成；生成必须由人批准的新 run plan 承载；
- 不把 VLM 相似度作为本期硬门；
- 不做 43 个模板全量语义标定，先覆盖 6 张已固化模板和长模板族；
- 不把“每域 2 支素材”解释成每支素材只能使用 2 次；实际容量由合法窗口、slot 时长和 H3/H4 计算。

---

## 附录 A：评审细化补丁（2026-08-27，评审组确认；不改主文，实现以此为准）

### A1. 求解器选型与确定性（对应 §8 P1-1 / §3.2-3.3）

- **N ≤ 18**：确定性回溯/枚举（剪枝 = 骨架强制保留 + 效用上界；保留集按字典序枚举，首个满足目标者胜出）；
- **N ≤ 30**：OR-Tools CP-SAT，固定 `seed=42`，`max_time_seconds=10`；不可变 `solver_version="cp-sat-1.0"`；
- 压缩制品必须输出 `solver_version` + 输入 hash（契约中 "solver_version、输入 hash" 由此落地）；
- **效用规则（可计算，P0-1 落字段）**：`utility_i = role_base + domain_scarcity_bonus`：
  `hook/cta=10, reveal=7, payoff=8, proof=6, problem/escalation=5, other=4`；
  `domain_scarcity_bonus = +2`（该域素材数=1 时，+1 每支素材=2 时取 0.5，向上取整为 +1）；相邻重复扣分在目标第 4 项，不进入 utility。

### A2. DIVERSIFY_LIMITED 阈值（对应 §3.5 / §4）

每条必需动作域 `d`：`m[d] ≥ 2` **且** 最终绑定中该域使用素材数 `≥2` 支 → TRUE；
任一域不满足 → `DIVERSIFY_LIMITED` + 结构化 warning（`constrained_domains=[...]`）。
阈值常量：`DIVERSIFY_MIN_ASSETS_PER_DOMAIN = 2`。

### A3. 窗口容量函数 C(a,l,δ) 算法契约（对应 §4 第 5 点 / §5 capacity_basis）

```
输入：素材 a（动作域 d）、slot 时长 l、H4 起点差 δ=0.75、步长 step=0.25
1) 合法窗口 = SEMANTIC_EVIDENCE_WINDOWS[d] ∩ [0, source_duration(a)]，长 L
2) 候选起点集 S = {s | s ∈ [0, L-l]，步长 step，[s, s+l] ⊆ 合法窗口}
3) 容量 C = S 上按 δ 间隔的最大独立集大小（贪心：起点升序，取与上一所选起点差 ≥ δ）
输出：{capacity, candidates(S), basis: {evidence_window, source_duration, slot_s, step, gap}}
任一 slot 的无解情形：C < 该域所需次数 → 缺口（capacity_basis 写入账单，见 P0-1 实现）。
```

### A4. 验收基线（对应 §9）

「全链回归」以**全量**为准：`tests/lib tests/tools tests/pipelines tests/contracts tests/qa tests/backlot`
（当前基线 1675 passed / 10 skipped / 0 failed；新增用例后该数字更新，不回退）。

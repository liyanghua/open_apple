# Judge Calibration（judge 版本治理与校准协议）

> Design_Review_2026-08-22.md P2。数据层在 `lib/gold_set.py`；本技能定义协议与
> 执行纪律。目标：评价版本可重放、评分变化可解释、升级不劣化。

## Gold Set 四层样本

- **Gold / Silver / Bad / Hard Negative**：Hard Negative 必须带 failure_tags；
- 每个样本同时保存：pointwise 分数、pairwise 引用、claims/QA（含时间戳证据）、
  failure tags、专家理由、人工采纳、online_outcome（接口占位，仅后验反馈，
  **不替代前置人工确认**）；
- 每个样本带 `group_key`（SKU/类目/创意模式），`assign_group_split` 按组整体
  落入 train/dev/test（防同模板泄漏）。

## 校准协议（门槛，未满足时结论自动降级为方向性）

1. 样本量：每维度 n ≥ 100 起步，按 bootstrap CI 宽度决定最终量；
2. 标注：双人独立标注 + 仲裁；IRR 用 Cohen's kappa（起步参考 ≥ 0.6，
   上线前校准）；不一致样本必须走 arbiter；
3. 报告：六维**分别**报告 Spearman/Kendall + bootstrap 95% CI，不做单一聚合
   数字；Critical FAR/FRR 单独报告；
4. 版本治理：judge 升级前对旧轨迹 replay scoring（`replay_score`），
   `hard_gate_failure_increase` 或 `grounding_drop` 触发则不发布；
5. VLM 随机性：多跑均值 + 记录种子；跨 judge_version 的分数不可比。

## 执行流

```text
标注 Gold Set（四层 + group_key + 双人标注）
  → assign_group_split（固定 seed，可复现）
  → judge 跑 dev → cohens_kappa / 分维 Spearman + bootstrap_ci
  → 达标才允许作为 gate / 排序依据
judge 升级：
  → replay_score(旧轨迹) → degradation_flags 全 false 才发布
  → 发布后重算 IRR；规则或模型升级不得降低事实一致性与硬门通过率
```

## 线上数据回流（P2 收口，仅接口）

`labels.online_outcome` 只承载发布后回流数据，作为后验反馈进入样本；
**不参与样本 tier 判定，不改变前置人工确认流程**；数据稳定（≥ 200 条带
评价样本）后才考虑自动学习或奖励建模。

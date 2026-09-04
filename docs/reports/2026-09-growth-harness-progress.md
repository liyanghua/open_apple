# 2026 年 9 月增长型视频 Harness 进展

> 口径：把“已经能跑”与“已经证明可投放”分开。当前代码已证明一条受约束的视频生产内环；9 月要把它推进到规模化交付、账号流量和付费放大闭环。

## 1. 月度目标

| 目标 | 9 月验收口径 | 当前状态 |
|---|---|---|
| 低成本、高质量规模化生成 | 1 天 10 条；每条有完整 QA、事实门、交付证书，可进入投放 | **部分证明**：batch-002 已完成 5 条候选，13.2 候选/h、$0.2833/批；真实 `template_batch_runner` 和 10 条发布验收尚未完成 |
| 前端账号流量池 | 账号池累计可触达 100–500W 曝光，并能回溯到具体账号、平台和视频版本 | **未接入**：当前发布后数据仍是外部依赖，没有 publication / performance snapshot 生产连接器 |
| 流量 → 内容生成飞轮 | 热点/趋势、账号反馈和视频表现能回流创意库、模板策略和下一批脚本 | **内环已成形，外环未闭合**：已有 research、template、evaluation、repair；缺线上反馈适配、基准和回灌策略 |
| 今日付费放大筛选 | 10 条中筛出 2–3 条进入付费放大；选择有质量门、数据门、预算门和回滚记录 | **有前置能力，未达目标**：当前支持批量质量报告和 1–2 条候选选择，但没有线上效果门，不能把 VLM 高分直接当作放大依据 |

## 2. 当前已经验证的基线

### 生产和质量

- `table-mat-batch-002`：5/5 候选有 1080×1920、30fps、约 15 秒成片和音轨。
- `final_qa` 全部通过；script lock、creative lock、sample 五项人工确认均已通过。
- 活跃耗时 1360.2 秒，吞吐 13.2 候选/h，批次成本 $0.2833。
- L1a 仍为 `revise`，原因是产品 SKU / 价格 / 参数事实覆盖不足；这不是可投放的最终通过。
- 已有内容指纹幂等、键控 lineage、素材动作语义匹配、局部重跑、批量事件、交付证书和评价报告。

### 运营工作台

- 单条审批展示已统一为九阶段材料模型；阶段、产物、审批门和异常状态由同一 view model 驱动。
- 批量工作台已有批次上下文、候选快速查看、批量审批和 revision / hash 重读校验。
- 最近 `tests/backlot` 回归为 **340 passed / 1 skipped**；前端模块语法检查通过。
- 三档宽度的最终人工视觉走查仍是收尾门，不能把“代码完成”写成“运营验收完成”。

## 3. 9 月推进顺序

### A. 先把 10 条/天做成真实生产能力

1. 完成 `template_batch_runner`：批锁、幂等键、断点恢复、失败隔离、成本和吞吐报表。
2. 将素材池从 6 条扩到 12+ 条，覆盖 6 个动作域；新模板先做 H1/H2 可行性判定。
3. 把 43 个模板的逐镜文案和动作映射补齐，至少先完成首批日跑模板。
4. 补 `audio_coverage_report`、转场边界帧检查和 `delivery-version` 目录 / current pointer。
5. 用 `delivery_certificate + L1a pass + sample 人审通过` 定义“可投放”，而不是用 render 成功定义。

**效率护栏**：单片付费不超过 $0.07；40 秒片 full render 单次不超过 20 分钟；失败重试不重复付费；注入故障后能从 checkpoint 恢复。

### B. 建立账号与流量数据入口

最小对象链路：

```text
delivery_version
  → publication(platform, account_id, post_id)
  → performance_snapshot(24h / 7d / 30d)
  → benchmark_record
  → effectiveness_evaluation
```

每条线上数据必须绑定准确的 `delivery_version_id`，并区分自然流量与付费流量。曝光池先以账号、平台、内容类型和可用投放额度建索引，不把“账号数量”误当作“有效曝光”。

### C. 把 10 → 2–3 做成可审计的放大门

候选必须同时满足：

```text
L1a / 技术硬门通过
AND 样片人工确认通过
AND L3 达到校准后的质量阈值
AND 达到最小有效曝光
AND 主指标优于同账号或同 cohort 基线
AND 预算、频控和负反馈护栏通过
```

结果写成 `amplification_decision`，记录入选、未入选原因、观察窗口、预算、实验组和回滚条件。10 条里最终 2–3 条是业务数据判定，不是模型自评判定。

## 4. 混剪系统定义

混剪主链路采用 **retrieve first, minimal generation**：

```text
热点/趋势
  → 创意库匹配
  → 创意方向
  → 产品事实约束下的剧本
  → 分镜与 template slot
  → 分镜-素材检索
  → 口播 / BGM 匹配
  → 商品 / 角色 / 场景一致性检查
  → 只有缺口才生成
  → 渲染、QA、交付和投放
```

当前实现映射：

- 趋势与研究：`research_brief.trending`、`reference_fingerprint`、`research_breakdown`。
- 创意库：`template_pack`、`creative_control_plan`、`hook_plan`、`candidate_variant_plan`。
- 事实与视觉身份：`product_facts.claims`、`product_facts.visual_identity`、`fact_continuity`。
- 剧本和分镜：`script`、`scene_plan`、`template_run_plan`、显式 `template_slot_ref` / `scene_id`。
- 素材检索：`media_index`、`source_media_review`、`reference_source_matrix`、`template_source_match`、语义证据窗口。
- 音频匹配：`tts_selector`、`voice_timeline_fit`、音乐库 / Suno、`sample_payload`。
- 一致性与质量：H1–H4/S1–S2 画面复用规则、语义对齐、字幕安全区、`final_qa`、L1a、L3 和人工五项确认。
- 最小生成：素材缺口才进入 `gap_strategy=generate`；付费前仍受 `production_lock` 和 `paid_generation_approved` 控制。

仍需补齐的领域能力：趋势实时抓取适配器、可排序的统一 retrieval ranker、角色 / 场景连续性合并约束、正式 audio coverage 制品，以及线上表现回流创意库的策略层。

独立架构图：`design-demos/remix-retrieve-first-architecture.html`

## 5. 月末应能回答的四个问题

1. 今天是否真的产出 10 条**可投放**视频，而不是 10 个 render 文件？
2. 哪些账号贡献了有效曝光，曝光对应的是哪个交付版本？
3. 哪条内容的线上表现证明了什么创意机制，下一批要复用哪一条？
4. 10 条中为什么选这 2–3 条付费放大，若效果变差如何停止和回滚？


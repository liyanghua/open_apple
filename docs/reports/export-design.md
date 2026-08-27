# 成片 Top-N 导出脚本设计（export_top_videos）

> 状态：设计定稿（待实现）。评估依据：`docs/EVALUATION_SYSTEM.md`（§13 业务册接入评估）+ `docs/insight_source/AI短视频规范监控_规则量化指标对照_表格.csv`（R01–R24）。
> 产出物示例：`docs/reports/export/top-<N>-videos-<date>.xlsx`。

---

## 1. 目标

给业务方一份**看得懂的成片清单表**：从最近跑片的 TOP N 中，导出「视频名称 / 成片 / 评估维度+分数」，按业务册分三层呈现：

1. **硬性门槛**（合规 + 交付，一票否决类）；
2. **投放前内容质量**（L3 VLM + L1a 技术 + 五确认 + 证书）；
3. **投放后数据反馈**（本期明确不评估，标注「外部依赖」）。

## 2. 输入数据源（全部持久化制品，不临场造数）

| 维度 | 事实来源 | 备注 |
|---|---|---|
| 成片 | `renders/final.mp4` + `delivery_certificate.json`（sha256） | 版本指纹 |
| L1a 硬门 | `artifacts/l1a_final.json` | 11 项检查 |
| 技术 QA | `artifacts/final_qa_full.json` | probe/媒体完整性/字幕校验 |
| L3 VLM 创意分 | `artifacts/l3_advisory.json`（**需落盘**；当前仅在分析目录） | `--score` 子命令：video_judge，pinned rubric=`l3-v1.0`、`frame_count=8`、注入实测响度；`--score-mode single|3seed`（3seed=42/7/2026 均值，正式推荐） |
| 交付状态 | `artifacts/delivery_certificate.json` | 存在性 + gates pass + hash 绑定 |
| 人工接受 | `checkpoint_sample.json`（human_approved）+ `decision_log`（batch_approval） | 本期口径=批量授权 |
| 成本 | `asset_manifest.total_cost_usd`（reuse 记 0 的按实付口径修正并标注） | 仅供参考 |
| 业务规则 | `docs/insight_source/...csv`（source_ref） | 不落 Python 常量（见 §6 策略包） |

## 3. 业务规则三层归位

| 层 | 业务册条目 | 我方证据映射 | 判定语义 |
|---|---|---|---|
| ① 硬性门槛 | R01 内容合规 / R03 违禁词·虚假承诺 | `l1a_sensitive` + `l1a_sku/price/params` | fail→红牌「不合格」；pass→绿牌 |
| | R05 站外联系方式 | L1a 文本来源扩展（正则） | 部分取证；无→「待接入」（§2.5 数据不足≠失败，标黄） |
| | R02/R04 封面合规·大字报·低质搬运 | final_qa 无封面取证 | 统一标「待接入」 |
| | R09/R15 画质(≥720p)·时长(15–60s)·水印·主体占比·亮度 | `final_qa.probe` + `l1a_resolution/duration` + 视觉异常近似 | 分辨率/时长/黑帧=已核验；主体占比/亮度/水印=部分取证 |
| | R18 商品描述一致度 | `l1a_params` + 事实卡 | 已核验（近似实现） |
| ② 投放前内容质量 | R07 前 3 秒 / R08 信息密度 / R12 痛点·实景·基础信息 / R10/R14 五维好内容 | L3 八维为主指标（hook↔R07 近似、rhythm/story↔节奏信息、text_readability↔画面文案、product_presence↔实景演示） | 映射列标注「近似度：强/中/弱」，不做伪精确换算 |
| | 系统层评价 | L3 均分/单维最低 + L1a 全绿 + 证书 + 转场数（edit 非 cut） | 直接展示 |
| ③ 投放后 | R06 账号健康 / R16 播放+完播 / R20–R22 消耗·CTR·转化 / R23/R24 商品入池 | 无本地数据 | 统一「外部依赖/本期不评估」 |

## 4. 打分与排名（composite 定义，脚本头部打版）

```
L3 均分 ≥8.5 → 推荐档；8.1–8.5 → 达标档；<8.1 → 观察档（单维 ≤6.5 给出定向返工建议）
排名键：L3 均分 desc, 单维最低 desc, 有证书优先, L1a 全绿, 转场占比 desc, 成本 asc
```

- `--top N` 取排序后前 N；
- `--runs` 或默认 `--discover`：扫描 `projects/template-run-*` 中 publish completed 的 run，按发布（publish_log 最早 entry）倒序取最近 ≤10 个，再按 §4 排序取 N。

## 5. 工作表结构（最终表头定义）

### ① 总览（Overview）—— 每视频一行

| # | 表头 | 字段键 | 类型 | 来源 |
|---|---|---|---|---|
| 1 | 排名 | rank | int | §4 排序 |
| 2 | 视频名称 | video_name | str | `template_pack.sheet_name` + 模板号（待确认，见 §8） |
| 3 | 模板编号 | template_id | str | run_plan.template_id |
| 4 | 成片 | final_file | str | `renders/final.mp4` |
| 5 | 时长(秒) | duration_s | number | l1a / final_qa probe |
| 6 | 定档 | tier | enum | 推荐/达标/观察 |
| 7 | L3 均分 | l3_avg | 0-10 | l3_advisory |
| 8 | 单维最低 | l3_min | 0-10 | 同上 |
| 9 | 短板维度 | weakest_dimension | str | 最低维名称 |
| 10 | L1a 硬门 | l1a_gate | enum | pass/fail |
| 11 | 合规检查 | compliance | enum | pass/未取证 |
| 12 | 画质·时长门槛 | delivery_gate | enum | pass（≥720p/15–60s） |
| 13 | 交付证书 | certificate | enum | ✅ 绑定/无 |
| 14 | 字幕安全区 | subtitle_bounds | enum | pass/fail |
| 15 | 响度 | loudness | str | `-14.2 LUFS / -4.5 dBTP` |
| 16 | 转场落地 | noncut_transitions | str | `19/21` |
| 17 | 人工确认 | human_approval | enum | 已批准（批量授权口径）/未批准 |
| 18 | 成本 | cost_usd | number | asset_manifest（口径标注） |
| 19 | 单位成本质量 | cost_per_point | number | cost ÷ L3 均分 |
| 20 | 发布时间 | published_at | datetime | publish_log timestamp |

### ② 硬性门槛（Business Gates）—— 行=规则，列=视频（矩阵）

| # | 表头 | 字段键 | 说明 |
|---|---|---|---|
| 1 | 规则ID | rule_id | R01–R24（正式替换 policy ID） |
| 2 | 规则名称 | rule_name | CSV 原文 |
| 3 | 规则类别 | rule_category | 合规检查/内容质量/基础门槛/运营策略/商品入池 |
| 4 | 指标类型 | metric_type | 硬性/可计算/可标注 |
| 5 | 量化指标 | metric | CSV 原文 |
| 6 | 阈值/评分标准 | thresholds | CSV 原文 |
| 7 | 我方证据源 | evidence_source | l1a_sensitive / final_qa.probe / l3_advisory / cert… |
| 8 | 实现状态 | impl_status | 已核验/部分取证/待接入/外部依赖 |
| 9 | 判定语义 | verdict_semantics | 一票否决/计分项/信息展示 |
| 10…N | 视频1…视频N | per_video | `通过（命中0）`/`未取证`/`待接入`/`外部依赖`，绿/黄/灰 |

### ③ 内容质量（Content Quality）—— 行=视频，列=维度

| # | 表头 | 字段键 |
|---|---|---|
| 1 | 排名/视频名称 | rank / video_name |
| 2 | 前3秒钩子 | hook_clarity |
| 3 | 视觉层级 | visual_hierarchy |
| 4 | 节奏 | rhythm |
| 5 | 镜头质量 | shot_quality |
| 6 | 故事连贯 | story_coherence |
| 7 | 音频质量 | audio_quality |
| 8 | 文字可读 | text_readability |
| 9 | 商品露出 | product_presence |
| 10 | L3 均分 | l3_avg |
| 11 | 单维最低/短板 | l3_min / weakest_dimension |
| 12 | 业务近似·前3秒 | biz_hook（R07，近似度标注） |
| 13 | 业务近似·信息密度 | biz_density（R08） |
| 14 | 业务近似·痛点/实景/基础信息 | biz_evidence（R12） |
| 15 | 业务近似·五维好内容 | biz_quality（R10/R14） |
| 16 | 技术摘要 | 黑帧/冻结/响度/字幕边界（可拆列） |
| 17 | 转场数/总镜 | noncut_transitions |
| 18 | 证书/人工确认/成本 | certificate / human_approval / cost_usd |

> 业务近似列脚注「近似度：强/中/弱」，不参与总分。

### ④ 数据口径（Methodology）—— 两列

| # | 表头 | 字段键 | 示例 |
|---|---|---|---|
| 1 | 导出时间 | exported_at | 2026-08-26 20:15 |
| 2 | 评价体系版本 | eval_policy_ref | EVALUATION_SYSTEM.md §13 |
| 3 | judge_version / rubric_version | judge_ver / rubric_ver | technical_validator-0.1.0 / l3-v1.0 |
| 4 | VLM 模型 | model | qwen-vl-max |
| 5 | 评分种子 | seeds | 42 / 42·7·2026 |
| 6 | 抽帧数 | frame_count | 8 |
| 7 | 打分模式 | score_mode | single / 3seed |
| 8 | 运行清单 | runs | 6 个 run 名 |
| 9 | 排序规则 | ranking_rule | §4 描述 |
| 10 | 业务规则包 | policy_version | business-policy.yaml v1（计划） |
| 11 | 已知限制 | caveats | 01/04 无证书 + 探索期链路；五确认=批量授权口径；投放后/账号/商品类外部依赖 |

### ⑤ 原始证据（Evidence）—— 长表，供复核

| # | 表头 | 字段键 |
|---|---|---|
| 1 | 视频名称 | video_name |
| 2 | 证据制品 | artifact（l1a_final/final_qa_full/l3_advisory/delivery_certificate/publish_log） |
| 3 | 检查项 | check_id（l1a_sensitive、l1a_loudness、subtitle_check…） |
| 4 | 状态 | status（pass/fail/skip/未取证/外部依赖） |
| 5 | 实测值 | value（-14.2 LUFS、1080x1920…） |
| 6 | 阈值 | threshold |
| 7 | 消息/说明 | message（含规则关联 ID） |

## 6. 脚本形态（CLI）

```bash
python -m scripts.export_top_videos \
  --top 5 \
  --score-mode 3seed \            # 缺省 single(seed=42)；正式推荐 3seed
  --out docs/reports/export/top-5-videos-2026-08-26.xlsx \
  [--runs run-a run-b ...]        # 缺省自动发现最近发布
```

- **幂等**：`l3_advisory.json` 存在且输入（成片 sha + rubric + model + seed）匹配 → 复用，不重复付费（≈ $0.02 × N × seeds）。
- **fail-closed**：缺 l1a_final/证书 → 行降级并在口径表说明；缺成片 → 剔除并警告，不静默。
- **业务规则包**：实现时按 `docs/EVALUATION_SYSTEM.md` §13.1 建 `docs/rules/business-policy.yaml`（policy_id/version/platform/category/rule_id/metric_definition/evidence_source/thresholds/severity/effective_at/source_ref）；脚本只消费策略包，CSV 仅作 source_ref——规则演进不改代码。

## 7. 边界与诚实性

- 未取证 ≠ 失败（R02/R04/R06/R16–R24 标「待接入/外部依赖」，不参与总分，EVALUATION §2.5）。
- L3 为 advisory：本期导出用于「效果展示」，不进发布硬门（§3.5）；正式后升级 3seed + gold_sample 校准（sheet-01=Gold / sheet-09 hook=Bad）。
- 五确认：本期为批量授权口径；接入 Editorial Gallery 后改为五项真实采集。

## 8. 待确认（实现前）

1. **⑤ 原始证据**：进 xlsx 长表，还是表内只放关键检查 + 附件链接？（xlsx 会随全量 dump 变重，倾向后者）
2. **视频名称**：用 `template_pack.sheet_name`（业务名，如「视频5_AKS桌垫」）还是项目目录名（`template-run-sheet-05-…`）？

---

*设计依据：2026-08-26 工作台/运行分析报告（docs/reports/2026-08-26-analysis-readonly-workbench-run-report.md §7 Goldset 基准选定）*

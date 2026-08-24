# table-mat-batch-002 批量混剪验收记录（2026-08-24）

## 1. 验收对象

- 批次：`table-mat-batch-002`（`diversity_mode=hard_gate`）
- 候选数：5（c1 结果先行 / c2 痛点先行 / c3 证据链先行 / c4 高密度快剪 / c5 产品质感）
- 成片路径：各候选 `renders/final.mp4`
- 批级报告：`artifacts/batch_run_report.json`、`batch_quality_report.json`
- VLM 主模型：`qwen3-vl-plus`（对照 `qwen-vl-max`，见各候选 `artifacts/creative_advisory.*.json`）

## 2. 成片技术验收

| 检查项 | 结果 |
|---|---|
| 成片数量 | 5 候选均有 `final.mp4` |
| 画面规格 | 1080×1920 / 30fps / ≈15.0s（`ffprobe` 复核通过）|
| 音轨 | 均有音轨（口播 doubao seed-tts-2.0 + BGM SUNO，ducking -6dB）|
| 全量 QA | `final_qa` 全部 `pass` |
| L1a | `revise`（coverage 7/11 < 9，SKU/价格/参数缺事实），已 `downgrade_approval` 确认后本地发布 |
| 黑屏/undefined 字幕 | 无（`build_sample_render_payload` 累计时间轴 + word 字幕）|

## 3. 批级门验收

| 门 | 状态 |
|---|---|
| script_lock | 5 候选 `approved`（一键通过）|
| creative_lock | 5 候选 `approved` + `shot_execution_plan=approved` + `paid_generation_approved=true` |
| sample | 5 候选 `approved`（五项效果确认）|

## 4. 效率/质量报告验收

```text
batch_run_report:    data_quality=complete  cycles=5
batch_quality_report: data_quality=complete  quality_candidates=5  vlm=scored(5/5)
```

- 活跃耗时 1360.2s（batch-001 3369.6s），吞吐 13.2 候选/h（batch-001 5.3）。
- 成本 $0.2833（batch-001 $0.2719）。
- 候选差异：`hard_gate` 通过（5 套 `candidate_variant_plan`，各 ≥3 结构镜头差异）。

## 5. VLM 评分（qwen3-vl-plus 主判 + qwen-vl-max 对照）

| 候选 | 方向 | qwen3-vl-plus 均分 | qwen-vl-max 均分 | 差值 |
|---|---|---|---|---|
| c1 | 结果先行 | 8.71 | 7.94 | +0.77 |
| c2 | 痛点先行 | 8.50 | 7.94 | +0.56 |
| c3 | 证据链先行 | 8.91 | 8.31 | +0.60 |
| c4 | 高密度快剪 | 8.66 | 8.44 | +0.22 |
| c5 | 产品质感 | 8.69 | 7.94 | +0.75 |

> 注意：qwen3-vl-plus 单次打分有 ±1 漂移（c3 hook 两次 9.0→7.8）。用于排序前建议跑 2–3 次取均值，或按"两模型差值 ≥2 人工复核"。

## 6. 本轮修复的代码问题（回归关注）

1. `backlot/server.py`：`/media`、`/thumb` 支持 `projects/` 前缀跨项目共享素材，并对**源项目二次 ACL**（`_resolve_served_media` 返回 source_project，route 调 `require_access`）。
2. `backlot/operator_state.py`：源素材预览改用预生成 H.264 代理，**代理不存在时回退 owned source**（`_source_proxy_path` 检查文件存在）。
3. `lib/batch_reporting.py`：`_scoped_eval` 合并样片作用域 VLM（修 `vlm_not_scored`）+ `timing.wall_seconds`（口径分离）。
4. `lib/approval_groups.py` + `backlot/operator_reviews.py`：`approve_bundle` 恢复**纯审批**；creative_lock 副作用（锁执行单 + 授权付费）移到 `lock_execution_after_creative_lock`，由 `decide()` 显式调用并在**同事务**刷新 checkpoint envelope（修信封漂移 + 副作用泄漏）。
5. `backlot/operator_reviews.py` + `backlot/batch_actions.py`：stale review supersede + `review_stale` 落 `rejected`（不再卡 `committing`）。
6. `tools/analysis/video_judge.py`：`VIDEO_JUDGE_MODEL` 环境变量 + `judge_with_average` 多次均值降噪。

## 7. 验收结论

- 回归：通过。全量 `PYTHONPATH=. .venv/bin/pytest -q` → **1898 passed / 11 skipped / 0 failed**（2026-08-24 工作树）。
- 技术成片：通过（5/5，1080×1920 / 30fps / 15s / 音轨）。
- 批级报告：通过（`batch_run_report`=complete、`batch_quality_report`=complete）。
- VLM 质量完整性：通过（5/5 scored）。
- 阻塞项：L1a coverage（产品事实档案 v0.1 已落地，但需真实 SKU/价格/参数填充后才从 `revise` 转 `pass`）。
- 最终结论：**可交付（本地成片 5 条，全量回归 0 failed）；建议人工从 5 条中选 1–2 条作为对外交付。**

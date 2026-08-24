# table-mat-batch-002 批次复盘与固化清单（2026-08-24）

> 上一批复盘：[`Table_Mat_Batch_001_Run_Retrospective_2026-08-23.md`](./Table_Mat_Batch_001_Run_Retrospective_2026-08-23.md)
> 验收记录：[`Table_Mat_Batch_002_Acceptance_Record_2026-08-24.md`](./Table_Mat_Batch_002_Acceptance_Record_2026-08-24.md)

## 0. 交付结论

- 5 候选全量成片（`renders/final.mp4`，1080×1920 / 30fps / 15s / 含音轨），全量 `final_qa` pass。
- 批级门全部通过：`script_lock`、`creative_lock`、`sample` 均人工批准。
- L1a 状态 `revise`（coverage 7/11，SKU/价格/参数缺事实档案）——与 batch-001 一致，已按 publish-director 追加 `downgrade_approval` 确认后本地发布。
- VLM：`qwen3-vl-plus` 全部评分（`complete`），`qwen-vl-max` 结果保留作对照。
- 效率：活跃 1360s（batch-001 3370s），吞吐 13.2 候选/h（batch-001 5.3），成本 $0.2833（batch-001 $0.2719）。

## 1. 本轮验证生效的升级（可固化 / 已固化）

| 项 | 状态 | 证据 |
|---|---|---|
| 候选多样性 hard_gate | ✅ 生效 | 建批自动分配 5 套稳定策略（结果/痛点/证据链/高密度/产品质感）；分叉自动落 `candidate_variant_plan`（≥3 结构镜头差异）；`diversity_mode=hard_gate` |
| 样片 payload 库 | ✅ 生效 | `lib.sample_payload.build_sample_render_payload`（累计时间轴 + `source_in/out` 分离 + word 字幕 + 混音音频）；无黑屏、无 `undefined` 字幕 |
| scoped 制品 | ✅ 生效 | `render_plan.sample/final.json`、`evaluation_report.final.json` 分区，无覆盖 |
| R1 audio_plan → lock | ✅ 生效 | `asset_plan.audio_plan` → `production_lock.locked_values.bgm.provider=suno`（batch-001 当时 `audio_plan=null`、bgm=pixabay）|
| 跨项目媒体服务 | ✅ 已修 | `backlot/server.py::_resolve_served_media` 支持 `projects/` 前缀共享素材；预生成源素材 H.264 代理（`table-mat-mix-v8/assets/video/proxies/`）|
| 报告 VLM 作用域 | ✅ 已修 | `lib/batch_reporting._scoped_eval` 合并样片作用域的 VLM creative_advisory，不再误报 `vlm_not_scored` |
| VLM 评分 | ✅ 生效 | `video_judge`（DashScope `qwen-vl-max`/`qwen3-vl-plus`，l3-v1.0）5 候选全部 `scored=true` |

## 2. 本轮临时发挥（agent 现场拍板，建议评估后吸收）

1. **`gen_stage1..5.py`**：直接从 batch-001 的 `continue_*.py` 复制、改批号 + 手改 `SECTION_IDX`（7 镜头→6 镜头）。未走 `sample-director`/`compose-director`/`publish-director` 的库化服务（batch-001 复盘 P2 仍未完成）。
2. **creative_lock 审批后手动锁**：`approve_bundle` 流程没有把 `shot_execution_plan.status` 从 `draft` 置 `approved`、也没有把 `asset_plan.paid_generation_approved` 置 `true`——本轮由脚本手动补。
3. **candidate_batch 同步**：手动 `record_candidate_result` 三步跳变（planned→in_progress→sampled→evaluated）+ 手写 `output_ref`。
4. **VLM 模型切换**：手动把 `model` 参数改成 `qwen3-vl-plus`，并另存 `creative_advisory.qwen-vl-max.json` 作对照。
5. **审批卡住修复**：bundle 升版后旧 review 未 supersede，导致 `review_stale` 把批动作卡在 `committing`；本轮手动删 stale review + 标记 stuck batch-action 为 rejected。

## 3. 本轮新暴露的系统缺口（#1–#3 已修复，#5 已确认，#4 部分固化）

> **处理状态（2026-08-24）**：
>
> | # | 修复/结论 | 代码 | 测试 |
> |---|---|---|---|
> | 1 | `approve_bundle` 原子锁执行单 + 授权付费 | `lib/approval_groups.py::_lock_execution_after_creative_lock` | `tests/lib/test_checkpoint_approval_groups.py::test_approve_bundle_locks_execution_plan_and_authorizes_paid_generation` |
> | 2 | stale review supersede + `review_stale` 落 `rejected` | `backlot/operator_reviews.py`（ensure_*_review_for_checkpoint）、`backlot/batch_actions.py::_commit_all` | `tests/backlot/test_operator_reviews.py`、`tests/backlot/test_batch_actions.py` |
> | 3 | `VIDEO_JUDGE_MODEL` 环境变量 + `judge_with_average` 多次均值 | `tools/analysis/video_judge.py` | `tests/tools/test_video_judge.py` |
> | 4 | voice-fit 阶梯库化（compose/publish CLI 仍未做） | `lib/voice_timeline_fit.py` | `tests/lib/test_voice_timeline_fit.py` |
> | 5 | 口径澄清 + `wall_seconds` 入报告 | `lib/batch_reporting.py`、`schemas/artifacts/batch_run_report.schema.json` | `tests/lib/test_batch_reporting.py` |

| # | 问题 | 影响 | 结论/建议 |
|---|---|---|---|
| 1 | ✅ 已修复 ~~creative_lock `approve_bundle` 不自动锁执行单/授权付费~~ | 高 | 已落地：`approve_bundle` 同事务内 `shot_execution_plan.status=approved` + `asset_plan.paid_generation_approved=true` |
| 2 | ✅ 已修复 ~~bundle 升版旧 review 不 supersede → 审批卡 committing~~ | 高 | 已落地：`ensure_*_review_for_checkpoint` 校验 subject 版本/hash 不一致即 supersede 重建；`_commit_all` 对 `review_stale` 落 `rejected` 而非卡 `committing` |
| 3 | ✅ 已修复 ~~VLM 模型硬编码 + 单次漂移~~ | 中 | 已落地：`VIDEO_JUDGE_MODEL` 覆盖默认模型；`judge_with_average(runs=N)` 取均值降噪 |
| 4 | 🟡 部分固化 ~~临时脚本未库化~~ | 中 | voice-fit 阶梯已库化（`lib/voice_timeline_fit.py`）；caption_style 派生已库化（`lib/caption_style.py`）。**仍待**：compose-director/publish-director 库 + CLI、expected_facts 产品事实档案 |
| 5 | ✅ 已确认 ~~`active_seconds` 口径待确认~~ | 低 | 结论：`active_seconds=1360s` 是**工具计算时长**（TTS 244s + render 533s + SUNO 412s + VLM 143s + 其余），run event 的 `machine_ms` 有完整发出、无漏计；`human_wait` 因批脚本未发 `approval_wait_ms` 恒为 0。已补 `timing.wall_seconds`（端到端 15219s），口径 = active（计算）/ wall（墙钟）分离 |

## 4. 与 batch-001 的净收益

| 指标 | batch-001 | batch-002 | 说明 |
|---|---|---|---|
| 活跃耗时 | 3370s | **1360s（-60%）** | 无黑屏重渲、无信封漂移重跑、复用研究+代理 |
| 吞吐 | 5.3 候选/h | **13.2 候选/h** | 同上 |
| 成本 | $0.2719 | $0.2833（+4%） | 多跑了双模型 VLM + 全量口播/BGM |
| 候选多样性 | `None` | **`hard_gate`** | 5 套变体计划 + 镜头级差异 |
| VLM | partial（c1 未评） | **complete** | qwen3-vl-plus 全评 + qwen-vl-max 对照 |
| 批级报告 | partial | **complete** | 修 `_scoped_eval` 后 |

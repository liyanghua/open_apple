# table-mat-batch-001 批量混剪验收记录（2026-08-23）

## 1. 验收对象

- 批次：`table-mat-batch-001`
- 候选数：5
- 候选状态：c1/c4/c5=`evaluated`，c2/c3=`selected_for_edit`
- 交付候选：`table-mat-batch-001-c2`、`table-mat-batch-001-c3`
- 成片路径：各候选 `renders/final.mp4`

## 2. 当前事实快照

| 检查项 | 结果 | 证据 |
|---|---|---|
| 成片数量 | 5 个候选均有 `final.mp4` | `projects/table-mat-batch-001-c*/renders/final.mp4` |
| 画面规格 | 1080×1920，30fps，约 15.018s | `ffprobe` 检查五个 final.mp4 |
| 批级报告制品 | 已存在 | `artifacts/batch_run_report.json`、`batch_quality_report.json` |
| 报告重建 | 代码支持幂等重建 | `lib/batch_reporting.py`、`tests/lib/test_batch_reporting.py` |
| 差异矩阵 | 代码支持投影 | `lib/candidate_diversity.py`、`backlot/batch_state.py` |
| 当前 VLM 完整性 | 不通过完整性门 | 最新构建器对未评分候选标记 `partial` |

注意：批次目录中已经存在的报告是较早版本生成的 `complete` 快照。执行下面的 `--dry-run` 可查看最新代码的真实判定；不要把旧报告的 `complete` 直接当作当前质量结论。

本轮 dry-run 实测：`batch_run_report=complete, cycles=5`；`batch_quality_report=partial, quality_candidates=5`。partial 的原因是至少一个候选尚未完成 VLM 创意评分。历史批次无独立 `cost_log` 时，报告回退汇总 provider 事件成本；本批最新汇总为 `$0.2719`，不是 `$0.00`。

## 3. 推荐验收顺序

### A. 运行回归

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/lib/test_candidate_diversity.py \
  tests/lib/test_batch_reporting.py \
  tests/backlot/test_batch_diversity_e2e.py \
  tests/backlot/test_batch_reporting_projection.py \
  tests/backlot/test_batch_workbench.py \
  tests/backlot/test_batch_actions.py \
  tests/lib/test_sample_preflight.py
```

通过标准：所有测试通过；本轮记录为 `51 passed`。

### B. 报告只读验收

```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_batch_reports.py \
  projects/table-mat-batch-001 --dry-run
```

通过标准：只读取 JSON/事件/评价制品，不调用 TTS、音乐、VLM 或渲染；输出候选周期数与 `data_quality`。若任一候选缺事件、成本不一致或 VLM 未运行，必须显示 `partial/degraded` 和 warning。

需要正式刷新历史报告时，才执行：

```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_batch_reports.py \
  projects/table-mat-batch-001 --overwrite
```

刷新后再次执行同命令，语义哈希必须保持不变；不得改变候选 current pointer、审批记录或媒体哈希。

### C. 成片技术验收

```bash
for p in projects/table-mat-batch-001-c*/renders/final.mp4; do
  ffprobe -v error -show_entries \
    stream=width,height,r_frame_rate,duration:format=duration \
    -of compact=p=0:nk=1 "$p"
done
```

通过标准：五个候选均可播放；分辨率 `1080x1920`；帧率 `30/1`；时长约 `15.018s`；存在音轨；无黑屏长段、`undefined` 字幕或全候选相同主体画面。

### D. 工作台验收

打开批页并逐候选展开：

```text
/p/table-mat-batch-001
```

检查：

- 批级 rail 能显示当前阶段和候选状态；
- 候选抽屉可查看样片、质量结论、差异证据和报告新鲜度；
- 报告 `partial/degraded/missing` 时，选择/发布动作明确禁用并给出重建动作；
- 只有通过质量门和差异门的候选进入终稿编辑室；
- 任一候选路径越界、报告损坏或 revision 变化时，页面显示降级/stale，不静默继续。

## 4. 验收结论模板

```text
验收日期：____
执行人：____
批次：table-mat-batch-001
回归：通过 / 不通过
报告重建：通过 / 不通过
技术成片：通过 / 不通过
工作台交互：通过 / 不通过
VLM 质量完整性：通过 / 部分通过（未运行候选：____）
阻塞项：____
最终结论：可进入终稿编辑 / 仅可继续批量修复 / 不可交付
```

## 5. 当前建议

`table-mat-batch-001` 适合作为历史回填和工作台回归样本，不适合作为新多样性硬门的 rollout 样本。下一次应新建五候选 smoke batch，先以 `warning` 跑完整报告和人工复核，确认差异矩阵、VLM 评分和重建报告均稳定后，再提升新批次默认 `diversity_mode=hard_gate`。

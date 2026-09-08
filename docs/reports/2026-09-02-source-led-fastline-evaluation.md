# Source-Led Fastline 迁移评价文档（Task 1-7 验收，2026-09-02）

> **2026-09-06 复审更新：** 四条真实样片暴露出商品事实来源缺失、单帧语义审核不足以及 known alignment fail 仍可被候选审批放行的问题。因此本文的“完成/通过”只保留为 2026-09-02 的测试快照，不再代表当前分支可合并或可交给一线运营。新的合并条件、商品链接浏览器取证和时序对齐升级见 [Cinematic Fast Input Modes and Source-Led Semantic Alignment Implementation Plan](../superpowers/plans/2026-09-03-cinematic-fast-input-modes.md#11-2026-09-06-复审修订商品页取证与时序对齐)。

> 对照物：桌垫表批次（reference-led，已投产）→ 毛巾批次（source-led，无参考视频）。
> 结论先行：**迁移方向正确、主干落地、全量回归转绿**；遗留 3 项（人工确认通道、master 字幕换算、proxy 实现差异）已入后续清单。

## 1. 任务验收

| Task | 内容 | 状态 | 证据 |
|---|---|---|---|
| 1 | 三种 input mode + source semantic index + evidence matrix | ✅ | `tests/contracts/test_cinematic_fast_input_modes.py`、`test_source_evidence_contract.py`、`test_source_semantics.py` |
| 2 | 批次差异化 + Script/Scene 单镜单证据闭环（键控配对） | ✅ | `test_differentiation.py`；script/shot schema 显式 `scene_id`/`section_id` |
| 3 | （与 1/2 合并验收） | ✅ | 同上 |
| 4 | （合并验收） | ✅ | 同上 |
| 5 | canonical sample alignment、五类 hash、五维语义门、stale hash 防绕过、sample/compose/publish gate | ✅ | `lib/template_alignment.py`、`test_template_alignment.py`、`tests/integration/test_source_led_sample_alignment.py` |
| 6 | 毛巾 wrapper 迁 canonical（Research/Batch/Scene/Assets/TTS/Render/Alignment） | ✅ | `tests/integration/test_towel_wrapper_uses_canonical_path.py`（44 passed 集）、4 产品 dry-run 通过 |
| 7 | 架构文档（本目录上文）+ 评价文档 + 最终回归 + 分支收尾 | ✅（本文档） | 见 §2/§3 |

## 2. 回归结果（最终实测）

| 套件 | 结果 |
|---|---|
| `pytest tests/`（全量，含 tools） | **2252 passed, 11 skipped, 1 subtests passed**（2026-09-04 最终实测） |
| 毛巾 `stage50 --dry-run`（4 产品） | 4/4 通过 |
| `py_compile` 毛巾 wrapper + `git diff --check` | 通过 |
| 真实付费渲染/TTS | **未执行**（按约束：等待样片门后的生产授权） |

### 回归过程中的修复（全部测试侧，生产代码零改动）

1. **夹具不完整**（你诊断的）：真实 v8 池仅 4 条素材（缺 防刮/防油易擦拭），而 sheet-01 模板
   及其合成测试覆盖 6 个动作域；新 fail-closed 正确拒绝 generate 缺口伪装 owned。
   → 新增 `tests/lib/_tablemat_pool.py`（完整 6 动作池夹具：真身 symlink + 缺失动作占位 +
   `PRODUCT_VIDEO_DIR`/`_clip_durations` monkeypatch）；三个受影响测试文件加 autouse 夹具。
2. **测试自身状态污染**（复诊发现的第二根因）：`test_capacity_verdict_three_branches` 直接改写
   模块级 `SLOT_ACTION_BY_TEMPLATE["sheet-test"]` 且失败路径不恢复 → 全量跑时顺序污染。
   → try/finally 清理（`pop`）。
3. **工作量不可行**：合成测试把 8 个 2s 槽全挤"防油"单一动作域（单条 8s 素材 H4 容量 ≤3 窗，
   正确拒绝）。→ `_make_run` 槽位改为覆盖 6 个真实动作域（与 sheet-01 一致，保留显式复用语义）；
   2 个 mapper 单测改用均衡 assigned（明确标注：测 mapper 非 matcher）。

**为何此前"单独跑通过、全量挂"**：正是第 2 项污染 + 第 1 项池缺失的组合；修复后单跑/全量一致。

## 2.1 回归期事件记录

在回归过程中发现 `projects/table-mat-mix-v8/inputs/source/video/product/` 曾被意外清空一次
（真实数据，projects/ 已 gitignore）。已从 `.backlot/review-stage/` 完整副本恢复 6 条源文件；
此后多次全量回归未复现。测试夹具已改为纯名称/时长补丁（无磁盘写入），降低再次发生的可能性；
仍在后续排查清单中（建议：为真实 projects/ 目录增加测试写入防护/快照校验）。

## 3. 遗留项（Task 7 记录，非阻塞）

| 项 | 建议处理 |
|---|---|
| 对齐门 partial 人工确认通道 | 规则：`no/error → 硬拦；partial → 写 alignment_review 记录 → sample 门人工批准后放行`（当前实现为"全 yes 硬拦"） |
| master 2160×2880 字幕尺寸/安全区 | 按 profile 等比换算（当前 caption_layout 数值按 1080 宽标定） |
| proxy 实现差异 | stage50 自实现（MediaProxy + 指纹 sidecar，契约满足）；可选收敛到 canonical `prep_template_media` |
| BGM 供应商 | 本机 Suno/Pixabay SSL 不可达 → 复用已授权音轨（decision_log 已记录）；恢复网络后可切回 |

## 4. 产量基线（待生产授权）

- 规格：3:4 竖版 · sample 540×720 / upload 1080×1440 / master 2160×2880 · 30fps
- 素材池：4 产品 × 24-26 条 4K 竖拍（97 条），证据窗标注 97/97（高置信 15-19/产品）
- 成品：16 条（每产品 4 条：测评证明/痛点反转/卖点罗列/场景种草），29.0-29.5s
- 主要成本：TTS（豆包）+ BGM；代理/合成本地
- 批准链：script 门（✅ 已批）→ creative lock（✅ 已批）→ sample 门（生产中，样片已就绪待复议）→ compose/publish

## 5. 变更文件索引（本批分支）

核心：`lib/source_semantics*`、`lib/template_alignment.py`、`lib/template_assets.py`、
`lib/template_render.py`、`lib/media_profiles.py`、`lib/template_mainline.py`、
`scripts/prep_template_media.py`、`scripts/gen_template_audio.py`、
`scripts/render_template_sample.py`、`scripts/finish_template_sample.py`、
`scripts/towel_batch_2026_09_02/*`、`tests/lib/_tablemat_pool.py`、文档（本文档与架构文档）。

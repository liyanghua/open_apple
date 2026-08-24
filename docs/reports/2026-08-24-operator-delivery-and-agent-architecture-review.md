# 一线运营交付与 Code Agent 架构复核

日期：2026-08-24

范围：本轮未提交代码、批量生产/编辑工作室接入、既有五层架构、Code Agent 接入方案。

## 结论

当前代码已经把批量生产从“临时脚本”推进到“有候选分叉、批级审批、报告和运营投影”的阶段，但还不能作为一线运营生产版本发布。

主要原因不是缺少新的 Agent，而是本轮改动仍有生产正确性回归：全量测试为 **1883 passed / 11 skipped / 6 failed**，聚焦回归为 **76 passed / 1 failed**。失败集中在媒体代理和 creative lock 审批后的制品一致性；这两类问题会直接导致运营看到不可播放素材，或审批后无法继续推进到 sample/compose。

上一版五层架构和 Agent Bridge/Broker 方案不需要推翻。当前改动应被吸收为五层的能力增强；仍需新增的是受控 Agent Runtime，而不是第二套视频编排器。

## 代码 Review Findings

### P1. 跨项目媒体 URL 只做 projects-root 校验，没有做源项目授权

位置：`backlot/server.py:591-613`、`backlot/operator_state.py:115-126`

`/media/{project_id}/...` 和 `/thumb/{project_id}/...` 先只校验 URL 中的 `project_id` 读权限；当路径以 `projects/` 开头时，解析器只确认目标仍在全局 `PROJECTS_DIR` 内。因此拥有项目 A 读取权限的用户可以构造 `media/project-a/projects/project-b/...`，读取项目 B 的素材。

修复要求：解析出被引用的源项目并再次执行 ACL，或改为只允许带有明确共享授权/不可猜测 token 的媒体引用。不能把 projects-root containment 当成项目级授权。

### P1. 源素材代理映射硬编码、未检查文件存在，且可能发生同名冲突

位置：`backlot/operator_state.py:238-249`、`backlot/operator_state.py:805-890`

`_SOURCE_PROXY_DIR` 固定为 `projects/table-mat-mix-v8/assets/video/proxies`，任何源文件只要有 stem 就会生成代理 URL，不检查代理是否存在，也没有使用源项目、媒体 ID 或 proxy cache key。不同项目中同名文件还可能映射到同一个代理。

当前直接证据：`tests/backlot/test_operator_state.py::test_projection_includes_safe_material_concept_and_shot_details` 期望原始自有素材 URL，实际得到不存在的 `source-0.proxy.mp4` URL。

修复要求：从 canonical media/proxy artifact 读取代理引用；代理不存在时回退到当前项目内的 owned source；代理引用必须带源项目和稳定媒体身份，不能按 basename 猜路径。

### P1. creative lock 审批后修改 canonical 制品，却没有同步 checkpoint 信封

位置：`lib/approval_groups.py:194-258`

`approve_bundle()` 无条件调用 `_lock_execution_after_creative_lock()`，直接改写 `shot_execution_plan.json` 和 `asset_plan.json`。但已写入 `checkpoint_assets.json` 的 artifact envelope 仍引用修改前的 hash。下一次写入 completed checkpoint 时，`load_artifact_envelope()` 检测到磁盘数据和 checkpoint embedded data 不一致而失败。

全量回归中该问题造成 cinematic-fast 集成、publish gate 等 **5 个失败**。这是审批成功后无法继续生产的阻断回归。

修复要求：审批事务必须从 transaction sink 的 staged view 读取，并在同一事务中同步更新所有受影响 checkpoint envelope；或者把执行锁定作为显式 artifact revision 写入流程，禁止审批 helper 在 checkpoint 外隐式改 canonical 文件。

### P1. 通用 `approve_bundle()` 对所有 approval group 施加 creative-lock 副作用

位置：`lib/approval_groups.py:233-258`

函数没有根据 `bundle["group"]` 判断，脚本锁或其他未来 approval group 也会把执行单标为 approved，并打开 `paid_generation_approved`。这会把“审批脚本”误当成“创意锁/付费授权”，破坏审批边界。

修复要求：仅当 `bundle.group == "creative_lock"` 且 terminal stage 语义匹配时执行锁定和付费授权；其他 group 必须保持纯审批状态转换。

### P1. 验收文档与当前可重复测试结果不一致

位置：`docs/art-plan/Table_Mat_Batch_002_Acceptance_Record_2026-08-24.md:45-65`

文档写明“聚焦回归 78 passed”和“可交付”，但当前工作树全量回归为 1883/11/6，聚焦回归为 76/1。文档还把审批后执行单锁定描述为已修复，但该修复正是当前集成测试失败的来源。

修复要求：验收记录必须绑定可重复命令、提交 revision 和测试快照；在失败未清零前将结论改为 blocked/rework，不得继续作为一线发布依据。

### P2. sample VLM advisory 被无 provenance 合并进 final report

位置：`lib/batch_reporting.py:92-116`

当 final report 没有 advisory 时，代码直接把 sample 或 unscoped report 的 `creative_advisory` 合并进去，没有验证 candidate revision、sample/final scope、rubric version、subject hash 或输出媒体身份。这样 sample 的评分可能在批报告中显示成 final 质量结论。

修复要求：保留 sample/final 两个 advisory；只有在 scope、revision、rubric 和 subject ref/hash 全部匹配时才允许派生展示，否则标为 provenance conflict/degraded。

### P2. `judge_with_average()` 已提供，但没有接入生产编排路径

位置：`tools/analysis/video_judge.py:254-346`

当前搜索到的生产 director/batch runner 仍直接使用单次 `video_judge`；`judge_with_average()` 只被测试/文档引用。因此“VLM 均值已生效”不能作为当前运行时事实，最多是可用 helper。

修复要求：明确接入 sample/batch evaluation，并记录 run_count、seed、model、rubric 和每次结果；或者把验收文档改成“提供均值工具，尚未启用”。

### P2. 批量 wall-clock 指标已写入，但吞吐仍使用阶段 wall time 求和

位置：`lib/batch_reporting.py:204-224、257-269`

`timing.wall_seconds` 是全局首末事件时间差；`throughput.candidates_per_hour` 仍使用各 stage wall time 的总和。两者口径不同，队列时间固定为 0，非法/缺失时间戳也只静默忽略。报告可以作为诊断指标，但不能直接解释为端到端 SLA 或真实批量吞吐。

修复要求：区分 `active_seconds`、`wall_seconds`、`queue_seconds` 和 `candidate_parallelism`；缺失时间戳写入 data-quality warning；吞吐明确采用 wall-clock 还是 active-time。

### P2. voice-fit 库函数与契约不完全一致，且仍未进入正式 stage service

位置：`lib/voice_timeline_fit.py:20-76`、`docs/art-plan/Batch_Production_Recovery_and_Formalization_Plan_2026-08-23.md:17-20`

文档契约包含“改写后仍放不下则 escalate”，实现只返回 `ok/retry/rewrite`，没有 `escalate` 状态；未知 `current_rate` 会从阶梯起点重新返回 0，可能导致无效重试。当前也没有 compose/publish 的正式 service/CLI 调用该库。

修复要求：把“改写后复测”的状态建模为显式 `escalate`，未知档位 fail-closed；在 sample stage service 中接入并将每段决策写入 decision log。

### P2. 产品事实卡无效时静默降级为“未提供事实”

位置：`lib/product_facts.py:23-40`、`tools/analysis/technical_validator.py:227-234`

事实卡 JSON 无效、schema 不匹配或读取失败时返回 `None`，validator 继续把 SKU/价格/参数检查标记为 skip。这会把“用户提供了但系统无法验证”伪装成“用户没有提供”。

修复要求：区分 absent、skipped、invalid 三种状态；invalid 至少进入 `data_quality`/hard gate，并阻止自动 downgrade。

## 本轮已经具备的基础

这些改动没有改变 OpenMontage 的核心事实源，反而补强了既有五层：

| 五层 | 本轮新增或确认的基础 | 当前成熟度 |
|---|---|---|
| Agent Instruction Layer | batch producer、product fact card、voice-fit、VLM 评分规则、Editorial Gallery 交互边界 | 规则已增加；仍由外部 Agent/脚本执行 |
| Capability Layer | VLM model override、candidate variant plan、batch report、媒体代理能力 | 能力可发现性仍需把 proxy/model 作为 canonical capability metadata |
| Production Tool Layer | `judge_with_average`、technical validator 自动读事实卡、样片 payload/音频拟合库 | 单元能力已有，部分未接入真实 stage |
| Persistence/Governance Layer | approval bundle、stale review、批量 report、事实卡 schema、事件时间统计 | 审批事务一致性仍有 P1 回归 |
| Operator Projection Layer | Backlot batch state、审批恢复、source/shot 预览、Editorial Gallery 设计 | 真实 Editorial Gallery API/页面尚未实现；当前仍是规划边界 |

特别要保留的判断：`docs/superpowers/plans/2026-08-24-editorial-gallery-real-data-integration.md` 是实施计划，不是已交付功能。当前代码搜索不到 `/studio/{batch_id}`、`editorial-gallery` 或 `rerun-plan` 的实际路由/DTO。

## 对既有 Code Agent 方案的复评

### 不需要改变的部分

1. 保留五层架构和现有 pipeline；不要为每个 coding Agent 复制一套视频状态机。
2. 保留 `pipeline_defs`、stage director skills、tool registry、BaseTool、artifact/checkpoint、ProjectCommitStore、cost tracker、events 和 Backlot projection 作为唯一事实链路。
3. Coding Agent 只负责理解指令、规划和编排；不直接持有 provider secret、不直接写 canonical artifact、不直接执行任意 shell。
4. 多 Agent 通过同一个 Broker 和事件 schema 接入，Agent 替换不能改变审批、预算、QA 和恢复语义。

### 需要补充或收紧的部分

接入 Agent 后新增的是“运行时边界”，不是生产领域层：

```text
Backlot Studio
  -> Job / Run API
  -> Agent Bridge（session、stream、interrupt、resume）
  -> Agent Broker（ACL、capability、budget、secret、workspace）
  -> 现有 pipeline + tools + ProjectCommitStore
  -> canonical artifacts/checkpoints/events
  -> Backlot projection / delivery version
```

在进入 Agent P1 之前必须先完成：

1. 修复本报告 P1，且全量回归为 0 failure。
2. 完成 Editorial Gallery 真实 DTO/API/同源页面，先只读和只生成 rerun plan。
3. 给单任务和批量任务统一 Job/Run 生命周期，明确 queue、pause、resume、cancel、retry、recovery。
4. 把审批、预算、媒体授权和 provenance 校验收口到 Broker/ProjectCommitStore 可复用的 typed contract。

## Agent 接入顺序

| 顺序 | Agent | 接入方式 | 判断 |
|---|---|---|---|
| P1 | Codex | app-server/SDK Bridge | 默认生产实现，优先验证 session、事件、恢复和受控工具调用 |
| P2 | OpenCode | SDK 或本地 server | 验证多 provider 与开源替换；必须复用同一 Broker |
| P2 | Pi | RPC/SDK | 验证低资源、轻量本地 worker；治理能力需由 Broker 补齐 |
| P3 | Hermes | ACP/受控 gateway | 适合远程、定时和消息入口；持久记忆/远程 terminal 需要更强隔离 |
| P3 | Claude Code | subprocess/官方 SDK | 作为工程质量和交互对照；需单独审核商业授权/数据策略 |
| 实验 | DeepSeek Harness | 独立 adapter | 先做兼容性与插件实验，不进入默认生产后端 |

验收门统一为：同一输入、同一授权、同一 pipeline 下，替换 Agent 后，Backlot 看到相同的 Job/Run 状态、事件、费用、canonical artifacts、失败和恢复结果。

## 发布判断

当前版本：**不发布给一线运营**。

修复并验证后，可按以下顺序灰度：

1. Backlot 单任务：不打开命令行完成 proposal → sample → compose → delivery。
2. 五候选批次：批级审批、候选选择、单候选编辑、最小重跑计划和恢复均可在工作台完成。
3. Codex 受控 sample run：Agent 无 secret、无任意路径/命令，仅经 Broker 调工具和提交。
4. 再接 OpenCode/Pi 做同合同回归；Hermes、Claude Code、DeepSeek Harness 保持实验/对照。

## 验证命令

```bash
PYTHONPATH=. .venv/bin/pytest -q
PYTHONPATH=. .venv/bin/pytest -q \
  tests/lib/test_checkpoint_approval_groups.py \
  tests/lib/test_batch_reporting.py \
  tests/tools/test_video_judge.py \
  tests/backlot/test_batch_actions.py \
tests/backlot/test_operator_state.py \
tests/backlot/test_server.py
```

# 剪映 / 镜头优化 / 成片评估三条链路落位决策与实施方案

> 决策日期：2026-08-22  
> 版本：v1.2（评审修订版，修订记录见文末）  
> 适用范围：OpenMontage `cinematic-fast` 管线（`ecommerce-viral-remix` skill，爆款复刻链路）、`jianying-poc`（剪映自动化）、`shot-generation-optimizer-mvp`（镜头优化器）  
> 背景：参照项目 `projects/table-mat-mix-v7`（透明桌垫 V7 复刻）当前进度——sample 已完成并获批、edit 已完成、compose 产物已出现（`renders/final.mp4`、`renders/master-450.mp4`）。三条新链路均为 capability_extension，不在 v7 生产关键路径上开发（D4 不变）。

## 0. 决策摘要

| # | 决策 | 状态 |
|---|---|---|
| D1 | 剪映链路 = compose 之后的"人工精修出口"，不作为渲染引擎、不进主链路 gate | ✅ 采纳 |
| D2 | shotopt 融入 scene_plan 缺口分析 → assets 生成执行；最小化生成；**生产链路唯一生成执行方 = OpenMontage** | ✅ 采纳 |
| D3 | 质量评估首期 = **L1a 确定性 Gate + VLM advisory**；L2/L1b 门禁为二期；爆款与复刻新片共用一套机制、两套 rubric | ✅ 采纳 |
| D4 | `table-mat-mix-v7` 不受任何基建影响，按现有管线跑完 | ✅ 纪律前提 |

### 修订顺序与门禁（v1.2 新增，执行时必须遵守）

1. **先修 C1/C3 artifact-gate 契约**（§3 的 C1/C2a/C3）——gate 语义不成立则后续都无锚点；
2. **再冻结 D2 字段映射与生成归属**（§2 的映射表 + D2.1）——B4 依赖它；
3. **再补 publish / TimelineIR 契约**（§1 的 A3/A4）；
4. **最后把 B3/C6 统计验收改成可复现评估协议**（§2 的 B3、§3 的 C6）。

每一步有独立验收（见各表），完成前不得进入下一步。

三条基建进入具体生产项目时，须按 Decision Communication Contract 在项目 `decision_log` 补 `category: "capability_extension"` 条目。

---

## 1. D1：剪映链路 = compose 后人工精修出口

### 边界（不可违反）

1. 剪映是 GUI，无 headless 渲染、结果不可复现，**不得替代 Remotion/HyperFrames 渲染引擎**（`render_runtime` 锁定不变）。
2. Pipeline 交付物与 QA 仍以 `renders/final.mp4` + `publish_log` 为准；剪映草稿是"人工精修工作台"。
3. publish 阶段不依赖剪映：`jianying_deploy` 失败只产生告警语义，不阻塞 publish。

### 落点

```text
compose（final.mp4 + SRT + 音乐）
   └─ publish 阶段可选工具：jianying_deploy → 剪映草稿（视频/音频/字幕三轨）
                                          → 人微调/替换素材/导出平台版
```

escape hatch（旁路，非主链路）：edit 阶段不满意时，可把样片 + `assets/video/*-proxy.mp4` 导入剪映人工粗剪找感觉；正式剪接仍在 OpenMontage。

### 实施方案（jianying-poc 仓库）

**A1 工程化重构（第 1 周）**
- 把 `jianying_draft_exporter.py` 拆为包 `jy/`：`draft.py`（草稿装配）、`registry.py`（virtual_store/key_value）、`srt.py`、`probe.py`、`deploy.py`、`cli.py`；
- `drafts-v5/` 冻结为回归 fixture；pytest 覆盖 SRT 解析、时间轴装配、注册表生成；
- 基线不变：输入仍是 `videos + srt` 时间线 JSON。

**A2 轨道能力 + 部署安全（第 1-2 周）**
- 新增音频轨（BGM + 旁白）、多套字幕样式（`verified_templates.json` 扩展 `_style1.._style3`）；
- 部署安全：检测剪映进程（运行中拒绝部署并提示 ⌘Q）、同名草稿时间戳备份、部署前后 diff 报告。

**A3 读回 + 指令式剪辑（第 2-3 周）——分级 round-trip 保证（v1.2 修正）**
- 定义 `TimelineIR` JSON schema（归一化时间线：tracks/segments/clips/texts/audio）；
- 读回解析器（draft→TimelineIR）分级保证：
  - **支持字段**：语义 round-trip（读回→写出语义等价）；
  - **未知字段**：保留 raw subtree（读回时整棵存下、写出时原样回写），不做语义解释；
  - **不支持的剪映特性**（特效/关键帧/滤镜等首期不覆盖项）：显式输出 `loss_report`（列出丢失字段、位置、影响范围）；
- raw subtree 必须经过回写策略分类：`roundtrip_safe` 可原样回写；`record_only` 只留档不回写；绝对路径、设备标识、账户/平台指纹归入 `sanitize_required`，先清洗或重建，禁止跨机器透传；
- 指令子命令：`jy import / cut / trim / split / remove-silence / subtitle / music / speed / template`，每条 = 一个 TimelineIR 纯变换；
- `SKILL.md`：coding agent 自然语言 → `jy` 命令序列的语法、组合示例、安全规则。

**A4 OpenMontage 接入与 publish 契约（第 4 周）——v1.2 修正**
- 新工具 `tools/publishers/jianying_deploy.py`（`BaseTool`，`capability = "publish"`）；
- **schema 变更**：`publish_log.schema.json` 的 entry 增加可选 `metadata`（type object，additionalProperties true），provenance 放 `entries[].metadata`：`source_render / deployed_at / draft_name`；不新增顶层结构化字段；
- 语义定义：部署成功 → `{platform: "jianying", status: "exported", export_path: <草稿目录>, metadata: {...}}`；部署失败但本地导出成功 → `{platform: "jianying", status: "failed", error: ..., metadata: {...}}`——publish_log 无全局状态，逐 entry 语义天然支持"本地包成功、剪映失败仅告警"；
- `pipeline_defs/cinematic-fast.yaml` publish 阶段：`required_tools: [export_bundle]`，`optional_tools: [jianying_deploy]`，`tools_available: [export_bundle, jianying_deploy]`；剪映工具**不**进 required_tools。
- publish director 必须先完成 `export_bundle`，再尝试 `jianying_deploy`；后者返回失败或抛异常时捕获为 warning，并追加 `platform: "jianying", status: "failed"` entry，不能把 publish stage 整体置为 failed。

### 验收方案（A 线）

| 任务 | 验收标准 |
|---|---|
| A1 | `pytest -q` 全绿；`jy import timeline_demo.json -o out --deploy <dir>` 与旧脚本产物 diff 仅含 id/时间戳差异；剪映专业版 11.2 打开成功 |
| A2 | 含音频轨 + 多字幕样式的草稿在剪映中可见可播放；剪映运行时部署被拒绝；同名草稿自动备份可恢复 |
| A3 | 支持字段子集 round-trip 语义等价（测试集断言）；未知字段原样保留；loss_report 完整列出未支持特性；**验收标准不含"无损"表述**；10 条自然语言指令 → 命令序列映射测试全对；remove-silence 与人工听感一致 |
| A4 | 对 `table-mat-mix-v7/renders/final.mp4` 跑 `export_bundle + jianying_deploy` 产出可打开草稿；publish_log 含本地 `exported` entry 与剪映 entry，metadata 三字段且 schema-valid；剪映缺失时 publish checkpoint 仍 completed（剪映 entry=failed + warning）；registry `provider_menu` 可见两个工具 |

---

## 2. D2：shotopt 融入 scene_plan 缺口分析 → assets 生成执行

### 状态模型（v1.2 修正：与现有 schema 枚举严格一致）

直接使用 `shot_execution_plan.schema.json` 现有枚举，**不扩 schema、不造新枚举**：

```text
coverage_status: enough | gap
gap_class:       none | expressive | evidential
gap_strategy:    none | real_capture | rephrase | remove | generate
```

| 组合 | 含义 | 动作 |
|---|---|---|
| `enough` | 自有素材可覆盖（v7 现状 7/7） | 不生成，直接用 source_selection in/out |
| `gap` + `real_capture` | 需实拍补拍 | 人工补拍，不进 shotopt |
| `gap` + `rephrase` | 素材够但文案/镜头语言不贴 | 改 shot 描述重剪，不进 shotopt |
| `gap` + `remove` | 镜头删掉更好 | 删除，不进 shotopt |
| `gap` + `generate` | 素材确实缺 | **编译 ShotSpec → shotopt → 生成** |

### ShotSpec 编译映射表（v1.2 新增：逐字段冻结）

`shotopt/models.py` 的 ShotSpec 字段为 `subject/action/endpoint/scene/camera/...`，与 shot schema 无同名字段，须经编译函数 `compile_shotspec(shot, project_ctx)` 转换（实现在 shotopt `shotopt/mapper.py` + `sgo compile-shotspec` 命令）：

| shot_execution_plan shot 字段 | ShotSpec 字段 | 编译规则 |
|---|---|---|
| `id` | `shot_id` | 直填 |
| `subject_action` | `subject` / `action` / `endpoint` | subject=动作主体；action=动作短语；endpoint 必须由 `project_ctx.shot_overrides[shot_id].endpoint` 明确传入（由 scene-director 或人工确认生成）；缺失时 `compile_shotspec` 失败并返回可修复诊断，**禁止填充占位事实** |
| `purpose` | `business_goal` | 直填 |
| `camera` | `camera` | 直填 |
| `setting` | `scene` | 直填 |
| `lighting` | `lighting` | 直填 |
| `sound` | `audio` | 直填 |
| `duration_seconds` | `duration_s` | 直填 |
| `framing` | `notes` + `aspect_ratio` | "9:16/横屏"从 framing 提取，其余入 notes |
| `screen_copy` / `narration` | `notes` | 直填 |
| `evidence_type` | `notes` | 直填（如 "real_proof"） |
| `reference_mechanisms` / `industry_notes` / `control_rule_refs` | `notes` / `forbid` | 机制要点入 notes；与参考片相关的禁项转 forbid（模板编译时） |
| （项目上下文） | `product_category` / `product_id` / `mode` / `identity_risk` / `references` | 由项目上下文 + 素材注册表填；商品镜头 `identity_risk` 默认 `high`；有参考图时 `mode=I2V` |
| `gap_class` / `gap_strategy` | （不映射） | 仅用于判定是否走 shotopt；只有 `gap+generate` 才编译 |

**冻结要求**：该映射表是 B4 的前置契约；`sgo compile-shotspec` 用 `table-mat-mix-v7/artifacts/shot_execution_plan.json` 的真实 shot JSON 做单元测试。

### 生成职责归属（v1.2 新增：D2.1 唯一入口）

**决策：跨仓集成中，OpenMontage 是唯一生成执行方。** shotopt 侧 `VideoProvider`/`--auto-generate` 保留但明确标记为 **shotopt 独立开发/实验模式**（README 与代码注释标注"跨仓集成禁用"），理由：OpenMontage 有 Rule Zero（生成必须走 registry 工具）、`cost_tracker` 预算治理、decision_log 审计与 checkpoint 门禁；两个生成入口会产生两套 job id、两套成本记录和重复扣费风险。

跨仓回流采用两层契约：OpenMontage `run_event` 是 `run_id / status / machine_ms / cost_reservation_id` 的唯一来源；OpenMontage generation task/`ToolResult` 是 `provider / model / output_uri / cost_usd` 的唯一来源，`latency_ms` 由 `machine_ms` 映射并在回流时明确记录。`sgo record` 接收版本化 `GenerationResult` envelope，要求携带 `source_run_id`，并以 `(source_run_id, provider)` 做幂等校验，重复提交拒绝，防重复扣费。

### 批准后回填规则（v1.2 修正：复用现有 adopt 语义）

**计划字段与运行结果字段分离**：
- `shot_execution_plan` 是批准后只读的计划工件；`generation_proposals` 在 scene_plan/assets 计划期写入；
- `selected_generation_task_id` 是运行态回填字段，**复用 `backlot/shot_generation.py` 现有 `adopt()` 语义**（已实现）：事务内更新 `selected_generation_task_id` + `asset_manifest`（`generated-{task_id}` asset）+ audit 事件 + 重算 hash + plan_hash 一致性校验（计划已批准且 hash 未变才可 adopt）；
- retry：失败任务保留原 task（status=failed + error），新尝试创建新 task_id，全部留审计；
- 若生成需求超出原批准范围（shot 语义变化），必须新建 revision 走重审批，不套 adopt；
- `production_lock` / `approval_bundle` 在 adopt 范围内不重签（素材替换不改变创意锁定）；超出范围变更按上述 revision 规则处理。

### 实施方案（shot-generation-optimizer-mvp 仓库）

**B1 P1 收尾核实（第 1 周）**
- 按 `docs/AI_CODING_TASKS.md` P1 验收清单逐条核实（xlsx 导入、wrap-template、重复校验、迁移报告），补齐缺口即关闭。

**B2 GenerationRequest + 回流契约（第 2-3 周，v1.2 重定义）**
- 定义 provider 无关的 `GenerationRequest` JSON（prompt/mode/duration/aspect_ratio/reference_roles/幂等键）；
- `sgo prepare-generation` 输出 GenerationRequest（已有雏形）；`sgo record` 接收 `source_run_id/provider/model/status/cost_usd/latency_ms/output_uri` 的版本化 GenerationResult envelope + 幂等校验；
- shotopt 侧 `VideoProvider` 接口保留为独立实验模式；**跨仓集成禁用 `--auto-generate`**。

**B3 Video Judge（第 3-5 周）**
- `shotopt/vjudge.py`：抽帧（均匀 + 关键帧，帧数可配置）→ VLM 评分（先 VideoScore2 单实现，可插拔）→ 六维分数 + `failure_tags` + `judge_version`/`rubric_version`；
- 同步提供 `sgo judge --json` CLI，输入/输出遵循 §4 的 `judge_result` schema；没有该 CLI 和 schema contract，OpenMontage `video_judge` 不得接入；
- 同一输入的重复运行必须在预设分数容差内，并记录 model/config/seed；不把外部 VLM 的精确 bitwise 一致当作前置条件；VLM 随机性用多跑均值和离散度报告，C6 再评估分布稳定性；
- `failure_tags` 喂现有 minimal-diff retry。

**B4 半自动桥（与 B2/B3 并行，第 2-4 周）**
- 实现 `shotopt/mapper.py` + `sgo compile-shotspec`（映射表见上，v7 真实 JSON 单测）；
- OpenMontage scene-director skill 增加 gap 判定判据（enough/gap 四策略判据表）；
- 半自动流程：scene_plan 标 `gap+generate` → `sgo compile-shotspec` + `sgo optimize` 出 Top-1 → OpenMontage `video_selector` 生成 → adopt → `sgo record` 回流。

**B5 学习闭环（第 6-8 周）**
- P4：模板级统计（FPAR / attempts / cost / failure-tag 分布）→ 晋升；P5：廉价预筛（规则 + 检索先行，再做小模型 predictor）。

### 验收方案（B 线）

| 任务 | 验收标准 |
|---|---|
| B1 | P1 清单逐条勾掉或补差；`pytest -q` + `scripts/run_demo.sh` 全绿 |
| B2 | GenerationRequest 幂等键单测（同 `source_run_id + provider` 重复 record 被拒）；mock provider 下 record 落库含 cost/latency，字段分别可追溯到 run_event 与 generation task/ToolResult |
| B3 | **接口/回归 smoke**：六维分数 + reasoning + failure_tags 结构完整；judge_version 落库；同输入重复运行分数差异在预设容差内且 model/config/seed 完整记录；failure_tags 触发正确 retry 分支；10 条人工样本仅做方向性目测（不作显著性结论）。**真正 gate 校准移到 C6**（见 §3 C6 协议） |
| B4 | v7 真实 shot JSON 经 `sgo compile-shotspec` 产出 ShotSpec 且字段符合映射表（单测断言）；半自动全流程走通（生成环节 mock） |
| B5 | 模板报告输出四项统计；晋升/降级规则在 held-out 数据上可复现 |

---

## 3. D3：质量评估——首期 L1a Gate + VLM advisory（v1.2 收窄范围）

**首期承诺（本期可验收）**：L1a 确定性 Gate（致命拦截 + `block` 路径）+ VLM judge 的 advisory 报告（不参与 pass/fail）。
**二期（本期不宣称门禁，仅列前置条件）**：L2 Grounding / 复刻机制符合度 / L1b 原创度。前置条件：ProductFact/Evidence 证据链数据源（素材授权 registry、商品事实库）就绪后，才定义其输入/输出/阈值/失败路径。

| 对象 | 阶段 | rubric | 强度 |
|---|---|---|---|
| 爆款（参考片） | research | L3/L4 维度对齐 GrowthBench 命名，产出"质量分 + 机制拆解"；复刻机制不复刻像素（`originality_boundary` 已锁） | 研究向 |
| 复刻新片 | compose | 首期：L1a 确定性 gate + VLM advisory；二期：L2/L1b | 门禁向（首期仅 L1a 强制） |

### 实施方案（OpenMontage-main 仓库）

**C1 契约落地（第 1 周，v1.2 重写为完整 artifact-gate 契约）**
- 新 schema `schemas/artifacts/evaluation_report.schema.json`：业务字段包括 `judge_version / rubric_version / dimensions[] / claims[] / findings[] / failure_tags[] / evidence[] / pass / overall_severity(fatal|warning|info) / thresholds / advisory_status`；每个 `findings[]` 项也必须带 `severity`，gate 以“是否存在 fatal finding”为唯一判定，`overall_severity` 只是其确定性聚合；同时遵循 fastline canonical artifact envelope，明确 required `version / project_id / created_at / producer / input_hashes / semantic_sha256 / artifact_sha256`；当 optional `video_judge` 未配置时，`judge_version/rubric_version` 可为 null，并必须带 `advisory_status: "skipped"` 与原因，不能宣称 judge_version 一致性；
- 在 `schemas/artifacts/__init__.py` 的 `ARTIFACT_NAMES` 注册 `evaluation_report`（checkpoint 校验与 Backlot 可见）；
- **schema 变更**：`final_review.schema.json` 增加可选 `evaluation_report_ref`（`{name, path, semantic_sha256, artifact_sha256}`，不新增 required，保持向后兼容；字段形状与 `approval_bundle.artifact_refs` 一致）；
- 契约表（冻结）：
  - `technical_validator`（required）→ 产出 evaluation_report；
  - `video_judge`（optional，advisory）→ 分数写入 evaluation_report.dimensions/reasoning；
  - gate 映射：evaluation_report `pass=false` 且含 `severity: fatal` → `final_review.status = "fail"` + `recommended_action = "block"`；仅 warning → `revise`；不得使用未被 `final_review.schema.json` 声明的 action 值；
  - checkpoint 语义：compose 阶段 fatal → checkpoint `status=failed`，`next_action` 写明修复 verb + context_refs（stage 复跑入口）；`review_focus` 仍是提示、不是 gate（gate 来自 required_tools + director 的上述映射）。

**C2 共享检查 API + technical_validator（第 1-2 周，v1.2 修正）**
- **先抽共享层**：新 `lib/qa_checks.py`——probe/decode/black/freeze/safe_zone/loudness/duration/audio_presence 纯函数（从 `final_qa.execute()` 抽出）；`final_qa` 改为调用共享层（行为不变）；
- 新工具 `tools/analysis/technical_validator.py`（`capability = "analysis"`）：复用共享层 + 新增 SKU/价格 OCR 对照（引擎可插拔，起步本地）、字幕越界、时长越界、音量异常、音画缺失；输出 evaluation_report 格式；
- 责任边界（冻结）：`final_qa` = 渲染技术健康（通用、保持现状语义）；`technical_validator` = 电商 L1a 门禁（产出 evaluation_report）；共享层单测 + 两工具各自注入测试矩阵。

**C3 compose gate 接入（第 2 周，v1.2 修正）**
- `pipeline_defs/cinematic-fast.yaml` compose 阶段：`produces` 增加 `evaluation_report`；`required_tools` 增加 `technical_validator`（保留 `video_compose, final_qa`）；`optional_tools: [video_judge]`；`tools_available` 明确为 `[video_compose, final_qa, technical_validator, video_judge]`；`review_focus` 增加 L1a 项（提示，非 gate）；
- compose-director skill 更新：按 C1 契约表执行 gate 映射与 checkpoint 失败/复跑语义；
- sample 的 quick QA 保持轻量不变。

**C4 video_judge 薄封装（第 3-4 周）**
- 新工具 `tools/analysis/video_judge.py`：调用 shotopt vjudge（`sgo judge` 子进程，JSON 进出；B3 完成前不得接入 compose）；judge 路由 registry（deterministic → VLM → specialist，对应调研文档 §5）；输出进 evaluation_report（advisory）。

**C5 复刻 rubric 落地（第 4-5 周）**
- research-scorecard 对齐 L3/L4 维度命名；复刻门禁 rubric（机制复刻度、原创度）写入 `ecommerce-viral-remix` skill，标注二期状态。

**C6 Gold Set + 版本治理 + 评估协议（第 5 周起，v1.2 重写统计协议）**
- 分层标注：Gold/Silver/Bad/Hard Negative；
- **gate 校准协议（冻结）**：
  - 样本量：每维度 n ≥ 100 起步（按 bootstrap CI 宽度决定最终量）；
  - 标注协议：双人独立标注 + 仲裁；IRR 用 Cohen's kappa（起步参考 ≥ 0.6，上线前校准）；
  - 切分：按 SKU/category/creative-pattern/time Group Split（对齐设计文档 §26），防同模板泄漏；
  - 报告：六维**分别**报告 Spearman/Kendall + bootstrap 95% CI，不做单一聚合数字；Critical FAR/FRR 单独报告；
  - 版本治理：judge 升级前对旧轨迹 replay scoring，分布变化超阈值不发布（设计文档 §19.1）；
  - VLM 随机性：多跑均值 + 记录种子。

### 验收方案（C 线）

| 任务 | 验收标准 |
|---|---|
| C1 | `evaluation_report` 注册后 checkpoint 校验可用；final_review 含 `evaluation_report_ref` 的样例 schema-valid；契约表逐条有对应单测 |
| C2 | 共享层单测全绿且 `final_qa` 行为不变（旧样例回归）；注入测试集全检出（黑帧/字幕越界/SKU 错配/超时长/音画缺失）；对 v7 `renders/final.mp4` 跑出报告 |
| C3 | 模拟一次 compose：fatal → final_review.status=fail + checkpoint failed + 复跑入口可用；warning → revise；video_judge 缺失不影响 compose（optional） |
| C4 | 对 v7 final.mp4 输出六维 advisory 报告；路由单测通过；judge_version 与 shotopt 一致 |
| C5 | v7 research_scorecard 补跑一版 GrowthBench 维度报告；复刻保真度字段出现在 evaluation_report（标注 advisory） |
| C6 | 协议条款全部可执行：分组切分脚本、IRR 计算、bootstrap CI、replay scoring 回放均可复现；**不满足协议样本量时结论自动降级为方向性** |

---

## 4. 跨仓契约（防止漂移）

1. **依赖方向**：OpenMontage → shotopt（子进程/薄封装）；shotopt 不依赖 OpenMontage。
2. **单实现原则**：VLM judge 核心只在 shotopt（`shotopt/vjudge.py`）；L1a 确定性校验只在 OpenMontage（`technical_validator`）；`final_qa` 共享层在 OpenMontage `lib/qa_checks.py`。
3. **生成唯一入口**（D2.1）：跨仓集成中生成只经 OpenMontage `video_selector`；`run_id/status/machine_ms/cost_reservation_id` 来自 run_event，`provider/model/output_uri/cost_usd` 来自 generation task/ToolResult；`sgo record` 只做版本化回流 + 幂等校验。
4. **契约文件**：shotopt `docs/` 定义 `judge_result` / `ShotSpec` / `GenerationRequest` JSON schema（含版本号），OpenMontage 保存引用副本；变更双仓 bump + 契约测试。
5. **产物路径**：遵守 OpenMontage `projects/<project-id>/` 路径纪律。
6. **license 边界**：shotopt 不拷 AGPL Prompt Optimizer 代码进 MIT core（不变）。

---

## 5. 编排与里程碑（8 周，v1.2 按修订顺序调整）

```text
周     修订顺序1:契约(C)      修订顺序2:映射(D2)      修订顺序3:剪映(A)       修订顺序4:统计(B3/C6)
1-2    C1 schema+注册         B1 P1收尾              A1 工程化              （B3 只做接口 smoke）
       C2a 共享层抽取         D2.1 生成归属冻结        A2 音频轨+部署安全
3-4    C2b technical_validator B2 回流契约           A3 读回+指令层
       C3 compose gate         B4 mapper+半自动桥     A4 publish 契约
5-6    C4 video_judge(advisory) B3 vjudge 接口         A 稳定化/回归
7-8    C5 rubric / C6 协议启动  B5 学习闭环            A 观察                 C6 校准协议执行
```

依赖：A 线独立；B3 依赖 B2；C4 依赖 B3；C2/C3 独立。**第 1-2 周四仓并行**是最大并行窗口。

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 剪映版本迁移（11.2 已验证） | golden fixture + 每次升级回归；读回解析器分级保证 + loss_report |
| Judge 成本挤占 cost_per_accepted_shot | 抽帧预算参数；静态/确定性检查先过滤；advisory 期可降频 |
| Seedance API 权限 | B2 回流契约先行；无 key 走人工生成 + record 回流，B3/B4 不受阻 |
| 跨仓契约漂移 | schema 版本号 + 双仓契约测试（§4） |
| v7 生产被基建干扰 | D4 纪律：基建不进关键路径；生产项目内缺能力记 capability_extension |
| L2/L1b 门禁被误解为已实现 | 计划层面已收窄为"L1a gate + VLM advisory"；二期以证据链数据源就绪为前置 |

## 7. 总验收（端到端 demo，v1.2 收窄判据）

场景：一个新桌垫类复刻项目存在 1 个 `gap+generate` 镜头。

```text
scene_plan 标 gap+generate → sgo compile-shotspec（映射表校验）→ sgo optimize 出 Top-1
→ OpenMontage video_selector 生成（唯一生成入口，run_id 幂等）
→ sgo record 回流（cost/latency 落库）→ vjudge 打分（advisory）
→ adopt（现有事务语义回填 selected_generation_task_id + asset_manifest）
→ compose 全片 → final_qa + technical_validator（evaluation_report）
→ publish 本地包 + jianying_deploy 剪映草稿（publish_log entry 含 metadata）
→ 人工剪映精修导出
```

**首期判据**：全链路产物 schema-valid；生成入口唯一（`source_run_id + provider` 幂等校验生效）；当 video_judge 启用时 judge_version 全程一致，未启用时按 `advisory_status=skipped` 记录；`sgo metrics` 三 KPI 可算；**致命 L1a 缺陷被拦截并走 `block` 路径**；VLM 分数仅 advisory 不影响 gate；剪映草稿可打开；剪映部署失败不阻塞 publish。

---

## 修订记录

- **v1.0（2026-08-22）**：初稿。记录 D1-D4 决策与三线实施方案。
- **v1.1（2026-08-22，评审修订）**：
  - P0：C1 重写为完整 artifact-gate 契约（evaluation_report 注册进 `ARTIFACT_NAMES`、final_review 增可选 `evaluation_report_ref`、compose `produces/required_tools` 变更、fatal→fail/Reject 映射、checkpoint 失败与复跑语义）；明确 `review_focus` 不是 gate；
  - P1：D2 状态模型改用现有枚举（`enough|gap` × `none|real_capture|rephrase|remove|generate`），删除 `partial/missing/reuse/hybrid`；新增逐字段 ShotSpec 编译映射表并冻结；D2.1 明确生成唯一入口 = OpenMontage（shotopt `--auto-generate` 降级为独立实验模式）；回填规则复用 `backlot/shot_generation.py adopt()` 语义（计划/运行字段分离、audit、hash 不变量）；
  - P1：A4 publish 契约落地（publish_log entry 增可选 `metadata`、jianying 失败语义、publish 加 `optional_tools`）；D3 范围收窄为"L1a gate + VLM advisory"，L2/L1b 转二期并列前置条件；
  - P1：C2 增加共享层 `lib/qa_checks.py` 抽取步骤与责任边界；B3 验收改为接口/回归 smoke，gate 校准移入 C6 完整统计协议（n≥100、双人标注、Group Split、分维 bootstrap CI、replay scoring、随机性多跑）；
  - P2：A3 改为分级 round-trip 保证（支持字段语义等价 / 未知字段 raw 保留 / 不支持特性 loss_report），删除"信息无损"表述；
  - 背景更新：v7 已过 sample（completed+approved）、edit 完成；新增“修订顺序与门禁”小节。
- **v1.2（2026-08-22，二次评审修订）**：
  - 修正 `recommended_action` 使用现有 schema 枚举 `block`，并要求 C1/C3 的 artifact、tool 清单与 stage contract 完整一致；
  - publish 明确 `export_bundle` 为 required、`jianying_deploy` 为 optional，并规定剪映失败只形成 failed entry + warning，不使 publish stage 失败；
  - `evaluation_report` 补充 canonical artifact envelope 与引用 hash 要求；跨仓回流拆分 run_event 与 generation task/ToolResult 的字段来源；
  - ShotSpec endpoint 缺失改为编译失败，不再填充占位事实；TimelineIR raw subtree 增加安全回写分类；VLM 验收改为容差稳定性而非 bitwise 一致；
  - 增加 `sgo judge --json` 与 `judge_result` schema 作为 OpenMontage video_judge 接入前置契约。

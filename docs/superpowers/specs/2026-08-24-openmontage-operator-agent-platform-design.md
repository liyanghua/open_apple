# OpenMontage 一线运营工作台与多 Agent 平台升级设计

**状态：** 提案基线，待拆解为 implementation plan

**日期：** 2026-08-24

**适用范围：** 单任务生产、批量生产、Backlot/编辑工作室、Agent Bridge、Agent Broker、运营 Skill

**部署默认：** 本机或内网单团队受控部署

**默认 Agent：** Codex；其他 Agent 通过可插拔适配器接入

---

## 1. 摘要

OpenMontage 已经具备 instruction-driven video production 的核心能力：pipeline manifest、stage director skill、tool registry、canonical artifact、checkpoint、成本跟踪、质量门和 Backlot 投影。当前需要解决的不是再写一套视频生成编排器，而是把现有能力包装成一线运营可以稳定使用的生产产品，并让多个 coding Agent 在同一套安全合同下工作。

本设计确定以下架构：

```text
一线运营
  -> Backlot 编辑工作室
  -> Operator API / Job Queue
  -> Agent Bridge
  -> Agent Broker
  -> OpenMontage pipeline + tool registry + checkpoint + QA
  -> delivery version
```

Agent 是推理和编排能力的提供者，但不是项目文件和 provider secret 的所有者。Backlot 是运营入口，Agent Bridge 是会话适配层，Agent Broker 是唯一的工具、写入、预算和权限边界。

首期不做多 Agent 协同编排。产品采用“一个默认 Agent + 可插拔适配器”：Codex 先作为生产默认实现，OpenCode 和 Pi 作为第二梯队，Hermes、Claude Code、DeepSeek Harness 先进入实验/对照范围。

## 2. 当前状态与判断

### 2.1 已具备的基础

- `pipeline_defs/` 已覆盖 animated explainer、cinematic-fast、clip factory、localization 等多类生产流程。
- `skills/pipelines/` 和 `skills/meta/` 已定义 stage director、reviewer、checkpoint、batch producer 等编排合同。
- `tools/tool_registry.py` 提供运行时能力发现、provider menu、selector 和 fallback 信息。
- `lib/checkpoint.py`、artifact schemas、decision log、cost tracker 和 run events 已形成生产事实源。
- Backlot 已具备中文 operator projection、认证/ACL、typed draft、impact preview、revision、review、batch state 和审计相关代码与契约。
- 批量生产已经具备 candidate project、候选聚合状态、批量事件和 batch report 的基础。
- Editorial Gallery 与成片审核台已经有独立设计，能够承载候选比较、时间线审核、版本切换和受约束修改。

### 2.2 仍未形成产品闭环的部分

- 单任务和批量任务尚未统一为运营可理解的 job/run 生命周期。
- Editorial Gallery 的真实数据接入和生产入口仍有契约 review 阻塞；当前部分能力仍是 fixture 或只读规划。
- 成片审核台、批量工作台、候选项目页之间缺少统一的创建、排队、暂停、恢复和交付动作模型。
- Agent Bridge / Agent Broker 尚未成为正式执行运行时，现有文档中的 Codex 适配仍属于规划边界。
- 一线运营所需的运行授权、成本确认、并发上限、取消、失败恢复和 secret 隔离还需要统一收口。
- 目前的 Agent 使用方式依赖外部 coding assistant 读取仓库和执行命令，适合研发人员，不适合直接交给一线运营。

### 2.3 产品判断

不应让每个 Agent 直接读取 `projects/`、直接写 artifact 或直接调用 provider。这样会造成：

1. 每个 Agent 都需要一套不同的权限和恢复逻辑；
2. provider key、费用和输出路径无法集中治理；
3. Agent 的私有事件格式会渗透到 Backlot UI；
4. 运营无法区分“建议”“草稿”“已提交事实”和“当前交付版本”；
5. 未来更换 Agent 会变成重写生产系统。

因此本设计优先固定 OpenMontage 内部合同，再实现外部 Agent 适配器。

### 2.4 现有架构基线

接入 Code Agent 前，OpenMontage 已经不是一个“等待接入 Agent 的空壳”。当前架构是一个由外部 coding assistant 驱动的 instruction-driven production system：Agent 负责理解需求、选择 pipeline、读取技能、做创意判断和推进阶段；Python 负责具体工具调用、文件持久化、合同校验、成本记录和状态投影。

现有主链路如下：

```text
外部 Coding Agent
  | 读取 AGENT_GUIDE / PROJECT_CONTEXT
  | 读取 pipeline_defs/<pipeline>.yaml
  | 读取 skills/pipelines/<pipeline>/*-director.md
  | 读取 .agents/skills/<provider-or-runtime>/SKILL.md
  v
工具注册表 tools/tool_registry.py
  | provider menu / capability catalog / selector / fallback
  v
tools/* (BaseTool)
  | image / video / tts / music / analysis / post / publish
  v
projects/<project-id>/
  | artifacts/*.json
  | checkpoint_<stage>.json
  | events.jsonl
  | assets/ renders/
  v
Backlot
  | operator state / batch state / editorial gallery / delivery review
```

现有架构可以分为五层：

| 层 | 当前职责 | 事实来源/入口 |
|---|---|---|
| Agent instruction layer | 选择 pipeline、读取导演技能、提出创意和推进阶段 | `AGENT_GUIDE.md`、`pipeline_defs/`、`skills/` |
| Capability layer | 发现工具、provider、依赖、成本和 fallback | `tools/tool_registry.py`、`BaseTool`、selectors |
| Production tool layer | 执行媒体分析、生成、音频、合成、发布 | `tools/` |
| Persistence/governance layer | 写 artifact、checkpoint、decision log、cost、events，并校验 schema | `lib/`、`schemas/`、`ProjectCommitStore` |
| Operator projection layer | 将项目事实投影为中文运营状态、批量状态和审核页面 | `backlot/`、`backlot/ui/` |

这套分层已经包含几个对 Code Agent 接入非常关键的设计决定：

1. **Agent 不是 Python 服务的一部分。** 当前没有通用 LLM API 调用层，也没有第二套 Python orchestrator；运行中的 coding assistant 本身就是编排者。
2. **Pipeline 是声明式的。** 阶段顺序、可用工具、审批门、review focus 和 success criteria 在 YAML/Markdown 中定义，而不是散落在 Python 控制流中。
3. **Tool 是能力边界。** 生成和分析通过 `BaseTool.execute()`、registry、selector 和 provider contract 进入，不应由 Agent 直接拼接 provider API。
4. **Artifact 和 checkpoint 是恢复事实。** Backlot 不以聊天记录推断生产进度，而是从项目目录中的 canonical artifact、checkpoint、events 和媒体派生状态。
5. **Backlot 当前主要是投影层。** 它已经有 typed draft、revision、review、batch action 等运营化能力，但这些能力仍应调用既有 canonical writers 和事务合同，不应另起一套视频状态机。

因此，Code Agent 接入的核心问题不是“把 Agent 放进现有 pipeline”，而是把当前由人工启动的外部 Agent 运行方式，收敛为可授权、可恢复、可审计的执行入口。

### 2.5 当前架构下 Code Agent 的两种含义

需要区分两个容易混淆的概念：

| 用法 | 当前是否已支持 | 是否需要生产架构变化 |
|---|---|---|
| 研发人员在终端使用 Claude Code/Codex/OpenCode 修改 OpenMontage 代码 | 已支持；这就是现有 README/AGENT_GUIDE 面向的使用方式 | **不需要**改变生产 pipeline；只需维护各 Agent 的项目指引文件 |
| 一线运营在 Backlot 中让 Agent 运行视频生产 | 目前只有设计边界，尚未形成统一运行时 | **需要**增加 Bridge、Broker、Job/Run、授权、事件归一化和恢复边界 |

本设计讨论的是第二种用法。第一种用法继续保留，不应被新的运营运行时替代。

### 2.6 现有视频复刻链路如何复用五层架构

当前“参考视频 + 自有素材 -> 原创复刻短视频”主要由 `cinematic-fast` pipeline 和 `ecommerce-viral-remix` Skill 实现。它不是另起一条专用的视频复刻程序，而是把参考解析、素材匹配、创意控制、镜头执行、样片审核和成片交付分别落在五层架构的既有边界中。

真实链路如下：

```text
参考视频 + 自有素材
        |
        v
research: 分析参考结构，探测自有素材，建立匹配证据
        |
        v
proposal: 生成 3 个原创方向，锁定创意控制计划
        |
        v
script: 口播/字幕/时长确认（script_lock）
        |
        v
scene_plan: 每个 beat 映射到自有素材时间段
        |
        v
assets: shot_execution_plan + asset_plan + production_lock
        |              (creative_lock)
        v
sample: 10-15 秒样片 + quick QA + judge + 人审
        |
        v
edit: 变更影响分类 no_render/mux_only/full_render
        |
        v
compose: 完整成片 + full QA + evaluation_report
        |
        v
publish: 本地交付包（外部上传另需授权）
```

#### 按五层映射

| 五层架构 | 在视频复刻链路中的具体复用 | 关键产物/入口 |
|---|---|---|
| Agent instruction layer | Agent 先读 `cinematic-fast.yaml`，再按 research/proposal/script/scene/asset/sample/edit/compose/publish director 执行；参考片只用于分析，不能直接进入成片 | `pipeline_defs/cinematic-fast.yaml`、`skills/pipelines/cinematic-fast/*`、`skills/meta/fastline.md` |
| Capability layer | Pipeline 的 `required_tools/tools_available` 声明阶段能力；Agent 通过 registry preflight 发现 `video_analyzer`、`scene_detect`、`frame_sampler`、`tts_selector`、`video_compose`、QA 和 judge 的真实可用状态；selector 根据配置 provider 路由 | `tools/tool_registry.py`、`video_selector`/`tts_selector`、pipeline manifest |
| Production tool layer | 研究阶段调用分析工具；样片/成片阶段调用 TTS、音频混合、字幕、代理素材、合成和 QA；所有工具通过 `BaseTool.execute()`，不是 Agent 直接写 provider API | `tools/analysis/`、`tools/audio/`、`tools/video/video_compose.py`、`tools/base_tool.py` |
| Persistence/governance layer | 每阶段写 canonical artifact 和 checkpoint；production lock 固定已批准配置；approval bundle 控制付费边界；decision log 记录 provider/runtime/创意变化；events 记录工具和编排心跳；change impact 控制最小重跑 | `projects/<id>/artifacts/`、`checkpoint_*.json`、`decision_log.json`、`events.jsonl`、`lib/checkpoint.py`、`lib/production_lock.py`、`lib/change_evaluation.py` |
| Operator projection layer | Backlot 将研究证据映射为“参考片怎么拍/我的素材能不能接上/参考镜头和我的素材怎么对应”；将脚本、镜头、素材、样片、成片和批量候选投影为中文业务卡片，并提供审批、草稿、版本和审核入口 | `backlot/operator_state.py`、`backlot/batch_state.py`、`backlot/ui/operator/`、Editorial Gallery |

#### 各阶段的职责边界

1. **Research 不做创意决策。** `video_analyzer`、`scene_detect`、`frame_sampler` 对参考视频和自有素材做实际探测，生成 `reference_fingerprint`、`research_breakdown`、`reference_source_matrix`、`source_media_review` 等证据。矩阵的每一行包含参考意图、自有素材区间、证据、置信度和 `pending/accept/replace_source/bridge/rewrite/omit` 处理结果。
2. **Proposal 消费研究证据并产生原创方向。** 它生成三个差异化方向、`creative_control_plan`、`hook_plan` 和 `decision_log`，把参考片的机制抽象为结构借鉴，而不是逐镜复制；此阶段不调用付费生成工具。
3. **Script 和 Scene Plan 将创意变成可执行合同。** Script 绑定已批准的 control plan，固定口播、字幕和时长；Scene Plan 用半开区间把每个 beat 映射到自有素材，并记录 `reference_evidence`、`source_fit`、`mapping_reason`、`originality_note` 和矩阵行引用。参考媒体始终标记为 `analysis_only`。
4. **Assets 形成真正的生产锁。** `shot_execution_plan`、`asset_plan`、`production_lock` 和 `approval_bundle` 固定镜头执行、声音、字幕、BGM、CTA、runtime、composition mode 和预算。创意锁批准前，只能检查缓存和估算成本，不能执行付费 TTS、音乐或视频生成。
5. **Sample 是第二个业务质量门。** 样片只渲染 10-15 秒窗口，但使用批准后的 lock 和真实的音频/字幕时间轴；`final_qa`、`technical_validator`、`video_judge` 生成样片范围的评价，运营完成 hook、proof、pacing、caption 等五项确认后才进入 edit/compose。
6. **Edit/Compose 把变更治理和交付分开。** Edit 只写 `edit_decisions` 和 `change_impact`，不能静默改 `final_props`；声音增益等局部变化可以走 `mux_only`，字幕/时间轴/画面变化必须重跑 sample 或 full render；Compose 是唯一的最终渲染入口，并执行完整 QA。

这说明五层架构在复刻链路中已经被实际使用：上层技能决定“如何借鉴”，工具层负责“如何观察和生成”，治理层保证“借鉴不变成复制、修改不破坏审批”，Backlot 层负责“运营人员如何理解和操作”。

#### 批量复刻如何复用同一架构

批量模式不是把同一条链路简单循环 N 次，而是复用研究结果、只分叉创意变量：

```text
一次共享 Research
  -> candidate_batch（索引、预算、并发、选择、差异轴）
  -> N 个 candidate project（各自 proposal/script/scene/asset/sample/edit/compose）
  -> 批级 state/report 聚合
  -> 运营选择 1-2 个候选进入精剪
```

- `lib/batch_fork.py` 将共享 research artifacts 和 analysis evidence 复制到候选项目，候选从 proposal 开始独立推进。
- `candidate_variant_plan` 固化每个候选的 hook、pacing、packaging、audience 和 duration 差异；候选不是无约束随机改写。
- `candidate_batch` 只保存候选索引、预算、并发、选择和 lineage，不复制候选完整阶段内容。
- 每个候选仍使用同一套 pipeline、tool registry、production lock、sample gate、QA 和 checkpoint；批根项目通过 `backlot.batch_state` 读取候选事实并计算批级相位。
- 批量事件是派生通知，不是候选状态真相；候选 revision 变化时，批级 `aggregate_revision` 变化，批页重新读取子项目。

当前批量架构的关键限制是：候选并发和推进仍主要由外部 Agent/运行脚本按 Skill 约定驱动，Python 只负责分叉、持久化和验证；这正是后续 Agent Bridge/Job Worker 需要补上的运行时边界，而不是重写 `candidate_batch` 或候选 pipeline。

### 2.7 五层架构在物理视频制作中的角色类比

这五层更适合理解为“制作职责簇”，不是严格的一对一岗位映射。一个物理岗位可能横跨多层，一个系统层也可能包含多个岗位的职责。尤其是 `Agent Instruction Layer` 不是“总导演本人”，而是总导演手册、制片 SOP、分镜规范、审片标准和阶段工作单的集合；运行中的 Agent 才是在读取这些规则后承担一部分总导演/执行制片职责。

| OpenMontage 层 | 物理制作中的近似角色 | 它负责什么 | 它不负责什么 |
|---|---|---|---|
| Agent Instruction Layer | 总导演 + 执行制片人 + 各工种导演的工作方法 | 理解 brief、确定创意方向、决定先做什么、选择拍法/剪法、在阶段之间做判断和取舍 | 不亲自生成每个镜头、不持有预算账、不替代真实工具和审批制度 |
| Capability Layer | 制片部门、资源调度、供应商管理、器材/场地协调 | 知道有哪些摄制资源、供应商、设备、预算、依赖和替代方案；决定某项能力当前是否可用 | 不决定影片主题、审美方向或最终镜头表达 |
| Production Tool Layer | 摄影、灯光、录音、剪辑、调色、声音、VFX、字幕和渲染工种 | 把已确定的制作意图变成实际媒体：拍摄、生成、剪辑、混音、合成、输出 | 不自行改变剧本、创意锁、审批门或交付规格 |
| Persistence/Governance Layer | 执行制片办公室 + 场记/连续性 + 版权/预算/质检 + 制片档案 | 记录版本、镜头、预算、授权、审批、返工原因、时间线和交付 QA；保证现场决定可追溯、可恢复 | 不提出新的创意方向；不根据文件状态擅自替人批准 |
| Operator Projection Layer | 监制/客户审片室 + 制片看板 + 交付台 | 把复杂制作事实翻译成“现在做到哪、要我确认什么、改动会影响什么、哪个版本可交付” | 不直接成为摄制或渲染引擎；不维护第二份生产事实 |

#### “Agent Instruction Layer 是不是总导演？”

更准确的说法是：

```text
Instruction Layer = 导演手册 + 制片 SOP + 各阶段工作单 + 质量标准
Coding Agent       = 读取这些规则并执行判断的总导演/执行制片代理
Production Tools   = 摄制与后期制作团队
Backlot Operator   = 监制/客户审片与交付入口
```

在 `cinematic-fast` 复刻链路中，Agent 的角色还会随阶段变化：

- Research 阶段更像研究导演和素材统筹；
- Proposal 阶段更像创意总监/总导演；
- Script 阶段更像编剧导演和口播导演；
- Scene Plan 阶段更像分镜导演和剪辑指导；
- Assets 阶段更像执行制片，负责生产锁、供应商、预算和审批准备；
- Sample/Compose 阶段更像后期导演和总剪辑；
- Publish 阶段更像交付制片。

所以不宜把“一个 Agent = 一个固定岗位”作为系统设计。更合理的是：Agent 在不同 stage skill 约束下，临时承担不同制作职责；`Agent Broker` 则像制片办公室的通行证和工单系统，限制它能调用哪些工种、花多少钱、修改哪些版本。

#### 两组容易混淆的边界

1. **Capability Layer 不是“副导演”。** 副导演会参与创意和现场调度；Capability Layer 更接近资源目录和制片资源台，只回答“有什么、是否可用、成本和替代路径是什么”。创意取舍仍属于 Agent Instruction Layer。
2. **Persistence/Governance 不是“行政后台”。** 它更像场记、连续性、制片档案、版权/预算和 QC 的合体。它不创造内容，但没有它就无法证明哪一版经过批准、哪些素材能用、为什么需要返工、当前版本是否可交付。
3. **Operator Projection 不是“生产控制器”。** 它是审片室和交付台。它可以提交 typed decision、draft、review 和 rerun request，但真正的生产事实仍由 pipeline、tool、artifact、checkpoint 和 commit contract 产生。

#### 对 Code Agent 接入的直接启示

如果把 Agent 当成“总导演”，仍然不能让它直接指挥所有物理工种。物理制作中总导演也通过制片、部门负责人、场记和审批流程工作；在 OpenMontage 中对应的是：

```text
Agent Instruction Layer
  -> Agent Bridge（会话与事件）
  -> Agent Broker（授权、预算、工具和 secret 边界）
  -> Capability Layer（可用资源）
  -> Production Tool Layer（实际执行）
  -> Persistence/Governance（留痕、校验、恢复）
  -> Operator Projection（监制确认和交付）
```

因此 Code Agent 接入主要是把“总导演代理”的工作入口从研发终端搬到受控的制片办公室；它不会替换现有的摄制/后期工具、生产档案、质量门或运营审片室。

## 3. 目标与非目标

### 3.1 目标

1. 一线运营无需命令行即可创建、审核、修改、重跑和交付单条视频。
2. 一线运营可以在同一工作台创建批量任务，比较候选，选择候选并进入精剪。
3. 单任务和批量任务共享项目 revision、checkpoint、审批、成本和 QA 合同。
4. Agent 可以被替换，但不会改变 pipeline、artifact、checkpoint 和质量门的定义。
5. 所有 Agent 的会话、事件、工具调用、写入和失败都可审计、可恢复。
6. 低风险任务可以自动推进；创意锁、付费调用、发布和降级路径必须明确确认。
7. 生产工作台能够支持本机/内网单团队，并为未来 worker 分离预留接口。

### 3.2 非目标

- 首期不建设自由拖拽式 NLE，不提供任意轨道、关键帧、曲线或插件画布。
- 首期不建设云端多租户、企业 SSO、在线对象存储和跨组织计费。
- 不让浏览器直接调用 TTS、图像、视频、音乐或发布 provider。
- 不新增第二套 Python pipeline orchestrator。
- 不将某一家 Agent 的私有协议作为 OpenMontage 的 canonical state。
- 不在 Agent 适配项目中重写已有的 pipeline director 或 tool provider。

## 4. 运营产品闭环

### 4.1 统一任务生命周期

Backlot 需要把单任务和批量任务投影为同一套业务状态：

```text
draft
  -> queued
  -> running
  -> awaiting_human
  -> running
  -> delivery_review
  -> delivered
```

异常分支：

```text
queued/running -> paused
queued/running -> failed -> recoverable|blocked
queued/running -> cancelled
delivery_review -> revision_requested -> queued
```

内部仍使用现有 pipeline stages：`research -> proposal -> script -> scene_plan -> assets -> sample -> edit -> compose -> publish`。运营界面只显示中文业务阶段和下一步，不暴露内部 stage id。

### 4.2 单任务流程

单任务工作流必须覆盖：

1. 创建项目：选择业务 Skill、平台、时长、素材和内容输入。
2. 生成方案：展示创意方向、工具路径、音乐计划、预算和运行时。
3. 生产：展示阶段进度、当前任务、预计完成时间和最近活动。
4. 审核：脚本、镜头、素材、样片和成片分别按 manifest gate 处理。
5. 修改：使用 typed editor 或 Agent 对话生成草稿。
6. 影响预览：显示受影响阶段、费用、耗时、复用范围和审批重开范围。
7. 生成新版：创建独立 delivery version，不替换当前版本。
8. QA 与交付：只有完整 QA 通过的版本才能成为 current delivery。

### 4.3 批量流程

批量工作流必须覆盖：

1. 创建批次：输入共同 brief、数量、候选差异策略和预算上限。
2. 生成候选：通过 `candidate_variant_plan` 固化候选差异，随后 fork candidate projects。
3. 批级观察：显示建批、样片、评分、选择、精剪、发布六个业务轨道。
4. 批级审核：支持候选抽屉、样片门、成片门和批级聚合审批。
5. 候选选择：选择不立即修改事实，提交时携带 `aggregate_revision`。
6. 批级精剪：只对选中的候选创建受约束修改。
7. 局部恢复：失败候选、过期候选和被拒候选可以单独重跑。
8. 批量报告：输出吞吐、成本、人工等待、缓存、重试、返工和候选通过率。

### 4.4 工作台页面边界

建议保留四个业务入口：

| 页面 | 作用 | 事实来源 |
|---|---|---|
| 项目库 | 建单、搜索、查看项目和批次 | `project.json`、operator state |
| 运行队列 | 查看排队、进行中、等待确认、失败和恢复 | job/run event projection |
| 编辑工作室 | 审核脚本、镜头、素材、成片和修改草稿 | canonical artifacts + revisions |
| 批量工作台 | 比较候选、聚合审批、选择和批量报告 | `candidate_batch` + child projects |

诊断页继续保留给管理员，允许查看原始 artifact、checkpoint、event、hash 和路径。

## 5. 统一运行模型

### 5.1 核心对象

新增或统一以下业务对象。它们是 Backlot 的运行合同，不取代现有 canonical artifacts。

```text
Job              用户发起的一次单任务或批量任务
Run              Job 的一次可恢复执行尝试
BatchRun         批量任务的聚合运行
CandidateRun     批量任务中某个候选的运行
AgentSession     Agent 与某个 Run 绑定的会话
RunAuthorization 本次运行允许的阶段、工具、预算和有效期
DeliveryVersion 经过 QA、可被发布的完整成片版本
```

### 5.2 `Job`

```json
{
  "schema_version": "1.0",
  "job_id": "job-20260824-000001",
  "kind": "single|batch",
  "project_id": "project-id",
  "batch_id": null,
  "skill_id": "ecommerce-viral-remix",
  "requested_by": "operator-id",
  "status": "queued",
  "base_revision": "opaque-revision",
  "budget_limit_usd": 2.0,
  "created_at": "2026-08-24T00:00:00Z"
}
```

约束：

- `job_id` 幂等；相同 idempotency key 不创建第二个 Job。
- Job 不携带 provider secret 或任意 shell 命令。
- Job 的业务输入通过 typed schema 验证，不能上传任意 project path。
- 批量 Job 只保存批级输入和候选计划引用，不复制候选完整 artifact。

### 5.3 `RunAuthorization`

```json
{
  "schema_version": "1.0",
  "authorization_id": "run-auth-000001",
  "job_id": "job-20260824-000001",
  "project_id": "project-id",
  "allowed_stages": ["assets", "sample", "edit", "compose"],
  "allowed_capabilities": ["tts", "image_generation", "video_post"],
  "max_cost_usd": 1.2,
  "max_parallel": 2,
  "approval_scope": "sample_only",
  "expires_at": "2026-08-24T04:00:00Z",
  "issued_by": "operator-id"
}
```

付费 provider、provider/model 切换、render runtime 切换和发布动作必须重新生成授权或重新审批，不能沿用旧 token。

## 6. Agent Bridge 与 Agent Broker

### 6.0 架构变化的总原则

接入 Code Agent 后，OpenMontage 的“生产智能”和“生产事实”边界不变，但“谁启动 Agent、谁提供上下文、谁执行工具、谁提交写入”会变化。

```text
接入前（研发/人工启动）

运营或研发人员 -> Coding Agent 进程 -> 读取仓库并调用 tools -> projects/ -> Backlot 投影

接入后（运营工作台启动）

运营 -> Backlot Job API -> Run Worker -> Agent Bridge
                                  |              |
                                  |              +-> Agent session
                                  v
                            Agent Broker
                              |  tool registry / budget / ACL / secrets
                              v
                         tools + ProjectCommitStore -> projects/ -> Backlot
```

必须保留的部分：

- pipeline manifest、stage director skill 和 meta skill；
- `tools/tool_registry.py`、`BaseTool`、selectors 和 provider contracts；
- canonical artifact、checkpoint、decision log、events、cost tracker 和 schema；
- 项目目录约定 `projects/<project-id>/`；
- Remotion/HyperFrames/FFmpeg 的 runtime 选择和“不能静默切换”的治理规则；
- Backlot 从事实源派生 operator state、batch state、审核和交付版本。

必须新增或收口的部分：

- Agent 的启动、会话、心跳、事件、暂停、恢复、取消和超时；
- Job/Run/CandidateRun 的队列和生命周期；
- Agent 能访问哪些项目、阶段、工具和预算的 capability token；
- Agent 与 provider secret、网络和任意 shell 的隔离；
- Agent proposal/draft 到 canonical artifact 的受控提交；
- 多种 Agent 输出到统一 `agent_event` 的适配；
- 运营 UI 中的 Agent 状态、等待确认、失败原因和恢复动作；
- Agent 版本、adapter 版本、回滚和兼容性记录。

明确不应新增的部分：

- 不新增一个独立于 pipeline manifest 的 Python production orchestrator；
- 不让每个 Agent 自己维护一份阶段状态机；
- 不把 Agent 对话历史当作 checkpoint；
- 不为每个 Agent 复制一套 provider selector、成本账本或 QA 规则；
- 不让 Backlot UI 直接理解 Codex/OpenCode/Pi/Hermes 的私有事件。

### 6.0.1 三种接入形态的影响

| 接入形态 | 适用对象 | 架构变化 | 结论 |
|---|---|---|---|
| 研发终端直连 | 开发者使用 Agent 改代码、调试工具 | 仅维护 `AGENTS.md`/`CLAUDE.md`/`CODEX.md` 等上下文文件 | 现有生产架构不用动 |
| Backlot 本机受控 subprocess/RPC | 一线运营使用 Agent 生成视频 | 增加 Bridge、Broker、Job/Run、授权、事件和恢复；项目事实源不变 | **首期推荐** |
| 云端/远程 Agent worker | 多用户、远程 GPU、消息入口或定时任务 | 还需 worker registry、租约、远程 artifact、对象存储、网络信任和多租户隔离 | 后续单独立项 |

首期采用第二种形态：Backlot 和 Broker 在本机/内网受控环境运行，Agent 可以是本机进程，但它看到的是受限 workspace 和 Broker 能力，而不是整个 OpenMontage 仓库及所有 secrets。

### 6.1 Agent Bridge 责任

Agent Bridge 只负责把外部 Agent 变成统一的 session/event 供应者，不负责决定业务审批和 canonical 写入。

建议接口：

```python
class AgentBridge(Protocol):
    def health(self) -> AgentCapabilities: ...
    def prepare(self, context: RunContext) -> PreparedSession: ...
    def start(self, request: AgentRequest) -> AgentSession: ...
    def send(self, session_id: str, message: str) -> Iterable[AgentEvent]: ...
    def interrupt(self, session_id: str) -> None: ...
    def resume(self, session_id: str, checkpoint: ResumeCheckpoint) -> Iterable[AgentEvent]: ...
    def cancel(self, session_id: str) -> None: ...
    def close(self, session_id: str) -> None: ...
```

Bridge 不允许：

- 直接写 `projects/<id>/artifacts/`；
- 直接修改 checkpoint、approval、decision log 或 current delivery；
- 读取未授权项目；
- 自己决定 provider fallback、runtime swap 或跳过人审；
- 把 Agent 私有 session state 当作 OpenMontage 恢复状态。

### 6.2 统一 `AgentCapabilities`

```json
{
  "agent_id": "codex",
  "adapter_version": "1.0",
  "transport": "app_server|sdk|rpc|subprocess|acp",
  "supports": {
    "streaming": true,
    "interrupt": true,
    "resume": true,
    "structured_events": true,
    "approval_callbacks": true,
    "local_models": false,
    "remote_workspace": false
  },
  "requires": ["node", "codex-auth"],
  "status": "available|degraded|unavailable"
}
```

### 6.3 Agent Broker 责任

Broker 是 Agent 能做什么的唯一来源。所有工具和写入都通过 Broker 执行。

首期允许的操作：

```text
project.read
artifact.read
artifact.propose
checkpoint.read
checkpoint.write
tool.discover
tool.execute
draft.apply
review.request
delivery.create
delivery.promote
run.pause
run.resume
```

操作约束：

1. `project.read` 只返回当前项目和允许阶段的业务上下文。
2. `artifact.propose` 写入 Agent proposal 或 operator draft，不直接写 canonical artifact。
3. `checkpoint.write` 必须经过 checkpoint schema、pipeline gate、artifact envelope 和 revision 校验。
4. `tool.execute` 只接受 tool registry 中已发现、已允许、依赖满足的工具名。
5. 付费调用必须匹配 `RunAuthorization` 的 capability、stage、budget 和有效期。
6. 所有输出先进入 `operator/jobs/<job-id>/outputs/`，校验后才由 ProjectCommitStore 提交。
7. 任意路径、任意 shell、任意 provider URL 和任意 secret 注入都必须拒绝。

### 6.4 Secret 与网络隔离

- Agent 进程不接收 TTS、音乐、图像、视频 provider secret。
- provider secret 只存在于 secret-bearing Broker worker。
- Agent 默认无外网；需要外部 provider 时由 Broker 代理调用。
- Broker 只将脱敏的 tool result、媒体引用和业务错误返回 Agent。
- Agent 日志不得包含环境变量、Authorization header、完整 URL query 或本机绝对路径。

### 6.5 会话与恢复

Agent session 只保存：

- Agent 标识和 adapter 版本；
- Job/Run/Project revision 绑定；
- 最近 checkpoint 引用；
- 已发送消息摘要；
- 事件游标；
- 恢复所需的短期 token 元数据。

Agent 私有上下文丢失时，恢复必须依赖 OpenMontage checkpoint 和 artifact，而不是依赖 Agent 的记忆文件。恢复动作创建新的 Run attempt，旧 attempt 保留审计记录。

## 7. 多 Agent 对比与接入决策

### 7.1 评估维度

比较不以“代码能力排行榜”为目标，而看它是否适合成为 OpenMontage 的受控执行后端：

- 是否有稳定的进程/SDK/RPC 接入面；
- 是否能提供结构化事件、会话恢复和中断；
- 是否支持权限、审批、MCP/工具扩展；
- 是否适合本机/内网部署；
- 是否容易隔离 secret 和工作区；
- 是否会将供应商或运行时锁死到 OpenMontage 核心；
- 维护成本和版本稳定性。

### 7.2 Agent 结论矩阵

| Agent | 主要优势 | 主要风险 | 首选接入 | 产品定位 |
|---|---|---|---|---|
| Codex | app-server、SDK、结构化事件和本地工程体验较完整 | OpenAI 生态绑定；适配 API 需要跟踪版本 | app-server/SDK | **默认生产 Agent** |
| OpenCode | 开源、多 provider、server/client/SDK 和 plugin 边界清晰 | TypeScript/Bun 运行栈较重，API 迭代快 | SDK 或本地 server | **第二生产适配器** |
| Pi | 极简、支持 print/JSON/RPC/SDK，扩展容易 | 默认不提供 sub-agent、plan 等治理能力 | RPC/SDK | **轻量本地 worker** |
| Hermes Agent | Python、MCP、ACP、远程 terminal backend、消息网关和 cron | 功能面大；持久记忆、自学习和远程后端增加治理面 | ACP 或受控 gateway | **后续自动化/远程 worker** |
| Claude Code | 工程质量、权限、hooks、plugins、MCP 生态成熟 | CLI/商业运行时耦合；数据与授权策略需单独审核 | subprocess 或官方 SDK | **质量对照 Agent** |
| DeepSeek Harness | MIT、插件化、带 Web UI，适合快速实验 | 官方仍为 developer preview，兼容性破坏风险高 | 独立实验 adapter | **暂不进入生产默认** |

### 7.3 推荐顺序

1. Codex：完成首个生产级 Agent Bridge。
2. OpenCode：验证多 provider 和开源替换能力。
3. Pi：验证最低成本 RPC worker。
4. Hermes：验证远程执行、定时任务和消息入口。
5. Claude Code：做质量、成本和交互体验对照。
6. DeepSeek Harness：等插件和 API 稳定后再评估生产化。

### 7.4 不建议的接入方式

- 在前端提供“选择任意 Agent 并直接执行 shell”。
- 每个 Agent 自己维护一份 OpenMontage pipeline prompt 和状态机。
- 通过解析 TUI 文本来判断阶段、费用或完成状态。
- 让 Agent 直接读取 provider key 并调用外部视频 API。
- 让一个 Agent 的失败自动静默切换到另一个 Agent。
- 用 Agent 记忆或对话历史替代 checkpoint 和 artifact。

## 8. 运营 Skill 目录

运营人员选择业务任务，不选择内部 stage、模型和 shell 命令。新增运营 Skill Catalog，每个 Skill 固定声明：

```text
skill_id
适用输入
默认 pipeline
默认 Agent
允许修改字段
允许工具能力
默认审批点
预算上限
批量上限
失败恢复策略
交付输出
```

首期 Skill 建议：

| Skill | 典型场景 | 默认路径 |
|---|---|---|
| 单条电商短视频 | 一个商品、一条平台视频 | cinematic-fast 或 hybrid |
| 批量变体 | 同一商品、多种 Hook/CTA/节奏 | batch producer + candidate projects |
| 长视频切片 | 直播、播客、课程切短视频 | clip-factory 或 podcast-repurpose |
| 成片返工 | 只改前三秒、字幕、声音或结尾 | delivery review + minimal rerun |
| 本地化版本 | 配音、字幕、平台规格转换 | localization-dub |

运营 Skill 必须将 provider、runtime、预算和审批策略写入 proposal/authorization，而不是藏在前端默认值中。

## 9. 交付分阶段路线

### P0：运营工作台闭环

范围：

- Editorial Gallery 真实数据接入；
- 成片审核台“审核 -> 影响预览 -> 生成新版 -> QA -> promote”；
- 单任务创建、运行队列、暂停、恢复、取消；
- 批量候选比较、批级审批、选择、局部恢复；
- 统一 Job/Run 状态和业务事件；
- 认证、ACL、CSRF、幂等、审计和成本显示；
- 明确 `trial` / `production` 发布状态，不提前承诺未经基准验证的 SLA。

交付门：运营仅通过 Backlot 完成一条单任务和一个五候选批次，且不需要打开命令行。

### P1：Codex Agent Runtime

新增：

```text
backlot/agent_bridge/base.py
backlot/agent_bridge/codex.py
backlot/agent_broker.py
schemas/backlot/agent_profile.schema.json
schemas/backlot/agent_session.schema.json
schemas/backlot/agent_request.schema.json
schemas/backlot/agent_event.schema.json
schemas/backlot/run_authorization.schema.json
```

交付门：Codex 可以在不接触 secret、不直接写 canonical 文件的情况下，完成一个受授权的 sample run，并在刷新、暂停、进程重启后恢复。

### P2：OpenCode 与 Pi

- OpenCode：接入 SDK 或本地 server，验证多 provider 和 plugin 能力。
- Pi：接入 RPC/SDK，验证轻量、低资源和快速启动。
- 两个适配器必须复用 P1 的 Broker 和事件 schema，不得复制生产权限。

交付门：相同输入、相同授权和相同 pipeline 下，两个 Agent 的事件、费用、产物和失败行为都能被 Backlot 统一投影。

### P3：Hermes、Claude Code、DeepSeek Harness

- Hermes：优先验证远程 terminal、ACP、消息网关和 cron；不默认开启自学习记忆写入项目。
- Claude Code：验证 subprocess/SDK 生命周期、权限提示和数据策略；只在授权明确时进入生产候选。
- DeepSeek Harness：以独立实验 adapter 验证 plugin 能力，不绑定核心数据合同。

交付门：每个适配器通过隔离、恢复、权限和事件契约测试后，才能出现在管理员 Agent Catalog；未通过的 Agent 不显示为可选生产后端。

## 10. 测试与验收

### 10.1 Bridge/Broker 契约测试

- `health()` 能正确报告 available/degraded/unavailable。
- session 可以 start、stream、interrupt、resume、cancel 和 close。
- Agent event 能转换为统一 schema。
- Agent 无法访问未授权项目、stage、tool 和 capability。
- Agent 无法读取 provider secret、绝对路径和未脱敏异常。
- 任意 shell、任意路径、任意 URL 和任意 JSON Patch 均被拒绝。
- 付费调用必须有有效 RunAuthorization，预算超限立即阻断。
- canonical 写入只能经 ProjectCommitStore，崩溃后只能看到旧状态或完整新状态。

### 10.2 单任务端到端测试

- 建单 -> proposal -> script -> sample -> compose -> delivery。
- 在 script gate 等待人工确认，刷新后状态不丢失。
- 修改字幕只触发正确的最小重跑路径。
- 修改声音时可以 `mux_only`，但 creative/sample review 重新打开。
- 新版 QA 失败时，旧版仍是 current delivery。
- Agent 进程重启后从 checkpoint 恢复，不重复付费调用。

### 10.3 批量端到端测试

- 五候选批量运行，候选状态、批级状态和报告一致。
- 批级审批使用 aggregate revision，任一候选 stale 时不产生部分批准。
- 只重跑失败候选，不重新生成成功候选。
- 候选选择、批级报告和成片版本在页面刷新后保持一致。
- 质量报告 partial/degraded/missing 时，系统禁止误显示为批量通过。

### 10.4 Agent 对比评测

统一记录：

```text
首次成片通过率
样片通过率
平均返工轮数
P50/P95 完成时间
每条视频成本
人工等待时间
缓存命中率
恢复成功率
工具越权拒绝率
运营确认次数
运营满意度
```

所有“更快”“更便宜”“质量更高”的结论必须来自同一批输入、同一 pipeline、同一质量 rubric 和可追溯的 run report。

## 11. 发布与运维策略

### 11.1 Agent Catalog 发布状态

Agent 只能处于：

```text
experimental -> internal_trial -> production -> suspended
```

晋级条件包括：适配器契约测试、权限测试、恢复测试、至少一组真实任务评测和版本回滚方案。

### 11.2 版本兼容

- 每个 adapter 固定 `adapter_version` 和外部 Agent 版本范围。
- Agent 升级先进入 shadow/fixture 环境，不直接替换 production adapter。
- 事件 schema 和 OpenMontage artifact schema 独立版本化。
- 外部 Agent 兼容性破坏不应改变项目事实源。

### 11.3 失败处理

发生失败时必须显示：

1. 尝试了什么；
2. 哪一步失败；
3. 是认证、provider、工具、Agent、权限、预算还是设计质量问题；
4. 可选的下一步；
5. 推荐的恢复方式。

不得静默更换 provider、模型、Agent、render runtime 或从 motion-led 降级为 still-led。

## 12. 决策记录

本设计默认采用以下决策：

| 决策 | 默认值 | 原因 |
|---|---|---|
| 部署 | 本机/内网单团队 | 与当前 Backlot 和 secrets 隔离模型一致 |
| Agent 策略 | 一个默认 Agent + 可插拔适配器 | 降低运营复杂度和状态分叉 |
| 默认 Agent | Codex | 接入面、结构化事件和本地执行最适合首期 |
| 审批策略 | 低风险自动，高风险确认 | 平衡吞吐、成本和运营可控性 |
| 内部事实源 | artifact/checkpoint/revision/event | 保持现有 OpenMontage 合同 |
| 浏览器权限 | typed operation，不允许任意 JSON/shell | 防止越权和不可审计修改 |
| 多 Agent 协作 | 不在首期范围 | 先验证单 Agent 受控执行闭环 |
| DeepSeek Harness | 实验性 | 当前仍是 developer preview，存在兼容性破坏风险 |

如果后续要采用云端多租户或多 Agent 协作，需要另立架构设计，不应在本设计上直接扩展。

## 13. 相关文档

- [Backlot 运营工作台与电商爆款复刻技术规范](2026-08-15-backlot-operator-workbench-design.md)
- [Backlot 成片运营审核台增量设计](2026-08-19-backlot-delivery-review-workbench-design.md)
- [Editorial Gallery 真实数据接入计划](../plans/2026-08-24-editorial-gallery-real-data-integration.md)
- [批量工作台交互设计](../../art-plan/Batch_Workbench_Interaction_Design_2026-08-23.md)
- [批量工作台聚合状态事件合同](../../art-plan/Batch_Workbench_Aggregate_State_Event_Contract_2026-08-23.md)
- [OpenMontage Architecture](../../ARCHITECTURE.md)

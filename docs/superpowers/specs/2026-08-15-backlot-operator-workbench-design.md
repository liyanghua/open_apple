# Backlot 运营工作台与电商爆款复刻 Skill 技术规范

**状态：** 定稿（实施基线）
**日期：** 2026-08-15
**依赖基线：** `cinematic-fast` artifact v2、approval groups、production lock、change impact、Fastline Benchmark
**首个验收项目：** `transparent-table-mat-remix-01`

## 1. 摘要

本规范将 Backlot 从只读工程观察板升级为本机/内网单团队使用的运营生产
工作台，并把 `cinematic-fast` 封装为一线运营可启动、可编辑、可批准、可恢复
的“电商爆款复刻”Skill。

系统保留现有 artifact、checkpoint、approval bundle、production lock 和事件流
作为机器合同，不以富文本或数据库取代它们。新增层只负责：

1. 将机器状态投影为中文业务状态；
2. 接受受约束的人工草稿；
3. 在提交前计算影响、费用、耗时和重审批范围；
4. 以追加式 revision 写入新版本；
5. 通过 Agent Bridge 将复杂修改交给 OpenMontage Agent；
6. 为团队提供身份、权限、审计、冲突和恢复。

Backlot 默认不展示 JSON、哈希、schema、runtime、artifact path、原始事件或内部
阶段名。管理员诊断视图继续保留这些信息，用于排障和合同审计。

## 2. 目标与非目标

### 2.1 目标

1. 一线运营无需命令行即可建单、查看进度、编辑中间结果和完成两道确认。
2. 所有界面阶段、状态、错误和操作使用简体中文业务语言。
3. 所有人工修改在提交前显示受影响内容、返工方式、预计时间、预计费用和
   重审批要求。
4. 所有提交、批准、拒绝、恢复和 Agent 修改均可追踪、可比较、可恢复。
5. Agent 与人工基于同一项目版本工作，冲突不得静默覆盖。
6. `cinematic-fast` 的两道 Gate、付费边界、版权隔离和最终 QA 不被 UI 绕过。
7. 内置 Agent 首版使用本机 Codex，接口保持可替换。
8. 透明桌垫项目能够完整展示业务视图，即使它是升级前的 legacy cinematic
   项目。

### 2.2 非目标

- 首版不建设多轨非线性剪辑器、关键帧编辑器或完整素材自由画布。
- 首版不建设云端多租户、在线对象存储、计费或企业 SSO。
- UI 不直接调用 TTS、音乐、图像或视频生成 provider。
- Python 不承担创意判断，不新增第二套 pipeline 编排器。
- 不允许浏览器提交任意 JSON Patch、任意文件路径或任意 shell 命令。
- 不承诺未完成 sample floor 的 3-5 小时 SLA。
- 不以 Flova 的所有通用视频功能为首版范围。

## 3. 设计原则

### 3.1 一份事实，两种视图

Canonical artifact 是机器事实。运营视图是确定性投影，不保存一份与 artifact
脱节的业务副本。管理员诊断视图可以查看原始合同，运营视图只能查看经过
映射、裁剪和中文化的字段。

### 3.2 草稿不是事实

编辑器自动保存的是用户草稿。草稿不修改 artifact、checkpoint、approval 或
production lock。只有用户查看影响并再次确认后，提交服务才创建新 revision。

### 3.3 恢复也是新版本

恢复历史版本不覆盖当前文件，也不删除后续历史。系统将选定历史内容复制为
新的当前 revision，并重新计算变更影响与审批状态。

### 3.4 直接编辑与 Agent 修改分工

- 字段明确、影响确定的修改由 typed adapter 直接处理。
- 跨阶段、语义重写、素材重新分析和创意设计交给 Agent Bridge。
- UI 不根据自然语言自行决定 pipeline、provider 或 render runtime。

### 3.5 最小安全返工

新增 `evaluate_change_impact()` 作为唯一公开分类入口。现有
`compare_production_locks()` 只提供 locked-field diff，`classify_change()` 只提供
props 的音画 diff；调用方不得直接使用二者的 route/reopen 结果。新入口按下表
同时决定渲染方式与重审批，消除两套分类器冲突：

| 变化 | 渲染方式 | Creative Lock | Sample |
|---|---|---|---|
| metadata、note | `no_render` | 不重开 | 不重开 |
| gain、LUFS、峰值修正 | `mux_only` | 不重开 | 不重开，必须 full audio QA |
| 旁白音频、音色、provider、model、rate、BGM 曲目 | `mux_only`，前提是视觉 props/caption/timing hash 不变 | 重开 | 重开 |
| 旁白文字且同步改变字幕或时长 | `full_render` | 重开 | 重开 |
| 字幕文字、字体、位置、强调、镜头、裁切、速度、转场 | `full_render` | 字幕文案/字体重开；纯执行参数不重开 | 重开 |
| CTA、平台、输出规格、runtime、composition mode | `full_render` | 重开 | 重开 |

若 `final_props` 证明视觉 hash 不变，创意音频变化可以 `mux_only`；渲染复用不
代表批准继续有效。默认允许自审时，提交人仍需对新 creative review 和 sample
review 分别作出可审计决定。无法完整分类时使用最保守的
`full_render + reopen creative + reopen sample`。

## 4. 产品语言规范

### 4.1 阶段名称

| 内部名称 | 运营名称 | 阶段目标 |
|---|---|---|
| research | 参考解析与素材体检 | 看懂参考方法并确认自有素材真实内容 |
| proposal | 创意方案 | 对比并选择原创方向和卖点顺序 |
| script | 口播与字幕 | 确认旁白、屏幕文案和时长 |
| scene_plan | 镜头映射 | 将每个叙事节拍绑定到真实素材时间段 |
| assets | 制作准备 | 确认声音、字幕、音乐、费用和制作锁 |
| sample | 样片确认 | 检查 10-15 秒真实样片 |
| edit | 修改与精剪 | 根据反馈执行最小范围调整 |
| compose | 成片生成 | 生成完整视频并执行全量 QA |
| publish | 交付下载 | 检查交付包并下载 |

### 4.2 工程术语映射

运营视图必须使用以下表达，不得同时显示内部英文：

| 内部术语 | 运营表达 |
|---|---|
| gate | 待确认事项 |
| approval bundle | 本次待确认内容 |
| production lock | 已确认制作配置 |
| cache hit | 已复用 |
| cache miss | 新处理 |
| change route | 本次修改范围 |
| full_render | 重新生成完整画面 |
| mux_only | 保留画面，仅更新声音 |
| no_render | 无需重新生成视频 |
| ETA | 预计完成时间 |
| dirty scenes | 需要重做的镜头 |
| artifact | 阶段内容或制作文件 |
| checkpoint | 阶段进度 |
| revision | 版本 |
| superseded | 内容已变化，需要重新确认 |
| awaiting_human | 等待确认 |

### 4.3 禁止项

运营 DOM、可访问名称、tooltip、错误消息和下载文件名中不得出现：

- raw JSON；
- `semantic_sha256`、`artifact_sha256`；
- `decision_log.json`、`events.jsonl`；
- schema 名称；
- 绝对文件路径；
- `research/proposal/scene_plan` 等内部阶段值；
- stack trace、Python 异常类名或 subprocess 命令。

管理员诊断视图不受此条限制，但必须明确标记“诊断信息”。

## 5. 总体架构

```text
浏览器运营工作台
  |-- 项目状态
  |-- 阶段编辑器
  |-- 审批/版本/恢复
  |-- Agent 对话
          |
          v
Backlot FastAPI
  |-- Auth / Session / CSRF
  |-- Operator Projection
  |-- Draft Service
  |-- Impact Preview
  |-- Project Commit Store / Revision Service
  |-- Approval Service
  |-- Agent Bridge
  |-- Agent Broker (受控工具与阶段提交)
          |
          +--> existing artifact/checkpoint/approval/change-impact libraries
          +--> read-only Codex CLI adapter
          +--> append-only operator audit and agent events
```

### 5.1 前端边界

继续使用原生 JavaScript ES modules，不新增 React/Vite 构建链。原因是 Backlot
当前由 FastAPI 直接提供静态文件，首版需求以表单、卡片、播放器和状态更新为主，
无需引入第二套前端运行时。

现有工程页面保留为管理员诊断页。默认项目路由加载新的运营模块；诊断路由
仅管理员可进入。

建议模块边界：

```text
backlot/ui/operator/
  app.js              页面启动和路由
  api.js              HTTP/SSE 与 CSRF
  store.js            当前项目、草稿和 job 状态
  language.js         中文阶段和状态词典
  components/         通用业务组件
  editors/            各阶段 typed editor
  styles/             运营工作台样式
```

`board.js` 不继续扩张为同时承担运营和诊断的单文件。

### 5.2 后端边界

建议新增：

```text
backlot/operator_state.py        运营投影
backlot/operator_actions.py      草稿、预览、提交、恢复
backlot/operator_adapters.py     各 artifact 可编辑字段和验证
backlot/operator_revisions.py    追加式版本与比较
backlot/project_commit.py        项目锁、generation、可见性与崩溃恢复
backlot/auth.py                  用户、角色、会话、CSRF
backlot/audit.py                 追加式操作审计
backlot/agent_bridge/base.py     可插拔 Agent 协议
backlot/agent_bridge/codex.py    Codex CLI 适配器
backlot/agent_broker.py          Agent 唯一工具/写入边界
backlot/skill_catalog.py         运营 Skill 目录
```

Backlot 不复制 artifact hash、checkpoint、approval group 或 change impact 的
实现，必须调用现有 `lib/` 能力。浏览器、Agent 和后台 worker 均不得直接写
canonical artifact；人工/Agent 提案通过 Revision Service，pipeline 阶段输出通过
Agent Broker 调用现有 artifact/checkpoint writer。二者最终都进入同一个
Project Commit Store。

所有新增 wire/persistence 对象使用 `schemas/backlot/` 下的版本化 JSON Schema：
`operator_state`、`operator_draft`、`impact_preview`、`operator_revision`、
`operator_review`、`agent_request`、`agent_event`、`run_authorization` 和
`operator_skill_index`。Python 和前端 fixture 必须验证同一份 schema；不允许只靠
TypeScript/JSDoc 或示例 JSON 定义合同。

## 6. 运营状态模型

### 6.1 `OperatorProjectState`

```json
{
  "project_id": "transparent-table-mat-remix-01",
  "title": "透明桌垫竖屏产品混剪",
  "pipeline": "cinematic-fast",
  "skill": {"id": "ecommerce-viral-remix", "version": "1.0.0"},
  "summary": {
    "current_stage": "镜头映射",
    "current_task": "正在确认镜头顺序和素材时间段",
    "progress_percent": 58,
    "next_action": "检查并提交镜头映射",
    "estimated_seconds": 1800,
    "estimate_confidence": "low",
    "spent_usd": 0.0
  },
  "stages": [],
  "workspace": {},
  "pending_review": null,
  "permissions": [],
  "active_job": null,
  "revision": "project-state-token"
}
```

规范要求：

- `pipeline` 只供客户端路由，不在运营界面直接显示。
- `revision` 是运营状态的并发令牌，不是工程哈希。
- `workspace` 只包含当前阶段所需的业务字段。
- 缺失新快线 artifact 时返回 legacy 业务摘要和升级建议，不返回空 JSON 卡片。

### 6.2 `StageView`

每个阶段返回统一外壳：

```json
{
  "id": "scene_plan",
  "label": "镜头映射",
  "status": "需要确认",
  "version": 3,
  "updated_at": "2026-08-15T12:00:00Z",
  "updated_by": "operator-a",
  "editable": true,
  "summary": "16 个镜头，30 秒",
  "warnings": [],
  "editor": {"type": "shot_mapping", "data": {}}
}
```

`editor.type` 必须来自固定枚举，前端不得根据任意 schema 动态生成表单。

### 6.3 Legacy 项目投影

对于升级前的 `cinematic` 项目：

1. 从现有 artifact 和 checkpoint 推导只读业务视图；
2. 缺少 `approval_bundle`、`render_plan` 或 `production_lock` 时显示“该项目创建于
   快线升级前，此项暂无结构化记录”；
3. 不伪造批准、缓存或 ETA；
4. 用户首次提交编辑前，必须执行显式的“创建快线运营副本”；
5. 原 legacy 项目保持只读且完全不修改；运营副本是新的 `cinematic-fast` 项目。

透明桌垫项目使用以下确定性迁移表：

| Legacy 内容 | 新项目处理 | 不能推导时 |
|---|---|---|
| `project.json` | 新建项目，记录 `parent_project_id`、`parent_pipeline_type`、`migration_version` | 整体失败，不创建半成品项目 |
| `research_brief`、`video_analysis_brief`、`source_media_review` | 校验后重新 envelope | research 回到 pending |
| `media_index`、`reference_fingerprint` | 只通过本地文件重新计算，不复制旧 hash | research 回到 pending |
| `proposal_packet`、`script`、`scene_plan` | schema 有效时复制并重新 envelope | 对应阶段及其后续回到 pending |
| `decision_log` | 保留历史 entry，追加 migration decision | 缺失时创建空 log 加 migration decision |
| `asset_manifest` | 仅作为“可复用候选素材”导入，不代表已批准 asset plan | 无候选素材 |
| `asset_plan` | 从候选素材生成 `reuse_only` 计划，`paid_generation_approved=false` | assets 回到 pending |
| `production_lock` | 使用新项目已迁移 artifact 重新构建 | assets 回到 pending |
| `approval_bundle` | 永不继承旧批准；创建新的 creative bundle `awaiting_human` | 整体升级失败 |
| sample/edit/compose/publish checkpoint | 不作为当前 checkpoint 复制 | 原成片只作为 legacy deliverable 链接 |
| renders/media | 通过不可变内容缓存复用，不共享可写文件 | 显示缺失，不伪造 |

迁移器从最后一个可连续验证的阶段停止：若 scene plan 无效，则只写 research、
proposal、script 的 completed checkpoint，scene plan 及后续保持 pending。若成功
构建 production lock，则写 assets `awaiting_human` 和新 creative review。迁移
使用 Project Commit Store；同一 `source_project + migration_version + idempotency_key`
重复请求返回同一新项目，不创建多个副本。

项目创建和 legacy fork 在写项目目录前，还必须进入全局创建 reservation。reservation
存放于 `BACKLOT_DATA_DIR/backlot.db`，表中以 `idempotency_key` 和标准化目标
project ID 分别建唯一索引；`source_project + migration_version` 仅作为非唯一检索
字段，允许用户显式创建多个独立副本。reservation 记录 request digest、目标 project
ID、状态 `reserved | materializing | committed | failed` 和首次响应。创建服务先在
SQLite 事务中占位，再写同级临时目录，完成校验后原子 rename 为目标目录。目录
发布后，在同一个 SQLite 事务中写创建者 owner ACL、reservation committed 状态和
首次响应；项目列表只暴露 committed reservation 对应的目录。若在 rename 后、该
事务前崩溃，恢复器验证目标目录后完成同一事务，不把无 owner 项目暴露给用户。
崩溃重试必须恢复同一 reservation：已 committed 返回
首次响应，materializing 清理或续作其临时目录，request digest 不同返回
`idempotency_conflict`。不得先检查目录是否存在再创建，这种 check-then-create 不能
防止两个 worker 生成重复项目。

## 7. 阶段编辑器规范

### 7.1 参考解析与素材体检

原始 probe、检测结果和抽帧证据不可编辑。运营人员可以：

- 标记素材“优先使用、可用、暂不使用”；
- 补充业务备注；
- 标记品牌/第三方 Logo 是否可用；
- 调整主张边界；
- 选择可借鉴的抽象方法。

这些修改写入新 artifact `research_annotations`，不重写原始
`source_media_review` 或 `video_analysis_brief`。

### 7.2 创意方案

可编辑字段：

- 方案选择；
- 钩子；
- 卖点顺序；
- 叙事结构；
- 预计时长；
- CTA；
- 保留/改变参考方法；
- 素材缺口处理策略。

选择方案或修改 CTA 必须追加对应 decision revision。

### 7.3 口播与字幕

按段显示：旁白、屏幕文案、起止时间、语气、节奏、字数和预计口播时长。

可编辑字段：

- 旁白文字；
- 屏幕文字；
- 段落顺序；
- 语气和速度；
- 字幕字体 profile 和强调词；
- 是否去尾标点。

编辑器必须实时提示：总时长偏差、单条字幕过长、安全区风险和尾句明显加速。
声音试听通过 Agent/资产流程生成，不允许前端直接调用 TTS。

### 7.4 镜头映射

以卡片和可视缩略图展示。可编辑：

- 镜头顺序；
- 自有素材文件；
- source in/out；
- 成片起止时间；
- 速度；
- 裁切和放大；
- 转场；
- 原声/SFX/BGM/旁白安排；
- 是否缺素材。

所有时间范围使用半开区间。提交前必须验证源素材覆盖、无负时长、无时间轴
重叠/空洞、总时长与交付规格一致。

### 7.5 制作准备

显示并允许选择：

- 口播 provider、model、音色、速度；
- BGM 来源和曲目；
- 字幕 profile；
- runtime 与 composition mode 的已批准选择；
- 预计费用；
- 付费生成授权；
- 素材缺口。

修改 runtime、composition mode、provider、voice、BGM、CTA 或关键脚本必须
重新打开 creative lock。

### 7.6 样片确认

播放器支持时间码评论。用户可以：

- 添加普通评论；
- 标记某一时间段需要修改；
- 批准样片；
- 拒绝并提交修改要求；
- 对比最近两个样片版本。

拒绝不删除样片。评论写入追加式 `sample_review`，Agent 根据结构化评论产生下一
版本。

### 7.7 修改与精剪

显示本次变更来源、影响镜头、执行方式、已复用内容、预计时间和费用。运营
人员不得在此直接改变已批准范围；新增要求必须回到草稿与影响预览。

### 7.8 成片生成与交付

显示：

- 生成进度；
- QA 项目及中文结果；
- 分辨率、帧率、准确时长、编码、响度和峰值；
- 黑帧、冻结帧、重复帧和字幕安全区结果；
- 最终视频、备份和交付说明。

失败时显示业务原因和下一步，不显示 stack trace。

## 8. 草稿、影响预览与提交

### 8.1 `OperatorDraft`

```json
{
  "draft_id": "uuid",
  "project_id": "project-id",
  "stage": "script",
  "base_revision": "state-token",
  "base_artifact_hash": "internal-only",
  "adapter": "script-v1",
  "changes": [],
  "created_by": "user-id",
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```

`changes` 使用 adapter 自己的 typed operation，不使用 RFC 6902 JSON Patch。例如：

```json
{"op": "replace_section_text", "section_id": "S04", "text": "新旁白"}
```

### 8.2 草稿保存

- 自动保存不改变生产状态；
- 草稿按用户隔离；
- 同一用户同一阶段只能有一个 active draft；
- 草稿可丢弃；
- 基础版本变化时草稿标记 stale，不能直接提交。

### 8.3 `ImpactPreview`

```json
{
  "draft_id": "uuid",
  "valid": true,
  "summary": "将更新 2 句旁白并重新生成声音，画面保持不变",
  "changed_fields": [],
  "affected_stages": ["口播与字幕", "制作准备", "修改与精剪"],
  "affected_scene_ids": [],
  "render_mode": "保留画面，仅更新声音",
  "reopen_reviews": [],
  "estimated_seconds": 420,
  "estimate_confidence": "low",
  "estimated_cost_usd": 0.06,
  "warnings": [],
  "preview_token": "signed-token"
}
```

预览为纯计算，不写 artifact、不调用 provider、不渲染。`preview_token` 绑定草稿
内容、project、actor、base generation 和过期时间，使用服务端 HMAC-SHA256
签名，默认 15 分钟有效。提交时必须携带该 token，防止用户确认后草稿发生
变化；token 不作为登录或项目授权凭据。

### 8.4 提交事务

所有写入通过 `ProjectCommitStore`。首版只支持单主机、单 Uvicorn worker；每个
项目使用 `fcntl.flock()` 锁定 `operator/project.lock`，Revision Service、Approval
Service、迁移器和 Agent Broker 使用同一把跨进程锁。

新运营项目在 `init_project` 后立即创建 generation 0。已有 fastline 项目首次启用
运营编辑时，在项目锁内从当前已验证 canonical 状态创建 generation 0，并写
`operator-managed` marker。marker 存在后，`write_artifact_atomic()` 和
`write_checkpoint()` 必须接收有效 Project Commit context；没有 context 的外部写入
被拒绝。未启用运营编辑的 legacy/普通 pipeline 保持现有写入行为。

#### 8.4.1 Transaction-aware writer 合同

现有 writer 不得在运营项目中各自执行临时文件加 `os.replace()`。新增
`ProjectWriteSink` 协议，负责收集逻辑写集并把实际落盘交给
`ProjectCommitStore`：

```python
class ProjectWriteSink(Protocol):
    project_id: str
    generation_id: str

    def stage_json(self, relative_path: str, value: object, *, schema: str) -> None: ...
    def stage_bytes(self, relative_path: str, source_path: Path, *, media_type: str) -> None: ...
    def stage_delete(self, relative_path: str) -> None: ...
    def append_event(self, stream: str, event: object) -> None: ...
```

以下现有公共写入口必须增加关键字参数 `sink: ProjectWriteSink | None`：

- `write_artifact_atomic(..., sink=...)`；
- `write_checkpoint(..., sink=...)`；
- `build_approval_bundle(..., sink=...)`、`approve_bundle(..., sink=...)`、
  `reject_bundle(..., sink=...)` 和 `reconcile_bundle(..., sink=...)`；
- `append_decision_revision(..., sink=...)`。

`reconcile_bundle()` 当前兼有检查和 superseded 写入，必须拆出纯函数
`inspect_bundle_reconciliation()` 返回 `unchanged | supersede` 及目标内容；原
`reconcile_bundle()` 保留为兼容包装，只有收到 `supersede` 时才经 sink 写入。
`operator-managed` 项目禁止直接调用内部 `_write_bundle()`；后续若新增 expire 等
审批状态，也必须复用同一 sink 合同，不能增加旁路 writer。

writer 仍负责 schema、业务规则、路径 containment 和语义 hash；sink 只负责事务
写集、before/after image、提交与恢复。具体规则如下：

1. 非 `operator-managed` 项目允许 `sink=None`，保持现有原子写行为；
2. `operator-managed` 项目若 `sink=None`，立即返回
   `operator_transaction_required`，不得降级为直接写；
3. sink 的 `project_id`、generation 和当前锁上下文必须与目标项目一致，否则返回
   `invalid_write_context`；
4. writer 只能向 sink 提交项目相对路径，不得把绝对路径、symlink target 或临时
   目录暴露给调用方；
5. 同一事务内 artifact、checkpoint、approval bundle、decision revision、
   production lock 和 review transition 必须进入同一 write-set；
6. writer 不得自行发布 SSE、写审计或终结 draft；这些副作用写入 generation 的
   durable outbox，在 commit point 后统一物化；
7. 测试必须证明任一 writer 在 prepare、apply、pointer swap 和 outbox drain 处
   崩溃后，只能观察到完整旧状态或完整新状态。

Revision Service、Approval Service、迁移器、pipeline worker 和 Agent Broker 只能
通过 `ProjectCommitStore.transaction(...)` 获得 sink。事务外不得构造可用 sink；
`ProjectWriteSink` 的实现类不从 Backlot API 导出。

提交采用 immutable generation + atomic pointer：

```text
operator/generations/<generation-id>/
  manifest.json        base、write-set、action、result、audit、draft transition
  before/              旧文件或 missing marker
  after/               已完整验证的新文件
  status               prepared | applying | applying-complete | committed | aborted
operator/current-generation.json
```

提交顺序固定为：

1. 校验登录、权限、CSRF、项目 containment、idempotency key 和 preview token；
2. 获取项目锁，重新读取 `current-generation` 与基础 artifact；
3. adapter 在内存应用修改并执行 schema/业务验证；
4. 在 generation 中写完整 before-image、after-image、write-set、业务 diff 和
   durable outbox。outbox 在 pointer 提交前即固化 action ID、idempotency key/request
   digest/result、audit event 和 draft terminal transition；
5. fsync generation，状态写为 `prepared`；
6. 将 after-image 原子 replace 到 canonical artifact/checkpoint/bundle/lock/impact；
7. 逐文件核对 after hash，状态写为 `applying-complete`；
8. 原子 replace `current-generation.json`，这是新版本对 reader 可见的唯一 commit
   point；
9. 状态写为 `committed`，在项目锁内幂等 drain durable outbox；
10. outbox materializer 将 audit/idempotency/draft transition 写入查询索引，每项以
   `action_id + event_type` 唯一；
11. 释放项目锁并只发布一次 SSE change。

Reader 不直接把正在变化的 canonical 文件当作运营状态。存在 active intent 或
canonical hashes 尚未匹配 pointer 时，Operator Projection 从 pointer 指向的
generation snapshot 返回最后一个已提交状态。项目 watcher 发现 active intent 时
只标记 dirty，不发布；commit/abort 后由 ProjectCommitStore 主动 invalidates cache
并发布一次。

generation 保存 control-plane JSON、checkpoint、review 和小型 pointer，不复制大
视频。Broker 工具先写入 `operator/jobs/<job-id>/outputs/`，校验后移动到不可变的
内容寻址 asset 或 `renders/versions/` 路径；已提交媒体路径永不覆盖。
`renders/final.mp4` 是可重新物化的交付别名，generation 只记录其前后 versioned
target。切换别名使用同目录临时文件和原子 replace，崩溃恢复从 immutable target
重新物化，不保存整份视频 before-image。

崩溃恢复固定为：

- pointer 未指向 generation：在项目锁内按 before-image rollback，校验旧 hash，
  写 `aborted`；
- pointer 已指向 generation：按 after-image roll-forward，校验新 hash，写
  `committed`，然后幂等 drain generation 内的 durable outbox；
- rollback/roll-forward 可重复执行；重复 idempotency key 返回首次已提交结果；
- before/after hash 均不匹配时停止自动恢复并将项目标记“需要管理员恢复”，不得
  猜测覆盖方向。

generation manifest 是 audit、idempotency result 和 draft terminal state 的权威
记录。`operator/actions.jsonl`、SQLite 查询表和 draft 文件中的 terminal 标记只是
可重建投影；即使 pointer 提交后、outbox drain 前崩溃，reader 也从 committed
manifest 得到正确结果。新的 mutation 在获取项目锁后先恢复和 drain 旧 generation，
再查所有 committed manifest 的 idempotency key，因此不会生成第二次提交。

每个可能的 crash point 都必须有故障注入测试。symlink 在准备阶段和 replace 前
各做一次 containment 检查；项目目录、artifact 目录和 generation 目录不得通过
symlink 逃逸。

若文件系统监测到 operator-managed 项目存在不属于任何 generation 的外部变化，
运营状态冻结在最后一个 committed generation，显示“检测到外部修改，需要管理员
处理”。管理员只能选择：将外部状态校验后导入为新 generation，或从当前
generation 重新物化 canonical；系统不得自动吞并未知改动。

## 9. 版本、比较、恢复和分支

### 9.1 版本存储

```text
projects/<id>/operator/
  drafts/<user>/<stage>.json
  revisions/<artifact>/<sequence>-<revision-id>.json
  generations/<generation-id>/...
  current-generation.json
  reviews/*.json
  actions.jsonl
  agent/events.jsonl
  agent/session.json
  skill-snapshot/...
```

revision 必须包含：`revision_id`、`parent_revision_id`、`artifact_name`、
`base_semantic_sha256`、`result_semantic_sha256`、actor、reason、timestamp、完整
snapshot 和业务差异摘要。

### 9.2 比较

版本比较由 artifact adapter 生成业务差异，不在运营界面显示 JSON diff。例如：

- “S04 旁白：旧文案 -> 新文案”；
- “SC08 source out：15.2s -> 16.0s”；
- “BGM：108 BPM 曲目 A -> 曲目 B”。

### 9.3 恢复

恢复历史版本创建新的 revision，parent 指向当前版本，并将历史内容作为新结果。
恢复前同样显示 ImpactPreview。

### 9.4 从历史创建分支

分支操作创建新的 project workspace：

- 新项目记录 `parent_project_id` 和 `parent_revision_id`；
- canonical artifact 按选定 revision 重新 envelope；
- 选定 revision 后的 checkpoint 不复制；
- source media 和生成资产通过不可变内容缓存复用，不共享可写文件；
- 新分支拥有独立 approval、revision、audit 和 Agent session。

## 10. 冲突处理

### 10.1 冲突检测

草稿保存时记录 `base_revision`。预览或提交时当前版本不同，则比较草稿 touched
fields 与新版本 changed fields：

- 无交集：允许自动 rebase 后重新预览；
- 有交集：返回 `409 conflict` 和字段级差异；
- 无 adapter 比较能力：整阶段视为冲突。

### 10.2 冲突界面

每个冲突字段提供：

- 保留我的修改；
- 采用当前版本；
- 文本字段手动合并；
- 放弃整个草稿。

解决冲突后生成新草稿和新 ImpactPreview。不得复用旧 preview token。

## 11. 审批服务

### 11.1 `OperatorReview`

```json
{
  "review_id": "project-creative_lock-v3",
  "project_id": "project",
  "kind": "creative_lock",
  "subject_id": "bundle-id",
  "subject_version": 3,
  "subject_hash": "internal-hash",
  "status": "awaiting_human",
  "submitted_by": "user-id",
  "decided_by": null,
  "reason": null,
  "created_at": "timestamp",
  "decided_at": null
}
```

`kind` 为 `creative_lock | sample`。状态迁移只有：

```text
awaiting_human -> approved | rejected | superseded
```

terminal review 不修改。内容变化、拒绝后重做或恢复版本都创建新 review ID 和
递增 subject version。`pending_review` 是当前唯一 `awaiting_human` review 的运营
投影。

### 11.2 Creative Lock

creative review 绑定现有 approval bundle ID、bundle version 和 semantic hash。
批准在项目锁内先执行 expected version/hash stale check，再调用扩展后的
`approve_bundle(..., expected_version, expected_hash)`，然后将 assets terminal
checkpoint 写为 `completed`、`human_approved=true`，最后将 review 写为 approved。

拒绝同样在项目锁内调用扩展后的 `reject_bundle()`，将 review 写为 rejected，
但不向 checkpoint schema 添加 `rejected` 状态。当前 assets checkpoint 归档到
history，当前文件移除，使 assets 从 manifest 派生为 pending；拒绝原因保存在
review。Milestone 2 必须允许运营人员直接打开对应 typed draft，根据拒绝意见手工
修改并提交下一版 bundle 和新 creative review；Milestone 3 上线后，Agent 修改只是
可选加速路径，不是拒绝流程的前置依赖。

### 11.3 Sample

sample review 绑定 `sample_report` revision、sample output hash 和当前 sample
checkpoint hash。

- 批准：expected revision/hash 通过后，将 sample checkpoint 从
  `awaiting_human` 写为 `completed`、`human_approved=true`，review 写为 approved。
- 拒绝：review 写为 rejected，当前 sample checkpoint 归档并移除，sample 从
  manifest 派生为 pending；样片文件和 sample revision 保留。Milestone 2 提供
  typed draft 让运营人员手工调整时间码评论对应的字幕、音频和剪辑参数并提交下一
  版；Milestone 3 可由 Agent 根据相同结构化评论提出修改，但不得成为唯一恢复路径。

### 11.4 重复与竞态

- 相同 idempotency key 重复 approve/reject 返回首次结果；
- 同一 awaiting review 的两个 approve 请求只有一个成功，另一个返回相同终态；
- approve 与 reject 竞态中，先提交者获胜，后者返回 `409 review_already_decided`；
- subject version/hash 不匹配返回 `409 review_stale`；
- stale check、bundle mutation、checkpoint transition 和 review transition 必须在
  同一个 Project Commit Store generation 中提交。

### 11.5 自审策略

按已确认产品决策，首版允许提交人批准自己的内容。所有批准必须记录
`approved_by`、时间、版本和当时 artifact hashes。管理员可将项目策略改为
`reviewer_required`，但默认值为 `allow_self_approval=true`。

### 11.6 防止旧批准误用

批准 API 必须携带 bundle/version 或 sample revision。若当前内容已变化，返回
`409 review_stale`，要求刷新，不得批准旧页面中的版本。

## 12. Agent Bridge

### 12.1 接口

```python
class AgentBridge(Protocol):
    def start(self, request: AgentRequest) -> AgentJob: ...
    def resume(self, session_id: str, request: AgentRequest) -> AgentJob: ...
    def cancel(self, job_id: str, actor: User) -> None: ...
    def status(self, job_id: str) -> AgentJobState: ...
```

`AgentRequest` 必须包含 project ID、Skill ID/version、用户消息、引用对象、基础
revision、允许动作、预算边界和付费授权状态。

### 12.2 Codex 适配器

首版最低支持 `codex-cli 0.133.0`，启动时通过 preflight 验证 `exec --json`、
`exec resume`、read-only sandbox 和 MCP 配置能力。通过参数数组启动，不得拼接
shell 字符串。初次任务创建持久 session，adapter 从 `thread.started` JSONL 事件
提取 session ID；后续使用 `codex exec resume <session-id>`。

固定约束：

- cwd 可读取 OpenMontage repo，但 sandbox 固定为 `read-only`；
- 不使用 bypass approvals；
- Codex 进程和 stdio MCP proxy 都不接收 provider API key、TTS secret、音乐服务
  secret 或 Backlot session secret，只保留 Codex auth、PATH、locale、单次
  capability token 和最小运行环境；
- provider secrets 只存在于 Backlot 内的 secret-bearing Broker worker。Broker 在
  `tool.execute` 内按 registry dependency 解析 secret，并在该 worker 中调用 tool
  SDK；若具体 tool 需要派生 provider 子进程，只向该子进程注入最小必要 secret。
  secret 不得写入 job env dump、提示词、事件、artifact 或诊断下载；
- Agent sandbox 禁止直接联网；所有外部 provider 调用必须经过 Broker 的
  `tool.execute`，由 Broker 执行 tool allowlist、费用和输出路径检查；
- 强制读取 `AGENT_GUIDE.md`、运营 Skill 和当前 pipeline director；
- 明确 project ID、base revision 和引用卡片；
- 输出使用固定 JSON schema，状态只能为 `completed | needs_input |
  needs_approval | blocked | failed`；
- stdout JSONL 只进入诊断日志，运营事件由 adapter 归一化为中文；
- stderr、命令和 stack trace 不返回运营 UI。

Codex 不能直接写 canonical artifact、checkpoint、revision、media 或 render。它只
能通过带短期 capability token 的 `AgentBroker` MCP 服务执行动作：

| Broker 操作 | 约束 |
|---|---|
| `project.read_context` | 只返回当前项目和授权引用的裁剪上下文 |
| `draft.propose` | 返回 typed adapter operations，不提交 |
| `tool.execute` | 只允许 run authorization 列出的 registry tool、预算和输出路径 |
| `stage.commit` | 只允许 manifest 当前 stage 的 declared artifacts，经 schema 和 Project Commit Store 提交 |
| `review.request` | 只创建 `needs_approval`，不能自批 |
| `job.progress` | 写入受限运营进度事件 |

每个 Agent job 的 run authorization 绑定 project、Skill digest、base generation、
允许 stage、允许 tools、预算、付费批准、过期时间和 nonce。Broker 服务端强制
验证，提示词中的 `allowed_actions` 不作为安全边界。capability token 只能授权该
project、stage、tool allowlist、预算和 expected generation，不能兑换或读取 provider
secret。

每次 `stage.commit` 必须携带 authorization 中的 `expected_generation`。Broker 在
项目锁内执行 compare-and-swap：若当前 generation 不一致，提交不落盘，job 转为
`needs_input` 并返回中文冲突摘要和刷新链接，不得自动 rebase、覆盖人工提交或重放
tool side effect。若提交成功，旧 nonce 立即消费，Broker 服务端签发只绑定新
generation 的下一枚单次 capability token，并仅放入该 job 的受限内存；后续 commit
必须使用新 token。token chain 任一环过期、重复使用、跨 stage 或跨 generation 都
返回 `authorization_stale`。只读调用可继续使用 job authorization，但不得据此提交。

若 pointer 已提交、旧 nonce 已消费，但新 token 尚未返回时进程崩溃，resume 先用
idempotency result 确认上次 commit 已成功，再读取 current generation，由 Broker
签发绑定该 generation 的新 nonce；不得重放 commit 或由客户端推导 token。该窗口
必须有故障注入测试。

Broker 使用明确的两段式 IPC，不监听 TCP：Codex 只连接每个 job 的无 secret
stdio MCP proxy；Backlot 在启动 proxy 前创建一对已连接的 Unix `socketpair`，将
一端作为预打开 FD 交给 proxy，另一端由 secret-bearing Broker worker 持有。proxy
只校验 JSON-RPC framing、大小和 request ID，并通过该 FD 转发；它不加载 registry、
`.env` 或 provider SDK，也不能连接任意 socket。Broker worker 校验 capability token
后才执行 registry tool、事务写入和结果脱敏。capability token 只存在于该 job 的
受限环境和内存，不写入项目日志；job 结束、取消或超时后 nonce 立即失效。

自然语言修改默认只运行到 `draft.propose`。用户必须经过 ImpactPreview 和 commit
才改变生产状态。已批准的 pipeline 执行可以调用 `tool.execute` 和
`stage.commit`；Broker 是唯一 side-effect/write 边界，并复用现有 registry、
artifact writer、checkpoint writer 和 Project Commit Store。

资源限制：提案任务默认 20 分钟超时；生产任务不得超过 pipeline manifest 的
`max_wall_time_minutes`；单条 JSONL 上限 1 MiB，单 job 诊断日志上限 50 MiB。
取消时终止整个进程组，先 SIGTERM，10 秒后仍未退出才 SIGKILL。服务重启时，
没有活动进程句柄的 running job 标记为 interrupted；保留 session ID，用户重试
时通过 resume 恢复，不自动重复提交 side effect。

### 12.3 并发

每个项目同一时间只允许一个 active Agent job。新消息在 job 运行时进入有序队列；
用户可以取消当前 job。AgentBroker 的 mutation 同样获取项目锁；取消只终止 Agent
进程，不回滚已经由 Project Commit Store 原子提交的 generation，也不删除已认证
artifact。

### 12.4 引用

右侧对话可引用：

- 当前阶段；
- 方案卡片；
- 脚本段；
- 镜头卡片和时间段；
- 素材版本；
- 样片时间码评论；
- QA 失败项。

引用使用内部稳定 ID，不把整份 artifact 或绝对路径拼入用户可见消息。

### 12.5 付费与重大决策

Backlot 消息不构成 provider、model、runtime、composition mode 或付费调用的
隐式批准。Agent 需要重大决策时返回 `needs_approval`，UI 展示选项、推荐、费用
和影响，用户批准后才 resume session。

## 13. 身份、权限与安全

### 13.1 部署边界

首版支持 loopback 或可信内网单团队，不支持公网裸露。非 loopback 监听必须显式
配置允许的 host/origin，并在启动时显示安全警告。

### 13.2 用户存储

用户、角色和 session 存储在 `BACKLOT_DATA_DIR/backlot.db`，默认
`BACKLOT_DATA_DIR=<repo>/.backlot`；该目录已 gitignore，不进入项目 artifact。
使用标准库 `sqlite3`。

密码使用 `hashlib.scrypt`、每用户随机 salt 和常量时间比较。首个管理员通过
`python -m backlot users create-admin` 创建，不提供默认密码。没有任何用户时：

- loopback 只开放一次性初始化页面；
- 非 loopback 拒绝启动；
- 管理员创建成功后初始化页面永久关闭。

### 13.3 角色

| 角色 | 权限 |
|---|---|
| operator | 建单、编辑、预览影响、提交、评论、启动 Agent、按项目策略批准 |
| reviewer | operator 能力上限，并可在获得 ACL 的项目中审核和拒绝 |
| admin | reviewer 权限、用户管理、Skill 发布、诊断视图和系统设置 |

上述是系统角色，只决定能力上限；非 admin 用户还必须通过项目 ACL 才能访问具体
项目。项目 ACL 存储于 `backlot.db`，角色固定为：

| 项目角色 | 项目内权限 |
|---|---|
| owner | 管理成员、编辑、提交、启动 Agent、批准/拒绝、分支和归档 |
| editor | 查看、编辑、提交、启动 Agent 和创建 review，不能管理成员 |
| reviewer | 查看、评论、批准和拒绝，不能修改内容或启动生产 |
| viewer | 只读业务视图、版本、媒体和进度 |

项目创建人默认成为 owner。有效权限取“系统角色能力上限”和“项目 ACL”交集；admin
拥有全局访问和恢复权限，但每次跨项目访问仍写审计。系统 reviewer 不自动获得所有
项目内容，只有 admin 或显式 ACL 才能访问。

所有项目入口必须使用同一个 `authorize_project(actor, project_id, action)`：
`/projects` 列表只返回可访问项目；operator-state、草稿、版本、review、Agent、SSE、
media、thumbnail 和兼容 state API 均执行相同授权，不能只在页面路由过滤。fork
默认只给发起人新项目 owner 权限，不继承源项目成员；发起人无源项目 read 权限时
不得 fork。成员变更使用 idempotency、CSRF 和审计合同，最后一个 owner 不可移除。

### 13.4 Web 安全

- session cookie：HttpOnly、SameSite=Strict；HTTPS 时必须 Secure；
- 除 `/api/health`、静态登录资源和首次 loopback 初始化外，所有项目列表、项目
  页面、GET API、SSE、media、thumbnail、library 和诊断接口都要求 session；
- legacy raw state、原始事件和诊断接口仅 admin 可访问；operator 只能访问
  `/api/v2` 业务投影；
- media/thumb 必须同时验证 session、项目访问权和 contained path；
- 所有 mutation API 要求 session CSRF token 和同源 Origin；
- `/api/v2/auth/login` 是 CSRF token 的唯一例外，但必须校验 Origin/Host、限制
  频率并返回统一失败消息；logout 仍要求 CSRF；
- SSE 使用 session cookie，只允许同源连接；
- 登录和 Agent 请求进行速率限制；
- project ID、artifact、revision、media path 必须 containment 校验；
- API 错误不回显秘密、环境变量、命令或绝对路径；
- subprocess 使用参数数组和受限 cwd/env；
- 管理员诊断下载需要再次验证 admin session。

## 14. 运营 Skill 目录

### 14.1 文件结构

```text
skills/catalog/ecommerce-viral-remix/
  index.yaml
  versions/
    1.0.0/
      skill.yaml
      SKILL.md
      intake.schema.json
      profiles/
        home-protection.yaml
        beauty.yaml
        food.yaml
      examples/
        transparent-table-mat.yaml
```

该目录属于 OpenMontage Layer 2 用户可见包装，内部映射到
`pipeline_defs/cinematic-fast.yaml` 和现有 stage director，不替代它们。

版本目录不可变。相同 `id + semver` 再次注册时，若内容 digest 不同必须拒绝；
任何修改都需要新 semver。`index.yaml` 只记录 repo 内可发现版本、digest 和建议
默认版本，不包含运行时 lifecycle 或用户分配。

### 14.2 `skill.yaml`

必填字段：

```yaml
id: ecommerce-viral-remix
version: 1.0.0
name_zh: 电商爆款复刻
description_zh: 使用参考方法和自有真实素材制作原创商品短视频
pipeline: cinematic-fast
supported_platforms: [douyin, wechat_channels, xiaohongshu]
default_profile: home-protection
approval_policy: two_gate
intake_schema: intake.schema.json
benchmark_policy: cinematic-fast
```

Skill manifest 使用独立 JSON Schema 校验。缺失 pipeline、不存在 profile 或未在
`index.yaml` 注册的 version 不得进入运行时 registry。生命周期 status 和实际
benchmark refs 存储在 `backlot.db.skill_versions`，不写入 repo 的 `index.yaml` 或
immutable `skill.yaml`；`skill.yaml` 只声明稳定的 benchmark policy。

创建项目时解析并校验 Skill、intake schema 和 profile，然后将完整 resolved
snapshot 复制到 `projects/<id>/operator/skill-snapshot/`，记录 digest。Agent 和
项目恢复始终读取 snapshot，不读取 catalog 的浮动 current version。retired 版本
不允许新建项目，但旧项目 snapshot 继续可用。

`intake_schema`、profile、example 和 SKILL 路径必须是当前 immutable version
目录内的相对 contained path，禁止绝对路径、`..` 和 symlink 逃逸。

### 14.3 建单表单

必填：商品、品类、平台、目标时长、参考素材、自有素材、版权确认、品牌/CTA。

可选：口播、字幕、BGM、预算、截止时间、禁用表达、付费补素材授权。

未授权付费补素材时，Agent 只能报告缺口和免费/已有素材路径，不能自动调用
provider。

### 14.4 发布状态

- `draft`：仅管理员可见；
- `trial`：指定测试用户可见；
- `published`：运营入口可见；
- `retired`：不可新建项目，旧项目仍按锁定版本运行。

功能发布必须满足 schema、合同测试、黄金样例、集成测试和管理员批准。状态迁移
只有 `draft -> trial -> published -> retired`；只有 admin 可以迁移，状态和
benchmark refs 写入 `backlot.db.skill_versions`。trial 用户/团队分配存储在
`backlot.db.skill_access`，不修改 repo 文件或版本目录。Benchmark cohort 是发布
性能承诺的条件；没有 cohort 时可以发布功能，但 UI 只能显示“实测数据不足”，
不能显示 SLA。

## 15. HTTP 与事件接口

### 15.1 认证

| Method | Path | 行为 |
|---|---|---|
| POST | `/api/v2/auth/login` | 登录并创建 session |
| POST | `/api/v2/auth/logout` | 注销当前 session |
| GET | `/api/v2/auth/me` | 当前用户、角色、CSRF token |

### 15.2 项目与 Skill

| Method | Path | 行为 |
|---|---|---|
| GET | `/api/v2/skills` | 可用运营 Skill |
| GET | `/api/v2/projects` | 当前用户有 ACL 的项目列表 |
| POST | `/api/v2/projects` | 按 Skill 建单 |
| GET | `/api/v2/projects/{id}/operator-state` | 运营状态 |
| POST | `/api/v2/projects/{id}/fork-fastline` | 从 legacy 项目创建快线运营副本 |
| GET | `/api/v2/projects/{id}/members` | 项目成员与角色 |
| PUT | `/api/v2/projects/{id}/members/{user-id}` | owner 设置项目角色 |
| DELETE | `/api/v2/projects/{id}/members/{user-id}` | owner 移除项目成员 |

### 15.3 草稿与版本

| Method | Path | 行为 |
|---|---|---|
| PUT | `/api/v2/projects/{id}/drafts/{stage}` | 创建或保存当前用户草稿 |
| DELETE | `/api/v2/projects/{id}/drafts/{stage}` | 丢弃草稿 |
| POST | `/api/v2/projects/{id}/drafts/{stage}/impact` | 计算影响预览 |
| POST | `/api/v2/projects/{id}/drafts/{stage}/commit` | 提交新版本 |
| GET | `/api/v2/projects/{id}/versions/{artifact}` | 版本列表 |
| GET | `/api/v2/projects/{id}/versions/{artifact}/compare` | 业务差异 |
| POST | `/api/v2/projects/{id}/versions/{artifact}/{rev}/restore` | 恢复为新版本 |
| POST | `/api/v2/projects/{id}/versions/{artifact}/{rev}/fork` | 创建项目分支 |

### 15.4 审批与 Agent

| Method | Path | 行为 |
|---|---|---|
| POST | `/api/v2/projects/{id}/reviews/{review-id}/approve` | 批准当前版本 |
| POST | `/api/v2/projects/{id}/reviews/{review-id}/reject` | 拒绝并写入反馈 |
| POST | `/api/v2/projects/{id}/agent/messages` | 发送带引用的消息 |
| POST | `/api/v2/projects/{id}/agent/jobs/{job-id}/cancel` | 取消运行任务 |
| GET | `/api/v2/projects/{id}/events` | 运营 SSE 事件 |

原 `/api/project/{id}/state` 与现有 SSE 在兼容期保留，仅诊断页使用。

### 15.5 Mutation 通用合同

所有 POST/PUT/DELETE mutation 请求必须携带：

- `Idempotency-Key`；
- session CSRF header；
- `base_revision` 或 expected subject version；
- 用户可见的 `reason`，批准动作可使用固定原因；
- JSON body schema version。

成功响应统一返回 `action_id`、`result_revision`、`status` 和 `links`。重复
idempotency key 且请求 digest 相同，返回首次响应；digest 不同返回
`409 idempotency_conflict`。错误码固定至少包括：`auth_required`、`forbidden`、
`csrf_failed`、`validation_failed`、`revision_conflict`、`review_stale`、
`review_already_decided`、`job_running`、`authorization_stale`、
`operator_transaction_required`、`invalid_write_context`、`recovery_required`。

## 16. 事件模型

运营 SSE 事件固定为：

- `project.updated`；
- `draft.saved`；
- `impact.ready`；
- `revision.committed`；
- `review.required`；
- `review.completed`；
- `agent.queued`；
- `agent.progress`；
- `agent.needs_input`；
- `agent.needs_approval`；
- `agent.completed`；
- `agent.failed`；
- `render.progress`；
- `qa.completed`。

事件 payload 只包含中文 message、稳定业务 ID、进度和操作链接。原始工具事件只
进入诊断视图。

## 17. 错误与恢复

| 条件 | HTTP/状态 | 运营提示 | 后续动作 |
|---|---|---|---|
| 草稿基线过期 | 409 | 内容已有新版本 | 查看并解决冲突 |
| 审批版本过期 | 409 | 待确认内容已经变化 | 刷新最新版本 |
| schema/业务校验失败 | 422 | 指出具体字段和修复建议 | 保留草稿 |
| Agent 已运行 | 409/queued | 已加入下一条修改 | 等待或取消当前任务 |
| Agent 进程失败 | failed | 本次处理未完成，已有结果未丢失 | 重试或查看诊断 |
| provider 需批准 | needs_approval | 显示选项、费用和影响 | 用户批准后恢复 |
| revision intent 未完成 | recovery | 正在恢复上次提交 | 服务启动自动恢复 |
| legacy artifact 缺失 | degraded | 旧项目没有该结构化记录 | 创建快线运营副本或继续只读 |
| operator-managed 外部写入 | frozen | 检测到外部修改 | 管理员导入或恢复已提交版本 |

任何错误都不得清除草稿、最后一个已提交 revision 或已认证 final video master。

## 18. 兼容与迁移

### 18.1 API 兼容

现有 GET API、library 页面和诊断页至少保留一个 minor release。新运营 UI 只调用
`/api/v2`。旧 API 不增加 mutation；启用认证后，旧 state/events/media/thumb/
library API 同样要求 session，raw state/events 仅 admin 可访问。

### 18.2 Legacy 项目

迁移采用第 6.3 节的“创建快线运营副本”，不在页面加载时改写原项目。预览列出
新项目 ID、逐 artifact 处理方式、停止迁移的首个无效阶段、无法继承的批准和
必须重新确认的内容。原项目在迁移成功或失败后都保持不变。

### 18.3 Pipeline 兼容

首版运营编辑只对 `cinematic-fast` 开启。其他 pipeline 继续使用只读业务摘要，
直到各自实现 typed adapter。不得用通用 JSON 编辑器临时覆盖。

## 19. 可观测性与审计

### 19.1 运营指标

- 建单完成时间；
- 各阶段停留时间；
- 草稿到提交耗时；
- 冲突率；
- 自审/复核比例；
- 影响预览后的取消率；
- cold/warm/audio-only 实际时长；
- cache reuse 和避免的费用；
- Agent needs_input/needs_approval 次数；
- 各类修改的返工范围。

### 19.2 审计事件

登录、建单、编辑提交、批准、拒绝、恢复、分支、Agent 请求、取消、Skill 发布、
用户管理和诊断下载必须记录 actor、时间、项目、版本、action 和结果。审计日志
append-only，运营用户不能删除。

### 19.3 隐私

审计不记录密码、session token、API key、完整环境变量、TTS secret、Codex auth
或上传文件内容。Agent 对话按项目保存，并允许管理员按保留策略清理；清理动作
本身进入审计。

## 20. 测试规范

### 20.1 单元测试

- 每个阶段 projection 的中文字段和 legacy fallback；
- typed adapter 的允许/拒绝字段；
- 半开时间范围、时长和字幕校验；
- impact preview 的 `no_render/mux_only/full_render`；
- revision append、compare、restore、fork；
- bundle 失效和 stale approval；
- base revision rebase/conflict；
- `evaluate_change_impact()` 决策表及旧分类器一致性；
- auth、scrypt、session、CSRF、系统角色与项目 ACL 交集；
- `ProjectWriteSink` 在运营项目拒绝无事务写入，legacy 行为保持兼容；
- Codex JSONL parser、session ID、输出上限、未知事件、超时和取消；
- AgentBroker capability token、generation token chain、允许 stage/tool/write-set、
  预算边界和 provider secret 隔离。

### 20.2 API 测试

- 未登录、错误角色、缺失 CSRF、错误 Origin；
- project/path traversal；
- stale preview token；
- 同项目并发提交；
- 每个 generation 步骤的 crash rollback/roll-forward 和重复恢复；
- 跨进程锁、symlink/TOCTOU、reader 不观察部分状态、watcher 单次发布；
- self-approval 审计、双击批准和 approve/reject 竞态；
- Agent 单项目互斥和消息队列；
- 人工提交抢先时 Agent `stage.commit` 转为 `needs_input`，不得自动覆盖；
- pointer commit 后、token 返回前崩溃，resume 换发新 token 且不重复 commit；
- Agent 试图绕过 broker、越权 stage/tool/path 和预算；
- Agent 进程环境、stdio proxy、事件和诊断包均不含 provider secret，proxy 不能
  绕过预打开 socketpair 访问 Broker；
- legacy fork migration 的逐 artifact fixture 与幂等性；
- 建单与 legacy fork 并发/崩溃重试只产生一个 reservation 和一个项目目录；目录
  rename 后、ACL 提交前崩溃时项目不可见，恢复后创建者成为 owner；
- owner/editor/reviewer/viewer 对项目列表、state、SSE、media、thumb、fork 和成员
  管理的权限矩阵；
- 旧 GET/SSE/media/thumb/library 的未登录、operator 和 admin 权限矩阵。

### 20.3 UI 合同测试

运营模式扫描可见文本和 accessibility tree，禁止工程术语和内部阶段英文。
运营路由不得创建 raw JSON `<pre>`。验证所有阶段空态、loading、失败、冲突、
待确认和 completed 状态。

### 20.4 浏览器验收

- 桌面 1440x900：完整建单、编辑、影响预览、版本、冲突、批准和 Agent 对话；
- 笔记本 1280x800：无重叠、无截断；
- 移动 390x844：项目查看、评论、批准和视频播放；
- 键盘导航、可见 focus、表单 label、错误关联和对比度；
- SSE 更新不重置正在编辑的草稿。

### 20.5 端到端黄金场景

1. 从透明桌垫素材创建 `cinematic-fast` 项目。
2. 查看参考解析和自有素材卡片，无 raw JSON。
3. 选择方案并修改 CTA，预览显示重开 creative lock。
4. 修改完整旁白，生成新版本并批准 creative lock。
5. 制作并拒绝第一版样片，提交时间码评论。
6. 批准第二版样片并生成成片。
7. 仅修改 BGM 音量，影响预览必须为“保留画面，仅更新声音”。
8. 验证 certified video master hash 不变。
9. 恢复旧脚本，创建新 revision 并重新审批。
10. 从旧版本创建独立项目分支。

### 20.6 Benchmark 与 Flova 对照

- 正常 pipeline 产生 3 cold、5 warm、3 audio-only 独立 run record；
- 未达到 sample floor 时 UI 只显示实测 ETA，不显示 SLA；
- Flova 使用同一 brief、素材、预算和时限；
- 盲评至少覆盖钩子、卖点、可信度、节奏和购买意愿；
- 未获得账号和费用批准前不执行对照生产。

## 21. 发布顺序与完成定义

### Milestone 1：全中文运营只读视图

- 新 projection 和 operator-state API；
- 中文阶段、状态、空态和错误；
- 默认页面无工程信息；
- 管理员诊断页保留现有能力。

发布级别：`internal/trial`，仅指定测试用户使用，不宣称完整运营工作台。

### Milestone 2：结构化编辑与版本

- 草稿、影响预览、typed adapter、revision、比较、恢复；
- creative/sample 审批，以及拒绝后不依赖 Agent 的 typed draft 手工修订；
- Project Commit Store、transaction-aware writers 和崩溃恢复；
- 用户、系统角色、项目 ACL、session、CSRF、审计；
- 全局建单 reservation 和 legacy 快线运营副本迁移。

发布级别：继续 `trial`，完成冲突和崩溃恢复验证后扩大试用。

### Milestone 3：Agent Bridge

- 内置对话、引用、Codex session、进度、取消、needs_input 和
  needs_approval；
- 单项目互斥和冲突处理。

发布级别：`trial`，Agent 只能通过 Broker 写入。

### Milestone 4：运营 Skill

- Skill catalog、建单表单、品类 profile、版本锁和发布状态；
- 透明桌垫黄金样例。

发布级别：Milestone 1-4 的合同、端到端和安全测试全部通过后，功能可以标记
`published`；没有 cohort 时不显示 SLA。

### Milestone 5：发布验收

- 全量测试与浏览器验收；
- 一线运营可用性测试；
- Benchmark cohort；
- 获批后的 Flova 同题对照。

功能发布、SLA 发布和对外比较是三个独立 Gate：Milestone 1-4 通过后可发布
功能；Milestone 5 的对应 sample floor 通过后才发布对应 SLA；真实同题盲评通过
后才允许使用“达到或超过 Flova”的结果表述。

## 22. 实施估算

| 阶段 | 单人工程时间 |
|---|---:|
| 报告、规范、数据合同 | 1-2 天 |
| 中文运营投影和只读 UI | 3-5 天 |
| 编辑、影响、版本、审批、权限 | 6-8 天 |
| Agent Bridge 和内置对话 | 5-7 天 |
| Skill catalog、建单和 profile | 4-6 天 |
| 试用、Benchmark 和对照验收 | 5-8 天 |

单人完整实施预计 5-7 周；两名工程师按后端合同/前端工作台拆分可压缩到约
3-4 周。首个全中文只读版本应在第一周进入 internal/trial，不等待全部功能完成
后一次发布，也不得在此时标记完整功能或 SLA 为 published。

本规范是 umbrella design。实施时必须按 Milestone 1、Milestone 2、Milestone 3、
Milestone 4-5 至少拆成四份独立 implementation plan；每份计划拥有自己的测试、
提交和发布 Gate，不使用一份超大计划并行修改全部子系统。

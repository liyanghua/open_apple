# Backlot Milestone 2 结构化编辑与版本 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Milestone 1 的中文只读工作台升级为具备认证、项目权限、结构化草稿、影响预览、原子提交、版本恢复和人工审批的单机运营工作台。

**Architecture:** 浏览器只提交固定 typed operations；adapter 在内存应用并验证业务合同，所有 canonical 写入经 `ProjectCommitStore` 的 immutable generation 和原子 pointer 提交。认证、ACL、CSRF、幂等、审计和审批共享统一 mutation 上下文；旧 `cinematic` 项目必须 fork 为新的 `cinematic-fast` 运营副本后才能编辑。

**Tech Stack:** Python 3.10、FastAPI、sqlite3、fcntl、hashlib/scrypt/HMAC、JSON Schema Draft 2020-12、原生 JavaScript ES modules、pytest、FastAPI TestClient。

**Spec:** `docs/superpowers/specs/2026-08-15-backlot-operator-workbench-design.md` 第 6-11、13、15-18、21 节。

---

## Chunk 1: 安全合同与提交基础

### Task 1: 定义 M2 wire schemas 与统一业务错误

**Files:**
- Create: `schemas/backlot/operator_draft.schema.json`
- Create: `schemas/backlot/impact_preview.schema.json`
- Create: `schemas/backlot/operator_revision.schema.json`
- Create: `schemas/backlot/operator_review.schema.json`
- Create: `schemas/backlot/mutation_result.schema.json`
- Create: `backlot/operator_errors.py`
- Create: `tests/backlot/test_operator_m2_schemas.py`

- [ ] **Step 1:** 写 schema RED，逐个验证最小合法对象、required、递归 `additionalProperties=false`、非法 operation/review status/error code。
- [ ] **Step 2:** 运行 `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_m2_schemas.py`，确认因 schema 缺失失败。
- [ ] **Step 3:** 实现五个 closed schema；operation 使用按 adapter 绑定的 `oneOf`，禁止自由 JSON Patch。
- [ ] **Step 4:** 实现 `OperatorError(code, message, status_code, field_errors)` 与固定中文安全消息，禁止路径、异常类和响应原文。
- [ ] **Step 5:** 运行 GREEN 和 `tests/backlot/test_operator_state_schema.py` 回归。
- [ ] **Step 6:** 提交 `feat: define Backlot editing contracts`。

### Task 2: 建立用户、session、项目 ACL 与 CSRF

**Files:**
- Create: `backlot/auth.py`
- Create: `backlot/auth_store.py`
- Create: `backlot/ui/login.html`
- Create: `backlot/ui/operator/login.js`
- Modify: `backlot/__main__.py`
- Modify: `backlot/server.py`
- Create: `tests/backlot/test_auth_store.py`
- Create: `tests/backlot/test_auth_api.py`

- [ ] **Step 1:** 写 SQLite 迁移、scrypt 密码、session 过期、系统角色和项目 ACL 的 RED；覆盖最后一个 owner 不可移除。
- [ ] **Step 2:** 写 `users create-admin` CLI RED，要求无默认密码、重复用户名失败且不打印秘密。
- [ ] **Step 3:** 实现 `BACKLOT_DATA_DIR/backlot.db`、参数化 SQL、随机 salt/session/CSRF、常量时间比较。
- [ ] **Step 4:** 实现 `Actor`、`authorize_project(actor, project_id, action)` 和权限交集；admin 跨项目仍产生日志事件。
- [ ] **Step 5:** 实现 login/logout/me；cookie 为 HttpOnly、SameSite=Strict，HTTPS 时 Secure；login 校验 Host/Origin 并限速。
- [ ] **Step 6:** 首个用户不存在时仅 loopback 开放初始化页，非 loopback 启动失败；创建 admin 后永久关闭初始化。
- [ ] **Step 7:** 为测试提供显式 `BACKLOT_AUTH_MODE=test` fixture，不在生产代码保留免认证后门。
- [ ] **Step 8:** 运行认证/CLI/旧 GET 回归并提交 `feat: secure Backlot users and project access`。

### Task 3: 实现 ProjectCommitStore generation、pointer 与恢复

**Files:**
- Create: `backlot/project_commit.py`
- Create: `backlot/project_write_sink.py`
- Create: `schemas/backlot/generation_manifest.schema.json`
- Create: `tests/backlot/test_project_commit.py`
- Create: `tests/backlot/test_project_commit_recovery.py`

- [ ] **Step 1:** 写 generation 0、项目 `flock`、prepared/applying-complete/committed 状态和 pointer commit point 的 RED。
- [ ] **Step 2:** 定义仅 `ProjectCommitStore.transaction()` 可构造的私有 sink；验证 project ID、generation、锁上下文和相对路径 containment。
- [ ] **Step 3:** 实现 `stage_json/stage_bytes/stage_delete/append_event`，prepare 时固化 before/after、hash、write-set、action result、audit、draft transition 和 durable outbox。
- [ ] **Step 4:** 实现 fsync、canonical apply、after hash 核对、pointer swap、幂等 outbox drain 和一次 SSE publish callback。
- [ ] **Step 5:** 对 prepare、apply、pointer swap、outbox drain 注入故障，断言只能观察到完整旧状态或完整新状态。
- [ ] **Step 6:** 实现启动恢复：pointer 前 rollback、pointer 后 roll-forward、hash 不可判定时 `recovery_required`；每种恢复可重复执行。
- [ ] **Step 7:** 两次检查 symlink containment，并覆盖并发进程争锁测试。
- [ ] **Step 8:** 提交 `feat: add atomic Backlot project commit store`。

### Task 4: 让 canonical writers 感知事务

**Files:**
- Modify: `lib/artifact_io.py`
- Modify: `lib/checkpoint.py`
- Modify: `lib/approval_groups.py`
- Modify: `lib/production_lock.py`
- Create: `tests/lib/test_transaction_aware_writers.py`
- Modify: `tests/lib/test_artifact_io.py`
- Modify: `tests/lib/test_checkpoint_approval_groups.py`
- Modify: `tests/lib/test_production_lock.py`

- [ ] **Step 1:** 写 `operator-managed` marker 下 `sink=None` 返回 `operator_transaction_required` 的 RED；普通项目保持原行为。
- [ ] **Step 2:** 为四个公共 writer 增加 keyword-only `sink=None`，sink 存在时只 stage 逻辑写集，不自行 replace/SSE/audit。
- [ ] **Step 3:** 把 `reconcile_bundle()` 拆为纯 `inspect_bundle_reconciliation()` 加兼容包装。
- [ ] **Step 4:** 扩展 approve/reject 以接收 expected version/hash，stale 时不写任何文件。
- [ ] **Step 5:** 禁止 operator-managed 项目调用 `_write_bundle()`；测试 artifact/checkpoint/bundle/decision revision 同 generation 原子提交。
- [ ] **Step 6:** 运行全部 `tests/lib/test_*artifact*`、checkpoint、approval、production-lock 回归。
- [ ] **Step 7:** 提交 `feat: route canonical writers through project transactions`。

## Chunk 2: 编辑、影响和版本

### Task 5: 建立固定 typed adapters

**Files:**
- Create: `backlot/operator_adapters/__init__.py`
- Create: `backlot/operator_adapters/base.py`
- Create: `backlot/operator_adapters/research.py`
- Create: `backlot/operator_adapters/proposal.py`
- Create: `backlot/operator_adapters/script.py`
- Create: `backlot/operator_adapters/scene_plan.py`
- Create: `backlot/operator_adapters/assets.py`
- Create: `backlot/operator_adapters/sample.py`
- Create: `tests/backlot/test_operator_adapters.py`

- [ ] **Step 1:** 为每阶段列出的 allowed operation 写参数化 RED；未知 op/field、raw path/hash、RFC6902 必须拒绝。
- [ ] **Step 2:** 实现 `load_snapshot/apply/validate/diff/touched_fields` 接口与显式 registry，不允许动态任意表单。
- [ ] **Step 3:** research 修改只生成 `research_annotations`，不覆盖 probe/review 原件。
- [ ] **Step 4:** script 校验总时长偏差、字幕长度、安全区、尾句加速；scene plan 校验半开区间、源覆盖、负时长、重叠和空洞。
- [ ] **Step 5:** assets 修改 runtime/mode/provider/voice/BGM/CTA 时输出 creative reopen 信号；sample 用时间码评论映射可编辑音频/字幕/剪辑字段。
- [ ] **Step 6:** adapter diff 只返回中文业务变化，不返回 JSON diff。
- [ ] **Step 7:** 提交 `feat: add typed Backlot stage adapters`。

### Task 6: 草稿服务、冲突和影响预览

**Files:**
- Create: `backlot/operator_drafts.py`
- Create: `backlot/operator_impact.py`
- Create: `lib/change_evaluation.py`
- Create: `tests/backlot/test_operator_drafts.py`
- Create: `tests/backlot/test_operator_impact.py`
- Create: `tests/lib/test_change_evaluation.py`

- [ ] **Step 1:** 写同用户/阶段唯一 active draft、自动保存、丢弃、stale 标记和用户隔离 RED。
- [ ] **Step 2:** 实现项目内 `operator/drafts/<user>/<stage>.json` 原子保存；terminal 状态由 committed generation manifest 投影。
- [ ] **Step 3:** 实现唯一公开 `evaluate_change_impact()`，组合 production-lock diff 与最终 props diff，按规范返回 `no_render/mux_only/full_render` 及 creative/sample reopen。
- [ ] **Step 4:** 实现 adapter touched-fields 冲突：无交集自动 rebase 后要求重预览，有交集 409 字段级差异，无比较能力整阶段冲突。
- [ ] **Step 5:** 实现纯计算 ImpactPreview；ETA/费用无证据为 null，不调用 provider、不渲染、不写 artifact。
- [ ] **Step 6:** 用服务端 HMAC-SHA256 签发 15 分钟 preview token，绑定 draft digest/project/actor/base generation；草稿变化、actor 变化和过期均拒绝。
- [ ] **Step 7:** 提交 `feat: preview typed Backlot draft impact`。

### Task 7: Revision Service、比较、恢复和分支

**Files:**
- Create: `backlot/operator_revisions.py`
- Create: `backlot/project_creation.py`
- Create: `tests/backlot/test_operator_revisions.py`
- Create: `tests/backlot/test_project_creation.py`

- [ ] **Step 1:** 写 append-only revision、parent、before/result semantic hash、actor/reason/snapshot/business diff RED。
- [ ] **Step 2:** 实现 commit draft：重新锁定 base，adapter apply/validate，revision + canonical artifact + checkpoint + review reopen + draft terminal transition 同 generation。
- [ ] **Step 3:** 实现 compare；只调用 adapter business diff。
- [ ] **Step 4:** 实现 restore 为新 revision，必须重新 ImpactPreview，不能移动 current pointer 到历史文件。
- [ ] **Step 5:** 实现 SQLite 创建 reservation，idempotency key 和标准化 project ID 双唯一；临时同级目录物化后原子 rename。
- [ ] **Step 6:** 实现 fork：记录 parent project/revision，重 envelope canonical，小文件/不可变媒体复用，不继承可写目录、成员、批准和 Agent session。
- [ ] **Step 7:** 注入 reservation/rename/owner ACL 事务崩溃并验证恢复不会暴露无 owner 项目。
- [ ] **Step 8:** 提交 `feat: add Backlot revisions restore and project forks`。

### Task 8: Creative 与 Sample Review Service

**Files:**
- Create: `backlot/operator_reviews.py`
- Create: `tests/backlot/test_operator_reviews.py`
- Modify: `backlot/operator_state.py`
- Modify: `schemas/backlot/operator_state.schema.json`

- [ ] **Step 1:** 写 `awaiting_human -> approved|rejected|superseded` 单向状态机和 terminal immutable RED。
- [ ] **Step 2:** 实现 review ID/version/hash 绑定、唯一 pending review、提交人自审默认策略和 reviewer-required 可选策略。
- [ ] **Step 3:** creative approve/reject 在同 generation 内执行 stale check、bundle mutation、assets checkpoint transition 和 review transition。
- [ ] **Step 4:** sample approve/reject 同样绑定 report/output/checkpoint hash；拒绝保留样片和 revision，仅归档并移除当前 checkpoint。
- [ ] **Step 5:** 覆盖 approve/approve、approve/reject 竞态、相同 idempotency replay、不同 digest 冲突和旧页面批准 stale。
- [ ] **Step 6:** projection 的 `pending_review` 只来自唯一 active review，并按权限返回可批准/可拒绝 action。
- [ ] **Step 7:** 提交 `feat: add atomic Backlot creative and sample reviews`。

## Chunk 3: API、迁移与运营界面

### Task 9: Mutation 上下文、幂等与审计

**Files:**
- Create: `backlot/operator_actions.py`
- Create: `backlot/audit.py`
- Create: `tests/backlot/test_operator_actions.py`

- [ ] **Step 1:** 写统一 mutation precondition RED：session、ACL、Origin、CSRF、schema version、Idempotency-Key、reason、base revision。
- [ ] **Step 2:** 实现 request digest；相同 key+digest 返回 committed manifest 首次结果，不同 digest 409。
- [ ] **Step 3:** 成功结果固定 `action_id/result_revision/status/links`；错误使用 Task 1 固定代码和中文安全消息。
- [ ] **Step 4:** 审计事件通过 durable outbox 物化到可重建 SQLite 查询表/JSONL；action+event type 唯一。
- [ ] **Step 5:** 覆盖 pointer commit 后 outbox 前崩溃的重放与无重复 SSE。
- [ ] **Step 6:** 提交 `feat: govern Backlot mutations and audit`。

### Task 10: Legacy 快线运营副本迁移

**Files:**
- Create: `backlot/operator_migration.py`
- Create: `tests/backlot/test_operator_migration.py`

- [ ] **Step 1:** 用透明桌垫 fixture 写迁移表 RED，验证原 legacy 项目字节级不变。
- [ ] **Step 2:** 在 creation reservation 和 ProjectCommitStore 中创建新 `cinematic-fast` 项目、generation 0、owner ACL 和 parent/migration metadata。
- [ ] **Step 3:** 按最后连续有效阶段重新 envelope research/proposal/script/scene plan；不复制旧 hash、sample/edit/compose/publish checkpoint。
- [ ] **Step 4:** asset manifest 仅作为候选，构造 `reuse_only` plan、`paid_generation_approved=false`、新 production lock 和新 awaiting creative review；永不继承旧批准。
- [ ] **Step 5:** media 只引用不可变内容缓存；legacy final 作为历史交付链接，不共享可写文件。
- [ ] **Step 6:** 重复 idempotency 返回同一副本；失败不留下半项目或无 owner 目录。
- [ ] **Step 7:** 提交 `feat: migrate legacy projects into operator fastline copies`。

### Task 11: 暴露 M2 v2 API 并封闭旧工程接口

**Files:**
- Modify: `backlot/server.py`
- Create: `backlot/operator_routes.py`
- Modify: `tests/backlot/conftest.py`
- Create: `tests/backlot/test_operator_mutation_api.py`
- Modify: `tests/backlot/test_operator_api.py`
- Modify: `tests/backlot/test_server.py`

- [ ] **Step 1:** 写 drafts save/delete/impact/commit、versions list/compare/restore/fork、reviews approve/reject、members 和 fork-fastline endpoint RED。
- [ ] **Step 2:** 路由只做 body/schema/auth/mutation context 解析，业务调用对应 service；不得在 route 直接写文件。
- [ ] **Step 3:** 所有 projects/operator-state/SSE/media/thumb/library/legacy API 加统一 session+ACL；诊断/raw state 仅 admin。
- [ ] **Step 4:** v2 SSE 事件固定为中文业务事件；不得回传原始 tool event、path/hash。
- [ ] **Step 5:** 覆盖 auth/ACL/CSRF/Origin/idempotency/revision conflict/error-redaction 矩阵。
- [ ] **Step 6:** 提交 `feat: expose secure Backlot editing APIs`。

### Task 12: 将运营 UI 升级为可编辑工作台

**Files:**
- Modify: `backlot/ui/operator.html`
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/api.js`
- Modify: `backlot/ui/operator/store.js`
- Modify: `backlot/ui/operator/language.js`
- Modify: `backlot/ui/operator/styles.css`
- Create: `backlot/ui/operator/editors.js`
- Create: `backlot/ui/operator/impact.js`
- Create: `backlot/ui/operator/revisions.js`
- Create: `tests/backlot/test_operator_edit_ui_contract.py`

- [ ] **Step 1:** 写静态 UI RED：typed 控件、自动保存、stale/conflict、影响预览、提交、版本比较/恢复、creative/sample approve/reject 中文状态。
- [ ] **Step 2:** API 模块统一携带 CSRF、Idempotency-Key、schema version/base revision/reason；不允许组件直接 fetch。
- [ ] **Step 3:** store 管理 server snapshot、active draft、dirty fields、preview token、conflict 和 pending review；SSE 更新不覆盖未提交输入。
- [ ] **Step 4:** editors 按固定 editor type 渲染 input/textarea/select/checkbox/slider；不从任意字段动态生成表单。
- [ ] **Step 5:** script 实时显示时长/字幕/安全区/尾句风险；shot editor 验证时间轴和素材范围；assets 变更显示重审批提示。
- [ ] **Step 6:** 提交前必须显示中文影响摘要、涉及阶段、渲染方式、费用/时间证据和 warnings；内容变化使旧 preview token 失效。
- [ ] **Step 7:** review 区支持批准、拒绝原因、typed draft 修订入口和最近两版样片对比；拒绝不依赖 Agent。
- [ ] **Step 8:** 390/1280/1440 无溢出，错误/DOM/accessibility name 无 JSON、hash、path、内部阶段值。
- [ ] **Step 9:** 提交 `feat: enable typed editing in Backlot operator UI`。

## Chunk 4: M2 发布 Gate

### Task 13: 安全、崩溃和端到端验收

**Files:**
- Create: `tests/integration/test_backlot_operator_editing.py`
- Create: `tests/backlot/test_operator_security.py`
- Create: `tests/backlot/test_operator_crash_matrix.py`
- Modify: `backlot/README.md`

- [ ] **Step 1:** 端到端覆盖：admin 初始化、operator 建 ACL、legacy fork、编辑脚本、影响预览、提交 revision、拒绝 creative、typed 修订、再批准、恢复旧版、创建分支。
- [ ] **Step 2:** 安全矩阵覆盖未登录、角色上限、项目 ACL、CSRF、Origin、session expiry、media containment、诊断 admin-only 和错误脱敏。
- [ ] **Step 3:** 故障矩阵覆盖每个 ProjectCommitStore crash point、reservation rename/ACL gap、outbox replay 和外部修改冻结。
- [ ] **Step 4:** 并发覆盖双 commit、双 approve、approve/reject、相同/不同 idempotency digest 和跨进程项目锁。
- [ ] **Step 5:** 运行 M1+M2 全回归、`python -m py_compile`、`git diff --check`；浏览器视觉按用户选择可人工验收，但 mutation 合同测试不得跳过。
- [ ] **Step 6:** README 标记 M2 为 `trial`，明确 Agent Bridge 和运营 Skill 尚未开放，不宣称 3-5 小时 SLA 或超过 Flova。
- [ ] **Step 7:** 提交 `test: certify Backlot structured editing milestone`。

## Milestone 2 完成定义

- 一线用户在登录和 ACL 约束下可用固定 typed editor 保存草稿、查看影响并提交新版本；
- 任一 mutation 可幂等重试，冲突和 stale approval 不会覆盖新内容；
- canonical artifact、checkpoint、bundle、lock、review 和 revision 只通过同一 generation 原子提交；
- 崩溃恢复只能得到完整旧状态或完整新状态，无法判定时冻结并请求管理员处理；
- legacy 项目保持只读，运营编辑发生在独立 `cinematic-fast` 副本；
- creative/sample 拒绝后可由人工 typed draft 完成修订，不依赖 Agent；
- 页面和 API 不泄漏 JSON、hash、路径、异常或内部阶段值；
- 发布级别保持 `trial`，Milestone 3 Agent Bridge 和 Milestone 4 Skill 完成前不标记完整功能。

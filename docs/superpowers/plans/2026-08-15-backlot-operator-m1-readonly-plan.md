# Backlot Milestone 1 全中文运营只读视图 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Backlot 默认项目页升级为全中文、无 JSON、无工程术语的运营只读工作台，同时保留现有工程看板作为独立诊断页。

**Architecture:** 现有 `backlot.state.load_board_state()` 继续作为只读机器事实；新增纯投影层把它确定性转换为版本化 `OperatorProjectState`。`/api/v2` 和新运营 UI 只消费投影，旧 API 与旧 UI 不改合同，通过独立诊断路由继续可用。

**Tech Stack:** Python 3.10、FastAPI、JSON Schema Draft 2020-12、原生 JavaScript ES modules、CSS、pytest、FastAPI TestClient、Playwright。

**Spec:** `docs/superpowers/specs/2026-08-15-backlot-operator-workbench-design.md` 第 4-6、15、18、20、21 节。

---

## Chunk 1: 运营投影合同

### Task 1: 定义 OperatorProjectState schema 与中文词典

**Files:**
- Create: `schemas/backlot/operator_state.schema.json`
- Create: `backlot/operator_language.py`
- Create: `tests/backlot/test_operator_state_schema.py`

- [ ] **Step 1: 写 schema 失败测试**

测试加载 `schemas/backlot/operator_state.schema.json`，用 `Draft202012Validator.check_schema()` 校验，并验证最小合法状态通过、缺少 `summary.next_action` 或 editor 类型非法时失败。

```python
def test_operator_state_schema_rejects_unknown_editor_type():
    state = minimal_operator_state()
    state["stages"][0]["editor"]["type"] = "raw_json"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, load_schema())
```

- [ ] **Step 2: 运行 RED**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_state_schema.py`

Expected: FAIL，因为 schema 文件不存在。

- [ ] **Step 3: 实现最小 schema 与词典**

schema 固定顶层字段 `schema_version/project_id/title/pipeline/skill/summary/stages/workspace/pending_review/permissions/active_job/revision/legacy`，`additionalProperties=false`。阶段 editor 枚举仅允许：

```text
research_review, proposal_choice, script_editor, shot_mapping,
asset_review, sample_review, edit_review, delivery_review, unavailable
```

`operator_language.py` 暴露不可变映射：

```python
STAGE_LABELS = {
    "research": "参考解析与素材体检",
    "proposal": "创意方案",
    "script": "口播与字幕",
    "scene_plan": "镜头映射",
    "assets": "制作准备",
    "sample": "样片确认",
    "edit": "修改与精剪",
    "compose": "成片生成",
    "publish": "交付下载",
}
STATUS_LABELS = {
    "pending": "未开始",
    "in_progress": "制作中",
    "awaiting_human": "等待确认",
    "completed": "已完成",
    "failed": "处理失败",
}
```

九阶段顺序和 label 固定为：

```text
research=参考解析与素材体检, proposal=创意方案, script=口播与字幕,
scene_plan=镜头映射, assets=制作准备, sample=样片确认,
edit=修改与精剪, compose=成片生成, publish=交付下载
```

旧 pipeline 的 `idea` 映射为“创意方案”，未知值映射为“其他步骤”，不得把内部值
直接返回 label。`compose` 与 `publish` 都使用 `delivery_review` editor，但必须保留为
两条独立 StageView。

schema 必须递归闭合，不允许用自由对象掩盖泄漏：

- `summary` required：`current_stage/current_task/progress_percent/next_action/
  estimated_seconds/estimate_confidence/spent_usd`；nullable 只允许 ETA 秒数和费用；
- `StageView` required：`id/label/status/version/updated_at/updated_by/editable/
  summary/warnings/editor`，其中 `updated_at/updated_by` 可为 null；
- `editor` required：`type/data`，`data` 使用 `oneOf` 绑定 editor type 对应的 closed
  data schema，不能是任意 object；
- `skill` 为 null 或 closed `{id, version}`；`pending_review` 为 null 或 closed
  `{kind,label,summary,subject_version}`；
- `workspace` 为 closed `{stage_id, editor, read_only, upgrade_action}`；
- `active_job` 在 M1 只能为 null；`legacy` 为 closed
  `{read_only, source_pipeline, upgrade_available, message}`；
- 每个嵌套 object 均显式 `additionalProperties=false`，数组 items 也必须闭合。

schema 测试除 editor 非法外，还要分别删除每个 required 字段、向各层插入未知键，
证明 unknown field、raw artifact/hash/path 字段和空壳 editor data 均被拒绝。

- [ ] **Step 4: 运行 GREEN**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_state_schema.py`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add schemas/backlot/operator_state.schema.json backlot/operator_language.py tests/backlot/test_operator_state_schema.py
git commit -m "feat: define Backlot operator state contract"
```

### Task 2: 实现确定性运营投影

**Files:**
- Create: `backlot/operator_state.py`
- Create: `tests/backlot/test_operator_state.py`

- [ ] **Step 1: 写 fastline 投影失败测试**

用真实临时项目写入 `project.json`、checkpoint、`script`、`scene_plan` 和 fastline 状态，调用期望 API：

```python
state = load_operator_state(project)
assert state["summary"]["current_stage"] == "样片确认"
assert state["summary"]["next_action"] == "请回到任务中确认样片效果"
assert state["stages"][0]["label"] == "参考解析与素材体检"
assert "artifacts" not in state["workspace"]
validate_operator_state(state)
```

同时断言 `pipeline` 仅用于路由、九阶段顺序/数量/label 正确、compose 和 publish 均
存在、stage version 正确，未知错误不会回传绝对路径或 stack trace。

- [ ] **Step 2: 运行 RED**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_state.py::test_fastline_project_projects_business_state`

Expected: FAIL，`backlot.operator_state` 不存在。

- [ ] **Step 3: 写 legacy 与其他 pipeline 的失败测试**

在实现通用投影前加入 fixture：

- legacy `cinematic` 缺 approval bundle/production lock：只读、中文升级建议，不伪造
  批准、缓存收益或 ETA；
- 未知 pipeline：返回 manifest/BoardState 中可识别的阶段，editor 为 `unavailable`；
- 自定义 manifest stage：label 为“其他步骤”，内容为只读 unavailable；
- 缺 artifact 与损坏 artifact：降级为中文空态，不泄漏异常类、绝对路径或原始 JSON。

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_state.py`

Expected: FAIL，`backlot.operator_state` 不存在。

- [ ] **Step 4: 实现纯投影骨架**

实现：

```python
def project_operator_state(board_state: Mapping[str, Any]) -> dict[str, Any]: ...
def load_operator_state(project_dir: Path) -> dict[str, Any]: ...
def validate_operator_state(value: Mapping[str, Any]) -> None: ...
```

要求：

- 不重新读取 artifact，不复制 `backlot.state` 的扫描逻辑；
- summary 从 `fastline`、stage rail、cost、media 确定性派生；
- stages 固定中文 label、中文 status、业务 summary、editor type；
- workspace 只返回当前阶段所需的裁剪业务字段；Milestone 1 的 `editable=false`；
- `pending_review` 为等待确认阶段的业务摘要；
- `permissions=["view"]`，认证/项目 ACL 留到 Milestone 2；
- `revision` 输入为除 `revision` 自身外的完整 closed projection，使用
  `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` 后做 SHA-256；
  BoardState 的 mtime、live、原始 event 顺序和未投影字段不参与；
- 响应必须通过 schema 校验。

派生优先级固定，避免不同实现产生不同结果：

1. current stage：按 manifest 顺序取首个 `awaiting_human`，否则首个
   `in_progress`，否则首个 `pending`，全部完成时取 `publish`；
2. progress：`completed stage count / declared stage count * 100` 四舍五入为整数，
   不用 mtime 或动画进度修饰；
3. current task/next action：fastline 已有中文字段优先，否则使用当前 stage/status 的
   固定中文模板；
4. ETA：仅映射 `fastline.eta.seconds/confidence`，缺失为 null，不直接解释原始 event；
5. spent：只映射 `cost.total_spent_usd`，缺失为 null；
6. skill：BoardState 没有已解析 Skill 时为 null，不根据 pipeline 猜测；
7. updated_at 使用 checkpoint timestamp，updated_by 在审计功能上线前固定 null；
8. version 使用 BoardState `stage.versions`，最小为 0。

- [ ] **Step 5: 实现逐阶段只读业务白名单**

`editor.data` 只允许下列字段，不得传递源 dict：

| editor type | allowed data |
|---|---|
| research_review | `reference_summary, source_count, usable_count, risks` |
| proposal_choice | `concepts[{id,title,hook,duration_seconds}], selected_id` |
| script_editor | `duration_seconds, sections[{id,label,text,start_seconds,end_seconds}]` |
| shot_mapping | `duration_seconds, shots[{id,beat,screen_copy,source_label,in_seconds,out_seconds}]` |
| asset_review | `narration_status, subtitle_status, music_status, estimated_cost_usd` |
| sample_review | `duration_seconds, preview_url, qa_status, review_summary` |
| edit_review | `change_scope, reasons, affected_shot_count` |
| delivery_review | `duration_seconds, qa_status, download_url, format_label` |
| unavailable | `message` |

`source_label` 只能是安全展示名，`preview_url/download_url` 必须是由 server 生成的
contained media URL，不接受 artifact 中的绝对/相对文件路径直接透传。

- [ ] **Step 6: 验证递归防泄漏与 revision 语义**

测试递归遍历整个响应：禁止 key 包含 `semantic_sha256/artifact_sha256/input_hashes/
artifact_refs/path/stack/traceback`；除 `pipeline` 与 stage `id` 合同字段外，用户可见
字符串不得包含绝对路径、`.json`、Python 异常类、内部状态或内部阶段名。

验证四种 revision 行为：重复投影相同；只改 mtime/扫描顺序/未投影 event 不变；
脚本文本或阶段状态改变后必变；`revision` 自身不参与 hash。

- [ ] **Step 7: 运行 Task 1-2 回归**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_state_schema.py tests/backlot/test_operator_state.py tests/backlot/test_fastline_state.py tests/backlot/test_state.py`

Expected: PASS。

- [ ] **Step 8: 提交**

```bash
git add backlot/operator_state.py tests/backlot/test_operator_state.py
git commit -m "feat: project Backlot state into Chinese operations"
```

## Chunk 2: API 与默认路由

### Task 3: 暴露 v2 只读 API 并保留诊断页

**Files:**
- Modify: `backlot/server.py`
- Create: `tests/backlot/conftest.py`
- Create: `tests/backlot/test_operator_api.py`
- Modify: `tests/backlot/test_server.py`

- [ ] **Step 1: 写 API 失败测试**

```python
def test_operator_state_endpoint_returns_versioned_chinese_projection(
    backlot_client, projects_root, make_project
):
    make_project(projects_root, "film")
    response = backlot_client.get("/api/v2/projects/film/operator-state")
    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.0"
    assert response.json()["summary"]["current_stage"] == "口播与字幕"
```

先把通用 `projects_root/backlot_client/make_project` fixture 移到
`tests/backlot/conftest.py`，`test_server.py` 改为消费共享 fixture；RED 必须是 endpoint
404，而不是 fixture collection error。另测未知/恶意 project ID 使用现有
`_safe_project_dir()`，不产生第二套路径校验。

- [ ] **Step 2: 运行 RED**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_api.py`

Expected: FAIL，endpoint 返回 404。

- [ ] **Step 3: 实现 endpoint 与路由拆分**

- 新增 `GET /api/v2/projects/{id}/operator-state`；
- 新增 `GET /api/v2/projects/{id}/events`，与旧 project SSE 调用同一个私有 stream
  helper 和 `ChangeHub`，hello/change payload 只含稳定业务 ID 和中文 message；
- `/diagnostics/p/{id}` 返回现有 `board.html`；
- Task 3 保持 `/p/{id}` 仍返回旧页面，避免引用尚未创建的 UI；Task 4 在
  `operator.html` 与资源就绪的同一提交中原子切换默认路由；
- 原 `/api/project/{id}/state`、SSE、media、thumb 保持行为不变；
- `_ui_html()` 同时对 operator 资源加 mtime query；
- no-cache middleware 覆盖 `/diagnostics/`；
- Milestone 1 不伪装已完成认证，诊断路由的 admin 限制在 Milestone 2 实施。

API 测试必须读取 v2 SSE 的首个 hello，再调用 `hub.publish(project_id)` 读取 change，
并覆盖非法/未知 ID；旧 SSE 路由运行相同回归，证明 alias 没有改变旧 payload。

- [ ] **Step 4: 运行 API 与兼容回归**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_api.py tests/backlot/test_server.py`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backlot/server.py tests/backlot/conftest.py tests/backlot/test_operator_api.py tests/backlot/test_server.py
git commit -m "feat: expose Backlot operator API and routes"
```

## Chunk 3: 全中文运营 UI

### Task 4: 建立无 JSON 的运营工作台外壳

**Files:**
- Create: `backlot/ui/operator.html`
- Create: `backlot/ui/operator/app.js`
- Create: `backlot/ui/operator/api.js`
- Create: `backlot/ui/operator/store.js`
- Create: `backlot/ui/operator/language.js`
- Create: `backlot/ui/operator/styles.css`
- Create: `tests/backlot/test_operator_ui_contract.py`
- Modify: `backlot/server.py`（运营资源就绪后切换 `/p/{id}`）

- [ ] **Step 1: 写静态合同失败测试**

静态测试只负责代码组织与明显反模式，运行时可见文本和 accessibility tree 由 Task 5
验证。静态测试要求：

- `operator.html` 为 `lang="zh-CN"`；
- 默认页面包含项目标题、总进度、当前任务、预计时间、下一步和九阶段导航；
- JS/CSS 含 loading、empty、degraded、error、awaiting、completed 状态；
- 运营目录不得出现 `<pre>`、`JSON.stringify(`、`artifact path`、`semantic_sha256`、
  `runtime`、`schema`、`pipeline`、英文内部阶段标签；
- 提供“查看诊断信息”链接，但不在页面展开工程内容；
- 390px、1280px 和 1440px 使用稳定 grid/sidebar 约束，无横向溢出。

- [ ] **Step 2: 运行 RED**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_ui_contract.py`

Expected: FAIL，因为运营 UI 文件不存在。

- [ ] **Step 3: 实现最小可用 UI**

页面结构：顶部项目摘要带、左侧阶段导航、中央当前阶段工作区、右侧下一步/ETA；窄屏改为单列，阶段导航横向滚动。只使用已有原生模块，不引入构建链或外部字体请求。

`app.js` 只渲染 `OperatorProjectState` 的业务字段；`api.js` 只调用 v2 GET/SSE；
`store.js` 在 SSE 更新时保留当前选择；`language.js` 只放 UI 固定文案，不重复后端
阶段映射。

- [ ] **Step 4: 运行静态合同 GREEN**

Run: `PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_ui_contract.py`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backlot/ui/operator.html backlot/ui/operator tests/backlot/test_operator_ui_contract.py
git commit -m "feat: add Chinese Backlot operator workbench"
```

### Task 5: 浏览器验收与 Milestone 1 发布 Gate

**Files:**
- Create: `tests/backlot/test_operator_browser.py`
- Modify: `backlot/README.md`
- Modify: `tests/backlot/test_ui_bug_bash.py`
- Modify: `scripts/backlot_screenshot_stage.py`
- Modify: `scripts/backlot_visual_eval.py`
- Modify: `scripts/backlot_watch_captures.py`

- [ ] **Step 1: 写浏览器验收**

启动临时 Backlot，验证：

- `/p/<project>` 默认加载运营页，运行时 `body.innerText`、可访问名称与 tooltip 无
  `<pre>`、JSON、hash、schema、runtime、artifact path、绝对路径和内部阶段英文；
- `/diagnostics/p/<project>` 仍加载旧看板；
- 1440x900、1280x800、390x844 无横向溢出、文字重叠或按钮截断；
- SSE refetch 不改变当前选中阶段；
- legacy、unknown pipeline、缺/损坏 artifact 项目显示中文只读/降级建议；
- 用 route interception 或专用 fixture 实际驱动 loading、empty、degraded、error、
  awaiting、completed；错误页不出现路径、异常类或响应原文；
- Tab 键能依次聚焦诊断链接、阶段按钮和主要操作，所有 icon-only 控件有中文
  accessible name；对 `body` 生成 ARIA snapshot 并扫描禁用术语。

现有工程看板消费者必须迁移到诊断路由：`test_ui_bug_bash.py` 中检查 `.approval-review`
等旧 DOM 的路径，以及三个截图/视觉脚本中的旧 board URL 改为
`/diagnostics/p/{id}`。`library.js` 和 `backlot/__main__.py open` 保持 `/p/{id}`，确保
一线入口默认进入运营页。

- [ ] **Step 2: 运行浏览器测试并修复**

Run:

```bash
BACKLOT_CHROMIUM_EXECUTABLE=/Users/yichen/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell \
PYTHONPATH=. <repo>/.venv/bin/pytest -q tests/backlot/test_operator_browser.py
```

Expected: PASS。浏览器验收是发布 Gate，不允许以 skip 视为通过。测试启动器优先读取
`BACKLOT_CHROMIUM_EXECUTABLE`，未设置时再使用 Playwright 自带 runtime；两者均不可用
时测试 FAIL 并提示确切配置方式。截图写入 pytest 临时目录，不提交二进制产物。

- [ ] **Step 3: 更新 README**

记录运营页、诊断页、v2 endpoint、Milestone 1 为 `internal/trial`，明确编辑、认证、Agent 对话尚未开放。

- [ ] **Step 4: 完整回归**

Run:

```bash
BACKLOT_CHROMIUM_EXECUTABLE=/Users/yichen/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell \
PYTHONPATH=. <repo>/.venv/bin/pytest -q \
  tests/backlot/test_operator_state_schema.py \
  tests/backlot/test_operator_state.py \
  tests/backlot/test_operator_api.py \
  tests/backlot/test_operator_ui_contract.py \
  tests/backlot/test_operator_browser.py \
  tests/backlot/test_state.py \
  tests/backlot/test_server.py \
  tests/backlot/test_fastline_state.py \
  tests/backlot/test_fastline_ui_contract.py \
  tests/backlot/test_ui_bug_bash.py
```

Expected: 全部 PASS；另运行
`python -m py_compile scripts/backlot_screenshot_stage.py scripts/backlot_visual_eval.py scripts/backlot_watch_captures.py`
确认迁移后脚本可加载，且 `git diff --check` 通过。

- [ ] **Step 5: 提交**

```bash
git add tests/backlot/test_operator_browser.py tests/backlot/test_ui_bug_bash.py \
  scripts/backlot_screenshot_stage.py scripts/backlot_visual_eval.py \
  scripts/backlot_watch_captures.py backlot/README.md
git commit -m "test: certify Backlot operator read-only milestone"
```

## Milestone 1 完成定义

- 默认项目页只显示中文业务信息，不显示 JSON、hash、schema、runtime、artifact path 或内部阶段名；
- v2 运营状态对 fastline 和 legacy 项目均可用，并通过版本化 schema；
- 旧 API 和旧诊断看板保持兼容；
- UI 在桌面、笔记本和手机宽度可用；
- 状态明确标记 `internal/trial`，不宣称编辑、权限、3-5 小时 SLA 或超过 Flova；
- 规范审查和代码质量审查均通过后，才能开始 Milestone 2。

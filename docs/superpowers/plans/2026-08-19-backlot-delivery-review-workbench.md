# Backlot 成片运营审核台实施计划

**目标：** 将“成片生成”升级为可播放、可理解、可暂存修改、可生成新版本的运营
审核台，并以 `table-mat-mix-v6` 完成端到端验收。
**设计依据：** `docs/superpowers/specs/2026-08-19-backlot-delivery-review-workbench-design.md`
**实施方式：** TDD，小步提交；不得覆盖当前工作树中已有改动。

## 0. 开始条件

1. 先审查当前未提交变更，确认哪些属于既有工作台实现并将其作为基线。
2. 不在实现中清理、回滚或格式化无关文件。
3. 记录 `table-mat-mix-v6` 当前 operator-state 和成片媒体基线。
4. 参考视频路径只允许进入分析来源检查，不允许进入任何候选或交付媒体字段。

## 1. 数据合同与失败测试

### 目标

先固定 `delivery_review` 和 operator-state 的公开合同。

### 变更

- 新增 `schemas/artifacts/delivery_review.schema.json`；
- 扩展 `schemas/backlot/operator_state.schema.json` 的 `delivery_review` editor；
- 扩展 `schemas/backlot/operator_draft.schema.json` 的封闭 stage/operation 枚举；
- 在 `schemas/artifacts/__init__.py` 注册新 artifact，并在 `lib/checkpoint.py` 将其声明为
  compose 的可选 supplementary artifact；
- 定义 timeline、candidate groups、version summaries、poster 和 pending changes；
- compose checkpoint 将 `delivery_review` 作为可选 artifact，旧项目保持兼容。

### 测试先行

- 合法最小 `delivery_review` 通过；
- 未知候选 ID、未知字段、媒体路径和任意时间码被拒绝；
- 旧 operator-state fixture 继续通过；
- 新字段缺失时采用可解释空态，而不是 schema 失败；
- operator-state 不输出绝对路径和参考视频媒体 URL。
- 带或不带可选 `delivery_review` 的 compose checkpoint 均通过合同验证。

### 相关文件

- `schemas/artifacts/delivery_review.schema.json`
- `schemas/backlot/operator_state.schema.json`
- `schemas/backlot/operator_draft.schema.json`
- `schemas/artifacts/__init__.py`
- `lib/checkpoint.py`
- `tests/backlot/test_operator_state_schema.py`
- 对应 artifact 与 checkpoint 合同测试

## 2. Compose typed adapter 与影响预览

### 目标

开放 compose 页面中的 `delivery_review` mutation，只允许提交审核台定义的受约束
操作，并保持已完成 compose checkpoint 与当前成片可读。

### 变更

- 新增 `backlot/operator_adapters/delivery_review.py`；
- 在 adapter registry 注册独立 `delivery_review` mutation，不把它伪装成 pipeline
  `compose` stage；
- 调整 `backlot/operator_drafts.py` 允许 delivery review 草稿；
- 在 `backlot/operator_impact.py` 注册“成片审核”标签并分类 poster-only、mux-only 和
  full-render 影响；
- 使用专用提交服务原子写入 `delivery_review` revision，不走会删除
  `checkpoint_compose.json` 的通用 `RevisionService.commit_draft()` 路径，也不直接生成
  视频或移动认证成片指针。

### 测试先行

- 候选选择、文案覆盖、同步口播开关可 round-trip；
- `sync_narration` 省略或首次创建时为 `true`；显式关闭时保留字幕修改、不触发 TTS，
  并返回音画不一致警告；
- 传入 provider、runtime、文件路径、未知镜头或非法 gain 时拒绝；
- 仅换封面不重渲染视频；
- BGM/音量按既有合同判定 mux-only 或重开审批；
- 文案联动口播时提示 TTS、字幕与 full render；
- stale revision 和并发提交按现有冲突合同处理。
- 提交审核草稿不删除或降级 compose checkpoint，不改变 current delivery pointer。

### 相关文件

- `backlot/operator_adapters/__init__.py`
- `backlot/operator_adapters/delivery_review.py`
- `backlot/operator_drafts.py`
- `backlot/operator_impact.py`
- 专用 delivery review 提交服务与 `backlot/project_commit.py`
- `tests/backlot/test_operator_adapters.py`

## 3. 时间线与版本投影

### 目标

从已有 production artifacts 构建稳定的四轨业务投影，不复制第二套生产事实。

### 变更

- 在 `backlot/operator_state.py` 增加 timeline projector；
- 将镜头、口播、字幕和音乐统一到成片时间轴；
- 按语义句合并字幕，并保留覆盖的 `shot_ids`；
- 提供 active version、历史版本和变更摘要；
- 单轨数据缺失时局部降级。

### 测试先行

- 一句跨多个镜头只产生一个 copy segment；
- 画面轨无重叠、无负时长，边界采用半开区间；
- 无 narration、subtitle 或 BGM 时分别返回真实空态；
- 版本按追加顺序稳定投影；
- QA 未通过的版本不会成为 active version。

### 相关文件

- `backlot/operator_state.py`
- `tests/backlot/test_operator_state.py`
- `tests/backlot/test_operator_state_schema.py`

## 4. 本地候选准备与历史项目兼容投影

### 目标

QA 通过后用当前项目资产幂等生成封面、前三秒、BGM 和结尾候选。

### 变更

- 从成片或自有素材提取非黑、清晰、产品可见的 poster 候选；
- 从现有镜头与文案组合钩子候选，只记录剪辑决策，不产生付费资产；
- 从项目现有音乐和 `music_library/` 读取真实 BGM 候选；
- 从现有结尾镜头、CTA 和可用品牌资产构造结尾候选；
- 为历史项目提供无业务写入的兼容投影；需要持久化的准备由显式任务执行；
- 候选 ID 使用 base version、类型和 provenance 内容哈希稳定派生；
- 对所有候选执行 media provenance 检查，排除 reference 来源。

### 测试先行

- 黑帧不会成为 poster；
- 候选只引用 source/generated/current-render 资产；
- reference 来源一律被过滤并触发测试失败；
- 无曲库时 BGM 候选为空且原因明确；
- 重复 GET 得到相同候选 ID，且不会新增 artifact、revision、candidate 或 pointer；
- 缩略图缓存即使生成，也不属于业务版本并可安全删除/重建；
- 候选准备不会产生 cost reservation。

### 相关文件

- `backlot/operator_state.py` 或独立候选投影模块
- 显式候选准备服务（如确需持久化）
- `tests/backlot/test_operator_state.py`
- 候选幂等性与 GET 只读合同测试

## 5. 审核台前端

### 目标

实现单播放器、四轨时间线、版本切换、行内文案编辑和模块候选栏。

### 变更

- 重构 `renderDelivery` 为审核台布局；
- 播放器使用 poster，轨道点击与播放头同步；
- 文案行内编辑复用现有 draft/impact/commit 流程；
- 候选模块支持选择、试听、取消和待生成摘要；
- “生成新版”前必须完成影响预览；
- 响应式布局在移动端降级为纵向分区。

### 测试先行

- UI 合同断言四轨、候选组、版本、poster 和三个主操作存在；
- 文案从显示态进入编辑态、取消和保存均正确；
- SSE 更新不覆盖正在编辑的草稿；
- 无 BGM、不存在候选、QA 失败和生成中状态可理解；
- UI 不出现 raw JSON、绝对路径或内部阶段英文。

### 相关文件

- `backlot/ui/operator/app.js`
- `backlot/ui/operator/editors.js`
- `backlot/ui/operator/styles.css`
- `tests/backlot/test_operator_ui_contract.py`

## 6. 新版本生产消费与 QA 门禁

### 目标

让生产流程消费已提交的 `delivery_review`，生成一个完整新版，并在 QA 通过后原子
切换当前版本。

### 变更

- 将候选选择映射到正式 script/edit/assets 决策；
- 根据 impact route 复用视觉、重新混音或完整渲染；
- 生成期间保留当前版可播放；
- 为每个完整版本写入不可变
  `operator/delivery-versions/<version-id>/manifest.json`，绑定视频、poster、subtitle、
  audio mix、render QA、审核 revision 和变更摘要；
- 使用独立 `operator/current-delivery.json` 作为已认证成片指针，不复用控制面的
  `operator/current-generation.json`；
- QA 通过后在 Project Commit Store 事务中登记 manifest 并更新认证指针；失败则保留
  失败版本和原因，认证指针不变。

### 测试先行

- 一次提交只生成一个完整版本；
- 生成失败或 QA 失败不移动 active pointer；
- 成功切换是原子的，reader 不观察半完成状态；
- `delivery_review` 提交、渲染开始和 QA 未通过状态都不能移动认证指针；
- delivery manifest 创建后不可修改，V1/V2/V3 从 manifests 稳定投影；
- poster-only 修改不改变 certified video master；
- BGM 变更执行完整音频 QA；
- 参考视频文件永不出现在 FFmpeg 输入、manifest 或交付目录。

### 相关文件

- `tools/video/video_compose.py`
- 既有 compose director 与 checkpoint 写入路径
- `backlot/project_commit.py`
- 对应 compose、QA 和事务测试

## 7. 验收与发布

### 自动验证

1. 运行新增 schema、adapter、state、UI 合同和 migration 测试。
2. 运行完整 `tests/backlot/` 回归。
3. 执行前端 JavaScript 语法检查。
4. 对 `table-mat-mix-v6` 执行一次 dry projection 和重复 GET 无业务写入检查。

### 浏览器验收

使用 Playwright 检查 1440x900、1280x800 和 390x844：

- poster 非黑且播放器可播放；
- 四轨与播放头同步；
- 跨镜头语义句显示正确；
- 文案编辑、候选选择、影响预览和暂存恢复可用；
- V1/V2/V3 切换不创建多个播放器；
- 无 BGM 时空态真实；
- 无重叠、截断和不可达按钮。

### 完成定义

- 设计规范第 12 节全部通过；
- 既有项目和 API 合同无回归；
- `table-mat-mix-v6` 能完成“审核 -> 修改 -> 查看影响 -> 生成新版 -> QA -> 切换”闭环；
- 未经确认不发生付费调用；
- reference provenance 隔离测试通过。

## 8. 建议提交顺序

1. `test(backlot): define delivery review contracts`
2. `feat(backlot): add delivery review drafts and impact`
3. `feat(backlot): project delivery timeline and versions`
4. `feat(backlot): prepare local review candidates`
5. `feat(backlot-ui): add delivery review workbench`
6. `feat(compose): consume approved delivery review decisions`
7. `test(backlot): cover delivery review golden workflow`

每个提交必须包含对应测试；不要把 schema、后端、前端和生产消费压成一个无法
独立验证的大提交。

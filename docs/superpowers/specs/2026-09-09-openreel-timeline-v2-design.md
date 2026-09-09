# OpenReel Timeline V2 设计规范

> 日期：2026-09-09
> 状态：待实施
> 适用范围：Source-led 电商短视频的批量候选复核、单条精剪和安全发布

## 1. 决策与问题定义

当前 main 没有 OpenReel 或 /studio 入口。历史分支
codex/editorial-gallery-rollout 实现了批量画廊、会话和 OpenReel V1 壳，但未合入主干。
该分支的 openreel_bridge 只可提交裁剪、速度、转场、字幕文字和镜头开关；分割、重排、
新增镜头、混音、文字层和字幕时间均只是浏览器本地草稿。其渲染 job 只维护状态，测试
直接写入假视频并由客户端提交 qa_status=pass。

因此 V2 不整体合并该分支，也不把 OpenReel 内部 JSON 当成生产事实。V2 在当前
Source-led Taobao 主链上选择性迁移批量浏览、会话归属、幂等、防陈旧写入、历史版本和
promote/discard 机制；重建可执行的多轨时间轴、真实预览/成片执行器和服务端 QA 门。

目标是让运营人员在不破坏已交付版本的前提下完成精细修改：替换镜头、分割并重排、修改
口播/BGM、调整字幕时间和花字，然后看到真实预览、通过事实与质量检查后再发布。

## 2. 非目标与边界

- 不更换已在 proposal 阶段确认的渲染引擎；运行时切换仍须走现有决策日志与人工确认。
- V2 首期只对 render_runtime=remotion 的候选开放。HyperFrames 与 FFmpeg 锁定候选在画廊
  显示“当前运行时尚未支持精剪”，不得创建 session；它们保留现有单条工作台。等价 adapter
  和渲染实现在后续 runtime 扩展中单独设计、测试和发布。
- 不允许编辑器创建新的商品事实、弱化事实范围，或把无证据素材绑定到商品卖点。
- 不在首期实现 OpenReel 的完整效果、调色、特效、协作光标或任意插件生态。
- 不以客户端状态、浏览器导出视频或客户端传入的 QA 结果作为交付依据。
- 不整体 vendoring 旧分支约 55 万行 OpenReel build；集成边界是锁定的前端包构建产物和
  明确的同源 HTTP bridge，源码升级独立管理。

## 3. 信息与运行模型

    Batch Gallery (/studio/<batch>)
      -> Candidate Detail (/p/<candidate>)
      -> OpenReel editor (/studio/<batch>/edit/<candidate>)
           GET editor snapshot (EditorialTimeline v1 + approved asset catalogue)
           POST typed EditDelta
      -> versioned timeline snapshot
      -> preview executor -> preview artifact + Source-led alignment + L1a + final QA
      -> human preview approval
      -> final executor -> immutable delivery candidate + server-derived QA
      -> human promote / discard

所有生产状态都写入候选项目下的 operator/editorial/ 并由 ProjectCommitStore 事务发布。
预览或最终版本失败时，operator/current-revisions/ 与已有 renders/ 指针不变。

## 4. Canonical Contract：EditorialTimeline v1

artifacts/editorial_timeline.json 是一次精剪版本唯一的可执行事实。它从当前已批准的
edit_decisions、final_props、asset manifest、Source-led coverage matrix 和 product facts
物化，带入这些不可篡改的起始约束：

- base_generation_id、base_edit_revision、source_artifact_hashes。
- 每个视觉片段的 asset_id、源时间范围、fact_scope、shot_id、
  visual_requirement_id 和允许的来源类别。
- 每条口播/字幕的 claim_ids、原始文本哈希与时间范围。
- 输出 profile（淘宝 3:4、2160x2880/上传版策略）、渲染运行时和安全区。

时间轴显式包含 video、narration、music、selling-point text 与 subtitle 五类轨道。视频 clip
支持源入/出点、时间轴起点、速度、变换、淡入淡出、层级和转场。音频 clip 支持增益、
淡入淡出、旁白优先 ducking。文字/字幕 clip 支持文本、开始/结束时间、样式令牌与位置。
花字样式被限制到批准的淘宝模板令牌，不能由编辑器提交任意 CSS 或外部资产。

edit_decisions.schema.json 保持旧链兼容；V2 新增 editorial_timeline.schema.json，并由
适配器将 timeline 确定性投影为编辑专用 Remotion props。现有 Explainer 不具备完整多轨
语义，因此必须扩展 remotion-composer/src/Explainer.tsx、Root.tsx 和对应 props 类型；不能
由现有 runtime 无损表达的能力必须在执行器前拒绝，绝不能静默丢弃。

### 4.1 Approved asset catalogue

每次 editor snapshot 同时写出 operator/editorial/asset-catalogue.json。它不是 asset_manifest
的直通投影，而是服务端从 coverage matrix、shot execution plan、source-media evidence 和
已批准生成任务构建的只读能力表。每个可选片段包含 server-issued asset_id、原文件 hash、
可用 in/out 区间、source class、claim_ids、fact_scope、visual_requirement_id、候选项目 ID
和 catalogue hash。EditDelta 只能引用该 version 的 asset_id 及区间；伪造 asset ID、跨候选
引用、越出探测区间、或以相同 claim 替代不同 visual_requirement 的操作必须拒绝。

## 5. EditDelta 与能力策略

每次提交是带 session_id、base_generation_id、base_timeline_hash、操作序号和 idempotency key
的 EditDelta。服务端按 CAS 校验、应用、重新验证并保存；与当前代数不匹配时返回
stale_generation，不覆盖新版本。

首期可提交 operation：

| 类别 | operation |
|---|---|
| 视频 | add_clip、remove_clip、move_clip、split_clip、trim_clip、replace_clip、set_speed、set_transition |
| 口播/BGM | move_audio、set_gain、set_fade、set_ducking、replace_narration、replace_music |
| 文本 | set_caption_text、set_caption_timing、set_text_style、set_text_timing、set_enabled |

操作只可引用编辑 snapshot 中的 approved asset catalogue。replace_clip 还必须满足原 clip 的
fact_scope 和 visual requirement；不满足时返回结构化 fact_scope_violation，并告诉 UI
哪项商品事实会失去证据。move_clip 默认是 non-ripple：只移动指定 video track 的 clip，
不隐式移动音频、字幕或 overlay；目标位置与同轨主片段冲突即拒绝。ripple 必须作为独立
operation，带显式受影响 clip IDs 和审批后的时间偏移计划。overlay/text 可与视频重叠，
音频可重叠但同类 voice-over 必须通过可懂度规则。OpenReel 无法被映射的动作必须呈现
“此功能当前不支持提交”，既不保存为可交付草稿，也不得使“保存/预览”按钮显示成功。

## 6. 真实执行与门禁

EditorialRenderExecutor 读取版本化 timeline，先执行静态约束验证，再用已锁定的
video_compose 运行时生成独立 version 目录：

    operator/editorial/versions/<revision>/
      timeline.json
      materialized/edit_decisions.json
      materialized/final_props.json
      preview.mp4 | final.mp4
      qa/alignment.json
      qa/l1a.json
      qa/final_qa.json
      execution_report.json

预览渲染可采用与当前样片一致的缩放/短窗策略，但仍必须生成新的、绑定 timeline hash 与
output hash 的 source-led evidence report；不得复用基线 alignment report。完整成片必须
运行全量三项门：

1. Source-led alignment：新版 evidence report 从物化 timeline、输出文件抽帧/探测和事实
   绑定生成，逐片段证明仍覆盖 visual requirement，且画面、花字、口播和商品事实一致。
2. L1a：以实际输出文件、事实卡和交付 profile 为输入。
3. final QA：以实际输出文件为输入。

服务端从文件和报告导出 gate 状态；请求体不得接受 qa_status、输出路径或“完成”信号。
任何一项失败仅产生失败版本，并保留可查看的报告和旧版。

## 7. UI、路由与版本生命周期

- /studio/<batch-id>：批量画廊，复用候选卡、筛选、状态与证据投影；“精剪”只能从已交付
  或已选中候选进入。
- /studio/<batch-id>/edit/<candidate-id>：OpenReel 实际编辑入口，含事实约束面板、
  approved assets、版本历史、渲染状态和明确的 unsupported action 提示。
- /p/<candidate-id>?from=batch...：保留单条制作工作台，不替代编辑器。

编辑创建新 revision，旧 delivery 一直保持可播放。状态为：

    draft -> preview_queued -> preview_ready -> preview_approved -> final_queued
          -> preview_failed | final_review | final_failed
          -> promoted | discarded

preview_approved 必须持久化 preview revision、output hash、actor 和时间；任何新 delta 或
新的 preview 都会使其失效。未批准 preview 的 final 请求一律拒绝。只有 final_review 且
服务端门均为 pass 时允许 promoted。discarded 永远不删除产物，只移除
当前候选引用。promote 采用 ProjectCommitStore 单事务更新 revision 指针、delivery manifest
和审计记录。

## 8. 选择性迁移与不迁移项

从历史分支迁移：gallery DTO/读取投影、candidate/revision session ownership、草稿恢复、
idempotency、generation stale guard、审计和 promote/discard 语义、同源 OpenReel shell。

不迁移：一条视频轨的 snapshot mapper、局部草稿动作白名单、将 render job 当作 worker、
客户端提交 QA、复制进 Backlot 的生成 OpenReel bundle 作为事实边界。

前端供应链改为 vendor/openreel 的固定 source revision + 受控 build script；构建输出放入
backlot/ui/editorial-editor/openreel/，校验 manifest、许可、内容 hash 后才能随发布提交。

## 9. 验收标准

1. 可从批量画廊打开任一已选候选的 OpenReel 精剪页，并展示真实视频、口播、BGM、字幕和
   绑定商品事实。
2. 替换、分割/重排、字幕改时、旁白/BGM 调整均在预览与最终成片真实生效。
3. 不匹配商品事实的素材替换被服务端拒绝，且 UI 显示具体原因。
4. preview/final 的 QA 由服务端产物得出；客户端伪造 pass 无效。
5. 失败、discard、并发陈旧写入不改变旧交付；promote 后可由具备 edit 权限的操作者恢复
   一份完整 hash 校验过的旧 delivery revision。
6. 每次版本都有输入 hash、编辑 delta、输出 hash、执行报告、三类门结果和操作者审计。
7. 现有 tests/integration/test_source_led_sample_alignment.py 和
   tests/integration/test_cinematic_fast_end_to_end.py 与 cinematic-fast 主链回归全绿。

## 10. 发布策略与风险

先以单一银离子毛巾批次验证，限制可编辑候选和 approved assets；通过后才开放给四商品、
16 条批量生产。feature flag 为 OPENMONTAGE_EDITORIAL_TIMELINE_V2；关闭时保留当前单条
工作台和主链，不影响生产交付。

No-Go 条件：执行器尚未连接真实合成、QA 仍由客户端声明、无法保证 product-fact scope，
或修改后的版本会覆盖既有交付。发生任一条件不得将 V2 入口暴露给运营。

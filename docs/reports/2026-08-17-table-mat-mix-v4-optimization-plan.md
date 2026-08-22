# table-mat-mix-v4 复盘评审 + 优化升级方案

**日期:** 2026-08-17
**评审对象:** [`2026-08-17-table-mat-mix-v4-process-technology-review.md`](2026-08-17-table-mat-mix-v4-process-technology-review.md)
**目标:** ① 执行效率(时长) ② 视频生成效果 ③ 用户审核前端 UI 体验 ④ 快速/高效
**证据等级:** 复盘文档的 P0/P1 论断已逐条抽查代码与项目产物,见 §1。

---

## 1. 对复盘文档本身的评审

### 1.1 已抽查验证的论断(全部属实)

| 论断 | 证据 |
|---|---|
| 事件流只有工具 start/finish,无编排/帧级事件 | `lib/events.py` 仅追加 `ts + tool + event + duration_s + cost_usd`;`events.jsonl` 全部 65 条只有 start/finish/cache_miss,最后一条 02:35,74 分钟空档属实 |
| UI 只取最近 10 条活动 | `backlot/ui/board.js:640` `rows.slice(-10)` |
| compose 未刷新 partial_progress | `checkpoint_compose.json` 为 completed 但 `partial_progress: null` |
| QA 安全区是布局推导,非 OCR 像素证据 | `tools/video/final_qa.py` 用 `caption_spec.computed_boxes + props_hash` 推导,`input_schema` 无 expected duration/frames |
| staged commit 存在但 checkpoint 校验读不到同事务 artifact | `backlot/project_commit.py` 有 `_TransactionSink` staged 写入 + materialize,与诊断一致 |

结论:复盘文档**证据扎实、分桶正确、不甩锅渲染**,是合格的事后分析。

### 1.2 复盘本身的缺口(方案要补的)

1. **最长的两个时间桶没有被缩短,只是被"照亮"。** 74 分钟研究空档 + 08:28→14:18 的 ~5.5 小时(人工决策 + 未记录编排 + sample-tts 支线),P0-1 让它们*可见*,但没有一项让它们*变短*。缺:
   - **关键路径纪律**(agent 规则):生产运行内禁止基建开发支线(sample-tts 教训),基建必须独立 branch 验收后集成;
   - **断点恢复协议**:每阶段结束把"下一步动作"写进 checkpoint/decision_log,新会话零重推导直接恢复——"上下文恢复"这个桶的根因正是每次恢复都要重新看文件猜状态。
2. **5 次样片重渲染只诊断了一半根因。** 复盘给出了"局部变更别触发全量样片窗口"(still/window),但没提**变更点之后区间重渲染**:CTA 在尾部时,用 Remotion `--frames` 从变更点渲到尾 + 复用前段,能把 24s 样片级迭代降到秒级(局限:变更点若移动时间线,则从变更点起整体重渲,仍是部分收益)。
3. **渲染速度本身没有优化项。** 900 帧 full render 76.2s(≈11.8fps),5 次样片每次 ~24s。P1-3 只管稳定性,没管速度:样片可用 fast 编码档(`crf`/`preset` 分档,现有 `video_compose` 已支持这两个参数,只是没有"样片档/full 档"策略化)。
4. **用户审核体验只覆盖了"批准原子化",没覆盖审核本身。** 且方案没引用已存在的资产:
   - `docs/superpowers/specs/2026-08-15-backlot-operator-workbench-design.md`(定稿,已定义两道 Gate、中文业务视图、影响预览、revision);
   - `backlot/operator_reviews.py` 的 `ReviewService.decide()` 已能 approve/reject approval bundle 并写 checkpoint。
   方案应落在"实现该 spec + 补 4 个增量",而不是重新设计。
5. **"视频生成效果"只覆盖交付质量,没覆盖创意质量反馈。** 5 轮返工的 cause(裁切/蒙版/CTA/空白帧/被拒 claim)没有被分类进评价体系——这正好接上 `docs/superpowers/specs/2026-08-17-video-quality-business-alignment.md` 的 issue tags(weak_offer/late_cta/unsafe_text…)与归因表。返工原因应该成为下一版 brief 的输入。
6. **四维遥测(§8 L166)只是采集要求,没进 P0-1 事件 schema。** 第一天不定字段,后面就要二次重构。且 heartbeat 的 `message` 是自由文本,UI 无法据此区分"等审批 / 重试退避 / provider 排队 / 渲染中"——需要 typed `wait_reason`。
7. **交付顺序缺基线对照组定义。** "渲染时长下降至少 50%"没有说明基线是 5×24s 样片、76.2s full、还是同变更的端到端时长;应定义"相同局部变更(如仅改 CTA 文案)前后各 3 次的端到端对比"。

---

## 2. 优化升级方案(按四个目标)

### 目标 ①:执行效率(时长)

| # | 工作 | 内容 | 预期收益 |
|---|---|---|---|
| E1 | **关键路径纪律 + 断点恢复协议**(agent 规则,零代码,当天生效) | 生产运行内禁止基建支线;每阶段 checkpoint 附 `next_action` 指令;研究类工具并行调用(本次 scene_detect/frame_sampler/audio_energy 本可并行) | 消灭 ~5.5h 桶中的支线与恢复重推导 |
| E2 | **P0-1 事件合同(含 typed wait_reason + 四维遥测字段)** | 在复盘 §5 的 schema 上增加:`wait_reason ∈ {waiting_user, retry_backoff, provider_queue, rendering, orchestrating}`、`machine_ms`、`approval_wait_ms`、`retry_count`、`cost_reservation_id`;5–10s heartbeat | 让时长可归因,是后续一切时长优化的前提 |
| E3 | **渲染梯度 + 变更路由**(P1-1 升级) | `still → window → sample → full` 四级;still/window 是 **agent 内部自检门**(用户只见 sample/full);CTA/裁切/字幕类局部变更默认只跑 still/window,change impact 判跨镜头才升级 | 消灭"局部问题触发 24s 样片"的主要来源 |
| E4 | **变更点区间重渲染 + 样片快档** | 变更点在尾部:Remotion `--frames` 从变更点渲到尾 + 复用前段 concat;变更点移动时间线:从变更点起整体重渲;样片用 fast 编码档(crf/preset 分档),full 保持质量档 | 尾部 CTA 迭代从 ~24s → 秒级;full 前迭代成本再降 |
| E5 | **稳定 runtime profile**(P1-3) | 机器级 profile(Chrome 路径/bundle hash/可靠 concurrency/frame timeout);已知崩溃组合不再盲试;concurrency=1 + per-frame retry | 减少重试烧掉的时间 |

### 目标 ②:视频生成效果

| # | 工作 | 内容 |
|---|---|---|
| Q1 | **source-burned caption 硬门**(P1-2) | `source_media_review` 逐段记 OCR/位置/所有权/claim 结果/处理动作+证据帧;任何 pending/rejected 未定动作 → 禁止 compose;final QA 校验 rejected claim 风险帧 100% 有 action+evidence |
| Q2 | **QA 硬输入** | expected duration/frames 对照 ffprobe(允许明确阈值,如 ≤1 帧封装误差);安全区 0-1 归一化坐标,消除 sample/full 隐性差异;跨镜头 identity 一致性检查(呼应业务对齐稿 §3.1 硬门槛"人物/产品/Logo 一致性") |
| Q3 | **返工原因 → 评价体系**(新) | 每次 sample 返工打结构化 issue tags(weak_offer/late_cta/unsafe_text/blank_frame/crop_mismatch/claim_rejected…),进项目 cost/decision log,按队列聚合后反哺 brief 与策略(接 `2026-08-17-video-quality-business-alignment.md` §3.2/§6) |
| Q4 | **sample 审批加 distinctness/style-drift 检查** | atelier 合同要求;进 sample 阶段的 review_focus,防止 5 轮返工里混入的"看起来像模板"问题留到 full |

### 目标 ③:用户审核前端 UI 体验

| # | 工作 | 内容 |
|---|---|---|
| U1 | **P0-3 原子批准**(复用现有服务) | 基于 `operator_reviews.ReviewService.decide()` 扩展:同 generation 写 approved decision + `checkpoint_sample=completed(human_approved=true)` + `checkpoint_compose=in_progress` + 首条 queued event;验收:点击后 2 秒状态翻转,刷新/重启代理不丢 |
| U2 | **决策收件箱**(新) | 跨项目 `awaiting_human` 视图 + 最近 10 条活动之上加"需要我处理"置顶,替代"只看尾部 10 条活动" |
| U3 | **审核播放器**(新) | sample 内嵌播放;帧级批注(时间戳 + 结构化拒绝原因,8 类对齐业务稿 §4);版本对比(vN vs vN-1 关键帧并排);一键 approve-and-continue |
| U4 | **进度卡**(P0-1 的 UI 面) | 帧 x/y、attempt、ETA、等待原因(typed)、费用预留、heartbeat 过期 >60s 标"需要关注";partial_progress 聚合展示 |
| U5 | **对齐已定稿的 operator workbench 规范** | 两道 Gate、中文业务视图、影响/费用/耗时预览、revision 历史按 `2026-08-15-backlot-operator-workbench-design.md` 落地;本方案只补 U2/U3/U4 + 帧级批注,不重造 |

### 目标 ④:快速/高效(横切)

- **交付顺序**(在复盘 §8 基础上调整):
  0. E1 关键路径纪律(零代码,立即生效);
  1. E2 事件合同(含 typed wait_reason + 四维遥测字段,一次性定死);
  2. U1 审批原子转换(接 ReviewService,改动小收益大);
  3. P0-2 staged view 事务验证;
  4. E3 渲染梯度 + 变更路由;
  5. Q1 caption 硬门 + Q2 QA 硬输入;
  6. E4 区间重渲染 + 样片快档、E5 runtime profile;
  7. U2/U3/U4 审核 UI(在 workbench spec 实施时一并做)。
- **基线先冻结**:74min 空档、~5.5h 人工+编排、5×24s 样片、76.2s full、4 帧人工抽检——升级后逐项对比。
- **对照组定义**:同类型局部变更(仅改 CTA 文案)前后各 3 次,比较端到端时长与人工介入次数。

---

## 3. 基线冻结与对照组(B8)

以下基线来自 `table-mat-mix-v4` 实测复盘,升级前后逐项对比;任何"效率提升"声明必须引用这组数字之一:

| 基线 | 数值 | 来源 |
|---|---|---|
| 研究空档(不可归因) | 74 分钟 | `events.jsonl` 首尾间隔 |
| 人工决策 + 编排 + 基建支线 | ≈5.5 小时(08:28→14:18) | 复盘 §2 |
| 样片重渲染 | 5 次 × 23.86–24.78s ≈ 120.9s | 复盘 §2 |
| full render | 145.18s(首次)、76.20s(受控复现) | 复盘 §2 |
| QA | Quick QA 0.10–3.33s;full QA 2.86s + 2.85s | 复盘 §2 |
| 人工抽帧复核 | 4 帧 | 复盘 §2 |

**对照组定义:** 同类型局部变更(如仅改 CTA 文案/裁切)在升级前、后各执行 3 次,比较端到端时长与人工介入次数;渲染类指标以 76.20s(full)与 ~24s(样片)为基准。

## 3.1 外部审查修复记录(2026-08-17 第二轮)

外部审查提出 6 个 P1 + 3 个 P2,全部修复并验证:

| 审查项 | 修复 | 状态 |
|---|---|---|
| P1-① render_plan schema 不支持 still/window/range | `schemas/artifacts/render_plan.schema.json` 扩展 mode 枚举 + still/window/range 定义(`timeline_stable` const:true 使不稳定 range 计划在 schema 层直接非法) | ✅ 已修复(三模式验证通过) |
| P1-② range 未校验 master / 输出存在即缓存命中 | `_render_range` 校验 master sha256(声明即比对)、probe 对照 plan profile、`previous_timeline_hash` == master.visual_timeline_hash;缓存命中要求输出 + provenance sidecar(cache_key + master_sha256)双匹配 | ✅ 已修复(合成素材实测:sha 不符/profile 不符均拒绝,sidecar 命中才 hit) |
| P1-③ range 双重有损编码 | 前缀与尾段先转无损中间格式(libx264 `-qp 0`,mkv),拼接后仅一次最终编码 | ✅ 已修复(实测拼接输出 60 帧精确) |
| P1-④ 审批自动推进会回退已完成的后续阶段 | `_stage_next_transition` 单调性:下一 stage 已有 checkpoint(任何状态)则完全不写 | ✅ 已修复(新增 2 个回归测试) |
| P1-⑤ 全量测试 4 failed + runner 破坏测试隔离 | 3 个 Remotion adapter 测试改 mock `_run_remotion_command`(新注入点);E2E fixture 补 `caption_policy_revision`(manifest v2 契约) | ✅ 已修复(adapter 测试 12 passed / 0.28s,不再触发真实 Remotion) |
| P1-⑥ 事件合同未覆盖研究/TTS/编排 | `BaseTool` 仪表层为所有工具调用自动发 queued/succeeded/failed run events(machine_ms);AGENT_GUIDE 增加编排心跳契约(agent 用 emit_heartbeat,wait_reason=orchestrating/waiting_user,approval_wait_ms) | ✅ 已修复(B7 升级为「工具级生产接入完成;编排级由技能契约覆盖」) |
| P2-⑦ next_action context_refs 与文档不一致 | schema 将 context_refs 设为 required(minItems 1);审批自动 next_action 带 context_refs | ✅ 已修复 |
| P2-⑧ issue_tags 可选 + 无 producer | decision_log schema 用 if/then 强制 rework_cause/review_rejection 必须带 issue_tags(minItems 1,枚举)+ rework_round;AGENT_GUIDE 决策契约增加强制条款 | ✅ 已修复 |
| P2-⑨ review-notes 绕过原子事务 | review-notes 走 ProjectCommitStore 事务(lock + audit manifest + outbox drain),materializer 原子追加到项目根 review_notes.jsonl | ✅ 已修复 |

## 3.2 第二轮审查修复记录(2026-08-17)

第二轮审查提出 5 个 P1 + 2 个 P2,全部修复:

| 审查项 | 修复 | 验证 |
|---|---|---|
| P1-① Remotion 进度写在 stdout 被丢弃 | `_run_remotion_command` 双流(stdout+stderr)reader 线程 + 统一解析器(`Rendered N frames`/`frame N/M`/`(N/M)`/bare `N/M`/`NN%`,含比例噪声守卫);stderr 仅作诊断 | 新增 4 个真实子进程测试(stdout 进度进 terminal event;失败时 stderr detail 透出) |
| P1-② review-notes materializer 恢复不幂等、吞其他流、忽略 Idempotency-Key | 保留 `_outbox_id` 并按其去重;`idempotency_key` 参与去重;非 review_notes 流(含 events)委托 canonical drain(项目 events.jsonl / operator 目录);API 读取并绑定 Idempotency-Key;state 读取时剥离 `_outbox_id` | 新增 4 个恢复测试(同 outbox_id 重放不重复、同 key 不重复、events 流不丢、两笔同 key 事务只落一行) |
| P1-③ next_action fail-open | `write_checkpoint` 对新增 in_progress/awaiting_human 缺 next_action 直接抛 `CheckpointValidationError`(读取旧 checkpoint 兼容);`_approval_input_hash` 排除 next_action(修复两阶段写自 supersede) | 更新 10 处受影响测试 + 新增 fail-closed 测试;全量绿 |
| P1-④ range 缓存不验证输出本体 | sidecar 记录输出 `output_sha256` + 结构探针(时长/分辨率/fps);缓存命中须 key + master sha + 输出 sha + 探针四重匹配 | 新增 5 个 range 测试(含篡改输出→miss→重渲修复) |
| P1-⑤ 工具级长调用无周期心跳 | `BaseTool` 仪表层 5s 心跳 worker 线程(queued→running→terminal,machine_ms) | 新增慢工具测试(5.8s 调用产生 ≥1 条 running 心跳) |
| P2-⑥ 拒绝路径不产生质量反馈 | `ReviewService.decide` 拒绝必须带 `issue_tags`(枚举,API fail-closed);同 generation 向 decision_log 追加 `review_rejection` 决策(自动 rework_round 递增);board.js 收件箱增加「拒绝并要求返工」+ 中文标签选择器 | 新增 3 个 producer 测试(无标签拒绝、标签落库、rework_round 递增) |
| P2-⑦ atelier still 继承全分辨率 scale | still 路由从计划强制 0.5 scale(复制决策对象,绝不继承 bespoke.scale=1.0) | 新增回归测试(`--scale=0.5` 且无 `--scale=1`) |

### 3.3 第三轮审查修复记录(2026-08-17)

| 审查项 | 修复 | 验证 |
|---|---|---|
| sample/window 显式路径误命中旧缓存 | 增加按 mode 隔离的 provenance sidecar，命中时同时校验 cache key 与输出 SHA | 同一路径切换 props hash 强制重新渲染 |
| range 音频 fail-open | 声明音频时强制文件存在并校验 SHA，缺失或不匹配立即失败 | 缺文件、SHA 不符两条 RED→GREEN |
| range 未校验精确帧数 | mux 后 probe 帧数必须严格等于 `totalFrames`，provenance/cache hit 同样校验 | 短尾段拼接被拒绝，正常 60 帧路径通过 |
| 拒绝审核破坏 decision log hash | 事务内统一经 `write_artifact_atomic(..., sink=...)` 重新附加并验证 v2 hash | `verify_hashes` 回归测试通过 |
| next_action fail-closed 破坏旧调用方 | 模拟、截图脚本及 checkpoint 协议示例全部补 resume directive | 脚本编译与完整测试通过 |
| BaseTool 与 Remotion 产生双 run_id | 内部进度工具复用外层 run id，并关闭对应通用 heartbeat | 单次调用事件流只有一个 run id |
| review-note 幂等冲突假成功 | 事务锁内、提交前比较语义字段；同 key 不同正文返回冲突，outbox 仅负责可恢复投递 | 重放/冲突/恢复测试通过 |
| 前端审批绕过版本校验 | awaiting state 下发 subject version/hash，前端回传，API 缺字段 fail-closed | API 与状态投影回归测试通过 |

**完整回归:** `1401 passed, 11 skipped, 1 subtest passed`。

## 4. 一句话总评

复盘把问题看对了(缺控制回路、缺可归因性),但升级方案偏"观测"而轻"缩短":本方案在其 P0/P1 之上补了**关键路径纪律、区间重渲染、样片快档、返工原因入评价体系、审核 UX 接既有 workbench 规范**五块,使四个目标都有具体抓手,而不是只让下一次"看得见慢在哪"。

## 附录:缺口拆分后的 Bug 登记表(8 项)

§1.2 的 7 条缺口中,第 1 条拆为两个独立 bug,共计 8 项;与复盘自身的 P0-1/2/3、P1-1/2/3 的对应关系见「合并到」列。

| # | Bug | 现象/证据 | 修复 | 涉及文件 | 工作量 | 目标 | 合并到 | 状态 |
|---|---|---|---|---|---|---|---|---|
| B1 | 关键路径纪律缺失 | ~5.5h 桶中 sample-tts 基建支线插进生产主线 | agent 规则:生产运行内禁止基建支线,基建独立 branch + 发布门 | `AGENT_GUIDE.md`(新增「关键路径纪律」节) | 小(零代码) | ① | 新增(E1) | ✅ 已实现 |
| B2 | 断点恢复靠重新推导 | 74min 空档;每次会话恢复重新读文件猜状态 | checkpoint 增加 `next_action` 指令(schema + lib + 协议 skill),恢复时直接执行 | `schemas/checkpoints/checkpoint.schema.json`、`lib/checkpoint.py`、`skills/meta/checkpoint-protocol.md` | 小 | ① | 新增(E1) | ✅ 已实现 |
| B3 | 局部变更触发全量样片窗口 | 5 次连续 sample compose ×~24s | still/window 层 + change impact 路由(agent 内部自检,用户只见 sample/full) | `lib/render_plan.py`(validate_window/validate_still_frames/RENDER_GRADIENT)、`tools/video/video_compose.py`(_render_stills/_render_framed_window)、`skills/pipelines/cinematic-fast/compose-director.md` | 中 | ①④ | P1-1(E3) | ✅ 已实现(单元测试通过;真实 E2E 待下次生产运行) |
| B4 | 无区间重渲染 / 样片快档 | full 76.2s(≈11.8fps),尾部 CTA 变更也全量重渲 | range 路由:Remotion `--frames` 变更点重渲 + ffmpeg 帧精确前缀拼接(已验证帧精确);渲染心跳进 events.jsonl | `tools/video/video_compose.py`(_render_range/_run_remotion_command,skip_final_review 尾段豁免) | 中-大 | ①④ | 新增(E4) | ✅ 已实现(拼接机制用合成素材验证帧精确;真实 E2E 待下次生产运行) |
| B5 | 审核 UI 只覆盖批准原子化 | board 只显示尾部 10 条活动;无决策收件箱/帧级批注/版本对比;未引用既有 workbench 规范 | U4 进度卡(backlot/state.py `_collect_run_ops` + board.js 进度卡,>60s 无心跳标「需要关注」);U2 决策收件箱(awaiting_human 置顶+批准按钮);P0-3 审批原子转换(operator_reviews.py 同 generation 写 decision+checkpoint+下一 stage in_progress(带 next_action)+queued run event);U3 审核播放器(样片视频+静帧网格+双版本并排+review-notes 端点);活动流放宽到 30 条并入 run events | `backlot/state.py`、`backlot/state_cache.py`、`backlot/operator_reviews.py`、`backlot/operator_routes.py`、`backlot/ui/board.js`、`backlot/ui/board.css` | 大 | ③ | P0-3 + 新增(U1-U5) | ✅ 已实现(tests/backlot 154 passed;TestClient 冒烟:state 端点返回 run_ops/next_action/review_notes/awaiting 字段,真实项目不报错;board.js 语法检查通过) |
| B6 | 创意返工原因不入评价体系 | 5 轮返工(裁切/蒙版/CTA/空白帧/claim)无结构化 cause | decision_log 增加 `issue_tags` + `rework_round` + `rework_cause`/`review_rejection` 类别 | `schemas/artifacts/decision_log.schema.json` | 小-中 | ② | 新增(Q3) | ✅ 已实现 |
| B7 | 遥测字段与 wait_reason 不进事件 schema | 四维遥测只是"采集要求";heartbeat 只有自由文本 message | 事件合同 v1:`schemas/events/run_event.schema.json` + `emit_run_event`/`emit_heartbeat`(typed wait_reason + machine_ms/approval_wait_ms/retry_count/cost_reservation_id) | `schemas/events/run_event.schema.json`、`lib/events.py` | 小(随 schema) | ①④ | P0-1(E2) | ✅ 已实现 |
| B8 | 无基线对照组 | "渲染时长下降 50%"没有可验证的对照组定义 | §3 基线冻结章节 + 对照组定义 | 本文档 | 小(零代码) | ④ | 新增 | ✅ 已实现 |

**与复盘 P 项的合并关系:** 复盘 P0-1→B7、P0-2(独立,staged view)、P0-3→B5、P1-1→B3、P1-2(独立,caption 硬门)、P1-3(独立,runtime profile)均已在方案 §2 中落地;本表是「新增缺口」的登记视角。

## 5. 样片阶段执行复盘与可追溯性升级

### 5.1 本次样片执行链路

`table-mat-mix-v7` 本次样片执行验证了以下业务链路：

```text
读取已锁定镜头执行单
  -> 准备/复用源素材代理
  -> 编译统一时间轴与字幕方案
  -> 生成 10-15 秒样片
  -> 快速 QA
  -> 原子写入样片产物与 checkpoint
  -> 等待用户确认
```

本次实际结果：7 个镜头全部使用自有素材，参考片未进入成片；代理素材有缓存复用；Remotion 首次因 profile/宽高参数契约不一致失败，第二次因 macOS Chrome 权限失败，授权后成功；字幕初版因短词累积显示造成画面过载，调整为按镜头展示；补齐字幕渲染声明后 QA 通过。样片最终正确停在“已生成，等待确认”，没有自动进入剪辑或正式成片。

### 5.2 应固化为产品能力的内容

| 固化项 | 标准约定 |
|---|---|
| 样片输入 | 只读取已锁定的 `shot_execution_plan`、`asset_plan`、`production_lock` 和审批包，不重新猜素材、区间、时长或镜头任务 |
| 素材边界 | 自有素材优先；参考片只用于分析；参考人物、品牌、水印和原文案不得进入成片 |
| 代理策略 | 统一 540×960/30fps；内容寻址缓存；记录来源 hash、输出路径和 probe 信息；命中缓存可复用 |
| 样片规格 | 300-450 帧、10-15 秒、540×960、30fps，通过 `video_compose` 生成 |
| 质量门 | 时长、帧数、分辨率、素材区间、字幕安全区、音画同步和黑帧/冻结帧通过 quick QA |
| 人工门 | 样片生成成功不等于阶段完成；必须停在 `awaiting_human`，确认后才能进入 edit |
| 产物写入 | `asset_manifest`、`final_props`、`render_plan`、`sample_report`、字幕策略和 checkpoint 使用同一事务及 hash 绑定 |
| 断点恢复 | checkpoint 必须带 `next_action`；恢复时执行已记录的动作，不重新推导项目状态 |
| 决策留痕 | 渲染引擎、字幕模式、音频和其他生产选择发生变化时，追加同一 subject 的 decision revision |

### 5.3 本次临时发挥与必须消除的行为

以下做法只允许作为故障记录，不得成为标准流程：

1. Agent 手工拼装 `edit_decisions`、`asset_manifest`、`final_props`、`render_plan`、`sample_report` 等结构化产物。
2. 通过 `profile=None` 绕过 Remotion 宽高参数错误。
3. 渲染失败后才申请 Chrome 启动权限。
4. 根据画面效果临时切换字幕展示模式。
5. 手工补写 `checkpoint_assets`，修复镜头锁定与素材阶段状态脱节。
6. 手工填写 checkpoint `sink` 或 `next_action.verb`，靠反复试错通过接口校验。
7. 额外留下 `sample_report.raw.json` 等未纳入正式契约的中间文件。

这些问题表明当前业务流程已经成立，但“Agent 决策、系统编排、状态事务、审核展示”之间仍存在边界缝隙。

### 5.4 样片执行对照：让用户知道画面依据和偏差

样片审核不能只显示最终视频，还要回答“前面确认的方案实际执行了多少”。新增面向审核台的业务产物：

```text
sample_execution_trace
```

它与技术性的 `sample_report` 分开：`sample_report` 说明渲染和 QA 是否通过，`sample_execution_trace` 说明参考规则、创意方案、制作剧本、镜头执行单与实际画面的对应关系。

每个镜头至少记录：

| 字段 | 用户能看到的含义 |
|---|---|
| `shot_id` | 镜头编号和业务名称 |
| `status` | 已按方案执行 / 部分执行 / 新增内容 / 尚未进入样片 |
| `planned_basis` | 参考规则、创意目标、剧本段落、镜头执行要求 |
| `actual_execution` | 实际素材、素材区间、时长、字幕、转场和画面文字 |
| `deviation` | 与已锁定方案的差异及原因 |
| `sample_window` | 是否落在本次 10-15 秒样片范围内 |

参考片只追踪已经锁定的业务规则，例如“前 2 秒建立问题”“先场景后产品证据”，不直接向用户展示 fingerprint、hash 或其他工程字段。

样片只覆盖部分镜头时，未出现的镜头必须显示“尚未进入样片”，不能误判为“未执行”。实际新增的镜头、字幕、转场或素材必须自动标记为“新增内容”，由用户决定保留或返工。

审核台在视频旁增加“执行对照”栏，顶部显示：

```text
本次样片覆盖 5/7 个镜头
按方案执行 4 个 · 部分执行 1 个 · 新增内容 0 个 · 尚未进入样片 2 个
```

用户确认样片时，同时确认视频、执行对照和新增内容；只确认视频而未处理新增内容时，仍保持待确认状态。

### 5.5 产品化升级计划

#### P0：稳定执行与可追溯

1. 新增统一的 sample orchestrator：读取锁定产物，生成/复用代理，编译时间轴，调用渲染和 QA，原子写入所有样片产物及 checkpoint。
2. 统一 assets 到 sample 的前置条件：镜头执行单锁定与素材 checkpoint 必须在同一事务完成，或统一改为以锁定镜头单作为唯一前置依据。
3. 统一 render profile：代理和样片使用 540×960，正式成片使用 1080×1920，禁止依赖 `profile=None`。
4. 统一字幕/画面文字模型，明确 `word_caption`、`sentence_caption`、`shot_overlay`，Remotion、QA 和审核台消费同一结构。
5. 增加渲染前置检查：Chrome、Remotion、FFmpeg、素材区间、代理、profile、帧数和权限一次性检查。
6. 新增并写入 `sample_execution_trace`，绑定参考规则、创意方案、剧本、镜头执行单、最终时间轴和样片版本 hash。

#### P1：效率与审核体验

1. 代理素材并行处理，展示完成数、缓存命中和预计剩余时间。
2. 审核台提供镜头级执行对照、状态筛选、点击镜头跳转时间点和新增内容处理。
3. 支持按镜头重试，单个镜头失败不重跑全部样片。
4. 自动生成业务审核摘要，隐藏 `final_props`、`semantic_sha256`、`render_route` 等内部字段。
5. 支持按开场钩子、核心证明和参考节奏自动选择样片窗口，而不是固定从 0 秒开始。

#### P2：扩展和度量

1. 将口播、音乐和补位生成接入同一套资产编排，并明确真实素材与“生成演示”的来源标记。
2. 支持执行对照版本比较和关键帧并排查看。
3. 统计按方案执行率、新增内容率、部分执行率、代理缓存命中率、样片耗时、QA 返工率和首次确认通过率。

### 5.6 验收标准

- 样片只覆盖 5/7 个镜头时，另外 2 个显示“尚未进入样片”。
- 素材、区间、时长和画面任务与锁定镜头单一致时显示“已按方案执行”。
- 只完成部分画面任务时显示“部分执行”并说明缺失项。
- 新增字幕、转场、素材或镜头时显示“新增内容”，可保留或要求返工。
- 用户确认后，样片、执行对照、decision 和下一阶段 checkpoint 一次事务提交。
- 刷新或重启后，样片版本与执行对照版本保持一致。
- 旧项目没有执行对照产物时仍可打开，但审核台明确显示“暂无执行对照”。

## 6. 相关文件

- 复盘原稿:`docs/reports/2026-08-17-table-mat-mix-v4-process-technology-review.md`
- 事件流:`lib/events.py`;UI 活动:`backlot/ui/board.js`;审批服务:`backlot/operator_reviews.py`;QA:`tools/video/final_qa.py`;事务:`backlot/project_commit.py`
- 运营工作台规范:`docs/superpowers/specs/2026-08-15-backlot-operator-workbench-design.md`
- 业务评价体系:`docs/superpowers/specs/2026-08-17-video-quality-business-alignment.md`

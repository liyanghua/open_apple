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

## 3. 一句话总评

复盘把问题看对了(缺控制回路、缺可归因性),但升级方案偏"观测"而轻"缩短":本方案在其 P0/P1 之上补了**关键路径纪律、区间重渲染、样片快档、返工原因入评价体系、审核 UX 接既有 workbench 规范**五块,使四个目标都有具体抓手,而不是只让下一次"看得见慢在哪"。

## 附录:缺口拆分后的 Bug 登记表(8 项)

§1.2 的 7 条缺口中,第 1 条拆为两个独立 bug,共计 8 项;与复盘自身的 P0-1/2/3、P1-1/2/3 的对应关系见「合并到」列。

| # | Bug | 现象/证据 | 修复 | 涉及文件 | 工作量 | 目标 | 合并到 |
|---|---|---|---|---|---|---|---|
| B1 | 关键路径纪律缺失 | ~5.5h 桶中 sample-tts 基建支线插进生产主线 | agent 规则:生产运行内禁止基建支线,基建独立 branch + 发布门 | `skills/meta/`(新规则) | 小(零代码) | ① | 新增(E1) |
| B2 | 断点恢复靠重新推导 | 74min 空档;每次会话恢复重新读文件猜状态 | checkpoint/decision_log 增加 `next_action` 指令,恢复时直接执行 | `lib/checkpoint.py`、director skills | 小 | ① | 新增(E1) |
| B3 | 局部变更触发全量样片窗口 | 5 次连续 sample compose ×~24s | still/window 层 + change impact 路由(agent 内部自检,用户只见 sample/full) | `lib/render_plan.py`、`tools/video/video_compose.py` | 中 | ①④ | P1-1(E3) |
| B4 | 无区间重渲染 / 样片快档 | full 76.2s(≈11.8fps),尾部 CTA 变更也全量重渲 | Remotion `--frames` 变更点重渲 + concat;crf/preset 样片/full 分档 | `tools/video/video_compose.py` | 中-大 | ①④ | 新增(E4) |
| B5 | 审核 UI 只覆盖批准原子化 | board 只显示尾部 10 条活动;无决策收件箱/帧级批注/版本对比;未引用既有 workbench 规范 | 落地 08-15 workbench spec + U2/U3/U4 增量 | `backlot/ui/board.js`、`backlot/operator_reviews.py` | 大 | ③ | P0-3 + 新增(U1-U5) |
| B6 | 创意返工原因不入评价体系 | 5 轮返工(裁切/蒙版/CTA/空白帧/claim)无结构化 cause | 返工打 issue tags 进 decision_log,聚合后反哺 brief | `schemas/artifacts/decision_log.schema.json` | 小-中 | ② | 新增(Q3) |
| B7 | 遥测字段与 wait_reason 不进事件 schema | 四维遥测只是"采集要求";heartbeat 只有自由文本 message | P0-1 事件合同 v1 直接定死 typed `wait_reason` + `machine_ms`/`approval_wait_ms`/`retry_count`/`cost_reservation_id` | `lib/events.py` | 小(随 schema) | ①④ | P0-1(E2) |
| B8 | 无基线对照组 | "渲染时长下降 50%"没有可验证的对照组定义 | 冻结基线(74min/5.5h/5×24s/76.2s/4 帧抽检);定义同变更前后各 3 次对照 | 文档 | 小(零代码) | ④ | 新增 |

**与复盘 P 项的合并关系:** 复盘 P0-1→B7、P0-2(独立,staged view)、P0-3→B5、P1-1→B3、P1-2(独立,caption 硬门)、P1-3(独立,runtime profile)均已在方案 §2 中落地;本表是「新增缺口」的登记视角。

## 4. 相关文件

- 复盘原稿:`docs/reports/2026-08-17-table-mat-mix-v4-process-technology-review.md`
- 事件流:`lib/events.py`;UI 活动:`backlot/ui/board.js`;审批服务:`backlot/operator_reviews.py`;QA:`tools/video/final_qa.py`;事务:`backlot/project_commit.py`
- 运营工作台规范:`docs/superpowers/specs/2026-08-15-backlot-operator-workbench-design.md`
- 业务评价体系:`docs/superpowers/specs/2026-08-17-video-quality-business-alignment.md`

# 工作台只读化 + 历史 Runs 最佳实践 + 运营交付分析（2026-08-26）

> 状态：分析文档（未改任何代码）。后续执行项见「执行建议」。

---

## 1. 当前工作台现状盘点（为「只读化 + 只留审批」定位）

### 1.1 现有界面与代码面

| 入口 | 文件 | 现状 | 说明 |
|---|---|---|---|
| `/` 项目列表 | `backlot/ui/index.html` + `library.js` | 项目列表 + **新建项目表单**（含参考素材上传、付费勾选、平台勾选） | 创建入口，本次未点名（保留与否待定） |
| `/p/<project>` **单任务+批量工作台（主）** | `backlot/ui/operator.html` + `operator/app.js`(1783) + `api.js` + `editors.js` + `revisions.js` + `impact.js` + `store.js` + `language.js` | 单任务工作台与**批驾驶舱合一** | 本次改造主体 |
| 旧技术看板 | `backlot/ui/board.html` + `board.js`(1786) | rail/drawer/审批复核/脚本卡/决策/活动流/渲染/故事板/回放条 | 疑似遗留（`/p/` 已不再挂它），待确认是否下线 |
| 认证 | `login.html` + `operator/login.js` | 保留 | 审批角色需要 |

### 1.2 交互清单（operator 工作台，按「去留」分类）

**A. 审批类（应保留——本工作台只留这些）**
- 阶段门审批：script 锁定 / assets creative_lock 门 / sample **五项确认**（`renderSampleConfirmation` 等）
- 批级门与恢复：`batchApproveGate`（已带 `aggregate_revision` + `participants`）、`batchRecover`
- 等待通知：`renderAwaitingNotice`；阶段/进度/预算/警告展示；成片预览（`preview-video`）；质量结论（L1a/评分摘要）；成本展示
- 审计可见性：`access-mark`（可编辑/只读徽标，后端按 permissions 下发）

**B. 编辑/交互类（应移除——未来归 Studio）**
- 草稿链：`fetchDraft/saveDraft/previewDraft/commitDraft`（operator/app.js 顶部 import）
- 类型化编辑器：`renderTypedEditor`（editors.js：research/proposal/script 等 6+ 编辑器）
- 内联编辑：`script-inline-editor`（逐段口播/花字编辑）、`decision-choice`（创意方向/素材/关键卖点逐项选择 + 「查看影响并确认」）
- 修改与重跑：`quoteShotGeneration/createShotGeneration/adoptShotGeneration`、`impact` 预览、`fetchVersions/restoreVersion/revisions`
- 批级选择：`batchSelectForEdit`（选择托盘）、`renderBatchCockpit` 中的驾驶舱按钮
- 其他：`复制给 Code Agent` 指令按钮（导出类交互）
- 阶段抽屉/回放条（技术诊断性质，视觉上应降级或移入「证据」折叠区）

### 1.3 与 Editorial Gallery 设计的关系（spec 2026-08-23）

- 设计定位是**批量审批工作台**（画廊+决策栏+抽屉+托盘+修改并重跑），**非目标**包含「本阶段不替换真实审批后端」。
- 本次只读化是设计的一个**前置子集**：先去掉编辑，把「审批」做成唯一主动作；随后 Studio 按 spec 落地 2.4 决策栏、2.5 抽屉、2.7 托盘、2.6 修改最小路径。
- **真实接入前必闭环（spec 5.2）**：① 批级请求携带 `aggregate_revision` + 每候选 `review_id/subject_version/subject_hash` + 五项确认（当前 `batchApproveGate` 已带 revision/participants，缺口在候选级确认快照与**coordinator prepare/commit/recovery 原子语义**）② `stale/forbidden/validation_failed/needs_recovery` 回放状态 ③ 方向/摘要/证据标签的 schema 或派生规则（当前展示层有，未入 schema）。
- 只读化最低改造面（后续执行）：operator app 按「审批场景白名单」渲染（phase-driven 主按钮），编辑模块按角色/URL 参数关闭；`board.*` 下线或归档；`library` 创建入口与 Studio 的关系待定。

---

## 2. 历史 Runs 全景报告（6 片，寻求最佳实践）

### 2.1 基线数据

| Run | 时长 | 镜/口播 | 阶段重写次数* | events | 渲染成功/失败 | 成本 | L1a | 响度 LUFS/TP | 转场(edit非cut) | 证书 |
|---|---|---|---|---|---|---|---|---|---|---|
| sheet-01 | 16.0s | 8 / 8 | 23 | 792 | 数次 | $0.052 | pass | -15.4 / - | 0/8 | 无 |
| sheet-04 | 28.0s | 14 / 14 | 9 | 562 | 数次 | $0.052 | pass | -14.8 / - | 0/14 | 无 |
| sheet-05 | 40.3s | 21 / 20 | 14 | 1766 | 10 / 1 | $0.053 | pass | -14.2 / -4.5 | 19/21 | ✅ |
| sheet-09 | 40.1s | 21 / 20 | 13 | 1378 | 多次 | $0.053 | pass | -14.1 / -4.1 | 17/21 | ✅ |
| sheet-14 | 58.2s | 30 / 29 | 13 | 1211 | 8 / 3 | $0.054 | pass | -14.2 / -4.2 | 28/30 | ✅ |
| sheet-19 | 42.7s | 22 / 21 | 13 | 980 | 多次 | $0.053 | pass | -13.8 / -4.4 | 18/22 | ✅ |

\* 阶段重写次数 = `history/` 里 checkpoint 版本数（含每轮重构/重渲染）。成本 = manifest total_cost_usd（TTS+SUNO；素材全自有 $0）。

### 2.2 三轮评审修复的代价（可量化教训）

1. **R1 语义错配 + HAP 误命中**：早期表索引错位 + `"HAP"` 误命中占位英文（权重 5.0 压过真实防油 1.2）→ 修 matcher 语义优先 + 显式 slot 动作表。
2. **R2 混音无口播 + True-Peak 超标**：TTS 三位 vs 混音两位编号 → **4 片全部静默口播**（发布级缺陷，靠 code-review 拦截）；双重 BGM 使 TP -0.9 超标 → 去重音乐轨 + loudnorm TP 后处理。
3. **R3 跨阶段漂移 + 无证书 + 转场丢失**：shot plan 为 rebuild 前制品（61/61/88/64 处漂移）→ 键控配对 + 漂移自愈；发布无不可变绑定 → 交付证书；edit_decisions 全 cut → 转场 token 派生。

**代价**：R1/R3 各引发 4 片**全量重渲染一轮**（≈每轮 1.5–2h 计算）；R2 引发混音+重渲染一轮。若 R1 的键控契约与 R2 的命名契约在首批就用上，预计省 2 轮全量重渲染 + 4 片重新认证 ≈ **3–4 小时机时**。

### 2.3 效率结构（已实测的单片耗时分布）

| 阶段 | 40s 片 | 58s 片 | 说明 |
|---|---|---|---|
| 研究/提案/剧本/场景（内容） | 一次编写跨片复用 | 同左 | 共享研究；剧本为模板级文案表 |
| 媒体管线（proxy+TTS+BGM+混音） | ~15–25min（TTS 4 并发后 ~10min） | ~30min | TTS 为 poll 型，并发是最大杠杆 |
| full 渲染 1080×1920 | ~12–15min | ~25–30min | **必须单并发**（并发→黑帧/超时，实测失败 3+） |
| quick 540×960 | 2–4min | 4–6min | 与 full 串行 |
| QA+L1a+证书 | 2–4min | 3–5min | 已硬门+证书 |
| 门/发布 | <1min | <1min | 证书校验后导出 |

### 2.4 最佳实践（10 条，作为后续批量 SOP 的依据）

1. **键控契约先行**：`template_slot_id → scene_id → section_id → shot_id → asset_id → delivery_version_id` 全部显式 ID 连接；任何下游制品允许 `scene[i]↔slot[i]` 位置推断 = 缺陷。
2. **rebuild 顺序 = 契约顺序**：run_plan 批准 → script+scene_plan（键控+对齐审计字段）→ assets 四制品（漂移则自动同步）→ prep → render → QA(证书) → 门 → publish(证书校验)。禁止「先建 assets 再重建 script」。
3. **音频命名单一契约**：`narration_filename(sec_id)` 三位编号，TTS/混音/清单/渲染共用；缺音频即阻断。
4. **幂等=内容指纹**：proxy/BGM/mix 用 `.prep.json`（源 bytes+参数+输出 hash），TTS 用 `.lock.json`（文案+voice+resource+rate）；exists-only 复用一律禁止。
5. **单并发 Remotion**：同机并发渲染产生黑帧与超时（实测失败 3 次）；超时按帧数缩放（frames×900ms）。
6. **window 预检**：full 前先 30–90 帧 window 层查黑帧/转场边界（本轮暗帧在 full 后才发现，属后验）。
7. **语义对齐进 schema**：`narration_action_key/bound_material_action/narration_material_aligned + template_slot_ref + scene_id` 固化；门禁 = 0 漂移 + 0 未对齐。
8. **交付不可变**：certified delivery（媒体+输入制品+QA 报告 hash 绑定），发布只允许当前证书指针；tamper 即阻断。
9. **内容成本与人工成本解耦**：视频素材全自有（$0），单片现金成本 ≈ $0.05；真正瓶颈是人工审片 → 工作台只留审批（本次需求正是该结论的落地）。
10. **模板内容资产化**：每模板的「逐镜文案表 + 显式 slot 动作表」是内容资产（6 张已标定，37 张待续）；VLM 语义匹配是它们的自动化来源（TODO）。

---

## 3. 代码提交准备（item 3，未执行）

当前 `git status`（草稿分析）：

- **已修改**（跨 2 轮评审）：`lib/`（sample_payload / sample_recovery / recipe_router / template_mainline / template_source_match / template_assets / template_render）、`scripts/`（prep_template_media / gen_template_audio / qa_template_render / publish_template_run / finish_template_sample / finish_template_compose / approve_template_sample / render_template_sample / run_template_mainchain）、`schemas/`（script / scene_plan / shot_execution_plan / delivery_certificate(新) / asset_manifest 未动?）、`remotion-composer/`（Explainer / types）、`tests/`（invariants 新 + 3 个既有文件）、`pipeline_defs/cinematic-fast.yaml`、`PROJECT_CONTEXT.md`、`requirements.txt`、`backlot/shot_generation.py`、`backlot/state.py`、`tools/analysis/technical_validator.py`、`skills/pipelines/cinematic-fast/*-director.md`（6 个）、`grok_image_1.jpeg`。
- **未跟踪**：`.superpowers/`、`docs/EVALUATION_SYSTEM.md`、`docs/art-plan/Reference_Library_Driven_Generation_Plan_2026-08-25.md`、`docs/insight_source/*`（xlsx/csv）、`docs/superpowers/plans/2026-08-26-studio-beta-minimum-upgrade.md`、`scripts/*.py`（新）、`schemas/artifacts/delivery_certificate.schema.json`、`tests/lib/test_template_invariants.py` 等。
- 建议按主题分批提交（示例）：① `feat(template): keyed lineage + alignment invariants`（lib/schemas/tests）② `feat(remotion): dissolve bridge + recipe parity + hard-cut semantics` ③ `feat(scripts): media pipeline with content-fingerprint idempotency` ④ `feat(delivery): certified delivery version + publish gates` ⑤ `docs: run report + studio plan + evaluation system`；`grok_image_1.jpeg` 与 `requirements.txt` 顺带核实（是否夹带/必要）。

---

## 4. 交付一线运营的剩余工作（item 4，对照 Studio Beta 计划）

### 4.1 对照 `2026-08-26-studio-beta-minimum-upgrade.md` 的完成度

| 任务 | 状态 | 差距 |
|---|---|---|
| T1 键控 shot 契约 + 跨阶段不变量 | ✅ 主链路已键控、不变量 12 条、schema 已扩 | 缺 `scripts/rebuild_template_artifacts.py` 迁移命令 + 对 18–24 runs 的 validator 全量跑 |
| T2 manifest 驱动媒体/缓存 | ✅ 内容指纹锁（TTS `.lock.json`、prod BGM 锁、mix/proxy `.prep.json`） | 缺 **audio coverage report 制品**（逐 section→TTS 文件→mix 区间→实测时长）；`asset_manifest` 尚缺 source bytes hash 强要求 |
| T3 转场 parity + 帧级 QA | ◐ recipe parity 已修（edit_decisions 19/21、17/21、28/30、18/22） | 缺 **边界帧亮度巡检**（FFmpeg luma 检查脚本）与 `lib/transition_contract.py` 制品 |
| T4 交付版本不可变 | ◐ 已实现 delivery_certificate + publish 门（tamper 阻断有测试） | 缺 **delivery-version 目录 + current pointer**（当前 final.mp4 是便利导出，非版本 ID 主体）与 `delivery_version.schema` |
| T5 Operator 5 工作流 | ❌ 全部未做（drafts/editors 是研究流遗留，非模板流） | 需要 **Studio**（本需求只读是前置）；`edit` 仍 no-op |
| T6 真实 batch runner | ❌ 目前是脚本编排（prep/render/qa/publish 串脚本） | 缺锁/幂等键/断点/失败隔离/报表 |
| T7 Beta 验收（18–24 runs + 双运营 5 工作流） | ❌ 未开始 | 验收矩阵见 plan |

### 4.2 运营就绪清单（非代码项）

- **环境**：`.env`（DOUBAO/SUNO/DASHSCOPE keys）、素材池路径（`projects/table-mat-mix-v8/...` 硬编码于 `PRODUCT_VIDEO_DIR`——建议改配置）、Remotion `node_modules`、ffmpeg。
- **账号角色**：审批角色（只读+审批点）vs 编辑角色（未来 Studio）；当前 `permissions` 已支持只读标记。
- **规范**：43 张模板 source sheet 的选片规则、违禁词/极限词清单、发布平台档位（1080×1920 30fps 原生）、五确认口径。
- **SOP**：每日批量跑片 SOP（哪 6 模板先跑、预算 $0.05×N、失败升级路径）、异常卡片（TTS error→重试；渲染超时→单并发重跑；证书 hash 不一致→禁止发布并回滚）。
- **培训**：5 工作流演示（Studio 接入后）、审批一次通过标准（对齐字段可读、转场无黑帧、L1a 全绿）。
- **数据**：版本保留策略（delivery versions 保留 N 版）、批报表（成功/失败/恢复/发布计数——runner 提供）。
- **里程碑建议**：M1 只读审批工作台（本需求）→ M2 Studio Beta（五工作流 + batch runner）→ M3 18–24 runs 验收 + 双运营实测。

---

## 5. 执行建议（等确认后开工）

1. **只读化**：先列 operator app 的审批白名单视图（phase → 唯一主动作），编辑模块按权限关闭；确认 `board.*` 是否下线；Library 创建入口去留。
2. **提交代码**：已完成（5 主题 commit：`25aea77` template core / `571cd07` human-AB / `a7f4d87` media+certified delivery / `4c09be7` remotion two-layer+dissolve / `4268e91` docs+validator）。
3. **报告持久化**：本文档已落 `docs/reports/`；后续按第 6 节「可固化资产与代办」推进。

---

## 6. 可固化资产与代办清单（Skills / 代码 / TODO，2026-08-26 汇总）

> 本清单汇集三轮评审 + 批量跑片全过程的历史沉淀：哪些已固化为代码、哪些应固化为 skills、哪些仍是待办。凡标「✅ 已固化」均有对应 commit 锚点。

### 6.1 可固化为 Skills（技能文档——供未来 agent 直接消费，未创建）

| 建议 skill | 内容 / 依据（历史事件） |
|---|---|
| `skills/meta/template-run-adaptation.md` | 从 43 模板库做逐镜适配：overlay/ASR → 逐镜文案表 → **显式 slot 动作表**（`SLOT_ACTION_BY_TEMPLATE`，6/43 已标定）→ 素材绑定；含反模式：HAP 误命中文案、故事线泛化、尾闪帧(<1s)只留花字、素材无该动作→显式 gap |
| `skills/meta/two-layer-captions.md` | 两层字幕渲染契约：calligraphy 指纹（Ma Shan Zheng 104px 左上竖排）+ `narrationSubtitles`（底部安全区）+ **single-mix 音频规则**（成品混音不再叠第二音乐轨→TP 修复）+ recipe key 重映射 scene→cut |
| `skills/meta/template-media-pipeline.md` | 媒体管线契约：三位命名 `narration_filename()`、内容指纹幂等（`.lock.json`/`.prep.json`）、TTS overflow/error fail-closed、混音 loudnorm -14 + TP -1.5、BGM 源锁（prompt+model+instrumental） |
| `skills/meta/template-certified-delivery.md` | 交付证书契约：`delivery_certificate` 字段（媒体+输入制品+QA 报告 hash）、publish 门校验、tamper 阻断、「certified delivery version」不可变指针 |
| `skills/pipelines/cinematic-fast/template-compose-director.md` | 模板十步流水（run_plan 批准→script/scene_plan→assets(漂移自动同步)→prep→render(full+quick)→QA(证书)→门→compose→publish），引用 `scripts/` 全链 |
| `skills/meta/cross-stage-invariants.md` | 跨阶段不变量：键控配对（`template_slot_id→scene_id→section_id→shot_id→asset_id→delivery_version_id`）、对齐审计字段、漂移自愈 `shot_plan_drift/sync_assets_artifacts`、门禁=0 漂移+0 未对齐 |
| `skills/meta/remotion-batch-discipline.md` | Remotion 批量纪律：**单并发渲染**（并发→黑帧/超时，实测失败 3+）、超时按帧数缩放（frames×900ms）、full 前先 window 层预检黑帧/转场边界、镜头间 dissolve 桥无暗帧 |

### 6.2 已固化为代码（✅ 完成，含 commit）

- **lib 契约层**：`template_source_match`（语义窗口/精确优先/显式动作表/键控配对）、`template_mainline`（逐模板文案表+对齐 build_script+rebuild_aligned_run+fail-closed advance_to_assets）、`template_assets`（键控 shot plan+漂移检测+同步）、`template_render`（真实资产名+转场 token 派生）、`sample_payload`（两层字幕+recipe 重映射+single-mix）、`recipe_router`（action-match→dissolve）、`sample_recovery`（script 带入）。
- **scripts 全链**（9 个）：`prep_template_media` / `gen_template_audio` / `render_template_sample` / `qa_template_render` / `finish_template_sample` / `finish_template_compose` / `approve_template_sample` / `publish_template_run` / `run_template_mainchain`（瘦包装）。
- **schemas**：script/scene_plan/shot_execution_plan 键控+审计字段扩展；`delivery_certificate`（新）。
- **Remotion**：Explainer Layer4 口播字幕轨、DissolveBridge、默认硬切语义；`types.ts` dissolve 类型。
- **测试护栏**：`tests/lib/test_template_invariants.py`（12 条：素材动作对齐/HAP 护栏/命名契约/recipe⊆cut/QA→发布门/内容hash失效/run_plan 不自动批准/漂移检出+转场 token/TTS 锁/BGM 锁/证书 tamper…）+ 3 个既有测试文件更新。
- **提交锚点**：`25aea77` / `571cd07` / `a7f4d87` / `4c09be7` / `4268e91`。

### 6.3 待办（TODO，按里程碑排序）

**M0 收尾（1-2 天）**
1. ✅ 已完成：5 主题代码提交；`grok_image_1.jpeg` 还原。
2. ⬜ `.gitignore` 收口：`.superpowers/`、`harness_history.html`（当前仅未跟踪，未入库）。
3. ⬜ 四片重跑与证书补齐：sheet-01/04 按新链路重跑（约 1.5h/片），使 6 片全有证书+对齐审计字段。
4. ⬜ 素材池路径配置化：`PRODUCT_VIDEO_DIR` 由环境/配置注入（当前硬编码 `projects/table-mat-mix-v8/...`）。

**M1 只读审批工作台（本次需求本体）**
5. ⬜ operator app 审批白名单视图（phase→唯一主动作），编辑模块按权限关闭。
6. ⬜ 决策：`board.*` 下线归档；Library 创建入口去留。
7. ⬜ 保留项打磨：五项确认、批级通过（revision+participants）、等待通知、成片预览、质量结论。

**M2 Studio Beta（对照 studio-beta plan）**
8. ⬜ **audio coverage report** 制品：逐 section→TTS 文件→mix 区间→实测时长（T1 余量：`rebuild_template_artifacts.py` 迁移命令+18–24 runs validator 全量）。
9. ⬜ **transition 边界帧 luma 巡检**（FFmpeg 帧级检查）+ `transition_contract.py`；纳入 full 前 window 预检。
10. ⬜ **delivery-version 目录 + current pointer**（final.mp4 仅便利导出）+ `delivery_version.schema`；旧版本恢复不可覆盖。
11. ⬜ **template_batch_runner**：锁/幂等键/断点/失败隔离/批报表（当前为脚本编排）。
12. ⬜ Operator 5 工作流（Studio 编辑侧）+ `edit` 不再是 no-op。
13. ⬜ 数据库/API 闭环：coordinator prepare/commit/recovery + stale 回放（spec 5.2 五条）。

**M3 规模化**
14. ⬜ VLM 语义匹配：自动产出 `SLOT_ACTION_BY_TEMPLATE`（当前人工标定 6/43），覆盖全部 43 模板。
15. ⬜ 37 张模板的逐镜文案表+显式动作表补齐（内容资产）。
16. ⬜ sheet-12/34 长模板分段/连播策略（78 镜/155s、44 镜/88s）。
17. ⬜ 18–24 runs 验收矩阵 + 双运营 5 工作流实测（Beta 门）。
18. ⬜ 成本记账全量化（reuse 路径 $0 修正为真实计费；批预算看板）。
19. ⬜ HyperFrames 双 runtime 呈现与锁（proposal 展示权衡）。

**常态维护**
20. ⬜ 6.1 的 7 个 skills 落地（按本轮经验编写）。
21. ⬜ 参考库增量：新模板入库 SOP（43 → N sheet），导入+标定+首片试跑模板。
22. ⬜ QA 基线回归：每次契约变更跑 `tests/lib/test_template_invariants.py` 全量 + `tsc`。

---

## 7. Goldset 基准选定（历史 6 片：L3 效果 × 效率合成）

> 方法：效果 = `video_judge` L3 VLM 创意评价（`l3-v1.0` 八维 0-10，seed=42，frame_count=8，逐片注入实测响度音频事实）；效率 = 现金成本（TTS+SUNO，素材全自有 $0）、成片时长、重写轮次（history/ 版本数）、转场落地（edit 非 cut 数）。5/09/14/19 的 manifest reuse 路径成本记 0，实际付费 ≈ $0.053/片（首次 TTS+BGM 各一次），下表按实付口径统一。

| 成片 | L3 均分 | 单维最低 | hook | cost/pt | 时长 | 重写轮次 | 转场(edit 非cut) | 证书 | 评估 |
|---|---|---|---|---|---|---|---|---|---|
| **sheet-01** | **8.56** | 7.5 | 8.0 | $0.0061 | 16s | 23 | - | 无 | **稳定证明链；无短板** |
| sheet-04 | 8.38 | 7.5 | 7.5 | $0.0062 | 28s | 9 | - | 无 | 异议反驳结构，钩子略弱 |
| sheet-05 | 8.31 | 7.5 | 8.0 | $0.0064 | 40s | 14 | 19/21 | ✅ | 当前管线最佳可复现样本 |
| sheet-09 | 8.06 | **6.0** | **6.0** | $0.0066 | 40s | 13 | 17/21 | ✅ | 开场钩子失效 → Hard Negative |
| sheet-14 | 7.94 | 7.0 | 7.0 | $0.0067 | 58s | 13 | 28/30 | ✅ | 长模板节奏、钩子可再优化 |
| sheet-19 | 7.94 | 6.5 | 7.0 | $0.0067 | 43s | 13 | 18/22 | ✅ | 同 14，钩子与节奏为主攻方向 |

### 7.1 选定结论

- **Goldset（质量/效率双基准）= sheet-01-video1（8.56 分）**
  - 理由：L3 最高、单维无短板（最低 7.5）、单位成本效果最优（$0.0061/分）、16s 证明链结构是模板适配的「标准答案」形态。
  - 用途：作为后续模板产出的**对照基准**（新片 ≥ Goldset 均分且单维 ≥ 7.5 视为达标；`video_judge` 以同 seed 同 rubric 直接可比）。
- **New-benchmark（当前管线最佳实践样本）= sheet-05**
  - 理由：唯一「8.3+ 均分 + 全证书 + 全键控对齐 + 转场 19/21 + 0 漂移」的当前链路产物；是新链路可复现性的基准，而非质量上限。
- **Silver = sheet-04**（异议反驳 14 镜结构，8.38/28s，第二模板形态基准）。
- **Bad / Hard Negative = sheet-09 开场（hook 6.0）**：作为钩子失效反向样本，与 sheet-01 的 8.0 构成对比对，用于 `video_judge` 校准与钩子优化回归测试。

### 7.2 使用方式与注意事项（后续基准化）

1. 固化时机：新片 L1a 全绿后跑同参数 `video_judge`（rubric `l3-v1.0`、seed 42、frame_count 8、audio_facts 注入实测响度）→ 与 Goldset 同表比较；不要跨 rubric/judge 版本比较（评价体系 §3.5）。
2. 多 seed 化建议：正式准入前将单 seed（42）升级为 3 seed 均值（42/7/2026）并把记录入 `evaluation_report.creative_advisory`（当前仅存 /tmp 分析文件）；随机评价器必须记录 model/seed（体系 §3.5 要求）。
3. `gold_sample`（体系 §4.7）校准数据对接：把 sheet-01 记为 **Gold**、sheet-04 记 **Silver**、sheet-09 记 **Bad**（hook 场景）并带 `group_key=模板族`（防同模板泄漏到不同数据集 split）；生成 pointwise/pairwise 标注后供 judge 校准回放。
4. 纳入门禁的保守值：新片 L3 均分 ≥ 8.1（当前 6 片中位 8.19）为「可发布」advisory 参考；≥8.5（Goldset 水平）为「推荐」；≤7.9 且单维 ≤6.5 给出针对性返工建议（钩子/节奏/音频）。
5. 效率护栏（供 runner 接入）：单片付费 ≤ $0.07、40s 片 full 渲染单次 ≤ 20min、重写轮次 ≤ 3（当前历史片 9-23 轮为探索期数据，非目标值）。

---

## 8. 结论（本轮分析一句话版）

模板主链路已从「agent 临场发挥」收敛为「确定性契约 + 脚本工厂 + 证书化发布」，1500+ 单测与 12 条跨阶段不变量背书；剩余工作 = ① 只读审批工作台（人审闭环）② Studio Beta（编辑闭环）③ 批量 runner（规模化）。历史教训（键控先行、指纹幂等、单并发、先预检后全量、发布绑定证书）均已沉淀为本文档 2.4 节最佳实践，可直接作为后续每轮生产 SOP。

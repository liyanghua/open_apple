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

#### 待办增量（2026-08-27 · 三强校验与画面重复）

**P0（标准落地前置）**
23. ⬜ 素材池扩容：6 → 12+（6 动作域 × 2 镜：餐桌生活×2 / 检测×2 / 边角×2 / 刮擦×2 / 擦拭×2 / 铺开×2）——当前 6 片仅 sheet-01 满足 H1-H4，其余全部违规（14 片 59% 占片 + 92 处完全重复窗口）的根因。
24. ⬜ 长模板分段/结构轮换策略（>12 镜模板：N/M 数学不可满足 H1/H2 时，分段成片或卖点组轮换）。
25. ⬜ H1/H2 可行性前置判定（新模板起片前跑 N/M 数学 + 结构检查，写进 template-run-adaptation 流程）。

**P1（校验体系补全）**
26. ⬜ 三强校验接入 `export_top_videos` xlsx（当前仅 `/overview/` 实时展示）。
27. ⬜ VLM 逐帧「画面-文案」自动抽检（当前为文案↔动作断言级；正文字面 ↔ 帧内容一致性需 OCR/VLM 复核；人工抽检降为兜底）。
28. ⬜ 正式 audio coverage report 制品（section→TTS 文件→mix 区间→实测时长；当前为 overview 轻量文件检查）。
29. ⬜ 素材池入池 SOP 落地：media_index + source_review + matrix 桥接 + 语义窗口标定 + H1/H2 冒烟（template-material-pool-design）。

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

### 6.4 本轮新增（2026-08-27）：overview 强校验 + 画面重合度标准

**overview 自动更新**：`/overview/` 每次加载实时计算并展示三组强校验（不缓存、不付费）：
| 校验 | 判定 | 数据源 |
|---|---|---|
| 语义一致（文案=口播=画面） | `semantic_mismatches`：证明词锚点+跨动作 claim+否定/反问豁免 | script + SLOT_ACTION + PROOF_KEYWORDS |
| 画面重复 | `material_reuse_report`（H1-H4/S1-S2，见下） | scene_plan.source_mapping |
| 口播覆盖 | 每个有声 section 存在 TTS 文件 + sample-mix 存在 | assets/audio |

**画面重合度标准（评审定稿）**：
- H1 相邻镜头不得使用同一素材（相邻同素材 = 0）
- H2 单一素材占全片时长 ≤ 33%（30 镜/6 素材理论下限 ≈29%）
- H3 同一素材不得出现**完全相同** in-point 窗口（分配器 fallback 已修复：无重叠位时选起点差 ≥0.75s 的差异化窗口；杜绝“同一帧画面复用”）
- H4 同素材相邻窗口起点差 ≥ 0.75s（微变化，允许部分重叠）
- S1（软）单素材复用次数 ≤ ceil(镜数/素材数)；S2（软）同素材两次使用间隔 ≥3 镜

现状（6 片实测）：**仅 sheet-01 通过**；05 重复窗口 25 处/占片 50%；04 =3 处/43%；09 =40%/相邻同素材 10；14 =59%/18 次复用（完全重复 92 处，最严重）；19 =53%/12 次。达标路径：①素材池扩充（6→12+，补生活/检测/边角/刮擦/擦拭/铺开各 2 镜头）②长模板（30 镜）按段落成片或结构轮换 —— 否则 H1/H2 在数学上不可满足。

**固化/技能建议（本轮新增）**：
- `skills/meta/template-platform-standards.md`：语义一致性 PROOF_KEYWORDS/反问豁免 + 画面重合度 H1-H4 标准 + 口播覆盖校验（三强校验作为模板片“准入三件套”）
- `skills/meta/template-material-pool-design.md`：素材池按“动作域 ×2 镜头”设计（最小可证明集），含复用数学（N 镜/M 素材 → H1/H2 可行性判定）

**临时发挥待补齐（代办增量）**：
- P0 素材池扩容（6 素材是 H1/H2 被违反的根因；需采购/拍摄 生活细节×2、检测读数×2、边角处理×2、刮擦×2、擦拭×2、铺开×2）
- P0 长模板分段策略（30+ 镜：分段成片或结构轮换）
- P1 三强校验接入 export xlsx（当前仅 overview 实时展示）
- P1 VLM 帧级“画面-文案”自动抽检（当前校验为文案↔动作断言级；正文字面一致性需逐帧 OCR/VLM）
- P1 正式 audio coverage report 制品（当前 overview 轻量文件检查）
- P2 视觉相似度度量（同素材多窗口的画面 embedding 相似度，替代“起点差”近似）

### 6.5 本轮（2026-08-28 后段）：VLM 标定量产 + 新模板全自动试产线

**目标**：把「新模板出片」从人工编表 + 手工引导升级为 VLM 全自动链路，并以 3 部新片验证。

**成果**：
| 成片 | 模板 | 链路 | 结果 |
|---|---|---|---|
| 视频48_岩板桌架 | sheet-42 | VLM 标定 → 严格子集契约（8镜/16.0s） | 标准✅ 严格✅ L3 **8.23**，★正式版指认 |
| 视频17 | sheet-15 | VLM 标定（域均衡 v2）→ 直跑（9镜/18.0s） | 标准✅ L3 **8.47**（严格微超：S5' 间隔） |
| 视频23 | sheet-20 | VLM 标定 + 1 步人工换槽（10镜/20.0s） | 标准✅ L3 **8.44**（严格微超：S1'/S2'） |

**关键能力**：
- `calibrate_template.py --mode vlm`：DashScope 文本分类，整表一次调用（slot→6 动作域+置信度+理由），0.85 阈值分档；**批量 35/35 成功**，43 主模板全部标定（readiness 未标定阻断=策略 C，存量清零）；
- 域均衡提示词（同域≤2/邻域不同/语义优先）单轮即让 15/20 从 COMPRESS → DIVERSIFY_LIMITED（判定可信度拐点）；
- 接线统一 `rows_for_template`（命名表→按动作生成兜底，VLM 模板零接线）；`--repair-swap` 聚簇修复（H1-类可修 / S2'-类归因 planner/素材）；
- 审批后自动刷新 checkpoint 信封（每月痛点根治）；发布门 strict_gate 正式版准入全域生效。

**判级全景（43 主模板）**：DIVERSIFY_LIMITED 4（01/15/20/22）+ 可行严格子集 2（04/42）+ 其余真判（素材/换序 backlog）；sheet-12（78 镜）等长模板=分段议题（planner 枚举上限 N≤18 已防护）。

**坑与修复（归档）**：write_calibration 三节文件丢节（已重构）；VLM 模板行错位（rows_for_template）；for-else 提前退出（swap）；正则/转义污染（两处）；`DASHSCOPE_API_KEY` 子 shell 环境（source ~/.zshrc）；信封刷新时机（4 例 → 自动化）。

**backlog 更新**：15/20 严格微调（换槽/子集）→ 计 1 轮；22 = S2'-类（需素材/换序）；素材池扩容（桌角×2 等，解锁 09 原结构与更多 LIMITED）；hook 优化（新片 weakest 仍为 hook，8.47/8.44/8.23 均受此限）；43 模板抽检制品化 + VLM 逐帧（P2）；治理（重发工单/Goldset 白名单复核周期）。

### 6.6 本轮（2026-08-28）：批量审批工作台收尾验收

Phase 0–3 已完成：批量与单条复用同一审批事实；批量提交有 visibility fence、统一 outbox 放行与恢复；批量选择会重读评价报告并校验 `evaluation_hash`；prepare 路径只校验、不在读取时补建审批记录。

Phase 4/5 收尾项：

- 批量候选入口携带批次上下文，单条复核提供返回批量总览；快速查看为只读，不提供审批动作。
- 候选卡、批量主动作、选择区、错误提示均提供稳定 `data-testid`，桌面/移动端场景覆盖混合阶段、媒体失效、报告降级、批次与候选不匹配、权限变化和刷新超时。
- 一线可见页面清理产品品牌词和内部枚举；技术字段仍只保留在 API/schema 或制作记录折叠区。
- 本轮不纳入自动化浏览器验收；按桌面 1180px、平板 900px、移动 390px 手动检查批量总览、快速查看、单条复核、返回批量、媒体失败、报告降级和权限变化。

验证记录：`PYTHONPATH=. .venv/bin/pytest -q tests/backlot` → **309 passed, 1 skipped**；`node --check` 覆盖 operator 前端模块。完整 `tests/lib` 需要仓库外部的 gitignored `projects/` 运行数据，缺失时属于环境前置条件，不计入本轮回归结论。

### 6.7 本轮原型对照回访：单条工作台仍需视觉升级

对照基准：`.superpowers/brainstorm/49441-1787886628/actual-mainline-review.html`；真实页面：`/p/table-mat-batch-002-c1?from=batch&batch_id=table-mat-batch-002`。

本轮确认的后端和交互基础已经存在：批次上下文、返回批量、快速查看只读、审批只读模式、三个人审门、五项样片确认、批量两步和异常恢复均有实现或契约测试。但真实单条页面首屏仍是旧的“项目总进度 + 左侧九步导航 + 中间阶段内容 + 右侧当前需要处理”，与原型的“当前确认说明 + 轻量九步进度 + 材料列表 / 视频说明 / 五项确认”存在结构性差距。

需要在下一阶段完成的单条升级：

- 用“现在需要你确认什么”替代项目进度和效率承诺作为首屏焦点；
- 把视频播放器、当前产物、确认项和确认后流程固定为审批阅读顺序；
- 将 `result_first`、`judge`、`L1a`、`VLM advisory`、文件路径等技术内容移入“制作记录”；
- 审批模式只保留“退回修改”和“确认通过，继续制作”，不渲染编辑器、暂存修改和影响预览；
- 复用现有审批事实和 API，不新增单条状态或视觉之外的后端协议。

专项计划：`docs/superpowers/plans/2026-08-28-single-review-workbench-visual-upgrade.md`。本阶段仍按 1180px、900px、390px 三档手动验收，不引入 Playwright 作为完成门。

### 6.8 单条工作台阶段与产物融合实施记录（2026-08-30）

已完成单条审批展示层升级：

- operator store 统一维护 `reviewGateId / selectedStageId / selectedArtifactId`；阶段和材料浏览写入 URL，刷新和浏览器返回可恢复，产物版本或 `subject_hash` 变化时回到当前确认门；
- 新增统一九阶段产物适配器，复用 operator-state 的脚本、分镜、清单、样片、成片和交付数据，缺失/处理中/失败均返回业务状态；
- 审批页不再直接调用旧阶段 renderer；左侧材料、中间单材料详情、右侧当前门/只读状态由同一 view model 驱动；
- 阶段、材料、时间片段改为语义化键盘操作，补充选中态、焦点态和异步错误提示；技术 URL、哈希、报告元字段不回流到主界面；
- 单条页面保持现有审批 API、审批事实和批量串联，不新增编辑器或 Studio 能力。

验证记录：`PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot` → **340 passed, 1 skipped**；`node --check` 覆盖 `store.js`、`approval_model.js`、`approval.js`、`app.js`。按用户约定未引入或运行浏览器自动化；1180px、900px、390px 的视觉主线走查仍由业务方手动确认。

### 6.9 历史成片总览新增「批量成片整体报告」（2026-08-31）

按业务要求，把「当前批量成片的整体报告」落到 `/overview/`（历史成片总览）首屏，只读聚合、不触发任何付费调用（L3 仅读制品，与页面既有口径一致）。

- 新增 `backlot/overview_state.py::_batch_report()`：聚合已发布成片（发布数/评分数/证书数/L1a 通过数/档位分布/TOP3/L3 均分/单维短板分布）、发布版本（正式版/已取代/基准/严格档全绿/豁免白名单）、模板池（50 条模板记录、43 张主模板、全部标定、容量判定分布）、产出覆盖（9/43 主模板已出片、34 张未产出）、素材缺口清单（动作域数 + P0 数）与在制状态；
- 新增 `_inflight_runs()`：扫描未完成 publish 的模板 run，按「进行中（plan 已批）」「已备未启动（plan 待批但有推进）」「占位未启动」三档分类，业务阶段/状态文案复用 `backlot/operator_language.py`；当前快照 = 1 条进行中（sheet-22-video27 停在「确认制作准备」等待确认，08-28 13:00）、2 条已备未启动（sheet-12/34，已推进到看分镜）、7 个占位 run；
- 修正已过时的口径文本：`known_limits` 原写死「sheet-01/04 无交付证书」，现改为按当前制品动态生成（当前 17/17 部均已绑定交付证书，该条不再出现）；
- 页面：`backlot/ui/overview.html` 新增「批量成片整体报告」区块（6 张 KPI 卡 + 短板/缺口明细 + 自动提示），`overview.js::renderBatchReport()` 渲染，`overview.css` 增补卡片样式；`node --check` 通过。

当前快照（2026-08-31，只读）：17 部已发布成片全部有 L3 评分与交付证书、L1a 全部 pass；L3 均分 8.23，推荐 1（sheet-01·视频1）、达标 10、观察 6（含短板 4，16/17 部短板均为 hook_clarity）；正式版 7 部（严格档全绿 6 + Goldset 豁免 1：sheet-01）、已取代 5、基准 5；主模板容量：受限 4 / 需压缩 29 / 素材缺口 10；素材缺口清单 4 个动作域均 P0，影响 23 个模板。

验证：`PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot` → **346 passed, 1 skipped**；`tests/backlot/test_overview_view.py` 增加整体报告字段、进行中/占位分类与动态口径断言。

### 6.10 九阶段产物完整性回访（2026-08-31）

本次回访针对“老工作台其他阶段的产物是否完整迁移到单条审批工作台”进行代码级对照。结论是：统一浏览状态和三栏审批壳已接入，但九阶段产物适配尚未达到业务验收标准。

**确定性问题：**

- 分镜“动作和时长”把源素材区间当成成片时间轴，存在语义错位；
- 创意方案未呈现导演总控单；
- 脚本仍以原始 sections 递归展示，存在工程字段和口播/字幕重复；
- 制作准备缺少生成任务预览、失败原因、实际费用和完整口播字幕内容；
- 样片口播字段未完整投影，`caption_diff` 和 `creative_rule_diff` 未进入审批材料；
- 精剪缺少“是否可以进入成片检查”的只读结果；
- 成片检查容易退化为单一 `qa_status`，评价报告细节没有完整呈现；
- 交付材料可能只显示 package files，平台状态、发布结果、下载动作和 QA 证据不完整；
- 通用递归渲染无法同时承担镜头、时间轴、检查项、生成任务和交付文件的业务阅读。

**回归结果：**

- `node --check backlot/ui/operator/store.js backlot/ui/operator/approval_model.js backlot/ui/operator/approval.js backlot/ui/operator/app.js`：通过；
- `tests/backlot/test_operator_ui_contract.py` + `tests/backlot/test_operator_single_review.py`：通过；
- `tests/backlot/test_operator_artifact_model.py`：**5 passed / 1 failed**，失败为材料 ID `risks` 与既有测试期望 `source_risks` 不一致，说明阶段材料契约存在命名漂移。

**处理决定：**

1. 保留 Phase 0–5、批量/单条事实串联和基础审批壳的历史完成记录；
2. 不把“统一适配器已接入”描述为“九阶段产物已完整”；
3. 新增专项计划 `docs/superpowers/plans/2026-08-31-single-review-artifact-completeness.md`，先补齐适配器、只读投影和阶段详情，再执行三档手动验收；
4. 在专项完成前，单条页面继续作为只读查看入口，最终视觉验收保持未完成。

### 6.11 九阶段产物完整性专项实施记录（2026-08-31）

按 `docs/superpowers/plans/2026-08-31-single-review-artifact-completeness.md` 完成 Chunk 0–3 与 Task 4.1：

- **Task 0.1 材料契约**：spec 新增 §9.5 九阶段材料契约表（ID/业务标题/必备字段/媒体动作 + 六条契约规则）；`risks` 规范为 `source_risks`；新增“同一事实只在一处完整呈现、摘要卡不重复正文”契约测试。
- **Chunk 1 阶段适配器**：新增 `compactProposal`（含 `control_plan` 导演总控单、`production_budget`）、`compactScript`（开场/正文/结尾 × 口播/字幕/段落目标/画面重点/节奏/证明要求，工程字段排除，口播/屏幕文字只留数量入口）、`compactScenePlan`（源素材区间与成片时间轴分离）、`compactAssets`（含 `generation_tasks`）、`compactSample/compactEdit/compactCompose/compactPublish`（含 `compose_readiness`、`version_history`、`pending_changes`、`delivery_package`、`qa_evidence`）。
- **Task 1.3 只读投影**：`_sample_editor` 补逐镜计划/实际口播、`caption_diff`、`creative_rule_diff`（来自 `sample_execution_trace` 制品），`operator_state.schema.json` 同步；未改变审批 API。
- **Chunk 2 阶段详情**：`approval.js` 新增 `STAGE_DETAIL_READERS`（35+ 专用阅读器），九类阶段详情分流；`renderArtifactValue()` 降为纯文本 fallback；预览/下载转为播放器与下载动作；统一“未生成/正在准备/资料异常/播放失败”文案。
- **Chunk 3 去重与无障碍**：工程字段只允许出现在 `isTechnicalArtifactKey` 过滤函数内；脚本/字幕/样片对照重复正文断言（`shot_comparison` 不再重复完整字幕）；键盘操作、`aria-live`、`aria-current`、`data-testid` 契约测试。
- **Task 4.1 完整性测试**：九阶段最小 fixture 29 项业务字段断言；分镜时间轴/样片口播/成片检查/交付下载语义测试；缺失/处理中/失败/成片与交付缺失的降级测试（空数据不再产出“ready”空 payload）。

验证记录：`PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot` → **370 passed, 1 skipped, 0 failed**；`node --check` 覆盖 `store.js / approval_model.js / approval.js / app.js / api.js / language.js`。

提交：`2bfd5d1`（overview 批量报告基线）、`708539c`（审批壳基线）、`6748dd5`（文档基线）、`38c15f4`（Task 0.1 契约）、`42d1932`（Task 1.1 proposal/script）、`0c16842`（Task 1.2 scene_plan/assets）、`83727bb`（Task 1.3 sample/edit/compose/publish + 只读投影）、`a638247`（Chunk 2 详情阅读器）、`339bbf4`（Chunk 3 去重/无障碍契约）。

**验收就绪**：九阶段产物完整性前置检查已可执行（见 `docs/reports/2026-08-28-single-review-manual-acceptance-checklist.md` 步骤 0 的逐阶段基线）；按约定，1180px/900px/390px 三档视觉走查由业务方在完整性检查通过后执行，本轮未引入浏览器自动化。

**第二轮：真实数据联调修复（2026-08-31 晚）**。review 指出第一轮以“适配器 fixture 通过”表述“真实链路完成”偏宽，并确认 4 个 P1 断链。本轮修复并闭环：

1. **生成任务真实状态（P1-1）**：`compactGenerationTasks` 改为优先读取 `execution_plan.generation_tasks`（`load_operator_state` 从 `operator/shot-generation/tasks` 真实任务目录注入，注入逻辑抽为 `_inject_generation_tasks` 供生产与测试共享）；按 `proposal_id + shot_id` 关联生成方案，输出任务状态、质量、预览、实际费用、失败原因；`selected_generation_task_id` 与 `task_id` 比较（此前误与 proposal id 比较）；有方案无任务显示“尚未生成”。
2. **样片计划/实际口播分离（P1-2）**：`compactCaptionsVoice` 输出 `planned_*/actual_*` 四列，实际缺失显示“实际口播未提供”，不再静默回退计划口播；音轨存在但无逐镜文本时提示文本核对入口。
3. **参考片段证据保留（P1-3）**：`compactScenePlan` 保留 `description/start_seconds/end_seconds/preview_url/poster_url`；详情中“参考片段预览”与“自有素材预览”为两个独立媒体动作。
4. **创意方向事实状态（P1-4）**：`selected_id` 未匹配时“采用方向”显示“尚未选定方向”，不再默认取第一个方向；“备选方向”列出全部方向；未选方向不派生卖点结论。
5. **费用字段分离（P2-5）**：`_asset_editor` 拆为 `estimated_cost_usd`（清单预计总额）与 `spent_cost_usd`（实际已用），schema 同步。
6. **脚本入口 payload（P2-6）**：删除 `source: "production_script"` 工程字段。

新增真实投影集成测试 `test_real_operator_state_flows_through_approval_adapter`：`project_operator_state` 真实投影 + 真实任务目录注入 → node `buildApprovalStages`，端到端断言四个 P1 字段不丢、不伪造。`test_nine_stage_minimal_fixture_keeps_legacy_business_fields` 明确为适配器层测试，不单独作为真实产物完整性证据。

验证记录：`PYTHONPATH=. .venv/bin/python -m pytest -q tests/backlot` → **375 passed, 1 skipped, 0 failed**；`node --check`、`git diff --check` 通过。三档视觉验收仍暂缓，待业务方按清单步骤 0 完成九阶段产物走查后执行。

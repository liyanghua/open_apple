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
2. **提交代码**：按上述 5 个主题 commit（不含未定稿的 `grok_image_1.jpeg`/`requirements.txt` 需你确认）。
3. **报告持久化**：本文档同步到 `docs/reports/`。

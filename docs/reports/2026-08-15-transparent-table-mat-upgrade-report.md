# 透明桌垫爆款复刻与 Cinematic Fastline 升级报告

**状态：** 定稿（实施基线）
**日期：** 2026-08-15
**项目：** `transparent-table-mat-remix-01`
**适用范围：** 电商真实素材爆款复刻、Backlot 运营工作台、运营 Skill 交付

## 1. 执行摘要

透明桌垫项目已经完成一条 30 秒竖屏产品混剪，并由此暴露出 OpenMontage
原有生产方式的主要问题：素材分析可靠，但审批点过多；局部修改经常被当作
全链路返工；Backlot 能观察工程状态，却不能承担运营编辑和审批；流程知识
存在于多份导演 Skill 中，一线运营无法直接复用。

围绕这些问题，上一阶段已经完成 `cinematic-fast` 的 P0/P1 基础能力：

- 内容寻址 artifact、缓存和媒体索引；
- 唯一生产时间轴、`sample | full_render | mux_only` 路由；
- creative lock 与 sample 两道人审门；
- approval bundle、production lock、追加式决策 revision、checkpoint history 和
  失效重审批；
- Backlot 中的 Gate、缓存收益、修改范围和 ETA 聚合；
- 快线 Benchmark 规则与 SLA Gate。

这些改动已经使“少做重复工作、只重做受影响部分、变更后重新审批”具备
可执行的底层合同。但通用 artifact snapshot、业务差异比较、恢复和崩溃事务
尚未实现；当前已有的追加能力只覆盖 decision log 和 checkpoint history。
产品层也仍未完成：当前 Backlot 后端只有只读接口，运营界面仍会展示英文
阶段、JSON、哈希和运行术语，也没有可编辑表单、版本比较、内置 Agent 对话
或团队权限。

下一阶段的核心不是继续增加工程状态，而是增加一层稳定的“运营投影与操作
协议”：机器继续使用严格 JSON artifact；运营人员只看到中文业务对象，并以
“草稿 -> 影响预览 -> 提交新版本 -> 最小返工 -> 必要时重审批”的方式工作。

## 2. 报告证据边界

本报告把结论分为三类，避免把设计目标写成已实现结果。

### 2.1 已由测试或成片验证的事实

- Python 主测试：`1242 passed`。
- Artifact/流程合同测试：`735 passed`。
- Remotion 测试：`4 passed`。
- TypeScript 与 Backlot JavaScript 校验通过。
- `cinematic-fast` 合同规定且测试证明只有两道人审门。
- `renders/final.mp4` 为 1080x1920、30fps、准确 30.000 秒、900 帧。
- 成片音频为 48kHz AAC-LC，约 -14.1 LUFS、-2.4 dBTP。
- 黑帧、冻结帧、连续重复帧、完整解码、字幕安全区检查通过。
- 16 条简体中文字幕已检查，尾部标点已移除，宋体和克制花字已进入成片。

### 2.2 当前项目的观察值

`analysis/benchmarks/20260815T101911Z.json` 记录：

- 可归集的工具主动执行时间约 425.457 秒；
- 观察到的人工等待约 13680.927 秒，即约 3.8 小时；
- `video_compose` 共记录 13 次，最大单次约 47.22 秒；
- Doubao TTS 共记录 3 次，最大单次约 56.97 秒；
- 抽帧、场景检测和合成是主要可见机器工作，但不是整体耗时的主要来源。

这些数据说明该 30 秒视频的主要瓶颈是审批往返和返工，而不是“900 帧太多”。
30 秒、30fps 的成片天然包含 900 帧；降低帧数会改变交付规格，不能解决流程
问题。

### 2.3 尚未证明的目标

当前 Benchmark cohort 为：

| 类型 | 已有合格样本 | 发布所需样本 |
|---|---:|---:|
| Cold | 0 | 3 |
| Warm | 0 | 5 |
| Audio-only | 0 | 3 |

因此 3-5 小时 cold、60-90 分钟 warm、5-15 分钟 audio-only 目前仍是工程
目标，不是已发布 SLA。透明桌垫项目是升级前创建的 `cinematic` 项目，不能
替代独立的 `cinematic-fast` 运行样本。

## 3. 用户输入与交互线复盘

### 3.1 实际交互过程

透明桌垫项目的用户交互大致经历以下阶段：

1. 提供参考视频、自有素材目录、平台、画幅、时长、风格和版权边界。
2. 确认方案 A/B/C，并选择家庭场景痛点型方向。
3. 确认完整口播脚本。
4. 确认分镜与真实素材映射。
5. 确认素材使用方式。
6. 确认样片节奏与口播、字幕、BGM 配置。
7. 针对声音温度、尾句语速、前后割裂感继续修改。
8. 改用 Doubao TTS 指定音色并重新生成完整口播。
9. 修改字幕字体、标点和花字，但保留已确认口播。
10. 完成成片、QA 和备份。

### 3.2 交互线的主要问题

- **批准被拆得过细。** 方案、脚本、分镜、素材分别停顿，早期小调整产生大量
  往返。
- **修改影响不透明。** 用户不知道改口播是否会重渲染画面，也不知道为什么
  30 秒视频需要处理 900 帧。
- **任务状态依赖对话记忆。** “已经确认什么、正在改什么、还剩多久”需要反复
  询问。
- **局部意图表达不稳定。** “口播不改，只改字幕”若没有 production lock，
  容易被后续步骤扩大为脚本或画面的整体变更。
- **审批入口分离。** Backlot 只能观察，真正批准或驳回仍需回到对话。

### 3.3 已完成的流程改进

- 将 proposal、script、scene plan、asset plan 合并为 `creative_lock` 一次确认。
- 保留独立 sample 确认，正式成片前只检查 10-15 秒样片。
- 通过 production lock 固定已批准的声音、字体、CTA、素材、时间轴和 runtime。
- 通过 change impact 区分 `no_render`、`mux_only` 和 `full_render`。
- 通过 append-only decision revision 和 checkpoint history 保留旧决策与阶段
  历史，不静默改写 decision log；通用 artifact 版本恢复仍属于下一阶段。

## 4. 后台执行线复盘

### 4.1 原始执行方式

原流程按 `research -> proposal -> script -> scene_plan -> assets -> edit -> compose`
逐阶段推进。每一阶段产生 canonical artifact，再由人工确认或下一阶段消费。

优点是证据完整、可恢复；缺点是同一媒体可能重复抽帧，同一口播可能重复生成，
修改任一层后容易重新进入整个后半段流程。

### 4.2 快线后的执行方式

```text
参考视频与自有素材
        |
        v
media_index + reference_fingerprint
        |
        v
research / proposal / script / scene_plan / asset_plan
        |
        v
creative_lock 一次确认
        |
        v
TTS / BGM / 字幕 / final_props / render_plan
        |
        v
10-15 秒样片 + quick QA
        |
        v
sample 确认
        |
        v
change_impact
  no_render | mux_only | full_render
        |
        v
成片 + full QA + 交付
```

### 4.3 后台改进的实际价值

| 变化 | 原方式 | 快线方式 | 业务价值 |
|---|---|---|---|
| 媒体身份 | 文件名/路径容易重复处理 | 内容哈希与媒体索引 | 同素材复用 |
| 时间轴 | 多处重复定义 | `final_props` 唯一真相 | 避免时长漂移 |
| 批准 | 多阶段独立暂停 | 两道 grouped gate | 降低等待 |
| 局部修改 | 常走完整后半链路 | 变更影响路由 | 减少返工 |
| 批准失效 | 靠人工记忆 | bundle 哈希自动失效 | 防止旧批准误用 |
| 决策与阶段历史 | 覆盖或零散留存 | decision revision + checkpoint history | 可审计 |
| 通用 artifact 版本 | 未提供 | 下一阶段新增 snapshot/compare/restore | 可恢复 |
| QA | 依赖手工零散检查 | quick/full 两级合同 | 交付标准稳定 |
| ETA | 口头估计 | 最近同类操作滚动中位数 | 预期更清晰 |

## 5. 成片效果变化

### 5.1 参考复刻方法

成片借鉴了参考视频的抽象方法：首秒动作、约 1-3 秒的信息单元、测试证明、
短字幕和动作切点。没有使用参考视频的画面、音频、字幕、Logo、音乐、字体
或尾卡，也没有逐镜复制顺序。

### 5.2 相比初始方向的改善

- 从单纯卖点罗列改为“家庭餐桌痛点 -> 真实测试 -> 使用结果”。
- 从文件名推断改为基于 ffprobe、场景检测、抽帧和人工观看的真实内容描述。
- 将“防油”收敛为画面可证明的酱汁污渍/防污易擦表达。
- 将“无甲醛认证”收敛为仪表实测画面，不虚构机构、报告和标准。
- Doubao TTS 替代毛刺明显的本地口播，保持温和家庭语气。
- 口播、BGM、字幕不再各自孤立，按 30 秒固定时间轴进行音画组织。
- 字幕采用宋体、去尾标点和少量花字，减少“模板字幕”观感。

### 5.3 仍需业务验证的效果

技术 QA 只能证明成片可交付，不能证明转化效果。后续仍需至少收集：

- 前 3 秒停留率；
- 完播率；
- 商品点击率；
- 评论中的卖点理解与信任反馈；
- 同一素材不同钩子和 CTA 的 A/B 结果。

## 6. Backlot 现状与 Flova 对标

### 6.1 当前 Backlot 的真实能力

Backlot 已能展示阶段、checkpoint、storyboard、renders、decision log、Gate、
缓存收益、变更范围和 ETA。但后端当前仅有 GET API，前端仍直接展开 artifact，
本质上是工程观察板，而不是业务生产台。

当前缺口包括：

- 英文 `research/proposal/script/scene_plan/assets/edit/compose/publish`；
- `artifact`、`bundle`、`runtime`、`cache`、`route`、哈希等工程词；
- 原始 JSON 展示；
- 无结构化编辑、影响预览、版本对比和恢复；
- 无内置 Agent 对话；
- 无团队账号、角色和操作审计；
- 老项目缺失快线 artifact 时只显示“暂无”，缺少业务化解释。

### 6.2 Flova 的关键优势

根据 Flova 公开文档，其人机协作优势主要来自：

1. Agent 对话与故事板、媒体、文档、时间线同屏。
2. 用户可直接编辑中间产物，Agent 基于当前版本继续。
3. 同一创作意图下保存多个素材版本并进行选择。
4. 支持停止、回到某一时刻、从某一时刻创建分支。
5. Agent 和人工并行编辑时提供冲突处理。
6. Skill、Final Video Spec 和项目状态持续进入上下文。

### 6.3 OpenMontage 可形成的差异化优势

OpenMontage 不应复制 Flova 的通用创作平台，而应在电商真实素材复刻中形成
更强的垂直能力：

- 参考与自有素材强制隔离，版权边界明确；
- 不凭文件名判断，强制技术探测、抽帧和观看；
- 每个卖点必须绑定实际素材时间段和证据边界；
- 修改前显示受影响镜头、费用、耗时和重审批范围；
- 口播/BGM 修改可复用已认证视频主轨；
- 成片强制通过黑帧、冻结、重复帧、响度、峰值、字幕安全区和编码 QA；
- 本地真实素材优先，不以付费生成作为默认补救。

## 7. Backlot 运营化目标

Backlot 下一版保留当前结构，但默认转换为四区运营工作台：

| 区域 | 运营信息 |
|---|---|
| 顶部 | 商品、当前进度、预计完成时间、待办、预算、风险 |
| 左侧 | 全中文阶段导航 |
| 中间 | 当前阶段的业务编辑器和预览 |
| 右侧 | 可引用卡片和文本的 Agent 对话 |

中文阶段固定为：

| 内部阶段 | 运营名称 |
|---|---|
| research | 参考解析与素材体检 |
| proposal | 创意方案 |
| script | 口播与字幕 |
| scene_plan | 镜头映射 |
| assets | 制作准备 |
| sample | 样片确认 |
| edit | 修改与精剪 |
| compose | 成片生成 |
| publish | 交付下载 |

工程数据继续存在，但只在管理员诊断入口显示。运营模式禁止直接展示 JSON、
哈希、schema、artifact path、runtime 名称或内部事件文件名。

## 8. 面向运营的 Skill 方案

### 8.1 Skill 定位

建立一个“电商爆款复刻”主 Skill，并用家居、美妆、食品等品类模板覆盖差异。
主 Skill 复用 `cinematic-fast`，不再复制一套 pipeline。

### 8.2 运营建单输入

- 商品名称与品类；
- 投放平台与画幅；
- 目标时长；
- 参考视频；
- 自有素材；
- 品牌、商品链接或购买方式；
- 必须表达与禁止表达；
- 口播、字幕、BGM 偏好；
- 是否允许付费生成补充素材；
- 截止时间与预算上限。

### 8.3 Skill 固定能力

- 参考结构解析与版权隔离；
- 自有素材真实检查；
- 三个原创方案；
- 逐镜素材与时间码映射；
- 两道人工确认；
- 先样片、后成片；
- 变更影响和最小返工；
- 最终技术与内容 QA；
- 项目级 Skill 版本锁定。

### 8.4 Skill 发布治理

Skill 状态为 `draft -> trial -> published -> retired`。只有同时通过 schema、
固定样例、集成回归、真实 Benchmark 和一线试用的版本才能进入运营入口。
透明桌垫项目作为第一个黄金样例。

## 9. 效率与效果验收指标

### 9.1 流程效率

| 工作流 | 发布门槛 |
|---|---|
| Cold | 中位数 <= 4 小时，全部 <= 5 小时，至少 3 次 |
| Warm | 中位数 <= 75 分钟，全部 <= 90 分钟，至少 5 次 |
| Audio-only | 中位数 <= 10 分钟，全部 <= 15 分钟，至少 3 次 |

### 9.2 可控性

- 100% 人工提交先显示影响预览；
- 100% 已批准语义内容变化触发正确重审批；
- 100% 冲突不静默覆盖；
- 常用调整无需阅读 JSON 或使用命令行；
- 旧版本可恢复，恢复动作本身创建新 revision。

### 9.3 易用性

- 至少 5 名一线运营参与测试；
- 首次建单 <= 10 分钟；
- 关键阶段编辑任务完成率 >= 90%；
- 用户无需理解 artifact、bundle、runtime、hash 或 schema；
- 桌面完成全量编辑，移动端至少支持查看、评论和批准。

### 9.4 与 Flova 的真实结果对照

使用同一 brief、同一参考、同一自有素材、同一预算和时限，分别生成结果并
盲评：前 3 秒钩子、卖点清晰、真实可信、节奏、购买意愿。

OpenMontage 的目标是总分至少高于 Flova 0.3/5，同时合规和素材真实性不得
更差。未获得 Flova 账号和费用批准前，不执行付费对照测试。

## 10. 建议实施顺序

1. 先建立运营状态投影和全中文只读工作台，立即消除 JSON 与英文信息。
2. 再增加阶段编辑、草稿、影响预览、版本、恢复、审批、项目 ACL 和事务写入；
   拒绝后的人工修订不依赖 Agent。
3. 接入可插拔 Agent Bridge，首个适配器使用本机 Codex，并通过 Broker 隔离
   provider secret、预算和项目写权限。
4. 增加运营 Skill 目录、建单表单、品类模板和发布治理。
5. 用透明桌垫和其他真实商品完成 cohort，再发布 SLA。
6. 最后执行 Flova 同题对照，不在缺少样本时宣称“已经超过”。

## 11. 风险与控制

| 风险 | 控制方式 |
|---|---|
| UI 修改绕过 pipeline | 所有提交进入 typed action service，不允许任意 JSON Patch |
| 旧批准继续生效 | production lock + bundle reconciliation |
| Agent 覆盖人工修改 | generation compare-and-swap；冲突后进入 needs_input，不自动覆盖 |
| 内置对话直接调用付费模型 | Agent 只持有单次 capability token；provider secret 仅在 Broker 进程 |
| 多 writer 产生部分提交 | ProjectWriteSink + immutable generation + 崩溃恢复 |
| 重试创建重复项目 | SQLite 全局 reservation + 唯一幂等键 + 原子目录发布 |
| 内网多人误操作 | 本地账号、项目 ACL、会话、CSRF、追加式审计 |
| 技术目标被当作 SLA | Benchmark sample floor 和 publish gate 强制约束 |
| 追求 Flova 功能导致范围膨胀 | 首版不做完整素材画布和多轨时间线 |

## 12. 证据来源

- `docs/superpowers/specs/2026-08-14-cinematic-fastline-technical-upgrade-design.md`
- `docs/superpowers/plans/2026-08-14-cinematic-fastline-implementation-plan.md`
- `docs/benchmarks/cinematic-fast.md`
- `projects/transparent-table-mat-remix-01/analysis/benchmarks/20260815T101911Z.json`
- `projects/transparent-table-mat-remix-01/artifacts/render_report.json`
- `projects/transparent-table-mat-remix-01/artifacts/final_review.json`
- Flova 公开文档：
  `https://www.flova.ai/zh-CN/docs/introduction/understanding-flova/`
- Flova Agent、Skill、媒体空间、文档区和时间线功能文档：
  `https://www.flova.ai/zh-CN/docs/features/agent/`

测试计数来自 Git SHA `13894d5` 的最终验收记录。正式发布报告时必须补充执行
命令、执行时间和保存的测试输出；在补齐前，计数只作为该提交的验收基线，
不替代新版本回归。

## 13. 结论

OpenMontage 已经具备比普通“Agent 调工具”更严格的生产合同，但当前产品体验
仍停留在工程观察层。下一阶段应把已完成的 Gate、锁、缓存、变更路由和 QA
转译成运营能直接理解和修改的业务对象，并让 Agent 与人工围绕同一版本工作。

在电商真实素材爆款复刻这个垂直范围内，OpenMontage 有机会在可信证据、修改
透明度、局部返工和最终 QA 上超过 Flova；前提是完成运营交互层，并通过真实
cohort 与同题盲评证明，而不是依靠功能清单自行宣布达成。

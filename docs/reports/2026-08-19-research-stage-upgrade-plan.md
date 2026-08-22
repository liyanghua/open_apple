# Research 阶段升级计划与评价范式

**日期：** 2026-08-19
**样本项目：** `table-mat-mix-v7`
**流程：** `cinematic-fast`
**范围：** 参考视频解析、自有素材体检、拆解维度模板、参考与素材匹配、研究制品归档，以及 Research 向导演总控单、制作剧本、镜头执行单和素材补位生成的下游交接。
**实施状态：** P0（P0-1 至 P0-5）已于 2026-08-19 实现；P1-6 和 P1-8 的审核台能力已落地。P1-9 与 P1-10 已实现：制作剧本逐段确认、镜头执行单横向审核，以及审核台逐镜 Seedance Fast/Standard 补位生成。2026-08-21 已完成 `table-mat-mix-v7` 的镜头执行单真实运行复盘；下一轮重点是消除素材区间重复确认、建立单一事实来源，并把临时行业判断模板化。
**证据等级：** 内部实现以项目 `events.jsonl`、研究制品、checkpoint 和仓库实现为准；面向视频制作人员和一线业务人员的工作台不直接展示这些工程术语，而是展示“看到了什么、哪里不确定、下一步要决定什么”。没有遥测记录的时间明确标记为“不可归因”。

## 1. 核心结论

本次 research 的内容质量达到进入 proposal 的要求，但执行过程还不是稳定、可度量的标准流程。

- 参考视频已完成深度解析：14.79 秒、7 个镜头、8 张关键帧。
- 6 条自有视频均完成真实探测、场景检测、抽帧和音频检查。
- 参考媒体与自有媒体路径分离，参考视频标记为 `analysis_only`，未进入成片素材候选。
- 研究结论不仅描述素材，还解释了参考片为什么这样组织，以及自有素材为什么能匹配这些镜头。
- 本次基线运行已形成 5 个结构化研究制品并完成 schema/hash 校验；升级后的 Research 完成态将固定为 9 个不可变研究制品，另有 1 个可编辑的 `research_annotations` overlay。
- 已确认可以将业务侧分镜表抽象为版本化 `analysis_dimension_profile`：模板只规定“观察哪些维度”，行业经验另行评价“这些观察在什么条件下有效”。
- Research 之后不能直接把创意方案当成全片总控；Proposal 内需要先选方向，再由 Agent 生成并锁定一份“导演总控单”，作为口播、分镜和制作准备共同遵守的创意合同。
- 导演总控单锁定后不能直接跳到口播、字幕或分镜；需要先生成并逐段确认一份可执行的“制作剧本”，再形成版本化镜头执行单。
- 当自有素材无法完成某个镜头任务时，Agent 可以基于行业模板、Reference Fingerprint、自有素材和总控规则提出生成补位方案；付费视频生成必须在镜头执行单锁定后，由用户在审核台逐镜发起。
- 纯媒体分析实际墙钟时间约 51.3 秒，累计工具进程时间约 155.5 秒，说明并行探测有效。
- 从第一条分析事件到最终 checkpoint 完成约 19 分 34 秒，其中约 18 分 43 秒不是媒体分析，而是编排、提交修复和校验修复。

主要判断（待 P0-1 编排遥测回填验证）：**媒体分析不是研究阶段的瓶颈（实测 51.3s / 19m34s），但剩余 18 分 43 秒当前不可归因**；候选假设是语义编排、提交与校验修复。P0-1 编排事件落地后必须用新 run 重新测量并回填该结论，在遥测缺失期间不得把该假设当作已测事实引用。

## 2. 本次实际执行过程

### 2.1 输入和约束确认

从项目 intake 读取并固定以下约束：

- pipeline：`cinematic-fast`
- 参考目录：`inputs/reference/`
- 自有素材目录：`inputs/source/`
- 参考视频只用于分析，不进入成片
- 项目需要口播、字幕和 BGM
- 目标平台包括抖音、视频号和小红书

这一层的职责是确认研究范围，不做创意推断，也不调用付费模型。

### 2.2 参考视频解析

参考视频走独立的 reference 分支，执行：

1. 视频元数据和时长读取；
2. 场景检测；
3. 关键帧抽样；
4. 动作、节奏和镜头语言归纳；
5. 音频能量检查；
6. 形成 `video_analysis_brief` 和 `reference_fingerprint`。

本次提取出的参考结构为：

```text
动作钩子 -> 桌角/边缘贴合 -> 防刮证明 -> 防水防油证明
-> 柔软/回弹 -> 真实餐桌场景 -> 搜索型 CTA
```

参考片没有可直接复用的有效口播转写，因此后续口播必须重新创作，不能把参考片字幕当作脚本来源。

### 2.3 自有素材体检

6 条自有视频并行执行：

- `ffprobe` 技术探测；
- 场景检测；
- 代表帧抽样；
- 音频轨道和声道检查；
- 可用区间和质量风险判断；
- 素材内容摘要。

本次体检结论：6 条素材均为 4K、约 59.94fps、双声道视频，没有发现低分辨率、单声道、过短或格式不兼容风险。素材覆盖无甲醛检测、桌角贴合、自动铺开、防刮、防油和餐桌场景。

### 2.4 参考理解与素材匹配

这一层不是简单的文件名匹配，而是将参考片的镜头意图拆成可验证的“动作 + 卖点 + 情绪功能”，再寻找自有素材证据。

例如：

| 参考片意图 | 自有素材候选 | 匹配理由 |
|---|---|---|
| 第一秒建立产品认知 | 桌角对齐/自动铺开 | 都能用动作直接展示产品，而不是从静态产品图开始 |
| 桌角和边缘贴合 | 桌角对齐、挤压不变形 | 画面证据与参考片的边缘特写同构 |
| 防刮功能证明 | 防刮素材 | 有明确硬物刮擦动作，证据强度高 |
| 防水防油证明 | 防油易擦拭素材 | 能把液体、油污和易清洁串成连续卖点 |
| 生活化收束 | 餐桌场景素材 | 将功能证据转成“透明且不遮挡桌面纹理”的使用结果 |

最终研究 brief 还形成了三个差异化方向：痛点优先、四段证据链、功能回到真实餐桌。

### 2.5 证据归档与 checkpoint

临时分析路径被改写为项目内稳定路径：

- `analysis/reference/keyframes/`
- `analysis/source/<content_sha256>/`

随后写入：

- `research_brief`
- `video_analysis_brief`
- `source_media_review`
- `media_index`
- `reference_fingerprint`

最后通过 `ProjectCommitStore` 写入 `checkpoint_research.json`，状态为 `completed`，下一动作指向 proposal 阶段。

## 3. 实际耗时

证据来源：[`projects/table-mat-mix-v7/events.jsonl`](../../projects/table-mat-mix-v7/events.jsonl)。

| 操作 | 次数 | 累计工具耗时 | 说明 |
|---|---:|---:|---|
| 参考/素材场景检测 | 8 | 83.78 秒 | 参考分支 2 次记录 + 6 条自有素材 |
| 关键帧/代表帧抽样 | 7 | 69.29 秒 | 参考 1 次 + 自有素材 6 次 |
| 自有素材音频探测 | 6 | 2.20 秒 | 每条自有视频 1 次 |
| 参考片音频能量 | 1 | 0.21 秒 | 用于节奏和音乐方向判断 |

由于研究探测是并行执行的：

- 第一条分析事件：`07:23:31.685 UTC`
- 最后一条分析工具事件：`07:24:22.990 UTC`
- 媒体分析墙钟时间：**51.3 秒**
- 工具进程累计时间：**155.5 秒**
- 付费调用：**0 次，成本 $0**
- 最终 research checkpoint：`07:43:06.016 UTC`
- 从第一条分析事件到 checkpoint：**19 分 34 秒**

最后 18 分 43 秒不能归因于媒体分析，主要由以下因素构成：

1. 研究语义层和证据路径的人工编排；
2. 第一次提交时，checkpoint 校验看不到同事务内暂存的 artifact；
3. 第二次提交时，`next_action.priority` 使用了非法值；
4. 修复脚本后重新执行并校验。

这部分目前没有独立 telemetry，未来必须单独计时，否则无法判断 research 是“分析慢”还是“编排慢”。

## 4. 当前实现的固定范式与探索部分

### 4.1 应固定的基础范式

- 先读 intake，再决定 reference/source 两条路径；
- reference 和 source 永远分开存储和校验；
- scene detect、frame sampler、audio probe 并行；
- 每条自有素材必须有真实 probe 和代表帧；
- 每个参考镜头必须有结构、节奏和关键帧证据；
- research 开始时必须锁定拆解 profile；参考和自有素材使用同一维度投影；
- 所有研究制品必须带 hash，并通过 schema 校验；
- research 结束后写入可恢复的 `next_action`；
- research 阶段不得调用付费生成工具。

### 4.2 可以探索但必须受控的部分

- 参考片的创意拆解方式；
- 卖点顺序和痛点钩子；
- 自有素材候选的匹配策略；
- 口播、字幕和 CTA 的研究建议；
- 视觉差异化方向。

探索项不能改变基础制品合同，也不能阻塞基础探测。每个探索项都应记录目的、成功标准、最大耗时和是否进入最终 brief。

## 5. 拆解维度输入模板

### 5.1 定位

首期将业务提供的《视频分镜拆解_2026-08-15.xlsx》规范化为 `cinematic-fast` 的第一个内置拆解 profile：

```yaml
profile_id: ecommerce-storyboard-cn
version: "1.0"
pipeline: cinematic-fast
use_case: ecommerce_product_proof
row_unit: shot
```

该 Excel 包含 43 个视频工作表、565 条镜头记录，所有工作表使用相同的 14 列结构。它适合定义业务人员希望看到的拆解视图，但不能直接作为行业规律：样本中 565 条均为俯拍、室内桌面、人声加背景音乐，522 条为固定镜头，说明它是同一产品类别下的集中样本，而不是跨行业基准。

首期采用内置 profile，不支持任意 Excel 的列语义推断。附件仅作为 profile 的设计依据和回归样本，不作为运行时依赖，也不修改原文件。

### 5.2 字段映射

| Excel 列 | 内部字段 | 规范化语义 |
|---|---|---|
| 序号 | `ordinal` | 镜头在视频内的顺序 |
| 景别 | `shot_size` | 全景、中景、近景、特写等 |
| 镜头 | `camera_movement` | 固定、推、拉、摇、移等；原表列名不等同于内部语义 |
| 拍摄方法 | `camera_angle` | 俯拍、平视、仰拍、过肩等 |
| 时长 | `interval` | 转换为数值化半开区间 `[start, end)` |
| 画面内容 | `visual_content` | 主体、动作、环境和动作结果 |
| 台词 | `dialogue` | 口播或人物对白 |
| 花字 | `overlay_text` | 画面文字；与场景内容、字幕轨分离 |
| 特效 | `effect_treatment` | 淡入、淡出、字幕动画等处理 |
| 备注 | `analyst_note` | 人工补充；为空时模型不得臆造 |
| 画面参考 | `evidence_frames` | 关键帧或代表帧证据引用 |
| 场景 | `setting` | 地点、内外、时间与环境 |
| 音频类型 | `audio_layers` | 人声、环境声、音乐和音效层 |
| BGM | `music_profile` | 音乐类型、能量与节奏特征 |

样本中 `备注` 和 `画面参考` 均为空，并存在 6 个 `end <= start` 的非正时长区间；`画面内容`、`台词`、`花字`还包含明显 OCR 噪声。因此每个观察值必须额外保存：

```text
observation_source
confidence
evidence_refs
warnings
```

低置信 OCR 只能作为待确认观察，不能直接进入事实、主张或最终文案。

### 5.3 系统增强维度

用户默认仍看到熟悉的 14 列。底层另外保留下列系统维度，用于 Reference Fingerprint、一致性分析和素材匹配：

```text
shot_id
reference_scene_id
narrative_function
reference_mechanism
subject
subject_motion
spatial_framing
lighting
continuity_anchors
originality_boundary
```

这些字段在工作台镜头详情中展开，不强行加入默认表格，避免牺牲扫描效率。`research_breakdown` 只保存可观察值及其来源，不把解释、使用政策或用户决策写入观察层：

- `narrative_function`、`reference_mechanism`、`continuity_anchors` 属于 `reference_fingerprint` 的派生解释；
- `originality_boundary`、`project_adaptation` 属于 `reference_source_matrix` / `research_synthesis`；
- 用户偏好只写入 `research_annotations` overlay。

### 5.4 Profile 合同

新增版本化配置：

```text
knowledge/analysis_profiles/ecommerce-storyboard-cn.v1.yaml
schemas/knowledge/analysis_dimension_profile.schema.json
```

每个维度固定声明：

```text
key
label
value_type
required
allowed_values
normalization
evidence_requirement
display_order
visible_by_default
```

profile 是“观察合同”，不包含剪辑优劣判断、推荐阈值或行业结论。未来新增行业或客户模板时复用同一合同。

### 5.5 Research Breakdown

新增 `research_breakdown` artifact，以锁定的 profile 对参考视频和自有素材进行同构投影：

```text
profile_ref
reference_shots[]
source_segments[]
coverage_summary
quality_warnings
```

每条记录包含：

```text
row_id
origin: reference | owned
media_id
interval
values
evidence_refs
confidence_by_dimension
observation_source: direct | derived | manual | missing
warnings
```

`ordinal` 等直接读取字段可以是 `direct`；模型从帧、音频或 OCR 推导的字段标记为 `derived`；人工补充标记为 `manual`；无法确认的字段标记为 `missing`，不能伪造证据。参考与自有素材使用相同维度后，匹配器才能比较镜头意图、动作证据、景别、机位、声音和连续性，而不是依赖文件名或自由文本猜测。

### 5.6 与 Reference Fingerprint 和行业经验的关系

五层职责必须分离：

```text
analysis_dimension_profile  = 要观察什么
research_breakdown          = 实际观察到了什么
reference_fingerprint       = 参考片反复使用了什么规律
industry_priors             = 这些规律在什么条件下通常有效
project_adaptation          = 当前项目决定保留、改变或舍弃什么
```

`reference_fingerprint` 采用三层颗粒度，不能只保存一段“风格像什么”的摘要：

| 层级 | 保存内容 | 主要用途 |
|---|---|---|
| Shot | 构图、景别、机位、运动、主体动作、文字/声音协作和证据帧 | 与自有素材区间做可验证匹配 |
| Beat | Hook、痛点、证明、转折、结果、CTA 的机制、进入/退出条件和节奏区间 | 支撑结构迁移与差异化改写 |
| Whole-video | Beat 顺序、节奏曲线、视觉/音频语法、重复模式和一致性合同 | 约束 Proposal 与 Scene Plan 的整体体验 |

一致性合同至少覆盖八类锚点：主体/产品身份、品牌与主张、场景与空间关系、动作与物理状态、时间与因果、镜头与视觉语法、光色与材质、台词/花字/音频与叙事功能。每个锚点必须标记：

```text
scope: shot | beat | whole_video
strength: hard | soft
source: reference_observation | owned_asset_fact | brand_rule | industry_prior | user_decision
evidence_refs
allowed_variation
conflict_policy
```

“爆款参考 + 自有素材补充”时，参考片主要提供结构机制和可变的 soft anchor，自有素材提供产品事实、权利边界和不可违背的 hard anchor。两者冲突时优先保真自有产品、品牌主张和物理连续性；参考片的构图、节奏或顺序只能作为可解释的迁移候选，不能为了“像”而伪造自有素材不存在的动作或证明。冲突及其 `keep | adapt | drop` 决议写入矩阵和 synthesis，而不是回写 observation。

行业经验不是第四层指纹。它按 `target_dimensions + scope` 评价 Shot/Beat/全片规律在特定平台、品类和目标下是否常见、有效或有风险，并给出例外；它不能覆盖参考观察、自有素材事实或用户决策。

当前 `video_analyzer` 已会写出带内容 hash、分析版本和请求参数的 v1 指纹；升级时必须避免双写：

1. analyzer 只负责 `video_analysis_brief` 和分析目录中的原始 fingerprint sidecar，不再直接覆盖最终 Research artifact；
2. Research projector 读取该 sidecar，独占写入 `reference_fingerprint@2.0`，保留 `content_sha256`、`analysis_depth`、`analyzer_version`、`canonical_request`、`input_hashes` 和输出摘要；
3. v1 项目继续只读兼容，Backlot 在缺少 v2 时投影旧摘要并显示升级提示，不把 v1 误标为已完成 v2 研究。

行业经验采用独立、版本化规则包：

```text
knowledge/industry_priors/short-video.v1.yaml
knowledge/industry_priors/ecommerce-proof.v1.yaml
```

每条规则至少包含：

```text
prior_id
version
applies_when
target_dimensions
recommended_range
rationale
confidence
exceptions
source
provenance_type: external_research | reviewed_benchmark | internal_validated
evidence_scope
reviewed_at
reviewer
expires_at
```

首期规则可评价钩子窗口、镜头时长、证据链、产品露出、字幕密度和 CTA，但不得因为附件样本全部俯拍，就推断“电商视频应该全部俯拍”。项目观测、客户附件和 profile fixture 不得直接晋升为行业先验，只能作为 tenant/project-scoped observation；只有经过独立验证、标注来源和审核周期后，才允许进入 prior。输出必须明确分栏：`observed`、`industry_prior`、`project_adaptation`。

### 5.7 缓存和增量重算

媒体底层分析与拆解模板解耦，但失效由声明式依赖 DAG 决定：

```text
媒体缓存键 = content hash + tool/version + algorithm version + normalized parameters + evidence contract version
模板投影缓存键 = all required upstream semantic hashes + profile id/version + projector/model/prompt/taxonomy version
```

- 更换或升级 profile 时，只要新增维度不需要未生成的证据，就不重跑已有 analyzer；若新增 OCR、ASR、音频或更密抽帧要求，则只补跑缺失能力；
- 只重算 `research_breakdown` 及其下游 fingerprint、匹配矩阵、综合和 scorecard；
- 修改行业规则重算规则评价，并按 DAG 传播到匹配关键性、综合、scorecard 和需要重新解释的下游输入；
- 修改用户偏好只更新 `research_annotations`，但若改变矩阵 resolution 或方向偏好，必须重算受影响的综合和 scorecard。

这将重媒体分析与轻语义投影分开，是 6–8 分钟 Research 目标的必要条件。

### 5.8 工作台呈现与用户语言

本方案采用“双层表达”：内部保留稳定的英文 artifact/字段名，便于程序校验和跨阶段传递；用户看到的是视频制作和业务现场的说法。所有工作台标题、按钮、提示和审核卡片默认使用右列文案，英文标识只出现在详情、导出或开发日志中。

| 内部名称 | 用户看到的名称 | 用户真正要回答的问题 |
|---|---|---|
| `research_breakdown` | **分镜拆解** | 这一镜拍了什么？多长？什么景别、机位、动作、台词、花字和声音？ |
| `reference_fingerprint` | **参考片的拍法和节奏** | 参考片为什么这样排？哪些拍法值得借鉴，哪些不能照搬？ |
| `reference_source_matrix` | **参考镜头 × 我的素材** | 参考中的这一镜，我有哪些素材可以完成？证据够不够？ |
| `research_synthesis` | **可选方向** | 我可以保留什么、换成什么、删掉什么，才能既有效果又像自己的片子？ |
| `research_scorecard` | **研究检查结果** | 关键镜头、素材和卖点是否都查清楚了？还有什么风险？ |
| `research_annotations` | **我的标注与决定** | 我确认采用哪条素材、哪种方向，哪些地方需要补看或重做？ |
| `analysis_dimension_profile` | **分镜拆解模板** | 这次要重点看哪些内容？ |

工程状态也要翻译成动作语言：`completed` 显示为“已完成”，`awaiting_human` 显示为“等你确认”，`in_progress` 显示为“正在拆解/匹配”，`failed` 显示为“这一步没查清，需要处理”。不要向用户显示“artifact 缺失”“DAG 失效”“hash 不一致”等原始错误；改为说明影响，例如“防水这一镜还没有找到可信素材，暂时不能进入方案”。

#### 5.8.1 工作台布局

**子阶段展示规则（固定链路）**

Research 在工作台中固定展示完整子阶段链路，不因项目输入缺失而改变顺序或让页面跳动。建议固定为：

1. **先看参考片怎么拍**
2. **再看我的素材能不能接上**
3. **把参考镜头和我的素材对上**
4. **决定这条片准备怎么做**
5. **检查还有什么没看清**

每个子阶段都要有自己的状态和中间产物入口，至少显示“未开始 / 正在处理 / 等你确认 / 已完成 / 本项目不需要”。当项目没有参考片时，仍保留“先看参考片怎么拍”及其后续依赖位置，但该子阶段置灰，显示“本项目没有参考片，这一步不需要处理”；参考相关卡片不展示伪造的结论，素材体检和自有方向仍按固定链路继续。状态文案使用业务语言，不向用户暴露 artifact、DAG 或内部字段名。

固定链路的目的，是让制作人员始终知道当前处于哪一步、下一步会产出什么，以及为什么某一步没有动作；输入变化只影响子阶段状态和内容，不影响导航位置。

Research 渐进工作台增加：

1. **本次拆解模板**：显示“电商产品证明分镜模板”和适用场景，不要求用户理解 profile/version；
2. **拆解进度**：显示“已识别 / 待确认 / 没看清”，而不是 coverage、confidence 数字；
3. **参考片分镜表**：默认展示附件同款 14 列，支持关键帧和“需要确认”标记；
4. **我的素材**：使用同一套栏目展示可用片段、可用卖点和风险；
5. **参考镜头 × 我的素材**：展示“推荐素材、为什么匹配、证据强不强、没有合适素材怎么办”；
6. **需要我确认**：集中展示“关键卖点没有素材”“这段字看不清”“参考片的做法与现有素材冲突”等需要业务决定的问题。

工作台首屏只呈现结论和待办，点击单条镜头后再展开时间码、关键帧、识别来源和内部字段。用户不需要先读完全部拆解才能推进；没有影响当前方案的低置信字段放在详情中，不阻塞主流程。

#### 5.8.2 用户可执行的审核动作

按钮和审核卡片采用现场语言：

| 用户操作 | 工作台文案 | 系统内部动作 |
|---|---|---|
| 选方向 | **保留这个方向 / 换一个方向 / 暂不采用** | `set_direction_preference` |
| 处理素材匹配 | **采用这段 / 换一段 / 需要补拍或补素材 / 改成别的表达 / 删除这一镜** | `resolve_matrix_row` |
| 重新确认 | **重新看这一段**，可勾选“动作、台词、字幕、声音、时长” | `request_local_reanalysis` |
| 写意见 | **补充业务说明** | `set_business_note` |

审核卡片必须回答三件事：**发生了什么、为什么会影响成片、我可以怎么处理**。例如不要写“矩阵 resolution 缺失”，而写“参考片有防刮证明，但现有素材里没有清楚的刮擦动作；请选择补素材、改成口播说明，或删掉这一卖点”。

用户可写业务注释、选择方向偏好或请求重新确认，但不能直接覆盖原始媒体证据；系统保留原始观察，并在用户标注旁显示“你的决定”。

#### 5.8.3 Research 决策门与下一步交接

Research 完成后，用户不需要逐项确认所有观察结果，只处理会改变成片方向或造成制作风险的阻塞决策。工作台增加“需要我确认”收件箱，固定归纳以下决策类型：

| 决策类型 | 触发条件 | 用户看到的选择 | 影响范围 |
|---|---|---|---|
| 核心卖点怎么表达 | 自有素材不能如实证明参考卖点 | 补拍/补素材、改成别的表达、删除这一卖点 | 相关镜头、脚本承诺、字幕和方案候选 |
| 这一镜用哪条素材 | 有多个可行候选或推荐证据不足 | 采用这段、换一段 | 对应分镜的素材区间、镜头证据和后续剪辑 |
| 是否重新确认 | 动作、文字、结果或时长识别不清，且会影响卖点 | 重新看动作/台词/字幕/声音/时长 | 局部 Research、匹配结果和检查项，不覆盖原始观察 |
| 整条片往哪个方向做 | 多个差异化方向都可行 | 保留这个方向、换一个方向、暂不采用 | Proposal 方案范围、参考机制取舍和原创边界 |
| 品牌与主张边界 | 参考表达可能越过自有品牌或事实边界 | 补充业务说明、修改主张边界 | 全部 Proposal、脚本和字幕，必要时阻止进入下一阶段 |

只有“开头钩子、核心卖点证明、结尾行动引导”存在无解缺口，或用户尚未完成方向选择时，Research 才保持“等你确认”。低置信但不影响当前方案的字段进入详情，不阻塞推进。

当所有阻塞决策都有明确处理结果，且研究检查通过后，工作台显示“可以进入创意方案”。当前版本没有直连 Code Agent 的通道，因此不伪装成已经启动下一阶段：页面生成一条带项目 ID 的继续指令，用户复制到 Agent 窗口发送；Agent 读取交接包后再执行 Proposal。交接包固定携带：已选方向 ID、每条关键镜头的处理结果、保留/改变/禁止照搬的参考机制、已确认的产品事实与品牌边界、仍需在 Proposal 中验证的前置条件。Proposal 直接读取这些决定并生成 2-3 个方案，不重新匹配素材；Scene Plan 继续沿用已确认的镜头意图和素材处理。

每个决策卡片必须同时回答“发生了什么、会影响什么、我可以怎么处理”，并在提交前显示影响预览。用户提交后写入 `research_annotations` revision；系统局部刷新匹配、方向和检查结果，保留原始证据与历史决定。

### 5.9 制品接入矩阵

首期不能只新增 JSON 文件；每个新制品必须同时接入 schema、注册表、pipeline、checkpoint、Backlot、director 和下游输入合同。升级后的 Research 完成态包含以下 9 个不可变制品：

```text
research_brief
video_analysis_brief
source_media_review
media_index
reference_fingerprint
research_breakdown
reference_source_matrix
research_synthesis
research_scorecard
```

`analysis_dimension_profile` 是知识配置，不是项目 artifact；`research_annotations` 是用户可编辑 overlay，不属于 Research 完成事务的必需制品。

| 对象 | Schema / 注册 | Pipeline 与 checkpoint | Backlot | Director 与下游消费 |
|---|---|---|---|---|
| `analysis_dimension_profile` | 新增 `schemas/knowledge/analysis_dimension_profile.schema.json`；由 profile loader 校验 | Research 启动时锁定 `profile_id/version/hash`，写入各派生 artifact provenance，不进入 `produces` | 显示当前模板、版本、覆盖率和升级提示 | Research director 负责选择；projector 按 profile 生成 breakdown |
| `research_breakdown` | 新增 `schemas/artifacts/research_breakdown.schema.json` 并加入 `schemas.artifacts.ARTIFACT_NAMES` | 加入 `cinematic-fast.research.produces`，作为完成 checkpoint 必需 envelope | 加入 `backlot.state.ARTIFACT_FILES`；默认投影 14 列及置信度、证据、warning | Research director 生成；Proposal 可选读取，Scene Plan 必需读取 |
| `reference_source_matrix` | 新增 artifact schema 并加入 `ARTIFACT_NAMES` | 加入 Research `produces` 和完成 checkpoint | 新增参考-素材矩阵视图、缺口与 resolution 状态 | Research director 生成；Proposal 和 Scene Plan 必需读取，不得下游重新匹配 |
| `research_synthesis` | 新增 artifact schema 并加入 `ARTIFACT_NAMES` | 加入 Research `produces` 和完成 checkpoint | 展示方向、取舍、行业先验冲突和决策理由 | Research director 生成；Proposal 必需读取并引用方向 ID |
| `research_scorecard` | 新增 artifact schema 并加入 `ARTIFACT_NAMES` | 加入 Research `produces` 和完成 checkpoint；硬性失败时不得写 completed | 展示完成状态、质量状态、各项分数和失败项 | Research director 在其他研究制品后生成；Proposal 只接受通过状态 |
| `research_annotations` | 新增 overlay schema 并加入 `ARTIFACT_NAMES`，保留 revision provenance | 不加入 Research `produces`；缺失时按空 overlay 处理，修改后按依赖 DAG 触发派生重算 | 扩展 `ResearchAdapter` 的操作类型、影响预览和 revision history | 工作台写入；Research/Proposal/Scene Plan 读取当前 revision，不得改写原始证据 |

同时更新 `lib.checkpoint.SUPPLEMENTARY_ARTIFACTS` / fastline 合同测试中需要识别的名称、Backlot state/operator 投影、pipeline contract 测试和端到端 fixture。由于 `artifact_contract_version: 2` 会把 `produces` 全部视为完成 checkpoint 的必需 envelope，升级必须一次完成，不能先改 manifest 再补 schema 或 writer。

### 5.10 下游传递合同

`research_synthesis` 不只是一段摘要，而是 Proposal 的结构化候选输入：

```text
differentiation_directions[]:
  direction_id
  promise
  keep_from_reference[]
  change_for_project[]
  avoid[]
  industry_prior_refs[]
  matrix_row_refs[]
  prerequisites[]
  tradeoffs[]
```

Proposal 阶段将 `research_brief` 和 `research_synthesis` 设为 required inputs，将 breakdown、fingerprint 和矩阵设为可追溯依据。每个 `proposal_packet.concept_options[]` 必须携带 `research_direction_refs`、`matrix_row_refs` 和 `fingerprint_rule_refs`，被选方案必须固定所采用的方向和原创边界。

Scene Plan 阶段将 `reference_source_matrix`、`research_breakdown`、`reference_fingerprint` 和 `source_media_review` 设为 required inputs。`scene_plan.metadata.source_mapping[]` 除现有 reference/source 证据外，必须增加 `matrix_row_id`、`matrix_resolution_id` 和 `research_direction_ref`。Scene director 可以在已批准 resolution 内选择具体 in/out 点，但不能重新发明参考意图、素材匹配或原创政策；确需改变时，先回写 `research_annotations` 并触发矩阵与 synthesis 局部重算。

### 5.11 Research 到创意方案的导演总控合同

Research 负责回答“看到了什么、证据在哪里、哪些方向可行”；Proposal 负责让用户选择“这条片往哪个方向做”。两者之间不能直接跳到口播，否则口播、分镜和素材阶段会各自重新解释 Research，导致局部都合理、全片却不一致。

因此，`cinematic-fast` 在 Proposal 阶段增加一个由 Agent 生成的独立中间产物，用户侧名称为 **导演总控单**，内部名称建议为 `creative_control_plan`。它不是新的大制作阶段，也不是口播脚本，而是已选创意方向的全片创意合同。

Proposal 内固定为两个连续子步骤：

```text
1. 选择创意方向：Agent 基于 research_synthesis 给出 3 个方向，用户选择 1 个
2. 审核导演总控单：Agent 基于已选方向生成草案，用户确认五类内容后锁定
```

只有总控单锁定后，才允许进入“剧本生成”。总控单不应为三个候选方向各生成一份完整合同，避免用户在 Research 之后面对过重的阅读和审批负担。

#### 5.11.1 总控单固定的五类内容

总控单必须把前面已经讨论的一致性内容翻译成制作人员能直接使用的语言：

| 内容 | 必须回答的问题 | 主要依据 |
|---|---|---|
| 内容方向 | 给谁看、为什么看、核心卖点和最终记忆点是什么？哪些主张不能说？ | `research_synthesis`、用户已选方向、品牌边界 |
| 故事和节奏 | 开头怎么抓人，卖点如何排序，哪里证明，哪里收束，哪里需要快或停？ | `reference_fingerprint` 的 Beat/Whole-video、矩阵处理结果 |
| 视觉规则 | 借鉴参考片哪些拍法、景别、机位、动作和文字协作？本项目要怎样改成自己的表达？ | `reference_fingerprint`、`research_breakdown`、行业提醒 |
| 事实和连续性 | 产品、功能、场景、动作、时间因果和画面证据必须怎样保持一致？ | `source_media_review`、矩阵证据、品牌规则 |
| 原创边界 | 保留什么结构机制、改变什么表达、明确不照搬什么？素材不足时如何改写？ | `reference_source_matrix`、`research_synthesis`、用户决定 |

每一条重要规则都必须能回指 Research 证据或用户决定；行业经验只能作为“行业提醒”，不能覆盖自有素材事实，也不能把参考片中不存在于自有素材的功能补写成事实。

#### 5.11.2 锁定和修改规则

- Agent 先生成 `creative_control_plan` 草案；审核台按五类内容分段展示，每段提供“通过”和“需要调整”。
- 用户不直接编辑合同字段；需要调整时写一句制作语言反馈，审核台保存反馈并生成可复制的 Agent 继续指令。
- 五类内容全部通过后，写入 `approved` 版本，记录总控单版本、内容 hash、确认人和确认时间；Proposal 才能向 Script 交接。
- 锁定后的合同不是永久冻结，但任何改变核心方向、卖点事实、连续性规则或原创边界的请求，都必须回到总控单创建新版本，不能由 Script 或 Scene Plan 静默覆盖。
- 新版本锁定后，系统显示影响范围：哪些口播、字幕、分镜、素材选择和制作准备需要重新确认；没有受影响的 Research 证据继续复用。

一致性门采用“硬约束阻断、软约束提醒”：产品身份、品牌主张、真实证据、权利边界、动作/物理/时间连续性违反时阻断；节奏、构图、镜头语法、光色材质、字幕声音和参考机制偏离时提示，并要求说明偏离原因。

#### 5.11.3 下游引用合同

总控单锁定后，Script、Scene Plan、Assets、Edit 和 Compose 都必须读取同一版本，并在产物中留下 `creative_control_ref`（总控单 ID、版本和 hash）。下游检查至少回答：

```text
口播是否只承诺总控单允许且素材能证明的卖点？
字幕是否与口播和画面强调同一件事？
每个镜头是否服务于已锁定的 beat、卖点和视觉规则？
素材和剪辑是否违反硬约束，或偏离软约束却没有说明？
参考片的结构借鉴是否仍在原创边界内？
```

这份合同的目的不是把 Agent 的创作变成表单填写，而是让 Agent 继续负责判断和生成，同时让审核台能看到“这条片接下来统一按什么标准做”，并在后续阶段发现偏离时知道应回到哪一层修正。

### 5.12 从导演总控单到制作剧本

导演总控单回答“整条片统一按什么标准做”，制作剧本回答“观众按什么顺序看到、听到和理解什么”。因此，本项目所说的剧本不是单独的口播稿，也不是直接展开到逐镜参数的拍摄表，而是连接创意合同和镜头执行的段落级生产合同。

`cinematic-fast` 的 Script 阶段新增独立确认关口。Agent 必须先读取已锁定的 `creative_control_plan`，再生成制作剧本；用户逐段确认后，才允许进入 Scene Plan。制作剧本至少包含：

| 段落内容 | 用户侧要看懂的问题 | 下游用途 |
|---|---|---|
| 段落任务 | 这一段要让观众知道、相信或感受到什么？ | 确定镜头意图和信息优先级 |
| 剧本生成 | 这一段说什么、屏幕上强调什么，两者是否重复或冲突？ | 生成可确认的段落级制作剧本 |
| 时间与节奏 | 从第几秒到第几秒，哪里快、哪里停、哪里需要动作钩子？ | 约束 Scene Plan 时间轴 |
| 画面与动作意图 | 需要什么主体、动作、场景和证据，不预先锁死具体素材文件 | 指导素材匹配和镜头设计 |
| 事实与连续性 | 哪句话必须由真实素材证明，产品外观、动作因果和使用场景如何连续？ | 建立事实硬门和连续性检查 |
| 总控引用 | 本段落实了总控单中的哪些规则，允许偏离什么？ | 防止后续阶段重新解释创意合同 |

用户侧按段落卡片确认，使用“这段可以”“这段要调整”的制作语言，不直接编辑内部 hash 或引用字段。任一段落需要调整时，Script 保持 `awaiting_human`，Agent 根据反馈生成新版本；全部段落确认后记录剧本版本、内容 hash、确认人和时间。

制作剧本确认后仍允许修订，但涉及卖点、事实、故事顺序或原创边界的修改必须先检查导演总控单；只改变措辞、停顿或字幕压缩时，可以只生成 Script 新版本。系统必须显示受影响的镜头、素材计划、口播、字幕和样片，不得静默沿用过期下游产物。

### 5.13 版本化镜头执行单

Scene Plan 继续负责镜头顺序、时间轴和素材映射；Assets 在不调用付费模型的前提下，把 Scene Plan、素材缺口和制作要求整理成用户可确认的 **镜头执行单**，内部名称为 `shot_execution_plan`。它参考附件拍摄脚本的拆解结构，但首期不追求复刻 PDF 排版；目标是形成可迭代的数据模板，并在审核台以一个镜头一张横向卡片展示。

每个镜头必须回答：

```text
这一镜为什么存在、持续多久、说什么或显示什么
主体在哪里做什么，景别、机位、运动、灯光和声音怎样配合
使用哪条自有素材、取哪一段、为什么适合
它承担真实证明、使用演示、氛围、过渡还是行动引导
素材是否足够；不足时补拍、改表达、删除还是生成补位
采用了哪些参考机制、行业提醒和总控规则，怎样保持原创
```

镜头执行单是版本化产物，至少绑定 `creative_control_ref`、`script_ref` 和 `scene_plan_ref`。锁定前允许 Agent 根据审核反馈重写方案，但禁止产生付费资产；锁定后生成执行单 ID、版本和 hash，后续素材生成、样片、剪辑和成片都引用同一版本。

执行单中的素材缺口按业务用途分为两类：

- **表达性缺口：** 氛围、转场、使用情境或不承担事实证明的动作镜头，可以优先提供生成补位方案；
- **证据性缺口：** 产品本体、规格、功能结果或效果证明，默认要求补真实素材。允许用户生成观看效果并用于最终成片，但生成片段不能单独把“缺少真实证据”改成“已经证明”，相关口播和字幕必须由真实证据支持或降级表达。

#### 5.13.1 本次真实运行复盘：执行单不是第二次素材匹配

`table-mat-mix-v7` 在制作剧本确认后实际完成了以下链路：读取已锁定总控单、制作剧本和 Scene Plan；按 Scene Plan 生成 7 张执行卡；补齐拍法、声音、证据类型和行业提醒；检查素材覆盖；生成 `asset_plan`、`production_lock` 和审核包；写入 `assets/awaiting_human` checkpoint。7 个镜头均有自有素材覆盖，未调用任何付费视频、TTS 或音乐服务。

这条链路中，下列内容可以固化为系统能力：

- 前置门槛：总控单已锁定、制作剧本已确认、Scene Plan 已生成；
- 一镜一卡的数据结构和横向审核方式；
- 每卡固定字段：镜头任务、动作、时长、口播、字幕、拍摄方式、证据类型、素材状态和缺口处理；
- 缺口分类：已有素材、补拍、改写、删除、生成演示；
- 执行单锁定前禁止付费生成；
- 执行单绑定总控单、制作剧本和 Scene Plan 的版本及 hash；
- 草案、待确认、已锁定的阶段状态和审核包。

下列内容仍属于 Agent 的临时发挥，不能直接当成稳定能力：

- 每镜的行业提醒、景别、机位、灯光、声音和拍摄措辞；
- “这段素材能证明什么”的自然语言总结；
- 素材覆盖是否足够的二次判断；
- 口播、音乐和 TTS 的具体选择；
- 素材标签、媒体 ID 和代理文件的自动解析。

这些内容后续应由镜头类型模板、行业经验规则和素材索引共同约束；Agent 负责项目适配，而不是每次重新发明字段和判断方式。

**必须去掉的重复交互：** 当前页面在 Scene Plan 的素材映射阶段已经让用户选择“原视频开始和结束秒数”，Assets 的镜头执行单又出现“这条素材用哪一段”。这两个动作实际修改同一个决定，第二次没有新增信息量。

后续职责划分固定为：

| 阶段 | 唯一职责 | 用户看到的内容 |
|---|---|---|
| Scene Plan | 决定使用哪条自有素材及具体区间 | 素材预览、起止时间、匹配理由 |
| 镜头执行单 | 确认这个镜头是否能执行 | 已选片段、它能证明什么、覆盖是否足够、缺口影响 |
| 缺口处理 | 决定补拍、改写、删除或生成演示 | 处理选项、费用、证据风险和对下游的影响 |

执行单不再重复提供开始/结束秒数输入框，而是只读展示“已选片段：00:00-00:02.2”。需要调整时，通过“调整素材片段”回到 Scene Plan 的原决定。数据层以 `scene_plan.metadata.source_mapping` 作为素材区间的唯一事实来源，执行单只保存 `source_mapping_ref` 或等价引用，不再维护第二套可编辑映射。

本次运行还发现一项需要在进入样片前修复的数据问题：生成的 `production_lock` 出现 `project_id: "unknown"`。这不会改变当前审核卡片，但会破坏后续审计、版本追踪和恢复，属于 P1 数据一致性缺陷。

### 5.14 审核台直连视频片段生成

首期只在 `cinematic-fast` 的镜头执行单中提供视频生成，不建设通用提示词编辑器，也不自动批量生成全部缺口。Agent 负责在生成前完成创意判断；审核台负责让用户理解方案、费用和影响，并执行已锁定参数。

#### 5.14.1 生成方案来源

Agent 编写补位方案前必须读取 `.agents/skills/ai-video-gen/SKILL.md` 和 `.agents/skills/seedance-2-0/SKILL.md`。生成方案至少固定：操作类型、镜头结构、主体与动作、环境、景别、机位运动、光色、声音、画幅、时长、参考素材、产品/人物一致性约束、禁止项和预计费用。

- 有清晰产品图或自有视频代表帧时，优先使用 `image_to_video` 或 `reference_to_video`；纯文字生成只用于不依赖产品身份的表达性镜头。
- 产品参考只能来自用户自有素材。参考片继续保持 `analysis_only`：Reference Fingerprint 可以贡献节奏、景别、镜头机制和视觉规律，但参考片原始帧或视频不得作为模型输入。
- 产品身份需要复用同一组清晰参考，并明确要求外观、颜色、材质和关键结构保持一致；不得依赖模型生成可读 Logo、字幕或规格文字，这些内容由后期文字层完成。
- 行业经验通过已锁定的拆解维度和行业提醒进入镜头描述，例如证据动作时长、俯拍适用性、产品细节景别和字幕安全区；行业经验不得覆盖现场素材事实。

#### 5.14.2 Fast 到 Standard 的两步生成

所有调用仍通过 `video_selector`，并限定 `allowed_providers: [seedance]`、`preferred_provider: seedance`，由 selector 在可用的 Seedance 网关间选择；不得在失败时静默切换到其他模型家族。当前环境可用路径为 fal.ai `seedance_video`，实际生成前必须重新检测并在确认层展示准确网关、模型和价格。

```text
Fast 预览：5 秒、480p、目标画幅，用来判断构图、主体和动作方向
Standard 成片候选：沿用已选 Fast 的 seed、720p，按执行单时长生成
```

Standard 时长遵守 Seedance 2.0 的 4–15 秒范围；短于 4 秒的目标镜头生成 4 秒后在后期取用，长镜头按执行单拆分或在 15 秒内生成。Fast 只用于确认方向；用户选择“方向可用，生成清晰版”后，才允许生成 Standard 并标记为最终成片候选。

Seedance 原生同步音频默认保留，便于检查动作声和环境声；正式口播、字幕、配乐以及是否采用生成音轨仍由制作时间线决定。审核台内部明确标记“生成演示”和生成来源，最终成片默认不叠加“生成演示”字样，也不因为内部追溯标记破坏画面表达。

#### 5.14.3 付费、任务与恢复边界

- 生成按钮固定放在对应镜头卡片中，但在整份镜头执行单锁定前置灰，避免方案变化后浪费费用。
- 点击“生成预览”先展示供应方、模型、档位、时长、分辨率、预计费用、剩余预算和证据风险；用户明确确认后才创建付费任务。
- 浏览器只提交镜头 ID、方案 ID、执行单版本和质量档，服务端从已锁定执行单解析提示词和参考素材，禁止通过接口任意提交提示词或项目外路径。
- 每个任务必须有幂等键、费用预留、执行单 hash、尝试 ID、父版本、远端任务标识、状态、实际费用和输出路径。一个项目可以排队多个镜头，首期并发数固定为 1。
- 任务状态至少包括“排队中、生成中、已完成、失败、需要确认”；通过现有运行事件和审核台刷新展示心跳、耗时和费用。
- 服务重启后恢复已排队任务，并根据持久化的远端任务标识继续查询已提交任务。无法确认远端状态时不得自动重新付费生成，而是标记“需要确认”。
- 失败重试、再次生成和 Standard 升级都是新的付费尝试，必须重新显示费用；同一幂等键不得产生第二次调用。

生成完成后直接在原镜头卡片播放。Fast 提供“方向可用，生成清晰版 / 再试一次 / 不采用”；Standard 提供“用于本镜头 / 再生成一个版本 / 暂不采用”。采用 Standard 时原子更新执行单的选中版本和 `asset_manifest` 生成来源；已有样片、剪辑或成片按影响范围进入需要更新状态。完成镜头选择后，页面继续提供现有 Agent 指令进入样片阶段；自动唤起 Agent 不在本期范围内。

## 6. Research 评价体系

建议每次 research 生成一个内部 `research_scorecard`，总分 10 分，每项 0-2 分。

| 维度 | 0 分 | 1 分 | 2 分 |
|---|---|---|---|
| 输入覆盖 | 未检查主要输入 | 检查但有漏项 | 参考和自有素材 100% 有证据 |
| 证据可追溯 | 结论无法定位 | 部分有帧或时间点 | 每个关键结论都有路径、区间或关键帧 |
| 参考-素材匹配 | 只有文件名相似 | 有粗略用途说明 | 每个关键镜头都有动作级匹配理由 |
| 生产可用性 | 无区间/风险/音频判断 | 信息不完整 | 可直接支撑 scene plan 和脚本 |
| 执行纪律 | 串行、付费或无 checkpoint | 并行、零付费、可恢复，但编排耗时未归因或提交非单事务 | 并行、零付费、可恢复、hash/schema 通过，且编排耗时已归因、9 制品经一次性事务提交 |

### 6.1 硬性失败条件

出现以下任一情况，research 不得通过：

- 参考视频被加入自有素材候选或输出素材；
- 任意自有素材未真实探测；
- 核心参考镜头没有自有素材候选或明确缺口；
- 结论无法追溯到画面、时间点或文件；
- 未经批准发生付费调用；
- artifact、hash 或 checkpoint 无法恢复。

### 6.2 本次运行的评价

- 输入覆盖：2/2
- 证据可追溯：2/2
- 参考-素材匹配：2/2
- 生产可用性：2/2
- 执行纪律：1/2

内容层面可判定为通过；执行纪律扣分来自提交过程缺少 staged view，以及语义编排和提交耗时未被单独记录。

## 7. 待升级项

### P0：必须优先升级

#### P0-1：补齐 research 编排事件

除工具 `start/finish` 外，研究编排器需要写入：

```json
{
  "run_id": "research-000001",
  "stage": "research",
  "operation": "semantic_synthesis",
  "status": "running",
  "unit": {"kind": "source_match", "current": 3, "total": 7},
  "attempt": 1,
  "started_at": "...",
  "updated_at": "...",
  "message": "正在建立参考镜头到自有素材的匹配证据"
}
```

要求：超过 30 秒的编排步骤每 5–10 秒 heartbeat；研究完成时写入各子步骤机器耗时、墙钟耗时和等待原因。

#### P0-2：统一 staged view 校验

`write_artifact_atomic(..., sink=...)` 与 `write_checkpoint(..., sink=...)` 应能在同一事务中读取 staged overlay，而不是依赖 artifact 先落盘。

验收：同一个 transaction 内完成 9 个不可变研究 artifact、代表帧和 research checkpoint；`research_annotations` 作为独立可编辑 overlay 版本化提交，不混入完成事务。故障注入后不得出现半套制品。

#### P0-3：固定 research scorecard artifact

将评价结果写入 `artifacts/research_scorecard.json`，由 checkpoint 保存摘要。这样工作台可以明确展示“研究完成”与“研究质量通过”是两件事。

#### P0-4：固定拆解 profile 与 research breakdown

将 `ecommerce-storyboard-cn@1.0` 固化为首个内置 profile，并新增 `research_breakdown` artifact。profile 必须在 Research 启动时锁定并进入缓存键、artifact provenance 和 checkpoint；参考与自有素材必须使用同一 profile 投影。

验收：完整表达附件 14 列；无效时长进入 warning/失败路径；OCR 观察携带置信度和证据；更换 profile 版本不得触发媒体重新探测。

#### P0-5：完成新制品的全链路注册

按照 5.9 的接入矩阵，一次性补齐 4 个新增不可变 artifact 的 schema、`ARTIFACT_NAMES`、pipeline `produces`、checkpoint envelope 校验、Backlot 文件映射与 operator 投影、Research director 写入要求、contract/integration tests。同步注册 `research_annotations` overlay，但不将其设为完成 checkpoint 的必需输入。

验收：任何一个接点缺失时 contract test 失败；Research completed checkpoint 必须同时包含 9 个可校验 envelope；Backlot 对用户展示“分镜拆解、参考镜头 × 我的素材、可选方向、研究检查结果”，而不是要求用户理解内部制品名。

### P1：下一版本完成

#### P1-1：增强矩阵 resolution 与人工决策

P0 先落地可供下游消费的单一最佳匹配。P1 再让每行支持多个候选、排序理由、用户 resolution 和局部重算；基础字段固定包含：

- `reference_scene_id`
- `reference_time_range`
- `reference_intent`
- `source_media_id`
- `source_time_range`
- `match_reason`
- `confidence`
- `evidence_frames`
- `unmatched_gap`

矩阵 resolution 会直接成为后续 Scene Plan 的输入，而不是重新猜映射。

#### P1-2：拆分机器耗时、代理耗时和人工等待

至少记录三类时间：

- `machine_time`：工具真正执行时间；
- `orchestration_time`：分析、综合、重试、校验和提交；
- `human_wait_time`：等待用户确认或外部授权。

所有报告都必须按这三类时间归因。

#### P1-3：设置 research 时间预算

针对“1 条参考 + 不超过 10 条自有素材”的标准 fixture，目标为：

- 输入与 preflight：30 秒以内；
- 并行媒体分析：2 分钟以内；
- 语义梳理与证据矩阵：3 分钟以内；
- 校验和 checkpoint：30 秒以内；
- 总 research：**6–8 分钟，不含人工审批**。

性能报告必须记录 CPU 型号/核心数、内存、操作系统、本地磁盘、ffmpeg 与 analyzer 版本、并发上限、视频数量/总时长/分辨率以及网络模型是否参与，不能只报单次最快值。统一口径如下：

- `cold-cache`：清空该输入的媒体分析与语义投影缓存，但依赖、模型和二进制已安装；
- `warm-cache`：输入 hash、工具版本、参数、profile 和行业先验均未变化，允许命中媒体与语义缓存；
- 端到端墙钟从第一个 `research started` 事件计到 completed checkpoint 原子落盘；排除 `human_wait_time`，但包含重试、校验和提交；
- 每种缓存状态至少运行 20 次，报告 p50、p95、失败率和缓存命中率；失败和超时不能从样本中剔除；
- 首期验收目标：cold-cache p95 不超过 8 分钟，warm-cache p95 不超过 4 分钟，均无硬性失败项。

若超过预算，必须在工作台显示超时步骤、等待原因和 cache 状态，而不是继续显示普通“分析中”。

#### P1-4：控制探索比例

建议采用“80% 固定合同 + 20% 探索预算”：

- 80% 时间保证基础探测、证据和产物可恢复；
- 20% 时间允许尝试新的理解、匹配或创意方法；
- 探索超时后必须回退到最近一次有效结果；
- 探索不得修改 reference/source 隔离规则。

#### P1-5：版本化行业先验及现场适用性校验

首期只提供短视频通用和电商产品证明两个规则包。规则通过 `target_dimensions` 引用 profile 维度，并记录适用条件、推荐区间、置信度、例外和来源；规则应用结果不得覆盖参考观察事实。

#### P1-6：渐进式 Research 工作台

**已落地：** Backlot 已实现固定五个子阶段导航（参考片怎么拍、我的素材能不能接上、参考镜头和我的素材怎么对应、这条片准备怎么做、还有什么没看清），每个子阶段拥有独立的中间产物面板；分镜拆解和参考镜头 × 我的素材改为横向滑动卡片轨道。没有参考片时保留第一子阶段位置并置灰，明确显示“本项目没有参考片，这一步不需要处理”。

**本轮 P1：** 增加“需要我确认”决策收件箱、影响说明和进入创意方案的交接状态。仅对阻塞卖点、素材选择、重新确认、方向选择和品牌边界发起决策；所有阻塞项处理完成且研究检查通过后，向 Proposal 交接已选方向、镜头处理结果、原创边界和待验证前置条件。由于当前没有直连 Code Agent，交接状态提供可复制的继续指令；自动唤起 Agent 作为下一步能力建设。

工作台按“进度、参考片怎么拍、我的素材、参考镜头 × 我的素材、可选方向、需要我确认”组织。P1 增加决策收件箱、影响预览和“进入创意方案”交接状态。默认自动推进，只有开头钩子、核心卖点证明或结尾行动引导没有可信自有素材，且没有补素材/改表达/删减的处理方案时，才显示“等你确认”。

验收：制作人员不需要理解 profile、artifact、矩阵或 resolution，就能回答“哪里缺素材、该补什么、推荐用哪段、采用后会影响什么”；工程术语只在技术详情、导出和日志中出现。

#### P1-7：完善 research annotations 操作

> 实施状态：三类操作的注册、影响预览与可撤销记录已在 P0 落地；P1 补齐 `request_local_reanalysis` 触发自动补做分析的执行引擎，其余不变。

在现有素材处置、业务备注、Logo、主张边界和参考机制操作之外，增加三类面向用户的显式操作：

```text
保留这个方向 / 换一个方向 / 暂不采用
采用这段 / 换一段 / 需要补拍或补素材 / 改成别的表达 / 删除这一镜
重新看这一段（动作、台词、字幕、声音、时长）
```

系统分别映射为 `set_direction_preference`、`resolve_matrix_row`、`request_local_reanalysis`。选方向只更新受影响的可选方向、检查结果和方案候选；处理素材匹配只更新对应镜头及依赖的方案/分镜；重新确认会按缺失证据补做分析，不直接改写原始观察。每次操作都要先说明“会影响哪些镜头和方案”，可撤销，并显示“正在更新 / 已更新”。

#### P1-8：在 Proposal 锁定导演总控单

新增 `creative_control_plan` 的生成、展示、确认和版本锁定能力，但首期只覆盖 `cinematic-fast`。Proposal 内先完成方向选择，再由 Agent 生成总控单草案；审核台按“内容方向、故事和节奏、视觉规则、事实和连续性、原创边界”五段展示，不增加新的大制作阶段。

P1-8 必须完成以下交接：Research 的 fingerprint、素材匹配、行业提醒和用户决定进入总控单；总控单锁定后进入 Script；Script、Scene Plan、Assets、Edit 和 Compose 引用同一总控版本；总控单修订会生成影响预览并使受影响的下游产物重新确认。首期不接自动唤起 Code Agent，仍由审核台提供可复制的继续指令。

#### P1-9：制作剧本确认与镜头执行单

将现有 Script 升级为“剧本生成”，产出段落级制作剧本，并增加独立确认关口。每段展示段落任务、口播、字幕、时间节奏、画面意图、证据要求和总控依据；只有全部段落确认后才生成 Scene Plan。

Assets 在付费调用前生成版本化 `shot_execution_plan`，将 Scene Plan 已完成的真实素材映射、行业模板和素材缺口整理成横向镜头卡片。素材区间在 Scene Plan 只确认一次；执行单以只读方式展示片段和“能证明什么”，不再重复询问起止秒数。用户锁定整份执行单后，才允许进入素材生成或样片制作。执行单修订必须显示受影响的生成方案、素材、样片和后续阶段。

锁定执行单后，用户侧不再重复审核“制作清单”。系统将“制作准备”标记为已完成，样片阶段成为下一步待执行阶段；审核台展示一条可复制给 Code Agent 的继续指令：`继续 <项目 ID>，读取已锁定的镜头执行单并生成样片`。代理、口播、字幕和合成配置属于系统准备动作，只有缺素材、付费授权或其他阻塞项才会打断交接。

P1-9 的后续补强项：

1. 删除 Assets 阶段重复的素材区间编辑器和“参考视频仅用于分析”的重复说明；保留一个简短的来源状态标识即可。
2. 为执行卡增加“调整素材片段”回链，而不是复制 Scene Plan 的输入表。
3. 用镜头类型模板固化产品出现、贴合细节、功能证据、动作-结果、使用场景和 CTA 收尾的行业经验。
4. 用 `media_index` 自动解析媒体 ID、路径、有效区间和代表帧，并校验素材区间确实覆盖镜头时长。
5. 修复 `production_lock.project_id` 的来源绑定，禁止生成 `unknown` 项目标识。

#### P1-10：审核台直连 Seedance 补位生成

对执行单中明确的素材缺口，由 Agent 结合 `ai-video-gen` 与 `seedance-2-0` 形成可生成方案；审核台提供逐镜“生成预览”按钮，通过 `video_selector` 限定 Seedance 路径发起任务。

首期采用 Fast 预览、同 seed 升级 Standard 的两步流程，生成前逐次确认模型、费用和证据风险。任务必须持久化、幂等、可恢复并纳入成本记录；产品本体和规格证据仍默认要求真实素材，生成片段可以进入最终成片但不能替代事实证据。审核台显示生成来源，最终成片默认不叠加“生成演示”字样。

### P2：长期优化

- research 结果跨项目缓存，按内容 hash 复用；
- 对相同产品类别沉淀卖点和镜头意图词典；
- 将素材匹配置信度与后续 scene plan 返工率关联；
- 建立“研究预测与最终成片表现”的回溯数据集。

## 8. 推荐的标准 Research 流程

```text
读取 intake
  -> 建立 reference/source 清单
  -> 锁定 analysis_dimension_profile
  -> 对无依赖媒体任务做有界并行：技术探测、场景检测、抽帧、音频检查
  -> 形成 source media review
  -> 按 profile 形成 reference/source research breakdown
  -> 形成 reference fingerprint
  -> 应用行业先验并记录适用性/冲突/例外
  -> 建立 reference-to-source evidence matrix
  -> 生成 research synthesis、research brief 和差异化方向
  -> research scorecard
  -> schema/hash 校验
  -> 原子 checkpoint
  -> 自动进入 proposal
```

这里的“并行”只适用于无数据依赖的 analyzer 调用以及不同媒体之间的同类调用，并受 CPU、I/O 和工具并发上限约束。语义层必须按声明式 DAG 的拓扑顺序执行：

```text
media_index + video_analysis_brief + source_media_review + locked profile
  -> research_breakdown
  -> reference_fingerprint + industry_prior_evaluation
  -> reference_source_matrix
  -> research_synthesis + research_brief
  -> research_scorecard
  -> checkpoint
  -> proposal：选择创意方向
  -> Agent 生成导演总控单草案
  -> 用户确认五类内容并锁定总控合同
  -> Agent 生成制作剧本
  -> 用户逐段确认制作剧本
  -> scene_plan
  -> Agent 读取 Scene Plan 已确认的素材映射，生成镜头执行单和素材缺口方案（零付费）
  -> 用户锁定镜头执行单和费用范围
  -> 审核台逐镜 Fast 预览 -> 同 seed Standard 成片候选
  -> 用户选择镜头版本
  -> Agent 继续 sample / edit / compose
```

同一层无依赖节点可以并行；下游不得在上游 hash 未固定前提前运行。每一步都必须有：输入 hash、输出 hash、耗时、证据、失败处理和下一动作。

## 9. 验收标准

Research 升级完成后，使用一条参考视频和 6 条自有素材回归，必须满足：

1. 参考和自有素材 100% 完成真实探测；
2. 无依赖媒体 analyzer 按有界并发执行，语义投影按 DAG 顺序执行，重复探测率为 0；
3. 机器耗时、编排耗时和人工等待可分别统计；
4. 每个参考镜头都有自有素材匹配、置信度或明确缺口；
5. scorecard 达到 8/10 且无硬性失败项；
6. 9 个不可变 research artifact、代表帧和 checkpoint 在一个事务中可恢复；
7. 研究阶段不产生任何付费调用；
8. 标准 fixture 的 cold-cache 与 warm-cache 均达到 P1-3 定义的 p95 目标，超时有明确步骤和原因；
9. 内置 `ecommerce-storyboard-cn@1.0` 能完整表达附件 14 列；附件 43 个工作表只作为离线 profile fixture 回归，不代表生产运行时支持 Excel 上传、任意列映射或按工作表名称路由；
10. 参考和自有素材使用相同维度生成 `research_breakdown`，每个观察值均可追溯且低置信内容有明确标记；
11. 修改 profile 或行业规则只增量重算语义产物，不重新执行媒体探测；
12. 工作台能展示用户熟悉的分镜表，并在详情中用“拍法和节奏、保持一致的地方、行业提醒、怎样做得更像自己的片子”表达参考机制、一致性约束、行业判断和原创边界；
13. 行业先验、参考观察和项目适配在 artifact 与界面中严格分离；
14. Proposal 的每个概念都引用 synthesis 方向和矩阵行，Scene Plan 的每个 source mapping 都引用已解析的 matrix resolution，不重新猜映射；（P0 已实现，checkpoint 握手校验强制引用）
15. 用户可完成“选方向、处理素材匹配、重新看这一段”三类操作；每个操作均可预览影响、撤销，并只更新受影响的结果。（操作记录、影响预览与撤销 P0 已实现；`request_local_reanalysis` 的自动补做分析执行在 P1 补齐）
16. Proposal 先让用户选择创意方向，再展示并锁定导演总控单；总控单覆盖五类内容，全部下游阶段能引用同一版本，硬约束偏离会阻断、软约束偏离会提示并记录原因。
17. 用户能在审核台看到总控单的五类中间产物、Research 依据、确认状态和修改影响；没有直连 Code Agent 时，页面提供可复制的继续指令，不把“已展示”误报为“已执行”。
18. 总控单锁定后先生成段落级制作剧本；用户能逐段确认口播、字幕、节奏、画面任务和证据要求，未全部确认时不得进入 Scene Plan。
19. 镜头执行单按一镜一卡横向展示，绑定总控、剧本和 Scene Plan 版本；每个镜头都有真实素材选择、证据类型、素材缺口或明确的补位处理方案。
20. 镜头执行单锁定前不发生付费视频生成；锁定后用户可以在镜头卡片中查看准确模型、档位、费用和风险，再逐镜发起生成。
21. Seedance 补位生成使用 Fast 预览和同 seed Standard 升级；任务在刷新和服务重启后可追踪，同一幂等键不重复调用，失败或未知远端状态不自动再次扣费。
22. 生成片段在审核台和制品中可追溯，可以被选入最终成片；生成内容不得单独承担产品本体、规格或功能结果的事实证明，最终成片默认不叠加“生成演示”文字。
23. 同一镜头的自有素材路径与起止区间只在 Scene Plan 确认一次；镜头执行单只读展示已选片段、证明用途和覆盖状态，调整入口必须回链到 Scene Plan，不能出现第二套起止秒数输入。
24. 每份 `production_lock` 的 `project_id` 必须等于项目标识；在进入样片前校验其与 `project.json`、执行单和 checkpoint 一致，禁止出现 `unknown`。

## 10. 本项目证据

- [`events.jsonl`](../../projects/table-mat-mix-v7/events.jsonl)
- [`checkpoint_research.json`](../../projects/table-mat-mix-v7/checkpoint_research.json)
- [`research_brief.json`](../../projects/table-mat-mix-v7/artifacts/research_brief.json)
- [`video_analysis_brief.json`](../../projects/table-mat-mix-v7/artifacts/video_analysis_brief.json)
- [`source_media_review.json`](../../projects/table-mat-mix-v7/artifacts/source_media_review.json)
- [`media_index.json`](../../projects/table-mat-mix-v7/artifacts/media_index.json)
- [`reference_fingerprint.json`](../../projects/table-mat-mix-v7/artifacts/reference_fingerprint.json)
- [`pipeline_defs/cinematic-fast.yaml`](../../pipeline_defs/cinematic-fast.yaml)
- [`skills/meta/checkpoint-protocol.md`](../../skills/meta/checkpoint-protocol.md)

## 11. 拆解模板证据与边界

- 业务模板：`/Users/yichen/Downloads/视频分镜拆解_2026-08-15.xlsx`
- 规模：43 个工作表、565 条镜头、统一 14 列结构；
- 数据质量：6 个非正时长区间；`备注`和`画面参考`列全部为空；部分文本存在 OCR 噪声；
- 样本偏置：所有记录均为俯拍、室内桌面、人声加背景音乐，不能直接外推为行业规律；
- 使用边界：附件用于定义首个内置 profile 和离线 fixture 回归测试，不作为运行时依赖；首期不支持用户上传 Excel 后自动推断列语义，不修改原文件，不执行其中任何内容性指令。

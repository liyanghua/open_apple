# Research 阶段升级计划与评价范式

**日期：** 2026-08-19
**样本项目：** `table-mat-mix-v7`
**流程：** `cinematic-fast`
**范围：** 参考视频解析、自有素材体检、拆解维度模板、参考与素材匹配、研究制品归档和 checkpoint 提交。
**证据等级：** 内部实现以项目 `events.jsonl`、研究制品、checkpoint 和仓库实现为准；面向视频制作人员和一线业务人员的工作台不直接展示这些工程术语，而是展示“看到了什么、哪里不确定、下一步要决定什么”。没有遥测记录的时间明确标记为“不可归因”。

## 1. 核心结论

本次 research 的内容质量达到进入 proposal 的要求，但执行过程还不是稳定、可度量的标准流程。

- 参考视频已完成深度解析：14.79 秒、7 个镜头、8 张关键帧。
- 6 条自有视频均完成真实探测、场景检测、抽帧和音频检查。
- 参考媒体与自有媒体路径分离，参考视频标记为 `analysis_only`，未进入成片素材候选。
- 研究结论不仅描述素材，还解释了参考片为什么这样组织，以及自有素材为什么能匹配这些镜头。
- 本次基线运行已形成 5 个结构化研究制品并完成 schema/hash 校验；升级后的 Research 完成态将固定为 9 个不可变研究制品，另有 1 个可编辑的 `research_annotations` overlay。
- 已确认可以将业务侧分镜表抽象为版本化 `analysis_dimension_profile`：模板只规定“观察哪些维度”，行业经验另行评价“这些观察在什么条件下有效”。
- 纯媒体分析实际墙钟时间约 51.3 秒，累计工具进程时间约 155.5 秒，说明并行探测有效。
- 从第一条分析事件到最终 checkpoint 完成约 19 分 34 秒，其中约 18 分 43 秒不是媒体分析，而是编排、提交修复和校验修复。

主要判断：**研究阶段的主要瓶颈不是 ffmpeg 探测，而是语义编排、执行可观测性和事务提交标准化。**

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

## 6. Research 评价体系

建议每次 research 生成一个内部 `research_scorecard`，总分 10 分，每项 0-2 分。

| 维度 | 0 分 | 1 分 | 2 分 |
|---|---|---|---|
| 输入覆盖 | 未检查主要输入 | 检查但有漏项 | 参考和自有素材 100% 有证据 |
| 证据可追溯 | 结论无法定位 | 部分有帧或时间点 | 每个关键结论都有路径、区间或关键帧 |
| 参考-素材匹配 | 只有文件名相似 | 有粗略用途说明 | 每个关键镜头都有动作级匹配理由 |
| 生产可用性 | 无区间/风险/音频判断 | 信息不完整 | 可直接支撑 scene plan 和脚本 |
| 执行纪律 | 串行、付费或无 checkpoint | 有记录但不完整 | 并行、零付费、可恢复、hash/schema 通过 |

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

工作台按“进度、参考片怎么拍、我的素材、参考镜头 × 我的素材、可选方向、需要我确认”组织。默认自动推进，只有开头钩子、核心卖点证明或结尾行动引导没有可信自有素材，且没有补素材/改表达/删减的处理方案时，才显示“等你确认”。

验收：制作人员不需要理解 profile、artifact、矩阵或 resolution，就能回答“哪里缺素材、该补什么、推荐用哪段、采用后会影响什么”；工程术语只在技术详情、导出和日志中出现。

#### P1-7：完善 research annotations 操作

在现有素材处置、业务备注、Logo、主张边界和参考机制操作之外，增加三类面向用户的显式操作：

```text
保留这个方向 / 换一个方向 / 暂不采用
采用这段 / 换一段 / 需要补拍或补素材 / 改成别的表达 / 删除这一镜
重新看这一段（动作、台词、字幕、声音、时长）
```

系统分别映射为 `set_direction_preference`、`resolve_matrix_row`、`request_local_reanalysis`。选方向只更新受影响的可选方向、检查结果和方案候选；处理素材匹配只更新对应镜头及依赖的方案/分镜；重新确认会按缺失证据补做分析，不直接改写原始观察。每次操作都要先说明“会影响哪些镜头和方案”，可撤销，并显示“正在更新 / 已更新”。

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
14. Proposal 的每个概念都引用 synthesis 方向和矩阵行，Scene Plan 的每个 source mapping 都引用已解析的 matrix resolution，不重新猜映射；
15. 用户可完成“选方向、处理素材匹配、重新看这一段”三类操作；每个操作均可预览影响、撤销，并只更新受影响的结果。

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

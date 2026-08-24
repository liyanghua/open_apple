# OpenMontage → 电商参考视频创意升级：AI Coding 快速适配实施指南

> 版本：v0.1<br>
> 目标：把现有“参考视频高保真复刻”链路升级为“Reference-grounded Creative Optimization（参考驱动的创意优化）”<br>
> 适用范围：15–30 秒电商短视频、商品卖点视频、爆款参考视频复刻/改编、Shot Generation Optimizer<br>
> 核心参考：OpenMontage（`calesthio/OpenMontage`）<br>
> 本文定位：**不是 OpenMontage 调研报告，而是一份可以直接交给 AI Coding Agent 执行的架构/数据/Prompt/验收规范。**

---

## 0. TL;DR：AI Coding 先做什么

不要 Fork OpenMontage 全项目，也不要先接它全部 Provider / Backlot / Pipeline。

对当前电商视频系统，第一阶段只借 OpenMontage 六个核心思想：

1. **Reference Video 是一等入口**：参考片必须先分析，不直接进入复刻。
2. **Pipeline Manifest**：把生产阶段、输入/输出、Gate 写成 YAML，而不是散在代码和 Prompt 里。
3. **Director Skill**：创意判断放在 Markdown Skill，不塞进 Python/TS orchestration。
4. **Canonical Artifact / IR**：每个阶段输出可验证 JSON，而不是靠自然语言上下文串联。
5. **Taste Profile + Beat Map + Shot Intent**：先确定创作标准，再做脚本/镜头。
6. **Reviewer + Checkpoint**：每一层能独立评测、局部重跑，不用整片返工。

针对当前 batch-002 的 4 个问题：

| 问题 | 现状 | OpenMontage 借鉴点 | MVP 动作 |
|---|---|---|---|
| 花字弱 | `caption_style_fingerprint` 只描述静态样式 | Taste Profile / Scene overlay 分层 | 先新增 `caption_intent` / `caption_recipe_id`，渲染仍走 Remotion |
| 转场硬 | `transition_in/out` 空或固定 hard cut | Scene Director + motion intensity + limited vocabulary | 场景级显式 transition intent，再映射到 Recipe |
| 无故事 | 卖点清单式 script | Cinematic Script Director 的 beat map | 引入 `hook → escalation → reveal → landing` |
| Hook 弱 | 单一功能直给 | Reference Analyst → 2–3 differentiated concepts | 增加 `reference_critique` + `creative_concepts[]`，禁止直接复制 reference hook |

**最小目标不是“把 OpenMontage 跑起来”，而是把当前系统的数据流改成：**

```text
Reference Video
  ↓
Reference Analysis
  ↓
Reference Critique
  ↓
Creative Proposal × 3
  ↓
Selected Concept + Taste Profile
  ↓
Beat Script
  ↓
Scene / Shot Plan
  ↓
Retrieve / Generate / Edit
  ↓
Remotion Compose
  ↓
Creative Judge + Video Judge
  ↓
Local Repair / Editorial Gallery
```

---

# 1. 为什么采用 OpenMontage 的“架构思想”，而不是整套 Fork

## 1.1 OpenMontage 最有价值的不是工具数量，而是 Agent Contract

OpenMontage 的核心设计是：

```text
Agent reads pipeline manifest (YAML)
  → reads stage director skill (MD)
  → uses tools
  → self-reviews
  → checkpoints
  → human approval
```

它明确把职责分成：

- **Agent / Skill：** 创意判断、Pipeline 路由、阶段决策、Review；
- **代码：** 工具、数据持久化、Schema Validation、Provider 调用、Render；
- **Artifact：** 阶段间唯一可信的数据交换格式。

这个边界非常适合现有视频生成系统，因为当前问题的根因恰恰不是“少写一个 API”，而是：

> Reference Analysis、Creative Standard、Script Director、Scene Director、Render Capability 混在一起，导致上游平庸时，下游只能高保真地把平庸生产出来。

---

## 1.2 本项目不要复用 OpenMontage 的全部 Pipeline

OpenMontage 有 cinematic / animation / animated-explainer / talking-head / hybrid 等大量 Pipeline。

当前只新增一个：

```text
reference-commerce
```

它只解决一个非常聚焦的问题：

> **给定商品事实 + 爆款/参考视频 + 素材资产，如何用最低成本生成比参考片更好的 15–30 秒电商短视频。**

暂时不做：

- 通用纪录片；
- Podcast repurpose；
- Talking head；
- 3D World；
- 全 Provider 市场；
- Backlot 全量复刻；
- 多 Runtime 用户选择 UI；
- 完整 Publish Pipeline。

---

# 2. License Boundary：代码复用前必须先定边界

OpenMontage 当前仓库 README 标注为 **AGPLv3**。

对于企业闭源系统，建议第一阶段采用：

### 推荐：Pattern / Protocol Reimplementation

可重点借鉴并自行实现：

- Pipeline Manifest 设计思想；
- Artifact-first 数据流；
- Reference Analyst 5-aspect 方法；
- Skill 分层；
- Beat Map；
- Taste Profile；
- Reviewer / Checkpoint 机制；
- Tool Registry / capability routing 思想；
- Schema 字段设计思想。

### 谨慎：直接 Copy 源代码

以下若直接复制、修改并部署，需单独做许可证评估：

- OpenMontage Python Tool 实现；
- Backlot；
- Remotion Composer 内具体实现；
- Pipeline loader / checkpoint 源代码；
- 其他 AGPL 覆盖代码。

本文所有代码/Schema 示例均为**面向现有系统重新设计的适配版本**，目标是避免 AI Coding Agent 无脑 Copy 整个仓库。

> 本节不是法律意见。商业部署前应由法务/开源合规负责人确认许可证义务。

---

# 3. 当前系统的目标架构

## 3.1 目标不是“Reference Replication”，而是“Reference-grounded Creative Optimization”

旧逻辑：

```text
reference_video
  ↓
reference_fingerprint
  ↓
script / scene_plan / caption_style
  ↓
copy
```

新逻辑：

```text
reference_video
  ↓
ReferenceAnalysis
  ↓
ReferenceCritique
  ├─ KEEP
  ├─ IMPROVE
  ├─ REPLACE
  └─ DO_NOT_COPY
  ↓
CreativeConcepts × 3
  ↓
SelectedConcept
  ↓
TasteProfile
  ↓
BeatScript
  ↓
ScenePlan / ShotSpec
  ↓
Production
```

关键原则：

> **Reference 是 Evidence，不是 Prescription。**

参考视频告诉系统：

- 哪些信息已经被市场证明值得表达；
- 哪些镜头语言属于这个品类；
- 节奏大约是什么；
- Proof 如何发生；
- 商品在故事中的角色是什么。

但参考视频不能自动决定：

- 必须复制它的 Hook；
- 必须复制它的硬切；
- 必须复制它的花字；
- 必须复制它的卖点顺序；
- 必须复制它的故事结构。

---

# 4. 推荐目录结构

在现有视频项目里新增以下最小结构：

```text
video-system/
├── pipeline_defs/
│   └── reference-commerce.yaml
│
├── skills/
│   ├── meta/
│   │   ├── reference-video-analyst.md
│   │   ├── reference-critic.md
│   │   ├── taste-direction.md
│   │   ├── reviewer.md
│   │   └── checkpoint-protocol.md
│   │
│   └── pipelines/
│       └── reference-commerce/
│           ├── proposal-director.md
│           ├── script-director.md
│           ├── scene-director.md
│           ├── asset-director.md
│           ├── compose-director.md
│           └── final-reviewer.md
│
├── schemas/
│   └── artifacts/
│       ├── reference-analysis.schema.json
│       ├── reference-critique.schema.json
│       ├── proposal-packet.schema.json
│       ├── beat-script.schema.json
│       ├── scene-plan.schema.json
│       ├── asset-manifest.schema.json
│       ├── creative-review.schema.json
│       └── repair-plan.schema.json
│
├── tools/
│   ├── analysis/
│   │   ├── video_analyzer.*
│   │   ├── scene_detect.*
│   │   ├── frame_sampler.*
│   │   └── transcript_fetcher.*
│   ├── generation/
│   │   └── video_generator_adapter.*
│   ├── retrieval/
│   │   └── asset_retriever.*
│   └── render/
│       └── remotion_compose.*
│
├── projects/
│   └── <run-id>/
│       ├── artifacts/
│       ├── assets/
│       ├── previews/
│       └── renders/
│
└── tests/
    ├── contracts/
    ├── golden/
    └── regression/
```

如果现有目录已经类似，不要为了对齐 OpenMontage 重构整个 repo；只补缺失层。

---

# 5. Pipeline Manifest：第一版可以直接照这个做

文件：`pipeline_defs/reference-commerce.yaml`

```yaml
name: reference-commerce
version: "0.1"
description: >
  Reference-grounded ecommerce short-video pipeline.
  Analyze the reference, critique its creative ceiling,
  generate differentiated concepts, build a beat-driven scene plan,
  then retrieve/generate/render the minimum required assets.

category: ecommerce-short-video

reference_input:
  supported: true
  analysis_depth: deep

stages:
  - name: reference_analysis
    skill: meta/reference-video-analyst
    produces:
      - reference_analysis
    tools:
      - video_analyzer
      - scene_detect
      - frame_sampler
      - transcript_fetcher
    checkpoint_required: false

  - name: reference_critique
    skill: meta/reference-critic
    requires:
      - reference_analysis
      - product_facts
    produces:
      - reference_critique
    checkpoint_required: false

  - name: proposal
    skill: pipelines/reference-commerce/proposal-director
    requires:
      - reference_analysis
      - reference_critique
      - product_facts
    optional:
      - gold_examples
      - taste_profile
    produces:
      - proposal_packet
    human_approval_default: true

  - name: script
    skill: pipelines/reference-commerce/script-director
    requires:
      - proposal_packet
      - product_facts
    produces:
      - beat_script
    human_approval_default: false

  - name: scene_plan
    skill: pipelines/reference-commerce/scene-director
    requires:
      - beat_script
      - proposal_packet
      - reference_analysis
    produces:
      - scene_plan
    human_approval_default: true

  - name: assets
    skill: pipelines/reference-commerce/asset-director
    requires:
      - scene_plan
      - product_assets
    produces:
      - asset_manifest
    checkpoint_required: false

  - name: compose
    skill: pipelines/reference-commerce/compose-director
    requires:
      - scene_plan
      - asset_manifest
    produces:
      - final_video
      - render_report

  - name: review
    skill: pipelines/reference-commerce/final-reviewer
    requires:
      - final_video
      - scene_plan
      - product_facts
    produces:
      - creative_review
      - repair_plan
```

## 5.1 MVP 不做通用 Orchestrator

如果当前系统已经有 workflow runner：直接复用。

如果没有，只需要：

```python
for stage in manifest.stages:
    load_required_artifacts(stage)
    load_skill(stage.skill)
    output = agent.execute(stage_context)
    validate(output, stage.output_schema)
    save_artifact(output)
    if stage.human_approval_default:
        pause_or_return_for_approval()
```

不要在第一版引入：

- DAG engine；
- LangGraph 大规模重构；
- Temporal；
- 全 OpenMontage checkpoint runtime。

**先把 Artifact Contract 跑通。**

---

# 6. Artifact 1：`reference_analysis.json`

这是最关键的上游事实层。

OpenMontage 的 reference analyst 强调 5 个方面：

1. Subject
2. Subject Motion
3. Scene
4. Spatial Framing
5. Camera

对于电商视频，需要额外增加：

6. Commerce Function
7. Caption / Overlay
8. Transition
9. Proof Type
10. Motion Type

推荐 Schema：

```json
{
  "version": "1.0",
  "source": {
    "uri": "...",
    "duration_seconds": 18.4,
    "fps": 30,
    "aspect_ratio": "9:16"
  },
  "summary": {
    "content": "...",
    "style": "...",
    "structure": "...",
    "what_makes_it_work": [
      "proof starts immediately",
      "product remains visible",
      "short shot duration"
    ]
  },
  "global_patterns": {
    "hook_pattern": "demonstration_first",
    "pacing": "fast",
    "story_shape": "feature_montage",
    "caption_style": "plain_functional",
    "transition_style": "mostly_hard_cut",
    "product_role": "proof_object"
  },
  "shots": [
    {
      "shot_id": "s01",
      "start_seconds": 0.0,
      "end_seconds": 1.8,
      "subject": {
        "description": "transparent table mat on wooden table"
      },
      "subject_motion": {
        "description": "hand pushes the mat laterally to demonstrate grip"
      },
      "scene": {
        "setting": "home dining table",
        "pov": "top-down close product demo",
        "overlays": [
          {
            "text": "防滑",
            "style_observation": "white bold text with dark outline"
          }
        ]
      },
      "spatial_framing": {
        "shot_size": "close_up",
        "subject_position": "center",
        "depth": "flat product plane"
      },
      "camera": {
        "movement": "static",
        "angle": "overhead",
        "steadiness": "locked"
      },
      "motion_type": "motion_clip",
      "commerce_function": "proof",
      "proof_type": "physical_demo",
      "selling_point": "anti_slip",
      "transition_in": "hard_cut",
      "transition_out": "hard_cut",
      "quality_notes": []
    }
  ]
}
```

## 6.1 必须与现有 fingerprint 解耦

现有：

```text
caption_style_fingerprint
transition fingerprint
shot fingerprint
```

不要删除，但它们从“生成指令”降级为：

```text
Observation / Evidence
```

也就是：

```text
Reference Analysis tells us what EXISTS.
Creative Director decides what SHOULD BE USED.
```

---

# 7. Artifact 2：`reference_critique.json`

这是 OpenMontage 思路在当前系统里最重要的增强层。

OpenMontage 明确要求：

- 说明参考片为什么有效；
- 保留哪些结构/节奏/语气；
- 输出 2–3 个 differentiated concepts；
- 不允许 carbon copy。

但是为了避免当前系统再次“忠实复制平庸”，建议显式增加 Critique IR。

```json
{
  "version": "1.0",
  "reference_ceiling": {
    "overall": "medium",
    "reason": "Clear proof but weak creative arc and generic packaging"
  },
  "keep": [
    {
      "pattern": "immediate_product_proof",
      "reason": "Low comprehension cost and directly supports conversion"
    },
    {
      "pattern": "short_shot_duration",
      "reason": "Matches short-form attention window"
    }
  ],
  "improve": [
    {
      "pattern": "caption_system",
      "current": "plain white outlined labels",
      "target": "role-driven kinetic caption recipes"
    },
    {
      "pattern": "transition_system",
      "current": "hard cut everywhere",
      "target": "action-matched and emphasis-driven transitions"
    }
  ],
  "replace": [
    {
      "pattern": "feature_list_story",
      "reason": "No escalation or payoff",
      "replacement": "problem → escalation → proof → relief"
    },
    {
      "pattern": "functional_hook",
      "reason": "Clear but not curiosity-generating",
      "replacement": "pain-shock or visual-risk hook"
    }
  ],
  "do_not_copy": [
    "exact shot order",
    "exact captions",
    "exact hook wording"
  ],
  "upgrade_priorities": [
    "hook",
    "story_arc",
    "caption_language",
    "transition_rhythm"
  ]
}
```

## 7.1 Critic Skill 的硬规则

文件：`skills/meta/reference-critic.md`

必须写进以下规则：

```text
You are not a replication planner.
The reference is evidence, not a prescription.

For every major observed pattern classify it as exactly one of:
KEEP / IMPROVE / REPLACE / DO_NOT_COPY.

KEEP only when the pattern serves:
- comprehension,
- product truth,
- conversion,
- pacing,
- visual memorability.

Do not preserve a pattern merely because it exists in the reference.
```

---

# 8. Artifact 3：`proposal_packet.json`

不要让 `script-director` 直接从 critique 生成唯一脚本。

先生成 **3 个 Creative Concept**。

推荐结构：

```json
{
  "version": "1.0",
  "concept_options": [
    {
      "id": "c1",
      "title": "最怕这一泼",
      "hook": "刚收拾好的桌子，最怕的不是划痕。",
      "hook_pattern": "pain_shock",
      "narrative_structure": "problem_solution",
      "story_shape": "hook_escalation_reveal_landing",
      "core_message": "透明桌垫真正保护的是日常失误",
      "product_role": "problem_solver",
      "visual_approach": "家庭事故感 + 微距 proof",
      "reference_inheritance": [
        "fast proof",
        "short shots"
      ],
      "creative_upgrades": [
        "stronger tension",
        "action-match transitions",
        "kinetic proof captions"
      ],
      "why_this_works": "把防油卖点从功能描述变成风险解除"
    },
    {
      "id": "c2",
      "title": "桌子的隐形盔甲",
      "hook": "看不见，才是这张桌垫最值钱的地方。",
      "hook_pattern": "contrarian",
      "narrative_structure": "reveal",
      "story_shape": "mystery_proof_payoff",
      "core_message": "保护但不破坏桌面颜值",
      "product_role": "invisible_protection"
    },
    {
      "id": "c3",
      "title": "一天四次事故",
      "hook": "早餐、作业、晚饭、夜宵——桌子每天都在挨打。",
      "hook_pattern": "specific_scenario",
      "narrative_structure": "journey",
      "story_shape": "day_in_life",
      "core_message": "一张桌垫覆盖全天风险",
      "product_role": "daily_protector"
    }
  ],
  "selected_concept": {
    "concept_id": "c1",
    "rationale": "strongest visual hook and easiest to render with existing product assets"
  },
  "taste_profile": {
    "design_read": "High-conversion home product demo: tactile, immediate, clean, slightly dramatic.",
    "visual_variance": 5,
    "motion_intensity": 7,
    "information_density": 4,
    "palette_discipline": "Keep real product and table tones; accent only on risk/proof words.",
    "anti_patterns": [
      "generic white text on every shot",
      "hard cut on every boundary",
      "one-selling-point-per-shot listicle"
    ],
    "quality_gates": [
      "first 2 seconds create risk or curiosity",
      "every proof shot resolves a prior viewer question",
      "captions emphasize meaning, not restate narration"
    ]
  }
}
```

---

# 9. Taste Profile：把“好看”变成可传递的创作标准

OpenMontage 的 Taste Direction 特别值得保留。

第一版保留 3 个 dial：

```text
visual_variance      1–10
motion_intensity     1–10
information_density  1–10
```

电商扩展 4 个：

```text
hook_intensity       1–10
proof_density        1–10
brand_restraint      1–10
caption_energy       1–10
```

最终：

```json
{
  "design_read": "...",
  "visual_variance": 5,
  "motion_intensity": 7,
  "information_density": 4,
  "hook_intensity": 8,
  "proof_density": 8,
  "brand_restraint": 7,
  "caption_energy": 7,
  "palette_discipline": "...",
  "anti_patterns": [],
  "quality_gates": []
}
```

## 9.1 为什么必须在 Scene Plan 之前有 Taste Profile

没有 Taste Profile 时：

```text
Scene Director
→ 为每个镜头独立做“看起来不错”的决定
→ 结果风格漂移 / 局部过度设计
```

有 Taste Profile：

```text
Taste Profile
→ scene layout
→ camera energy
→ transition vocabulary
→ caption energy
→ hold time
→ composition style
```

---

# 10. Artifact 4：`beat_script.json`

OpenMontage cinematic script director 使用：

```text
hook → escalation → reveal → landing
```

电商版建议扩展成 Beat Graph，而不是固定要求每次 4 段。

允许节点：

```text
HOOK
PROBLEM
ESCALATION
QUESTION
PRODUCT_ENTRANCE
MECHANISM
PROOF
COMPARISON
PAYOFF
TRUST
CTA
```

## 10.1 推荐 Schema

```json
{
  "version": "1.0",
  "title": "最怕这一泼",
  "target_duration_seconds": 18,
  "story_thesis": "真正的桌面保护应该在事故发生时存在，但平时看不见。",
  "beats": [
    {
      "id": "b01",
      "role": "HOOK",
      "start_seconds": 0,
      "end_seconds": 2.0,
      "viewer_question": "桌子会不会被毁？",
      "text": "最怕这一泼。",
      "visual_event": "dark sauce tips toward clean wooden table",
      "product_visibility": "partial",
      "selling_point": null
    },
    {
      "id": "b02",
      "role": "ESCALATION",
      "start_seconds": 2.0,
      "end_seconds": 4.0,
      "viewer_question": "已经来不及了吗？",
      "visual_event": "sauce lands and spreads",
      "product_visibility": "visible but not explained"
    },
    {
      "id": "b03",
      "role": "REVEAL",
      "start_seconds": 4.0,
      "end_seconds": 7.0,
      "viewer_question": "为什么桌面没事？",
      "visual_event": "edge catches light and reveals transparent mat",
      "selling_point": "water_oil_resistance"
    },
    {
      "id": "b04",
      "role": "PROOF",
      "start_seconds": 7.0,
      "end_seconds": 11.0,
      "visual_event": "single wipe removes sauce",
      "selling_point": "easy_clean"
    },
    {
      "id": "b05",
      "role": "PAYOFF",
      "start_seconds": 11.0,
      "end_seconds": 15.0,
      "visual_event": "table grain remains clearly visible",
      "selling_point": "transparent"
    },
    {
      "id": "b06",
      "role": "CTA",
      "start_seconds": 15.0,
      "end_seconds": 18.0,
      "text": "保护桌面，不挡颜值。"
    }
  ]
}
```

## 10.2 Script Director 的硬约束

必须明确禁止：

```text
卖点 A → 卖点 B → 卖点 C → CTA
```

除非选中的 narrative_structure 明确就是：

```text
rapid_proof_montage
```

否则每个卖点必须回答：

```text
Why does the viewer care here?
What changed from the previous beat?
What question does this beat open or close?
```

---

# 11. Artifact 5：`scene_plan.json`

OpenMontage 的 Scene Plan 已经包含三个非常重要的字段：

- `shot_intent`
- `narrative_role`
- `information_role`

当前系统应该直接吸收这个思想。

## 11.1 电商版 SceneSpec

```json
{
  "id": "s03",
  "beat_id": "b03",
  "start_seconds": 4.0,
  "end_seconds": 7.0,

  "narrative_role": "reveal",
  "selling_role": "proof",
  "shot_intent": "Reveal the invisible protection only after the viewer expects table damage.",
  "information_role": "Viewer realizes the liquid never touched the wooden surface.",

  "subject": {
    "primary": "transparent table mat",
    "secondary": "dark sauce"
  },
  "subject_motion": {
    "sequence": [
      "sauce settles",
      "hand catches mat edge",
      "edge flex reveals material"
    ]
  },
  "scene": {
    "setting": "wood dining table",
    "overlays": []
  },
  "spatial_framing": {
    "shot_size": "extreme_close_up",
    "subject_position": "lower center",
    "depth": "surface + edge separation"
  },
  "camera": {
    "movement": "dolly_in",
    "angle": "low_macro",
    "steadiness": "gimbal"
  },

  "asset_strategy": {
    "mode": "retrieve_or_generate",
    "preferred": "existing_product_asset",
    "generation_required_if": "no macro edge reveal footage exists"
  },

  "caption_intent": {
    "role": "reveal",
    "message": "原来有一层",
    "recipe_id": "reveal-pop-soft",
    "energy": 0.65
  },

  "transition_in": {
    "intent": "hold tension then reveal",
    "recipe_id": "micro-punch-in"
  },
  "transition_out": {
    "intent": "match hand wipe direction",
    "recipe_id": "action-match-horizontal"
  },

  "hero_moment": true,
  "product_truth_constraints": [
    "mat must remain transparent",
    "wood grain visible below",
    "material thickness must match product facts"
  ]
}
```

---

# 12. Scene Director 必须使用“5 Aspect + Commerce Intent”

OpenMontage 的 5 Aspect 可以直接转为 Scene Planner 的结构化检查：

```text
1. Subject
2. Subject Motion
3. Scene
4. Spatial Framing
5. Camera
```

电商额外检查：

```text
6. Narrative Role
7. Selling Role
8. Product Role
9. Caption Intent
10. Transition Intent
11. Asset Strategy
12. Product Truth Constraints
```

## 12.1 所有 Hero Moment 必须填写完整

Hero Moment 包括：

- Hook frame；
- Reveal frame；
- strongest proof；
- payoff / final product frame。

Hero Moment 不允许：

```text
camera: cinematic
framing: close up
```

这种模糊描述。

必须明确：

- shot size；
- angle；
- movement；
- subject position；
- depth；
- action；
- overlay；
- product constraints。

---

# 13. Caption：不要继续扩大 fingerprint，改成 Recipe Router

当前问题：

```text
caption_style_fingerprint
  → font size
  → color
  → outline
```

这种方式只适合视觉复制，不适合创意表达。

第一版应改成：

```text
Caption Intent
  ↓
Caption Recipe Router
  ↓
Remotion Component
```

## 13.1 Caption Intent

```json
{
  "role": "pain|proof|reveal|comparison|cta",
  "message": "一擦就净",
  "emphasis_tokens": ["一擦"],
  "energy": 0.8,
  "recipe_id": "proof-punch",
  "placement": "upper-middle",
  "max_duration_seconds": 1.4
}
```

## 13.2 第一批 Caption Recipe 只做 10 个

```text
pain-shake
proof-punch
reveal-pop-soft
keyword-highlight
number-counter
before-after-split
marker-underline
sticker-burst
clean-minimal-label
cta-lockup
```

每个 Recipe 由 Remotion 确定：

- font；
- layout；
- spring；
- stagger；
- stroke；
- keyword color；
- entrance；
- exit。

不要让 VLM 直接输出 Remotion CSS 参数。

---

# 14. Transition：从“效果列表”升级成“语义 Recipe”

不要让 Scene Director 直接选：

```text
fade / wipe / zoom / slide
```

让它先输出**为什么需要转场**：

```json
{
  "intent": "increase tension",
  "recipe_id": "impact-cut"
}
```

第一批 Transition Recipe：

```text
hard-cut-clean
impact-cut
action-match-horizontal
action-match-vertical
flash-proof
micro-punch-in
soft-dissolve
speed-ramp-cut
texture-wipe
hold-and-drop
```

规则：

- 每条片最多 3 个 transition family；
- Hook/Proof 可以更强；
- 普通信息镜头默认 clean cut；
- 不为“看起来高级”而加转场；
- transition 必须服务 rhythm / meaning / direction continuity。

---

# 15. Product Truth：必须比 OpenMontage 更严格

电商系统与通用视频系统最大的不同是：

> **商品不能被创意模型自由改造。**

新增 `ProductBible`：

```json
{
  "product_id": "tablemat_001",
  "facts": {
    "material": "TPU",
    "thickness_mm": 1.5,
    "transparency": "high",
    "shape": "rectangular rounded corner"
  },
  "visual_identity": {
    "must_preserve": [
      "transparent appearance",
      "correct edge shape",
      "correct thickness"
    ],
    "allowed_variation": [
      "table environment",
      "lighting",
      "camera angle"
    ],
    "forbidden": [
      "opaque material",
      "invented printed pattern",
      "wrong thickness",
      "extra product features"
    ]
  },
  "claims": [
    {
      "id": "oilproof",
      "status": "verified",
      "evidence": "product spec / real footage"
    }
  ]
}
```

所有 Script / Scene / Generation Prompt / Judge 必须引用 ProductBible。

---

# 16. Asset Director：优先 Retrieve / Reuse，再 Generate

这一步要结合已有商品素材资产。

Scene Plan 每个镜头都输出：

```text
asset_strategy.mode
```

枚举：

```text
reuse_exact
retrieve
reframe
edit_existing
generate_image
generate_video
hybrid
```

路由顺序：

```text
Can existing asset satisfy shot intent?
  ↓ yes
reuse/reframe
  ↓ no
Can existing asset be edited cheaply?
  ↓ yes
edit_existing
  ↓ no
Generate
```

目标：

> **只为新的“视觉事实”付生成成本。**

字幕、转场、节奏、轻动画、构图包装交给 Remotion；不要浪费 Seedance/Kling 去生成本可确定性完成的工作。

---

# 17. Tool Registry：MVP 只做能力路由，不做 OpenMontage 全量生态

建议统一 Tool Contract：

```typescript
interface VideoTool {
  name: string;
  capability: string;
  provider: string;
  supports: string[];
  costModel?: CostModel;
  available(): Promise<boolean>;
  execute(input: unknown): Promise<ToolResult>;
}
```

第一批注册：

```text
video_analyzer
scene_detect
frame_sampler
transcript_fetcher
asset_retriever
image_generator
video_generator
remotion_compose
video_judge
```

第二阶段才做：

```text
provider_selector
cost ranking
fallback graph
```

---

# 18. Skill 设计：创意逻辑不要写进代码

## 18.1 `reference-video-analyst.md`

职责：只描述事实，不下创意结论。

硬规则：

```text
- Separate observation from recommendation.
- Use the 5-aspect structure for every meaningful shot.
- Explicitly classify motion_type.
- Extract caption/overlay separately from scene depth.
- Extract transition patterns.
- Extract commerce function and proof type.
- Mark unknown as UNKNOWN, never infer product facts.
```

输出：`reference_analysis.json`

---

## 18.2 `reference-critic.md`

职责：判断学什么、不学什么。

硬规则：

```text
Reference is evidence, not creative authority.

For each major pattern:
KEEP / IMPROVE / REPLACE / DO_NOT_COPY.

Never preserve a pattern because it is present.
Preserve only if it improves comprehension, conversion,
memorability, product truth, rhythm, or production efficiency.
```

输出：`reference_critique.json`

---

## 18.3 `proposal-director.md`

职责：生成 3 个真正不同的 Creative Concept。

硬规则：

```text
Generate exactly 3 concepts.
They must differ in at least 2 of:
- hook pattern
- story shape
- product role
- visual treatment
- emotional arc

One concept may stay closest to the reference.
At least one must challenge the reference's story structure.
At least one must introduce a fresh hook.
```

并要求显式：

```text
what_from_reference_is_kept
what_is_upgraded
what_is_new
renderability_risks
```

---

## 18.4 `script-director.md`

职责：Concept → Beat Script。

硬规则：

```text
Build beats before lines.
Every beat must change:
- viewer knowledge,
- viewer emotion,
- product understanding,
OR story state.

Avoid feature-list progression unless selected concept explicitly requires montage.
```

---

## 18.5 `scene-director.md`

职责：Beat → Scene / Shot Intent。

硬规则：

```text
Every scene must explain WHY the shot exists.
Every hero moment must fully specify all five visual aspects.
Caption and overlays are separate layers.
Transition is semantic intent first, effect recipe second.
Every scene must declare its asset strategy.
Every generated scene must carry product truth constraints.
```

---

# 19. AI Coding 实施顺序

不要一次性做完整系统，按下面 patch 顺序实施。

## Phase 0 — Baseline Freeze

目标：让后续优化可比较。

新增：

```text
tests/golden/batch-002/
  reference.mp4
  current-output.mp4
  current-script.json
  current-scene-plan.json
  baseline-review.json
```

记录 baseline：

```json
{
  "hook_strength": 4.5,
  "story_arc": 3.0,
  "caption_quality": 4.0,
  "transition_quality": 3.0,
  "product_truth": 9.5,
  "render_stability": 9.0
}
```

> 数字以真实 Judge/人工打分为准，上面仅为结构示例。

---

## Phase 1 — Reference Analysis + Critique

新增：

```text
reference-analysis.schema.json
reference-critique.schema.json
reference-video-analyst.md
reference-critic.md
```

改造入口：

```text
reference_fingerprint()
```

变为：

```text
analyze_reference()
critique_reference()
```

保留旧 fingerprint 作为 compatibility adapter：

```text
reference_analysis → legacy_fingerprint_adapter
```

### 验收

同一参考视频必须输出：

- `what_makes_it_work`；
- `keep[]`；
- `improve[]`；
- `replace[]`；
- `do_not_copy[]`；
- 至少一项明确指出“参考片本身的创意天花板”。

---

## Phase 2 — Creative Proposal + Taste Profile

新增：

```text
proposal-packet.schema.json
proposal-director.md
taste-direction.md
```

原：

```text
reference → script
```

改：

```text
reference
→ critique
→ concepts × 3
→ selected concept
→ taste profile
→ script
```

### 验收

3 个 Concept 不允许只改文案。

程序化检查：

```text
unique(hook_pattern) >= 2
unique(story_shape) >= 2
unique(product_role) >= 2 OR unique(visual_approach) >= 2
```

---

## Phase 3 — Beat Script + Enhanced Scene Plan

新增：

```text
beat-script.schema.json
scene-plan.schema.json
script-director.md
scene-director.md
```

迁移原字段：

```text
scene.description
scene.transition_in
scene.transition_out
```

扩展为：

```text
narrative_role
selling_role
shot_intent
information_role
5-aspect visual fields
caption_intent
transition intent / recipe
asset_strategy
product_truth_constraints
```

### 验收

每个 Scene：

```text
shot_intent != empty
narrative_role != empty
asset_strategy != empty
```

Hero Moment：

```text
5-aspect completion = 100%
```

---

## Phase 4 — Caption / Transition Recipe Adapter

不要先做复杂 UI。

建立：

```text
render/recipes/caption/*.tsx
render/recipes/transition/*.tsx
```

统一接口：

```typescript
resolveCaptionRecipe(scene.caption_intent.recipe_id)
resolveTransitionRecipe(scene.transition_in.recipe_id)
```

第一批各 8–10 个即可。

### 验收

- 同一条视频不再全部白字描边；
- 转场不再由单个 `transition` 字符串直接控制底层实现；
- Recipe 可独立替换并局部重渲染。

---

## Phase 5 — Creative Judge + Repair Plan

新增评测：

```text
hook_strength
concept_originality
story_arc
selling_clarity
proof_clarity
caption_quality
transition_quality
brand_fit
product_truth
renderability
```

建议总分：

```text
CreativeScore =
  0.18 * hook_strength
+ 0.14 * concept_originality
+ 0.14 * story_arc
+ 0.12 * selling_clarity
+ 0.10 * proof_clarity
+ 0.08 * caption_quality
+ 0.06 * transition_quality
+ 0.06 * brand_fit
+ 0.06 * product_truth
+ 0.06 * renderability
```

其中硬门槛：

```text
product_truth >= 8.5/10
renderability >= 7.5/10
```

不要允许靠“更炫”换来商品失真。

---

# 20. Repair Plan：让 Editorial Gallery 真正成为最后一公里

Judge 不直接输出：

```text
bad / good
```

输出：

```json
{
  "overall_pass": false,
  "issues": [
    {
      "scope": "scene",
      "scene_id": "s01",
      "dimension": "hook_strength",
      "severity": "high",
      "diagnosis": "opening is clear but low tension",
      "repair_action": "regenerate_hook_scene",
      "upstream_stage": "script",
      "rerun_scope": ["b01", "s01"]
    },
    {
      "scope": "scene",
      "scene_id": "s04",
      "dimension": "caption_quality",
      "severity": "medium",
      "repair_action": "swap_caption_recipe",
      "upstream_stage": "compose",
      "rerun_scope": ["s04"]
    }
  ]
}
```

这样 EG 的职责非常清晰：

```text
换镜头
换素材
调字幕 recipe
调某个 transition
裁切
时长
局部重跑
```

而下面这些不得在 EG 临时解决：

```text
story arc
hook concept
reference critique
product role
creative standard
```

---

# 21. Checkpoint：只保留 2 个 Human Gate

OpenMontage 很重视 human approval，但电商批量生产不能每层都等人。

MVP 只保留：

## Gate A：Creative Proposal

人工看：

- 3 个 Concept；
- Taste Profile；
- 预计成本；
- 主要风险。

选中一个。

## Gate B：Scene Plan / Storyboard

人工看：

- Hook；
- Beat Map；
- Hero Frames；
- 商品真实性；
- 生成成本大的 Shot。

通过后批量生产。

其余阶段自动。

后续有 Gold Set + Judge 后，可将 Gate A/B 转为高分自动通过、低分人工审批。

---

# 22. Decision Log：建议保留，但做轻量版

```json
{
  "decisions": [
    {
      "category": "creative_concept",
      "subject": "selected concept",
      "selected": "c1",
      "options_considered": ["c1", "c2", "c3"],
      "reason": "highest hook + easiest product truth preservation"
    },
    {
      "category": "asset_strategy",
      "subject": "s03 macro reveal",
      "selected": "generate_video",
      "options_considered": ["retrieve", "edit_existing", "generate_video"],
      "reason": "no existing macro edge reveal asset"
    }
  ]
}
```

主要用来回答：

```text
为什么这个镜头要生成？
为什么没复用素材？
为什么 Hook 改了？
为什么用了这个 transition？
```

这会成为未来 Autoresearch / 复盘的重要数据。

---

# 23. Project Workspace：让每次生产都可回放

建议：

```text
projects/<run-id>/
├── input/
│   ├── reference.mp4
│   ├── product_facts.json
│   └── product_assets.json
│
├── artifacts/
│   ├── 01-reference-analysis.json
│   ├── 02-reference-critique.json
│   ├── 03-proposal-packet.json
│   ├── 04-beat-script.json
│   ├── 05-scene-plan.json
│   ├── 06-asset-manifest.json
│   ├── 07-render-report.json
│   ├── 08-creative-review.json
│   └── 09-repair-plan.json
│
├── assets/
│   ├── source/
│   ├── retrieved/
│   ├── generated/
│   ├── audio/
│   └── captions/
│
├── previews/
└── renders/
    └── final.mp4
```

任何 Stage 都不得只把结果留在 LLM 上下文。

---

# 24. Schema Validation 是硬要求

每个 Artifact 都必须：

```text
LLM structured output
  ↓
JSON schema validate
  ↓ fail
repair JSON only
  ↓
validate again
  ↓
save artifact
```

禁止：

```text
LLM 输出 Markdown
→ 下一个 Agent 靠自然语言重新理解
```

创意可以自由，**接口必须严格**。

---

# 25. 最小 Orchestration Pseudocode

```python
def run_reference_commerce(ctx):
    a = run_stage(
        "reference_analysis",
        skill="meta/reference-video-analyst.md",
        inputs=[ctx.reference_video],
        schema="reference-analysis.schema.json",
    )

    c = run_stage(
        "reference_critique",
        skill="meta/reference-critic.md",
        inputs=[a, ctx.product_facts],
        schema="reference-critique.schema.json",
    )

    p = run_stage(
        "proposal",
        skill="pipelines/reference-commerce/proposal-director.md",
        inputs=[a, c, ctx.product_facts, ctx.gold_examples],
        schema="proposal-packet.schema.json",
    )

    p = human_gate("creative_proposal", p)

    script = run_stage(
        "script",
        skill="pipelines/reference-commerce/script-director.md",
        inputs=[p, ctx.product_facts],
        schema="beat-script.schema.json",
    )

    scenes = run_stage(
        "scene_plan",
        skill="pipelines/reference-commerce/scene-director.md",
        inputs=[script, p, a, ctx.product_facts],
        schema="scene-plan.schema.json",
    )

    scenes = human_gate("storyboard", scenes)

    assets = materialize_assets(scenes, ctx.product_assets)
    video = compose(scenes, assets)

    review = judge(video, scenes, ctx.product_facts)

    if not review.overall_pass:
        apply_repair_plan(review.repair_plan)

    return final_video
```

---

# 26. Reference Video Analysis 的工具链

第一版足够：

```text
ffprobe
scene detect
keyframe sample
ASR/transcript
VLM frame analysis
optical flow / motion heuristic（已有则用）
```

输出要区分：

```text
motion_clip
animated_still
static_image
```

因为这个判断会影响：

```text
生成视频
vs
生成图片 + Remotion
vs
直接复用素材
```

不要靠 LLM 猜。

---

# 27. Reference → Creative 的核心 Prompt Contract

以下内容建议写入 `proposal-director.md`：

```text
You are the Creative Director for a conversion-oriented ecommerce video.

INPUTS:
- ProductFacts
- ReferenceAnalysis
- ReferenceCritique
- GoldExamples (optional)
- TasteProfile defaults

The reference is evidence, not authority.
Do not reproduce its exact shot order, captions, hook wording, or transition pattern.

Generate exactly 3 differentiated creative concepts.

For every concept:
1. State what it keeps from the reference.
2. State what it deliberately improves.
3. State the fresh angle.
4. Define the hook mechanism.
5. Define the story shape.
6. Define the product's narrative role.
7. Explain why this can be rendered with available assets/tools.
8. Identify product-truth risks.

Reject concepts that are merely:
- a new wording of the same feature list,
- the same story with different captions,
- decorative motion without a stronger idea.

Prefer concepts where the product solves, reveals, proves, prevents,
or transforms something inside a viewer-understandable situation.
```

---

# 28. Script Director Prompt Contract

```text
You convert the selected CreativeConcept into a BeatScript.

Do NOT begin by writing dialogue or captions.
Begin with viewer-state transitions.

For every beat specify:
- role,
- viewer_question,
- what changes,
- visible event,
- product role,
- selling point if any.

A valid beat changes at least one:
- knowledge,
- emotion,
- tension,
- product understanding,
- story state.

Use hook → escalation → reveal → landing as the default skeleton,
but adapt when the selected concept needs comparison, day-in-life,
myth-busting, rapid proof, or other structures.

Feature-list montage is forbidden unless explicitly selected as the concept structure.
```

---

# 29. Scene Director Prompt Contract

```text
You convert BeatScript into production-ready SceneSpecs.

For every scene:
- WHY does this shot exist? -> shot_intent
- What narrative job? -> narrative_role
- What selling job? -> selling_role
- What does the viewer learn/feel? -> information_role
- What visual event happens?
- Complete five visual aspects.
- Which product facts must remain true?
- Can we retrieve/reuse/edit an asset before generating?
- What caption intent is needed?
- What transition intent is needed?

Do not output generic cinematography adjectives.
"cinematic close-up" is invalid.

Hero moments require complete camera/framing/action details.
```

---

# 30. Judge：Creative 与 Technical 分开

不要只做一个总分。

## 30.1 Creative Judge

输入：

```text
reference critique
selected concept
beat script
scene plan
rendered video
```

评分：

```text
Hook Strength
Concept Originality
Story Arc
Scene Progression
Selling Clarity
Proof Clarity
Caption Semantics
Transition Semantics
Brand/Taste Fit
```

## 30.2 Technical / Video Judge

评分：

```text
Visual Quality
Temporal Consistency
Text Legibility
Audio Quality
Product Truth
Physical Plausibility
Generation Artifacts
```

最终不要把 VideoScore 类基础质量分直接当“创意好不好”。

---

# 31. Gold Set 对接

每个 Gold Example 不只存视频文件。

建议：

```text
gold/<id>/
├── video.mp4
├── reference-analysis.json
├── creative-tags.json
├── beat-map.json
├── hero-frames/
└── human-score.json
```

`creative-tags.json`：

```json
{
  "hook_pattern": "visual_risk",
  "story_shape": "problem_reveal_payoff",
  "caption_language": "kinetic_minimal",
  "transition_language": "action_match",
  "product_role": "problem_solver",
  "why_gold": [
    "hook understood without audio",
    "proof answers hook directly",
    "product remains visually truthful"
  ]
}
```

Proposal Director 检索的是 Pattern，不是复制某条成片。

---

# 32. 与 Autoresearch 的接口

后续优化对象：

```text
skills/meta/reference-critic.md
skills/meta/taste-direction.md
skills/pipelines/reference-commerce/proposal-director.md
skills/pipelines/reference-commerce/script-director.md
skills/pipelines/reference-commerce/scene-director.md
```

不要让 Autoresearch 一开始改 Render Engine。

实验 Loop：

```text
Skill vN
  ↓
Gold Tasks
  ↓
Generate artifacts / previews
  ↓
Judge
  ↓
Aggregate metric
  ↓
Keep / Discard
```

建议先优化：

```text
proposal-director
→ script-director
→ scene-director
```

再优化：

```text
caption recipes
transition recipes
```

---

# 33. Batch-002 的第一条 Regression Test

用当前“防滑耐磨防水防油透明桌垫”参考视频固定为回归用例。

测试目标：

```text
Input:
- reference video
- same product facts
- same product asset pool

Baseline:
- feature-list script
- functional hook
- hard cuts
- plain captions
```

新系统必须满足：

### Reference Critique

```text
replace includes feature-list story
replace/improve includes functional hook
improve includes caption system
improve includes transition rhythm
```

### Proposal

```text
concept_options == 3
unique hooks >= 2
unique story shapes >= 2
```

### Beat Script

至少包含：

```text
HOOK
+ one change/escalation/reveal
+ PROOF/PAYOFF
```

### Scene Plan

```text
all scenes have shot_intent
all hero scenes have complete 5-aspect fields
all scenes have asset_strategy
```

### Final Judge

目标不是绝对分，而是相对 baseline：

```text
hook_strength > baseline
story_arc > baseline
caption_quality > baseline
transition_quality > baseline
product_truth >= baseline - tolerance
renderability >= baseline - tolerance
```

建议 tolerance：`0.3 / 10`。

---

# 34. 单元测试 / Contract Test 清单

## Schema

```text
[ ] reference analysis validates
[ ] critique validates
[ ] 3 concepts minimum/maximum rules pass
[ ] scene hero moment requires full fields
[ ] unknown enum fails fast
```

## Creative Contracts

```text
[ ] reference observations cannot directly overwrite selected creative direction
[ ] critique has KEEP/IMPROVE/REPLACE/DO_NOT_COPY
[ ] 3 concepts are structurally different
[ ] feature list is rejected when concept != rapid_proof_montage
[ ] every scene has shot_intent
```

## Product Truth

```text
[ ] generated prompt contains must_preserve constraints
[ ] forbidden claim cannot enter script
[ ] forbidden visual variation triggers judge failure
```

## Render

```text
[ ] caption recipe ID exists
[ ] transition recipe ID exists
[ ] missing recipe falls back to safe minimal recipe, not crash
[ ] local scene rerender works
```

## Regression

```text
[ ] batch-002 baseline stored
[ ] new creative score does not regress
[ ] product truth does not regress
[ ] cost per candidate is tracked
```

---

# 35. 推荐的错误处理策略

## Structured Output Invalid

```text
retry JSON repair once
→ still invalid
→ fail stage
```

不要无上限 retry。

## Reference Analysis Incomplete

如果缺：

```text
motion_type
shot boundaries
keyframes
```

禁止直接进入 Proposal。

## Product Facts Missing

标记：

```text
UNKNOWN
```

禁止 Agent 自行补产品参数。

## Generation Fails

优先：

```text
same shot intent
→ alternative provider/model
```

不要 silently 改：

```text
shot intent / product role / story beat
```

---

# 36. Cost Governance

每个 Scene 记录：

```json
{
  "estimated_cost": 0.0,
  "actual_cost": 0.0,
  "generation_attempts": 0,
  "reuse_saved_cost": 0.0
}
```

核心指标：

```text
Cost per Accepted Shot
Cost per Accepted Video
Generation Attempts per Accepted Shot
Reuse Rate
Repair Rate
```

这比只看模型 API 成本更有经营意义。

---

# 37. 不要照搬 OpenMontage 的地方

## 37.1 不需要每个 Provider 都呈现给用户

OpenMontage 偏通用 Agent 产品，会要求对 Provider / Runtime 做大量显式选择。

企业视频工厂更适合：

```text
Policy + Router 自动选
→ 只有成本/质量差异过大时人工介入
```

## 37.2 不需要所有阶段 Human Gate

批量电商生产会被拖死。

只保留两个高价值 Gate。

## 37.3 不要把 Style Playbook 做得过重

第一版 Taste Profile + Recipe Library 足够。

## 37.4 不要把 Reference Analyst 当 Creative Director

这也是当前系统最需要避免的。

---

# 38. OpenMontage 参考文件 → 当前系统映射

| OpenMontage 文件/机制 | 借鉴内容 | 当前系统对应 |
|---|---|---|
| `AGENT_GUIDE.md` | Reference 一等入口、Pipeline-first、Director Skill、Checkpoint | Agent 生产协议 |
| `PROJECT_CONTEXT.md` | Instruction-driven 3 层架构、Artifact canonical | Harness / Skill 组织 |
| `skills/meta/video-reference-analyst.md` | 5-aspect、motion classification、differentiated concepts | Reference Analyzer |
| `skills/meta/taste-direction.md` | taste profile + 3 dials + anti-default | 创作标准 |
| `pipeline_defs/cinematic.yaml` | proposal/script/scene/assets/edit/compose staging | reference-commerce pipeline |
| `cinematic/script-director.md` | hook → escalation → reveal → landing | Beat Script |
| `cinematic/scene-director.md` | Hero Frame、5-aspect、transition vocabulary | Scene/Shot Director |
| `scene_plan.schema.json` | shot_intent / narrative_role / information_role | 新 SceneSpec |
| `proposal_packet.schema.json` | 3 concepts / selected concept / production plan | Creative Proposal |
| `script.schema.json` | timestamped canonical script artifact | BeatScript 的时间契约 |

---

# 39. OpenMontage 原始参考路径

仓库：

```text
https://github.com/calesthio/OpenMontage
```

重点阅读顺序：

```text
1. AGENT_GUIDE.md
2. PROJECT_CONTEXT.md
3. skills/meta/video-reference-analyst.md
4. skills/meta/taste-direction.md
5. pipeline_defs/cinematic.yaml
6. skills/pipelines/cinematic/script-director.md
7. skills/pipelines/cinematic/scene-director.md
8. schemas/artifacts/proposal_packet.schema.json
9. schemas/artifacts/script.schema.json
10. schemas/artifacts/scene_plan.schema.json
```

AI Coding 不需要第一轮阅读整个仓库。

---

# 40. 给 AI Coding Agent 的 Master Instruction

可把下面直接作为任务入口：

```text
TASK: Adapt our existing reference-driven ecommerce video pipeline using the architectural patterns of OpenMontage, without forking or copying the whole OpenMontage codebase.

BUSINESS GOAL:
Given a reference ecommerce video + verified product facts + product asset pool,
produce a short video that preserves useful evidence from the reference while deliberately improving weak creative patterns.

CORE PRINCIPLE:
Reference is evidence, not a prescription.
The system must be able to KEEP / IMPROVE / REPLACE / DO_NOT_COPY observed patterns.

DO NOT:
- replace the existing video system wholesale;
- rewrite the render engine;
- build a generic OpenMontage clone;
- add many providers;
- build Backlot;
- put creative orchestration into Python/TS business logic;
- let LLM stages communicate only through prose;
- infer unknown product facts.

IMPLEMENT IN THIS ORDER:

P0. Freeze batch-002 baseline and regression fixtures.

P1. Add canonical artifacts:
- ReferenceAnalysis
- ReferenceCritique

P2. Add Creative Proposal:
- exactly 3 differentiated concepts
- selected concept
- TasteProfile

P3. Replace feature-list script output with BeatScript.
Use beat roles such as HOOK / PROBLEM / ESCALATION / REVEAL / PROOF / PAYOFF / CTA.

P4. Upgrade ScenePlan:
- narrative_role
- selling_role
- shot_intent
- information_role
- 5 visual aspects
- asset_strategy
- caption_intent
- transition_intent
- product_truth_constraints

P5. Add CaptionRecipe and TransitionRecipe routing on top of the existing Remotion renderer.
Do not replace Remotion.

P6. Add CreativeReview + RepairPlan with local rerun scopes.
Editorial Gallery remains the last-mile local editor.

ARCHITECTURAL RULES:
1. Each stage has a Markdown Director Skill.
2. Each stage emits JSON validated by JSON Schema.
3. Code provides tools, persistence, validation, routing, rendering.
4. Skills provide creative reasoning and production decisions.
5. Every expensive generation decision must be traceable to ScenePlan.asset_strategy.
6. ProductBible is immutable truth and must flow into prompts and judges.
7. Preserve backwards compatibility through adapters where possible.

FIRST DELIVERABLE:
Produce a patch plan before coding with:
- files to add
- files to modify
- compatibility risks
- migration order
- tests to add

THEN IMPLEMENT P1-P3 FIRST.
Do not implement P4-P6 until P1-P3 tests pass.

ACCEPTANCE TEST:
Run the existing batch-002 transparent-table-mat case.
The new system must:
- identify the reference's flat feature-list structure as a weakness;
- identify plain captions and all-hard-cut rhythm as upgrade targets;
- produce 3 structurally different concepts;
- produce a beat-driven script;
- preserve verified product facts;
- not increase downstream render failures.
```

---

# 41. 建议 AI Coding 第一次提交的文件清单

第一轮只做 P1–P3：

```text
ADD
pipeline_defs/reference-commerce.yaml
skills/meta/reference-video-analyst.md
skills/meta/reference-critic.md
skills/meta/taste-direction.md
skills/pipelines/reference-commerce/proposal-director.md
skills/pipelines/reference-commerce/script-director.md
schemas/artifacts/reference-analysis.schema.json
schemas/artifacts/reference-critique.schema.json
schemas/artifacts/proposal-packet.schema.json
schemas/artifacts/beat-script.schema.json

tests/golden/batch-002/*
tests/contracts/test_reference_analysis.*
tests/contracts/test_reference_critique.*
tests/contracts/test_proposal_diversity.*
tests/contracts/test_beat_script.*

MODIFY
reference pipeline entry/router
legacy reference fingerprint adapter
script-director entry
artifact persistence/index
schema registry
```

第一轮明确不改：

```text
Remotion renderer
Editorial Gallery
video generation provider adapters
existing caption components
existing transition components
```

这样风险最低。

---

# 42. Definition of Done：P1–P3

完成标准不是“代码能跑”。

必须同时满足：

```text
[ ] ReferenceAnalysis 成为 canonical artifact
[ ] ReferenceCritique 显式 KEEP/IMPROVE/REPLACE/DO_NOT_COPY
[ ] 旧 reference fingerprint 仍能通过 adapter 使用
[ ] Proposal 每次输出 3 个结构不同 concept
[ ] Taste Profile 可以被后续 Scene Director 读取
[ ] BeatScript 不再默认 feature list
[ ] Product facts 无法被 Prompt 覆盖
[ ] batch-002 regression 测试通过
[ ] Artifact 全部 schema-valid
[ ] 每个 artifact 可持久化并回放
```

---

# 43. Definition of Done：完整 MVP

```text
REFERENCE
✓ 自动 scene / frame / transcript analysis
✓ 5-aspect + commerce annotation
✓ motion type

CRITIQUE
✓ KEEP / IMPROVE / REPLACE / DO_NOT_COPY
✓ reference ceiling

CREATIVE
✓ 3 concepts
✓ hook pattern
✓ story shape
✓ taste profile

SCRIPT
✓ beat map
✓ viewer-state change
✓ proof/payoff relation

SCENE
✓ shot intent
✓ narrative/selling role
✓ 5 aspects
✓ asset strategy
✓ caption/transition intent
✓ product truth

PRODUCTION
✓ retrieve-first
✓ generate-only-when-needed
✓ Remotion recipe routing

EVAL
✓ creative judge
✓ technical judge
✓ product truth gate
✓ local repair plan

EDITORIAL GALLERY
✓ last-mile only
✓ scene-level rerun
```

---

# 44. 最后的架构判断

对当前系统，OpenMontage 最有价值的不是“帮忙生成视频”，而是提供了一个很清晰的工程原则：

```text
Creative Intelligence lives in Skills.
Production Capabilities live in Tools.
State lives in Artifacts.
Workflow lives in Manifests.
Quality lives in Gates and Reviews.
```

把它映射到电商视频之后：

```text
Reference Analyst
    负责看懂参考

Reference Critic
    负责判断哪些值得学

Creative Director
    负责超越参考

Script Director
    负责把卖点变成 Beat

Scene Director
    负责把 Beat 变成可执行 Shot Intent

Asset Router
    负责复用 / 编辑 / 生成

Remotion
    负责确定性的字幕、转场、合成

Judge
    负责判断是否真的更好

Editorial Gallery
    只负责最后一公里
```

这比继续在原来的 `reference fingerprint → direct replication` 管线里补更多参数更重要。

**最优先实施：ReferenceAnalysis → ReferenceCritique → CreativeProposal → BeatScript。**

只要这四个对象形成稳定 Contract，后面的 Caption Recipe、Transition Recipe、Shot Generation、Video Judge、Autoresearch 都可以逐步接入，而不需要再次推翻架构。

---

## Appendix A：当前问题 → 目标字段对照

| 当前问题 | 不要继续加什么 | 应增加什么 |
|---|---|---|
| 花字不匹配 | 更多 font/color fingerprint | `caption_intent + caption_recipe_id` |
| 硬切 | 更多 transition 枚举 | `transition_intent + recipe_id` |
| 无故事 | 更长 script prompt | `creative concept + beat_script` |
| Hook 弱 | 单个 hook prompt | `hook_pattern + 3 concepts + judge` |
| 参考平庸 | 更高复刻精度 | `reference_critique` |
| 成本高 | 更便宜模型 | `asset_strategy: reuse/retrieve/edit/generate` |
| 一致性 | prompt 加“保持一致” | `ProductBible + truth constraints` |
| EG 承担过多 | 增加全局编辑能力 | `RepairPlan + upstream rerun_scope` |

---

## Appendix B：MVP 最关键的 8 个对象

```text
1. ProductBible
2. ReferenceAnalysis
3. ReferenceCritique
4. CreativeProposal
5. TasteProfile
6. BeatScript
7. ScenePlan
8. CreativeReview / RepairPlan
```

只要 AI Coding 围绕这 8 个对象建立稳定数据契约，整个系统就会从“Prompt 串联”升级成真正可评测、可局部重跑、可持续优化的视频生产 Harness。

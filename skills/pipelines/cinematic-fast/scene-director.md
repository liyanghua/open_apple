# Scene Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/scene-director.md` and
`skills/meta/fastline.md` before acting. Map every beat to source footage with
half-open in/out frames, safe caption zones, crop and speed decisions. Keep
the scene plan deterministic and do not create an independent approval stop;
the `creative_lock` bundle covers it at `assets`.

Before mapping shots, require the canonical `script` artifact to have
`status: approved`. Use each section's goal, pacing, visual intent, evidence
requirements, and control-rule references as constraints. A draft or partially
reviewed script is not permission to enter Scene Plan.

Every source mapping must be stored in `metadata.source_mapping[]`, keyed to the
canonical scene and owned source interval. Each mapped scene must also have a
non-empty canonical `scenes[].shot_intent`. Record every mapping in this shape:

```yaml
scene_id: "scene identifier"
reference_evidence:
  mode: "direct_segment | structural_only | none"
  reference_scene_id: "reference-1"  # direct_segment only
  reference_interval:                # direct_segment only
    start_seconds: 0
    end_seconds_exclusive: 2
  mechanism: "reference mechanism used by this shot"
  rationale: "why that mechanism serves the shot intent"
source_path: "path under the project's owned source set"
source_interval: {start_seconds: 0, end_seconds_exclusive: 2}
timeline_interval: {start_seconds: 0, end_seconds_exclusive: 2}
reference_basis: "reference pattern or structural observation"
source_fit: "why this owned source interval fits the beat"
mapping_reason: "how the source fit serves the shot intent"
originality_note: "how the treatment remains original"
matrix_row_id: "resolved research matrix row"
matrix_resolution_id: "resolution used for this shot"
research_direction_ref: "selected differentiation direction"
```

Accept a mapping only when all four fields explain the reference understanding,
the fit of the project's own source footage, and the intended role of the shot.
Use `direct_segment` only when `reference_scene_id` and `reference_interval`
resolve to an analyzed reference scene. Use `structural_only` when the mapping
borrows an abstract mechanism without claiming a direct clip relationship; it
must not carry a reference interval. Use `none` when no reliable reference
evidence exists. Never infer a direct mapping from scene order alone.
Set `metadata.reference_media_usage: analysis_only`. Reference media is
analysis-only evidence: every `source_path` must resolve to the project's owned
source set, never a reference path, and reference media must never be copied into
assets or appear in the final edit or render.

The matrix row and resolution are the Research handoff. Choose an interval
within the approved resolution; do not invent a new reference/source match in
Scene Plan.


Caption policy 1.0.1: every source caption must declare origin, review, interval, and treatment (`retain`, `crop`, `mask`, or `replace`). Retain requires approved rights/copy/claim review. Reference captions are forbidden. Record `caption_source`, `source_caption_action`, and `source_caption_review` per shot; localized crop/mask reasons and safe-zone geometry are mandatory.

## caption / transition recipe intent（runtime 无关，P2）

每个 shot 必须填 `caption_recipe_intent`（`proof`/`label`/`hook`/`reveal`）和
`transition_recipe_intent`（`impact`/`action_match`/`proof`/`soft`）——这是**语义意图**，
不是具体做法。渲染器经 `lib.recipe_router.route_caption(intent, runtime)` /
`route_transition(intent, runtime)` 解析到 recipe_id（含 runtime 能力检查与回退）。

- 意图由 shot 的 `narrative_role` / `shot_intent` 派生，不写死 Remotion 组件名；
- 运营可预览 `recipe_capabilities(runtime)` 里的 recipe 清单并替换；
- 渲染 runtime 不支持首选 recipe 时自动回退，绝不静默换渲染器。

## 逐镜花字 treatment（应用层，参考 template/参考片）

`caption_recipe_intent` 应取自**自有镜头**语义（`shot_intent`/`narrative_role`）。
只有无显式意图时，才允许参考/模板的 `caption_treatment` 回退：

```text
自有 shot_intent/narrative_role → caption_recipe_intent（首选）
参考/模板 caption_treatment → 仅 fallback 提示（resolver 得出）
```

用 `lib.caption_treatment.resolve_caption_recipe_intent(own_caption_intent, reference_treatment)`
解析，并记录 `caption_treatment` / `caption_intent_derived_from` / `caption_fallback_used`。
`caption_fallback_used=true` 时，不得在验收中声称"与参考花字列一致"即是语义正确。
参考花字**文本/字体/成片**绝不进入最终字幕或资产（`analysis_only`）。

## template_run_plan（模板驱动，Req 3）

若项目有 `artifacts/template_run_plan.json`（`template_batch` 产物），scene_plan 以它为**结构约束**：
- 每个 scene 对应模板一个 slot，`metadata.template_slot_ref` 引用 slot_id；
- 消费 slot 的 `shot_language{shot_size/camera_movement/camera_angle}`（模板镜头语法）+ `caption_treatment`（经需求 1 的 `resolve_caption_recipe_intent` 得出 `caption_recipe_intent`）；
- 未绑定的 slot（`source=unbound`）不得进入 paid assets；参考 `overlay_text`/`dialogue` 仅 `analysis_only`，绝不复制进最终字幕或台词。

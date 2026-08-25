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

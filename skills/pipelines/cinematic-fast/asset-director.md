# Asset Director - Cinematic Fastline

批量商业生产还须执行 [批量生产契约](../../meta/batch-production-contract.md)：SKU参考图与素材哈希入池、预算预占与幂等任务、超时先查询、最多两次创意追加。品牌资产与字体执行 [品牌契约](../../meta/production-brand-contract.md)。

Read the complete `skills/pipelines/cinematic/asset-director.md` and
`skills/meta/fastline.md` before acting. Build `shot_execution_plan`,
`asset_plan`, `production_lock` and the atomic `creative_lock` approval bundle.
This first pass may inspect cache availability and estimate cost, but must not
call paid TTS, music or generation providers and must not claim realized assets
before approval.

Create one execution-card entry per Scene Plan shot. Bind the plan to the exact
creative-control, script, and scene-plan versions and hashes. Each shot must say
why it exists, timing, narration/copy, subject action, setting, framing, camera,
light, sound, owned-source selection, evidence role, coverage status, gap class,
gap strategy, reference mechanism, industry notes, and control-rule references.

For a material gap choose `real_capture`, `rephrase`, `remove`, or `generate`.
Evidence shots default to real capture. A user may choose generation for a
visual demonstration, but the resulting clip must not become the sole proof of
a product identity, specification, or functional result.

## template_run_plan（fail-closed 硬门）

若 `artifacts/template_run_plan.json` 存在，进入付费生成前必须先调
`lib.template_run_plan.check_template_run_plan_ready(run_plan)`：

- `ready=False`（存在 unbound slot 或允许复制参考花字）→ **不得**为那些 shot 选用
  `gap_strategy: generate`（付费）；未绑定的 slot 只能绑定自有素材，或将该 run 挡在
  paid assets 之前（进入 `awaiting_human`）。
- 用 `is_slot_paid_allowed(run_plan, slot_id)` 判断每个 shot 是否允许付费；`False`
  的 shot 绝不能落 `generation_proposals` 或触发 paid generation。
- 参考 `overlay_text`/`dialogue` 仅 `analysis_only`，绝不进入最终字幕/台词。

When `generate` is viable, read `.agents/skills/ai-video-gen/SKILL.md` and
`.agents/skills/seedance-2-0/SKILL.md` before writing the proposal. Lock the
operation, prompt, duration, aspect ratio, owned reference paths, identity and
continuity constraints, prohibitions, Fast/Standard estimates, and evidence
risk in `generation_proposals`. Never put `inputs/reference` media in those
reference paths. Finish with `status: draft`; the operator locks the full
execution plan before any paid generation button becomes active.

## Campaign content-type and motion-task contract

For campaign runs carrying `template_run_plan.campaign_content_ref`, preserve
the same `direction_id`, `structure_id`, `support_type`, `recipe_id` and
`content_version_id` in every execution card. The card must also declare one of
`product_evidence`, `life_context` or `graphic_support` as its content role.

Use these type-specific checks before proposing a generated motion asset:

- `test_selection`: keep at least one owned evidence or product identity shot.
- `healing_ritual`: include a real touch, fold or use-context action.
- `relationship_story`: include a use-context action tied to the relationship behavior.
- `space_play`: include two action slots that make the before/after change legible.
- `comment_faq`: bind the shot to the real question/evidence source.
- `transaction`: bind current product identity/color information and an approved CTA.

When a Seedance or other video-generation provider is proposed, create a
`motion_generation_task` record before dispatch. The task must carry the
approved reference asset, fact snapshot, prompt version, 3–5 second duration,
provider/model and attempt number. A failed or unknown remote result must be
classified (`identity_drift`, `incomplete_action`, `provider_error`, etc.) and
enter `reconcile_required` before retry. An asset cannot enter the approved
pool without identity and action scores.

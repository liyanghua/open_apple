# Asset Director - Cinematic Fastline

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

When `generate` is viable, read `.agents/skills/ai-video-gen/SKILL.md` and
`.agents/skills/seedance-2-0/SKILL.md` before writing the proposal. Lock the
operation, prompt, duration, aspect ratio, owned reference paths, identity and
continuity constraints, prohibitions, Fast/Standard estimates, and evidence
risk in `generation_proposals`. Never put `inputs/reference` media in those
reference paths. Finish with `status: draft`; the operator locks the full
execution plan before any paid generation button becomes active.

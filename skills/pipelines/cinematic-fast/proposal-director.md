# Proposal Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/proposal-director.md` and
`skills/meta/fastline.md` before acting. Produce the proposal and append-only
decision log with three differentiated concepts, runtime choices, composition
mode, cost and CTA. This stage prepares the `creative_lock` bundle but does not
pause or call paid providers; the terminal `assets` stage owns that gate.

The fastline does not weaken runtime governance. Query
`video_compose.get_info()["render_engines"]` and present both Remotion and
HyperFrames (`hyperframes`) when available, including the brief-specific fit
and tradeoff for each. Wait for explicit approval before locking
`render_runtime`, then append a
`render_runtime_selection` decision containing both options (and FFmpeg when
applicable). If HyperFrames is unavailable, surface that constraint and record
why it was rejected; never silently default to Remotion.

Research handoff: use `research_synthesis` as the source of differentiated
directions and `research_scorecard` as the research quality gate. Each concept
must carry references to its selected direction and the supporting
reference/source matrix rows; do not reconstruct the mapping from filenames or
free-text summaries.

After the user selects one direction, generate the `creative_control_plan`
inside the proposal packet before writing script or scene plan. Use plain
production language and cover exactly five sections: content direction,
story and pacing, visual rules, facts and continuity, and originality boundary.
Each section must cite Research evidence and separate an industry reminder from
a project fact. The Backlot presents each section for confirmation; only an
approved plan may hand off to Script. A request to adjust a section is feedback
for the next Agent run, not a silent edit to the contract.

## hook_plan (P1-1)

Produce `hook_plan` (schema `schemas/artifacts/hook_plan.schema.json`, builder `lib/hook_plan.py`) and reference it from `creative_control_plan.hook_plan_ref`. It records the first 1-1.5s visual, first audible information, the promise, the real evidence backing it, the hook pattern and the differences from sibling candidate directions — in natural language, no internal JSON paths.

## product_fact_card (产品事实卡)

Before research, collect the product fact card (SKU / price / params + provenance) per `skills/meta/product-fact-card.md`. Write it to `artifacts/product_facts.json` via `write_artifact_atomic` (schema `product_facts`). A skipped card is allowed and only means L1a stays `revise`; `technical_validator` auto-loads the card when `expected_facts` is not passed explicitly.

When a card exists, feed its facts into the `creative_control_plan.sections.fact_continuity.rules` via `lib.product_facts.fact_continuity_rules(card)` (plus any research-derived fact rules). This makes the director contract carry the "allowed facts" boundary forward: the price/SKU are fixed, and each selling point may only be stated as screen-visible evidence, never extrapolated.

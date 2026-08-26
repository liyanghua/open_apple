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

## template_run_plan（模板驱动，Req 3 的 proposal 产出）

模板模式下 proposal 不是"为每条模板重新发明一个概念"，而是**为整个模板批锁定一个可复制的适配骨架**：

1. 读批根共享的 `template_pack`（`templates[43]` 的 `archetype` / `slots[].shot_language` + `caption_treatment`）、`product_facts`、共享 `research_synthesis`。
2. 从 `template_pack` 挑选 pilot 模板（默认 `lib.template_run_plan.select_pilot`，覆盖不同 archetype + 字幕 treatment）；对每条被选模板：
   - 调 `lib.template_run_plan.create_template_run(template, template_pack_ref=..., product_facts_ref=..., adaptation_policy=...)` 生成 `template_run_plan`（status=`awaiting_human`）;
   - 对每个 slot 调 `lib.template_source_match.match_run_plan(slots, run)` 得到**去重到素材 + 一致性**的 `source_media_id` 绑定（no-dup：每素材先一次，缺则复用最贴近动作的素材；scene_plan 阶段再提 in-point 去重）;
   - 把每个 `template_run_plan` 写到 `projects/template-run-<template_id>/artifacts/template_run_plan.json`。
3. 调 `lib.template_batch.create_template_batch(template_pack, product_facts_ref=..., template_run_plan_refs=...)` 生成 `template_batch` 控制面并 `mark_pilot`；写到批根 `projects/<batch>/artifacts/template_batch.json`。
4. `template_run_plan` 是**单条 run 的不可变适配契约**，proposal 只做一次性骨架；后续 script/scene_plan/assets 各自读它作为输入约束，**不在 proposal 之外重复推导** slot 结构。

proposal 本身（`proposal_packet`）仍按字节走主链路——对模板批，它描述的是**这一批模板的共性与差异策略**，而非某一条的独立创意。`render_runtime` / `composition_mode` / 成本 / CTA 的治理规则照常适用。

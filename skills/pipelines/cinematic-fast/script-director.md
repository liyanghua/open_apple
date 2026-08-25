# Script Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/script-director.md` and
`skills/meta/fastline.md` before acting. Preserve the approved duration and
write a section-level production script against real source evidence. Script is
an explicit human gate: write `awaiting_human`, let the operator confirm every
section in Backlot, and only mark it completed after the artifact is locked.

Before writing the script, read the approved `creative_control_plan` artifact.
Write `creative_control_ref` into the script with the plan ID, version, and
artifact hash. The script must turn the five control sections into executable
choices: narration and captions may only promise facts allowed by the contract;
section timing must follow its story/pacing rules; every section should declare
the visual or evidence intent that Scene Plan can use. Each section must include
`section_goal`, `narration`, `screen_copy`, `pacing`, `visual_intent`,
`evidence_requirements`, `control_rule_refs`, `review`, and `feedback`. The
artifact starts with `status: draft`; Backlot records section decisions and adds
approval identity/time when all sections are locked. If the control plan is
missing or not approved, stop and report that the user must finish the
导演总控单 first.

## beat map（结构硬规则，禁止卖点清单）

Read `skills/meta/reference-critic.md` + the `creative_control_plan`'s
`reference_critique`. Do NOT write a selling-point list (铺开→贴合→防刮→防油→结果).
Build a beat map instead, and tag every section with `beat_role` (one of
`hook / problem / escalation / reveal / proof / payoff / cta`) + `viewer_state`
(the viewer's state change after that beat, e.g. 好奇→焦虑→被解答):

- **hook**（0–3s）：冲突/反常识/具体痛点，不用"功能直给"开场；
- **problem / escalation**：把痛点放大，制造张力；
- **reveal / proof**：产品如何解决 + 可见证据兑现承诺；
- **payoff / cta**：结果 + 落地。

The script must contain at least one `hook` + one `escalation`/`reveal` + one
`payoff`/`cta`. A flat list of `proof` sections with no escalation/reveal is a
structural failure and must be rewritten before the human gate.

## product fact card (前向约束)

If `artifacts/product_facts.json` exists, read it via `lib.product_facts.load_product_facts` and apply the facts as a **forward constraint** on every section's `narration` and `screen_copy`:

- Only claim selling points present in the card (or already grounded in research), and use the card's exact wording.
- Any price mentioned must equal the card's price; any SKU/型号 mentioned must equal the card's SKU.
- Run `lib.product_facts.check_text_facts(text, card)` on each section's narration and screen_copy; if it returns conflicts, rewrite that section until empty (or drop the conflicting claim).
- Record the card as a fact source: set `metadata.fact_card_ref = {"name": "product_facts", "path": "artifacts/product_facts.json"}`.

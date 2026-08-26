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

## template_run_plan（模板驱动，Req 3 的 script 重写）

若项目有 `artifacts/template_run_plan.json`，script 以它为**节奏与叙事结构约束**，但**文案必须重写为本商品事实**：

1. 读 `template_run_plan.slot_bindings` 与对应 `template_pack` 模板的 `slots[]`：取每个 slot 的 `shot_language`（景别/机位）、`duration_s`、`caption_treatment`、`overlay_text`、`dialogue`、`audio_layers`、`music_profile`，作为这一段**节奏/拍点/表现方式**的输入。
2. **只借结构，不借文字**：模板 `dialogue`/`overlay_text` 是参考台词/花字，仅 `analysis_only`，**绝不进入**本 run 的 `narration` 或 `screen_copy`。每段换成用 `product_facts` 重写、并由 `lib.product_facts.check_text_facts` 校验过的台词与花字（见上节前向约束）。
3. Scene 时序按模板 slot 节奏派生（每 scene 对应一个 slot，`start/end_seconds` 累计自 slot `duration_s`），并写入 `creative_control_ref` 指向 `template_run_plan` 的 `artifact_sha256`。
4. 每个 section 的 `beat_role` 仍须满足 beat map 硬规则（≥1 hook + ≥1 escalation/reveal + ≥1 payoff/cta），不允许把模板的平铺 slots 直接抄成卖点清单。
5. `status: draft`，照常过 script 人工 gate（`awaiting_human`）；只有 `check_template_run_plan_ready` 可用的 binding 才允许进入后续 paid assets。

仍须以 `script_id`/`template_id` 与 `metadata.fact_card_ref` 记录商品事实与模板来源，便于回溯。

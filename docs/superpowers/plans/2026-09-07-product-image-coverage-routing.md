# Product Image Coverage Routing Implementation Plan

> **For agentic workers:** REQUIRED: Use `superpowers:executing-plans` to implement this plan task-by-task, and `superpowers:test-driven-development` for every behavior change.

**Goal:** Extend the canonical `cinematic-fast` source-led mainline so every approved claim is routed to a semantically valid owned clip, a reviewed product-image-to-video task, or an explicit omission, while preserving fact provenance, human gates, product identity, 3:4 safety, and copy/voice/visual alignment.

**Architecture:** Add a claim-level coverage router between Research and Script. Keep `reference_source_matrix` as the single evidence/coverage matrix, represent owned and generated routes as a discriminated union, then propagate the selected route through Script, Scene Plan, Shot Execution Plan, Asset Plan, Backlot, generation execution, and QA. Original product-page assets remain immutable; clean product references are derived ledger assets. Generated media is visual expression only and never becomes independent product-fact evidence.

**Tech Stack:** Python 3.11+, JSON Schema Draft 2020-12, pytest, vanilla JavaScript/CSS Backlot UI, OpenMontage artifact/checkpoint APIs, registry/selector-based media providers, FFmpeg/ffprobe for deterministic media checks.

---

## Constraints and definition of done

- Keep input mode `source_led` or `source_led_template`; never route product images through `reference_driven`.
- Preserve legacy all-owned projects when their source media/hash/interval bindings are complete.
- Do not fabricate owned-source fields for generated routes.
- Do not make paid calls before the matching Assets approval subject is locked.
- If paid image cleanup is required, approve and review that result before authorizing image-to-video.
- Never hardcode a provider/model into schemas or claim-routing business logic; query the registry and lock the concrete selection in the approved production plan.
- The pilot is complete only when the silver-ion towel has a full 3:4 sample that passes identity, factuality/L1a, temporal alignment, crop safety, and human sample review.

## Chunk 1 — Canonical claim coverage contracts

### Task 1: Compile product facts into visual requirements

**Files:**

- Create: `lib/product_image_routing.py`
- Modify: `schemas/artifacts/product_asset_ledger.schema.json`
- Modify: `schemas/artifacts/product_facts.schema.json`
- Test: `tests/lib/test_product_image_routing.py`
- Test: `tests/contracts/test_product_page_acquisition.py`

**Step 1: Write failing unit tests**

Add tests for `compile_claim_visual_requirements(...)` proving that:

- observable claims require explicit subjects/actions/results and forbidden substitutions;
- contextual and non-observable claims cannot claim a generated shot as proof;
- wording is copied only from approved fact wording;
- page asset IDs and SKU scope remain attached;
- a forbidden or unresolved fact fails closed.

Also add ledger contract fixtures for a `derived_clean_reference` that records parent asset, transform input/output hashes, OCR result, identity result, SKU scope, and claim refs.

**Step 2: Run the tests and confirm RED**

Run:

```bash
pytest -q tests/lib/test_product_image_routing.py tests/contracts/test_product_page_acquisition.py
```

Expected: failure because the compiler and derived-reference contract do not exist.

**Step 3: Implement the minimal compiler and schema extension**

Implement pure deterministic functions in `lib/product_image_routing.py`:

- `compile_claim_visual_requirements(product_facts, requirement_specs)`
- `validate_clean_reference_asset(asset, *, parent_asset, expected_sku)`

Extend the ledger without weakening original asset validation. Original assets retain existing roles; derived assets use `asset_role=derived_clean_reference`, `usage_role=generation_reference`, structured transforms, `clean_reference_status`, OCR output, identity check, claim refs, and generation eligibility.

**Step 4: Run focused tests and confirm GREEN**

Run the command from Step 2. Expected: all pass.

**Step 5: Commit only Task 1 files**

```bash
git add lib/product_image_routing.py schemas/artifacts/product_asset_ledger.schema.json schemas/artifacts/product_facts.schema.json tests/lib/test_product_image_routing.py tests/contracts/test_product_page_acquisition.py
git commit -m "feat(cinematic-fast): define claim visual requirements"
```

### Task 2: Add the three-state coverage router

**Files:**

- Modify: `lib/product_image_routing.py`
- Modify: `lib/source_semantics.py`
- Modify: `schemas/artifacts/reference_source_matrix.schema.json`
- Modify: `lib/cinematic_fast_validation.py`
- Test: `tests/lib/test_product_image_routing.py`
- Test: `tests/lib/test_source_semantics.py`
- Test: `tests/contracts/test_source_evidence_contract.py`
- Test: `tests/lib/test_cinematic_fast_validation.py`

**Step 1: Write failing route-selection tests**

Cover these cases:

- exact subject + required action + visible result + crop-safe owned candidate → `owned_source`;
- a single droplet cannot satisfy continuous-pour absorption;
- roller-only cannot satisfy absorption;
- a `0.00` gauge cannot satisfy thickness/weight;
- no owned match + ready clean reference + approved fact → `generated_from_product_image`;
- non-observable AG+/10A content may use a generated expression but remains page-claim evidence only;
- SKU conflict, residual risky OCR, missing allowed wording, or unconfirmed fact → `omit`;
- legacy source-led rows become `owned_source` only when source/hash/interval are complete.

**Step 2: Run focused tests and confirm RED**

```bash
pytest -q tests/lib/test_product_image_routing.py tests/lib/test_source_semantics.py tests/contracts/test_source_evidence_contract.py tests/lib/test_cinematic_fast_validation.py
```

**Step 3: Implement the router and discriminated matrix row union**

Add `route_claim_coverage(...)` as a deterministic pure function. Update Research artifact construction to emit:

- `visual_route`
- `claim_visual_requirements`
- `owned_candidates` with accept/reject reasons
- `selected_source` only for `owned_source`
- `generation_reference` and `generation_spec` only for generated routes
- `route_reason`

Change schema and closure validation so each route has mutually exclusive required fields. `omit` rows cannot feed approved Script sections. Keep external-reference matrix behavior unchanged.

**Step 4: Run focused tests and confirm GREEN**

Run the command from Step 2.

**Step 5: Commit Task 2 files**

```bash
git add lib/product_image_routing.py lib/source_semantics.py lib/cinematic_fast_validation.py schemas/artifacts/reference_source_matrix.schema.json tests/lib/test_product_image_routing.py tests/lib/test_source_semantics.py tests/contracts/test_source_evidence_contract.py tests/lib/test_cinematic_fast_validation.py
git commit -m "feat(cinematic-fast): route claim visual coverage"
```

## Chunk 2 — Route propagation and executable asset plans

### Task 3: Propagate routes through Script and Scene Plan

**Files:**

- Modify: `lib/template_mainline.py`
- Modify: `schemas/artifacts/script.schema.json`
- Modify: `schemas/artifacts/scene_plan.schema.json`
- Modify: `lib/cinematic_fast_validation.py`
- Test: `tests/lib/test_template_mainline.py`
- Test: `tests/contracts/test_cinematic_fast_input_modes.py`
- Test: `tests/contracts/test_source_evidence_contract.py`

**Step 1: Write failing propagation tests**

Assert that mixed owned/generated rows can produce one approved script and scene plan; every section/scene retains claim IDs, fact/page refs, action keys, evidence row IDs, and `visual_route`; generated scenes contain no fake source path or interval; omitted rows are rejected before Script approval.

**Step 2: Run tests and confirm RED**

```bash
pytest -q tests/lib/test_template_mainline.py tests/contracts/test_cinematic_fast_input_modes.py tests/contracts/test_source_evidence_contract.py
```

**Step 3: Implement conditional mapping builders**

Refactor source-led row selection and `scene_plan_data(...)` to dispatch by route. Preserve current keyed scene/slot/section joins and existing approved copy. Make generation mappings bind a clean-reference hash and prompt contract, not an owned source interval.

**Step 4: Run tests and confirm GREEN**

Run the command from Step 2.

**Step 5: Commit Task 3 files**

```bash
git add lib/template_mainline.py lib/cinematic_fast_validation.py schemas/artifacts/script.schema.json schemas/artifacts/scene_plan.schema.json tests/lib/test_template_mainline.py tests/contracts/test_cinematic_fast_input_modes.py tests/contracts/test_source_evidence_contract.py
git commit -m "feat(cinematic-fast): propagate visual routes"
```

### Task 4: Build route-aware Shot Execution and Asset Plans

**Files:**

- Modify: `lib/template_assets.py`
- Modify: `schemas/artifacts/shot_execution_plan.schema.json`
- Modify: `schemas/artifacts/asset_plan.schema.json`
- Modify: `lib/template_alignment.py`
- Test: `tests/lib/test_template_assets.py`
- Test: `tests/lib/test_template_alignment.py`

**Step 1: Write failing builder tests**

Prove that:

- owned routes create `video_proxy`, `coverage_status=enough`, `gap_strategy=none`;
- generated routes create a `clean_product_reference` dependency and a `generated_video` task with `operation=image_to_video`;
- generated tasks bind fact/page/action/copy/reference hashes, 3:4 target, prompt constraints, provider capability, shortlist, cost range, retry limit, and approval subject hash;
- pre-lock paid tasks have `exists=false` and `paid_generation_approved=false`;
- generated shots never expose generated media as factual evidence.

**Step 2: Run tests and confirm RED**

```bash
pytest -q tests/lib/test_template_assets.py tests/lib/test_template_alignment.py
```

**Step 3: Implement minimal route-aware builders**

Update `build_shot_execution_plan(...)`, `build_asset_plan(...)`, and alignment validation. Remove the `model_family=seedance` schema constant and replace it with capability/operation plus runtime-selected provider/model fields. Add `generate_from_product_image` to the gap strategy enum and 3:4 to supported target ratios.

**Step 4: Run tests and confirm GREEN**

Run the command from Step 2.

**Step 5: Commit Task 4 files**

```bash
git add lib/template_assets.py lib/template_alignment.py schemas/artifacts/shot_execution_plan.schema.json schemas/artifacts/asset_plan.schema.json tests/lib/test_template_assets.py tests/lib/test_template_alignment.py
git commit -m "feat(cinematic-fast): build image fallback asset plans"
```

## Chunk 3 — Human-readable Assets review and approval sequencing

### Task 5: Render one coverage card per selling point

**Files:**

- Modify: `backlot/operator_state.py`
- Modify: `schemas/backlot/operator_state.schema.json`
- Modify: `backlot/ui/operator/approval_model.js`
- Modify: `backlot/ui/operator/approval.js`
- Modify: `backlot/ui/operator/styles.css`
- Test: `tests/backlot/test_operator_state.py`
- Test: `tests/backlot/test_operator_artifact_model.py`
- Test: `tests/backlot/test_operator_ui_contract.py`

**Step 1: Write failing projection/UI contract tests**

Require every Assets coverage card to expose:

- fact source, SKU scope, risk, allowed and prohibited wording;
- original product image and clean reference preview;
- owned candidates, action/result coverage, crop safety, and rejection reason;
- selected route and business-language reason;
- narration, subtitle, expected visual action/result;
- provider/model shortlist, duration, 3:4 target, estimated cost, and retry limit.

The UI must label generated media as “AI 视觉表达，不是商品事实证明” and must not use the generic “源素材代理 / 待生成” card for image-to-video tasks.

**Step 2: Run tests and confirm RED**

```bash
pytest -q tests/backlot/test_operator_state.py tests/backlot/test_operator_artifact_model.py tests/backlot/test_operator_ui_contract.py
```

**Step 3: Implement projection and rendering**

Build the business-readable coverage-card projection in `_asset_editor(...)`; keep raw artifact details available for engineering diagnostics. Render clear route badges and rejection explanations at 1180px, 900px, and 390px widths.

**Step 4: Run tests and confirm GREEN**

Run the command from Step 2.

**Step 5: Commit Task 5 files**

```bash
git add backlot/operator_state.py schemas/backlot/operator_state.schema.json backlot/ui/operator/approval_model.js backlot/ui/operator/approval.js backlot/ui/operator/styles.css tests/backlot/test_operator_state.py tests/backlot/test_operator_artifact_model.py tests/backlot/test_operator_ui_contract.py
git commit -m "feat(backlot): explain product image coverage routes"
```

### Task 6: Enforce two-step approval when cleanup is paid

**Files:**

- Modify: `backlot/operator_reviews.py`
- Modify: `backlot/shot_generation.py`
- Modify: `lib/template_mainline.py`
- Modify: `lib/checkpoint.py`
- Test: `tests/backlot/test_operator_reviews.py`
- Test: `tests/backlot/test_shot_generation_service.py`
- Test: `tests/lib/test_checkpoint_prerequisites.py`
- Test: `tests/lib/test_template_mainline.py`

**Step 1: Write failing gate tests**

Cover zero provider calls before approval; approval-subject hash mismatch; paid cleanup approval authorizing only clean-reference generation; a new Assets revision after cleanup; image-to-video remaining blocked until the clean reference is reviewed; idempotent replay; and denial of stale approvals after any fact/reference/prompt change.

**Step 2: Run tests and confirm RED**

```bash
pytest -q tests/backlot/test_operator_reviews.py tests/backlot/test_shot_generation_service.py tests/lib/test_checkpoint_prerequisites.py tests/lib/test_template_mainline.py
```

**Step 3: Implement approval scopes and revision reopening**

Represent approval scope explicitly (`clean_reference` or `image_to_video`), hash the complete paid subject, reject stale locks, archive superseded checkpoints, and always write a precise `next_action` for Assets recovery.

**Step 4: Run tests and confirm GREEN**

Run the command from Step 2.

**Step 5: Commit Task 6 files**

```bash
git add backlot/operator_reviews.py backlot/shot_generation.py lib/template_mainline.py lib/checkpoint.py tests/backlot/test_operator_reviews.py tests/backlot/test_shot_generation_service.py tests/lib/test_checkpoint_prerequisites.py tests/lib/test_template_mainline.py
git commit -m "fix(cinematic-fast): gate product image generation by revision"
```

## Chunk 4 — Registry execution and generated-shot QA

### Task 7: Execute approved image tasks through selectors

**Files:**

- Create: `lib/product_image_asset_execution.py`
- Modify: `backlot/shot_generation.py`
- Test: `tests/lib/test_product_image_asset_execution.py`
- Test: `tests/backlot/test_shot_generation_service.py`

**Step 1: Write failing fake-provider tests**

Use injected fake registry/selectors to test provider capability filtering, explicit model lock, local-reference support, idempotency key reuse, cost ledger writes, bounded retries, output hash capture, failure classification, and prohibition of silent provider/model substitution.

**Step 2: Run tests and confirm RED**

```bash
pytest -q tests/lib/test_product_image_asset_execution.py tests/backlot/test_shot_generation_service.py
```

**Step 3: Implement the thin execution adapter**

The adapter validates the approved task, resolves the locked registry tool, executes one operation, and records result provenance. It makes no creative routing decisions. Keep all tests provider-free.

**Step 4: Run tests and confirm GREEN**

Run the command from Step 2.

**Step 5: Commit Task 7 files**

```bash
git add lib/product_image_asset_execution.py backlot/shot_generation.py tests/lib/test_product_image_asset_execution.py tests/backlot/test_shot_generation_service.py
git commit -m "feat(cinematic-fast): execute approved product image tasks"
```

### Task 8: Fail closed on generated identity and temporal mismatch

**Files:**

- Modify: `lib/template_alignment.py`
- Modify: `schemas/artifacts/evaluation_report.schema.json`
- Modify: `skills/pipelines/cinematic-fast/sample-director.md`
- Test: `tests/lib/test_template_alignment.py`
- Test: `tests/integration/test_source_led_sample_alignment.py`

**Step 1: Write failing QA tests**

Require reference-hash equality, SKU/color/texture/structure identity pass, no generated text/logo corruption, expected action and result coverage, 3:4 subject completeness, and voice/subtitle timing overlap. Prove that a generated visual cannot raise fact-evidence strength.

**Step 2: Run tests and confirm RED**

```bash
pytest -q tests/lib/test_template_alignment.py tests/integration/test_source_led_sample_alignment.py
```

**Step 3: Implement QA gates and director guidance**

Add generated-asset checks to semantic alignment and the evaluation contract. Known failures must block Sample and cannot be overridden by a generic manual approval.

**Step 4: Run tests and confirm GREEN**

Run the command from Step 2.

**Step 5: Commit Task 8 files**

```bash
git add lib/template_alignment.py schemas/artifacts/evaluation_report.schema.json skills/pipelines/cinematic-fast/sample-director.md tests/lib/test_template_alignment.py tests/integration/test_source_led_sample_alignment.py
git commit -m "feat(cinematic-fast): gate generated product shot alignment"
```

## Chunk 5 — Silver-ion pilot migration and end-to-end acceptance

### Task 9: Rebuild the silver-ion Research and Assets artifacts

**Files:**

- Modify through canonical writers: `projects/template-run-yinlizi-aligned-A/artifacts/*.json`
- Modify through checkpoint API: `projects/template-run-yinlizi-aligned-A/checkpoint_*.json`
- Test fixture only if needed: `tests/integration/fixtures/silver-ion-product-routing.json`

**Step 1: Add the golden routing fixture and failing integration assertions**

Encode the approved expectations:

- continuous pour/visible contact result → owned;
- double-loop macro → owned;
- touch/knead softness → owned;
- stacked thickness → owned;
- AG+/10A → generated expression or information card, never independent proof;
- selected SKU identity card → soft-pink, 32×72cm, 120g;
- lifestyle shots → context only.

Explicitly reject single-droplet, roller-only absorption, cotton-prop softness proof, and `0.00` gauge proof.

**Step 2: Run the golden test and confirm RED**

```bash
pytest -q tests/integration/test_source_led_sample_alignment.py -k silver_ion
```

**Step 3: Re-run Research builders and rebuild downstream drafts**

Use artifact writers and checkpoint APIs; do not hand-edit hashes. Preserve the user-approved copy except where an omitted route forces a Script revision. Reopen Assets as `awaiting_human` with the complete coverage cards and zero paid calls.

**Step 4: Run the golden test and focused regression suite**

```bash
pytest -q tests/integration/test_source_led_sample_alignment.py tests/lib/test_product_image_routing.py tests/lib/test_template_mainline.py tests/lib/test_template_assets.py tests/backlot/test_operator_state.py
```

**Step 5: Open the Backlot Assets review and stop at the human gate**

Open:

```text
http://127.0.0.1:4750/p/template-run-yinlizi-aligned-A?stage=assets&artifact=generation_list
```

The user must be able to explain for each shot: what fact it serves, why the owned clip passes or fails, which product image is used, what will be generated, and how much it can cost.

### Task 10: After approval, generate, compose, and accept the full sample

**Files:**

- Generated artifacts/assets under: `projects/template-run-yinlizi-aligned-A/`
- Final sample under the approved project render/delivery path

**Step 1: Re-run preflight and read stage/provider skills**

Before any paid call, read the current cinematic-fast Assets/Sample directors and every registry-selected tool's `agent_skills`. Announce exact tool, provider, model/variant, reason, estimated cost, and that this is a sample.

**Step 2: Execute only the approved asset subjects**

Generate/clean references as separately approved, reopen Assets when required, then perform approved image-to-video, TTS, and BGM work. Record provider/model/seed/hash/cost/retry provenance after each call.

**Step 3: Compose one complete 2160×2880 3:4 sample**

Use the already approved render runtime. Do not silently switch runtime or provider.

**Step 4: Run automated acceptance**

```bash
pytest -q tests/integration/test_source_led_sample_alignment.py tests/lib/test_towel_stage50_contract.py
python -m pytest -q
```

Also run ffprobe/output-profile checks, L1a fact closure, generated identity checks, temporal copy/voice/visual alignment, audio presence, and 3:4 crop-safety checks.

**Step 5: Open Sample review and wait for human approval**

Present the full sample plus per-shot planned-vs-actual evidence. Human review must cover composition completeness, visual/copy/voice match, factual wording, rhythm/audio, and 3:4 subject integrity.

## Final merge readiness check

After the sample passes:

1. Run `git diff --check` and the full suite.
2. Confirm no generated project media or unrelated dirty files are staged.
3. Review the branch diff against `origin/main` for schema compatibility and migration safety.
4. Record the silver-ion pilot evidence and remaining Beta limitations.
5. Use `superpowers:finishing-a-development-branch` to present merge options; do not merge until the user explicitly chooses.


# Studio Beta Minimum Upgrade Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模板批量主链路收敛为一条可审计、可恢复、可由运营在 Studio 内完成常规修改的 Studio Beta 生产链路。

**Architecture:** 保留 `cinematic-fast` 作为唯一生产阶段机，把 `template_pack` / `template_run_plan` 作为输入事实；新增跨阶段 shot contract，使 `template_slot_id → scene_id → section_id → shot_id → asset_id → delivery_version_id` 以稳定 ID 连接。所有渲染、音频、QA、发布都只消费同一份不可变 manifest，运营编辑通过现有 Backlot typed draft/revision API 进入，批量层只负责隔离调度、checkpoint 和版本指针。

**Tech Stack:** Python 3.10+, Pydantic/JSON Schema, FFmpeg, Remotion, FastAPI Backlot operator API, existing `ProjectCommitStore`, pytest.

---

## Current Evidence

Focused regression tests currently pass (`43 passed`), but that is not Studio Beta evidence. Existing generated artifacts show downstream drift after the semantic fix:

| Run | Shots | `scene_plan` → `shot_execution_plan` source drift | Silent sections | Recipe intents | Non-cut `edit_decisions` |
|---|---:|---:|---:|---:|---:|
| sheet-01 | 8 | 1 | 0 | 6 | 0 |
| sheet-05 | 21 | 5 | 1 CTA | 19 | 0 |
| sheet-09 | 21 | 18 | 1 CTA | 17 | 0 |
| sheet-19 | 22 | 21 | 1 CTA | 18 | 0 |

The drift comes from positional reconstruction in `lib/template_assets.py` and `lib/template_source_match.py`, while existing runs were not rebuilt. `lib/template_mainline.py:768` still treats `edit` as a no-op. `lib/template_batch.py` is a status projection rather than a scheduler. `scripts/qa_template_render.py` promotes `sample-v1.mp4` to mutable `renders/final.mp4`, and `scripts/publish_template_run.py` checks statuses but does not certify an immutable delivery version or revalidate the current media hash.

## Quality Assessment Before Upgrade

| Metric | Current status | Evidence | Beta gate |
|---|---|---|---|
| 语义错配 | **不通过** | Existing long runs have source drift; current invariant compares derived keys, not the final rendered asset lineage | 0 mismatches in cross-stage audit and pilot renders |
| 静音/缺句 | **未证明** | TTS/mix has a local missing-file guard, but no final audio coverage report tied to every narration section | 100% narrated sections covered, intentional CTA silence explicit |
| 错误素材 | **不通过** | `shot_execution_plan` source selection diverges from `scene_plan` in 1/8, 5/21, 18/21, 21/22 sampled runs | 0 wrong-material findings |
| 错误转场 | **不通过** | 6/8, 19/21, 17/21, 18/22 scenes declare recipes while generated `edit_decisions` have 0 non-cut transitions | 100% recipe parity plus frame-level no-black-frame check |
| QA 失败但成功发布 | **未证明** | Negative test covers failed L1a, not stale hash, replaced final file, or old version publish | Every failed/stale gate blocks publish |
| 失败后可恢复率 | **未证明** | `ProjectCommitStore` and delivery versions exist; no template fault-injection matrix | 100% injected failures resume without duplicate paid work |
| 运营无需 JSON/脚本 | **不满足** | Typed operator APIs exist, but template media path still depends on `prep_*`, `render_*`, `qa_*`, `publish_*` scripts | 100% normal edits through Studio |
| 常规修改无需研发 | **不满足** | Existing adapters support pieces of the workflow; template `edit` is no-op | 5/5 operator scenarios completed independently |
| 批量黑帧/旧缓存/版本覆盖 | **未证明** | No real template runner, mutable `final.mp4`, and mixed cache keys | 0 black frames, 0 stale-cache reuse, 0 overwrites |

## Implementation Order

Implement in this order: (1) canonical lineage and invariants, (2) media/cache manifests, (3) recipe parity and transition rendering, (4) QA and publish hard gates, (5) Studio integration, (6) batch runner and recovery, (7) pilot acceptance. Do not expose the current template runs to operators before steps 1–4 are complete; otherwise Studio will make stale pairings easier to edit without making them correct.

### Task 1: Canonical Shot Contract and Cross-Stage Invariants

**Files:**
- Create: `lib/template_contract.py` — stable-ID joins, manifest construction, and fail-closed invariant validation.
- Modify: `lib/template_source_match.py:254-365` — return mappings keyed by `template_slot_id`/`scene_id`; remove downstream reliance on list position.
- Modify: `lib/template_mainline.py:552-611` — create explicit `scene_id`, `section_id`, `shot_id`, `asset_id` references and derive narration from the bound evidence action.
- Modify: `lib/template_assets.py:31-80` — join scene, section, and mapping by IDs; copy the selected source path/window directly from the mapping.
- Modify: `schemas/artifacts/scene_plan.schema.json`, `schemas/artifacts/script.schema.json`, `schemas/artifacts/shot_execution_plan.schema.json`, `schemas/artifacts/asset_manifest.schema.json` — require lineage references and semantic alignment fields.
- Create: `tests/lib/test_template_contract.py` — permutation, missing-ID, duplicate-ID, wrong-action, and stale-reference tests.
- Modify: `tests/lib/test_template_invariants.py` — run the validator across `scene_plan`, `script`, `shot_execution_plan`, `asset_manifest`, `final_props`, and `edit_decisions`.

- [ ] Write failing tests that reorder scenes, change a source mapping, and alter narration after downstream artifacts are built; each must fail closed.
- [ ] Implement ID joins and the invariant report with machine-readable findings (`severity`, `shot_id`, `expected`, `actual`).
- [ ] Make `scene_plan` the only source of selected source path/window and `script` the only source of narration/copy.
- [ ] Add a migration command `scripts/rebuild_template_artifacts.py` that rebuilds all derived artifacts transactionally for existing runs and archives superseded checkpoints.
- [ ] Run the validator against sheet-01/05/09/19 and require zero lineage mismatches before proceeding.

Run: `.venv/bin/pytest -q tests/lib/test_template_contract.py tests/lib/test_template_invariants.py tests/lib/test_template_mainline.py tests/lib/test_template_source_match.py`

### Task 2: Manifest-Driven Media, Audio, and Cache Invalidation

**Files:**
- Create: `lib/template_media_manifest.py` — canonical input fingerprint for source bytes/window, script text, voice/model/rate, BGM source, duration, runtime, recipe version, and output profile.
- Modify: `scripts/gen_template_audio.py:62-132` — sidecar must include the complete audio input fingerprint; reuse only on exact match; preserve failed/overflow status.
- Modify: `scripts/prep_template_media.py:45-236` — proxy, BGM, and mix products must use manifest keys; no exists-only reuse; register output hashes and durations.
- Modify: `lib/template_render.py:35-152` — replace placeholder hashes and hard-coded asset names with manifest references.
- Modify: `schemas/artifacts/asset_manifest.schema.json`, `schemas/artifacts/render_plan.schema.json` — require input/output hashes and cache keys.
- Create: `tests/lib/test_template_media_manifest.py` and extend `tests/lib/test_template_invariants.py` for text, voice, source-window, BGM, duration, and runtime invalidation.

- [ ] Write failing tests for changed narration, source bytes, source window, TTS rate, BGM bytes, and recipe version.
- [ ] Implement one fingerprint function and use it for TTS, proxy, mix, and render inputs.
- [ ] Make missing narration, `overflow`, failed probe, missing source, and missing mix track fail closed before rendering.
- [ ] Add an audio coverage report mapping every narration `section_id` to TTS file, mix interval, and measured speech duration.
- [ ] Verify that a successful asset from an older fingerprint is retained for audit but never reused for a new run.

Run: `.venv/bin/pytest -q tests/lib/test_template_media_manifest.py tests/lib/test_template_invariants.py tests/lib/test_template_render.py`

### Task 3: Transition Recipe Parity and Motion QA

**Files:**
- Modify: `lib/template_render.py:79-110` — derive `edit_decisions.cuts[].transition_*` from the same recipe router used by `sample_payload`.
- Modify: `lib/recipe_router.py`, `lib/sample_payload.py`, `remotion-composer/src/Explainer.tsx`, `remotion-composer/src/cinematic/types.ts` — keep canonical recipe IDs and render specs aligned.
- Create: `lib/transition_contract.py` — compare scene intent, edit decision, runtime payload, and rendered boundary expectations.
- Create: `tests/lib/test_transition_contract.py` — recipe parity and fallback tests.
- Modify: `tests/contracts/test_remotion_video_transition_contract.py` — assert dissolve overlap and no dark-frame fallback.
- Create: `tests/qa/test_template_transition_render.py` — render short boundary fixtures and inspect boundary frames with FFmpeg pixel/luma checks.

- [ ] Write a failing test for a scene recipe that is lost when `edit_decisions` is generated.
- [ ] Implement one canonical recipe lookup by `scene_id`/`shot_id`; record fallback reason when runtime lacks a recipe.
- [ ] Ensure `impact-cut`, `flash-proof`, and `action-match` have deterministic boundary windows and no implicit per-clip fade.
- [ ] Fail compose when a recipe is declared but absent from the runtime payload or when the transition contract cannot be evaluated.
- [ ] Verify all pilot templates have intended recipe parity and no black/near-black transition frame.

Run: `.venv/bin/pytest -q tests/lib/test_transition_contract.py tests/contracts/test_remotion_video_transition_contract.py`; then run the boundary fixture QA script with FFmpeg.

### Task 4: QA, Certification, Publish, and Version Immutability

**Files:**
- Create: `lib/template_delivery_gate.py` — validate current artifact hashes, final media hash, `final_qa_full`, L1a, sample/compose checkpoints, and certified delivery manifest.
- Modify: `scripts/qa_template_render.py:31-125` — QA the immutable candidate output itself; write `qa.subject_hash` and `qa.input_hashes`; do not copy a sample into a mutable final path before QA.
- Modify: `scripts/finish_template_compose.py` — write a versioned delivery candidate under `operator/delivery-versions/<version_id>/`.
- Modify: `scripts/publish_template_run.py:20-96` — call `DeliveryVersionService.certify`; publish only the current certified pointer; reject stale hashes and prior versions.
- Modify: `schemas/backlot/delivery_version.schema.json`, `schemas/backlot/current_delivery.schema.json`, `schemas/artifacts/publish_log.schema.json` as needed for template lineage.
- Create: `tests/lib/test_template_delivery_gate.py` — negative tests for missing QA, failed L1a, changed final bytes, changed input artifact, old version, and duplicate version ID.

- [ ] Write all negative tests before changing publish behavior.
- [ ] Implement candidate version creation with immutable media path and manifest hash.
- [ ] Make every edit or asset change invalidate certification and current pointer until re-rendered and re-QA'd.
- [ ] Prove publishing an old certified version cannot silently replace the current version.
- [ ] Add recovery tests for a crash between render, QA, certify, and pointer update; replay must be idempotent.

Run: `.venv/bin/pytest -q tests/lib/test_template_delivery_gate.py tests/backlot/test_delivery_versions.py tests/backlot/test_operator_revisions.py`

### Task 5: Minimum Studio Beta Operator Workflow

**Files:**
- Modify: `backlot/operator_adapters/script.py` — preserve section IDs and expose narration/copy edits with semantic revalidation.
- Modify: `backlot/operator_adapters/scene_plan.py` — expose source replacement/window, shot duration, framing, and transition edits against canonical IDs.
- Modify: `backlot/operator_adapters/assets.py` — expose TTS/BGM/subtitle/runtime controls and show gap/failure state without requiring JSON.
- Modify: `backlot/operator_adapters/edit.py`, `backlot/operator_adapters/sample.py` — wire edits to the template render plan and change-impact route; remove template no-op behavior.
- Modify: `backlot/operator_state.py` — show per-shot narration, evidence action, source preview/window, caption, transition, audio coverage, QA, and version status from the canonical manifest.
- Modify: `backlot/ui/operator/editors.js`, `backlot/ui/operator/app.js`, `backlot/ui/operator/api.js`, `backlot/ui/operator/store.js` — implement the five Beta workflows in the existing typed API.
- Modify: `schemas/backlot/operator_draft.schema.json` only when an operation cannot be represented by the existing typed contracts.
- Create: `tests/backlot/test_template_operator_workflow.py` and browser smoke coverage for operator-only edits.

Required Beta workflows:

1. Edit one narration and screen copy section; preview impact; commit; re-render only affected shots/audio.
2. Replace one source or source window; preview; commit; re-render affected shot and downstream QA.
3. Change shot duration/speed and preserve timeline continuity.
4. Change a transition recipe and preview the boundary.
5. Restore a previous delivery version and certify it again without overwriting another version.

- [ ] Write API and state tests for each workflow, including stale revision and idempotency conflicts.
- [ ] Implement typed template adapters and change-impact routing.
- [ ] Add UI controls and per-shot error messages that do not expose JSON or script commands.
- [ ] Verify a fresh operator can complete all five workflows using only Studio.

Run: `.venv/bin/pytest -q tests/backlot/test_template_operator_workflow.py tests/backlot/test_operator_drafts.py tests/backlot/test_operator_revisions.py`; run the browser smoke suite against the local Studio.

### Task 6: Real Batch Runner, Isolation, and Recovery

**Files:**
- Create: `lib/template_batch_runner.py` — durable queue, per-run lock, idempotency key, bounded retries, checkpoint resume, and failure isolation.
- Modify: `lib/template_batch.py` — store scheduler state, run attempts, output directory, current delivery version, and failure reason; keep projection separate from execution.
- Modify: `scripts/run_template_mainchain.py` — make it a thin entry point to the runner, not the scheduler itself.
- Modify: `scripts/render_template_sample.py`, `scripts/qa_template_render.py`, `scripts/publish_template_run.py` — accept run-scoped version/output directories and never share `final.mp4` or transient cache names.
- Create: `tests/lib/test_template_batch_runner.py` — concurrency, retry, interruption, duplicate submission, stale cache, and version-overwrite tests.
- Create: `tests/qa/test_template_batch_stress.py` — 18–24 runs with at least two concurrent asset-prep workers and serialized Remotion rendering.

- [ ] Write fault-injection tests for TTS failure, source missing, render failure, QA failure, process interruption, and publish conflict.
- [ ] Implement run-scoped locks and unique output paths; allow TTS/proxy preparation to parallelize but serialize Remotion rendering at concurrency 1.
- [ ] Resume from the last completed checkpoint and reuse only assets whose exact fingerprint is still valid.
- [ ] Ensure one failed run never changes another run's artifacts, pointer, cache, or status.
- [ ] Produce a batch report with success, failed, skipped, recovered, published, and blocked counts.

Run: `.venv/bin/pytest -q tests/lib/test_template_batch_runner.py tests/lib/test_template_batch.py`; then run the stress matrix and inspect all output hashes/pointers.

### Task 7: Beta Acceptance and Rollout

**Files:**
- Create: `docs/reports/studio-beta-readiness-2026-08-26.md` — evidence bundle, metrics, known limits, and sign-off.
- Create: `tests/acceptance/test_studio_beta_acceptance.py` — executable acceptance gates.
- Modify: `docs/EVALUATION_SYSTEM.md` — reference the template semantic/audio/transition/delivery gates and failure taxonomy.

Acceptance matrix:

| Gate | Required result |
|---|---|
| Semantic pairing | 0 mismatches across 18–24 runs; every shot has matching evidence action and stable lineage |
| Audio | 100% narration coverage; 0 unexpected silence/overflow/missing sentence |
| Assets | 0 wrong source/window findings; every source hash and duration verified |
| Transitions | 100% recipe parity; 0 black/near-black boundary frames |
| QA/publish | 0 publishes after failed/stale QA; only current certified delivery pointer publishable |
| Recovery | 100% recovery for injected failures; no duplicate paid generation |
| Operator independence | 5/5 workflows completed by two operators with no JSON/script edits |
| Batch integrity | 0 concurrent black frames, stale-cache reuse, cross-run contamination, or version overwrites |

- [ ] Run 18–24 template runs across the six currently supported templates and at least one long template (20+ shots).
- [ ] Have two operators perform the five workflows and record time, retries, and escalation count.
- [ ] Inject every failure class and retain logs/checkpoints as evidence.
- [ ] Publish the readiness report only when every hard gate is green; otherwise keep Studio Beta blocked.

## Explicit Non-Goals for Beta

- Do not expand from the current six proven templates to all 43 templates before the acceptance matrix is green.
- Do not add VLM semantic matching or a second render runtime to the critical path; the first Beta must prove deterministic lineage and fail-closed behavior.
- Do not support arbitrary JSON editing in Studio; expose typed operations only.
- Do not make `renders/final.mp4` the source of truth; it may be a convenience export, never the certified version identity.

## Go/No-Go Decision

Current decision: **No-Go for Studio Beta.** The existing implementation has useful foundations and a passing local unit-test slice, but it does not yet prove semantic correctness of downstream artifacts, transition parity, immutable QA-gated publishing, operator-only editing, or batch recovery. Re-evaluate only after Tasks 1–6 produce the evidence required by Task 7.

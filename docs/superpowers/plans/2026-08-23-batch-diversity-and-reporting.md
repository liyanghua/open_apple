# Batch Candidate Diversity and Run Reporting Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Implementation status (2026-08-23 code snapshot):** Track A core contracts, candidate diversity library, batch/sample gates, pairwise projection, and legacy compatibility are implemented. Track B report schemas, deterministic builders, historical backfill, report projection, degradation locks, and UI summary are implemented. The latest focused regression is `51 passed`; repository full-suite baseline is `1873 passed / 11 skipped`.
>
> Remaining rollout work: run a new five-candidate smoke batch, validate real VLM output and `partial/degraded` reporting, then promote new-batch default from `warning` to `hard_gate`. `table-mat-batch-001` remains historical/read-only and is never retroactively blocked. Rerun preview/promote/discard and incremental report generation remain follow-up work.

**Goal:** Make every batch candidate visibly and structurally different, and produce reproducible efficiency and quality reports that support production decisions without re-running generation.

**Architecture:** The work is split into two independently testable tracks. Track A creates a `candidate_variant_plan` before assets and samples, computes shot-level difference fingerprints, and blocks or warns on insufficient diversity. Track B rebuilds `batch_run_report` and `batch_quality_report` from run events, cost records, checkpoints, evaluation artifacts, and operator reviews. The batch workbench consumes a read-only projection of those artifacts; it must not calculate business metrics from UI state or introduce another orchestrator.

**Tech Stack:** Python 3, JSON Schema 2020-12, `jsonschema`, existing artifact hashing/atomic-write utilities, `lib.events`, `tools.cost_tracker`, Backlot state projection, browser UI contract tests, and `pytest`.

---

## Scope and Release Policy

The two tracks may be implemented in parallel, but each has its own contract tests and release gate.

- Track A release gate: a candidate pair that differs only in the first three seconds is rejected; a pair with at least three structural shot differences and three changed variant dimensions is accepted.
- Track B release gate: reports can be rebuilt from persisted facts after restart, tolerate missing/failed candidates with explicit warnings, and produce identical semantic content on an idempotent rebuild.
- The existing `table-mat-batch-001` is read-only input for backfill and verification. It must not call TTS, music, media providers, VLM, or rendering tools.
- Diversity starts in planning. It is not repaired by changing only the opening after samples are rendered.
- `candidate_batch` remains an index. Candidate artifacts, checkpoints, and decision logs remain in each child project.

## File Map

### Track A: candidate diversity

- Create: `schemas/artifacts/candidate_variant_plan.schema.json` — candidate-level variant intent, six variation dimensions, shot differences, and fingerprints.
- Modify: `schemas/artifacts/candidate_batch.schema.json` — `variant_plan_ref`, `diversity_mode`, and batch diversity summary. `variant_plan_ref` is required for new `hard_gate` batches and optional only for legacy/read-only batches.
- Modify: `schemas/artifacts/__init__.py` — register `candidate_variant_plan` and both batch report artifacts.
- Create: `lib/candidate_diversity.py` — pure planning, fingerprint, pairwise comparison, and gate functions.
- Modify: `lib/candidate_batch.py` — persist/validate variant-plan references and aggregate diversity metadata.
- Modify: `backlot/batch_actions.py` — expose separate structural and visual diversity failures to selection gates.
- Modify: `backlot/batch_state.py` — project diversity matrix, warnings, and eligible candidate explanations.
- Modify: `lib/sample_preflight.py` — reject a new hard-gate candidate with no valid variant plan before sample rendering.
- Create: `tests/lib/test_candidate_diversity.py`.
- Modify: `tests/lib/test_candidate_batch.py`, `tests/backlot/test_batch_actions.py`, `tests/backlot/test_batch_workbench.py`.

### Track B: efficiency and quality reporting

- Create: `schemas/artifacts/batch_run_report.schema.json` — timing, attempts, providers, cache, concurrency, throughput, and cost.
- Create: `schemas/artifacts/batch_quality_report.schema.json` — facts coverage, technical QA, VLM dimensions, human review, diversity, rework, and recommendations.
- Create: `lib/batch_reporting.py` — deterministic report builders and source-hash collection.
- Modify: `backlot/state.py` — add `batch_run_report.json` and `batch_quality_report.json` to `ARTIFACT_FILES` and collect them from `projects/<batch-project>/artifacts/` without changing child-project facts.
- Modify: `backlot/batch_state.py` — project report summaries and degraded/missing-data warnings from the two report artifacts.
- Modify: `schemas/backlot/operator_state.schema.json` — add a closed `reports` DTO under `batch_review`.
- Modify: `backlot/ui/operator/app.js`, `backlot/ui/operator/api.js`, `backlot/ui/operator/styles.css` — present report summaries and candidate comparison evidence after the backend contract is ready.
- Create: `scripts/backfill_batch_reports.py` — explicit read-only backfill for historical batches.
- Create: `tests/lib/test_batch_reporting.py`, `tests/backlot/test_batch_reporting_projection.py`, `tests/scripts/test_backfill_batch_reports.py`.
- Modify: `tests/backlot/test_operator_state_schema.py`, `tests/backlot/test_operator_ui_contract.py`.

### Documentation and fixtures

- Modify: `docs/art-plan/Batch_Production_Recovery_and_Formalization_Plan_2026-08-23.md` — link this plan and track P0-P3 status.
- Modify: `docs/art-plan/Table_Mat_Batch_001_Run_Retrospective_2026-08-23.md` — record candidate homogeneity and missing structured reporting as a dedicated finding.
- Modify: `docs/art-plan/Batch_Workbench_Interaction_Design_2026-08-23.md` and `docs/art-plan/Batch_Workbench_Editorial_Gallery_UI_Standards_2026-08-23.md` — define the candidate difference matrix and efficiency/quality report surfaces.
- Create: `tests/fixtures/batch_reporting/table_mat_batch_fixture.json` — one five-candidate fixture with named cases `diverse_pass`, `opening_only_blocked`, `failed_candidate`, `missing_events`, and `cost_degraded`; tests select cases by key and verify expected hashes/statuses.

---

## Chunk 1: Freeze the Contracts

### Task 1: Add the candidate variant contract

**Files:** `schemas/artifacts/candidate_variant_plan.schema.json`, `schemas/artifacts/candidate_batch.schema.json`, `schemas/artifacts/__init__.py`, `tests/lib/test_candidate_diversity.py`.

- [ ] **Step 1: Write failing schema tests.** Cover missing dimensions, duplicate shot IDs, invalid fingerprints, and a valid six-dimension plan.
- [ ] **Step 2: Define the minimal contract.** Require `version`, `batch_id`, `candidate_id`, `variant_revision`, `baseline_ref`, `dimensions`, `shot_differences`, `difference_fingerprint`, and `provenance`. Each dimension is an object with `value`, `baseline_value`, `changed`, and `rationale`; require `hook_type`, `narrative_structure`, `visual_grammar`, `pacing_profile`, `evidence_strategy`, and `asset_strategy`.
- [ ] **Step 3: Define deterministic gate evidence.** Use SHA-256 lowercase hex (`^[0-9a-f]{64}$`) for `structure_hash`, `visual_hash`, and `timing_hash`. Each `shot_differences` row carries `shot_id`, `difference_type` (`shot_order`, `source_window`, `duration`, `visual_grammar`, `evidence_role`, `asset_role`, or `caption_layout`), `evidence_class` (`structural` or `visual`), `evidence_ref` (`artifact`, `path`, `sha256`), and an optional half-open `time_range` in seconds. Require `opening_window: {start_seconds: 0, end_seconds: 3}` and `opening_only_change`.
- [ ] **Step 4: Define pairwise semantics.** A candidate must change at least three dimensions relative to the batch baseline. A candidate pair passes only when its symmetric dimension difference count is at least three, its structural shot difference count is at least three, and `opening_only_change` is false. The pairwise matrix is authoritative for selection; baseline counts explain how each plan was authored.
- [ ] **Step 5: Specify custom validation.** JSON Schema validates fields and hash patterns; `validate_artifact("candidate_variant_plan")` additionally rejects duplicate `shot_id` values, non-increasing ranges, `end_seconds > 3` when `opening_only_change=true`, and mismatched fingerprint counts.
- [ ] **Step 6: Register the artifact and add the reference.** New `hard_gate` batches reject a candidate without `variant_plan_ref`; `warning` batches persist `diversity_data_missing` and continue. Existing batches remain read-only compatible.
- [ ] **Step 7: Run `pytest tests/lib/test_candidate_diversity.py tests/lib/test_candidate_batch.py -q`.** Expected: schema tests pass and legacy candidate fixtures remain valid.

### Task 2: Add the batch run and quality report contracts

**Files:** `schemas/artifacts/batch_run_report.schema.json`, `schemas/artifacts/batch_quality_report.schema.json`, `schemas/artifacts/__init__.py`, `tests/lib/test_batch_reporting.py`.

- [ ] **Step 1: Write failing contract tests** for valid reports, missing source hashes, inconsistent totals, unsupported rubric versions, and explicit degraded sections.
- [ ] **Step 2: Define common provenance fields.** Both reports require `version`, `batch_id`, `run_id`, `generated_at`, `input_hashes`, `rubric_version`, `source_refs`, and `data_quality`. `rubric_version` is the metric-definition version for `batch_run_report` and the judge/evaluation rubric version for `batch_quality_report`. `source_refs` rows contain `kind`, relative `path`, `sha256`, and `record_count`; `data_quality` contains `status` and structured `warnings`.
- [ ] **Step 3: Define `batch_run_report` sections.** Require `timing` (seconds with queue/active/human_wait), `stages[]` (stage id, wall/active seconds, attempts), `provider_calls[]`, `cache` (hits/misses/rate), `concurrency`, `throughput`, `cost` (USD), `candidate_cycles[]`, and `milestones` (`start_to_sample`, `sample_to_selectable`, `select_to_delivery`).
- [ ] **Step 4: Define `batch_quality_report` sections.** Require `candidates[]`, `pairwise_diversity[]`, `human_review`, `rubric_version`, and `recommendations[]`. Candidate quality uses a 0-10 score scale where available, explicit `status` (`pass`, `revise`, `fail`, `missing`), VLM dimensions (`hook`, `opening_alignment`, `proof`, `pacing`, `readability`, `diversity`), five confirmation keys (`creative_direction`, `hook`, `proof`, `pacing`, `readability`), blocking items, rework tags/rounds, and next action. VLM remains advisory and is never substituted for a hard technical gate.
- [ ] **Step 5: Define source precedence and deduplication.** Read each `projects/<candidate>/events.jsonl` via `lib.events.read_events` and the batch stream `projects/<batch-project>/operator/batch-events.jsonl` via `backlot.batch_events.read_events`; deduplicate candidate events by `(run_id, event_seq)` and batch events by `event_id`, order by sequence, mark gaps as degraded, and compute active seconds from `machine_ms` while human wait comes from `approval_wait_ms`. Read each candidate `cost_log.json` through `tools.cost_tracker` as authoritative for spend; compare `candidate_batch.cost_usd` only for discrepancy warnings. Read checkpoint transitions, scoped `evaluation_report.sample/final`, and operator reviews by current revision/hash.
- [ ] **Step 6: Define semantic idempotency.** Canonicalize JSON with sorted keys and stable array ordering. Preserve `generated_at` when `run_id + input_hashes` match; exclude `generated_at` from `semantic_sha256`. A rebuild may update `generated_at` only when inputs changed and must create a new `report_revision`.
- [ ] **Step 7: Register both artifacts and run `pytest tests/lib/test_batch_reporting.py -q`.** Expected: report schema tests pass without changing old artifact validation.

## Chunk 2: Plan and Enforce Candidate Diversity

### Task 3: Implement the pure diversity library

**Files:** Create `lib/candidate_diversity.py`; test `tests/lib/test_candidate_diversity.py`.

- [ ] **Step 1: Add failing unit tests** for `build_variant_plan`, `compute_difference_fingerprint`, `compare_candidate_pair`, and `selection_diversity_failures`.
- [ ] **Step 2: Implement deterministic normalization.** Normalize dimension labels, shot order, source references, and timing buckets before hashing. The same inputs must produce the same fingerprint across restarts.
- [ ] **Step 3: Implement the hard checks.** Require at least three changed dimensions per candidate relative to the batch baseline and at least three structural shot differences per candidate pair. A first-three-second-only change fails. Shared source media alone is not a failure.
- [ ] **Step 4: Implement advisory checks.** Accept optional VLM evidence for visual grammar, composition, emotional read, and opening alignment. Return separate `structural_failures` and `visual_similarity_warnings` with evidence references.
- [ ] **Step 5: Keep rollout configurable.** The first batch uses `warning` mode; after fixture and smoke validation, switch new batches to `hard_gate`. Historical reports preserve the mode used at generation time.
- [ ] **Step 6: Run `pytest tests/lib/test_candidate_diversity.py -q`.** Expected: pass for distinct candidates, fail for opening-only candidates, and stable fingerprints.

### Task 4: Write plans before candidate production and feed the batch gate

**Files:** Modify `lib/candidate_batch.py`, `backlot/batch_actions.py`, `backlot/batch_state.py`; tests in `tests/lib/test_candidate_batch.py`, `tests/backlot/test_batch_actions.py`, `tests/backlot/test_batch_state.py`.

- [ ] **Step 1: Add failing integration tests** proving every newly planned candidate has a variant-plan reference before asset/sample work starts.
- [ ] **Step 2: Persist the plan through the existing artifact write path.** The stage agent writes `projects/<candidate>/artifacts/candidate_variant_plan.json` before `batch_fork.fork_candidate_projects` starts asset/sample work; `candidate_batch` stores only the reference and aggregate summary.
- [ ] **Step 3: Enforce the precondition.** `batch_approve_gate(gate="assets"|"sample")` and `lib.sample_preflight` call `assert_candidate_variant_ready`. In `hard_gate` mode a missing/invalid plan returns `validation_failed` and no paid call; in `warning` mode it emits a warning event and continues. `batch_select_for_edit` consumes the same pairwise gate result and cannot bypass it.
- [ ] **Step 4: Extend `selection_quality_failures()`** so structural sameness, visual similarity, missing diversity evidence, and unrelated technical failures are separate user-facing entries.
- [ ] **Step 5: Project a pairwise matrix** containing candidate IDs, symmetric changed dimensions, structural shot count, structural status, visual risk, and evidence refs. The eligible set must come from this projection, not a duplicated UI rule.
- [ ] **Step 6: Verify the named five-candidate fixture** where one pair is blocked and another pair passes. Run the focused Backlot tests and confirm no candidate is auto-selected.

## Chunk 3: Build Reproducible Efficiency and Quality Reports

### Task 5: Implement deterministic report builders

**Files:** Create `lib/batch_reporting.py`; test `tests/lib/test_batch_reporting.py`.

- [ ] **Step 1: Write failing tests** with event streams, cost records, checkpoints, evaluation reports, and operator reviews. Include retries, human waits, cache hits, failed candidates, and partial event data.
- [ ] **Step 2: Implement source readers.** Read persisted run events, cost tracker records, checkpoint metadata, scoped evaluation reports, candidate index data, and operator review decisions. Do not infer elapsed time from UI timestamps when an event or checkpoint fact exists.
- [ ] **Step 3: Implement `build_batch_run_report()`** with deterministic aggregation, explicit queue/active/human-wait separation, provider/runtime counts, cost reconciliation, and source hashes.
- [ ] **Step 4: Implement `build_batch_quality_report()`** with hard-gate status, VLM advisory dimensions, human confirmations, diversity matrix, rework tags, and recommended action per candidate.
- [ ] **Step 5: Record gaps explicitly.** Missing events, missing VLM output, cost mismatch, or failed candidates become `partial`/`degraded` sections with warnings; they never become zero-valued success metrics.
- [ ] **Step 6: Persist reports atomically** at `projects/<batch-project>/artifacts/batch_run_report.json` and `projects/<batch-project>/artifacts/batch_quality_report.json` through the canonical artifact path. Rebuilding the same input must not append duplicate decision-log entries or change the current candidate revision.
- [ ] **Step 7: Run `pytest tests/lib/test_batch_reporting.py -q`.** Expected: reports rebuild identically and all incomplete-data cases are explainable.

### Task 6: Backfill historical batches without production calls

**Files:** Create `scripts/backfill_batch_reports.py`; test `tests/scripts/test_backfill_batch_reports.py`.

- [ ] **Step 1: Write a dry-run test** proving `table-mat-batch-001` only reads artifacts/events and performs zero provider, VLM, TTS, music, or render calls.
- [ ] **Step 2: Add explicit CLI arguments** for batch project, `--dry-run`, and `--overwrite` (default false). Existing reports are preserved unless overwrite is explicitly requested.
- [ ] **Step 3: Backfill with historical `rubric_version` and input hashes.** Do not compare old scores to new rubric versions without a visible compatibility warning.
- [ ] **Step 4: Run the script in dry-run mode, then write the two reports once.** Verify idempotency by running it a second time and checking unchanged semantic hashes.

## Chunk 4: Expose the Reports in the Batch Workbench

### Task 7: Add a closed report projection

**Files:** Modify `backlot/state.py`, `backlot/batch_state.py`, `schemas/backlot/operator_state.schema.json`; test `tests/backlot/test_batch_reporting_projection.py`, `tests/backlot/test_operator_state_schema.py`.

- [ ] **Step 1: Add failing projection tests** in `tests/backlot/test_batch_reporting_projection.py` for complete, partial, degraded, and missing-report batches.
- [ ] **Step 2: Project only business-facing fields.** Efficiency: total time, slowest stage, retry rate, cache rate, cost, throughput, and milestone durations. Quality: candidate status, hard-gate conclusion, VLM summary, diversity risk, rework count, and recommended action. Keep provider/model/runtime in the evidence drawer, not the judgment layer.
- [ ] **Step 3: Preserve existing candidate field mapping.** Use the current DTO locations (`candidate.media.sample_url`, `candidate.score.evaluation`, `candidate.cost`, `phase_reason`, `aggregate_revision`) rather than inventing `preview_url` or `phase_label` fields.
- [ ] **Step 4: Disable or downgrade actions** when reports are stale, missing, `unstable`, or `degraded`; show the next recovery/read-only action instead of a false “complete” state.
- [ ] **Step 5: Run the projection and schema tests.** Expected: old batches still render, new reports appear when present, and no raw JSON or internal enum is required by the UI.

### Task 8: Add the decision surfaces and UI contract tests

**Files:** Modify `backlot/ui/operator/app.js`, `backlot/ui/operator/api.js`, `backlot/ui/operator/styles.css`, `docs/art-plan/Batch_Workbench_Interaction_Design_2026-08-23.md`, `docs/art-plan/Batch_Workbench_Editorial_Gallery_UI_Standards_2026-08-23.md`; test the existing UI contract suite.

- [ ] **Step 1: Add UI contract assertions** to `tests/backlot/test_operator_ui_contract.py` for a batch efficiency summary, candidate quality matrix, diversity evidence, slowest stage, rework recommendation, and report freshness/data-quality state.
- [ ] **Step 2: Keep candidate judgment compact.** Each candidate shows one conclusion and no more than three evidence tags; the drawer contains the pairwise matrix, VLM evidence, QA findings, cost, and retry detail.
- [ ] **Step 3: Show report provenance.** Display report timestamp, rubric version, and “数据不完整/已降级” status in business language. Never render `evaluation_report`, `status=sampled`, `undefined`, or raw provider fields in the judgment layer.
- [ ] **Step 4: Use a fake adapter for static mockup work.** Do not connect the mockup to batch actions until aggregate revision, review snapshots, stale handling, and coordinator recovery are complete.
- [ ] **Step 5: Run `node --check backlot/ui/operator/app.js` and `pytest tests/backlot/test_operator_ui_contract.py -q`.** Expected: no syntax errors, responsive states, and no horizontal overflow at 1440, 1024, and 390 pixels; Playwright screenshots are required when the static mockup is implemented.

## Chunk 5: Verification and Release

### Task 9: End-to-end fixture acceptance

**Files:** `tests/fixtures/batch_reporting/table_mat_batch_fixture.json` and the focused regression tests.

- [ ] **Step 1: Run the diversity matrix:** one high-homogeneity batch is blocked; one diverse batch is selectable; shared assets do not cause a false positive.
- [ ] **Step 2: Run report reconstruction:** reports are rebuilt from events/artifacts after a simulated restart; candidate failure and missing events produce warnings, not fabricated zeros.
- [ ] **Step 3: Run consistency cases:** cost mismatch uses `cost_tracker` as authoritative and reports the index discrepancy; event gaps mark the report degraded; repeated rebuilds are idempotent.
- [ ] **Step 4: Run the historical backfill:** `table-mat-batch-001` receives reports only and its current pointer, approvals, candidate revisions, and media hashes remain unchanged.
- [ ] **Step 5: Run the focused regression command:**

```bash
pytest tests/lib/test_candidate_diversity.py \
  tests/lib/test_batch_reporting.py \
  tests/lib/test_candidate_batch.py \
  tests/backlot/test_batch_actions.py \
  tests/backlot/test_batch_reporting_projection.py \
  tests/backlot/test_batch_workbench.py \
  tests/backlot/test_operator_state_schema.py \
  tests/backlot/test_operator_ui_contract.py \
  tests/scripts/test_backfill_batch_reports.py -q
```

- [ ] **Step 6: Commit each track separately** after its contract and focused tests pass. Do not merge the UI surface before the report and diversity artifacts are available in the projection.

## Rollout Order

1. Contracts and fixtures (P0).
2. Diversity planning and warning-mode gate (P1).
3. Report builders and read-only historical backfill (P1).
4. Batch projection and UI surfaces (P2).
5. Promote diversity from warning to hard gate after one new five-candidate smoke batch (P3).

## Open Decisions to Resolve Before Coding

- Default mode is `warning` for the first new five-candidate smoke batch and `hard_gate` for subsequent new batches only after the smoke fixture passes. `table-mat-batch-001` remains `legacy_read_only` and is never blocked retroactively.
- Which VLM model/rubric version is releasable for the `diversity` and `opening_alignment` advisory dimensions; unavailable VLM output must remain advisory and visible as missing.
- Whether report files are generated at batch completion only or also after each stage checkpoint. The first implementation should support completion plus explicit rebuild; incremental streaming can follow after the artifact contract is stable.

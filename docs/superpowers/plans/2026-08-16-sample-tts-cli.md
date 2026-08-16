# Sample TTS CLI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one governed `openmontage sample-tts` command and reusable service for approved Operator-managed `cinematic-fast` projects, with safe cache, paid-call authorization, recovery, and agent integration.

**Architecture:** The CLI is a thin parser/renderer. `SampleTTSService` owns project validation, approved-text resolution, selector planning, operation persistence, staging, cost governance, and the two Operator transactions around the external provider call. Existing providers remain behind `tts_selector`; all project mutations use `ProjectCommitStore`.

**Tech Stack:** Python 3.10+, argparse, JSON Schema, pytest, existing `TTSSelector`, `CostTracker`, `ProjectCommitStore`, checkpoint and artifact hashing utilities.

---

## Chunk 1: Contracts And Pure Resolution

### Task 1: Add schemas and schema registration

**Files:**
- Create: `schemas/artifacts/sample_tts_metadata.schema.json`
- Create: `schemas/artifacts/sample_tts_report.schema.json`
- Create: `schemas/backlot/sample_tts_operation.schema.json`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `lib/checkpoint.py`
- Test: `tests/openmontage/test_sample_tts_contracts.py`

- [ ] Write schema tests for normalized timestamps, report hashes, operation attempts, and invalid unknown lock/metadata fields.
- [ ] Run `pytest tests/openmontage/test_sample_tts_contracts.py -q`; expect import/schema-file failures.
- [ ] Add strict Draft 2020-12 schemas and register artifact names in the existing registry/checkpoint allowlist.
- [ ] Run the focused tests and existing schema contract tests.

### Task 2: Implement approved text and lock resolution

**Files:**
- Create: `openmontage/sample_tts_models.py`
- Create: `openmontage/sample_tts_resolution.py`
- Test: `tests/openmontage/test_sample_tts_resolution.py`

- [ ] Write tests first for provider-text precedence, punctuation joining, NFC, duplicate/invalid timings, 10-15 second range selection, explicit text equality, and canonical `locked_values.tts` keys/types.
- [ ] Run the focused tests to verify the expected missing-module failures.
- [ ] Implement deterministic dataclasses, typed errors, canonical request hashing, and whole-section range resolution.
- [ ] Run focused tests and `pytest tests/lib/test_production_lock.py tests/lib/test_checkpoint_approval_groups.py -q`.

## Chunk 2: Durable State And Governance

### Task 3: Add operation store and secure staging helpers

**Files:**
- Create: `openmontage/sample_tts_operation.py`
- Create: `openmontage/sample_tts_staging.py`
- Test: `tests/openmontage/test_sample_tts_operation.py`
- Test: `tests/openmontage/test_sample_tts_recovery.py`

- [ ] Write tests for monotonic transitions, one active reservation, receipt hashes, symlink/path containment, retention cleanup, and ambiguous-call reconciliation.
- [ ] Run tests to verify RED.
- [ ] Implement content-addressed operation records, RFC3339-Z timestamps, allowlisted metadata normalization/redaction, and staging roots outside projects.
- [ ] Run the focused tests and schema validation.

### Task 4: Extend cost tracker for operation-idempotent reservations

**Files:**
- Modify: `tools/cost_tracker.py`
- Test: `tests/tools/test_cost_tracker_concurrency.py`

- [ ] Write tests for cross-process lock, idempotent reserve by operation key, exact tool/estimate binding, refund, and reconciliation.
- [ ] Run the focused test to verify RED.
- [ ] Add sidecar locking and narrowly scoped operation-key methods while preserving existing unmanaged APIs.
- [ ] Run focused cost governance tests and the full existing cost tracker suite.

### Task 5: Materialize Operator activity to root events

**Files:**
- Modify: `backlot/project_commit.py`
- Test: `tests/backlot/test_project_commit.py`

- [ ] Write a failing test showing `stream="events"` reaches project `events.jsonl`, while existing streams retain their current paths.
- [ ] Run the test to verify RED.
- [ ] Add the explicit stream mapping and outbox idempotence using existing atomic writes.
- [ ] Run the focused Backlot transaction tests.

## Chunk 3: Selector Contract And Service

### Task 6: Harden the TTS selector envelope

**Files:**
- Modify: `tools/audio/tts_selector.py`
- Test: `tests/tools/test_tts_selector_sample_contract.py`

- [ ] Write tests for selected-provider allowlists, canonical provider arguments, effective request reporting, metadata/timestamp compatibility, and no-fallback failure envelopes.
- [ ] Run the focused tests to verify RED.
- [ ] Implement provider adapter normalization and consistent success/failure envelopes without changing provider routing policy.
- [ ] Run existing Doubao cache tests and selector contract tests.

### Task 7: Implement the shared service

**Files:**
- Create: `openmontage/sample_tts.py`
- Test: `tests/openmontage/test_sample_tts_service.py`
- Test: `tests/openmontage/test_sample_tts_recovery.py`

- [ ] Write integration-style fake-provider tests for managed preconditions, plan-only/cache-hit behavior, authorization/plan-hash binding, start/completion transactions, output validation, failure reconciliation, and idempotent reruns.
- [ ] Run the tests to verify RED.
- [ ] Implement `SampleTTSService.run()` and explicit reconcile flow using the resolution, operation, staging, selector, cost, and Operator primitives.
- [ ] Run focused service/recovery tests; confirm no real network provider is called.

## Chunk 4: CLI And Pipeline Integration

### Task 8: Add CLI entry points and stable exit codes

**Files:**
- Create: `openmontage/__init__.py`
- Create: `openmontage/__main__.py`
- Create: `openmontage/cli.py`
- Modify: `setup.py`
- Create: `tests/cli/test_sample_tts_cli.py`

- [ ] Write tests for both invocation forms, argument exclusivity, JSON stdout discipline, interactive provider confirmation, and exit codes 2-5.
- [ ] Run focused CLI tests to verify RED.
- [ ] Implement thin argparse entry points; keep orchestration and file writes in the service.
- [ ] Run CLI tests and `python -m openmontage sample-tts --help`.

### Task 9: Wire cinematic-fast sample director and docs

**Files:**
- Modify: `skills/pipelines/cinematic-fast/sample-director.md`
- Create: `docs/sample-tts.md`
- Modify: `docs/PROVIDERS.md`
- Modify: `Makefile`
- Test: `tests/contracts/test_cinematic_fast_pipeline.py`

- [ ] Add a contract test asserting the director references the shared service and no direct provider orchestration.
- [ ] Run the test to verify RED.
- [ ] Update the director, user/agent examples, provider configuration link, and optional Make target.
- [ ] Run the contract test.

## Chunk 5: Full Verification

- [ ] Run `pytest tests/openmontage tests/cli tests/tools/test_cost_tracker_concurrency.py tests/tools/test_tts_selector_sample_contract.py tests/backlot/test_project_commit.py -q`.
- [ ] Run the full existing test suite with `pytest -q` and record any unrelated baseline failures.
- [ ] Run `python -m compileall openmontage` and inspect `git diff --check`.
- [ ] Verify the live command remains plan-only unless explicit `--live --approve-paid` plus authorization is supplied; do not call Doubao during tests.

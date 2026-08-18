# Shot Reference Evidence Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add truthful per-shot reference evidence beside each matched owned-source clip in the Backlot shot mapping view.

**Architecture:** Extend each `scene_plan.metadata.source_mapping[]` item with one `reference_evidence` object. The cinematic-fast validator enforces direct, structural, and none modes; the operator-state projection resolves direct reference intervals into preview data; the vanilla JS workbench renders reference and owned evidence in a responsive two-column comparison.

**Tech Stack:** Python 3.10, JSON Schema, vanilla JavaScript, CSS, pytest

---

## Chunk 1: Data Contract And Projection

### Task 1: Project Per-Shot Reference Evidence

**Files:**
- Modify: `tests/backlot/test_operator_state.py`
- Modify: `tests/backlot/test_operator_state_schema.py`
- Modify: `backlot/operator_state.py`
- Modify: `schemas/backlot/operator_state.schema.json`

- [ ] Add failing tests for `direct_segment`, legacy `structural_only`, and strict operator-state schema validation.
- [ ] Run `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_state.py tests/backlot/test_operator_state_schema.py` and confirm the new assertions fail.
- [ ] Project `reference_evidence` with mode, mechanism, rationale, scene label, interval, preview URL, and poster URL into every shot.
- [ ] Resolve direct segments only through explicit `reference_scene_id` and `reference_interval`; never infer by shot index.
- [ ] Update the strict operator-state schema and rerun the focused tests to green.
- [ ] Commit the data-contract change.

## Chunk 2: Workbench Comparison

### Task 2: Render Reference And Owned Clips Side By Side

**Files:**
- Modify: `tests/backlot/test_operator_ui_contract.py`
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/styles.css`

- [ ] Add failing UI contract assertions for “参考机制”, “自有素材匹配”, direct reference playback, structural-only state, and the responsive comparison grid.
- [ ] Run `PYTHONPATH=. .venv/bin/pytest -q tests/backlot/test_operator_ui_contract.py` and confirm failure.
- [ ] Replace the current shot media/body split with a shot header, two-column evidence area, and shared mapping conclusion.
- [ ] Keep both media areas at stable aspect ratios; stack reference before owned source below the narrow breakpoint.
- [ ] Rerun the UI contract test and inspect the live project page at desktop and mobile viewport widths.
- [ ] Commit the workbench layout change.

## Chunk 3: Pipeline Enforcement

### Task 3: Validate Reference Evidence Semantics

**Files:**
- Modify: `tests/lib/test_cinematic_fast_validation.py`
- Modify: `tests/integration/test_cinematic_fast_end_to_end.py`
- Modify: `lib/cinematic_fast_validation.py`
- Modify: `lib/checkpoint.py`
- Modify: `skills/pipelines/cinematic-fast/scene-director.md`

- [ ] Add failing validator cases for valid direct and structural evidence, missing direct reference IDs, out-of-scene intervals, structural evidence with fabricated intervals, and `none` evidence carrying an interval.
- [ ] Run `PYTHONPATH=. .venv/bin/pytest -q tests/lib/test_cinematic_fast_validation.py tests/integration/test_cinematic_fast_end_to_end.py` and confirm failure.
- [ ] Load the verified `video_analysis_brief` envelope with `source_media_review` at checkpoint validation.
- [ ] Enforce the three evidence modes and keep `reference_media_usage: analysis_only` mandatory.
- [ ] Update the scene director with the exact `reference_evidence` shape and rerun focused tests to green.
- [ ] Run `PYTHONPATH=. .venv/bin/pytest -q tests/backlot tests/contracts/test_cinematic_fast_pipeline.py tests/lib/test_cinematic_fast_validation.py tests/integration/test_cinematic_fast_end_to_end.py`.
- [ ] Restart Backlot on port `4750`, verify `/api/health`, and inspect `table-mat-mix-v6` without mutating project artifacts.
- [ ] Commit the validation and documentation change.

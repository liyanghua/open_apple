# Source-Burned Caption Policy Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan.

**Goal:** Adopt the approved source-caption policy for `table-mat-mix-v4`, publish catalog `1.0.1`, and rerender a 10-15 second sample with no full-frame top/bottom masks while preserving the approved upstream lock.

**Architecture:** Add additive contract-v2 fields guarded by `caption_policy_version`, register a project-scoped `caption_policy_revision`, and require its semantic/artifact hashes at the sample gate. Keep catalog `1.0.0`, creative bundle, and production lock byte-stable; atomically stage only the revision, revised sample artifacts, render, report, and `awaiting_human` checkpoint.

**Tech Stack:** JSON Schema 2020-12, Python artifact/checkpoint validators, YAML pipeline/catalog manifests, Remotion/TypeScript, FFmpeg and existing `final_qa` tooling.

---

## Chunk 1: Contract RED→GREEN

### Task 1: Caption inventory and scene treatment schemas

**Files:**
- Modify: `schemas/artifacts/source_media_review.schema.json`
- Modify: `schemas/artifacts/scene_plan.schema.json`
- Modify: `schemas/artifacts/final_props.schema.json`
- Modify: `schemas/artifacts/sample_report.schema.json`
- Create: `schemas/artifacts/caption_policy_revision.schema.json`
- Modify: `schemas/artifacts/__init__.py`
- Test: `tests/contracts/test_caption_policy_contract.py`

- [x] Write tests for valid owned-caption inventory, invalid provenance/status/enums, interval containment, retain/reject and replace/overlay invariants, revision hash/date/status rules, and sample QA verdict requirements.
- [x] Run the focused contract tests and confirm they fail for the missing discriminator and schema fields.
- [x] Add the minimal additive schema conditionals and register the revision schema; retain legacy artifacts without the discriminator.
- [x] Run focused tests, then the existing artifact schema suite.

### Task 2: Catalog and pipeline contract

**Files:**
- Create: `skills/catalog/ecommerce-viral-remix/versions/1.0.1/SKILL.md`
- Create: `skills/catalog/ecommerce-viral-remix/versions/1.0.1/skill.yaml`
- Create: `skills/catalog/ecommerce-viral-remix/versions/1.0.1/examples/transparent-table-mat.yaml`
- Modify: `skills/catalog/ecommerce-viral-remix/index.yaml`
- Modify: `pipeline_defs/cinematic-fast.yaml`
- Modify: `skills/pipelines/cinematic-fast/scene-director.md`
- Modify: `skills/pipelines/cinematic-fast/compose-director.md`
- Test: `tests/backlot/test_caption_policy_catalog.py`

- [x] Write tests proving 1.0.0 digest/bytes remain unchanged, 1.0.1 resolves with a new digest, and sample/edit/compose artifact requirements include the revision.
- [x] Run tests to observe the expected missing-version/manifest failures.
- [x] Copy 1.0.0 into 1.0.1 and add the approved source-caption policy, example fields, digest/index entry, and pipeline requirements/director rules.
- [x] Run catalog and pipeline contract tests.

## Chunk 2: Project Revision and Composition RED→GREEN

### Task 3: Project caption-policy revision and checkpoint validation

**Files:**
- Modify: `lib/checkpoint.py`
- Modify: `backlot/project_commit.py` (only if required by existing transaction API)
- Create/update: `projects/table-mat-mix-v4/artifacts/caption_policy_revision.json`
- Test: `tests/projects/test_table_mat_caption_revision.py`

- [x] Write tests for revision reference/hash matching, approved sample-only impact, stale generation rejection, and atomic staging of all required paths.
- [x] Run tests and confirm they fail against the current checkpoint/artifacts.
- [x] Implement semantic hash/reference validation and create the revision from the approved production-lock and scene-plan hashes without mutating either.
- [x] Run focused tests and verify the current generation is used.

### Task 4: Remove masks and implement deterministic crop behavior

**Files:**
- Modify: `projects/table-mat-mix-v4/atelier/TableMatSample.tsx`
- Modify: `projects/table-mat-mix-v4/atelier/index.tsx` only if render input wiring requires it
- Test: `tests/projects/test_table_mat_sample_composition.py` or the repo's existing Remotion smoke-test location

- [x] Write failing composition checks for absence of `SourceTextGuard` full-frame bands, no contact caption overlay, retained clean/edge source copy, and the specified 1.4x top-anchored contact crop/frame mapping.
- [x] Run the focused test and confirm it fails on the current v2 implementation.
- [x] Remove the guard and duplicate captions; implement the approved clean/contact/edge per-scene behavior and crop geometry.
- [x] Run the focused test and a local Remotion render smoke test.

## Chunk 3: Render, QA, and Gate

### Task 5: Render revised sample and build QA artifacts

**Files:**
- Update: `projects/table-mat-mix-v4/artifacts/final_props.json`
- Update: `projects/table-mat-mix-v4/artifacts/render_plan.json`
- Update: `projects/table-mat-mix-v4/artifacts/sample_report.json`
- Create/update: `projects/table-mat-mix-v4/renders/sample-v3.mp4`
- Create/update: QA evidence under `projects/table-mat-mix-v4/artifacts/`

- [x] Render through the approved Remotion/atelier path with existing narration and locked assets.
- [x] Inspect frames 126 and 239 plus every fifth frame in `[126,240)`; verify the rejected claim is absent, no full-width bands remain, retained source copy is not duplicated, and subject/safe zones hold.
- [x] Run `final_qa`; require 540x960, 30fps, H.264/AAC, audio, full decode, frame evidence, crop geometry, and normalized-duplicate checks.
- [x] Record hashes, evidence, policy verdict, and revision reference in final_props/report.

### Task 6: Atomic sample checkpoint

**Files:**
- Update atomically via `ProjectCommitStore.transaction`: revision, decision log revision, final_props, render_plan, sample_report, sample-v3.mp4, `checkpoint_sample.json`

- [x] Stage the complete generation using the current expected generation.
- [x] Validate the checkpoint as `sample: awaiting_human`; do not advance edit or compose.
- [x] Verify approved production lock and creative bundle hashes are byte-stable and report the sample approval gate with the v3 path.

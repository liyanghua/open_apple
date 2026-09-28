# Caption Structure Review Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver 38-frame s01 text-risk / possible-clean-structure / uncertain evidence for human review, without making a new repaired clip or promoting assets.

**Architecture:** One bounded diagnostic library proposes three mutually exclusive labels inside the unchanged outer mask. A local registry tool validates the existing v2 contract and the exact d032 candidate, loads only small RGB crops, and writes source/overlay/candidate evidence and a clearly labelled diagnostic video. Nothing consumes these proposals as a compositing mask; every report remains `proposal_only=true`, `approved_for_restore=false`, `accepted_for_production=false`.

**Tech Stack:** Existing Python, NumPy, OpenCV, FFmpeg and BaseTool registry. No packages, network, paid inference, source changes or main-worktree merge.

Approved design: main project `projects/table-mat-reuse-first-v1/analysis/caption-structure-diagnosis/next-step.md`; user replied “同意” on 2026-09-28. This authorizes the evidence phase, not automatic restoration of proposed green pixels.

## Chunk 1: One diagnostic capability

### Task 1: Classify conservatively and produce an auditable review bundle

**Files:**
- Create `lib/caption_structure_review.py`: pure bounded crop classification; no file I/O, no corrected frame output.
- Create `tools/video/caption_structure_review.py`: one local `caption_structure_review` BaseTool, diagnostics only.
- Create `tests/lib/test_caption_structure_review.py` and `tests/tools/test_caption_structure_review.py`.
- Do not change `masked_caption_composite`, its defaults, VACE adapter, cost tracker, old contracts, masks, active manifests or old results.

- [x] **Step 1: Write and run failing core tests.**

API: `classify_structure(source_crops, candidate_crops, allowed_mask) -> (labels, stats)`.
Inputs: equal uint8 `(T,H,W,3)` arrays; `3 <= T <= 38`, H/W at least 7, at most 100000 crop pixels, boolean nonempty interior mask `(H,W)`. Reject invalid/oversize inputs before expensive allocations. Never mutate inputs. Labels uint8 `(T,H,W)`: 0 outside M, 1 text risk, 2 possible preservation (unapproved), 3 uncertain. Every pixel of M gets exactly one label in each frame; no label outside M.

Tests must cover:
1. Stationary white text and dark outline over varying background are risk, not preservation.
2. Moving bright structure agreeing with the text-free candidate is not classified as text merely because it is bright.
3. Candidate disagreement remains uncertain, unless marked text risk.
4. Matching isolated islands without a path to exterior agreement do not become preservation.
5. Spatially supported matching background can be proposed; deterministic/no input mutation/partition invariants hold.
6. Invalid geometry, dtype, mask, frame count and resource limits fail closed.

Run from this worktree with root `.venv/bin/python -m pytest -q tests/lib/test_caption_structure_review.py --tb=short`. Expected RED: missing classifier. Then implement, rerun, expect PASS.

- [x] **Step 2: Implement a fixed, conservative multi-cue proposal (not semantic truth).**

Compute grayscale and signed residual between source and already-caption-free candidate. Static bright-core evidence: 10th temporal percentile source gray >=180 and signed residual >=30. Static dark-core evidence: 90th temporal percentile source gray <=110 and signed residual <=-20. Core must be in M. Dilate union by two pixels and intersect M to guard text/shadows; never erode M and call its remainder clean. These constants are diagnostic heuristics, not accuracy claims. Record all thresholds.

For each frame, agreement requires max RGB difference <=8 AND x/y grayscale Sobel gradient difference <=4 (Sobel 3x3, scale 1/8). Require the entire 3x3 neighbourhood to agree, then exclude risk. Only agreement components connected to an agreeing exterior ring within 5 pixels of M can become green proposals inside M. No text-core signal => all M uncertain (refuse to treat a matching text-bearing candidate as a clean proof).

Output labels/stats only. Describe green as “possible preservation / pending human review”; matching candidate pixels are not independent proof of no text. Red is “text risk incl. guard,” not ground-truth OCR. Yellow includes uncertainty and unproven background. No temporal smoothing of RGB, no candidate warp, no blur repair, no automatic source restoration. Keeping pixels uncertain is a valid diagnostic result.

- [x] **Step 3: Write failing registry/tool tests.**

Use actual existing pilot fixture when available; no network mocks needed because tool has no network dependency. Wrong/missing exact candidate hash, v1 contract, missing explicit `diagnostic_only=true`, existing output directory, bad candidate geometry must fail without publishing a success report. Invalid cases checked before output mkdir. Tool must expose local provider and no new corrected clip/compositing action.

Success fixture: use real immutable local source/contract/candidate, skip explicitly if absent. Assert 38 labelled frames and local crop mask partition, source/candidate hashes unchanged, all output refs exist, review is visibly overlay-labelled, and `proposal_only is True`, `approved_for_restore is False`, `accepted_for_production is False`. Check new tool discovery and unchanged compositing defaults.

- [x] **Step 4: Implement bounded local tool.**

Inputs: `contract_path`, `candidate_path`, `output_dir`, literal `diagnostic_only=true`. Reuse `_file_path`, `_output_path`, `validate_contract`, `verify_pilot_source`, `verify_video`, `stream_rgb`, `_source_hash` and existing bounded FFmpeg helpers. Contract must be version 2; source and mask hashes are the existing pilot; candidate must equal SHA256 `e2346ec5a1b18e4f8e1f6cb3fb2bd9ef377a4186dbbe717c64000d50f32305df`, <=100MiB, 81 frames at 720x1280/30fps silent. Source frames 0..37 map to candidate 21..58. Validate all streams and exact counts; do not silently accept truncated media.

Crop is original M bbox plus 60px context, clipped to frame; record xyxy coordinates. Hold only 38 source/candidate crops (about 16MiB combined), not full videos. Array file stores labels and crop geometry with `allow_pickle=False` compatible arrays; it is named `unapproved-label-proposals.npz`, not release mask.

Write into a new output directory, never overwrite:
- 38 per-frame source/overlay/candidate PNG strips, at native crop pixel scale.
- Contact sheets, max 5 frame rows per sheet, with column names and frame numbers.
- Silent 30fps overlay diagnostic MP4, using strips and a visible “PROPOSAL ONLY - NOT REPAIRED VIDEO” banner; pad to even geometry for encoding, do not change frame count.
- `report.json`: hashes, code commit, timing, mapping, parameters, per-frame counts, proposal disclaimers, unknown text-removal/temporal/geometry acceptance, generated evidence refs and hashes. Flags as above; no `master.mkv` or completed repair output.

Candidate download/state, checkpoints, user approvals and cost decisions are NOT the tool's responsibility.

- [x] **Step 5: Verify software and independent reviews.**

Run new tests and existing masked/temporal/cost regressions with root Python, cwd isolated worktree. Use spec compliance review first, then separate code quality review. Fix findings before publishing a successful evidence run. Commit only these code/plan files to `codex/temporal-caption-repair`; preserve main worktree.

- [x] **Step 6: Real evidence run and human gate (parent agent).**

Log approval as revision of `(capability_extension, s01 mask-interior boundary refinement)` and keep assets in progress/false. Invoke local registry tool once to `projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/`. Inspect every source/overlay/candidate row, especially whether green overlaps old text or shadow. If wrong, report rejected proposal and retain uncertainty; do not manually relabel without recording evidence or manufacture a passing percentage.

Verify 7 protected source/mask/TTS hashes and report no model calls/budget changes. Publish an accessible review Markdown with legend and all sheets plus diagnostic video. Checkpoint awaiting_human with exact next_action. User approves/rejects the proposed preservation regions; only a subsequent authorized implementation may consume approved regions for v4. This turn ends at that evidence gate.

## Execution result — 2026-09-28

Evidence-phase implementation completed at `3142a3015eda21f3c89cbc0e5d271e97e04dfded`. New tests: 26 passed; regression: 136 passed plus 1 subtest. Independent spec and quality reviews approved this evidence scope. Nonblocking maintenance note: deduplicate classifier thresholds against the reported parameter dictionary in a future change; current values agree.

The real 38-frame registry run took 4.992 seconds. All 8 contact sheets were visually inspected; all 48 output hashes, label partitions, 7 protected inputs and the unchanged cost ledger were verified. Diagnostic video is H.264/yuv420p with 38 frames; continuous dynamic visual acceptance was not performed.

**Result is insufficient for restoration release:** possible-preservation proposals contain only 12–65 pixels/frame, mean 32.32 (0.251% of the fixed edit mask). This is a conservative heuristic result, not a physical upper bound on recoverable clean structure. No v4 was created, and no green proposal was approved. The project remains `awaiting_human` under d038, with assets unapproved and paid generation paused.

Review bundle: `projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/review.md` in the main project. Next proposed method is limited manual structure annotation on three key frames; it is not executed or authorized by completing this plan. Code remains in this isolated branch; no main-worktree merge.

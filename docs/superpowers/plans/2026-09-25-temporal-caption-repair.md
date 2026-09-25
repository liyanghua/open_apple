# Temporal Caption Repair Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Follow test-driven-development for implementation and independent spec/quality review. Do not operate paid providers.

**Goal:** Add a bounded, local, source-pixel temporal reconstruction capability and prove its limits on s01 before touching the other eight shots or resuming s06 generation.

**Architecture:** A numerical core registers clean image features between frames within an explicitly selected single shot. It borrows only unmasked, geometrically supported donor pixels from original frames. A registry tool handles exact frame decode, immutable inputs, lossless diagnostic encoding, provenance and quality evidence. The core never uses spatial fill or generated pixels as a silent fallback; uncertainty produces a rejected/partial diagnostic, never an accepted production asset.

**Tech Stack:** Existing Python 3.10 virtualenv, NumPy, installed OpenCV, FFmpeg/ffprobe, pytest, existing BaseTool/registry. No new models, GPU setup or paid API calls. ProPainter is not adopted: upstream states non-commercial-only, unsuitable for automatic use in this ecommerce production.

**Approved scope:** User approved on 2026-09-25: “按这个顺序补齐能力”. Isolated branch `codex/temporal-caption-repair`; main worktree has unrelated user changes and stays untouched except production-state records. No new generation, no broad crop/blur/black caption background, no auto human approval. Existing script/TTS remain immutable. Source production stays paused at assets.

## Chunk 1: Reconstruction capability, contracts and single-shot validation

### Task 1: Temporal source-pixel reconstruction core

Files:
- Create `lib/temporal_caption_repair.py` (registration and masked reconstruction only).
- Create `tests/lib/test_temporal_caption_repair.py`.

Interface:
```python
def repair_frames(frames, masks, *, min_coverage=0.98, max_donors=12):
    # frames: uint8 array [N,H,W,3], RGB; masks: bool/uint8 [H,W] or [N,H,W].
    # returns (candidate_frames, report).
    # Unresolved pixels retain original pixels and are explicitly reported.
    # No in-place modification of frames/masks, no source frame outside this array.
    ...
```

- [ ] Write failing tests for invalid shape/dtype/count/non-finite/out-of-range settings; immutable inputs and empty mask identity; source context bounds; stationary fully occluded region rejected; translated textured synthetic background reconstructed from clean donor pixels; outside-mask pixels exactly unchanged; masks followed through the warp; corrupted/misaligned donors excluded; deterministic result.
- [ ] Run with `/Users/yichen/Desktop/open_source_vedio_gen_projects/OpenMontage-main/.venv/bin/python -m pytest tests/lib/test_temporal_caption_repair.py -q`. Confirm failure is missing capability, not bad fixtures.
- [ ] Implement local sparse feature registration with masks excluded at both ends (including bilinear footprint), forward/backward or RANSAC consistency and local photometric evidence. Restrict feature region around the repair area; do not let hands far above the caption dominate the alignment. Use bounded donor count and avoid quadratic full-HD optical flow.
- [ ] Exclude the full feature/descriptor support footprint around captions, not only feature centres. Require finite/in-bounds transforms, RANSAC inliers plus forward/backward consistency, and pixel-local clean photometric support before accepting a donor. Reject unsupported parallax/occlusion; any chained transform must validate the final mapping directly, with bounded accumulated error, or be rejected. Never count a global fit alone as recovered pixel evidence.
- [ ] For each target frame, reconstruct masked pixels only from registered original unmasked donor regions; robust donor selection, no generative or spatial fallback. Report per-frame coverage, unresolved pixels, registration confidence/evidence, donor frame IDs, actual changed-pixel counts and method limitations.
- [ ] Copy the nearest original donor RGB triplet exactly; no averaging across donors, inpainting or interpolated output colours. Subpixel mapping may inform registration, but sampled output must have an explicit valid unmasked donor coordinate and valid surrounding sampling footprint. Bound the core to the same frame/pixel limits as the adapter and ≤12 donor attempts per target (≤1,440 registrations); working memory target ≤1 GiB at the documented maximum.
- [ ] Require min frame coverage and valid registration; `status` must be `candidate_requires_visual_review` at best, not `approved`. Lack of recovery yields `insufficient_evidence`. Quality evidence is not human approval.
- [ ] Every incomplete frame is explicitly partial, even if coverage ≥min_coverage. Use `partial_requires_visual_review` if any masked pixel remains unresolved; do not label the proxy as clean/uncaptioned and never set accepted_for_production true automatically. Only 100% supported coverage may receive `candidate_requires_visual_review`, still requiring visual inspection.
- [ ] Run tests; record exact command/results and limitations. Commit only Task 1 files.

### Task 2: Registry adapter and fail-closed diagnostics

Files:
- Create `tools/video/temporal_caption_repair.py`.
- Create `tests/tools/test_temporal_caption_repair.py`.
- Create `docs/temporal-caption-repair.md` (usage/release gate).

Required inputs: `input_path`, `mask_path`, `start_frame`, `end_frame_exclusive`, `output_dir`, `single_shot_verified` (must be the literal boolean true, no default). Bound to ≤120 decoded frames, ≤2,100,000 pixels per frame and ≤40,000,000 total decoded pixels (120 MB RGB input); apply limits before decode. Bound all subprocesses: probe ≤30s/2 MiB captured output, decode/encode ≤120s and decoded stdout limited to expected raw bytes plus one frame. Output directory must be new, not input parent/root, with no overwrite of source or existing artifacts (including symlink aliases). Masks must exactly match decoded frame geometry, be binary, nonempty and sparse enough for caption repair (≤10% frame pixels). Reject VFR/mismatched frames or invalid intervals rather than guessing. Audio is explicitly excluded for this visual diagnostic; no output should be presented as an audiovisual replacement.

- [ ] Write failing tests for registered discovery, input/path/frame/mask validation, source overwrite/existing output protection, geometry/rate mismatch and audio policy. Use small synthetic video fixture and real FFmpeg for end-to-end output, not only mocked success.
- [ ] Adapter inherits BaseTool, capability video_post, provider local, zero cost, experimental status, dependencies OpenCV/NumPy/FFmpeg/ffprobe; missing dependency yields unavailable and actionable install note. Discover through existing registry without editing provider routing or other pipelines.
- [ ] Decode exactly `[start,end)` to RGB24, call core, emit lossless FFV1 RGB master and diagnostic H264 review proxy under output_dir plus structured report. If quality gate fails, return a diagnostic with `accepted_for_production=false`; do not claim success as a production output. Exceptions must not masquerade as missing coverage.
- [ ] The proxy is a **diagnostic review proxy**, not necessarily uncaptioned: retain and label unresolved original pixels. Reserve output directory exclusively, reject path aliases/symlink ancestors, and never overwrite a prior output. Decode and validate the lossless master incrementally to stay within the 1 GiB working-memory target.
- [ ] Decode the lossless master and verify every pixel outside mask equals the corresponding decoded source; report separately from lossy preview drift. Record source/mask hashes, source intervals, fps, frame counts, elapsed time, model=`none`, provider=`local`, donor/coverage evidence, and `human_review_required=true`.
- [ ] Require caller to declare a verified single-shot frame interval; document that cross-shot donors are forbidden and camera/parallax errors require visual rejection. A passing numerical gate never guarantees recovered hidden ground truth.
- [ ] Run core/adapter tests and existing frame_sampler cache tests; document invocation and release checklist. Commit only task files.

### Task 3: Independent reviews and real s01 trial

- [ ] Independent spec review of Tasks 1–2, then independent code-quality review; fix findings with regression tests. No production integration until code gates pass.
- [ ] Run tool from isolated worktree through its registry against original production source frame interval `[0,38)` and the existing glyph mask v2. Inputs remain in the original project; new outputs go to its `analysis/temporal-caption-repair-v1/` directory only. This is an explicitly authorized capability trial, not full production advancement.
- [ ] Inspect start/middle/end plus 6 or more repair-region frames and normal-speed single-shot preview. Check old text, dark shadow, table rim, wood texture, flicker, donor ghosting and exact outside-mask preservation. Mark visual outcome honestly; retain failed evidence.
- [ ] If accepted, present ONLY the single-shot result for human review; do not batch before approval. If rejected, record the exact remaining occlusion/registration issue and next capability boundary, rather than silently switching to paid generation or a spatial blur.
- [ ] Record branch/commit, tests, trial report and current production checkpoint via existing writer. Keep source assets/TTS unchanged. Report implementation status distinctly from sample acceptance; no automatic s06 paid call or full render.

## Verification and non-goals

Baseline: `tests/tools/test_frame_sampler_cache.py`: 2 passed on clean worktree HEAD bf774a1. OpenCV/NumPy already installed; SciPy unavailable and not needed.

This first release is an evidence-based local reconstruction tool, not universal video inpainting, OCR, automatic segmentation, licensed model integration or a new production pipeline. A truly never-observed region may remain unrecoverable; reject it. No workarounds for provider content restrictions.

Primary technical references: https://docs.opencv.org/4.x/dc/d6b/group__video__track.html ; https://github.com/sczhou/ProPainter#license .

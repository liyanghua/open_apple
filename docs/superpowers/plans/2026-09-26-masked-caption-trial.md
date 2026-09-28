# Masked Caption Trial Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Execute one approved fal Wan2.1 VACE14B s01 repair, producing an original/repaired review clip without changing pixels outside the caption mask.

**Architecture:** A bounded local preparation/composite tool plus a one-attempt provider adapter; reuse existing FFmpeg validators and CostTracker. Keep all production choices in the agent/checkpoint. Existing source-only repair remains unchanged.

**Tech Stack:** Python 3.10, NumPy/OpenCV, FFmpeg/FFprobe, requests, fal-client for uploads with explicit lifecycle, pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-masked-temporal-caption-reconstruction-design.md` (adc30b5). User approved implementation and single sample in reply to the model/$0.50/upload proposal; decision d030. Do not reconfirm the same approval.

**Workspace:** `/Users/yichen/Desktop/open_source_vedio_gen_projects/OpenMontage-main/.worktrees/temporal-caption-repair`; use original repo `.venv/bin/python`. Baseline: 81 tests passed in 4.76s. Do not edit dirty main or merge yet.

## Chunk 1: One bounded pilot, not a general platform

### Task 1: Implement and test local media + approved one-attempt provider path

Files (only these plus direct tests/documentation):

- Create `lib/masked_caption_media.py`: streaming decode, contract/padding, composite and verification helpers.
- Create `tools/video/masked_caption_composite.py`: BaseTool, capability `video_post`, local `prepare`/`composite` actions, no network.
- Create `tools/video/vace_caption_candidate.py`: BaseTool, capability `video_post` (not default generation selector), provider fal, actions `submit` and `resume`, one POST maximum per reservation.
- Create `tests/lib/test_masked_caption_media.py`, `tests/tools/test_masked_caption_tools.py`.
- Create `docs/masked-caption-trial.md`: invocation inputs and actual limitations.

- [ ] Write failing tests for padding, source/mask hashes, strict metadata, composite and protected pixels.

Core rules in executable pseudocode:

```python
mapping = [max(0, min(j - 21, 37)) for j in range(81)]
assert mapping[21:59] == list(range(38))
out = source.copy()
out[mask] = candidate[mask]
assert np.array_equal(out[~mask], source[~mask])
```

Contracts restrict pilot to 720x1280, 30fps, source[0,38), static P5 0/255 mask exactly as approved. Source SHA `163a97e1536698d5dff1a61b075b60de7acfdf0500cde661c29664a45a8d0a61`; mask SHA `e4cdd2fa8c772889b2766ec5e3583893fd4642a921566297c600d51bbc9ba6d8`. Unit helper tests may use small synthetic dimensions; public prepare rejects anything except pilot. No caller-supplied hashes can relax the public contract.

- [ ] Run tests RED: `.venv` Python `-m pytest tests/lib/test_masked_caption_media.py tests/tools/test_masked_caption_tools.py -q`. Fail for missing behaviors before implementation.
- [ ] Implement minimum local tool. Inputs prepare: `action,input_path,mask_path,output_dir,single_shot_verified=true`. Output new immutable directory: source/master frame proof, `input-padded.mp4`, `mask-padded.mp4`, `repair_contract.json`; preserve 81 exact frames with map. MP4 encoded near/lossless for upload, static binary mask validated after decoding (threshold 128 equals original mask); source original RGB remains local authority. Reuse existing `_probe_metadata`, `_probe_timestamps`, `_pgm_mask`, bounded process helpers from `tools/video/temporal_caption_repair.py`; do not duplicate full decoder to whole-frame arrays. Stream one frame at a time with 120s watchdog/stderr cap; no rotations, VFR, scaling or flow interpolation. No audio in uploads.
- [ ] Implement composite action taking `contract_path,candidate_path,output_dir`. Validate all input hashes and prepared artifact hashes; candidate <=100MiB,81 frames,30fps,720x1280. Slice[21,59), hard-paste only approved mask. Produce FFV1/bgr0 `master.mkv`, H264 `review.mp4`, three-column source/candidate/composite `comparison.mp4` and `comparison-slow.mp4` (0.5x review only), 38-frame cropped contact sheets with sufficient unmasked neighboring context, `report.json`. Stream master re-decode against original and assert 0 outside-mask changed pixels. Report alignment `unverified`, visual review `pending`, accepted false; numerical pixel proof never implies visual pass. Do not emit production acceptance or touch manifest.
- [ ] Write failing provider tests: no approval/no reservation/hash mismatch cause zero uploads/POSTs; lifecycle on both uploads, fixed payload; no retries on uncertain POST; same reservation cannot submit twice even to new directory; resume only existing request ID; limit/download host safety; no key/url leak; fee remains unknown until reconciled by agent.
- [ ] Implement provider adapter. Input `action,contract_path,output_dir,project_dir,reservation_id,approval_ref=d030`; inspect canonical checkpoint for approved matching decision/model/scope and original project budget. Assert CostTracker reservation for this tool, operation `s01_wan_vace14b_once`, amount $0.50. Before uploads validate source, contract and upload artifacts; use original project paths. Acquire an atomic project-level attempt claim keyed to d030+s01+endpoint and permanently bind its reservation before side effects; a new reservation/output directory must not permit another submission under the same approval. Test concurrent callers and different-reservation attempts. Persist submission intent before POST; reuse CostTracker.bind_submission. If prior attempt exists, never POST again. Failures before POST are distinct from submission unknown; no auto refund.

Fixed payload is the reviewed spec: endpoint `fal-ai/wan-vace-14b/inpainting`, prepared video + mask_video,81 frames,match_input_frames/fps true,30fps,720p,9:16,30 steps,seed20260926,unipc,guidance5,shift5,acceleration none,maximum quality,safety true,prompt expansion/preprocess/auto downsample false,interpolation/downsample 0. Prompt only requests reconstruction of background under subtitles preserving visible tabletop/mat geometry and motion; no product images or restyling. Header `X-Fal-Store-IO:0`; output lifecycle 86400s. Upload via fal-client1.0.3 `lifecycle=StorageSettings(expires_in=86400)` (local normalization verified to yield expiration_duration_seconds86400; a raw dict is NOT accepted). Do not use SDK inference retry machinery: requests one POST, redirects off. Read-only status/result requests to fal queue URLs may be resumed; no second submission.

Submit returns request ID promptly (no 10min blocking call). Each resume polls once, records status/event; completion downloads candidate bounded to100MiB/120s with explicit HTTPS provider media hosts only, credentials never forwarded to media. Restrict authenticated status/result hosts to queue.fal.run. Retain minimal sanitized state; avoid raw signed URLs in user-visible outputs/events. For failed/pending/unknown return distinct truthful statuses and preserve reservation. Result success is provider completion, not creative approval. Parent agent performs <=10min10–30s bounded polling and billing reconciliation through existing CostTracker, then visual QA.

- [ ] Run tests GREEN plus baseline (81). Include real FFmpeg small synthetic roundtrip, padding mapping, unexpected frame count/rotation/VFR/corruption and frame-by-frame protected pixels; mocked network only, no real model in unit tests.
- [ ] Self-review, commit only owned paths. Run separate spec compliance then code quality reviews, fix blockers and re-run. No model call before release approval. Registry must discover both tools with metadata and explicit dependency status.

### Task 2: Execute single live trial and report (parent agent)

- [ ] Before use read project-scoped VACE technique note with official sources, then local tool `prepare` through registry. Inspect every mask/source crop for coverage. If existing mask insufficient, stop before upload, do not widen automatically.
- [ ] Verify current published 720p estimate81/16*.08=$0.405 (<$0.50), existing commitment4.5012/remaining3.9988; use CostTracker.approve_tool,estimate(.50),reserve; append explicit request metadata. Never print .env.
- [ ] Announce exact tool/provider/model then submit once through registry. If sandbox DNS fails before network success, inspect durable state: escalate permissions and resume the SAME logical attempt safely, never discard a submitting/unknown record or blind retry.
- [ ] Poll same ID with heartbeat. Record request result, actual runtime, unknown billed amount correctly. Provider failures/policy refusals do not cause fallback or second trial.
- [ ] If candidate passes strict media contract, run composite via registry; inspect all38 frames with source/candidate/composite context and normal-speed plus0.5x temporal review. Explicitly disclose if playback cannot be inspected in available tools. A bad candidate may still produce explicitly rejected diagnostic video, never accepted asset.
- [ ] Preserve original/TTS and active manifest; keep assets unapproved. Write trial report and checkpoint with next_action. Open local review video and include absolute Markdown media link. User reviews this first-shot diagnostic, not whole final video. If cannot obtain candidate, report precise blocker without calling old footage new output.

## Execution log

- [x] Design reviewed/committed adc30b5 and user approval d030 recorded.
- [x] Existing baseline81 tests pass4.76s.
- [x] Plan review passed after cross-reservation single-approval claim and three-column/half-speed review corrections.
- [ ] Task1 implementation and two-stage review.
- [ ] Task2 one live trial, honest QA and user handoff.

# Fixed s01 masked-caption trial

This is a bounded diagnostic for `table-mat-reuse-first-v1`, not a general
caption remover or a production-acceptance tool. Run through the `hybrid` assets
stage and registry. Existing `temporal_caption_repair` remains source-only.

## Contract and approval

Only the approved source and glyph-mask hashes are accepted. The source interval
is `[0,38)`, 720×1280 at 30fps. Uploads contain 81 silent frames using
`clamp(j-21,0,37)`; the candidate must match 81 frames/geometry/rate exactly.
Final diagnostic uses candidate `[21,59)` and source `[0,38)`.

The editable region is the existing 12,869-pixel glyph mask, not its bounding
rectangle. Do not expand, blur, feather, recolor, or replace the whole frame.
Do not apply the later approved 42-frame edit timing to this diagnostic.

## Registry invocation

Discover tools with `registry.discover()` and retrieve with `registry.get(name)`.
Call `.execute(inputs)` and inspect `success`, `data`, and `error`.
Use absolute paths beneath the original project, even from a code worktree.
All output directories must be new; historical artifacts must not be overwritten.

1. `masked_caption_composite` with `action="prepare"`, `input_path`, `mask_path`,
   `output_dir`, and literal `single_shot_verified=true` creates silent padded
   input/mask videos and `repair_contract.json`. Inspect source/mask coverage
   over all 38 frames before uploading. Source RGB, masks and frame mapping are
   validated after encoding; fail closed on mismatches.
2. Use the original project's `CostTracker`: approve `vace_caption_candidate`,
   estimate/reserve `$0.50` for operation `s01_wan_vace14b_once`. This is the one
   trial authorized by decision `d030`, not an additional or batch approval.
3. `vace_caption_candidate` with `action="submit"`, `contract_path`,
   `output_dir`, `project_dir`, `reservation_id`, `approval_ref="d030"` submits
   at most once. Provider is fal, endpoint `fal-ai/wan-vace-14b/inpainting`.
   Project-level exclusive ownership prevents a new reservation or directory
   from reusing the same approval. There are no automatic inference retries.
4. `action="resume"` with the same inputs polls only the owned request. The
   agent controls bounded polling, heartbeats and cost reconciliation. An
   uncertain submission must not be reset or submitted again.
5. `masked_caption_composite` with `action="composite"`, `contract_path`,
   `candidate_path`, `output_dir` validates the candidate, copies source RGB
   outside the mask, and creates `master.mkv`, `review.mp4`, three-column
   `comparison.mp4`, half-speed `comparison-slow.mp4`, contact sheets and report.

## Runtime, privacy and billing

Dependencies: NumPy/OpenCV, FFmpeg/ffprobe, requests, fal-client 1.0.3. Load the
project's configured `FAL_KEY` or `FAL_AI_API_KEY` without printing/copying it.
Both uploads use `StorageSettings(expires_in=86400)`. Inference requests use
`X-Fal-Store-IO: 0` and a separate 24-hour output expiration preference.
This does not promise zero retention. Only the silent pilot and mask are
uploaded; no product references, TTS or entire source video are uploaded.

720p published estimate is `81/16*0.08 = $0.405`, checked 2026-09-28.
The `$0.50` reservation belongs inside the existing `$8.50` cap. It is not a
provider-side spending cap or a known bill. Unknown charges remain unknown;
do not record zero or call catalog estimates actual spend. Failed/uncertain
submissions do not trigger a refund, fallback model or another submission.

## Verification and known limits

The FFV1 master must have zero changed RGB pixels outside the mask on every
frame. H.264 review files are lossy proxies and do not carry that exact-pixel
guarantee. Matching count/fps is not proof of content alignment. The report
therefore leaves alignment unverified, visual review pending and
`accepted_for_production=false`.

Inspect all 38 frames at full local detail plus normal and half-speed playback
for remaining glyphs/shadows, seams, displaced edges and temporal flicker.
Generated hidden background is reconstruction, not recovered source evidence.
Human approval is required before any production use; these tools never alter
the active asset manifest, script, TTS or the other shots.

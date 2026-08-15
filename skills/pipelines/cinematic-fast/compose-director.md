# Compose Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/compose-director.md` and
`skills/meta/fastline.md` before acting. Route only through `video_compose`
using the approved `render_plan` (`full` or validated `mux_only`). Run full
`final_qa`; black frames, freeze, loudness, safe-zone, resolution, frame-rate
or encoding failures stop the pipeline as failed and cannot be published.

Read the approved `render_runtime` from `edit_decisions` and pass it, together
with `proposal_packet`, to `video_compose`. Route Remotion, HyperFrames, or
FFmpeg exactly as the cinematic compose director specifies. A runtime failure
is a blocker: do not silently swap away from the approved engine, and do not
use `mux_only` when the runtime or visual timeline changed.

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

**Render gradient (cheapest first).** Before any user-facing render, work the
local-change ladder from `lib/render_plan.RENDER_GRADIENT`:

1. `still` — 1-3 target frames (CTA frame, crop-sensitive frames, source-caption
   frames) as PNGs via `render_plan.mode="still"`. Local changes (CTA text,
   crop geometry, caption treatment) are validated HERE first — no motion
   render until the stills pass.
2. `window` — 30-90 frames across a transition or a suspected blank-frame span,
   `render_plan.mode="window"`, for motion continuity.
3. `sample` — 300-450 frames at 0.5 scale, the only layer the USER reviews.
4. `full` — only after the previous layers pass.

A local visual change must not trigger `sample`/`full` directly; use
`change_impact` to decide. When the change is confined to the tail (e.g. CTA
fix after an approved full render) and the timeline did not shift, use
`render_plan.mode="range"` with `{"fromFrame": N, "master": {...},
"timeline_stable": true}` — frames [N, total) re-render and the unchanged
prefix is spliced from the master. Never set `timeline_stable: true` if a cut
moved.

Every long render emits run-event heartbeats (frames, attempt, wait reason)
into `events.jsonl` — do not re-implement progress reporting in chat.


Caption policy 1.0.1: when `caption_source=source_burned`, do not render duplicate atelier text. QA must check normalized-exact duplicate overlays, rejected glyph visibility, localized treatment area, crop geometry, and the caption-policy revision hash before sample approval.

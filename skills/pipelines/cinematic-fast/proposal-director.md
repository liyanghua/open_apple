# Proposal Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/proposal-director.md` and
`skills/meta/fastline.md` before acting. Produce the proposal and append-only
decision log with three differentiated concepts, runtime choices, composition
mode, cost and CTA. This stage prepares the `creative_lock` bundle but does not
pause or call paid providers; the terminal `assets` stage owns that gate.

The fastline does not weaken runtime governance. Query
`video_compose.get_info()["render_engines"]` and present both Remotion and
HyperFrames (`hyperframes`) when available, including the brief-specific fit
and tradeoff for each. Wait for explicit approval before locking
`render_runtime`, then append a
`render_runtime_selection` decision containing both options (and FFmpeg when
applicable). If HyperFrames is unavailable, surface that constraint and record
why it was rejected; never silently default to Remotion.

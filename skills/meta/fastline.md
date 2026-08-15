# Cinematic Fastline

Use this meta skill with `pipeline_defs/cinematic-fast.yaml`. It is a source- and
reference-led route for a short product montage where speed comes from reuse,
not from skipping evidence or approval.

## Operating Contract

1. Inspect reference and source media once, then persist the canonical review
   artifacts. Never use a reference file as an output asset.
2. Build one `production_lock` from the approved proposal, script, scene plan,
   asset plan and decisions. Do not call paid TTS, music or generation
   providers before the `creative_lock` bundle is approved.
3. Reuse content-addressed TTS, BGM, subtitles and media proxies when hashes
   match. A cache hit still requires materialization and media validation.
4. `final_props` is the only production timeline. Frame intervals are
   half-open: `[fromFrame, toFrameExclusive)`.
5. The `sample` stage renders a 10-15 second window through `video_compose` and
   runs quick QA. Pause for the second approval before edit or final compose.
6. A lock change must append a decision revision with the same `(category,
   subject)` pair. Use the lock diff route: `no_render`, `mux_only`, or
   `full_render`, plus the corresponding reapproval flag.
7. `edit` records impact and may not silently rewrite approved props. `compose`
   is the only final render entry point and must run full QA. `publish` only
   packages local files; external upload needs separate permission.

## Resume Rules

- Resume by reading the latest checkpoint, canonical artifact hashes and
  approval bundle state before any tool call.
- If a bundle hash no longer matches, mark it superseded and return to the
  appropriate gate. A rejected bundle stays pending until a revised bundle is
  created.
- Audio gain/LUFS-only changes may use validated `mux_only`; narration,
  provider, voice, CTA, runtime or composition changes reopen `creative_lock`.
- Caption or scene timing changes reopen `sample` and do not silently advance
  to final compose.

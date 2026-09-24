# Compose Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/compose-director.md` and
`skills/meta/fastline.md` before acting. Route only through `video_compose`
using the approved `render_plan` (`full` or validated `mux_only`). Run full
`final_qa`; black frames, freeze, loudness, safe-zone, resolution, frame-rate
or encoding failures stop the pipeline as failed and cannot be published.

## evaluation_report (final scope) — L1a gate

After full `final_qa` passes, run `technical_validator` on the final render
with `scope: "final"` and produce `evaluation_report`. Inputs: expected
duration from `edit_decisions.metadata.durationInFrames` / `final_props`,
`expected_facts` from the approved script facts, `text_sources` from final
captions and narration, `execution_diff_ref` pointing at
`sample_execution_trace`. Fatal L1a failures (SKU/price/params/sensitive
words) stop the pipeline as failed and cannot be published; fixable failures
become `repair_targets` recorded in the report.

Read the approved `render_runtime` from `edit_decisions` and pass it, together
with `proposal_packet`, to `video_compose`. Route Remotion, HyperFrames, or
FFmpeg exactly as the cinematic compose director specifies. A runtime failure
is a blocker: do not silently swap away from the approved engine, and do not
use `mux_only` when the runtime or visual timeline changed.

## Production-brand mainline (approved towel profile)

Read [the production brand contract](../../meta/production-brand-contract.md)
before using `renderer_family="production-brand"`. This family is supported
in the canonical proposal and edit schemas. Lock `render_runtime="remotion"`
and the reusable `composition_mode="templated"` at proposal; carry those
choices forward through edit. The branded component's exact font, media,
word timestamps, captions and title schedule come from the approved final
props artifact; do not invent a second timeline or mutate canonical edit JSON
to add render-only props.

Use the normal **`video_compose(operation="render")`** entry. Build its
`edit_decisions` render payload from a copy of the canonical decisions plus
the approved `ProductionBrandProps` fields. Keep the runtime and family
identical to the approved decisions. Pass `project_dir`, `asset_manifest`,
`proposal_packet`, `render_plan`, `output_path`, and the final script /
independent narration transcript used by final review. Example orchestration:

```python
payload = {**canonical_edit_decisions, **approved_brand_props,
           "renderer_family": canonical_edit_decisions["renderer_family"],
           "render_runtime": canonical_edit_decisions["render_runtime"]}
video_compose = registry.get("video_compose")  # registry already discovered at preflight
result = video_compose.execute({
    "operation": "render", "project_dir": str(project_dir),
    "edit_decisions": payload, "asset_manifest": asset_manifest,
    "proposal_packet": proposal_packet, "render_plan": approved_render_plan,
    "output_path": str(project_dir / approved_render_plan["output_path"]),
    "script_text": final_script_text,
    "narration_transcript_path": str(independent_transcript_path),
})
```

`approved_render_plan.mode` must currently be **`full`** and its delivery
profile dimensions/FPS must match the props. Include every referenced video,
logo, font and audio file in the asset manifest; references may be manifest
IDs or project-relative/absolute paths resolving to those entries. The tool
resolves and stages local media, checks declared content hashes, invokes
brand preflight and the actual `src/brand/entry.tsx` / `ProductionBrand`
component, applies delivery pixel-format normalization, and runs existing
pre-compose and final self-review gates. Failed brand preflight remains in
`result.data.brand_preflight`; failures cannot silently route to another
renderer.

For an approved final mixed audio track, keep `render_plan.audio.path/sha256`
bound to that manifest asset and omit the component's `audio` props; the tool
muxes that exact track before final review. Alternatively, when the approved
plan has no external mix, use the component's real `audio.narrationSrc` and
optional `bgmSrc`. Supplying both paths is rejected to prevent replacing or
doubling approved audio silently.

The generic `still/window/sample/range/mux_only` adapters, `sample_frames`,
dimension overrides, subtitle sidecars and generic compose `options` are
**not supported for this family yet** and fail explicitly. The render-gradient
instructions below apply only to families with those adapters. Do not bypass
this limitation by calling low-level `remotion_render` to label a partial
render as approved mainline output. Existing dedicated local still diagnostics
may test the component, but cannot count as the missing pipeline adapter or
production approval. Keep any plan requiring those modes blocked until its
adapter or an explicit revised full-render plan is approved.

Collect actual browser font-loading/DOM evidence at title/caption changes,
transition boundaries and the last frame as described in the brand contract.
The returned `brand_preflight` is source-file preflight, never final visual
QA; run the normal `final_qa` and specified human final review on the resulting
file and bind their evidence to its dependencies. A legacy font appearance
does not certify Microsoft YaHei and cannot unlock strict batch production.

## Remotion Render Payload Contract (templated / Explainer)

The canonical `edit_decisions` artifact is schema-strict and must NOT be
silently mutated. The render payload passed to `video_compose` is the
canonical artifact plus three render-contract fields, ALL derived
deterministically from the approved `final_props`:

1. **`cuts[].source`** may stay an asset-manifest ID — `video_compose`
   resolves it to the project-relative path and stages the media against the
   project dir (never the agent CWD).
2. **`captions`** (top level, render payload only):
   `[{word: c.text, startMs: c.startMs, endMs: c.endMs} for c in final_props.captions]`.
   The canonical artifact declares them via
   `caption_render_mode="remotion_overlay"` +
   `caption_source="artifacts/final_props.json#captions"`.
3. **`audio.music`** (Explainer shape, when music is approved):
   `{src: <absolute path>, volume, fadeInSeconds, fadeOutSeconds}`.
   Schema-shape (`asset_id`, `fade_in_seconds`) is for the artifact record
   only.

The tool now enforces the approved timeline: it injects
`props.durationInFrames` (from `edit_decisions.metadata.durationInFrames` /
`final_props`) and the stock Explainer composition honours it instead of its
"+1s final fade" padding. When the timeline must be capped explicitly, pass
`sample_frames: "0-<N-1>"` (forwarded through `operation="render"`). The tool
also normalizes the finished render to the delivery profile's pixel format
automatically (Remotion emits full-range yuvj420p; the tool re-encodes to
yuv420p/tv in place, flagged as `post_encode: true`) — never hand-run an
encode pass.

## Music Change (audio-only, post sample approval)

When full QA reports the deliverable effectively silent and the user approves
adding music (decision re-logged as `music_source`, same category+subject
pair):

- Prefer layering the track through the Explainer music layer with a full
  re-render (single pass, fades land exactly on the delivery boundary). A
  validated `mux_only` on the approved visual master is the alternative when
  the visuals must not be touched.
- Music-only changes do NOT reopen `creative_lock` or `sample` (fastline:
  music is not a creative-lock member). Record the route in the compose
  checkpoint `metadata.change_impact`.
- BGM sourcing order: `music_library/` → free search (pixabay_music, no key)
  → generation APIs (key required). Record track, license, volume and fades
  in the decision entry.

## QA Truth Table

| Signal | Meaning | Action |
|---|---|---|
| final_review "effectively silent" | sources silent, no music approved | escalate to user: silent / BGM / bring-your-own |
| final_review subtitle "expected but not found" + `caption_render_mode` declared | false positive (pixel-burned captions) | fixed in tool; verify via final_qa caption_spec |
| frame count > approved timeline | stock composition padding | fixed in tool (durationInFrames injection); pass `sample_frames` if a legacy composition ignores it |
| `pix_fmt` mismatch in final_qa | legacy Remotion yuvj420p | fixed in tool (automatic profile normalization, `post_encode`) |
| "Motion ratio 0%" on a video-led montage | review ran on unresolved asset IDs | fixed in tool (review uses resolved cut paths) |

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

## caption_style render-payload field (P1-1)

When a captioned render goes through Remotion, the render payload may carry a
top-level `caption_style` object derived deterministically from the approved
`caption_style_fingerprint.style` via `lib.caption_style.to_overlay_spec()`.
`caption_style_fingerprint` is a `required_artifacts_in` of both the sample and
compose stages (see `pipeline_defs/cinematic-fast.yaml`) — the agent must read
it from the research checkpoint, not improvise a style. The derived spec
includes `bottomOffsetPx` (安全区底部偏移的单一数据源); when the fingerprint
is `not_applicable`, omit `caption_style` and let the renderer use its defaults.
It is a render-payload-only field (never written into canonical
`edit_decisions`), mirroring the `captions` and `audio.music` derived fields.
The composition applies it in `CaptionOverlay`/`SafeCaptionTrack`; no reference
font file is ever copied — `fontFamily` must name an open-source font or style
approximation.

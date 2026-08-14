# Cinematic Fastline Technical Upgrade Design

**Status:** Draft for user review  
**Date:** 2026-08-14  
**Scope:** OpenMontage reference-driven cinematic/product remix pipeline  
**Primary project:** `transparent-table-mat-remix-01`  
**Target runtime:** Remotion  
**Target platforms:** Douyin, WeChat Channels, Xiaohongshu  

## 1. Summary

This design makes the cinematic reference-remix workflow predictable within a
3-5 hour wall-clock window without weakening the production contract. The main
source of delay is repeated analysis, repeated TTS/mixing, dispersed human
approvals, and unnecessary full-path reruns. A 30-second 30fps video has 900
frames by definition; reducing that count would change the delivery, not solve
the workflow bottleneck.

The upgrade is split into two layers with a strict dependency boundary:

- **P0, required for the 3-5 hour claim:** registered content-addressed
  artifacts, parallel media inspection, provider-complete TTS/mix caching,
  canonical timeline props, deterministic mux-only output, executable approval
  groups, a real sample stage, and schema-backed quick/full QA.
- **P1, after P0 is measured:** Backlot cache/ETA presentation, reusable brand
  and caption profiles, and optional scene-level incremental rendering for
  longer or batch productions.

The implementation remains instruction-driven. Python may provide tools,
cache persistence, schemas, and reports; it must not become a hidden workflow
orchestration engine or a second state machine.

## 2. Goals and Non-goals

### Goals

1. A new source-footage remix reaches a reviewable 10-15 second sample quickly.
2. Unchanged media and unchanged TTS are never reprocessed or re-billed.
3. A change is routed to the smallest safe affected layer.
4. The final output still passes full technical, visual, audio, subtitle, and
   runtime-governance checks.
5. Backlot explains what is running, what was reused, and the remaining ETA.
6. Remotion remains an explicit, logged runtime choice.

### Non-goals

- No silent switch from Remotion to HyperFrames or FFmpeg.
- No removal of source-media inspection, copyright isolation, sample review, or
  final QA.
- No paid supplemental generation without an explicit approval gate.
- No claim that arbitrary caption changes can be overlay-only before the
  composition is actually split into independent layers.
- No global change that disables existing checkpoint governance for other
  pipelines.

## 3. Performance Contract

The following are engineering targets, not unconditional promises. Total time
is reported as `active_seconds + human_wait_seconds`; the wall-clock targets
assume each of the two approvals is answered within ten minutes.

| Workflow | Target | Conditions |
|---|---:|---|
| Cold reference remix, best case | 2.5-3 hours | New source/reference, immediate approvals, no FAL generation |
| Normal fastline run | 3-5 hours | Two approval bundles, full final QA |
| Warm same-brand run | 60-90 minutes | Fingerprints, voice, BGM, and profile hit |
| Narration/BGM-only revision | 5-15 minutes | Video master remains unchanged |
| Caption/visual revision in P0 | 15-30 minutes | Full Remotion render may still be required |
| Scene-incremental revision in P1 | 5-15 minutes | Only after scene cache and layer guards pass |

The current project's recorded tool work was approximately nine minutes in
total, with individual full Remotion renders around 38-47 seconds. Therefore,
approval and rework reduction take priority over frame-count or scene-cache
optimization for this 30-second deliverable.

Before treating these targets as an SLA, run three cold and five warm benchmark
runs and record CPU model, core count, RAM, macOS version, Node, Remotion,
Chromium, FFmpeg, source count/bytes/duration, cache hit rate, active seconds,
human-wait seconds, and end-to-end seconds. Report median and slowest run. ETA
uses a rolling median of the last five matching operations; with fewer than
three observations it is marked `estimate_confidence: low`.

Benchmark pass rules use normalized wall time with two ten-minute approval
waits added to active execution:

- cold runs: median <= 4 hours and every run <= 5 hours;
- warm same-brand runs: median <= 75 minutes and every run <= 90 minutes;
- audio-only revisions: median <= 10 minutes and every run <= 15 minutes.

If a threshold fails, publish measured results as a benchmark report but do not
claim the corresponding SLA.

## 4. Proposed Data Flow

```text
reference/source files
        |
        v
media_index + reference_fingerprint (content-addressed)
        |
        +--> reference analysis
        +--> source media review
        |
        v
creative_lock bundle
  script + voice + BGM + captions + scene mapping + CTA
        |
        +--> TTS cache
        +--> BGM/mix cache
        +--> subtitle artifact
        +--> final_props/render_plan
        |
        v
sample render (proxy scale) --> sample gate
        |
        v
change_impact router
  mux_only | full_render | incremental (P1)
        |
        v
final render --> full QA --> Backlot report and delivery
```

## 5. P0 Architecture

### 5.0 Artifact ownership and validation

Create:

- `schemas/artifacts/media_index.schema.json`
- `schemas/artifacts/reference_fingerprint.schema.json`
- `schemas/artifacts/production_lock.schema.json`
- `schemas/artifacts/approval_bundle.schema.json`
- `schemas/artifacts/asset_plan.schema.json`
- `schemas/artifacts/change_impact.schema.json`
- `schemas/artifacts/render_plan.schema.json`
- `schemas/artifacts/final_props.schema.json`
- `schemas/artifacts/sample_report.schema.json`

Modify `schemas/artifacts/__init__.py` to register every name and modify
`lib/checkpoint.py::SUPPLEMENTARY_ARTIFACTS` so checkpoint validation cannot
silently skip them. Every artifact contains `version`, `project_id`,
`created_at`, `producer`, `input_hashes`, `semantic_sha256`, and
`artifact_sha256` and is written atomically under
`projects/<project-id>/artifacts/`.

Hashing uses RFC 8785 JSON Canonicalization Scheme semantics. `artifact_sha256`
hashes exact canonical JSON with only `artifact_sha256` omitted, so it protects
the stored record. `semantic_sha256` omits both hash fields plus volatile
`created_at`, run/event ids, and absolute project path; it represents the
approval-relevant meaning. Approval bundles carry both hashes: semantic changes
supersede approval, while exact-hash changes with equal semantic hash are
treated as regenerated provenance and still validated for integrity.

Add `lib.pipeline_loader.get_stage_produces()` and make checkpoint validation
require every manifest-declared `produces` artifact when a stage becomes
`awaiting_human` or `completed`; `CANONICAL_STAGE_ARTIFACTS` remains only a
legacy fallback. This makes `sample -> sample_report` and future custom stages
enforceable without another hard-coded stage map.

Canonical ownership is:

| Owner stage | Artifacts |
|---|---|
| research | `media_index`, `source_media_review`, `video_analysis_brief`, `reference_fingerprint` |
| creative-lock group | `proposal_packet`, `script`, `scene_plan`, `asset_plan`, `production_lock`, `approval_bundle` |
| sample | realized `asset_manifest`, `final_props`, `render_plan`, `sample_report` |
| edit | `edit_decisions`, `change_impact`; references approved props/plan hashes |
| compose | `render_report`, `final_review`, finalized `render_plan` |

The relevant stage checkpoint embeds the validated JSON artifact and its disk
path/hash. Resume logic reloads the registered schema, recomputes referenced
artifact hashes, and refuses reuse when provenance does not match. Add contract
tests proving all names validate and are visible to checkpoint and Backlot.

### 5.1 Media index and analysis cache

Create:

- `lib/media_index.py`
- `schemas/artifacts/media_index.schema.json`
- `tests/lib/test_media_index.py`
- `tests/lib/test_source_media_review_cache.py`

Modify:

- `lib/source_media_review.py`
- `tools/analysis/video_analyzer.py`
- `tools/analysis/scene_detect.py`
- `tools/analysis/frame_sampler.py`

`media_index.json` is written under
`projects/<project-id>/artifacts/` and contains one entry per media file:

```json
{
  "path": "inputs/source/video/product/clip.mp4",
  "media_type": "video",
  "fingerprint": {
    "content_sha256": "...",
    "size_bytes": 123,
    "mtime_ns": 123
  },
  "probe": {},
  "scenes": [],
  "representative_frames": [],
  "audio": {"has_track": false, "usable": false},
  "best_ranges": [],
  "quality_risks": [],
  "analysis_version": "media-review-v2"
}
```

Rules:

- `content_sha256` is the only file-identity value used in cache keys. Path,
  size, and mtime are fast hash-avoidance prechecks, never identity fields.
- A size/mtime match may reuse a previously verified SHA only when the same
  canonical path record exists; otherwise compute SHA-256 again.
- A touched or copied byte-identical file must hit the content cache. A changed
  file at the same path must miss even if its name is unchanged.
- A changed file cannot hit an old result merely because its path is unchanged.
- Frame output is isolated under a fingerprint-specific directory.
- `source_media_review` reuses the index and adds content observations; it does
  not infer content from filenames.
- `scene_detect`, frame extraction, audio probing, and motion summaries run in
  bounded parallel workers.
- Silent or missing audio tracks skip transcription rather than invoking a
  speech tool unnecessarily.
- Cache manifests are written atomically. Reuse verifies schema version,
  provenance, every output artifact digest, and ffprobe readability where
  applicable; sidecar existence alone is insufficient.

The cache key includes tool name, tool version, algorithm version, source
`content_sha256`, normalized parameters, and output format. Tests cover
same-content/new-mtime, same-path/changed-content, corrupt output, and analyzer
version invalidation.

`reference_fingerprint.json` is a P0 research artifact containing reference
content SHA-256, analyzer version, depth, canonical request, output digest, and
the extracted abstract structure. Unchanged references reuse deep tool output,
but the agent still reviews extracted frames and never reuses copyrighted
picture, audio, subtitles, logos, or music.

### 5.2 Common artifact cache

Create:

- `lib/artifact_cache.py`
- `tests/lib/test_artifact_cache.py`

The cache API is deliberately small:

```python
cache.lookup(key, expected_artifacts) -> CacheHit | CacheMiss
cache.store(key, artifacts, metadata) -> CacheRecord
cache.invalidate(key, reason)
```

It must provide file locking, atomic metadata writes, sidecar validation,
corrupt-entry eviction, and a `cache_hit`/`cache_miss` event. API keys,
provider signatures, and signed URLs are never cached.

Canonical manifests stay project-local. Reusable binary/object data lives in
`PROJECTS_DIR/.cache/artifacts/<key>/`; project artifacts reference it by hash
and use a hard link when supported, otherwise an atomic copy. Cache eviction
must never delete a project's canonical output.

`tools/base_tool.py` may expose common cache-key and event helpers, but it must
not automatically cache every tool invocation. Each tool opts in only when its
output is deterministic and its side effects are understood.

### 5.3 TTS and audio mixing

Modify:

- `tools/audio/tts_selector.py`
- `tools/audio/doubao_tts.py`
- `tools/audio/audio_mixer.py`
- `tools/subtitle/subtitle_gen.py`

The TTS key is not a hand-picked cross-provider field list. After selector
resolution, serialize the exact provider request payload with secrets removed
and defaults materialized, then hash:

```text
provider + endpoint + model/resource revision + provider tool version
canonical provider request payload
input type/language/instructions/style/stability/voice controls
output format/sample rate/timestamp/markdown-filter options
```

This covers Doubao and future providers whose controls differ. The canonical
payload is stored as redacted provenance beside the audio, never as an API key
or signed URL.

Before a Doubao call, the cache verifies that the audio is readable with
ffprobe and that the timestamp sidecar is present when requested. A partial or
corrupt result is a cache miss and is rebuilt. A hit returns `cache_hit=true`,
`reused_from`, and `saved_seconds`; the cost tracker reconciles the event as
zero provider spend without fabricating a new provider call.

The mixer key includes the content fingerprint of every track and all mix
parameters: ducking, target LUFS, target duration, track volumes, segment
boundaries, fades, and FFmpeg/tool version.

The dependency order is fixed:

```text
approved copy -> TTS -> actual audio duration -> subtitles -> scene timing
```

This prevents a late voice-speed change from cascading invisibly through the
timeline.

Tests prove invalidation for text, voice, rate, format, timestamp mode,
language, input type, instructions/style, provider/model revision, and damaged
timestamp sidecars.

### 5.4 Change-impact routing and mux-only output

Create:

- `lib/change_impact.py`
- `schemas/artifacts/change_impact.schema.json`
- `schemas/artifacts/render_plan.schema.json`
- `tests/tools/test_change_impact.py`
- `tests/tools/test_video_compose_mux_only.py`

Modify the `video_compose` input schema without changing its low-level
operations. High-level calls remain `operation: "render"` and add a required
`render_plan` object for fastline projects:

```json
{
  "operation": "render",
  "output_path": "projects/p/renders/final.mp4",
  "render_plan": {
    "version": "1.0",
    "mode": "sample|full|mux_only",
    "profile": "social_vertical_1080p30",
    "timeline_hash": "...",
    "visual_timeline_hash": "...",
    "video_master": {
      "path": "renders/.cache/video-master.mp4",
      "sha256": "...",
      "profile_hash": "...",
      "visual_timeline_hash": "..."
    },
    "audio": {"path": "assets/audio/final-mix.wav", "sha256": "..."},
    "sample": {
      "startFrame": 0,
      "endFrameExclusive": 360,
      "scale": 0.5,
      "qaMode": "quick"
    },
    "dirty_scene_ids": []
  }
}
```

`video_compose._render()` validates this plan and routes to Remotion or the
existing audio mux helper. Direct low-level `remotion_render` calls remain
available but do not receive fastline cache semantics.

The initial routing table is:

| Change | Route in P0 | Reason |
|---|---|---|
| Voice/BGM/volume only | mix + external audio mux | Video pixels are unchanged |
| TTS text changed | TTS + subtitles + full render | Timing and spoken content can change |
| Caption wording/style/花字 | Full render | Current composition owns the overlay |
| Clip in/out, crop, speed, transition | Full render | Scene pixels/timing change |
| CTA only | Full composition render | CTA is currently inside composition; partial scenes are P1 |
| Metadata/report only | No render | Artifact-only change |

The existing `_mux_external_audio()` path is the P0 low-risk accelerator. The
video master is rendered without a baked narration track where practical, and
the final audio is muxed once. `mux_only` is accepted only when the master hash,
visual timeline hash, duration, and profile hash match the current plan. The
profile-certified master must be H.264/yuv420p at 1080x1920 and 30fps. Mux uses
AAC 192kbps, 48kHz, stereo, replaces any previous audio stream, and then runs
ffprobe validation. A mismatch returns a structured `requires_full_render`
result; it never silently copies a nonconforming master.

Tests cover valid mux reuse, wrong timeline hash, wrong profile, nonconforming
pixel format/codec, 44.1kHz input audio, duration mismatch, and missing master.
P0 does not introduce unsafe frame stitching.

### 5.5 Single source of timeline truth

Modify:

- `projects/transparent-table-mat-remix-01/Root.tsx`
- `projects/transparent-table-mat-remix-01/Composition.tsx`
- `projects/transparent-table-mat-remix-01/artifacts/final_props.json`
- `schemas/artifacts/final_props.schema.json`
- `tests/tools/test_final_props_timeline.py`

The artifact becomes the only authoritative timeline. Each scene contains:

```json
{
  "scene_id": "n06",
  "fromFrame": 180,
  "toFrameExclusive": 249,
  "durationInFrames": 69,
  "source": "footage/scratch.mp4",
  "inSeconds": 0.4,
  "outSeconds": 2.7,
  "speed": 1.0,
  "cache_key": "..."
}
```

All ranges use half-open semantics `[fromFrame, toFrameExclusive)`, and
`durationInFrames` must equal the difference. Top-level
`durationInFrames` must equal the maximum scene end; captions and audio may not
extend beyond it.

For `playbackMode="normal"`, the validator also requires:

```text
abs(durationInFrames - round((outSeconds - inSeconds) * fps / speed)) <= 1
```

`loop` or `hold` behavior must be declared explicitly and has separate source
coverage rules; it cannot bypass the normal invariant accidentally.

`FinalRenderProps` receives `scenes[]`, captions, audio, fps, width, height, and
duration from the validated artifact. `Composition.tsx` maps `scenes[]` into
`Sequence` nodes; `Root.tsx` contains only fixture defaults for Studio and no
production scene list. `calculateFinalMetadata` derives duration, fps, width,
and height from props. Remove all duplicated 16-scene offsets and the literal
production duration from Root and Composition.

Tests mutate one boundary and the overall duration and prove both Sequence
placement and calculated metadata change. They also reject gaps when disallowed,
overlap, missing sources, duration disagreement, out-of-bounds captions, and
source-duration/speed disagreement beyond one frame, undeclared loop/hold, and
an unexpected production timing literal in the project components.

### 5.6 Content-addressed proxy media

Create:

- `tools/video/media_proxy.py`
- `tests/tools/test_media_proxy_cache.py`

The proxy tool writes a fingerprinted, ffprobe-validated proxy for a named
profile such as `remotion-social-v1`. Its key includes source SHA-256,
crop/aspect policy, width/height, codec, pixel format, and tool version. The
project artifact records the proxy path and source relationship. Existing local
proxies are checked before creating another copy, removing manual duplication
between project assets and Remotion `public/footage`.

### 5.7 Sample and runtime preflight

Create `lib/remotion_runtime.py` and
`tests/tools/test_remotion_runtime.py`. Update `make preflight` and
`tools/video/video_compose.py` to report:

- installed Node/Remotion version;
- the actual local Chrome/Chromium executable;
- FFmpeg version;
- composition id and props validation;
- font availability;
- staged media and audio duration checks.

Default local concurrency is `min(4, max(1, cpu_count // 2))` and is recorded
in the render report. The user may override it, but preflight must not infer a
missing Chromium installation merely because one configured path is absent.

The approved proposal selects a representative half-open sample window of
300-450 frames (10-15 seconds). `render_plan.sample` carries that window and a
scale of `0.5`. The adapter passes Remotion an inclusive CLI range of
`startFrame-(endFrameExclusive - 1)`, preserving original timeline frame
numbers, audio, and caption timing. Scale changes width/height only; fps remains
30. Output is isolated at `assets/sample/sample-<cache-key>.mp4`, and the key
includes final-props hash, window, scale, audio hash, runtime, and runtime
version.

After rendering, `final_qa.execute(mode="quick")` writes the registered
`sample_report` artifact. Tests verify dimensions, frame count, duration,
caption/audio offset, cache segregation, and that the sample consumes the same
props hash as the final plan. Final output remains 1080x1920. Existing local
Chromium locations are checked before any download is suggested.

## 6. P0 Fastline Workflow and Governance

### 6.1 Executable two-gate contract

Create:

- `pipeline_defs/cinematic-fast.yaml`
- `skills/meta/fastline.md`
- `skills/pipelines/cinematic-fast/` director wrappers for every declared stage
- `schemas/artifacts/approval_bundle.schema.json`
- `tests/contracts/test_cinematic_fast_pipeline.py`
- `tests/lib/test_checkpoint_approval_groups.py`

Modify:

- `schemas/pipelines/pipeline_manifest.schema.json`
- `lib/pipeline_loader.py`
- `lib/checkpoint.py`
- `schemas/checkpoints/checkpoint.schema.json`
- `skills/meta/checkpoint-protocol.md`
- `backlot/state.py`

The fast pipeline retains normal stages and registered artifacts:

```text
research -> proposal -> script -> scene_plan -> assets
         -> sample -> edit -> compose -> publish
```

`sample` is a real checkpoint stage, not an informational sub-stage. The
manifest declares:

```yaml
approval_groups:
  creative_lock:
    members: [proposal, script, scene_plan, assets]
    terminal_stage: assets
    required_artifacts:
      [proposal_packet, script, scene_plan, asset_plan, production_lock]

stages:
  - name: proposal
    approval_group: creative_lock
    human_approval_default: false
  - name: script
    approval_group: creative_lock
    human_approval_default: false
  - name: scene_plan
    approval_group: creative_lock
    human_approval_default: false
  - name: assets
    approval_group: creative_lock
    approval_group_terminal: true
    produces: [asset_plan, production_lock, approval_bundle]
    human_approval_default: true
  - name: sample
    required_artifacts_in:
      [proposal_packet, script, scene_plan, asset_plan, production_lock]
    produces: [asset_manifest, final_props, render_plan, sample_report]
    human_approval_default: true
```

Research, edit, compose, and local publish-package stages explicitly set
`human_approval_default:false`. External upload is not part of this manifest.
Therefore only the assets terminal and sample stage can enter
`awaiting_human` during local production.

The checkpoint schema adds optional `approval_group`, `approval_bundle_id`, and
`approval_bundle_version` fields. `approval_bundle.status` is one of
`awaiting_human`, `approved`, `rejected`, or `superseded`. Manifest validation
rejects a group with a missing member, multiple terminals, a terminal outside
the member list, or a non-terminal member that still declares its own human
gate.

The first gate is executable as follows:

1. Non-terminal group stages and the terminal assets-planning pass write plans
   and evidence only; no paid generation runs before approval. `asset_plan`
   records intended TTS/BGM/subtitle outputs without claiming files exist.
2. The terminal stage may enter `awaiting_human` only when every member
   checkpoint exists and all required artifact hashes validate.
3. The terminal checkpoint embeds `approval_bundle` with bundle id, version,
   member stages, terminal stage, artifact paths/hashes, status, and decision-log
   revision ids.
4. One user approval writes an approved bundle temp file, fsyncs and renames it,
   then atomically rewrites the terminal checkpoint as `completed` with
   `human_approved=true` and the exact bundle hash. A crash between the two
   renames leaves an unreferenced bundle that resume ignores; the checkpoint is
   the canonical transition record.
5. `_enforce_stage_prerequisites()` treats the group terminal as the approval
   evidence for the bundle; non-terminal members are never separate stops.
6. On resume, bundle hashes are recomputed. A mismatch marks the approved
   bundle `superseded`, archives it, reopens the terminal stage as
   `awaiting_human`, and prevents `sample` from advancing.
7. Rejection records `status=rejected` and leaves the terminal stage pending.
   A revised bundle increments `bundle_version`; history is append-only.

After creative approval, the real `sample` stage generates/reuses the approved
TTS, BGM, subtitle, and proxy assets, writes an `asset_manifest` containing only
files that now exist, compiles actual audio timing into `final_props` and
`render_plan`, and renders the preview. The second gate is this sample
stage. After sample approval, edit,
compose, full QA, backup, and local publish packaging continue without another
creative stop. Actual upload to an external platform remains outside fastline
and always requires separate explicit authority.

The fast director wrappers reuse cinematic creative rules but replace their
per-stage Gate Reminder with manifest-driven group behavior. This avoids
silently contradicting the existing cinematic director instructions.

The edit stage may reference the approved `final_props` and `render_plan` hashes
but may not mutate them silently. Any visual or timing change after sample
approval creates a new change-impact record and reopens the sample gate; a
major locked creative change also reopens `creative_lock`.

### 6.2 Production lock and decision revisions

Create:

- `lib/production_lock.py`
- `schemas/artifacts/production_lock.schema.json`
- `tests/lib/test_production_lock.py`

`production_lock.json` records hashes and selected values for script,
narration, provider/resource/voice/rate, BGM and mix profile, font, caption
profile and emphasis rules, CTA, platform, resolution, fps, duration, render
runtime, and composition mode.

The lock is written atomically with the creative bundle. Resume loads and
reconciles it before any tool call. A major change appends a new decision-log
entry with a unique `decision_id` while reusing the exact same `(category,
subject)` pair; the superseded choice is placed in `options_considered` and
`rejected_because` explains the revision. It also writes `change_impact.json`
and supersedes the creative bundle when reapproval is required.

Provider, voice, CTA, runtime, composition mode, and narration-content changes
reopen `creative_lock`. Pure gain/LUFS adjustments remain within the approved
audio path, are logged, and route through mix/mux without reopening the bundle.

## 7. P1 Reusable Profiles and Caption Components

### 7.1 Brand profile

Create `brand_profile.schema.json`. `brand_profile.json` is an optional,
user-approved input that stores voice/resource, speech rate, BGM family, font,
caption profile, emphasis rules, CTA pattern, and platform defaults. It never
overrides an approved production lock silently; differences create a new
decision and change-impact record.

### 7.2 Caption component productization

Create `remotion-composer/src/components/SafeCaptionTrack.tsx` and its tests.
Extend `CaptionOverlay.tsx` with:

```ts
type SafeCaptionProps = {
  safeZoneProfile?: "douyin_9_16" | "wechat_9_16" | "xiaohongshu_9_16";
  fontMin?: number;
  fontMax?: number;
  maxWidth?: number;
  stripTrailingPunctuation?: boolean;
  emphasisRules?: Array<{term: string; color: string; effect: string}>;
};
```

Version 1 of all three 1080x1920 platform profiles uses the same conservative
safe rectangle until platform-specific measurements justify a change:

```text
left >= 72px, right >= 72px, top >= 120px, bottom >= 300px
font 44-52px, maximum two lines, line-height 1.24, text width <= 864px
```

The default follows the validated transparent-mat treatment: Songti-family
font, deterministic CJK width fitting, no trailing punctuation, and restrained
keyword 花字. The component must not rely on browser font measurement that
changes between render machines. QA fails when any computed caption/emphasis
bounding box crosses the selected safe rectangle.

`edit_decisions` and `final_review` record whether captions are a Remotion
overlay, FFmpeg burn, or subtitle stream. QA must use that declaration rather
than assuming that the presence of a source subtitle file proves that pixels
were rendered.

### 7.3 Optional scene-level incremental rendering

P1 may add `render_plan.mode="incremental"` only after P0 benchmarks show that
full composition render time is material. Scene cache keys include source and
component code hashes, final-props scene data, crop/trim/speed, captions and
overlays intersecting the scene, transition configuration, runtime versions,
and output profile. Dirty ranges expand by transition and premount guard frames.
The implementation renders those ranges, validates them, and assembles a
profile-certified video master before one final audio mux. Any global style,
font, runtime, fps, resolution, or timeline-structure change falls back to a
full render.

## 8. QA Design

Create `tools/video/final_qa.py` as the single canonical QA implementation and
tests. Refactor `tools/video/video_compose.py::_run_final_review()` into a thin
adapter calling:

```python
final_qa.execute({
    "mode": "quick|full",
    "input_path": "...",
    "expected_profile": {...},
    "caption_spec": {...},
    "allowed_black_ranges": [],
    "allowed_freeze_ranges": [],
    "output_path": "..."
})
```

`final_review.schema.json` migrates compatibly: version `1.0` remains readable;
new fastline writes version `2.0`. Existing required top-level fields
`version`, `output_path`, `status`, and `checks` remain. Add these named objects
under `checks` so `additionalProperties:false` still protects the contract:

```json
{
  "version": "2.0",
  "output_path": "renders/final.mp4",
  "status": "pass",
  "checks": {
    "technical_probe": {},
    "visual_spotcheck": {},
    "audio_spotcheck": {},
    "promise_preservation": {},
    "subtitle_check": {},
    "media_integrity": {
      "decode_passed": true,
      "black_ranges": [],
      "freeze_ranges": []
    },
    "audio_loudness": {
      "integrated_lufs": -14.0,
      "lra_lu": 6.0,
      "true_peak_dbtp": -2.3
    },
    "caption_render": {
      "mode": "remotion_overlay",
      "source": "assets/subtitles.remotion.json",
      "safe_zone_profile": "douyin_9_16",
      "safe_zone_passed": true
    }
  },
  "metadata": {"review_mode": "full", "qa_policy_version": "social-v1"}
}
```

Schema conditionals require the three new check objects when version is `2.0`;
version `1.0` fixtures continue validating unchanged.

Quick mode performs ffprobe, decode smoke, representative frames, audio stream
presence, caption-source/timeline consistency, and output dimensions/duration.
It writes `sample_report`, not the final delivery approval.

Full mode performs full-stream decode, `blackdetect`, `freezedetect`, frame-hash
duplicate review, `ebur128`/`loudnorm` measurement, subtitle geometry and cue
coverage, transcript comparison when narration exists, and runtime-lock
comparison.

The default `social-v1` failure thresholds are:

| Check | Pass threshold |
|---|---|
| Duration | absolute difference <= one frame |
| Frame rate | absolute difference <= 0.01fps |
| Video | exactly 1080x1920, H.264, yuv420p |
| Audio | AAC, 48kHz, stereo |
| Black | no unapproved interval >= 0.15s |
| Freeze | no unapproved interval >= 1.00s |
| Integrated loudness | -15.0 to -13.0 LUFS |
| True peak | <= -1.0 dBTP |
| LRA | 2-12 LU |
| Caption geometry | every box inside the selected versioned safe rectangle |
| Caption timing | cue count matches source; final cue ends within one frame |

`social-v1` pins FFmpeg filters rather than relying on defaults:

```text
blackdetect=d=0.15:pix_th=0.10:pic_th=0.98
freezedetect=n=-50dB:d=1.00
```

The review stores these values and the FFmpeg version in metadata. A policy or
FFmpeg major-version change invalidates cached QA and reruns the detector test
fixtures before release.

Intentional black/freeze ranges must be declared in `render_plan` and are
compared by interval overlap; undeclared ranges fail. Final QA remains mandatory
even when every upstream artifact is a cache hit.

## 9. Backlot Observability

Modify:

- `backlot/state.py`
- `backlot/server.py`
- `backlot/ui/board.js`
- `tests/backlot/test_fastline_state.py`

The board remains read-only for approvals in P0/P1. It displays:

- current fastline gate, bundle version/status, member artifacts, and hash diff;
- locked decisions and their hashes;
- cache hit/miss counts;
- reused artifact path and saved seconds;
- `render_mode`, dirty scenes, and ETA;
- current blocker and next required human action.

Events extend with `cache_hit`, `cache_key`, `reused_from`, `dirty_scene_ids`,
`eta_seconds`, and `estimate_confidence`. A state cache may reduce repeated artifact parsing, but it
must be invalidated whenever watched artifacts or `events.jsonl` change.

Backlot derives approval state from the terminal checkpoint plus the registered
`approval_bundle`; it does not invent a second approval store. A superseded
bundle is visibly blocked and cannot be presented as approved.

## 10. Test Strategy

Add or update tests for:

- artifact registry, schema validation, checkpoint ownership, and hash replay;
- media fingerprint changes and stale-frame isolation;
- cache hit, miss, corruption, and atomic recovery;
- TTS canonical provider-payload collisions and cost reconciliation;
- audio mixer key completeness and no-FFmpeg cache hits;
- render-plan input schema, master provenance, and mux profile rejection;
- sample frame window, scale, audio/caption offset, and quick-QA output;
- half-open props timeline validation and Root/Composition metadata consumption;
- caption punctuation, CJK fitting, safe zones, and style cache invalidation;
- version 1/2 final-review schema compatibility and threshold failures;
- runtime swap governance;
- approval-group terminal, approve/reject/supersede/resume/history behavior;
- Backlot state derivation and cache-hit activity rendering;
- transparent-mat end-to-end regression at 1080x1920, 30fps, 30 seconds.

Recommended existing regression groups include the audio mixer tests,
`test_remotion_audio_mux.py`, subtitle timestamp tests, checkpoint gate tests,
Backlot state/server tests, and pipeline contract tests.

## 11. Rollout Plan

### Phase P0-A: Cache and media evidence

Register new artifacts; implement media index, artifact cache, provider payload
keys, mixer keys, and source review reuse. Run existing and new cache tests.

### Phase P0-B: Deterministic edit and audio reuse

Implement canonical props, change-impact artifact, mux-only path, runtime
preflight, proxy media, and render-plan/sample contracts. Validate that
audio-only changes do not invoke Remotion and nonconforming masters are rejected.

### Phase P0-C: QA and fastline profile

Implement schema-backed approval groups, the real sample stage, full QA v2,
quick/full modes, fast director wrappers, and `cinematic-fast.yaml`. Run
approve/reject/resume tests before one transparent-mat benchmark production.

### Phase P1: Backlot and reusable visual components

Add cache/ETA/diff presentation, brand profiles, `SafeCaptionTrack`,
and contract tests. Only after P0 measurements justify it, implement scene-level
incremental rendering.

## 12. Acceptance Criteria

The upgrade is accepted when:

1. Byte-identical media with a new mtime hits; changed bytes at the same path
   miss; corrupt cached outputs rebuild.
2. Identical resolved Doubao requests produce valid audio/timestamps with zero
   new provider spend; any output-affecting provider field invalidates the key.
3. An audio-only change uses `mux_only`, launches no Remotion render, and still
   produces H.264/yuv420p 1080x1920 30fps plus AAC 48kHz stereo output.
4. An end-to-end fast run enters `awaiting_human` exactly twice: creative-lock
   terminal and sample. Approve, reject, supersede, history, and resume tests pass.
5. Sample output is 540x960 at 30fps, lasts 300-450 frames, shares the final
   props hash/window semantics, and passes quick QA.
6. Mutating `final_props` changes Sequence placement and metadata; no production
   scene timing or 900-frame duration remains duplicated in Root/Composition,
   and normal source-duration/speed math stays within one frame.
7. Final QA v2 passes every `social-v1` threshold, including duration within one
   frame, no undeclared black >=0.15s or freeze >=1.0s, -15 to -13 LUFS, true
   peak <=-1dBTP, and caption boxes inside the versioned safe rectangle.
8. Backlot shows bundle status/hash diffs, cache reuse, affected scope, ETA, and
   estimate confidence from canonical artifacts/events.
9. No paid generation, provider/model change, runtime change, or composition-mode
   change occurs without an append-only decision revision and required approval.
10. Three cold and five warm benchmark runs produce a report; the 3-5 hour SLA
    is adopted only if the measured environment meets it.

## 13. Deferred P1 Decisions

- Whether measured platform chrome justifies separate safe-zone profiles after
  conservative `social-v1` ships.
- Whether scene-level Remotion rendering is justified by P0 benchmark data or
  should remain out of scope for short videos.
- Whether cache eviction needs a size-based LRU after real cross-project usage.

Implementation must not begin until these choices and this document are
approved. The repository currently has no usable Git metadata, so the document
can be reviewed and used locally, but it cannot be committed until Git history
is restored.

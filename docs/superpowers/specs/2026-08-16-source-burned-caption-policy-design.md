# Source-Burned Caption Policy Design

## Goal

Distinguish user-owned burned-in captions from reference-video captions and
generated overlays. Preserve approved source copy where possible, prevent
duplicate messaging, and block unsupported claims without covering large parts
of the footage.

The first migration target is `table-mat-mix-v4`. Its current sample stays at
the sample approval gate; narration, C1, Remotion, and atelier remain locked.

## Policy

Ownership does not imply claim approval. Every burned-in source caption must be
reviewed for rights, copy, and claims before it can be retained.

```yaml
source_subtitle_policy:
  owned_burned_subtitles: review_required
  reference_burned_subtitles: forbidden
  duplicate_overlay: forbidden
  unsupported_claims: reject_or_local_replace
```

Each scene declares per-caption treatments and separate generated layers:

```yaml
caption_policy_version: "1.0"
caption_treatments:
  - caption_id: owned-video-01-caption-03
    action: retain | crop | mask | replace
    review: approved | pending | rejected
    interval: {start_seconds: 3.8, end_seconds: 5.0}
    reason: approved product label
    replacement_overlay_id: null
overlay_layers:
  - overlay_id: evidence-contact
    source: generated_overlay | narration_caption
    text: 先隔一层
    start_seconds: 10.4
    end_seconds: 14.2
    review: approved | pending | rejected
    approval_ref: artifacts/caption-copy-review.json#evidence-contact
```

Each inventory entry also has a stable `caption_id`, `media_id`, `origin`
(`owned` or `reference`), half-open `start_seconds`/`end_seconds`, and a
normalized region in `x/y/width/height` percentages of the source frame. A
scene must reference the exact inventory IDs it uses. Rights, copy, and claim
statuses are enums (`approved`, `pending`, `rejected`) and carry evidence
references, reviewer identity, review timestamp, and approval authority.
Each `files[]` item owns a project-unique `media_id`; every `caption_id` is
project-unique and resolves to exactly one owning file. Percent values use
`0..100`, with `x + width <= 100` and `y + height <= 100`. Custom validation
enforces ID uniqueness and reference integrity. Aggregate `review=approved`
means rights, copy, and claim statuses are all `approved`; any rejected member
makes the aggregate `rejected`, otherwise it is `pending`.

The invariants are machine-checkable: `retain` requires `approved`; rejected
copy cannot be retained; and `crop`/`mask`/`replace` require a source reference,
a reason, and an exact half-open interval. A treatment may reference only
`origin=owned`, and its interval must be contained by both the inventory entry
and the scene. `replace` requires a non-null `replacement_overlay_id` resolving
to an approved layer with `approval_ref`; every other action forbids that field.
`duplicate_overlay` applies to retained approved copy
after Unicode/punctuation/whitespace normalization, in the same language and
overlapping time range. An overlay replacing rejected copy is not a duplicate,
but its replacement text must itself be approved.

`mask` means a localized treatment around rejected copy, not a default
full-width top or bottom band. A generated overlay may replace rejected source
copy or add missing meaning, but it may not repeat approved burned-in copy.

## Versioning

Do not mutate catalog version `1.0.0`. Publish `ecommerce-viral-remix 1.0.1`,
update the catalog index and digest, and leave existing snapshots reproducible.
The current project records a project-scoped caption-policy revision; it does
not silently replace its frozen Skill snapshot.

## Contract Changes

1. Add the policy to the `1.0.1` Skill and transparent-table-mat example.
2. Extend `source_media_review.files[]` with a structured source-caption
   inventory: stable IDs, provenance, text, half-open time range, normalized
   region, rights/copy/claim status enums, evidence, reviewer, authority,
   timestamp, and review notes.
3. Extend `scene_plan.scenes[]` with `caption_policy_version`,
   `caption_treatments[]`, `overlay_layers[]`, inventory references, treatment
   reasons, and conditional invariants.
4. Add fastline scene/compose director rules requiring source-caption mapping,
   duplicate prevention, and localized treatment reasons.
5. Extend `final_props` with the resolved caption treatments and policy revision
   reference. Extend `sample_report` with the durable QA report linkage and
   caption-policy verdict.
6. Register `caption_policy_revision` in `schemas/artifacts/__init__.py`,
   `lib/checkpoint.py`, and the cinematic-fast manifest. Sample produces and
   checkpoints it; edit and compose require its semantic hash so the final
   route cannot ignore the revision.
7. Add schema contract tests proving valid enums pass and unknown values fail.

Legacy artifacts may omit the new fields. The discriminator is a top-level
`caption_policy_version: "1.0"` property on each `source_media_review`,
`scene_plan`, `final_props`, and `sample_report` artifact. Schema conditionals
then require complete inventories, treatments, and QA. Artifact
schema `$id` and `version` remain at `1.0` for additive optional fields; a
breaking change requires a new schema ID/version and an explicit migration.
Register any project caption-policy revision as a contract-v2 artifact rather
than relying on untracked metadata.

For projects whose frozen Skill snapshot resolves
`ecommerce-viral-remix >= 1.0.1`, checkpoint cross-artifact validation requires
the discriminator on these newly written artifacts. Frozen `1.0.0` projects
remain readable; the current project adopts the 1.0 policy explicitly through
its `caption_policy_revision`, which triggers the same conditional validation.

## Current Project Revision

Treat the user's feedback as a sample-stage revision. Do not advance to edit or
compose.

- `clean`: retain reviewed burned-in source copy and remove the duplicate
  atelier evidence caption.
- `contact`: remove the large bands and use the deterministic `crop` treatment:
  reframe the approved intervals `july16:[3.8,5.0)` and
  `transparent:[7.8,8.9)` with a top-anchored 1.4x crop so the lower rejected
  phrase “防刮耐磨的材质” leaves the frame; retain the knife, tabletop, and
  contact line. The visible source rectangle is
  `x=14.2857%, y=0%, width=71.4286%, height=71.4286%`, mapped to the full
  540x960 output using center-x/top-y anchoring. `july16` source frames
  `[114,150)` map to output frames `[126,183)` at playback rate `0.63`;
  `transparent` source frames `[234,267)` map to `[183,240)` at `0.58`.
  Remotion rounds sampled source frames down. The rejected source region must
  be entirely below the visible rectangle; the knife/contact line stays within
  output `x=10%-90%, y=25%-70%`. No `先隔一层` overlay is rendered in this
  crop-only revision.
- `edge`: retain reviewed product/decorative source copy, remove the generated
  evidence caption, and keep the bespoke ice-blue edge sweep.

Record the sample-specific mapping, inventory IDs, policy revision, and hashes in
`final_props` and `sample_report`; these fields are required by their schemas.
Do not overwrite approved upstream artifacts. For a caption-only change, create
a registered contract-v2 `caption_policy_revision` artifact containing the
approved production-lock hash, exact delta, user authorization evidence,
decision revision ID, and evaluated change impact. Keep the approved creative
bundle and its canonical production lock byte-stable. One operator transaction
stages the policy revision, decision log, revised sample artifacts, and sample
checkpoint atomically. If the evaluated delta contains a creative token rather
than only caption/crop treatment, supersede the bundle and reopen creative lock.
A caption-only revision reopens the sample gate and requires a sample rerender.
`full_render` describes the eventual post-sample final route, not permission to
skip the sample gate; edit/compose remain blocked until sample approval.

`caption_policy_revision` is an object with `additionalProperties: false` and
these required fields:

```yaml
version: "1.0"
project_id: string
created_at: RFC3339 date-time
producer: string
input_hashes: {production_lock: sha256, scene_plan: sha256}
semantic_sha256: sha256
artifact_sha256: sha256
revision_id: non-empty string
revision_version: integer >= 1
base_production_lock_artifact_sha256: sha256
caption_treatments: [CaptionTreatment]
authorization:
  source: user_message | approval_record
  actor: string
  timestamp: RFC3339 date-time
  evidence_ref: string
decision_revision_id: non-empty string
change_impact:
  render_route: no_render | mux_only | full_render
  reopen_creative: boolean
  reopen_sample: boolean
  changed_fields: [unique non-empty string]
status: approved_for_sample_revision
```

`CaptionTreatment` uses the exact scene treatment schema and invariants above.
Every SHA-256 field matches `^[a-f0-9]{64}$`; arrays and nested objects also use
`additionalProperties: false`. The sample checkpoint must contain the full v2
envelope. `final_props.caption_policy_revision_ref` is the full reference
`{name, path, semantic_sha256, artifact_sha256}`, not a bare hash.

The manifest adds `caption_policy_revision` to `sample.produces`, to the sample
checkpoint, and to `edit.required_artifacts_in` and
`compose.required_artifacts_in`. Edit and compose validate that their reference
hashes equal the sample checkpoint envelope before proceeding.

Use one `ProjectCommitStore.transaction(..., expected_generation=<current>)`.
The generation stages `artifacts/caption_policy_revision.json`,
`artifacts/decision_log.json`, `artifacts/final_props.json`,
`artifacts/render_plan.json`, `artifacts/sample_report.json`, the revised MP4,
and `checkpoint_sample.json`. A stale base generation aborts the whole commit.

## QA

For the current sample:

- inspect at least four frames plus the complete rejected-caption interval;
  the sample window must contain that interval, and the report records the
  frame list and reviewer evidence;
- confirm no full-width masking bands remain;
- confirm no rejected claim is visible;
- confirm no generated overlay is a normalized-exact duplicate of retained
  source copy. Normalization is Unicode NFKC, lowercase, punctuation removal,
  and whitespace collapse; broader semantic similarity is an advisory human
  review, not a blocking automated assertion;
- run quick `final_qa`, verify 540x960, 30 fps, H.264/AAC, full decode, and audio;
- require structured `final_qa` linkage and assertions for codec, audio,
  decode, dimensions, FPS, and frame evidence. A localized mask has a
  measurable area bound of at most 20% of frame area; a crop must move the
  rejected region fully outside the output while preserving documented
  subject/safe-zone bounds;
- store `sample_report.qa.final_qa` as
  `{path, sha256, status, video_codec, audio_codec, audio_present, decode_ok,
  width, height, fps, frame_evidence[]}`. Pass requires `status=pass`, H.264,
  AAC, audio present, full decode, 540x960, and 30 fps. Frame evidence includes
  output frames 126 and 239, every fifth frame in `[126,240)`, the frame path,
  reviewer, timestamp, and `rejected_glyphs_visible=false`. Crop geometry must
  also prove the rejected inventory region lies outside the visible rectangle;
- store `sample_report.qa.caption_policy_verdict` as
  `{reference_origin_forbidden_pass, treatment_resolution_pass,
  crop_geometry_pass, rejected_copy_visibility_pass,
  normalized_duplicate_pass, evidence_refs[]}`. The referenced QA report file
  must exist, and `final_qa.sha256` hashes its exact bytes. Every verdict flag
  and every blocking `final_qa` assertion must pass before
  `sample_report.status=pass`;
- checkpoint `sample` as `awaiting_human` and stop.

Longer term, duplicate detection can compare the declared source-caption
inventory with generated overlay text. OCR is optional evidence, not a
prerequisite for the first contract version.

## Tests

Use RED-GREEN coverage for:

- source-caption inventory schema acceptance and enum rejection;
- scene caption-source fields and invalid combinations;
- catalog `1.0.1` digest/version resolution;
- immutable byte/digest regression for catalog `1.0.0` and resolution of an
  existing frozen `1.0.0` project snapshot;
- sample composition behavior: no default full-frame guard, rejected glyphs
  absent, retained source copy not duplicated, and the selected per-scene
  treatment rendered;
- render smoke test and visual frame review for the revised sample.

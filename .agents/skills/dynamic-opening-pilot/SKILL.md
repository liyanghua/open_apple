---
name: dynamic-opening-pilot
description: Execute an already approved, paid first article for a three-second product-video opening with generated moving footage. Use for opening-pilot production and review, not for approving a full film or releasing a batch.
---

# Dynamic opening first article

Follow the selected pipeline and its stage directors. This skill supplies the
extra checks for an approved moving opening; it does not choose a provider,
model, product claim, or creative concept in place of the approved lock.

## Fixed work before creative choices

1. Read the SKU fact snapshot, approval, production lock and source-image hashes.
   Locate approved reusable footage before requesting a new paid source.
2. Build one generation input per approved slot. Pin the exact tool/model,
   aspect ratio, source duration, resolution, audio mode, reference files,
   idempotency key, reservation and task journal from the lock. Run the tool's
   dry-run, then run `scripts/validate_dynamic_hook_pilot.py --phase gate`
   on a project-relative packet of immutable refs. Do not submit when either fails or the approved count is
   exhausted. Unknown remote status is queried by task/attempt ID first.
3. After each source returns, save the result and actual usage. A successful
   but rejected source still has cost. Probe and watch the source for actual
   towel motion, product identity, texture and frame stability. Generated
   imagery may illustrate a use concern; it does not prove a performance claim.
4. Compose the approved opening window as moving footage with the existing
   brand profile, real TTS timing, captions and approved music. Keep the brand
   layer continuous across a cut. The current towel route uses a four-second
   generated source and a 90-frame, 30-fps preview; other values require their
   own lock. Reused footage must retain its source hash and selected interval.
5. Run the actual render through technical validation, bind the raw status and
   render SHA, and run the same validator with `--phase preview`.
   Register a canonical `opening.scope=preview` record and submit it through
   `ReviewService.create_production_review`. The preview review is separate
   from complete-film QA, final approval and campaign work counting. Preserve
   `not_run`/`revise` and unknown settlement as such.

The validator packet has `approval_ref`, `lock_ref`, and `items`. Before payment,
each item needs `slot_id` and `generation_inputs_ref`. For preview validation,
add `generation_result_ref`, `source_ref`, `preview_props_ref`,
`render_inputs_ref`, `preview_ref`, `render_result_ref`, and `technical_ref`.
Every ref is a project-relative `{path, sha256}` pair. Invoke the script with
`--project-dir <project> --packet <project-relative packet> --phase gate|preview`.

## Agent decisions after those gates

Choose the first visual event, framing, action verb, usable source interval and
cut point from the approved facts and actual source. For each decision record
why the visible action supports the hook, and call out weak or misleading
expression for human review. The agent may select a better approved asset or
request a local edit within the locked budget; changing provider/model,
claim or paid-task scope requires a new lock. Human preview approval binds only
the exact three-second render and does not release later full variants.

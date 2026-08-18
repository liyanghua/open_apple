# Scene Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/scene-director.md` and
`skills/meta/fastline.md` before acting. Map every beat to source footage with
half-open in/out frames, safe caption zones, crop and speed decisions. Keep
the scene plan deterministic and do not create an independent approval stop;
the `creative_lock` bundle covers it at `assets`.

Every source mapping must be stored in `metadata.source_mapping[]`, keyed to the
canonical scene and owned source interval. Each mapped scene must also have a
non-empty canonical `scenes[].shot_intent`. Record every mapping in this shape:

```yaml
scene_id: "scene identifier"
reference_evidence:
  mode: "direct_segment | structural_only | none"
  reference_scene_id: "reference-1"  # direct_segment only
  reference_interval:                # direct_segment only
    start_seconds: 0
    end_seconds_exclusive: 2
  mechanism: "reference mechanism used by this shot"
  rationale: "why that mechanism serves the shot intent"
source_path: "path under the project's owned source set"
source_interval: {start_seconds: 0, end_seconds_exclusive: 2}
timeline_interval: {start_seconds: 0, end_seconds_exclusive: 2}
reference_basis: "reference pattern or structural observation"
source_fit: "why this owned source interval fits the beat"
mapping_reason: "how the source fit serves the shot intent"
originality_note: "how the treatment remains original"
```

Accept a mapping only when all four fields explain the reference understanding,
the fit of the project's own source footage, and the intended role of the shot.
Use `direct_segment` only when `reference_scene_id` and `reference_interval`
resolve to an analyzed reference scene. Use `structural_only` when the mapping
borrows an abstract mechanism without claiming a direct clip relationship; it
must not carry a reference interval. Use `none` when no reliable reference
evidence exists. Never infer a direct mapping from scene order alone.
Set `metadata.reference_media_usage: analysis_only`. Reference media is
analysis-only evidence: every `source_path` must resolve to the project's owned
source set, never a reference path, and reference media must never be copied into
assets or appear in the final edit or render.


Caption policy 1.0.1: every source caption must declare origin, review, interval, and treatment (`retain`, `crop`, `mask`, or `replace`). Retain requires approved rights/copy/claim review. Reference captions are forbidden. Record `caption_source`, `source_caption_action`, and `source_caption_review` per shot; localized crop/mask reasons and safe-zone geometry are mandatory.

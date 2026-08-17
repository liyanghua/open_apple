# Scene Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/scene-director.md` and
`skills/meta/fastline.md` before acting. Map every beat to source footage with
half-open in/out frames, safe caption zones, crop and speed decisions. Keep
the scene plan deterministic and do not create an independent approval stop;
the `creative_lock` bundle covers it at `assets`.



Caption policy 1.0.1: every source caption must declare origin, review, interval, and treatment (`retain`, `crop`, `mask`, or `replace`). Retain requires approved rights/copy/claim review. Reference captions are forbidden. Record `caption_source`, `source_caption_action`, and `source_caption_review` per shot; localized crop/mask reasons and safe-zone geometry are mandatory.

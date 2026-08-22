# Research Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/research-director.md` and
`skills/meta/fastline.md` before acting. Run the declared reference analyzers,
inspect every source clip, lock the built-in `ecommerce-storyboard-cn@1.0`
analysis template, and write the canonical `research_brief`,
`video_analysis_brief`, `source_media_review`, `media_index`,
`reference_fingerprint@2.0`, `research_breakdown`, `reference_source_matrix`,
`research_synthesis` and `research_scorecard`. Keep reference media
analysis-only and stop after the evidence checkpoint; no creative approval is
needed here.

The user-facing summary must use "分镜拆解", "参考片的拍法和节奏",
"参考镜头 × 我的素材", "可选方向" and "研究检查结果". Keep raw
observation separate from industry reminders and project decisions. Every
matrix row must have a source interval, evidence, confidence and a resolution
(`pending`, `accept`, `replace_source`, `bridge`, `rewrite`, or `omit`).

The v2 fingerprint must include shot patterns, beat patterns, whole-video
structure and the continuity contract. Apply the reviewed `short-video@1.0`
and `ecommerce-proof@1.0` reminder packs, but show them as "行业提醒" and never
overwrite observed facts or user decisions.

Use `lib.events.emit_run_event` for the queued and terminal event of every
Research orchestration operation, and `lib.events.emit_heartbeat` every 5-10
seconds while a semantic operation is still running. Use the operation names
`profile_projection`, `fingerprint_synthesis`, `source_matching`,
`semantic_synthesis`, `research_scorecard`, and `research_commit`; report
matching progress with `unit.kind="source_match"` and
`wait_reason="orchestrating"`. A terminal event records active local work in
`machine_ms` and any approval wait in `approval_wait_ms`. No orchestration step
may remain silent for more than 30 seconds.

Commit Research completion as one `ProjectCommitStore.transaction`. Within that
transaction stage all 9 immutable Research artifacts, every representative frame
required by their `evidence_refs` via `sink.stage_bytes`, and
`checkpoint_research.json` through the same sink. Validate the checkpoint against
the staged view before the transaction exits; do not write these files directly
to the project directory. A failure must be recoverable by the commit store;
after recovery, no partial Research bundle may remain visible.

## caption_style_fingerprint (P1-1)

Build `caption_style_fingerprint` (schema `schemas/artifacts/caption_style_fingerprint.schema.json`, builder `lib/caption_style.py`) from `research_breakdown` overlay observations. Reference without caption text → `applicability: not_applicable`; with captions → `needs_review` until a human confirms font family / size hierarchy / weight / stroke (automated part only seeds overlay samples, evidence frames and effect treatment). Never copy reference font files or caption assets — Remotion renders from this spec with open-source approximations.

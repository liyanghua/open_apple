# Sample Director - Cinematic Fastline

There is no same-named base director. Before acting, read the complete
`skills/pipelines/cinematic/asset-director.md`,
`skills/pipelines/cinematic/compose-director.md` and
`skills/meta/fastline.md`. After the creative bundle is approved, materialize
or generate approved TTS/BGM/subtitle/proxy assets, compile `final_props` and
`render_plan`, render a 10-15 second sample through `video_compose`, and run
quick `final_qa`. Also build `sample_execution_trace` from the approved
`shot_execution_plan` and realized `final_props`, showing which locked shots
are included, partial, new, or outside the sample window. Pause for sample
approval; approval covers both the sample video and this execution trace. Do
not advance to edit or final compose before that approval. The operator must
also complete the five effect checks: creative direction, hook, proof clarity,
pacing/cuts, and caption/visual readability. Only five ``pass`` decisions may
advance the pipeline; ``adjust`` routes to edit and ``redirect`` reopens the
creative direction gate.

## evaluation_report (sample scope) — L1a contract

After quick `final_qa` passes, run `technical_validator` on the sample render
with `scope: "sample"` and produce `evaluation_report` (schema:
`schemas/artifacts/evaluation_report.schema.json`). Inputs come from the
approved lock: `expected_duration_s` from the `render_plan` sample window,
`expected_facts` (SKU/price/params) from the script/shot_execution_plan fact
fields when present, `text_sources` from captions and narration, and
`execution_diff_ref` pointing at `sample_execution_trace`. A fatal L1a failure
in the sample must be surfaced to the user before sample approval; fixable
failures become `repair_targets` and do not block the five effect checks.

## L3 评分契约（video_judge，required_tools）

`video_judge` 是 sample/compose 的 `required_tools`（`pipeline_defs/
cinematic-fast.yaml`）。样片通过 `final_qa` + `technical_validator` 后运行
`video_judge`（advisory 用 `rubric_version: "l3-v1.0"`），把其
`dimensions` 写入 `evaluation_report.creative_advisory`。规则：

- judge 是 fail-closed：缺维/非法分数直接失败并重试，绝不钳制分数；
- judge 不可用（无 `DASHSCOPE_API_KEY`）→ `creative_advisory.scored=false`，
  不得宣称自动达标；optimization 自动循环只能跑 shadow mode；
- Autoresearch 优化门禁用 `rubric_version: "ecommerce-remix-v1.0"`，其分数
  经 `lib.optimization_scoring.aggregate_optimization_scores` 聚合后写入
  `evaluation_report.optimization` 区块（`optimization_policy.enabled=false`
  时该区块为 null，保持人工 review 优先）。

## Execution diff + audio contract (P0-2 / P0-3)

- Build `sample_execution_trace` with the full input set (script,
  final_props, creative_control_plan, research_breakdown) so it carries the
  three diffs: audio (口播/BGM/原声), caption (字幕数量与时间轴漂移) and
  creative rules (自然语言规则文本 + 绑定状态，绝不展示 JSON 路径).
- The sample page shows: player, evaluation card, execution diff, the three
  audio tracks (口播 / BGM / 原声) and the next action.
- Audio rule: 口播 or BGM selected in `production_lock` must exist as a real
  track in the sample; "无音频" is only valid with an explicit reason recorded
  in the lock's `mix.reason` / `no_audio_reason` / `note`. A sample with
  selected-but-missing audio must not be marked complete.
- TTS real duration drives the caption/audio timeline (measured duration,
  not estimated), and BGM records profile, mood, volume and ducking.
  混音前逐段执行 [`skills/meta/voice-timeline-fit.md`](../../meta/voice-timeline-fit.md)
  的实测适配流程（实测 > 语速调优 > 改写 > 结构升级），禁止静默压缩。
- **口播 provider 默认豆包 TTS**（用户已确认；seed-tts-2.0 /
  `DOUBAO_SPEECH_VOICE_TYPE` 声线，返回词级时间戳用于字幕对齐）。换 provider
  必须经过用户确认并追加 `decision_log`。BGM 待用户选择（建议 SUNO 生成或
  pixabay 检索，key 已配置）；未确认前不得静默默认。

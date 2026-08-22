# voice-timeline-fit — TTS 实测时长驱动的口播时间轴适配

> 固化自 table-mat-mix-v8 生产实战：豆包 TTS 每段实测时长普遍超出剧本段落
> 槽位，手工调语速对齐耗时且易错。此 skill 是口播进入样片前的固定动作。

## 契约

1. **实测时长驱动时间轴**（Design_Review P0-3）：TTS 生成的每段音频必须
   以 `ffprobe` 实测时长为准，字幕与镜头槽位依据实测时长排布，禁止先按
   估算时长排完再硬塞音频。
2. **先测量，后适配**：对剧本每个有口播的段落，收集
   `段落槽位时长 slot_s`（scene_plan/script 声明）与
   `实测音频时长 audio_s`。全部落入槽位才允许混音。
3. **放不下时的决策顺序**（不允许静默压缩）：
   1. 逐段提高 `speech_rate`（豆包 seed-tts：+10% → +20% → 最多 +50%），
      每档重新实测；
   2. 仍放不下 → 改写该段文案（先删修饰语，再砍次要信息），保留事实与
      结论；
   3. 仍放不下 → 升格为结构问题：调整 scene_plan 段落时长并走
      `change_impact` 记录，或向用户升级（换更短声线/接受节奏变化）。
4. **混音对齐**：段落起点用 `adelay=<start_ms>` 逐段对齐；整轨
   `loudnorm` 至 -16 LUFS；口播与 BGM 需要 ducking 时按 music profile 执行。
5. **失败记录**：每段适配结果（slot/audio/speech_rate/是否改写）写入
   `decision_log`（`category: "capability_extension"` 或 rework 时
   `rework_cause` + `issue_tags`），供后续批量生产复用同一调参。

## 检查清单（混音前）

- [ ] 每段 `audio_s <= slot_s`（实测，非估算）
- [ ] 字幕 `startMs/endMs` 来自词级时间戳（豆包返回逐字 startTime/endTime）
- [ ] 无音频段落有明确理由（production_lock 记录）
- [ ] 混音后整轨响度在 L1a `loudness_bounds` 内
- [ ] `sample_execution_trace.audio_diff` 显示 executed

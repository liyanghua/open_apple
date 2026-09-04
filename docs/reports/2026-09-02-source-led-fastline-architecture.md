# Source-Led Cinematic Fastline — 架构文档（2026-09-02）

> 适用：无参考视频、自有素材驱动的模板化批量混剪（毛巾批次为代表，桌垫批次为参照验证）。
> 分支：`codex/cinematic-fast-source-led-mainline`。本文档描述当前主干形态，与 Task 1-7 实现一致。

## 1. 系统定位

OpenMontage 的 cinematic-fast 快线以"别处已把单条跑通"为基座，本批次把**无参考视频**（source-led）
变成一等输入模式：没有参考片可拆时，创意结构来自人工模板包（template_pack），素材绑定来自
**逐段逐帧的语义证据（evidence）**，而非位置索引或关键词猜测。

```
热点/商品事实
  → template_pack（人工模板）
  → 模板 × 证据矩阵 research（source semantics + evidence matrix）
  → 批次差异化（differentiation_plan）
  → Script/Scene 单镜单证据闭环（键控配对）
  → canonical assets（shot plan / asset plan / production lock）
  → canonical media prep（指纹 sidecar）→ canonical TTS（lock 指纹）
  → template_render（profile 驱动）→ sample 渲染
  → 对齐硬门（五维语义检查）→ finish（sample/compose/publish gate）
  → 交付
```

## 2. 输入模式（Task 1）

`lib/source_semantics.py`（或等价物）统一三态：

| 模式 | 说明 |
|---|---|
| reference-led | 有参考片，走 video_analyzer 深拆（既有路径不变） |
| source-led | 无参考片：自有素材即证据源 |
| template-led | 有模板包无素材：结构先行，素材槽位按缺口生成/桥接 |

毛巾批次 = source-led + template_pack（4 产品 × 4 方向 × 12 镜，共 16 条 30s 模板）。

## 3. 证据链（Task 1/2，本批次核心）

### 3.1 素材语义索引（semantic map）

每条素材（4K 竖拍 9:16，4.0-9.0s）经 ffprobe + scene_detect + 6 帧均匀采样 + VLM 标注：

```json
{
  "stem": "product_银离子毛巾-吸水演示-2",
  "domain": "吸水演示",            // 动作域（品类词汇表）
  "sub_actions": {"drop", "absorb"}, // 子动作标签（水滴/倒水/擦拭/渗透）
  "evidence_window": [1.844, 4.54],  // 动作实际发生的时间窗（帧级标注）
  "label_visible": [1.35, 4.77],     // 标签类素材的文字可见窗口（10 帧扫描）
  "duration_seconds": 8.98
}
```

### 3.2 证据矩阵（matrix）

模板每镜 × 素材窗口 → matrix row：`{matrix_row_id, source_media_id, source_time_range,
evidence_frames, confidence, resolution: accept/pending/rewrite|bridge|omit}`。
matrix 是 scene_plan 可以引用的唯一素材事实来源；row 的 resolution 必须 resolve 才允许进入 mapping。

### 3.3 证据窗优先级（allocator）

分配器三级策略，保证"口播开始时刻 == 动作开始时刻"：

1. **覆盖**：窗口完整包含动作区间（ev ⊆ window ±0.3s）；
2. **相交**：窗口与动作区间重叠（动作至少部分可见）；
3. **任意**：无证据窗或前两级耗尽（尾帧/CTA 品牌卡允许）。

候选顺序从 `ev_start` 向两侧扩展（不再从 0 秒盲探——这是修复"口播与画面错位"的关键之一）。

## 4. 键控配对与防漂移（Task 2，评审 P0-1）

所有跨阶段引用禁止"位置索引"：

- `script.section.scene_id` ↔ `scene_plan.scene.id`；
- `shot_execution_plan.shot.section_id` ↔ `script.section.id`；
- `scene_plan.metadata.source_mapping.template_slot_ref` ↔ `template.slot.id`。

配套：`lib.template_alignment.shot_alignment_errors`（shot→section 显式校验）、
`lib.template_assets.shot_plan_drift`（漂移即同步重派生四制品）。

## 5. 指纹与失效（Task 5）

| 资产 | 绑定字段 | 失效条件 |
|---|---|---|
| proxy | source_path / source_sha256 / start / duration / width / height / fit / fps | 任一字段变化即重建 |
| TTS | normalized_text / text_sha / voice_id / resource_id / speech_rate | 文本或参数变化即重生成 |
| render | final_props.input_hashes{script, sep, asset_manifest} + render_plan hash | 上游 hash 变化 → sample/compose 重走 |
| sample | 五类 hash（script/scene_plan/sep/proxy/tts） | 任一不匹配 → sample 硬化门失败 |

原则：**不得因"同名文件存在"而复用**。旧样片（无 section_id 绑定的 sep）在 dry-run 即被阻断。

## 6. 对齐硬门（Task 5，五维）

`lib.template_alignment` 提供：

- `tts_binding_errors`：口播文件与 lock 指纹（文本/音色/资源/语速）一致性；
- `shot_alignment_errors`：shot→section 绑定与文本一致性；
- `alignment_gate_errors`：VLM 逐镜画面对齐检查，非 `yes` 即阻断；
- `build_semantic_alignment`（stage51）：五维判定（内容/域/子动作/标签/节奏），
  输出结构化 check，不再把粗粒度 match 扇出成多个"通过"。

门接点：`finish_template_sample`（sample 门）、stage50 内部（渲染后门控）、
compose/publish 级联。`no/error → 硬拦；partial → 需人工确认通道（Task 7 规划）`。

## 7. Profile 层（3:4，Task 6）

| 档 | 分辨率 | 用途 |
|---|---|---|
| sample | 540×720 | 样片（0.5x） |
| upload | 1080×1440 | 交付/上传版 |
| master | 2160×2880 | 主片（4K 级，淘宝详情页主图 3:4） |

`lib.media_profiles` 三档案 + `AspectRatio.PORTRAIT_3_4`；`template_render` /
`template_assets.build_production_lock` / `prep_template_media` / `render_template_sample`
全部由 profile 驱动；`caption_layout` 新增 `taobao_detail_3_4` 安全区。

## 8. 批次执行序（毛巾）

```
stage20 semantic_links   → 素材语义命名 + 域
stage17 evidence_windows → 6 帧证据窗 + 10 帧标签扫描
stage25 research_matrix  → research 9 制品 + evidence matrix（批根共享）
stage30 build_batch      → template_batch + differentiation_plan + run 项目 + run plan + script
stage40 scene_assets     → canonical build_scene_plan + build_assets（四制品 + creative_lock 门）
stage50 sample           → canonical prep/TTS/render + alignment 门 + trace（含 deviation 三差）
stage51 verify_alignment → 五维语义对齐审计（写 alignment_check.json，供硬门消费）
```

## 9. 决策记录要点

- 无参考视频 → source-led + template_pack（不硬改 lib 桌垫硬编码表：创作数据外置）
- 3:4 输出 = profile 参数化，不建独立流程
- 渲染 seek 修复：asset_manifest 记录代理真实时长（否则 source_in 被钳 0）
- 银离子毛巾"抗菌标识"素材实为称重屏 0.00 → 抗菌 claim 无证据，按一致性纪律删除
- BGM 供应商：Suno/Pixabay 本机网络失败 → 复用已授权音轨（decision_log 已记录）

## 10. 边界与后续

- 对齐门 partial 的人工确认通道尚未实现（Task 7 遗留建议：`no → 硬拦；partial → alignment_review 人工`）
- proxy 自实现（MediaProxy + 指纹 sidecar）与 canonical `prep_template_media` 并存，
  契约一致，属实现差异而非缺口
- master 2160×2880 字幕字号/安全区需按 profile 等比换算（当前按 1080 宽标定）
- 单次全量回归基线：tests/ 全绿（见评价文档）

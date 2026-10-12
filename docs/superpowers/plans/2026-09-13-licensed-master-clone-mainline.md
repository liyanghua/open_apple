# 授权母版严格复刻主线 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有“爆款复刻（参考片仅分析）”之外新增更严格的“授权母版严格复刻”模式，以参考视频作为不可变母版，只允许批准遮罩和批准插入区间发生变化，并用帧级质量门保证至少 90% 的输出帧继承母版。

**Architecture:** 保留现有 `reference_fidelity` 的 `analysis_only` 安全语义，新增 `licensed_master_clone` 输入模式及独立制品合同。新模式先锁定母版、镜头和可修改范围，再通过时序遮罩执行局部材质迁移、字幕/口播替换和最多 10% 的新增证明镜头；最终由 FFmpeg 确定性合成并生成像素保真报告，任何不适配、越界修改或超时都 fail closed，禁止自动降级为整片生成。

**Tech Stack:** Python 3.10+、FFmpeg/ffprobe、OpenCV、SAM 2.1 small（本地缓存、MPS/CPU）、ONNX Runtime、JSON Schema、Backlot 原生 HTML/JavaScript、pytest。

---

## 已锁定产品决策

| 项目 | 现有爆款复刻 | 授权母版严格复刻 |
|---|---|---|
| 内部模式 | `reference_driven` / `reference_fidelity` | `licensed_master_clone` |
| 参考视频用途 | `analysis_only` | `render_source` |
| 画面路径 | 自有素材或新生成素材重建 | 原片母版 + 局部遮罩编辑 |
| 原人物/动作/机位 | 只能分析后重建 | 授权后原样保留 |
| 允许变化 | 新画面整体可变化 | 仅批准遮罩、字幕区和插入区间 |
| 新增整帧镜头 | 不限制来源，按普通质量门 | 最多占总帧数 10% |
| 不适配处理 | 可重新创作 | 直接阻断，不自动纯生成 |
| 合成路径 | Remotion / HyperFrames / FFmpeg | FFmpeg 像素锁定 |
| 人工门 | 脚本、创意和样片审核 | 额外增加遮罩审核 |
| 机器 SLA | 沿用 pipeline 上限 | 遮罩批准后 10 分钟硬上限 |

本次桌垫基线用于验收：原片为 720x1280、30fps、12.446 秒；基线克隆为 720x1280、24fps、12.064 秒。抽样边缘相关度中，原片对基线约为 0.397，原片对当前整片生成样片约为 0.013。新模式不把 0.397 当作最终门槛，而是要求遮罩外像素来源和时间轴具有可证明的母版血缘。

## 文件与责任边界

### 新增

- `lib/master_clone_contract.py`：纯函数；构建授权、母版、修改预算、插入预算和 SLA 合同。
- `lib/master_clone_validation.py`：校验遮罩、帧血缘、时间轴、编码对照和阻断原因。
- `lib/master_clone_edit_policy.py`：校验插入区间、字幕遮罩、音频授权和禁止路由。
- `lib/master_clone_deadline.py`：持久化遮罩批准后的统一 deadline，供所有后续工具检查和取消。
- `tools/video/master_mask_builder.py`：按镜头生成并传播 editable/protect masks，只写项目内制品。
- `tools/video/master_surface_transfer.py`：执行确定性颜色/材质迁移，不负责生成或编排。
- `tools/video/master_clone_compose.py`：FFmpeg 帧级合成、字幕替换、音频拼接和无损验证母版。
- `tools/video/master_insert_generate.py`：只生成合同中批准的短插入镜头，拒绝整片生成。
- `tools/subtitle/localized_subtitle_replace.py`：在批准 glyph mask 内修复和重绘字幕。
- `tools/audio/master_audio_replace.py`：按授权范围保留或移除母版音频，并做分段 TTS 替换。
- `tools/qa/pixel_preservation.py`：计算 source-frame coverage、遮罩外差异、SSIM、边缘抖动和切点漂移。
- `tools/qa/master_clone_qa.py`：deadline-aware QA 包装器；严格模式只能通过它调用 `final_qa` 和 `technical_validator`。
- `schemas/artifacts/master_edit_contract.schema.json`、`mask_manifest.schema.json`、`pixel_preservation_report.schema.json`：新模式的 canonical artifacts。
- `tests/contracts/test_licensed_master_clone_contract.py`、`tests/lib/test_master_clone_validation.py`、`tests/tools/test_master_clone_tools.py`、`tests/integration/test_licensed_master_clone_fixture.py`：合同、纯函数、工具和桌垫 fixture 测试。

### 修改

- `lib/pipeline_loader.py`、`lib/checkpoint.py`、`pipeline_defs/cinematic-fast.yaml`：登记新模式、阶段制品和遮罩审批 checkpoint。
- `backlot/operator_routes.py` 与项目创建界面：收集授权声明，区分两种复刻入口，展示遮罩审核。
- `skills/pipelines/cinematic-fast/*-director.md`：描述母版模式下的阶段行为，不改变旧模式规则。
- artifact/checkpoint schema 注册表与 Backlot 投影：展示母版血缘、修改范围、SLA 和质量门。

## Chunk 1：模式、授权和兼容合同

### Task 1：新增模式而不改写现有模式

**Files:**
- Modify: `lib/pipeline_loader.py`
- Modify: `lib/checkpoint.py`
- Modify: `schemas/checkpoints/checkpoint.schema.json`
- Test: `tests/contracts/test_licensed_master_clone_contract.py`

- [ ] **Step 1：先写失败合同测试**

覆盖：

```python
def test_licensed_master_clone_requires_render_source_and_rights(): ...
def test_licensed_master_clone_rejects_analysis_only_reference(): ...
def test_reference_fidelity_still_requires_analysis_only(): ...
def test_legacy_project_modes_are_unchanged(): ...
```

- [ ] **Step 2：运行并确认失败**

Run: `.venv/bin/python -m pytest tests/contracts/test_licensed_master_clone_contract.py -q`

Expected: FAIL，提示未知 `licensed_master_clone` 或缺少授权合同。

- [ ] **Step 3：实现最小模式合同**

将 `licensed_master_clone` 加入 `INPUT_MODES`。上传完成后，服务端计算母版 SHA-256，再创建与该哈希绑定且不可修改的授权声明：

```json
{
  "input_mode": "licensed_master_clone",
  "external_reference": {
    "present": true,
    "paths": ["inputs/reference/source.mp4"],
    "usage": "render_source"
  },
  "rights_attestation": {
    "confirmed": true,
    "source_sha256": "<server-computed master sha256>",
    "scopes": ["video_pixels", "adaptation", "likeness"],
    "confirmed_by": "<authenticated actor>",
    "confirmed_at": "<server timestamp>",
    "revoked_at": null
  }
}
```

服务端写入 actor、时间和 source hash，前端不得伪造。若要保留原环境声或音乐，还必须单独包含 `source_audio_reuse`；未授权时必须移除全部母版音频并使用新 TTS/音效。替换母版文件或撤销授权都会令合同和下游 checkpoint 失效。compose 与 publish 必须重新核对授权未撤销且 source hash 一致。`reference_fidelity` 继续只接受 `analysis_only`。

- [ ] **Step 4：运行合同和旧模式回归**

Run: `.venv/bin/python -m pytest tests/contracts/test_licensed_master_clone_contract.py tests/contracts/test_reference_fidelity_contract.py tests/contracts/test_cinematic_fast_input_modes.py tests/lib/test_reference_fidelity.py -q`

Expected: PASS，且旧模式行为没有变化。

- [ ] **Step 5：提交**

```bash
git add lib/pipeline_loader.py lib/checkpoint.py schemas/checkpoints/checkpoint.schema.json tests/contracts/test_licensed_master_clone_contract.py
git commit -m "feat: add licensed master clone input contract"
```

### Task 2：扩展 skill intake 与项目创建 API

**Files:**
- Modify: `skills/catalog/ecommerce-viral-remix/versions/1.0.1/intake.schema.json`
- Modify: `backlot/operator_routes.py`
- Modify: `backlot/ui/library.js`
- Test: `tests/backlot/test_reference_fidelity_entry.py`

- [ ] **Step 1：新增失败测试**

要求创建 API 区分：普通爆款复刻、结构严格复刻、授权母版严格复刻。母版模式缺少任一授权 scope、路径不在 `inputs/reference`、参考文件不可解析时返回 400；重复请求保持幂等。环境变量 `OPENMONTAGE_LICENSED_MASTER_CLONE` 缺失或为 `0/false/off/no` 时，入口不展示且 API 返回 404。

- [ ] **Step 2：运行并确认失败**

Run: `.venv/bin/python -m pytest tests/backlot/test_reference_fidelity_entry.py -q`

- [ ] **Step 3：实现 UI 和 API 校验**

界面文案固定为：

- “爆款复刻：参考片不进入成片，使用自有/生成素材重建。”
- “结构严格复刻：锁定镜头、节奏与口播槽位，参考片不进入成片。”
- “授权母版严格复刻：参考片进入成片，仅批准区域可修改；必须确认改编和肖像授权。”

母版模式必须显示授权 checkbox 和“遮罩审核后才开始制作”的提示。

功能开关固定为 `OPENMONTAGE_LICENSED_MASTER_CLONE`，由 `backlot/operator_routes.py` 的单一 helper 解析，默认关闭；创建页从现有 skills/capability 响应读取开关状态，不在前端硬编码开启。

- [ ] **Step 4：运行测试**

Run: `.venv/bin/python -m pytest tests/backlot/test_reference_fidelity_entry.py tests/backlot/test_auth_api.py -q`

- [ ] **Step 5：提交**

```bash
git add skills/catalog/ecommerce-viral-remix/versions/1.0.1/intake.schema.json backlot/operator_routes.py backlot/ui/library.js tests/backlot/test_reference_fidelity_entry.py
git commit -m "feat: expose authorized master clone entry"
```

## Chunk 2：母版合同与严格准入

### Task 3：实现 `master_edit_contract`

**Files:**
- Create: `lib/master_clone_contract.py`
- Create: `schemas/artifacts/master_edit_contract.schema.json`
- Modify: `lib/pipeline_loader.py`
- Modify: `lib/checkpoint.py`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `schemas/pipelines/pipeline_manifest.schema.json`
- Modify: `pipeline_defs/cinematic-fast.yaml`
- Test: `tests/lib/test_master_clone_validation.py`
- Test: `tests/contracts/test_licensed_master_clone_contract.py`

- [ ] **Step 1：为合同构建器写失败测试**

合同至少包含：母版 SHA-256、分辨率、FPS、time base、帧数、音频采样率、镜头半开区间、允许修改类别、最大插入帧数、目标输出 profile 和 600 秒 SLA。

- [ ] **Step 2：运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_master_clone_validation.py -q`

- [ ] **Step 3：实现纯函数与 schema**

固定策略：

```json
{
  "source_frame_coverage_min": 0.90,
  "max_full_frame_replacement_ratio": 0.10,
  "outside_mask_lossless_changed_pixels_max": 0,
  "delivery_outside_mask_ssim_min": 0.995,
  "mask_tracking_confidence_min": 0.90,
  "mask_edge_jitter_px_max": 2,
  "sample_machine_sla_seconds": 600,
  "final_machine_sla_seconds": 180,
  "fallback_policy": "block"
}
```

输出 FPS、帧数和切点默认完全继承母版；批准插入镜头只能替换已有时间窗，不能延长整片。

`source_frame_coverage` 的分母是最终输出总帧数；仅当输出帧的 base lineage 指向同序号母版帧、且该帧不在批准的全帧替换区间内时计入分子。逐帧 lineage 必须与全部 `approved_insert_intervals` 精确对账。90% 整通过，89.99% 失败；空遮罩和零插入是合法情况。

- [ ] **Step 4：接入完整 mode requirements**

mode resolver 对模式字段采用“替换”而不是“追加”，因此必须为新模式显式声明每个阶段的完整合同，不得只写新增制品：

```yaml
licensed_master_clone:
  research_required_tools: [video_analyzer, scene_detect, frame_sampler, transcriber, audio_energy]
  research_required: [research_brief, video_analysis_brief, reference_fingerprint]
  research_produces: [research_brief, video_analysis_brief, reference_fingerprint, research_breakdown, reference_source_matrix, research_synthesis, research_scorecard, reference_timeline, fidelity_policy, caption_style_fingerprint, master_edit_contract]
  script_required: [proposal_packet, creative_control_plan, reference_timeline, fidelity_policy, master_edit_contract]
  script_produces: [script, replacement_matrix]
  scene_plan_required: [script, creative_control_plan, reference_timeline, replacement_matrix, reference_source_matrix, master_edit_contract]
  assets_required: [scene_plan, replacement_matrix, fidelity_policy, master_edit_contract]
  assets_produces: [shot_execution_plan, asset_plan, production_lock, approval_bundle]
  mask_required: [reference_timeline, replacement_matrix, shot_execution_plan, master_edit_contract]
  mask_produces: [mask_manifest]
  mask_required_tools: [master_mask_builder]
  mask_tools_available: [master_mask_builder]
  sample_required: [asset_plan, production_lock, reference_timeline, replacement_matrix, reference_source_matrix, master_edit_contract, mask_manifest]
  sample_produces: [asset_manifest, final_props, render_plan, sample_report, sample_execution_trace, voice_alignment_report, reference_alignment_report, pixel_preservation_report]
  sample_required_tools: [master_surface_transfer, master_insert_generate, localized_subtitle_replace, master_audio_replace, master_clone_compose, master_clone_qa, pixel_preservation]
  sample_tools_available: [master_surface_transfer, master_insert_generate, localized_subtitle_replace, master_audio_replace, master_clone_compose, master_clone_qa, pixel_preservation]
  compose_required: [edit_decisions, final_props, reference_timeline, replacement_matrix, reference_source_matrix, voice_alignment_report, master_edit_contract, mask_manifest, pixel_preservation_report]
  compose_produces: [render_report, evaluation_report, reference_alignment_report, pixel_preservation_report]
  compose_required_tools: [master_clone_compose, master_clone_qa, pixel_preservation]
  compose_tools_available: [master_clone_compose, master_clone_qa, pixel_preservation]
  publish_required: [render_report, evaluation_report, reference_alignment_report, pixel_preservation_report, replacement_matrix, reference_source_matrix, master_edit_contract, mask_manifest]
```

同时扩展 manifest schema 和 loader，使 `required_tools` / `tools_available` 可按任意阶段和模式解析。增加一个位于 `assets` 与 `sample` 之间的 `mask` 阶段，并在 stage schema 增加 `applies_to_modes: [licensed_master_clone]`；其他模式必须自动跳过该阶段。`mask` 独占 `mask_lock` approval group，避免让已有 `assets -> creative_lock` 同时属于两个审批组。

先把 `master_edit_contract` 注册进 `schemas/artifacts/__init__.py` 的 `ARTIFACT_NAMES` 以及 `lib/checkpoint.py` 的 canonical artifact 集合；后续两个 artifact 在各自 schema 落地任务中注册。增加 Product Truth 失败测试：replacement matrix 缺商品事实、reference source matrix 缺证据或高风险 claim 未闭环时，licensed 模式的 sample/compose/publish 均失败。

必须增加负向路由测试：该模式的 sample/compose 不能解析出 `video_compose`、Remotion、HyperFrames、原始 `final_qa`、原始 `technical_validator` 或任何整片生成工具；QA 列表中只能出现 deadline-aware 的 `master_clone_qa`，其他模式的工具列表保持原样。

- [ ] **Step 5：测试和提交**

Run: `.venv/bin/python -m pytest tests/lib/test_master_clone_validation.py tests/contracts/test_pipeline_manifests.py tests/contracts/test_licensed_master_clone_contract.py tests/contracts/test_reference_fidelity_contract.py -q`

```bash
git add lib/master_clone_contract.py lib/pipeline_loader.py lib/checkpoint.py schemas/artifacts/__init__.py schemas/artifacts/master_edit_contract.schema.json schemas/pipelines/pipeline_manifest.schema.json pipeline_defs/cinematic-fast.yaml tests/lib/test_master_clone_validation.py tests/contracts/test_licensed_master_clone_contract.py
git commit -m "feat: define immutable master edit contract"
```

### Task 4：实现严格准入分类器

**Files:**
- Modify: `lib/master_clone_validation.py`
- Modify: `skills/pipelines/cinematic-fast/research-director.md`
- Test: `tests/lib/test_master_clone_validation.py`

- [ ] **Step 1：增加失败场景**

阻断条件包括：目标产品与参考商品几何类别不同、必须改变手部接触关系、必须重建人物、可编辑区域覆盖不稳定、预计整帧替换超过 10%、参考人物授权缺失。

- [ ] **Step 2：实现准入结果**

返回 `eligible | blocked`，并使用稳定 reason code：

```text
rights_missing
geometry_incompatible
interaction_reconstruction_required
mask_untrackable
replacement_budget_exceeded
```

不得返回或执行 `generate_full_video` fallback。

- [ ] **Step 3：验证桌垫 fixture**

本例应判定为 `eligible`：透明桌垫的几何和动作沿用母版，只需要桌面/桌垫区域材质迁移、字幕口播替换和一个批准插入镜头。

- [ ] **Step 4：测试和提交**

Run: `.venv/bin/python -m pytest tests/lib/test_master_clone_validation.py -q`

```bash
git add lib/master_clone_validation.py skills/pipelines/cinematic-fast/research-director.md tests/lib/test_master_clone_validation.py
git commit -m "feat: fail closed on incompatible master clones"
```

## Chunk 3：时序遮罩与人工审核

### Task 5：实现逐镜头 mask builder

**Files:**
- Create: `tools/video/master_mask_builder.py`
- Create: `schemas/artifacts/mask_manifest.schema.json`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `lib/checkpoint.py`
- Test: `tests/tools/test_master_clone_tools.py`

- [ ] **Step 1：写工具合同测试**

输入为母版路径、reference timeline、关键帧提示框/点和输出目录。输出必须分别记录：

- `editable_mask`：桌面、桌垫或批准商品区域。
- `protect_masks`：手、人物、器具、桌边和其他不得修改区域。
- 每帧 tracking confidence、面积变化和边缘抖动。
- 每镜头首、中、尾三张审核叠图。

- [ ] **Step 2：运行并确认失败**

Run: `.venv/bin/python -m pytest tests/tools/test_master_clone_tools.py -q`

- [ ] **Step 3：实现 SAM 2.1 small 传播**

将工具注册到现有 registry，并在 `get_status()` 中检查 FFmpeg、模型运行库和权重。模型权重必须在 capability preflight 时预下载并缓存，生产运行不得临时下载。优先使用 MPS，失败时回退 CPU；两者均不可用时工具状态为 unavailable，而不是调用在线生成替代。preflight 必须在任何付费调用和 mask checkpoint 之前完成。

最终编辑遮罩计算为：

```text
effective_editable_mask = editable_mask - union(protect_masks)
```

在同一提交中将 `mask_manifest` 注册到 artifact schema loader 和 checkpoint canonical artifact 集合。

- [ ] **Step 4：加入稳定性硬门**

任一镜头 confidence <0.90、边缘抖动 >2px、遮罩越过手指/人物保护区时标记 `blocked`，不得生成样片。

增加 registry 发现测试和 provider-menu 测试，确认工具不可用时只返回安装说明，不会路由到 `video_selector`。

- [ ] **Step 5：测试和提交**

Run: `.venv/bin/python -m pytest tests/tools/test_master_clone_tools.py -q`

```bash
git add tools/video/master_mask_builder.py schemas/artifacts/mask_manifest.schema.json schemas/artifacts/__init__.py lib/checkpoint.py tests/tools/test_master_clone_tools.py
git commit -m "feat: build tracked masks for master clone edits"
```

### Task 6：增加遮罩审核 checkpoint

**Files:**
- Modify: `lib/checkpoint.py`
- Modify: `lib/pipeline_loader.py`
- Modify: `schemas/pipelines/pipeline_manifest.schema.json`
- Create: `skills/pipelines/cinematic-fast/mask-director.md`
- Modify: `pipeline_defs/cinematic-fast.yaml`
- Modify: `backlot/operator_state.py`
- Modify: `backlot/ui/operator/approval.js`
- Test: `tests/backlot/test_reference_fidelity_operator_state.py`
- Test: `tests/contracts/test_licensed_master_clone_contract.py`

- [ ] **Step 1：先写失败测试**

测试 `mask` 阶段只出现在 `licensed_master_clone`，其他四种模式会跳过；`mask_lock` 未批准时 sample 被阻断；审核页展示每镜头首/中/尾叠图、修改区域、保护区域、confidence 和阻断原因。

- [ ] **Step 2：定义完整的 mode-applicable 阶段**

在 manifest 的 `required_skills` 注册 `pipelines/cinematic-fast/mask-director`，并增加完整阶段块：

```yaml
- name: mask
  skill: pipelines/cinematic-fast/mask-director
  applies_to_modes: [licensed_master_clone]
  approval_group: mask_lock
  approval_group_terminal: true
  required_artifacts_in: [reference_timeline, replacement_matrix, shot_execution_plan, master_edit_contract]
  produces: [mask_manifest]
  required_tools: [master_mask_builder]
  tools_available: [master_mask_builder]
  checkpoint_required: true
  human_approval_default: true
  review_focus: [Editable mask containment, protected pixels, temporal stability]
  success_criteria: [Schema-valid mask manifest, all shots meet confidence and jitter gates]
```

`mask-director.md` 只负责解释遮罩构建、review bundle、失败回修和审批规则，不承担模型下载或图像处理实现。测试确认 skill 可解析、仅 licensed 模式进入该阶段。

- [ ] **Step 3：实现审核动作**

实现 `stage.applies_to_modes` 和 checkpoint 的可跳过阶段解析。`mask` 阶段独占 `mask_lock`，审核只允许 `approve | reject`。reject 回到 mask builder；不允许在 UI 直接放宽像素阈值或改变 10% 插入预算。

- [ ] **Step 4：运行测试和提交**

Run: `.venv/bin/python -m pytest tests/backlot/test_reference_fidelity_operator_state.py tests/backlot/test_operator_state.py tests/contracts/test_licensed_master_clone_contract.py -q`

```bash
git add lib/checkpoint.py lib/pipeline_loader.py schemas/pipelines/pipeline_manifest.schema.json skills/pipelines/cinematic-fast/mask-director.md pipeline_defs/cinematic-fast.yaml backlot/operator_state.py backlot/ui/operator/approval.js tests/backlot/test_reference_fidelity_operator_state.py tests/contracts/test_licensed_master_clone_contract.py
git commit -m "feat: add mandatory mask approval gate"
```

## Chunk 4：局部变换、音频和确定性合成

### Task 7：实现确定性桌面/材质迁移

**Files:**
- Create: `lib/master_clone_deadline.py`
- Create: `tools/video/master_surface_transfer.py`
- Create: `tests/lib/test_master_clone_deadline.py`
- Test: `tests/tools/test_master_clone_tools.py`

- [ ] **Step 1：编写失败测试**

使用 fake clock 先验证 mask approval 会创建统一 600 秒 deadline，过期状态不可恢复。使用合成桌面 fixture 验证：目标色彩进入 editable mask；阴影、反射和透明垫边缘亮度保持；protect mask 内手部像素不变；遮罩外像素完全相同。

- [ ] **Step 2：实现局部变换**

先实现 `master_clone_deadline` 的持久化状态和 `assert_active()`。`master_surface_transfer` 必须接收 `deadline_ref`，执行前后检查。对桌面类平面材质采用镜头内透视跟踪、Lab 色彩映射、局部 LUT 和亮度保留。不得使用整帧视频生成。只有当目标商品几何与母版一致时才允许迁移产品颜色/材质；否则由准入门阻断。

- [ ] **Step 3：运行测试和提交**

Run: `.venv/bin/python -m pytest tests/tools/test_master_clone_tools.py tests/lib/test_master_clone_deadline.py -q`

```bash
git add lib/master_clone_deadline.py tools/video/master_surface_transfer.py tests/lib/test_master_clone_deadline.py tests/tools/test_master_clone_tools.py
git commit -m "feat: transfer surface appearance inside approved masks"
```

### Task 8：实现插入镜头、字幕和口播合同

**Files:**
- Create: `lib/master_clone_edit_policy.py`
- Create: `tools/video/master_insert_generate.py`
- Create: `tools/subtitle/localized_subtitle_replace.py`
- Create: `tools/audio/master_audio_replace.py`
- Modify: `skills/pipelines/cinematic-fast/asset-director.md`
- Modify: `skills/pipelines/cinematic-fast/sample-director.md`
- Modify: `lib/voice_alignment.py`
- Test: `tests/lib/test_master_clone_edit_policy.py`
- Test: `tests/lib/test_voice_alignment.py`

- [ ] **Step 1：先写编辑政策失败测试**

覆盖半开区间相交、重叠插入区间、空插入、恰好 10%、10.01%、89.99%/90% source coverage、分数 FPS、字幕遮罩越界、protect mask 像素变化、未授权音频保留，以及任意整片生成路由。

- [ ] **Step 2：运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_master_clone_edit_policy.py tests/lib/test_voice_alignment.py -q`

- [ ] **Step 3：实现插入预算与受限生成工具**

新增证明动作只允许写入 `master_edit_contract.approved_insert_intervals`。所有区间总帧数不得超过母版帧数的 10%；生成任务和 TTS 可并行，整片生成工具不在该模式候选列表中。

`master_insert_generate` 必须接收已批准 interval、合同 hash、`deadline_ref` 和最大帧数；输出超过批准区间或试图覆盖完整时间线时立即失败。它可以内部调用已批准的视频 provider，但不能接受整片 duration，也不能被 `video_selector` 自动扩展任务范围。

- [ ] **Step 4：实现音频授权和分段替换**

只有授权包含 `source_audio_reuse` 时才允许保留母版非人声环境层；否则 `master_audio_replace` 必须移除母版音轨。工具必须接收 `deadline_ref`，再使用批准的豆包 TTS 替换产品口播。逐段起止误差 <=80ms，字幕和口播文本必须来自同一 approved script section。工具输出记录保留/移除的采样区间和授权 hash。

- [ ] **Step 5：实现字幕局部修复**

`localized_subtitle_replace` 只接受批准的 glyph mask 和 `deadline_ref`。原烧录字幕只可在该遮罩内修复并重绘，字幕遮罩计入允许修改区域；全宽模糊条、未登记矩形覆盖或改变 protect mask 像素均失败。

- [ ] **Step 6：增加禁止路由测试**

确认 `licensed_master_clone` 的 resolved tools 不含 `video_compose`、Remotion、HyperFrames、`seedance_video` 或通用 `video_selector`；只有 `master_insert_generate` 可以在批准短区间内触发生成。

- [ ] **Step 7：测试和提交**

Run: `.venv/bin/python -m pytest tests/lib/test_master_clone_edit_policy.py tests/lib/test_voice_alignment.py tests/tools/test_subtitle_timestamps.py tests/contracts/test_licensed_master_clone_contract.py -q`

```bash
git add lib/master_clone_edit_policy.py tools/video/master_insert_generate.py tools/subtitle/localized_subtitle_replace.py tools/audio/master_audio_replace.py skills/pipelines/cinematic-fast/asset-director.md skills/pipelines/cinematic-fast/sample-director.md lib/voice_alignment.py tests/lib/test_master_clone_edit_policy.py tests/lib/test_voice_alignment.py
git commit -m "feat: constrain inserts captions and narration in master clone mode"
```

### Task 9：实现 FFmpeg 像素锁定合成器

**Files:**
- Modify: `lib/master_clone_deadline.py`
- Create: `tools/video/master_clone_compose.py`
- Modify: `tools/video/master_surface_transfer.py`
- Modify: `tools/video/master_insert_generate.py`
- Modify: `tools/subtitle/localized_subtitle_replace.py`
- Modify: `tools/audio/master_audio_replace.py`
- Create: `tools/qa/master_clone_qa.py`
- Modify: `tools/cost_tracker.py`
- Modify: `skills/pipelines/cinematic-fast/compose-director.md`
- Test: `tests/tools/test_master_clone_tools.py`
- Test: `tests/lib/test_master_clone_deadline.py`

- [ ] **Step 1：编写合成合同测试**

合成器必须输出：无损 FFV1 验证母版、交付 H.264 MP4、每帧 source lineage，以及字幕/音频修改区间。禁止 Remotion/HyperFrames 作为此模式的最终渲染器。

- [ ] **Step 2：实现逐帧合成**

每帧使用原片作为底图，只在 `effective_editable_mask` 内混入变换结果；批准插入区间允许全帧替换。输出 FPS、帧数、time base、分辨率和切点继承原片。

- [ ] **Step 3：先写跨任务 deadline 失败测试**

使用 fake clock 覆盖：mask approval 时创建 `phase=sample` 的 600 秒机器时间预算；surface transfer、插入生成、TTS、字幕、合成和 QA 读取同一 phase deadline；过期后取消 provider task、停止轮询、不再 reserve 新费用、退回尚未提交的 reservation，并禁止自动重试。

当 sample 写入 `awaiting_human` 时停止 sample 计时。人工等待任意时长都不消耗预算；sample 获批后创建新的 `phase=final`、180 秒机器时间预算，用于最终合成、final QA 和最终像素报告。增加“人工等待 24 小时后仍可完成 final”的 fake-clock 测试。

- [ ] **Step 4：实现持久化 deadline owner**

`lib/master_clone_deadline.py` 以 phase 记录 `active_machine_ms`，而不是把人工等待计入墙钟时间。mask approval 创建 sample phase；sample awaiting-human 关闭该 phase；sample approval 创建 final phase。每个 phase 分别记录 `started_at`、`budget_ms`、`active_machine_ms`、`status` 和 approval hash。`master_surface_transfer`、`master_insert_generate`、`localized_subtitle_replace`、`master_audio_replace`、`master_clone_compose`、`master_clone_qa` 和 `pixel_preservation` 的 input schema 都必须包含当前 phase 的 `deadline_ref`，并在执行前后调用 `assert_active()`。

`master_audio_replace` 是 licensed 模式调用 TTS/audio mixer 的唯一入口，`localized_subtitle_replace` 是 subtitle 工具的唯一入口，`master_clone_qa` 是调用 `final_qa` / `technical_validator` 的唯一入口，防止绕过 deadline。`CostTracker.reserve()` 增加可选的 deadline guard，在过期后拒绝新 reservation。`master_insert_generate` 保存 provider task id 并负责 cancel；超时后原子写入 `status=expired`、`reason=sla_exceeded`。无法取消的远端任务只能取回结果，不得自动进入合成或产生第二次提交。

- [ ] **Step 5：运行测试和提交**

Run: `.venv/bin/python -m pytest tests/tools/test_master_clone_tools.py tests/lib/test_master_clone_deadline.py tests/tools/test_cost_tracker_governance.py -q`

```bash
git add lib/master_clone_deadline.py tools/video/master_clone_compose.py tools/video/master_surface_transfer.py tools/video/master_insert_generate.py tools/subtitle/localized_subtitle_replace.py tools/audio/master_audio_replace.py tools/qa/master_clone_qa.py tools/cost_tracker.py skills/pipelines/cinematic-fast/compose-director.md tests/tools/test_master_clone_tools.py tests/lib/test_master_clone_deadline.py
git commit -m "feat: compose pixel-locked master clone outputs"
```

## Chunk 5：像素证明、工作台和端到端验收

### Task 10：实现 `pixel_preservation_report`

**Files:**
- Create: `tools/qa/pixel_preservation.py`
- Create: `schemas/artifacts/pixel_preservation_report.schema.json`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `lib/master_clone_validation.py`
- Modify: `lib/artifact_io.py`
- Modify: `lib/checkpoint.py`
- Modify: `skills/pipelines/cinematic-fast/publish-director.md`
- Test: `tests/lib/test_master_clone_validation.py`
- Test: `tests/contracts/test_licensed_master_clone_contract.py`

- [ ] **Step 1：写失败门测试**

覆盖：遮罩外修改一个像素、source-derived frames <90%、insert frames >10%、切点漂移一帧、输出帧数变化、SSIM <0.995、mask jitter >2px、SLA >600 秒。

- [ ] **Step 2：实现带 scope 和哈希绑定的报告**

将 `pixel_preservation_report` 注册进 artifact schema loader，并加入 `lib/artifact_io.py::SCOPED_ARTIFACTS`；合法 scope 仅为 `sample | final`，物理文件分别为 `pixel_preservation_report.sample.json` 和 `pixel_preservation_report.final.json`。checkpoint/artifact resolver 必须按当前阶段解析正确 scope，禁止无 scope 覆盖。

`pixel_preservation` 工具同样要求当前 phase 的 `deadline_ref` 并在读取、计算和写报告前检查：sample 使用 600 秒预算，final 使用 180 秒预算，防止 QA 超时后仍把结果推进到下一阶段。

sample 与 final 各生成一份独立报告；报告必须绑定 exact source、rights、contract、mask、control encode 和被测输出的 SHA-256：

```json
{
  "scope": "sample",
  "deadline_phase": "sample",
  "source_sha256": "...",
  "rights_attestation_sha256": "...",
  "master_edit_contract_sha256": "...",
  "mask_manifest_sha256": "...",
  "control_encode_sha256": "...",
  "output_sha256": "...",
  "source_frame_coverage": 0.90,
  "full_frame_replacement_ratio": 0.10,
  "outside_mask_lossless_changed_pixels": 0,
  "delivery_outside_mask_ssim": 0.995,
  "frame_count_match": true,
  "fps_match": true,
  "cut_point_drift_frames_max": 0,
  "machine_elapsed_seconds": 600,
  "status": "pass"
}
```

交付编码与“同参数重编码的原片 control”比较，避免把 H.264 编码噪声误算为编辑越界；无损母版必须满足遮罩外零变化。

- [ ] **Step 3：定义聚合与发布硬门**

`reference_alignment_report.status` 由纯函数聚合三组独立门：timeline fidelity、Product Truth、pixel preservation；任一失败则整体失败，分数不得互相抵消。sample checkpoint 必须引用 sample report；compose 完成后必须针对最终交付文件重新生成 `scope=final` 的报告。

checkpoint publish gate 与 `publish-director.md` 必须调用同一个 validator，并拒绝：sample scope 冒充 final、output hash 与交付文件不一致、source hash 已变化、mask/contract hash 过期、授权已撤销或 Product Truth 输入不完整。仅在这些检查通过时才允许 publish。

schema 与测试同时要求 `scope` 和 `deadline_phase` 成对匹配：只允许 `sample/sample` 与 `final/final`，交叉组合均无效。

- [ ] **Step 4：测试和提交**

Run: `.venv/bin/python -m pytest tests/lib/test_master_clone_validation.py tests/contracts/test_licensed_master_clone_contract.py tests/contracts/test_evaluation_report_contract.py -q`

```bash
git add tools/qa/pixel_preservation.py schemas/artifacts/pixel_preservation_report.schema.json schemas/artifacts/__init__.py lib/master_clone_validation.py lib/artifact_io.py lib/checkpoint.py skills/pipelines/cinematic-fast/publish-director.md tests/lib/test_master_clone_validation.py tests/contracts/test_licensed_master_clone_contract.py
git commit -m "feat: enforce pixel preservation quality gates"
```

### Task 11：升级 Backlot 可视化

**Files:**
- Modify: `backlot/operator_state.py`
- Modify: `backlot/ui/operator/app.js`
- Modify: `backlot/ui/operator/approval.js`
- Test: `tests/backlot/test_reference_fidelity_operator_state.py`

- [ ] **Step 1：写工作台投影测试**

严格模式页面必须显示：授权状态、母版哈希、遮罩覆盖、保护区域、source-frame coverage、插入比例、像素一致性、SLA 倒计时和明确阻断原因。

- [ ] **Step 2：实现两条链路的视觉区分**

分析型复刻显示“参考片不进入成片”；母版严格复刻显示“参考片作为授权母版”。禁止共用容易误解的单一“严格复刻”标签。

- [ ] **Step 3：测试和提交**

Run: `.venv/bin/python -m pytest tests/backlot/test_reference_fidelity_operator_state.py tests/backlot/test_operator_state.py -q`

```bash
git add backlot/operator_state.py backlot/ui/operator/app.js backlot/ui/operator/approval.js tests/backlot/test_reference_fidelity_operator_state.py
git commit -m "feat: visualize authorized master clone guarantees"
```

### Task 12：桌垫项目端到端验收

**Files:**
- Create: `tests/integration/test_licensed_master_clone_fixture.py`
- Read: `projects/table-mat-mix-v1/inputs/reference/douyin-7670014963255151913.mp4`
- Read: `projects/table-mat-mix-v1/analysis/benchmark/three-way-comparison.jpg`

- [ ] **Step 1：建立小型测试 fixture**

从原片提取短区间和降采样帧作为测试 fixture，不将完整用户视频提交到 Git。测试合同仍记录原始 720x1280/30fps/373 帧基线。

- [ ] **Step 2：运行母版编辑回放**

只允许：桌面/桌垫遮罩内颜色材质迁移、字幕与豆包口播替换，以及不超过总帧 10% 的擦拭证明区间。人物、手部动作、机位、空间背景和其他帧必须来自母版。

- [ ] **Step 3：验证硬门**

要求：

- `source_frame_coverage >= 0.90`
- `full_frame_replacement_ratio <= 0.10`
- `outside_mask_lossless_changed_pixels == 0`
- `delivery_outside_mask_ssim >= 0.995`
- FPS、帧数、切点匹配
- 口播段 drift <=80ms
- 从 mask approval 到样片完成 <=600 秒
- 人工样片审核等待不计入机器时间
- 样片批准后 final compose + QA <=180 秒

- [ ] **Step 4：运行完整回归**

Run:

```bash
.venv/bin/python -m pytest \
  tests/contracts/test_licensed_master_clone_contract.py \
  tests/contracts/test_reference_fidelity_contract.py \
  tests/lib/test_reference_fidelity.py \
  tests/lib/test_master_clone_validation.py \
  tests/lib/test_master_clone_edit_policy.py \
  tests/lib/test_master_clone_deadline.py \
  tests/tools/test_master_clone_tools.py \
  tests/integration/test_licensed_master_clone_fixture.py \
  tests/backlot/test_reference_fidelity_entry.py \
  tests/backlot/test_reference_fidelity_operator_state.py -q
```

Expected: 全部 PASS，现有 `reference_driven`、`reference_fidelity`、`source_led` 和 `source_led_template` 回归无变化。

旧 `reference_fidelity` 的渲染边界测试必须继续证明：参考路径不能进入 `asset_manifest`、`final_props`、`render_plan` 或任一 renderer 输入。新模式测试则证明只有与有效 rights/source hash 绑定的母版路径可以进入 `master_clone_compose`。

- [ ] **Step 5：提交**

```bash
git add tests/integration/test_licensed_master_clone_fixture.py
git commit -m "test: validate licensed master clone end to end"
```

## 发布与迁移

- [ ] 以环境变量 `OPENMONTAGE_LICENSED_MASTER_CLONE=0` 合入；`backlot/operator_routes.py` 和创建页共用服务端投影，旧项目不迁移、不改变已有 checkpoint，并由 `tests/backlot/test_reference_fidelity_entry.py` 验证默认关闭。
- [ ] 在已缓存 SAM 权重且 capability preflight 通过的机器上开启内部 canary。
- [ ] 将 `table-mat-mix-v1` 的当前纯生成样片标记为历史结果；重新运行时从母版合同和遮罩审核开始，复用现有 research、商品事实和豆包 TTS。
- [ ] canary 连续 10 条视频均通过像素门、无越界修改且 P95 机器执行时间 <=600 秒后，再向所有用户开放入口。
- [ ] 任一项目触发 `rights_missing`、`mask_untrackable`、`replacement_budget_exceeded` 或 `sla_exceeded` 时只展示阻断和修复建议，不提供自动纯生成按钮。

## 完成定义

实施完成必须同时满足：

1. 两条复刻链路在入口、项目 marker、pipeline mode、工作台和文档中完全区分。
2. 只有经过授权的 `licensed_master_clone` 可以将参考视频声明为 `render_source`。
3. 遮罩审核是不可绕过的阶段门。
4. 遮罩外像素在无损母版中零变化，至少 90% 输出帧继承参考母版。
5. 新增整帧镜头不超过 10%，不适配时直接阻断。
6. FFmpeg 是该模式唯一最终合成路径，Remotion/HyperFrames 不参与最终像素锁定渲染。
7. 遮罩批准到样片完成的机器时间不超过 10 分钟；人工审核暂停计时；样片批准后的最终合成与 QA 不超过 3 分钟。
8. sample 与 final 分别生成像素报告；publish 只接受绑定最终文件和未撤销授权的 final 报告。

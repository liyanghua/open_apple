# Cinematic 4 小时快线 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将参考视频驱动的 cinematic 产品混剪稳定压缩到 3-5 小时，并让同素材复用、音频修改和暖启动任务进一步缩短到分钟级，同时保留版权隔离、人工审批、Remotion 运行时治理和最终全量 QA。

**Architecture:** 以内容哈希和注册制 artifact 作为可恢复生产状态，以 `final_props.json` 作为唯一时间轴，以 `render_plan` 决定 `sample | full | mux_only` 最小执行路径。流水线保留全部阶段证据，但把人工等待合并为 `creative_lock` 和 `sample` 两个审批点；P0 先解决重复工作与返工，P1 只在基准数据证明有价值后增加 UI、品牌配置和场景级增量渲染。

**Tech Stack:** Python 3.10+、pytest、jsonschema、RFC 8785/JCS、FFmpeg/ffprobe、Remotion 4、React 18、TypeScript、FastAPI、原生 JavaScript Backlot UI、YAML pipeline manifests。

---

## 核心要点

1. **900 帧不是主要瓶颈。** 30 秒、30fps 的交付天然就是 900 帧；真正耗时来自重复抽帧/分析、重复 TTS 与混音、多人机审批往返以及任何修改都全链路重跑。
2. **P0 只做六件决定性工作。** 内容寻址缓存、唯一时间轴、最小变更路由、真实样片阶段、两个审批点、可执行的 QA v2。完成这些后才允许宣称 3-5 小时快线。
3. **`final_props.json` 是生产时间轴唯一真相。** Remotion 的 `Root.tsx` 和 `Composition.tsx` 不再重复保存 16 个镜头边界或固定 900 帧。
4. **`render_plan` 决定是否渲染。** 仅口播/BGM/音量变化走 `audio_mixer -> mux_only`；字幕、画面、裁切、速度或转场变化在 P0 仍走完整 Remotion；元数据变化不渲染。
5. **先锁创意，再花钱。** `assets` 在第一次审批前只生成 `asset_plan`，不得调用付费 TTS、音乐或视频生成；审批后才生成真实 `asset_manifest` 和 10-15 秒样片。
6. **只保留两个用户停点。** 第一次一次性确认方案、完整口播、字幕、逐镜映射、素材与 CTA；第二次确认基于最终 props 的样片。
7. **缓存命中也必须做最终 QA。** 最终输出固定为 H.264/yuv420p、1080x1920、30fps、AAC 48kHz 双声道，并检查黑帧、冻结、响度、峰值、字幕安全区和准确时长。
8. **P1 由数据触发。** Backlot UI 和通用字幕组件可紧随 P0；场景级增量渲染只有在基准证明完整渲染占总耗时超过 10% 或单次超过 3 分钟时才实施。

## 交付边界与顺序

```text
P0-A 证据与缓存
  -> P0-B 唯一时间轴、sample/full/mux_only
  -> P0-C QA v2、两道审批门、cinematic-fast
  -> 3 次冷启动 + 5 次暖启动基准
  -> P1 Backlot/品牌/字幕
  -> 条件满足时才做场景级增量渲染
```

执行期间必须遵守：

- 不改变用户已锁定的 Remotion runtime 和 atelier composition mode。
- 不调用任何付费 provider 作为测试；provider 测试全部 mock。
- 时间区间统一为半开区间 `[fromFrame, toFrameExclusive)`。
- 所有 cache key 使用文件内容 SHA-256，不使用文件名或 mtime 作为身份。
- 所有 canonical artifact 原子写入 `projects/<project-id>/artifacts/`。
- 当前目录没有可用 Git 元数据；下列 commit 步骤是恢复 Git 后的逻辑提交边界，执行时若仍无 `.git`，记录为 `SKIPPED_NO_GIT`，不得自行 `git init`。

## 文件职责总览

| 边界 | 新文件 | 单一职责 |
|---|---|---|
| Artifact 完整性 | `lib/artifact_hashing.py` | RFC 8785 规范化、语义哈希、完整性哈希与校验 |
| Artifact I/O | `lib/artifact_io.py` | 原子写入、artifact envelope、路径/hash 回放校验 |
| 通用缓存 | `lib/artifact_cache.py` | 原子缓存、锁、命中校验、损坏淘汰 |
| 媒体证据 | `lib/media_index.py` | 递归媒体索引、内容指纹、并行分析复用 |
| 变更路由 | `lib/change_impact.py` | 比较 production lock/props，输出最小安全执行模式 |
| 时间轴 | `lib/final_props.py` | 半开区间、源素材覆盖、字幕/音频边界验证 |
| Remotion 环境 | `lib/remotion_runtime.py` | Node、Remotion、Chromium、FFmpeg、字体和 props 预检 |
| 代理素材 | `tools/video/media_proxy.py` | 内容寻址代理文件生成与验证 |
| 最终 QA | `tools/video/final_qa.py` | quick/full 两级媒体、音频和字幕质检 |
| 审批组 | `lib/approval_groups.py` | bundle 构建、批准、拒绝、失效和恢复 |
| 生产锁 | `lib/production_lock.py` | 锁定关键决策并计算重审批影响 |
| 快线流程 | `pipeline_defs/cinematic-fast.yaml` | 两道人工门的声明式 pipeline |
| Backlot 缓存 | `backlot/state_cache.py` | 基于状态文件签名缓存派生 board state |
| 通用字幕 | `remotion-composer/src/components/SafeCaptionTrack.tsx` | 安全区、宋体、动态字号、去尾标点、克制花字 |

## Chunk 1: Artifact、媒体与音频缓存

### Task 1: 注册快线 Artifact 并建立双哈希契约

**Files:**
- Create: `lib/artifact_hashing.py`
- Create: `lib/artifact_io.py`
- Create: `tests/lib/test_artifact_hashing.py`
- Create: `tests/lib/test_artifact_io.py`
- Create: `tests/contracts/test_fastline_artifact_contracts.py`
- Create: `schemas/artifacts/media_index.schema.json`
- Create: `schemas/artifacts/reference_fingerprint.schema.json`
- Create: `schemas/artifacts/production_lock.schema.json`
- Create: `schemas/artifacts/approval_bundle.schema.json`
- Create: `schemas/artifacts/asset_plan.schema.json`
- Create: `schemas/artifacts/change_impact.schema.json`
- Create: `schemas/artifacts/render_plan.schema.json`
- Create: `schemas/artifacts/final_props.schema.json`
- Create: `schemas/artifacts/sample_report.schema.json`
- Modify: `requirements.txt`
- Modify: `setup.py`
- Modify: `schemas/artifacts/__init__.py:10-34`
- Modify: `schemas/checkpoints/checkpoint.schema.json`
- Modify: `lib/pipeline_loader.py:90-165`
- Modify: `lib/checkpoint.py:30-155`

- [ ] **Step 1: 写双哈希失败测试**

```python
# tests/lib/test_artifact_hashing.py
from lib.artifact_hashing import attach_hashes, semantic_sha256, verify_hashes

def test_semantic_hash_ignores_only_declared_volatile_fields():
    a = {"version": "1.0", "project_id": "p", "created_at": "t1", "payload": {"x": 1}}
    b = {"version": "1.0", "project_id": "p", "created_at": "t2", "payload": {"x": 1}}
    assert semantic_sha256(a) == semantic_sha256(b)
    b["payload"]["x"] = 2
    assert semantic_sha256(a) != semantic_sha256(b)

def test_integrity_hash_detects_provenance_mutation():
    record = attach_hashes({"version": "1.0", "project_id": "p", "created_at": "t"})
    assert verify_hashes(record).valid
    record["created_at"] = "changed"
    assert not verify_hashes(record).valid
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_artifact_hashing.py -v`

Expected: FAIL，错误包含 `No module named 'lib.artifact_hashing'`。

- [ ] **Step 3: 添加 RFC 8785 依赖和最小哈希实现**

在 `requirements.txt` 与 `setup.py` 增加同一约束：`rfc8785>=0.1.4,<1`。核心实现保持纯函数：

```python
# lib/artifact_hashing.py
from dataclasses import dataclass
import hashlib
from typing import Any
import rfc8785

SEMANTIC_OMIT_PATHS = frozenset({
    ("artifact_sha256",), ("semantic_sha256",), ("created_at",),
    ("metadata", "run_id"), ("metadata", "event_id"),
    ("metadata", "absolute_project_path"),
})

def _without_paths(value: Any, omitted: frozenset[tuple[str, ...]], path=()) -> Any:
    if isinstance(value, dict):
        return {
            k: _without_paths(v, omitted, path + (k,))
            for k, v in value.items() if path + (k,) not in omitted
        }
    if isinstance(value, list):
        return [_without_paths(v, omitted, path + (str(i),)) for i, v in enumerate(value)]
    return value

def canonical_bytes(value: dict[str, Any], omitted=frozenset()) -> bytes:
    return rfc8785.dumps(_without_paths(value, omitted))

def semantic_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value, SEMANTIC_OMIT_PATHS)).hexdigest()

def artifact_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value, frozenset({("artifact_sha256",)}))).hexdigest()

def attach_hashes(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["semantic_sha256"] = semantic_sha256(result)
    result["artifact_sha256"] = artifact_sha256(result)
    return result

@dataclass(frozen=True)
class HashVerification:
    valid: bool
    semantic_valid: bool
    artifact_valid: bool

def verify_hashes(value: dict[str, Any]) -> HashVerification:
    semantic_valid = value.get("semantic_sha256") == semantic_sha256(value)
    artifact_valid = value.get("artifact_sha256") == artifact_sha256(value)
    return HashVerification(semantic_valid and artifact_valid, semantic_valid, artifact_valid)
```

- [ ] **Step 4: 安装锁定版本的 JCS 依赖**

Run: `.venv/bin/python -m pip install 'rfc8785>=0.1.4,<1'`

Expected: `Successfully installed rfc8785-...` 或 `Requirement already satisfied`。这是需要网络/包安装权限的动作，执行 agent 必须先请求批准；若批准后仍无法安装，停止该 Task 并报告 blocker，不能用近似 `json.dumps(sort_keys=True)` 冒充 RFC 8785。

- [ ] **Step 5: 运行哈希测试并确认通过**

Run: `.venv/bin/python -m pytest tests/lib/test_artifact_hashing.py -v`

Expected: PASS。

- [ ] **Step 6: 写 Artifact Envelope 与原子 I/O 失败测试**

新 fastline checkpoint 不再在 `artifacts` 字段里混用“原始 dict 或字符串路径”，而使用兼容 envelope；旧 checkpoint 仍可读：

```python
def test_write_artifact_atomic_returns_verified_envelope(tmp_path):
    envelope = write_artifact_atomic(
        tmp_path / "artifacts" / "media_index.json",
        "media_index",
        valid_media_index(),
    )
    assert envelope["name"] == "media_index"
    assert envelope["path"] == "artifacts/media_index.json"
    assert load_artifact_envelope(tmp_path, envelope)["version"] == "1.0"
```

Envelope v2 固定为：

```json
{
  "name": "media_index",
  "path": "artifacts/media_index.json",
  "semantic_sha256": "<64 hex>",
  "artifact_sha256": "<64 hex>",
  "data": {"...": "validated artifact snapshot"}
}
```

测试覆盖临时文件写失败不覆盖旧文件、path escape 被拒绝、disk data 与 embedded data 不同被拒绝、hash replay 失败被拒绝。

- [ ] **Step 7: 运行 Artifact I/O 测试并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_artifact_io.py -v`

Expected: FAIL，模块不存在。

- [ ] **Step 8: 实现 Artifact I/O 并扩展 checkpoint schema**

`lib/artifact_io.py` 暴露 `write_artifact_atomic()`、`load_artifact_envelope()`、`unwrap_checkpoint_artifact()`。写入必须 `flush + fsync + os.replace`；path 必须是 project-relative 且位于 `artifacts/`。checkpoint schema 的 `artifacts.additionalProperties` 改为 `oneOf`：legacy raw object/string 或上述 v2 envelope。

`lib/checkpoint.py::_validate_artifacts_for_stage()` 对 envelope 先加载磁盘、重算双 hash、比较 embedded snapshot，再调用 `validate_artifact()`；所有新 fastline checkpoint 必须写 envelope，legacy pipeline 可继续写 raw artifact。

- [ ] **Step 9: 为九类 artifact 写 schema 合约测试**

`tests/contracts/test_fastline_artifact_contracts.py` 必须枚举九个名称，断言：schema 文件存在、名称出现在 `ARTIFACT_NAMES`、缺 envelope 字段失败、最小合法样例通过。所有新 schema 统一要求：

```json
{
  "required": [
    "version", "project_id", "created_at", "producer", "input_hashes",
    "semantic_sha256", "artifact_sha256"
  ],
  "properties": {
    "version": {"type": "string"},
    "project_id": {"type": "string", "minLength": 1},
    "created_at": {"type": "string", "format": "date-time"},
    "producer": {"type": "string", "minLength": 1},
    "input_hashes": {"type": "object", "additionalProperties": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
    "semantic_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "artifact_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}
  }
}
```

九个 schema 的业务结构必须在文件内完整定义，并由 fixture 逐字段 mutation 测试，不能只检查字段是否存在：

| Artifact | 业务结构与约束 |
|---|---|
| `media_index` | `analysis_version:string`; `entries:array`，item 必须含 `path:string`、`media_type:video|audio|image`、`fingerprint:{content_sha256,size_bytes>=0,mtime_ns>=0}`、`probe:object`、`scenes:array`、`representative_frames:array[string]`、`audio:{has_track:boolean,usable:boolean}`、`best_ranges:array[{start_seconds>=0,end_seconds>start}]`、`quality_risks:array[string]` |
| `reference_fingerprint` | `content_sha256:64hex`、`analysis_depth:transcript_only|standard|deep`、`analyzer_version:string`、`canonical_request:object`、`output_digest:64hex`、`abstract_structure:object`; 禁止任何 reference media path 出现在 final asset list |
| `production_lock` | `lock_version:integer>=1`; `locked_values` 明确列出 `script/narration/tts/bgm/mix/font/captions/cta/platform/output/render_runtime/composition_mode`；runtime 枚举 `remotion|hyperframes|ffmpeg`；`decision_revision_ids:array[string]` unique |
| `approval_bundle` | `bundle_id:string`、`bundle_version:integer>=1`、`group:string`、`terminal_stage:string`、`members:array[string]` unique、`artifact_refs:array`（每项为 envelope ref 四个 hash/path 字段）、`status:awaiting_human|approved|rejected|superseded`、可选 `approved_by/rejected_reason/superseded_by` |
| `asset_plan` | `planned_assets:array`，item 含 `id/type/provider/model/cost_estimate_usd/paid/output_path/source_stage`；`paid_generation_approved:boolean`；creative-lock 前必须为 false，且不得出现 `exists:true` 的付费产物 |
| `change_impact` | 两个 lock hash 均为 64hex；`route:no_render|mux_only|full_render`（P1 schema 才加入 incremental）；`reasons:array[string] minItems=1`；`dirty_scene_ids:array[string]` unique；`reopen_creative_lock/reopen_sample:boolean` |
| `render_plan` | `mode:sample|full|mux_only`；`profile` 当前只允许已注册 profile 名；两个 timeline hash 为 64hex；`audio:{path,sha256}`；mux_only 时条件要求 `video_master:{path,sha256,profile_hash,visual_timeline_hash}`；sample 时条件要求 `sample:{startFrame,endFrameExclusive,scale=0.5,qaMode=quick}` |
| `final_props` | `compositionId:string`、`fps=30`、`width=1080`、`height=1920`、`durationInFrames>=1`、`footage:object[string]`、`scenes:array`（字段沿用 `id/assetId/footageKey/fromFrame/toFrameExclusive/durationInFrames/sourceInSeconds/sourceOutSeconds/playbackRate/playbackMode`）、`captions:array[{text,startMs,endMs,timestampMs,confidence}]`、`audio:{mix,assetId}` |
| `sample_report` | 两个 source hash 为 64hex；`window:{startFrame,endFrameExclusive,scale}`；`output_path:string`；`probe:{width=540,height=960,fps=30,frame_count}`；`qa:object`；`status:pass|revise|fail` |

`additionalProperties:false` 用于这些新 v1 fastline schema 的已列出业务对象；确需 provider 扩展的 `canonical_request/probe/abstract_structure` 明确保留 `additionalProperties:true`。现有旧 artifact 的兼容通过其自身 schema version 分支处理，不用放宽新治理对象。

- [ ] **Step 10: 运行 schema 测试并确认失败**

Run: `.venv/bin/python -m pytest tests/contracts/test_fastline_artifact_contracts.py -v`

Expected: FAIL，指出 schema 未创建或名称未注册。

- [ ] **Step 11: 创建九个 schema 并注册名称**

在 `schemas/artifacts/__init__.py` 将九个名称加入 `ARTIFACT_NAMES`；在 `lib/checkpoint.py::SUPPLEMENTARY_ARTIFACTS` 同步加入，确保任何嵌入 checkpoint 的新 artifact 都会实际校验。checkpoint 对新 artifact 保存 envelope，不再依靠字符串 path 绕过 schema。

在 `lib/pipeline_loader.py` 增加：

```python
def get_stage_produces(manifest: dict, stage_name: str) -> list[str]:
    for stage in manifest["stages"]:
        if stage["name"] == stage_name:
            return list(stage.get("produces", []))
    return []
```

把 `_validate_artifacts_for_stage()` 改为接收 `pipeline_type`，当状态为 `completed|awaiting_human` 时优先加载 manifest 并要求 `get_stage_produces()` 的全部 artifact；仅在 manifest 不可用时回退 `CANONICAL_STAGE_ARTIFACTS`。

- [ ] **Step 12: 运行合约与 checkpoint 回归**

Run: `.venv/bin/python -m pytest tests/lib/test_artifact_io.py tests/contracts/test_fastline_artifact_contracts.py tests/lib/test_checkpoint_prerequisites.py tests/contracts/test_phase0_contracts.py -v`

Expected: PASS，现有 pipeline 未声明的新 artifact 不应被强制要求。

- [ ] **Step 13: 逻辑提交**

```bash
git add requirements.txt setup.py lib/artifact_hashing.py lib/artifact_io.py lib/pipeline_loader.py lib/checkpoint.py schemas/artifacts/__init__.py schemas/artifacts/media_index.schema.json schemas/artifacts/reference_fingerprint.schema.json schemas/artifacts/production_lock.schema.json schemas/artifacts/approval_bundle.schema.json schemas/artifacts/asset_plan.schema.json schemas/artifacts/change_impact.schema.json schemas/artifacts/render_plan.schema.json schemas/artifacts/final_props.schema.json schemas/artifacts/sample_report.schema.json schemas/checkpoints/checkpoint.schema.json tests/lib/test_artifact_hashing.py tests/lib/test_artifact_io.py tests/contracts/test_fastline_artifact_contracts.py
git commit -m "feat: register fastline artifacts and canonical hashes"
```

### Task 2: 实现可校验、可恢复的通用 Artifact Cache

**Files:**
- Create: `lib/cache_io.py`
- Create: `lib/artifact_cache.py`
- Create: `tests/lib/test_cache_io.py`
- Create: `tests/lib/test_artifact_cache.py`
- Create: `tests/lib/test_events.py`
- Modify: `tools/base_tool.py:149-220`
- Modify: `lib/events.py`
- Modify: `tools/video/clip_cache.py`

- [ ] **Step 1: 写缓存命中、损坏和并发失败测试**

覆盖以下精确行为：首次 lookup 为 miss；store 后 hit；输出内容被修改后自动失效；sidecar 损坏后自动失效；两个 writer 不能得到半写记录；project hard-link/copy 被删除不影响共享 cache；cache 淘汰不删除项目 canonical 输出。

```python
def test_corrupt_cached_artifact_is_evicted(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    source = tmp_path / "audio.wav"
    source.write_bytes(b"valid")
    cache.store("k", [source], {"tool": "fake", "version": "1"})
    cached = cache.lookup("k", ["audio.wav"])
    Path(cached.artifacts[0]).write_bytes(b"changed")
    assert cache.lookup("k", ["audio.wav"]).hit is False
```

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_artifact_cache.py -v`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 写最小缓存实现**

先把锁、原子 JSON 和 link/copy 抽到 `lib/cache_io.py`，再让 `ArtifactCache` 和现有 `tools/video/clip_cache.py` 共用同一实现。唯一协议固定为：O_EXCL lock（写 PID/created_at，600 秒 stale）、同目录 temp + fsync + replace、hard-link 优先且 EXDEV/权限失败时 atomic copy。`tests/lib/test_cache_io.py` 对两种 cache 跑同一并发/崩溃 fixture。

ArtifactCache API 必须保持为：

```python
cache.lookup(key, expected_artifacts) -> CacheLookup
cache.store(key, artifacts, metadata) -> CacheRecord
cache.invalidate(key, reason) -> None
```

实现规则：

- 根目录固定由调用方传入，生产使用 `PROJECTS_DIR / ".cache" / "artifacts"`。
- `record.json` 先写同目录临时文件，`flush + os.fsync + os.replace` 后才可见。
- 使用 `lib.cache_io.exclusive_lock()`，不得再实现第二份锁协议。
- 每个缓存 artifact 保存 SHA-256、大小、相对路径和可选 probe 规则。
- 命中时重新校验 schema/version、所有 digest；媒体类额外调用注入的 validator。
- 不缓存 API key、authorization header、provider signature、signed URL。

- [ ] **Step 4: 让 BaseTool 事件携带缓存事实**

`ToolResult.data` 若包含 `cache_status: "hit"|"miss"`，`_instrument_execute()` 追加一条 `cache_hit` 或 `cache_miss` 事件。完整字段固定为：`event`、`tool`、`scene_id`、`depth`、`cache_key`、`reused_from`、`saved_seconds`、`cost_usd`、`ts`；hit 的 `cost_usd=0.0`，miss 的 cost 为 null。`lib/events.py` 保持 append-only，不建立第二份状态库。

- [ ] **Step 5: 运行缓存与事件测试**

Run: `.venv/bin/python -m pytest tests/lib/test_cache_io.py tests/lib/test_artifact_cache.py tests/lib/test_events.py tests/tools/test_clip_cache.py -v`

Expected: PASS；缓存命中事件 `cost_usd` 必须为 `0.0`，不得伪造 provider finish。

- [ ] **Step 6: 逻辑提交**

```bash
git add lib/cache_io.py lib/artifact_cache.py lib/events.py tools/base_tool.py tools/video/clip_cache.py tests/lib/test_cache_io.py tests/lib/test_artifact_cache.py tests/lib/test_events.py tests/tools/test_clip_cache.py
git commit -m "feat: add validated content-addressed artifact cache"
```

### Task 3: 将素材探测改为内容寻址媒体索引

**Files:**
- Create: `lib/media_index.py`
- Create: `tests/lib/test_media_index.py`
- Create: `tests/lib/test_source_media_review_cache.py`
- Create: `tests/tools/test_video_analyzer_cache.py`
- Create: `tests/tools/test_scene_detect_cache.py`
- Create: `tests/tools/test_frame_sampler_cache.py`
- Modify: `lib/source_media_review.py:1-320`
- Modify: `schemas/artifacts/source_media_review.schema.json`
- Modify: `tools/analysis/video_analyzer.py`
- Modify: `tools/analysis/scene_detect.py`
- Modify: `tools/analysis/frame_sampler.py`

- [ ] **Step 1: 写指纹与复用失败测试**

必须覆盖：byte-identical + 新 mtime 命中；复制到新路径命中；同路径内容变化 miss；同 size/mtime 内容变化仍 miss；算法版本变化 miss；抽帧文件损坏 miss；无音轨不调用 transcriber。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_media_index.py tests/lib/test_source_media_review_cache.py -v`

Expected: FAIL，`lib.media_index` 不存在或现有 source review 重复调用 analyzer。

- [ ] **Step 3: 实现内容指纹和 bounded parallel review**

`lib/media_index.py` 暴露：

```python
@dataclass(frozen=True)
class MediaFingerprint:
    content_sha256: str
    size_bytes: int
    mtime_ns: int

def fingerprint_media(path: Path) -> MediaFingerprint: ...
def build_media_index(files: list[Path], *, project_dir: Path,
                      registry, analysis_version: str,
                      max_workers: int | None = None) -> dict: ...
```

每次 run 初始化都流式读取文件计算 SHA-256；size/mtime 只用于显示和变更诊断，不能跳过内容哈希。这样才能保证“同路径、同 size/mtime、字节变化”必定 miss。`ThreadPoolExecutor` 的 worker 数固定为 `min(4, max(1, (os.cpu_count() or 2) // 2), max(1, len(files)))`；空文件列表直接返回合法空 index，不启动 executor。每个文件内部按 `ffprobe -> scene_detect/frame_sampler -> audio decision` 执行，避免同一输出目录竞态。

抽帧目录必须是：

```text
projects/<id>/analysis/media/<content_sha256>/<analysis_version>/frames/
```

调用 `frame_sampler` 时显式传入支持的 `strategy="count"` 与 `count=4`；deep reference review 可选择 `scene_guided` 并传 `scene_boundaries/max_frames`。不得使用不存在的 `uniform`，strategy 及其必需参数都进入 cache key。

- [ ] **Step 4: 重构 source_media_review 消费 media_index**

删除按文件名推断内容的路径；`review_source_media()` 接受可选 `media_index`，对已验证记录复用 probe/scenes/frames，只补充真正的视觉观察、`best_ranges`、`usable_audio` 和 `quality_risks`。同步扩展 `source_media_review.schema.json`，为这些字段及 `transcription_skipped_reason` 定义类型；没有音轨或音轨不可用时明确记录跳过原因。

`video_analyzer` deep 输出同时生成 `reference_fingerprint`；其 `canonical_request/output_digest` 必须落盘，通过 `write_artifact_atomic()` 写入 research-owned artifact，并以 envelope 嵌入 research checkpoint。scene/frame tools 的 key 加入 tool version、算法版本、content SHA 和规范化参数；测试覆盖相同 reference 复用、analyzer version 变化、output digest 损坏和 path 变化。

- [ ] **Step 5: 运行媒体测试与现有 source-review 回归**

Run: `.venv/bin/python -m pytest tests/lib/test_media_index.py tests/lib/test_source_media_review_cache.py tests/lib/test_source_media_review_empty.py tests/tools/test_video_analyzer_cache.py tests/tools/test_scene_detect_cache.py tests/tools/test_frame_sampler_cache.py tests/tools/test_scene_detect_lavfi_escape.py -v`

Expected: PASS；第二次运行 analyzer/ffprobe 调用数为 0，损坏帧场景调用数为 1。

- [ ] **Step 6: 逻辑提交**

```bash
git add lib/media_index.py lib/source_media_review.py schemas/artifacts/source_media_review.schema.json tools/analysis/video_analyzer.py tools/analysis/scene_detect.py tools/analysis/frame_sampler.py tests/lib/test_media_index.py tests/lib/test_source_media_review_cache.py tests/tools/test_video_analyzer_cache.py tests/tools/test_scene_detect_cache.py tests/tools/test_frame_sampler_cache.py
git commit -m "feat: cache source and reference media analysis by content"
```

### Task 4: 为 Doubao TTS、字幕与混音补齐 provider-complete Cache Key

**Files:**
- Create: `tests/tools/test_doubao_tts_cache.py`
- Create: `tests/tools/test_audio_mixer_cache.py`
- Create: `tests/tools/test_subtitle_cache.py`
- Modify: `tools/base_tool.py:268-395`
- Modify: `tools/audio/tts_selector.py:120-205`
- Modify: `tools/audio/doubao_tts.py:160-330`
- Modify: `tools/audio/audio_mixer.py:199-330`
- Modify: `tools/subtitle/subtitle_gen.py:1-180`
- Modify: `tools/cost_tracker.py:160-185`
- Modify: `tests/tools/test_cost_tracker_governance.py`

- [ ] **Step 1: 写 provider 请求碰撞测试**

Doubao 参数化测试逐项改变其真实请求字段 `text`、`voice_id`、`resource_id`、`speech_rate`、`sample_rate`、`format`、`enable_timestamp`、`disable_markdown_filter` 和 tool/resource revision，断言 key 全部变化；只改变 `output_path`、request UUID、API key、signed URL 时 key 不变。另建支持 `language/input_type/instructions/style` 的 fake provider，证明 selector 会哈希 provider 返回的完整 canonical request，而不是硬编码 Doubao 字段；Doubao 当前未消费的字段不得虚假改变其 key。

- [ ] **Step 2: 写 mixer/subtitle 内容哈希测试**

Mixer key 必须包含每条输入音轨的内容 SHA、音量、起点、淡入淡出、ducking、normalize、LUFS、target duration、segments、FFmpeg 与 tool version。Subtitle key 必须包含 segments 内容、格式、每 cue 字/词数、语言、去尾标点、safe-zone 和 emphasis rules。

- [ ] **Step 3: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/tools/test_doubao_tts_cache.py tests/tools/test_audio_mixer_cache.py tests/tools/test_subtitle_cache.py -v`

Expected: FAIL；当前 `idempotency_key_fields` 会产生至少一个碰撞。

- [ ] **Step 4: 在 BaseTool 定义 provider-resolved request 契约**

`BaseTool` 增加默认返回 `None` 的 opt-in 方法：

```python
def canonical_request(self, inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Return the fully defaulted, secret-free provider request used for caching."""
    return None

def cache_artifact_contract(self, inputs: dict[str, Any]) -> list[CacheArtifactSpec]:
    return []
```

Selector 不能自己猜 provider 默认值。它先选定具体 tool，再由 provider 的 `canonical_request()` 生成 key；`CacheArtifactSpec` 描述 `role/suffix/required/validator`。没有实现这两个方法的 provider 不启用跨运行 cache。

- [ ] **Step 5: 在 Doubao provider 内物化规范化请求**

`DoubaoTTS` 覆盖公开的 `canonical_request(inputs)`，内容与 `_submit_body()` 一致，但删除 `unique_id` 和 secret/signed URL，并加入 `provider`、`SUBMIT_URL`、`resource revision`、`tool.version`；所有默认值在这里物化。它同时返回 audio + metadata artifact contract；缓存命中前用 ffprobe 验证音频，并在 `enable_timestamp=true` 时验证 metadata 中 `sentences`。

`TTSSelector.input_schema.operation` 扩展为 `rank|prepare|materialize|generate`，缓存所有权只在 selector：

1. `prepare` 选择 provider，构造 `sha256(JCS({provider,endpoint,model_revision,tool_version,canonical_request}))`，只读 lookup，返回 `cache_hit:boolean`、`cache_status`、`cache_key`、`estimated_cost_usd`；不调用 provider、不写 output。
2. `materialize` 只允许缓存路径：重新校验同一 key，hit 时写到显式 output path 并返回 `cost_usd=0.0/cache_hit=true/provider_called=false`；若 prepare 之后 cache 损坏/失效，返回 structured miss，**不得调用 provider**。
3. `generate` 是唯一允许 provider call 的操作；cache miss 时要求 `cost_log_path + reservation_id`，并用 `CostTracker.assert_reserved()` 验证 reservation 的 tool、operation、amount/status 后才调用 provider。结果验证后 store。
4. 直接调用 `DoubaoTTS.execute()` 保持兼容但没有跨运行 selector cache；fastline director 必须走 `tts_selector`。

- [ ] **Step 6: 为 mixer 和 subtitle 接入 opt-in cache**

只有确定性操作 opt in；cache hit 时将共享对象 hard-link/copy 到调用方明确的 `output_path`。任何读取失败、digest 不符、ffprobe 失败或 timestamp sidecar 缺失都必须自动 miss 并重建。

所有 cache-aware 结果同时返回新字段 `cache_status:"hit|miss"` 和兼容字段 `cache_hit:boolean`；Backlot 使用前者显示事件，现有消费者可继续读取后者。

- [ ] **Step 7: 在成本预留前完成 Cache Prepare**

`CostTracker` 增加 `record_reuse(tool, cache_key, reused_from, saved_seconds)` 与只读 `assert_reserved(entry_id, tool, operation, estimated_usd)`。`sample-director` 是明确调用方：先 `tts_selector.prepare`；hit -> 调用 `materialize`，只有 materialize 成功后才 `record_reuse`；materialize 返回 miss 或初始 miss -> 检查已批准 production lock -> `estimate/reserve` -> 带 reservation 调用 `generate` -> `reconcile`。测试在 prepare 与 materialize 之间破坏 cache，断言 provider 调用数和 reuse 记录数均为 0；随后未带 reservation 的 generate 必须失败，带有效 reservation 才允许 provider 调用。

- [ ] **Step 8: 运行新测试与音频回归**

Run: `.venv/bin/python -m pytest tests/tools/test_doubao_tts_cache.py tests/tools/test_audio_mixer_cache.py tests/tools/test_subtitle_cache.py tests/tools/test_cost_tracker_governance.py tests/tools/test_audio_mixer_*.py tests/tools/test_subtitle_timestamps.py -v`

Expected: PASS；mock provider 在第二次相同请求中调用数为 0；改变任一输出字段调用数变为 1。

- [ ] **Step 9: 逻辑提交**

```bash
git add tools/base_tool.py tools/audio/tts_selector.py tools/audio/doubao_tts.py tools/audio/audio_mixer.py tools/subtitle/subtitle_gen.py tools/cost_tracker.py tests/tools/test_doubao_tts_cache.py tests/tools/test_audio_mixer_cache.py tests/tools/test_subtitle_cache.py tests/tools/test_cost_tracker_governance.py
git commit -m "feat: cache resolved TTS subtitle and mix outputs"
```

## Chunk 2: 唯一时间轴、最小渲染与 QA v2

### Task 5: 让 `final_props.json` 成为唯一生产时间轴

**Files:**
- Create: `lib/final_props.py`
- Create: `tests/lib/test_final_props.py`
- Create: `tests/projects/test_transparent_mat_final_contract.py`
- Modify: `schemas/artifacts/final_props.schema.json`
- Modify: `projects/transparent-table-mat-remix-01/artifacts/final_props.json`
- Modify: `projects/transparent-table-mat-remix-01/Root.tsx:1-92`
- Modify: `projects/transparent-table-mat-remix-01/Composition.tsx:24-52,771-832`

- [ ] **Step 1: 写半开区间和播放覆盖失败测试**

```python
# tests/lib/test_final_props.py
import pytest
from lib.final_props import FinalPropsError, validate_final_props

def test_normal_scene_obeys_half_open_and_source_duration_math(valid_props):
    scene = valid_props["scenes"][0]
    scene.update({
        "fromFrame": 0, "toFrameExclusive": 69, "durationInFrames": 69,
        "sourceInSeconds": 0.4, "sourceOutSeconds": 2.7, "playbackRate": 1.0,
        "playbackMode": "normal",
    })
    validate_final_props(valid_props)

def test_boundary_or_source_math_drift_is_rejected(valid_props):
    valid_props["scenes"][0]["durationInFrames"] += 2
    with pytest.raises(FinalPropsError):
        validate_final_props(valid_props)
```

同时覆盖：不允许未声明 gap/overlap；最后 scene end 等于顶层 duration；caption/audio 不越界；source 不存在；`loop|hold` 必须显式声明；normal 模式公式误差不超过 1 帧。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_final_props.py -v`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `lib/final_props.py`**

公开 API：

```python
class FinalPropsError(ValueError): ...

def validate_final_props(props: dict, *, project_dir: Path | None = None) -> dict:
    fps = int(props["fps"])
    expected_from = 0
    for scene in props["scenes"]:
        start = int(scene["fromFrame"])
        end = int(scene["toFrameExclusive"])
        duration = int(scene["durationInFrames"])
        if end - start != duration:
            raise FinalPropsError("scene duration does not match half-open range")
        if not props.get("allowTimelineGaps", False) and start != expected_from:
            raise FinalPropsError("timeline gap or overlap")
        if scene.get("playbackMode", "normal") == "normal":
            source_frames = round(
                (float(scene["sourceOutSeconds"]) - float(scene["sourceInSeconds"]))
                * fps / float(scene.get("playbackRate", 1.0))
            )
            if abs(duration - source_frames) > 1:
                raise FinalPropsError("source duration and playback speed disagree")
        elif scene["playbackMode"] not in {"loop", "hold"}:
            raise FinalPropsError("unknown playbackMode")
        expected_from = end
    if expected_from != int(props["durationInFrames"]):
        raise FinalPropsError("top-level duration disagrees with scene timeline")
    return props
```

校验器还需用 ffprobe/source metadata 验证 `sourceOutSeconds` 不超过源时长；测试中通过注入 probe map 避免调用真实 FFmpeg。字段沿用当前项目已有的 `id/assetId/footageKey/sourceInSeconds/sourceOutSeconds/playbackRate`，避免为了命名迁移重写已验证镜头数据；禁止同时引入第二套 alias。

- [ ] **Step 4: 运行 validator 测试并确认通过**

Run: `.venv/bin/python -m pytest tests/lib/test_final_props.py -v`

Expected: PASS。

- [ ] **Step 5: 写项目时间轴单一来源失败测试**

`tests/projects/test_transparent_mat_final_contract.py` 读取 `final_props.json` 和两个 TSX 文件，断言：

- `final_props` 通过 schema 与 Python validator。
- `Root.tsx` 不包含 `durationInFrames={900}`、`finalCaptions` 或生产 footage 列表。
- `Root.tsx` 不再注册独立 `TransparentMatSample`；样片必须由 final props + render window 生成。
- `Composition.tsx` 不包含 `from={0} duration={20}` 等生产时间常量。
- `calculateFinalMetadata` 使用传入 props。
- TSX 中所有生产 `Sequence` 都来自 `props.scenes.map(...)`。
- Scene01-Scene16 中不再硬编码生产 `trimSeconds/playbackRate/durationFrames`；修改 final props 中对应字段会传到 `FinalClip`。

- [ ] **Step 6: 运行项目测试并确认失败**

Run: `.venv/bin/python -m pytest tests/projects/test_transparent_mat_final_contract.py -v`

Expected: FAIL，指出重复的 900 帧、字幕或镜头边界。

- [ ] **Step 7: 重构透明桌垫 Remotion 入口**

`FinalRenderProps` 至少包含：

```ts
export type TimelineScene = {
  id: string;
  assetId: string;
  footageKey: string;
  fromFrame: number;
  toFrameExclusive: number;
  durationInFrames: number;
  sourceInSeconds: number;
  sourceOutSeconds: number;
  playbackRate: number;
  playbackMode: "normal" | "loop" | "hold";
};

export type FinalRenderProps = {
  compositionId: string;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  footage: Record<string, string>;
  scenes: TimelineScene[];
  captions: Caption[];
  audio: {mix: string};
};
```

`FinalScene` 用 `scenes.map(scene => <Sequence from={scene.fromFrame} durationInFrames={scene.durationInFrames}>...)`。视觉组件映射可继续按 `scene.id -> Scene01...Scene16` 保存，但每个 Scene 组件统一接收 `{scene, src}`，调用 `FinalClip` 时使用 `trimSeconds={scene.sourceInSeconds}`、`playbackRate={scene.playbackRate}`、`durationFrames={scene.durationInFrames}`；所有时长、素材 path、source in/out 和 playback rate 必须取自 scene props，素材由 `footage[scene.footageKey]` 解析。纯视觉参数（label、遮罩、scale 动画）仍可留在 bespoke 组件中。

`Root.tsx` 只保留最小 Studio fixture；生产渲染通过 `--props=projects/.../artifacts/final_props.json`。`calculateFinalMetadata({props})` 返回 props 的 duration/fps/width/height。

- [ ] **Step 8: 编译/枚举 composition 并运行回归**

Run: `cd remotion-composer && npx remotion compositions ../projects/transparent-table-mat-remix-01/index.tsx --props=../projects/transparent-table-mat-remix-01/artifacts/final_props.json --public-dir=../projects/transparent-table-mat-remix-01/public`

Expected: 列出 `TransparentMatFinal`，metadata 为 `900 frames, 1080x1920, 30fps`，不执行 render。

Run: `.venv/bin/python -m pytest tests/lib/test_final_props.py tests/projects/test_transparent_mat_final_contract.py -v`

Expected: PASS。

- [ ] **Step 9: 逻辑提交**

```bash
git add lib/final_props.py schemas/artifacts/final_props.schema.json projects/transparent-table-mat-remix-01 tests/lib/test_final_props.py tests/projects/test_transparent_mat_final_contract.py
git commit -m "refactor: make final props the only production timeline"
```

### Task 6: 建立内容寻址代理和 Remotion Runtime Preflight

**Files:**
- Create: `tools/video/media_proxy.py`
- Create: `lib/remotion_runtime.py`
- Create: `tests/tools/test_media_proxy_cache.py`
- Create: `tests/tools/test_remotion_runtime.py`
- Modify: `lib/media_profiles.py`
- Modify: `schemas/artifacts/asset_manifest.schema.json`
- Modify: `tools/video/video_compose.py:224-330`
- Modify: `tools/tool_registry.py:275-305`
- Modify: `tests/contracts/test_phase0_contracts.py`
- Modify: `Makefile:9,100-101`

- [ ] **Step 1: 写 proxy key 与本机 Chromium 探测测试**

测试 source 内容相同但路径不同会命中；crop/profile/codec/pixel format 任一变化会 miss；代理损坏会重建。Runtime 测试必须模拟多个 Chromium 路径，断言已存在的可执行文件优先于下载建议。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/tools/test_media_proxy_cache.py tests/tools/test_remotion_runtime.py -v`

Expected: FAIL，两个模块不存在。

- [ ] **Step 3: 实现 `MediaProxy` BaseTool**

输入 schema：`input_path`、`output_path`、`profile`、`width`、`height`、`fit`、`codec`、`pixel_format`。key 为 source SHA + 全部 profile 字段 + FFmpeg/tool version。输出必须 ffprobe 验证并记录 source relationship；命中时不得运行 FFmpeg。`asset_manifest` 的 proxy asset 明确保存 `source_content_sha256/proxy_cache_key/profile/source_path`，schema 和测试共同验证 provenance。

- [ ] **Step 4: 实现 runtime probe**

`probe_remotion_runtime()` 返回：

```python
{
  "node_version": "...",
  "remotion_version": "...",
  "chromium_executable": "/absolute/path/or/null",
  "ffmpeg_version": "...",
  "fonts": {"Songti SC": True},
  "composition_id": "TransparentMatFinal",
  "props_valid": True,
  "media_valid": True,
  "recommended_concurrency": 4,
  "warnings": [],
}
```

Chromium 顺序：显式配置 -> Remotion 缓存 -> 常见 macOS Chrome/Chromium 应用 -> PATH。只有全部不存在时才返回安装建议；不得主动下载。

- [ ] **Step 5: 注册快线输出 profile**

在 `lib/media_profiles.py` 增加 `social_vertical_1080p30`：1080x1920、30fps、libx264、yuv420p、AAC、48kHz、2 channels、CRF 18。为 `MediaProfile` 增加默认 `audio_sample_rate=48000` 与 `audio_channels=2`，并扩展 `tests/contracts/test_phase0_contracts.py` 证明 profile 可发现且 FFmpeg args 完整。

- [ ] **Step 6: 接入 `video_compose.get_info()` 和 `make preflight`**

`video_compose.get_info()` 增加 `remotion_runtime` 摘要但保持现有 `render_engines`。同步扩展 `tools/tool_registry.py::provider_menu()` 的 extra-key 白名单，使摘要不会丢失该字段。`make preflight` 改为先输出 `registry.provider_menu_summary()`，再输出 runtime probe；不得再打印完整 provider firehose。

- [ ] **Step 7: 运行测试与 preflight smoke**

Run: `.venv/bin/python -m pytest tests/tools/test_media_proxy_cache.py tests/tools/test_remotion_runtime.py tests/contracts/test_phase0_contracts.py -v`

Run: `make preflight`

Expected: PASS；输出明确显示本机 Chromium 路径、Remotion/FFmpeg 版本与字体状态，不触发下载。

- [ ] **Step 8: 逻辑提交**

```bash
git add tools/video/media_proxy.py lib/remotion_runtime.py lib/media_profiles.py schemas/artifacts/asset_manifest.schema.json tools/video/video_compose.py tools/tool_registry.py Makefile tests/tools/test_media_proxy_cache.py tests/tools/test_remotion_runtime.py tests/contracts/test_phase0_contracts.py
git commit -m "feat: add media proxy cache and remotion runtime preflight"
```

### Task 7: 实现 Change Impact、Render Plan 与安全的 `mux_only`

**Files:**
- Create: `lib/change_impact.py`
- Create: `lib/render_plan.py`
- Create: `tests/lib/test_render_plan.py`
- Create: `tests/tools/test_change_impact.py`
- Create: `tests/tools/test_video_compose_mux_only.py`
- Modify: `schemas/artifacts/change_impact.schema.json`
- Modify: `schemas/artifacts/render_plan.schema.json`
- Modify: `schemas/artifacts/render_report.schema.json`
- Modify: `tools/video/video_compose.py:78-205,342-430,1465-1635`
- Modify: `tests/tools/test_remotion_audio_mux.py`

- [ ] **Step 1: 写路由表失败测试**

```python
@pytest.mark.parametrize(("changed", "route"), [
    ({"audio.mix.gain"}, "mux_only"),
    ({"audio.bgm.sha256"}, "mux_only"),
    ({"narration.text"}, "full_render"),
    ({"captions.0.text"}, "full_render"),
    ({"scenes.n06.inSeconds"}, "full_render"),
    ({"metadata.notes"}, "no_render"),
])
def test_change_impact_routes_smallest_safe_path(changed, route): ...
```

P0 不允许 caption-only 或 scene stitch 假优化；只有音频像素无关变化可以 `mux_only`。

- [ ] **Step 2: 写 master provenance 拒绝测试**

覆盖：正确 master 成功；timeline hash 错、visual hash 错、profile hash 错、缺 master、H.265、非 yuv420p、非 1080x1920、非 30fps、音频时长漂移超过 1 帧均返回 `requires_full_render=true`，且不覆盖原文件。

- [ ] **Step 3: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/tools/test_change_impact.py tests/lib/test_render_plan.py tests/tools/test_video_compose_mux_only.py -v`

Expected: FAIL。

- [ ] **Step 4: 实现纯函数 change router**

`classify_change(previous_lock, current_lock, previous_props, current_props)` 返回 schema-valid artifact；比较基于 semantic hash 和字段路径，不依赖自然语言。路由枚举固定：`no_render | mux_only | full_render`，P1 才加入 `incremental`。

`lib/render_plan.py` 负责 schema 加载、profile lookup、master ffprobe/hash 校验、sample half-open window 转换和输出 provenance；`video_compose.py` 只消费其 `ValidatedRenderPlan`，避免继续把治理逻辑堆进已很大的 composer 文件。

- [ ] **Step 5: 扩展 `video_compose` render schema 和路由**

`operation="render"` 的 fastline 调用要求 `render_plan`。在检查 `asset_manifest` 之前先处理 `mode="mux_only"`：

```python
if render_plan["mode"] == "mux_only":
    validation = self._validate_video_master(render_plan)
    if not validation.ok:
        return ToolResult(success=False, data={"requires_full_render": True, "reasons": validation.reasons})
    shutil.copyfile(render_plan["video_master"]["path"], output_path)
    result = self._mux_external_audio(output_path, render_plan["audio"]["path"])
    return self._validate_muxed_profile(result, render_plan)
```

`_mux_external_audio()` 继续 `-c:v copy`，但明确输出 AAC 192kbps、48kHz、stereo、替换旧音轨并在 replace 前 ffprobe。失败时删除 temp，保留原 master/final。

`render_report` 必须记录 `render_plan_hash`、`render_mode`、`video_master_sha256`、`profile_hash`、`visual_timeline_hash` 和 `remotion_invoked`，让 QA/Backlot 能验证真实执行路径而不是从文件名猜测。

- [ ] **Step 6: 运行 mux 和旧回归**

Run: `.venv/bin/python -m pytest tests/tools/test_change_impact.py tests/lib/test_render_plan.py tests/tools/test_video_compose_mux_only.py tests/tools/test_remotion_audio_mux.py -v`

Expected: PASS；测试 spy 证明 `mux_only` 不调用 `_remotion_render()`。

- [ ] **Step 7: 逻辑提交**

```bash
git add lib/change_impact.py lib/render_plan.py schemas/artifacts/change_impact.schema.json schemas/artifacts/render_plan.schema.json schemas/artifacts/render_report.schema.json tools/video/video_compose.py tests/tools/test_change_impact.py tests/lib/test_render_plan.py tests/tools/test_video_compose_mux_only.py tests/tools/test_remotion_audio_mux.py
git commit -m "feat: route audio revisions through validated mux only"
```

### Task 8: 将 10-15 秒样片实现为真实 `sample` Render Mode

**Files:**
- Create: `tests/tools/test_video_compose_sample.py`
- Modify: `tools/video/video_compose.py:1858-2180`
- Modify: `schemas/artifacts/sample_report.schema.json`
- Modify: `schemas/artifacts/render_plan.schema.json`

- [ ] **Step 1: 写 sample window 失败测试**

测试 half-open `startFrame=180, endFrameExclusive=540` 被转换为 Remotion CLI `--frames=180-539`；输出 540x960、30fps、360 帧；caption/audio 保留原时间轴 offset；key 包含 final props hash、窗口、scale、audio hash、runtime/version。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/tools/test_video_compose_sample.py -v`

Expected: FAIL，当前 render 不理解 `render_plan.mode=sample`。

- [ ] **Step 3: 实现 sample adapter**

只改变输出尺寸与 frame range，不改 fps，不制作另一套 sample props。输出固定到：

```text
projects/<id>/assets/sample/sample-<cache-key>.mp4
```

样片窗口必须在 300-450 帧；若不满足直接 schema/输入失败。`sample_report` 记录 `final_props_hash`、`render_plan_hash`、窗口、实际 probe、quick QA 和 cache metadata。

- [ ] **Step 4: 运行 sample 测试**

Run: `.venv/bin/python -m pytest tests/tools/test_video_compose_sample.py -v`

Expected: PASS；mock Remotion 参数保持原 timeline frame number。

- [ ] **Step 5: 逻辑提交**

```bash
git add tools/video/video_compose.py schemas/artifacts/render_plan.schema.json schemas/artifacts/sample_report.schema.json tests/tools/test_video_compose_sample.py
git commit -m "feat: add first-class fastline sample rendering"
```

### Task 9: 用统一 `final_qa` 替换四帧/文件大小启发式检查

**Files:**
- Create: `lib/caption_layout.py`
- Create: `tools/video/final_qa.py`
- Create: `tests/lib/test_caption_layout.py`
- Create: `tests/tools/test_final_qa.py`
- Create: `tests/tools/test_video_compose_final_review.py`
- Create: `tests/fixtures/caption_layout/social_v1_cases.json`
- Create: `tests/fixtures/final_qa/README.md`
- Modify: `schemas/artifacts/final_review.schema.json`
- Modify: `tools/video/video_compose.py:2182-2590`
- Modify: `projects/transparent-table-mat-remix-01/CaptionTrack.tsx`
- Modify: `tests/tools/test_hyperframes_compose.py`

- [ ] **Step 1: 写 v1/v2 schema 兼容测试**

现有 v1 fixture 必须继续通过；v2 缺 `media_integrity`、`audio_loudness` 或 `caption_render` 必须失败。`final_review.version` 改为 `oneOf const 1.0/2.0`，用 `if/then` 只对 v2 增加 required checks。

- [ ] **Step 2: 写 quick/full 阈值测试**

测试命令构造和 parser，不把大型二进制提交到仓库。用 pytest fixture 在 `tmp_path` 生成短视频，覆盖：准确 profile、0.2 秒黑段、1.2 秒冻结、-20 LUFS、-0.2 dBTP、字幕越安全区、声明的 intentional black/freeze range。

- [ ] **Step 3: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_caption_layout.py tests/tools/test_final_qa.py -v`

Expected: FAIL，`tools.video.final_qa` 不存在或 v2 schema 不接受。

- [ ] **Step 4: 实现并注册 `FinalQA` BaseTool**

`execute({mode, input_path, expected_profile, caption_spec, allowed_black_ranges, allowed_freeze_ranges, output_path})`：

- quick：ffprobe、全片 decode smoke、代表帧、音频流、caption source/timeline、一帧内时长。
- full：`ffmpeg -v error -i ... -f null -`、`blackdetect=d=0.15:pix_th=0.10:pic_th=0.98`、`freezedetect=n=-50dB:d=1.00`、frame hash 复核、`ebur128=peak=true`、字幕 geometry/cue coverage、runtime lock。

Tool metadata 固定 `name="final_qa"`、`capability="analysis"`、`provider="ffmpeg"`、`determinism=DETERMINISTIC`，确保 registry 自动发现。测试必须断言 `registry.get("final_qa")` 可用；后续 fast manifest 的 sample/compose 都显式列出该工具。

字幕安全区不做虚假的 OCR 承诺：composition/render report 提交 `caption_render_mode`、caption props hash 与按同一确定性 CJK layout 算法得到的 `computed_boxes`；full QA 重算并逐框验证安全区，同时抽取首/中/尾 caption frames 供人工 spotcheck。缺 props hash 或 computed-box evidence 时 `caption_render.safe_zone_passed=false`。

`lib/caption_layout.py` 是 Python QA 的单一算法实现，`social_v1_cases.json` 固定中文长度、换行、字号和 box 期望；透明桌垫本地 CaptionTrack 与 P1 `SafeCaptionTrack.tsx` 都必须通过同一 fixture 的 parity 测试，但 atelier 组件仍保持项目本地实现。

固定 `social-v1` 阈值：

```text
duration <= 1 frame drift
fps <= 0.01 drift
H.264 / yuv420p / 1080x1920 / 30fps
AAC / 48kHz / stereo
black < 0.15s unless declared
freeze < 1.00s unless declared
-15.0 <= integrated LUFS <= -13.0
true peak <= -1.0 dBTP
2 <= LRA <= 12 LU
caption left/right >= 72px, top >= 120px, bottom >= 300px
```

- [ ] **Step 5: 把 `_run_final_review()` 降为 adapter**

`video_compose` 只组装 expected profile、caption declaration、proposal/runtime evidence 并调用 `FinalQA.execute()`；删除 PNG `<2KB` 黑帧和 `volumedetect` 作为最终判断的逻辑。quick 写 `sample_report`，full 才能批准最终交付。

- [ ] **Step 6: 运行 QA、compose 和 schema 回归**

Run: `.venv/bin/python -m pytest tests/lib/test_caption_layout.py tests/tools/test_final_qa.py tests/tools/test_video_compose_final_review.py tests/tools/test_hyperframes_compose.py tests/contracts/test_phase0_contracts.py -v`

Expected: PASS；故障 fixture 的 status 精确为 `fail|revise`，合法 fixture 为 `pass`。

- [ ] **Step 7: 逻辑提交**

```bash
git add lib/caption_layout.py tools/video/final_qa.py tools/video/video_compose.py schemas/artifacts/final_review.schema.json projects/transparent-table-mat-remix-01/CaptionTrack.tsx tests/lib/test_caption_layout.py tests/tools/test_final_qa.py tests/tools/test_video_compose_final_review.py tests/tools/test_hyperframes_compose.py tests/fixtures/caption_layout/social_v1_cases.json tests/fixtures/final_qa/README.md
git commit -m "feat: add deterministic quick and full final QA"
```

## Chunk 3: 两道审批门、生产锁与快线 Pipeline

### Task 10: 扩展 Manifest Schema 以声明 Approval Groups

**Files:**
- Create: `tests/contracts/test_pipeline_approval_groups.py`
- Modify: `schemas/pipelines/pipeline_manifest.schema.json:1-170`
- Modify: `lib/pipeline_loader.py:90-180`

- [ ] **Step 1: 写 manifest 校验失败测试**

覆盖以下无效 manifest：group member 不存在；terminal 不在 member 中；两个 terminal；non-terminal member 仍 `human_approval_default=true`；terminal 未开 gate；两个 group 重复拥有同一 stage；required artifact 未由 member 产出。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/contracts/test_pipeline_approval_groups.py -v`

Expected: FAIL，schema 不认识 `approval_groups/approval_group/approval_group_terminal`。

- [ ] **Step 3: 扩展 schema**

顶层增加：

```json
"approval_groups": {
  "type": "object",
  "additionalProperties": {
    "type": "object",
    "required": ["members", "terminal_stage", "required_artifacts"],
    "properties": {
      "members": {"type": "array", "minItems": 2, "uniqueItems": true, "items": {"type": "string"}},
      "terminal_stage": {"type": "string"},
      "required_artifacts": {"type": "array", "uniqueItems": true, "items": {"type": "string"}}
    },
    "additionalProperties": false
  }
}
```

stage properties 增加 `approval_group: string` 与 `approval_group_terminal: boolean`。

- [ ] **Step 4: 添加语义校验 helper**

`load_pipeline()` 在 jsonschema 之后调用 `_validate_approval_groups(manifest)`。新增 getters：

```python
def get_approval_group(manifest: dict, stage_name: str) -> dict | None: ...
def get_approval_group_terminal(manifest: dict, group_name: str) -> str | None: ...
def stage_is_group_terminal(manifest: dict, stage_name: str) -> bool: ...
```

语义错误统一抛 `PipelineManifestError`，错误消息包含 pipeline/group/stage。

- [ ] **Step 5: 运行 manifest 合约回归**

Run: `.venv/bin/python -m pytest tests/contracts/test_pipeline_approval_groups.py tests/contracts/test_pipeline_manifest_categories.py tests/contracts/test_phase0_contracts.py -v`

Expected: PASS；没有 approval group 的旧 manifest 行为不变。

- [ ] **Step 6: 逻辑提交**

```bash
git add schemas/pipelines/pipeline_manifest.schema.json lib/pipeline_loader.py tests/contracts/test_pipeline_approval_groups.py
git commit -m "feat: declare grouped human approvals in pipeline manifests"
```

### Task 11: 实现 Approval Bundle 的原子批准、拒绝、失效与恢复

**Files:**
- Create: `lib/approval_groups.py`
- Create: `tests/lib/test_checkpoint_approval_groups.py`
- Modify: `schemas/artifacts/approval_bundle.schema.json`
- Modify: `schemas/checkpoints/checkpoint.schema.json`
- Modify: `lib/checkpoint.py:284-520`
- Modify: `tests/lib/test_checkpoint_prerequisites.py`
- Modify: `tests/backlot/test_gate_scenarios.py`

- [ ] **Step 1: 写 terminal gate 生命周期测试**

精确覆盖：

1. proposal/script/scene_plan 完成时不进入 `awaiting_human`。
2. assets terminal 缺任一 member checkpoint 或 required artifact 时不能 awaiting。
3. terminal awaiting 时 bundle 为 version 1、status awaiting_human。
4. approve 后先原子写 approved bundle，再把 terminal checkpoint 改为 completed + `human_approved=true` + exact bundle hash。
5. reject 后 terminal 保持 pending，history 保留旧版本。
6. 任一 semantic hash 改变后 bundle 变 superseded，sample 不能前进。
7. crash 留下未引用 bundle 时 resume 忽略它。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_checkpoint_approval_groups.py -v`

Expected: FAIL，当前 prerequisite 把每个 gated predecessor 当作独立审批。

- [ ] **Step 3: 实现 bundle service**

公开 API：

```python
def build_approval_bundle(project_dir: Path, manifest: dict, group_name: str) -> dict: ...
def approve_bundle(project_dir: Path, bundle_id: str, *, approved_by: str) -> Path: ...
def reject_bundle(project_dir: Path, bundle_id: str, *, reason: str) -> Path: ...
def reconcile_bundle(project_dir: Path, terminal_checkpoint: dict) -> BundleState: ...
```

Artifact ref 结构固定：`name/path/semantic_sha256/artifact_sha256`。每个状态写入不可变版本文件 `artifacts/approvals/<bundle_id>-v<version>-<status>.json`，checkpoint envelope 指向具体版本，避免历史 checkpoint 因 current 文件被覆盖而失真。写入顺序固定为 temp -> fsync -> replace；checkpoint 是唯一 canonical transition record。任何 exact hash 不符先报 integrity error；semantic hash 变化才表示审批内容变化并 supersede。

- [ ] **Step 4: 扩展 checkpoint schema 和 writer**

checkpoint 可选字段：`approval_group`、`approval_bundle_id`、`approval_bundle_version`。`write_checkpoint()` 对 group member 使用 manifest 规则：non-terminal 不单独 gate；terminal 才执行 grouped gate。`_enforce_stage_prerequisites()` 将已批准 terminal 作为整个 group 的批准证据，仍要求所有 member checkpoint 完成。

- [ ] **Step 5: 运行生命周期与旧 gate 回归**

Run: `.venv/bin/python -m pytest tests/lib/test_checkpoint_approval_groups.py tests/lib/test_checkpoint_prerequisites.py tests/backlot/test_gate_scenarios.py -v`

Expected: PASS；rejected bundle 后 terminal checkpoint 仍为 `awaiting_human`，只有 revised bundle 才增版本；旧 pipeline 的单 stage gate 行为完全不变。

- [ ] **Step 6: 逻辑提交**

```bash
git add lib/approval_groups.py lib/checkpoint.py schemas/artifacts/approval_bundle.schema.json schemas/checkpoints/checkpoint.schema.json tests/lib/test_checkpoint_approval_groups.py tests/lib/test_checkpoint_prerequisites.py tests/backlot/test_gate_scenarios.py
git commit -m "feat: add atomic approval bundles and grouped gates"
```

### Task 12: 锁定制作决策并用 Append-only Revision 驱动重审批

**Files:**
- Create: `lib/production_lock.py`
- Create: `tests/lib/test_production_lock.py`
- Modify: `schemas/artifacts/production_lock.schema.json`
- Modify: `lib/artifact_io.py`
- Modify: `lib/checkpoint.py:360-420`
- Modify: `schemas/artifacts/decision_log.schema.json`

- [ ] **Step 1: 写 lock diff 与 revision 测试**

关键字段必须覆盖：script/narration 文本、TTS provider/model/resource/voice/rate、BGM、mix profile、font、caption profile/emphasis、CTA、platform、resolution/fps/duration、render runtime、composition mode。

参数化期望：provider/voice/CTA/runtime/composition/narration change -> reopen creative lock；gain/LUFS only -> mux_only 且不 reopen；caption/scene timing -> reopen sample；metadata note -> no render/no reopen。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_production_lock.py -v`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 production lock**

```python
@dataclass(frozen=True)
class LockDiff:
    changed_paths: tuple[str, ...]
    reopen_creative_lock: bool
    reopen_sample: bool
    render_route: str

def build_production_lock(*, proposal, script, scene_plan, asset_plan, decisions) -> dict: ...
def compare_production_locks(previous: dict, current: dict) -> LockDiff: ...
def append_decision_revision(project_dir: Path, *, category: str, subject: str,
                             selected: object, superseded: object, reason: str) -> str: ...
```

Revision 必须使用新的 `decision_id`，但复用完全相同的 `(category, subject)`；旧值放入 `options_considered`，`rejected_because` 明确写 changed/superseded 原因。禁止就地修改历史 decision。

同时修正现有 `_merge_decision_log()`：canonical 文件迁移到 `projects/<id>/artifacts/decision_log.json`；必须先构造并验证 checkpoint 与 decision artifact，再用 `write_artifact_atomic()` 追加写入，最后原子替换 checkpoint。禁止在 checkpoint 验证失败时留下已修改的 decision log。读取端对旧的项目根 `decision_log.json` 保持只读迁移兼容。

- [ ] **Step 4: 写入与 approval bundle 的联动**

创建新 lock 时同时写 `change_impact`。若 `reopen_creative_lock`，归档并 supersede 当前 creative bundle；若只 `reopen_sample`，creative bundle 保持 approved，但 sample checkpoint 回到 awaiting；gain/LUFS only 不动 gate。

- [ ] **Step 5: 运行 lock 与 decision-log 回归**

Run: `.venv/bin/python -m pytest tests/lib/test_production_lock.py tests/lib/test_checkpoint_approval_groups.py tests/contracts/test_phase0_contracts.py -v`

Expected: PASS；project decision log 中同一 subject 的旧新记录都存在，Backlot 可按最新 revision 展示。

- [ ] **Step 6: 逻辑提交**

```bash
git add lib/production_lock.py lib/checkpoint.py schemas/artifacts/production_lock.schema.json schemas/artifacts/decision_log.schema.json tests/lib/test_production_lock.py
git commit -m "feat: lock production decisions and append revisions"
```

### Task 13: 新增 `cinematic-fast` Pipeline 和 Stage Director Wrappers

**Files:**
- Create: `pipeline_defs/cinematic-fast.yaml`
- Create: `skills/meta/fastline.md`
- Create: `skills/pipelines/cinematic-fast/executive-producer.md`
- Create: `skills/pipelines/cinematic-fast/research-director.md`
- Create: `skills/pipelines/cinematic-fast/proposal-director.md`
- Create: `skills/pipelines/cinematic-fast/script-director.md`
- Create: `skills/pipelines/cinematic-fast/scene-director.md`
- Create: `skills/pipelines/cinematic-fast/asset-director.md`
- Create: `skills/pipelines/cinematic-fast/sample-director.md`
- Create: `skills/pipelines/cinematic-fast/edit-director.md`
- Create: `skills/pipelines/cinematic-fast/compose-director.md`
- Create: `skills/pipelines/cinematic-fast/publish-director.md`
- Create: `tests/contracts/test_cinematic_fast_pipeline.py`
- Modify: `skills/meta/checkpoint-protocol.md`
- Modify: `AGENT_GUIDE.md:250-275`

- [ ] **Step 1: 写 pipeline 结构失败测试**

断言 stage 顺序严格为：

```text
research -> proposal -> script -> scene_plan -> assets -> sample -> edit -> compose -> publish
```

只允许 `assets` 和 `sample` 的 `human_approval_default=true`；assets 是 `creative_lock` terminal；publish 是本地打包，不执行外部上传；sample 必须 produce `asset_manifest/final_props/render_plan/sample_report`。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/contracts/test_cinematic_fast_pipeline.py -v`

Expected: FAIL，manifest 不存在。

- [ ] **Step 3: 创建 manifest**

关键声明必须是：

```yaml
name: cinematic-fast
version: "1.0"
category: cinematic
stability: beta
approval_groups:
  creative_lock:
    members: [proposal, script, scene_plan, assets]
    terminal_stage: assets
    required_artifacts: [proposal_packet, script, scene_plan, asset_plan, production_lock]
```

`assets` 第一次只产 `asset_plan/production_lock/approval_bundle`，成功标准明确“付费资产尚未生成”；`sample` 在批准后才产真实 `asset_manifest`。sample 的 required tools 至少包含 `tts_selector/audio_mixer/subtitle_gen/media_proxy/video_compose/final_qa`，research 显式包含 `video_analyzer/scene_detect/frame_sampler`，并由 director 调用 `lib.source_media_review` helper 生成 canonical artifact。`edit/compose/publish` 均自动前进，但 compose full QA 失败时必须停为 failed，不得发布。

`sample.tools_available` 与 `compose.tools_available` 都必须显式包含 `final_qa`；sample 使用 quick，compose 使用 full。`video_compose` 仍是唯一合成入口，manifest 不允许 director 用 ad-hoc FFmpeg 脚本绕过 render plan。

- [ ] **Step 4: 写 director wrappers**

每个 wrapper 第一段要求完整读取对应 `pipelines/cinematic/*-director.md`，只覆盖快线差异。`sample-director.md` 没有同名 base，必须依次读取 cinematic `asset-director.md`、`compose-director.md` 与 `skills/meta/fastline.md`，不能假设不存在的 base skill：

- proposal/script/scene_plan：写 evidence 和 artifact，但不暂停。
- asset：生成 `asset_plan`，禁止批准前 provider call，组装 creative bundle 后暂停。
- sample：按 production lock 生成/复用 TTS、BGM、subtitle、proxy，编译最终 props，渲染 10-15 秒并 quick QA 后暂停。
- edit：只生成 `change_impact`，不得静默修改 approved props。
- compose：按 render_plan full/mux_only，执行 full QA。
- publish：仅本地 package；任何平台上传都需要独立权限。

`skills/meta/fastline.md` 统一说明缓存、两道 gate、半开区间、paid-call boundary 和 resume 规则，避免 wrapper 重复大段文本。

- [ ] **Step 5: 更新 checkpoint protocol 和可发现列表**

`checkpoint-protocol.md` 增加 grouped gate 章节；`AGENT_GUIDE.md` pipeline 表增加 `cinematic-fast`（beta），说明适合 reference/source-led 3-5 小时产品混剪。不要改变现有 cinematic 默认行为。

- [ ] **Step 6: 运行 manifest/skill 合约**

Run: `.venv/bin/python -m pytest tests/contracts/test_cinematic_fast_pipeline.py tests/contracts/test_pipeline_approval_groups.py tests/contracts/test_phase0_contracts.py -v`

Expected: PASS；所有 `required_skills` 路径存在，所有 produces 名称已注册。

- [ ] **Step 7: 逻辑提交**

```bash
git add pipeline_defs/cinematic-fast.yaml skills/meta/fastline.md skills/meta/checkpoint-protocol.md skills/pipelines/cinematic-fast AGENT_GUIDE.md tests/contracts/test_cinematic_fast_pipeline.py
git commit -m "feat: add two-gate cinematic fastline pipeline"
```

### Task 14: 验证端到端只出现两次人工停点

**Files:**
- Create: `tests/integration/test_cinematic_fast_end_to_end.py`
- Modify: `tests/backlot/test_gate_scenarios.py`

- [ ] **Step 1: 写无付费调用的端到端 fixture**

使用临时项目、1 个 reference fixture、2 个 source fixture、fake TTS/music providers 和 fake Remotion adapter。测试完整推进并收集每次 `awaiting_human`。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/integration/test_cinematic_fast_end_to_end.py -v`

Expected: FAIL，直到所有 P0 组件接通。

- [ ] **Step 3: 补齐 stage 之间 artifact/hash 传递**

确保研究输出进入 creative bundle；批准前 provider mock 调用数为 0；creative approve 后 sample 生成资产；sample approve 后 edit/compose/publish 自动完成；最终 full QA 仍执行一次。

加入版权隔离断言：reference fingerprint 的 content hash、原文件 path、抽帧 path、音频 path 均不得出现在 realized `asset_manifest`、`final_props` 或 render inputs；只有 `abstract_structure` 的 semantic hash 可作为研究 provenance 引用。

- [ ] **Step 4: 运行并确认 exactly two gates**

Run: `.venv/bin/python -m pytest tests/integration/test_cinematic_fast_end_to_end.py tests/backlot/test_gate_scenarios.py -v`

Expected:

```text
awaiting_human_stages == ["assets", "sample"]
paid_provider_calls_before_assets_approval == 0
full_qa_calls == 1
```

- [ ] **Step 5: 运行 P0 聚合测试**

Run: `.venv/bin/python -m pytest tests/lib/test_artifact_hashing.py tests/lib/test_artifact_cache.py tests/lib/test_media_index.py tests/tools/test_doubao_tts_cache.py tests/tools/test_audio_mixer_cache.py tests/lib/test_final_props.py tests/tools/test_video_compose_mux_only.py tests/tools/test_video_compose_sample.py tests/tools/test_final_qa.py tests/lib/test_checkpoint_approval_groups.py tests/lib/test_production_lock.py tests/contracts/test_cinematic_fast_pipeline.py tests/integration/test_cinematic_fast_end_to_end.py -v`

Expected: PASS。

- [ ] **Step 6: 逻辑提交**

```bash
git add tests/integration/test_cinematic_fast_end_to_end.py tests/backlot/test_gate_scenarios.py
git commit -m "test: prove fastline has exactly two human gates"
```

## Chunk 4: Backlot、通用字幕、基准与条件式增量渲染

### Task 15: 让 Backlot 展示缓存、影响范围、审批 Bundle 与 ETA

**Files:**
- Create: `backlot/state_cache.py`
- Create: `tests/backlot/test_fastline_state.py`
- Modify: `backlot/state.py:570-675`
- Modify: `backlot/server.py:65-110,175-190`
- Modify: `backlot/ui/board.js:477-700`
- Modify: `backlot/ui/board.css`
- Modify: `tests/backlot/test_state.py`
- Modify: `tests/backlot/test_server.py`

- [ ] **Step 1: 写 fastline board-state 失败测试**

构造 bundle approved/superseded、cache hit/miss、change impact、render plan 和 ETA events，断言 state 暴露：

```json
{
  "fastline": {
    "gate": "creative_lock|sample|null",
    "bundle": {"version": 2, "status": "approved", "changed_artifacts": []},
    "cache": {"hits": 4, "misses": 1, "saved_seconds": 620},
    "render": {"mode": "mux_only", "dirty_scene_ids": []},
    "eta": {"seconds": 48, "confidence": "high"},
    "blocker": null,
    "next_action": "等待样片确认"
  }
}
```

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/backlot/test_fastline_state.py -v`

Expected: FAIL，现有 state 只有通用 stages/events。

- [ ] **Step 3: 实现派生 state 和轻量缓存**

`state_cache.py` 的 key 由 `checkpoint_*.json`、`artifacts/*.json`、`events.jsonl` 的 path/size/mtime_ns 组成；任何签名变化自动 miss。缓存只保存可重算 board state，不保存审批状态，不写 project artifact。

`load_board_state()` 从 terminal checkpoint + registered approval bundle 推导 gate，从 cache events 聚合 saved seconds，从最近五个同类 operation 的完成事件计算 rolling median ETA；少于三条时 confidence=`low`。

- [ ] **Step 4: 增加只读 UI 模块**

`board.js` 增加一个 unframed `FastlineStatus` section，显示：当前任务、剩余时间、缓存命中、是否需要完整重渲染、受影响镜头、bundle artifacts/hash diff 和下一动作。审批按钮仍只提示“回任务中确认”，不从浏览器写 checkpoint，避免鉴权和并发状态源。

- [ ] **Step 5: 运行 state/server/UI smoke**

Run: `.venv/bin/python -m pytest tests/backlot/test_fastline_state.py tests/backlot/test_state.py tests/backlot/test_server.py -v`

Expected: PASS；状态文件不变时第二次 load 命中 cache，文件变化后立即失效。

- [ ] **Step 6: 使用浏览器验证桌面和移动视口**

Run: `python -m backlot open transparent-table-mat-remix-01`

验证 `http://127.0.0.1:4750/p/transparent-table-mat-remix-01`：1080px 和 390px 宽度无文字覆盖；长 artifact 名换行；ETA、render mode、gate 一屏可扫读。只做截图/读取验证，不从 UI 批准。

- [ ] **Step 7: 逻辑提交**

```bash
git add backlot/state_cache.py backlot/state.py backlot/server.py backlot/ui/board.js backlot/ui/board.css tests/backlot
git commit -m "feat: show fastline reuse gates and ETA in backlot"
```

### Task 16: 产品化品牌 Profile 与安全区字幕组件

**Files:**
- Create: `schemas/artifacts/brand_profile.schema.json`
- Create: `lib/brand_profile.py`
- Create: `tests/lib/test_brand_profile.py`
- Create: `tests/contracts/test_brand_profile_contract.py`
- Create: `remotion-composer/src/components/SafeCaptionTrack.tsx`
- Create: `remotion-composer/src/components/SafeCaptionTrack.test.ts`
- Modify: `schemas/artifacts/__init__.py`
- Modify: `schemas/artifacts/edit_decisions.schema.json`
- Modify: `schemas/artifacts/final_review.schema.json`
- Modify: `remotion-composer/src/components/CaptionOverlay.tsx:1-150`
- Modify: `remotion-composer/src/components/index.ts`
- Modify: `remotion-composer/package.json`
- Modify: `remotion-composer/package-lock.json`

- [ ] **Step 1: 写 brand profile 合约测试**

Profile 可选字段固定为 voice/provider/resource/rate、BGM family、font、caption profile、emphasis rules、CTA pattern、platform defaults。`lib/brand_profile.py::merge_brand_defaults()` 只能填补尚未选择的值；与 production lock 不同必须返回 structured conflict 并生成 decision revision，不能静默覆盖。

- [ ] **Step 2: 写字幕纯函数失败测试**

把以下 helper 导出并用 Vitest 测试：`stripTrailingPunctuation`、`fitCjkFontSize`、`captionBoxForCue`、`isInsideSafeZone`。读取 `tests/fixtures/caption_layout/social_v1_cases.json` 做 Python/TS parity，并覆盖最长中文词、两行换行、44-52px clamp、宋体 fallback、尾部中英文标点、关键词 emphasis box 越界。

- [ ] **Step 3: 安装最小 TS 测试依赖并确认失败**

Run: `cd remotion-composer && npm install --save-dev vitest@2.1.9`

Expected: `added ... packages` 或 lockfile 中解析为 `vitest 2.1.9`。这是网络/依赖写入动作，执行 agent 必须先请求批准；Node 版本不满足时先由 runtime preflight 报 blocker，不得临时安装另一个未锁定版本。

在 `package.json` 增加 `"test": "vitest run"`。

Run: `cd remotion-composer && npm test -- SafeCaptionTrack.test.ts`

Expected: FAIL，组件/helper 不存在。

- [ ] **Step 4: 实现 `SafeCaptionTrack`**

公开 props：

```ts
type SafeCaptionProps = {
  captions: Caption[];
  safeZoneProfile?: "douyin_9_16" | "wechat_9_16" | "xiaohongshu_9_16";
  fontMin?: number;
  fontMax?: number;
  maxWidth?: number;
  stripTrailingPunctuation?: boolean;
  emphasisRules?: Array<{term: string; color: string; effect: "scale" | "underline" | "color"}>;
};
```

三个 profile v1 暂时共享保守矩形：left/right 72、top 120、bottom 300、宽度不超过 864、最多两行、line-height 1.24。CJK 字号由字符宽度近似表确定，不依赖不同机器会漂移的浏览器测量。

重要边界：透明桌垫项目是 atelier，仍保留项目本地 `CaptionTrack.tsx`，**不得导入这个 stock component**；该组件服务后续 templated 作品。atelier 可复用算法知识，但不能复用成品创意组件。

- [ ] **Step 5: 把字幕渲染事实写入 artifacts**

`edit_decisions` 增加：

```json
{
  "caption_render_mode": "remotion_overlay|ffmpeg_burn|subtitle_stream",
  "caption_source": "path",
  "safe_zone_profile": "douyin_9_16"
}
```

同步把当前项目已经实际使用、但 schema 尚未声明的 caption style 字段 `trailing_punctuation` 与 `keyword_effect` 正式加入 schema，并增加回归断言 `projects/transparent-table-mat-remix-01/artifacts/edit_decisions.json` 可验证。不要通过删除真实 artifact 字段来让测试变绿。

`final_review` 的 `caption_render` 必须按该声明验证，不得因存在 `.srt` 文件就假定字幕已经出现在像素中。

- [ ] **Step 6: 运行 TS 与 schema 测试**

Run: `cd remotion-composer && npm test -- SafeCaptionTrack.test.ts`

Run: `cd remotion-composer && npx tsc --noEmit`

Run: `.venv/bin/python -m pytest tests/lib/test_brand_profile.py tests/contracts/test_brand_profile_contract.py tests/tools/test_final_qa.py -v`

Expected: PASS。

- [ ] **Step 7: 逻辑提交**

```bash
git add schemas/artifacts/brand_profile.schema.json schemas/artifacts/__init__.py schemas/artifacts/edit_decisions.schema.json schemas/artifacts/final_review.schema.json lib/brand_profile.py remotion-composer/src/components/SafeCaptionTrack.tsx remotion-composer/src/components/SafeCaptionTrack.test.ts remotion-composer/src/components/CaptionOverlay.tsx remotion-composer/src/components/index.ts remotion-composer/package.json remotion-composer/package-lock.json tests/lib/test_brand_profile.py tests/contracts/test_brand_profile_contract.py
git commit -m "feat: add reusable brand and safe caption profiles"
```

### Task 17: 建立可复现的 3-5 小时 Benchmark 与 SLA Gate

**Files:**
- Create: `tools/analysis/fastline_metrics.py`
- Create: `tests/tools/test_fastline_metrics.py`
- Create: `docs/benchmarks/cinematic-fast.md`
- Modify: `tools/tool_registry.py`
- Modify: `Makefile`

- [ ] **Step 1: 写 active/human/end-to-end 计时聚合测试**

输入 checkpoints/events，输出每类 operation 的 count、cache hit rate、active seconds、human wait seconds、end-to-end seconds、median、max、environment fingerprint 和 estimate confidence。重叠并行事件只能计算 wall time union，不能简单相加。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/tools/test_fastline_metrics.py -v`

Expected: FAIL，tool 不存在。

- [ ] **Step 3: 实现只读 metrics BaseTool**

该 tool 只读取已有 run，不负责启动或编排 pipeline。输出写入 `projects/<id>/analysis/benchmarks/<timestamp>.json`，记录 CPU、cores、RAM、macOS、Node、Remotion、Chromium、FFmpeg、素材数量/字节/总时长和 cache hit rate。

- [ ] **Step 4: 写 benchmark runbook 和 Make target**

`docs/benchmarks/cinematic-fast.md` 要求通过正常 pipeline 执行 3 次 cold、5 次 warm、至少 3 次 audio-only revision；每次人工等待归一为两个 10 分钟 gate。`make benchmark-fastline PROJECT_ID=<id>` 只聚合结果，不启动付费生成。

- [ ] **Step 5: 运行 metrics 测试**

Run: `.venv/bin/python -m pytest tests/tools/test_fastline_metrics.py -v`

Expected: PASS。

- [ ] **Step 6: 执行真实基准并判定是否可发布 SLA**

通过正常 `cinematic-fast` pipeline 完成运行后执行聚合。通过规则：

```text
cold: median <= 4h, every run <= 5h
warm: median <= 75m, every run <= 90m
audio-only: median <= 10m, every run <= 15m
```

任一失败时仍发布 benchmark report，但产品/UI 不显示对应 SLA，只显示实测 rolling ETA。

- [ ] **Step 7: 逻辑提交**

```bash
git add tools/analysis/fastline_metrics.py tools/tool_registry.py tests/tools/test_fastline_metrics.py docs/benchmarks/cinematic-fast.md Makefile
git commit -m "feat: measure and gate cinematic fastline performance"
```

### Task 18: 条件满足时才实现 Scene-level Incremental Render

**Precondition:** 只有 P0 基准显示完整 Remotion render 占 active time >10%，或目标机器单次完整 render >3 分钟，才执行本 Task；否则标记 `DEFERRED_BY_BENCHMARK`。

**Files:**
- Create: `lib/scene_render_cache.py`
- Create: `tests/lib/test_scene_render_cache.py`
- Create: `tests/tools/test_video_compose_incremental.py`
- Modify: `schemas/artifacts/render_plan.schema.json`
- Modify: `tools/video/video_compose.py`

- [ ] **Step 1: 写 dirty range 与全量回退测试**

Scene key 包含 source/component code hash、scene props、crop/trim/speed、相交 caption/overlay、transition、runtime/version/profile。font、global style、runtime、fps、resolution、timeline structure 任一变化必须 `full_render`。

- [ ] **Step 2: 运行并确认失败**

Run: `.venv/bin/python -m pytest tests/lib/test_scene_render_cache.py tests/tools/test_video_compose_incremental.py -v`

Expected: FAIL。

- [ ] **Step 3: 实现 transition/premount guard 扩展**

Dirty scene range 向前后扩展 transition frames 与 premount guard；缓存输出必须先验证同一 H.264/yuv420p/profile，再允许 concat。任何 range 缺失或 profile 不一致立即返回 `requires_full_render`，不得拼接不确定片段。

- [ ] **Step 4: 实现 `render_plan.mode=incremental`**

只渲染 dirty ranges，组装新的 profile-certified video master，最后统一 mux 音频并执行 full QA。不要把字幕单独视为 overlay-only，除非它已被证明完全位于独立合成层。

- [ ] **Step 5: 运行 incremental 与完整回归**

Run: `.venv/bin/python -m pytest tests/lib/test_scene_render_cache.py tests/tools/test_video_compose_incremental.py tests/tools/test_video_compose_mux_only.py tests/tools/test_final_qa.py -v`

Expected: PASS；global change spy 证明调用 full render，单镜头变化只渲染扩展后的 range。

- [ ] **Step 6: 重新跑 3 次 revision benchmark**

只有 median scene revision <=15 分钟且 QA 与 full render 像素/音频合约一致时保留该功能；否则保留代码 feature flag off，并记录原因。

- [ ] **Step 7: 逻辑提交**

```bash
git add lib/scene_render_cache.py schemas/artifacts/render_plan.schema.json tools/video/video_compose.py tests/lib/test_scene_render_cache.py tests/tools/test_video_compose_incremental.py
git commit -m "feat: add guarded scene incremental rendering"
```

## 最终验证清单

- [ ] **Step 1: 运行 Python 全量测试**

Run: `make test`

Expected: 全部 PASS；若存在既有失败，记录测试名和与本改动无关的证据，不得静默忽略。

- [ ] **Step 2: 运行 contract 测试**

Run: `make test-contracts`

Expected: 全部 artifact、manifest、checkpoint schema PASS。

- [ ] **Step 3: 运行 Remotion 编译与组件测试**

Run: `cd remotion-composer && npm test && npx tsc --noEmit`

Expected: PASS。

- [ ] **Step 4: 运行 preflight**

Run: `make preflight`

Expected: 显示 provider menu summary、Remotion/FFmpeg/Chromium/字体路径，不下载 Chromium，不泄露 `.env` secret。

- [ ] **Step 5: 透明桌垫回归样片**

使用已存在的真实 source 素材和已批准 props，运行 `render_plan.mode=sample`，验证 540x960、30fps、300-450 帧、字幕/音频 offset 与 final props 一致。此步骤不得调用付费模型。

- [ ] **Step 6: 音频-only 回归**

仅调整 BGM gain，断言：Doubao 不调用、Remotion 不调用、`audio_mixer` 运行或命中、`mux_only` 完成、full QA 通过，最终仍为 1080x1920/30fps/H.264/yuv420p/AAC 48kHz stereo。

- [ ] **Step 7: 两道 gate 回归**

从空 checkpoint 运行到本地 publish package，记录且只记录：`assets awaiting_human`、`sample awaiting_human`。任何第三次等待均为 release blocker。

- [ ] **Step 8: Backlot 浏览器验证**

确认桌面和移动视口可看到 gate、bundle diff、cache hit、render mode、affected scenes、ETA 与 blocker；没有重叠、溢出或重复审批状态源。

- [ ] **Step 9: 发布 benchmark 结论**

完成 3 cold + 5 warm + audio-only runs。只有通过 Task 17 阈值才把“3-5 小时”写成产品承诺；否则文案使用实际 median/max。

## 建议实施周期

| 阶段 | 预计工程时间 | 可独立交付的结果 |
|---|---:|---|
| P0-A：Task 1-4 | 2-3 工程日 | 分析、TTS、字幕、混音可安全复用 |
| P0-B：Task 5-9 | 3-4 工程日 | 唯一时间轴、sample/full/mux_only、QA v2 |
| P0-C：Task 10-14 | 2-3 工程日 | 两道 gate 的 `cinematic-fast` 可端到端运行 |
| P1：Task 15-16 | 1-2 工程日 | Backlot 可观测性与通用配置/字幕 |
| Benchmark：Task 17 | 0.5-1 工程日 + 实际运行时间 | 是否能正式承诺 3-5 小时 |
| Incremental：Task 18 | 2-3 工程日，仅条件触发 | 长视频/批量任务的局部重渲染 |

这里的“3-5 小时”是**升级完成后的单条视频生产耗时目标**，不是本次代码升级的开发时长。首版应先交付 P0 并基准验证，再决定是否投入场景级增量渲染。

# OpenReel Timeline V2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在当前 Source-led 电商主链上交付可真实渲染、可审核、可回滚的 OpenReel 多轨精剪闭环。

**Architecture:** 新增 EditorialTimeline v1 和严格的 EditDelta 作为精剪唯一生产事实；服务端将它物化为现有 composition 输入并调用现有 video_compose、对齐、L1a、final QA。选择性移植旧分支的画廊、会话和版本管理，不合并旧的一轨 mapper、假渲染 job 或大体积 vendor build。

**Tech Stack:** Python 3、FastAPI、JSON Schema、ProjectCommitStore、Remotion/HyperFrames/FFmpeg 既有 composition path、pytest、OpenReel 同源前端 bridge。

---

## File Structure

| 文件 | 职责 |
|---|---|
| schemas/artifacts/editorial_timeline.schema.json | 可执行多轨 timeline 结构与事实绑定 |
| schemas/artifacts/editorial_edit_delta.schema.json | 可提交操作、CAS 和幂等输入 |
| lib/editorial_timeline.py | snapshot 物化、delta 应用、静态校验和 legacy projection |
| lib/editorial_asset_catalogue.py | 从 Source-led 证据生成可替换片段的不可伪造 catalogue |
| lib/editorial_alignment_evidence.py | 为修改后输出生成 hash-bound source-led alignment evidence |
| lib/editorial_executor.py | 真实 preview/final render、QA 产物与报告 |
| remotion-composer/src/Explainer.tsx | 多轨剪辑、音频、字幕和花字的真实画面实现 |
| remotion-composer/src/Root.tsx | EditorialTimeline props 的 composition metadata 注册 |
| backlot/editorial_sessions.py | 候选归属、版本、草稿、CAS、审计 |
| backlot/editorial_gallery.py | 批量画廊只读 DTO |
| backlot/openreel_bridge.py | OpenReel Action 到完整 typed delta，未知操作显式失败 |
| backlot/operator_routes.py | V2 session、render、promote/discard API |
| backlot/server.py | /studio 页面与静态 editor assets 路由 |
| backlot/ui/editorial-editor/* | OpenReel shell、事实约束/版本/渲染状态 UI |
| tests/lib/test_editorial_timeline.py | IR、delta、约束、投影单测 |
| tests/lib/test_editorial_executor.py | 真正执行器与 QA gate 单测 |
| tests/backlot/test_editorial_studio_v2.py | API、CAS、版本、promote/discard 集成测试 |
| tests/backlot/test_editorial_gallery_v2.py | 画廊真实投影和入口测试 |
| tests/backlot/test_openreel_bridge_v2.py | Action 映射和 unsupported failure 测试 |

## Chunk 1: Contract And Timeline Core

### Task 1: Define timeline and delta contracts

**Files:**
- Create: schemas/artifacts/editorial_timeline.schema.json
- Create: schemas/artifacts/editorial_edit_delta.schema.json
- Test: tests/lib/test_editorial_timeline.py

- [ ] **Step 1: Write failing schema tests** for valid video/narration/music/text/subtitle tracks and a video clip fact binding. Keep stale base hashes out of schema tests: CAS belongs to the session service.

    def test_editorial_timeline_requires_fact_binding_for_video_clip():
        errors = validate_timeline({"version": "1.0", "tracks": [{"kind": "video", "clips": [{"id": "v1"}]}]})
        assert "fact_scope" in errors[0]

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/lib/test_editorial_timeline.py -q
Expected: FAIL because schemas and validators do not exist.

- [ ] **Step 3: Implement minimal schemas.** Use closed additionalProperties; require profile, base_generation_id, source hashes, typed tracks, media asset IDs, fact bindings and operation discriminators. Permit only declared text-style tokens.

- [ ] **Step 4: Run focused and schema registry tests.**

Run: pytest tests/lib/test_editorial_timeline.py tests/contracts -q
Expected: PASS.

- [ ] **Step 5: Commit.**

    git add schemas/artifacts/editorial_timeline.schema.json schemas/artifacts/editorial_edit_delta.schema.json tests/lib/test_editorial_timeline.py
    git commit -m "feat(editorial): define timeline and edit delta contracts"

### Task 2: Materialize source-led artifacts as EditorialTimeline

**Files:**
- Create: lib/editorial_timeline.py
- Create: lib/editorial_asset_catalogue.py
- Modify: lib/template_render.py
- Test: tests/lib/test_editorial_timeline.py

- [ ] **Step 1: Write a failing fixture test** with edit_decisions, final_props, product facts, coverage matrix, source-media evidence, source videos, narration and BGM. Assert five canonical tracks and that every video clip preserves shot_id, claim_ids and visual_requirement_id. Assert the generated approved catalogue has server-issued IDs, source hashes and valid ranges.

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/lib/test_editorial_timeline.py::test_materialize_source_led_timeline -q
Expected: FAIL with missing materialize_editorial_timeline.

- [ ] **Step 3: Implement materialize_editorial_timeline() and build_editorial_asset_catalogue().** Resolve media only from source-media evidence and approved generation assets, bind source artifact hashes and valid source ranges, and fail closed for missing coverage/fact evidence. Add the smallest build call from template_render.py; do not change existing render behavior.

- [ ] **Step 4: Run focused and Source-led regressions.**

Run: pytest tests/lib/test_editorial_timeline.py tests/integration/test_source_led_sample_alignment.py -q
Expected: PASS.

- [ ] **Step 5: Commit.**

    git add lib/editorial_timeline.py lib/template_render.py tests/lib/test_editorial_timeline.py
    git commit -m "feat(editorial): materialize source-led timeline"

### Task 3: Apply typed deltas and enforce product-fact scope

**Files:**
- Modify: lib/editorial_timeline.py
- Test: tests/lib/test_editorial_timeline.py

- [ ] **Step 1: Add failing parameterized tests** for trim, split, non-ripple move, replace, caption timing, BGM gain/fade and narration replacement. Add rejection cases for forged/cross-candidate asset IDs, source-range overflow, same-claim/different-requirement replacement, fact-scope mismatch, overlapping primary clips and invalid speed. Add cross-track tests proving a non-ripple move does not alter subtitles/audio/overlays.

- [ ] **Step 2: Run the failing operation tests.**

Run: pytest tests/lib/test_editorial_timeline.py -k "delta or scope" -q
Expected: FAIL because operations are unimplemented.

- [ ] **Step 3: Implement immutable apply_delta().** Return a new timeline/hash or structured errors. Preserve clip IDs on trims, create child IDs on splits, apply non-ripple moves only to the named track, and validate every changed fact binding before return. Add a separate explicit ripple operation only after it has a declared affected-clip plan.

- [ ] **Step 4: Run all timeline tests.**

Run: pytest tests/lib/test_editorial_timeline.py -q
Expected: PASS.

- [ ] **Step 5: Commit.**

    git add lib/editorial_timeline.py tests/lib/test_editorial_timeline.py
    git commit -m "feat(editorial): enforce typed timeline edits"

## Chunk 2: Real Rendering And Quality Gates

### Task 4: Extend the composition runtime for the supported multitrack contract

**Files:**
- Modify: lib/editorial_timeline.py
- Modify: remotion-composer/src/Explainer.tsx
- Modify: remotion-composer/src/Root.tsx
- Create: remotion-composer/src/editorial/types.ts
- Create: remotion-composer/src/editorial/EditorialTimeline.tsx
- Test: remotion-composer/src/editorial/EditorialTimeline.test.tsx
- Test: tests/lib/test_editorial_timeline.py
- Test: tests/tools/test_video_compose_sample.py

- [ ] **Step 1: Write failing renderer tests** that render a small multi-track fixture. Assert frame-level order for split/reorder, caption timing, vertical selling-point text, narration replacement, BGM gain/fade/ducking and 3:4 one-line subtitle safe zones. Add an audio filter-graph or decoded waveform assertion proving BGM changes occur in the output.

- [ ] **Step 2: Run test to verify it fails.**

Run: cd remotion-composer && pnpm test -- EditorialTimeline
Expected: FAIL because the editorial renderer does not exist.

- [ ] **Step 3: Implement EditorialTimeline composition props and renderer.** Add deterministic track ordering, timing, trim/speed, text placement, subtitles, narration/BGM gain/fade/ducking and allowed transitions. Then implement project_timeline_for_compose() as an explicit adapter to these props; return unsupported_delivery_operation before rendering for anything the locked runtime cannot honor.

- [ ] **Step 4: Run composition regressions.**

Run: cd remotion-composer && pnpm test -- EditorialTimeline && cd .. && pytest tests/lib/test_editorial_timeline.py tests/tools/test_video_compose_sample.py tests/tools/test_video_compose_vertical.py -q
Expected: PASS.

- [ ] **Step 5: Commit.**

    git add lib/editorial_timeline.py remotion-composer/src/Explainer.tsx remotion-composer/src/Root.tsx remotion-composer/src/editorial tests/lib/test_editorial_timeline.py
    git commit -m "feat(editorial): render multitrack timeline composition"

### Task 5: Build the real editorial executor

**Files:**
- Create: lib/editorial_executor.py
- Create: lib/editorial_alignment_evidence.py
- Modify: scripts/qa_template_render.py
- Test: tests/lib/test_editorial_executor.py
- Test: tests/lib/test_editorial_alignment_evidence.py

- [ ] **Step 1: Write failing tests** injecting a fake video_compose tool and QA runners. Assert preview and final write to operator/editorial/versions/<revision>/, persist actual output SHA-256 and never overwrite renders/final.mp4.

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/lib/test_editorial_executor.py -q
Expected: FAIL because the executor does not exist.

- [ ] **Step 3: Write failing alignment-evidence tests** that modify a bound shot, generate a new output hash, then prove a baseline alignment report is rejected. Test that the evidence builder requires the output probe/frame sample, rendered timeline hash, fact bindings and current script/product-fact hashes.

- [ ] **Step 4: Implement build_editorial_alignment_evidence().** Produce a fresh hash-bound report from the versioned timeline, output probe/frame sampling, current product facts and visual requirements; route its report through existing semantic alignment gate helpers only after their hash-binding inputs match the editorial output.

- [ ] **Step 5: Implement EditorialRenderExecutor.** render_preview() and render_final() must materialize inputs, call the locked video_compose runtime, create new alignment evidence, invoke technical_validator and final_qa against the generated file, then persist server-derived execution_report.json. Reuse QA helpers; never accept a report or qa_status from HTTP.

- [ ] **Step 6: Add failure tests** for composition error, stale/baseline alignment report, alignment failure, L1a failure and final QA failure. Assert failed status and unchanged current delivery pointer/output hash.

- [ ] **Step 7: Run executor and existing QA tests.**

Run: pytest tests/lib/test_editorial_executor.py tests/lib/test_editorial_alignment_evidence.py tests/tools/test_final_qa.py tests/lib/test_template_alignment.py -q
Expected: PASS.

- [ ] **Step 8: Commit.**

    git add lib/editorial_executor.py lib/editorial_alignment_evidence.py scripts/qa_template_render.py tests/lib/test_editorial_executor.py tests/lib/test_editorial_alignment_evidence.py
    git commit -m "feat(editorial): execute real timeline renders with QA"

### Task 6: Define server-owned revision lifecycle

**Files:**
- Create: backlot/editorial_sessions.py
- Modify: backlot/delivery_versions.py
- Test: tests/backlot/test_editorial_studio_v2.py

- [ ] **Step 1: Write failing tests** for session ownership, idempotent draft save, same-key/different-payload conflict, two concurrent deltas on one base hash, generation advance during render/promote, failed preview retention, final gate failure, discard, promote and restoration of the prior delivery revision. Add that final is rejected without preview approval and that a new delta invalidates a prior preview approval.

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/backlot/test_editorial_studio_v2.py -q
Expected: FAIL because the session service does not exist.

- [ ] **Step 3: Implement session persistence and transitions** using ProjectCommitStore. The state machine advances only from executor artifacts. Store preview approval with revision/output hash/actor/time, invalidate it after any edit or new preview, and require it before final. promote() validates server-owned pass reports and atomically updates delivery pointers. Implement restore_delivery_revision() as an explicit audited/idempotent transition: authorize edit, require expected generation and selected old manifest/output hashes, then atomically repoint only after their integrity checks pass.

- [ ] **Step 4: Run focused state and existing revision tests.**

Run: pytest tests/backlot/test_editorial_studio_v2.py tests/backlot/test_operator_revisions.py tests/lib/test_rerun_plan.py -q
Expected: PASS.

- [ ] **Step 5: Commit.**

    git add backlot/editorial_sessions.py backlot/delivery_versions.py tests/backlot/test_editorial_studio_v2.py
    git commit -m "feat(editorial): add server-owned edit revision lifecycle"

## Chunk 3: Backlot And OpenReel Integration

### Task 7: Port gallery projection without old-branch state regressions

**Files:**
- Create: backlot/editorial_gallery.py
- Modify: backlot/batch_state.py
- Test: tests/backlot/test_editorial_gallery_v2.py

- [ ] **Step 1: Write failing tests** from a current cinematic-fast batch fixture. Assert gallery items show actual poster/video URLs, direction, current revision, gate statuses, fact-summary evidence and Studio eligibility. Assert a remotion candidate is eligible while HyperFrames/FFmpeg candidates have an explicit unsupported-runtime reason and cannot create a V2 session. Assert missing media is an honest empty state.

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/backlot/test_editorial_gallery_v2.py -q
Expected: FAIL because the projection is absent on main.

- [ ] **Step 3: Selectively port gallery DTO logic** from codex/editorial-gallery-rollout, adapting it to current batch_state and Source-led evidence. Do not overwrite current batch approval APIs or state naming.

- [ ] **Step 4: Run gallery and workbench tests.**

Run: pytest tests/backlot/test_editorial_gallery_v2.py tests/backlot/test_batch_workbench.py -q
Expected: PASS.

- [ ] **Step 5: Commit.**

    git add backlot/editorial_gallery.py backlot/batch_state.py tests/backlot/test_editorial_gallery_v2.py
    git commit -m "feat(backlot): add source-led editorial gallery"

### Task 8: Add V2 APIs and routes

**Files:**
- Modify: backlot/operator_routes.py
- Modify: backlot/server.py
- Test: tests/backlot/test_editorial_studio_v2.py
- Test: tests/backlot/test_editorial_gallery_v2.py

- [ ] **Step 1: Write failing API tests** for GET gallery, create/load session, GET snapshot, POST delta, POST preview render, POST final render, POST promote, POST discard and POST restore-delivery. Include actor authorization, CSRF, idempotency, expected generation, manifest/output hash verification and stale errors. Assert a non-Remotion candidate cannot create a session.

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/backlot/test_editorial_studio_v2.py tests/backlot/test_editorial_gallery_v2.py -q
Expected: FAIL on missing routes.

- [ ] **Step 3: Register APIs and pages** at /api/v2/projects/{batch}/editorial-gallery/*, /studio/{batch} and /studio/{batch}/edit/{candidate}, including POST restore-delivery. Route handlers pass only typed inputs to session/executor services; no handler accepts a client QA status or arbitrary output path. Reject non-Remotion session requests before session creation with an explicit capability error.

- [ ] **Step 4: Run API and security tests.**

Run: pytest tests/backlot/test_editorial_studio_v2.py tests/backlot/test_editorial_gallery_v2.py tests/backlot/test_operator_api.py -q
Expected: PASS.

- [ ] **Step 5: Commit.**

    git add backlot/operator_routes.py backlot/server.py tests/backlot/test_editorial_studio_v2.py tests/backlot/test_editorial_gallery_v2.py
    git commit -m "feat(backlot): expose editorial timeline studio APIs"

### Task 9: Implement a complete OpenReel bridge

**Files:**
- Create: backlot/openreel_bridge.py
- Create: backlot/ui/editorial-editor-shell.html
- Create: backlot/ui/editorial-editor/shell.js
- Create: backlot/ui/editorial-editor/shell.css
- Test: tests/backlot/test_openreel_bridge_v2.py

- [ ] **Step 1: Write failing bridge tests** mapping clip add/split/move/replace, audio gain/fade/ducking and caption timing to EditDelta. Add a test that color_grade/apply returns a visible unsupported error and produces no saved delta.

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/backlot/test_openreel_bridge_v2.py -q
Expected: FAIL because the V2 bridge is absent.

- [ ] **Step 3: Implement snapshot-to-OpenReel adapter and Action-to-EditDelta bridge.** Bind only server-issued clip/asset IDs, preserve mapping version and reject unknown IDs. Never persist an upstream action directly.

- [ ] **Step 4: Implement editor shell states** for Source-led fact scope, approved-assets drawer, save/preview/final actions, rendering progress, QA results, version comparison and unsupported-operation warning. The shell calls same-origin APIs only.

- [ ] **Step 5: Run bridge and UI contract tests.**

Run: pytest tests/backlot/test_openreel_bridge_v2.py tests/backlot/test_operator_ui_contract.py -q
Expected: PASS.

- [ ] **Step 6: Commit.**

    git add backlot/openreel_bridge.py backlot/ui/editorial-editor-shell.html backlot/ui/editorial-editor tests/backlot/test_openreel_bridge_v2.py
    git commit -m "feat(editorial): connect OpenReel to timeline V2"

### Task 10: Add controlled OpenReel build and gallery-to-studio navigation

**Files:**
- Create: scripts/build_openreel_editor.py
- Modify: Makefile
- Modify: backlot/ui/operator/app.js
- Modify: backlot/server.py
- Test: tests/backlot/test_editorial_gallery_v2.py
- Test: tests/backlot/test_openreel_bridge_v2.py

- [ ] **Step 1: Write failing tests** for “进入精剪” links from the gallery and build-manifest verification: pinned source revision, license file and bundle hash. Add feature-flag-off tests proving /studio and editorial APIs return unavailable while /p remains unchanged. Assert a missing-build fallback never pretends the editor is usable.

- [ ] **Step 2: Run test to verify it fails.**

Run: pytest tests/backlot/test_editorial_gallery_v2.py tests/backlot/test_openreel_bridge_v2.py -q
Expected: FAIL on absent navigation/build contract.

- [ ] **Step 3: Implement build script, make editorial-editor-build and OPENMONTAGE_EDITORIAL_TIMELINE_V2 gate.** The build uses pinned upstream source, produces a manifest with version/license/hash, and fails CI when the shell bridge target is absent. Flag-off hides Studio routes/APIs while retaining /p. Add Studio links to the current operator workbench without replacing the single-video workflow.

- [ ] **Step 4: Run tests and local server smoke check.**

Run: pytest tests/backlot/test_editorial_gallery_v2.py tests/backlot/test_openreel_bridge_v2.py -q
Expected: PASS.

Then run: python -m backlot open <fixture-batch-id>
Expected: /studio/<fixture-batch-id> and /studio/<fixture-batch-id>/edit/<candidate-id> return HTML.

- [ ] **Step 5: Commit.**

    git add scripts/build_openreel_editor.py Makefile backlot/ui/operator/app.js backlot/server.py tests/backlot/test_editorial_gallery_v2.py tests/backlot/test_openreel_bridge_v2.py
    git commit -m "feat(editorial): add controlled editor build and studio navigation"

## Chunk 4: End-To-End Acceptance And Rollout

### Task 11: Prove the complete source-led editorial loop

**Files:**
- Create: tests/integration/test_source_led_editorial_timeline.py
- Modify: tests/integration/test_source_led_sample_alignment.py
- Create: docs/reports/2026-09-09-openreel-timeline-v2-pilot.md

- [ ] **Step 1: Write an end-to-end silver-ion towel fixture** with source clips, product fact card, visual coverage, narration, BGM and an approved delivery. Perform replacement, split/reorder, vertical selling-point text adjustment and caption timing update.

- [ ] **Step 2: Run test to verify it fails before orchestration glue exists.**

Run: pytest tests/integration/test_source_led_editorial_timeline.py -q
Expected: FAIL until the full loop is wired.

- [ ] **Step 3: Add minimal orchestration glue** that creates the editorial timeline on Studio entry and exposes render progress through the existing event model. Do not introduce a second production state machine.

- [ ] **Step 4: Assert final acceptance.** Actual preview/final files exist; facts stay covered; alignment/L1a/final QA are server-derived and pass; old delivery remains unchanged before promotion; promotion changes only the delivery pointer.

- [ ] **Step 5: Run full targeted regression.**

Run: pytest tests/lib/test_editorial_timeline.py tests/lib/test_editorial_executor.py tests/backlot/test_editorial_studio_v2.py tests/backlot/test_editorial_gallery_v2.py tests/backlot/test_openreel_bridge_v2.py tests/integration/test_source_led_editorial_timeline.py tests/integration/test_source_led_sample_alignment.py -q
Expected: PASS.

- [ ] **Step 6: Run broader regression before release.**

Run: pytest tests/backlot tests/lib/test_template_alignment.py tests/integration/test_source_led_sample_alignment.py tests/integration/test_cinematic_fast_end_to_end.py tests/tools/test_video_compose_sample.py tests/tools/test_final_qa.py -q
Expected: PASS; document unrelated environmental skips.

- [ ] **Step 7: Record pilot evidence and commit.**

    git add tests/integration/test_source_led_editorial_timeline.py tests/integration/test_source_led_sample_alignment.py docs/reports/2026-09-09-openreel-timeline-v2-pilot.md
    git commit -m "test(editorial): prove source-led timeline V2 loop"

## Release Gate

Enable OPENMONTAGE_EDITORIAL_TIMELINE_V2 only after focused and broad tests pass, browser acceptance confirms real Studio navigation, and one silver-ion towel candidate completes preview -> final -> promote with real media. Rollback is the feature flag; no delivery file or revision is deleted.

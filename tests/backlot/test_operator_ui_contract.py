from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "backlot" / "ui"
OPERATOR_ROOT = UI_ROOT / "operator"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operator_ui_files_and_chinese_shell_exist() -> None:
    expected = {
        UI_ROOT / "operator.html",
        OPERATOR_ROOT / "app.js",
        OPERATOR_ROOT / "api.js",
        OPERATOR_ROOT / "store.js",
        OPERATOR_ROOT / "language.js",
        OPERATOR_ROOT / "styles.css",
    }
    assert all(path.is_file() for path in expected)

    html = _read(UI_ROOT / "operator.html")
    assert 'lang="zh-CN"' in html
    for label in ("项目总进度", "当前任务", "预计时间", "下一步", "制作流程"):
        assert label in html
    assert "/diagnostics/p/" in html
    assert "查看诊断信息" in html


def test_operator_ui_supports_nine_business_stages_and_view_states() -> None:
    source = "\n".join(_read(path) for path in OPERATOR_ROOT.iterdir() if path.is_file())
    for label in (
        "参考解析与素材体检",
        "创意方案",
        "剧本生成",
        "分镜",
        "制作准备",
        "样片确认",
        "修改与精剪",
        "成片生成",
        "交付下载",
    ):
        assert label in source
    for state in ("loading", "empty", "degraded", "error", "awaiting", "completed"):
        assert state in source


def test_operator_ui_does_not_embed_engineering_output_patterns() -> None:
    source = "\n".join(
        _read(path)
        for path in (UI_ROOT / "operator.html", *sorted(OPERATOR_ROOT.iterdir()))
        if path.is_file()
    ).lower()
    forbidden = (
        "<pre",
        "json.stringify(",
        "artifact path",
        "semantic_sha256",
        "runtime",
        "schema",
        "pipeline",
        "scene_plan",
    )
    assert all(term not in source for term in forbidden)


def test_operator_ui_has_stable_desktop_and_mobile_layout_constraints() -> None:
    css = _read(OPERATOR_ROOT / "styles.css")
    assert "grid-template-columns" in css
    assert "minmax(0, 1fr)" in css
    assert "overflow-x: auto" in css
    assert "max-width: 1440px" in css
    assert "@media (max-width: 1280px)" in css
    assert "@media (max-width: 390px)" in css
    assert "min-width: 0" in css
    assert ".research-matching-row .inline-edit-actions" in css


def test_operator_ui_renders_detailed_sources_concepts_and_clip_previews() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for field in (
        "data.sources", "concept.visual_approach", "concept.why_this_works",
        "preview_url", "poster_url", "source_in_seconds",
    ):
        assert field in app
    assert 'preload = "none"' in app
    assert 'source.media_type === "image"' in app
    assert 'source.media_type === "audio"' in app
    assert 'video.addEventListener("play"' in app
    assert 'video.addEventListener("seeking"' in app
    assert "source-card" in css
    assert "concept-details" in css
    assert "shot-preview" in css


def test_research_review_uses_scoped_decision_controls_without_generic_editor() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    editors = _read(OPERATOR_ROOT / "editors.js")

    assert 'research_review: (target, value) => renderResearch' in app
    assert '!["research_review", "script_editor", "asset_review", "delivery_review"].includes(editor?.type)' in app
    assert "resolve_matrix_row" in app
    assert "request_local_reanalysis" in app
    assert "业务备注" not in editors
    assert 'editor?.type === "research_review"' not in editors


def test_research_ui_renders_fixed_substages_and_horizontal_shot_rail() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")
    for term in ("research-substage-nav", "research-substage-panel", "research-shot-rail", "本项目没有参考片，这一步不需要处理"):
        assert term in app
    for term in (".research-substage-nav", ".research-shot-rail", "overflow-x: auto", ".research-substage.is-not-needed"):
        assert term in css


def test_research_ui_has_decision_inbox_and_proposal_handoff() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")
    for term in ("需要我确认", "decision-inbox", "proposal-handoff", "复制给 Code Agent", "会影响"):
        assert term in app
    for term in (".decision-inbox", ".decision-card", ".proposal-handoff"):
        assert term in css


def test_proposal_ui_hands_off_locked_control_plan_to_script_generation() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    director = _read(REPO_ROOT / "skills/pipelines/cinematic-fast/script-director.md")
    assert "control-plan-handoff" in app
    assert "生成制作剧本" in app
    assert "读取已锁定的导演总控单并生成制作剧本" in app
    assert "creative_control_ref" in director
    assert "missing or not approved" in director


def test_proposal_control_section_reviews_survive_workspace_refreshes() -> None:
    app = _read(OPERATOR_ROOT / "app.js")

    assert 'fetchDraft(projectId, "proposal")' in app
    assert "proposalOperationKey" in app
    assert "applyProposalControlPlanDraft" in app
    assert "pendingOperations: changes" in app


def test_production_script_and_execution_plan_use_business_confirmation_language() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for phrase in ("这段可以", "这段要调整", "制作剧本已锁定", "锁定镜头执行单", "制作准备已完成", "读取已锁定的镜头执行单并生成样片"):
        assert phrase in app
    assert "shot-execution-rail" in app
    assert "overflow-x: auto" in css
    assert "生成预览" in app
    assert "执行单锁定后才能生成" in app
    assert "quoteShotGeneration" in app
    assert "createShotGeneration" in app
    assert "供应方" in app
    assert "剩余预算" in app


def test_sample_review_shows_plan_to_sample_execution_trace() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")
    for term in ("执行对照", "本次样片覆盖", "按方案执行", "新增内容", "尚未进入样片"):
        assert term in app
    for term in (".sample-review-workbench", ".sample-execution-trace", ".sample-trace-card"):
        assert term in css


def test_research_decisions_stay_in_place_and_confirm_as_one_flow() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")
    for term in (
        "activeResearchSubstage", "pendingOperations", "researchOperationKey",
        "已完成", "查看影响并确认", "确认并保存决定",
    ):
        assert term in app
    assert 'activeResearchSubstage = "quality"' in app
    assert "direction.title" in app
    assert "去选方向" not in app
    assert 'store.selectStage("proposal")' not in app
    assert "继续 ${projectId}" in app
    for term in (".decision-progress", ".decision-choice", ".decision-confirm-bar", ".is-selected"):
        assert term in css


def test_script_uses_inline_editing_without_a_duplicate_editor_form() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    editors = _read(OPERATOR_ROOT / "editors.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for term in (
        "script-inline-editor", "编辑这段剧本", "保存修改", "取消",
        "replace_section_narration", "flushSave",
    ):
        assert term in app
    assert 'editor?.type === "script_editor"' not in editors
    assert "script-row-heading" in css
    assert "inline-edit-actions" in css


def test_ui_explains_reference_analysis_and_source_mapping_rationale() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for term in (
        "data.reference", "爆款结构", "为什么有效", "可复刻机制", "原创差异",
        "data.reference_basis", "参考视频怎么拍", "这条分镜用哪条素材", "shot.mapping_reason",
    ):
        assert term in app
    assert "reference-analysis" in css
    assert "reference-scene-list" in css
    assert "mapping-rationale" in css


def test_shot_mapping_compares_reference_and_owned_evidence_side_by_side() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for term in (
        "renderReferenceEvidence", "shot.reference_evidence", "参考视频怎么拍",
        "这条分镜用哪条素材", "无直接参考片段", "shot-evidence-grid",
    ):
        assert term in app
    for term in (
        ".shot-evidence-grid", ".reference-evidence-panel",
        ".owned-evidence-panel", "grid-template-columns: repeat(2",
    ):
        assert term in css


def test_shot_mapping_editor_keeps_selected_ranges_collapsed_until_adjustment() -> None:
    editors = _read(OPERATOR_ROOT / "editors.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for term in ("已选片段", "调整素材片段", "range.hidden = hasRange"):
        assert term in editors
    assert "这条素材用哪一段" not in editors
    assert "填写开始和结束秒数；参考视频仅用于分析" not in editors
    assert "素材出点" not in editors
    for term in (".shot-range-editor", ".shot-range-inputs", ".editor-help"):
        assert term in css


def test_execution_cards_link_back_to_scene_plan_for_source_adjustments() -> None:
    app = _read(OPERATOR_ROOT / "app.js")

    for term in ("已选片段", "source_coverage", "调整素材片段", "onNavigate()"):
        assert term in app


def test_asset_stage_shows_planned_progress_and_reasons() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    state = _read(REPO_ROOT / "backlot" / "operator_state.py")
    css = _read(OPERATOR_ROOT / "styles.css")

    for term in ("制作就绪", "proxyItems", "源素材准备", "waiting_confirmation_count"):
        assert term in app or term in state
    assert "制作清单" not in app
    assert "item.reason" not in app
    assert "asset-progress" in css


def test_delivery_stage_is_an_operator_review_workbench() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    editors = _read(OPERATOR_ROOT / "editors.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for term in (
        "delivery-review-workbench", "delivery-player", "data.player.poster_url",
        "data.timeline.tracks", "delivery-track", "delivery-playhead",
        "data.candidate_groups", "delivery-candidate", "data.versions",
        "切换成片版本", "暂存修改", "查看影响", "生成新版",
        "replace_delivery_copy", "select_delivery_candidate", "sync_narration",
    ):
        assert term in app or term in editors or term in css
    for term in (
        ".delivery-review-workbench", ".delivery-main", ".delivery-player",
        ".delivery-timeline", ".delivery-track", ".delivery-candidates",
        ".delivery-version-switcher", ".delivery-copy-editor",
    ):
        assert term in css
    assert 'const mutationStage = editor?.type === "delivery_review" ? "delivery_review" : stage.id;' in app


def test_delivery_workbench_restores_and_projects_saved_draft_changes() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    api = _read(OPERATOR_ROOT / "api.js")

    assert "export async function fetchDraft" in api
    assert "fetchDraft(projectId, \"delivery_review\")" in app
    assert "snapshot.drafts?.[mutationStage]?.changes" in app
    assert "pendingCandidateIds" in app
    assert "pendingCopyOverrides" in app


def test_impact_panel_does_not_chain_from_dom_append_return_value() -> None:
    impact = _read(OPERATOR_ROOT / "impact.js")

    assert ".append(document.createElement" not in impact
    assert "change.label || change.field" in impact

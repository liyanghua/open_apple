"""单条审批工作台契约：新壳入口、业务语言、信息架构、五项确认与降级状态。

静态契约测试：读取 operator.html / approval.js / app.js / language.js /
styles.css 的稳定结构、业务文案与禁止回流的技术字段。浏览器行为由
业务方按 1180px / 900px / 390px 三档手动验收（专项计划 Chunk 4）。
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "backlot" / "ui"
OPERATOR_ROOT = UI_ROOT / "operator"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_operator(name: str) -> str:
    return _read(OPERATOR_ROOT / name)


def _visible_html_text(path: Path) -> str:
    source = _read(path)
    source = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", source, flags=re.I | re.S)
    return " ".join(part.strip() for part in re.sub(r"<[^>]+>", " ", source).split() if part.strip())


def _frontline_combined() -> str:
    """一线界面全部可见/语义层文案：HTML 可见文字 + 审批模块 + 语言映射。"""
    return (
        _visible_html_text(UI_ROOT / "operator.html")
        + _read_operator("approval.js")
        + _read_operator("language.js")
    )


# ---------------------------------------------------------------------------
# Task 1: 审批视图专用渲染入口
# ---------------------------------------------------------------------------


def test_approval_shell_entry_is_a_dedicated_render_branch() -> None:
    """审批模式优先走 renderApprovalWorkbench，批级驾驶舱仍走原壳。"""
    app = _read_operator("app.js")
    approval = _read_operator("approval.js")

    assert "isApprovalShellActive" in approval
    assert "renderApprovalWorkbench(" in approval
    assert "view_mode === \"approval\"" in approval
    assert "pending_review" in approval
    assert "parseBatchContext" in approval
    # render() 必须在任何编辑器渲染之前分流；批驾驶舱不进入审批壳。
    assert "isApprovalShellActive" in app
    assert "renderApprovalWorkbench(" in app
    assert 'editor?.type === "batch_review"' in approval
    assert '!== "batch_cockpit"' not in app


def test_approval_shell_has_stable_shell_structure() -> None:
    html = _read(UI_ROOT / "operator.html")
    for marker in (
        "approval-shell", "approval-topbar", "approval-hero",
        "approval-rail", "approval-materials", "approval-main",
        "approval-confirmation", "approval-activity",
    ):
        assert marker in html, marker
    for test_id in ("approval-shell", "approval-rail", "approval-materials", "approval-confirmation"):
        assert f'data-testid="{test_id}"' in html, test_id


def test_approval_view_never_renders_editor_draft_or_restore_controls() -> None:
    approval = _read_operator("approval.js")
    for term in (
        "renderTypedEditor", "./editors.js", "./revisions.js", "./impact.js",
        "saveDraft", "commitDraft", "restoreVersion", "暂存修改", "恢复版本",
        "预览修改影响", "查看影响", "生成新版",
    ):
        assert term not in approval, term


def test_direct_access_is_read_only_and_actions_follow_eligibility() -> None:
    approval = _read_operator("approval.js")
    html = _read(UI_ROOT / "operator.html")
    combined = _frontline_combined()
    # 无批次上下文不渲染返回批量入口；按钮按资格禁用。
    assert "返回批量总览" in html
    assert "navigation" in approval
    assert "hasReviewPermission" in approval or "permissions" in approval
    assert "没有审批权限" in combined
    assert "请重新拉取" in combined


# ---------------------------------------------------------------------------
# Task 2: 前端业务语言收敛
# ---------------------------------------------------------------------------


def test_approval_shell_uses_prototype_business_copy() -> None:
    visible = _visible_html_text(UI_ROOT / "operator.html")
    approval = _read_operator("approval.js")
    language = _read_operator("language.js")
    source = visible + approval + language
    for phrase in (
        "商品视频制作工作台", "当前需要你确认", "本次确认材料",
        "请看样片，并确认 5 件事", "退回修改", "确认通过，继续制作", "查看制作记录",
    ):
        assert phrase in source, phrase


def test_approval_main_interface_has_no_internal_vocabulary() -> None:
    """主界面（HTML 可见文案）不得出现内部枚举/技术字段；技术字段只留在
    API 调用与“制作记录”折叠区。"""
    visible = _visible_html_text(UI_ROOT / "operator.html")
    forbidden = (
        "result_first", "judge", "L1a", "L1b", "VLM advisory",
        "runtime", "revision", "evaluation_report", "subject_hash",
        "workflow_revision", "aggregate_revision", "creative_lock",
        "script_lock", "/projects/", ".json", "OpenMontage", "OPENMONTAGE",
    )
    assert not [term for term in forbidden if term.lower() in visible.lower()], visible


def test_business_language_is_consumed_from_mapping() -> None:
    """app/approval 只消费 language.js 映射，不直接拼接内部阶段名。"""
    language = _read_operator("language.js")
    approval = _read_operator("approval.js")
    for symbol in ("STAGE_LABELS", "GATE_LABELS", "CONFIRMATION_ITEMS", "CONFIRMATION_VALUE_LABELS", "APPROVAL_COPY"):
        assert symbol in language, symbol
    assert "STAGE_LABELS" in approval
    assert "CONFIRMATION_VALUE_LABELS" in approval
    assert "APPROVAL_COPY" in approval


# ---------------------------------------------------------------------------
# Task 3: 顶部上下文与轻量九步进度
# ---------------------------------------------------------------------------


def test_approval_shell_has_topbar_hero_and_lightweight_rail() -> None:
    html = _read(UI_ROOT / "operator.html")
    approval = _read_operator("approval.js")
    for term in ("approval-topbar", "approval-hero", "approval-rail"):
        assert term in html, term
    assert "制作进度" in approval
    assert "需要人工确认" in approval
    assert "step gate" in approval or "is-gate" in approval
    assert "系统自动" in approval or "自动完成" in approval


def test_approval_rail_draws_stages_from_server_not_ui_guess() -> None:
    approval = _read_operator("approval.js")
    assert "project.stages" in approval
    assert "stage.status" in approval
    assert "stage.label" in approval
    assert "STAGE_LABELS" in approval


def test_return_to_batch_is_contextual() -> None:
    html = _read(UI_ROOT / "operator.html")
    approval = _read_operator("approval.js")
    assert 'data-testid="return-to-batch"' in html
    assert "return-batch" in approval or "return-to-batch" in approval
    assert "navigation" in approval


# ---------------------------------------------------------------------------
# Task 4: 审批三栏视觉壳与响应式
# ---------------------------------------------------------------------------


def test_approval_three_column_layout_and_visual_hierarchy() -> None:
    css = _read_operator("styles.css")
    approval = _read_operator("approval.js")
    for selector in (".approval-layout", ".approval-materials", ".approval-main", ".approval-confirmation", ".approval-activity"):
        assert selector in css, selector
    # 视觉层级：视频为主角、深色工作台、暖色状态、卡片圆角 <= 8px。
    for token in ("--approval-bg", "--approval-surface", "--approval-line", "--approval-green", "--approval-amber"):
        assert token in css, token
    assert "border-radius" in css
    assert "approval-player" in css
    assert "approval-video" in css or "preview-video" in css
    # 300px 断点只出现在响应式规则内，不改整体方向。
    assert "minmax(0, 1fr)" in css


def test_approval_responsive_breakpoints() -> None:
    css = _read_operator("styles.css")
    assert "@media (max-width: 1280px)" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 390px)" in css or "@media (max-width: 399px)" in css
    assert "overflow-x: auto" in css
    assert "overflow-x: hidden" in css or "overflow-x: visible" in css or "word-break" in css or "overflow-wrap" in css


def test_approval_uses_editorial_palette_without_brand_neon() -> None:
    css = _read_operator("styles.css")
    approval = _read_operator("approval.js")
    html = _read(UI_ROOT / "operator.html")
    source = css + approval + html
    for term in ("gradient", "linear-gradient", "neon", "logo", "OPENMONTAGE", "OpenMontage"):
        assert term not in source.lower(), term


# ---------------------------------------------------------------------------
# Task 5: 产物按“看什么/判断什么/之后发生什么”重排
# ---------------------------------------------------------------------------


def test_sample_gate_artifact_order_follows_decision_flow() -> None:
    combined = _frontline_combined()
    for term in ("renderApprovalMaterials", "renderApprovalMedia", "renderApprovalOutcome"):
        assert term in _read_operator("approval.js"), term
    for heading in ("样片", "镜头对照", "字幕和口播", "声音效果", "系统检查", "系统建议", "制作依据"):
        assert heading in combined, heading
    assert "画面和声音对照" in combined
    assert "确认通过后" in combined
    assert "退回修改后" in combined


def test_approval_materials_reuse_existing_review_facts() -> None:
    approval = _read_operator("approval.js")
    html = _read(UI_ROOT / "operator.html")
    for source in ("sample_review", "delivery_review", "execution_trace", "audio_tracks", "preview_url"):
        assert source in approval, source
    assert "制作记录" in approval
    assert "<details" in html or "details" in html


def test_approval_renders_per_gate_variants() -> None:
    approval = _read_operator("approval.js")
    for term in ("script", "assets", "sample", "delivery"):
        assert f'"{term}"' in approval or term in approval, term
    for phrase in ("生成清单", "制作脚本"):
        assert phrase in approval, phrase


# ---------------------------------------------------------------------------
# Task 6: 五项确认与单条审批动作
# ---------------------------------------------------------------------------


def test_five_confirmations_use_business_values() -> None:
    language = _read_operator("language.js")
    approval = _read_operator("approval.js")
    combined = _frontline_combined()
    for item in ("创意方向", "开头", "证明", "节奏", "字幕"):
        assert item in language, item
    assert "通过" in language and "需要修改" in language and "不通过" in language
    assert "CONFIRMATION_VALUE_LABELS" in approval
    assert '"pass"' in language or '"pass"' in approval
    assert '"adjust"' in language or '"adjust"' in approval
    assert '"redirect"' in language or '"redirect"' in approval
    assert "未全通过" in combined or "有一项确认未通过" in combined or "全部通过" in combined


def test_approval_only_actions_are_reject_and_approve() -> None:
    approval = _read_operator("approval.js")
    combined = _frontline_combined()
    assert "decideReview(" in approval
    assert "review_id" in approval and "subject_hash" in approval and "subject_version" in approval
    assert "effect_confirmations" in approval
    assert "退回修改" in combined and "确认通过，继续制作" in combined
    for forbidden in ("暂存", "修改并重跑", "编辑工作室", "局部修改", "渲染引擎", "批量重跑"):
        assert forbidden not in approval, forbidden


def test_approval_maps_stale_forbidden_validation_outcomes() -> None:
    approval = _read_operator("approval.js")
    combined = _frontline_combined()
    for message in ("结果有更新，请重新拉取", "没有审批权限", "有一项确认未通过", "该内容已经完成确认，请重新拉取"):
        assert message in combined, message
    assert '"stale"' in approval
    assert '"review_stale"' in approval
    assert '"review_already_decided"' in approval
    assert '"forbidden"' in approval
    assert '"validation_failed"' in approval


# ---------------------------------------------------------------------------
# Task 7: 失败、缺失、播放失败与直接访问
# ---------------------------------------------------------------------------


def test_approval_degraded_states_have_visible_reasons_and_recovery() -> None:
    approval = _read_operator("approval.js")
    combined = _frontline_combined()
    for message in (
        "样片无法播放，请重新拉取最新结果", "样片未生成", "候选已不可用",
        "报告不完整", "没有审批权限", "重新拉取",
    ):
        assert message in combined, message
    assert "isAvailable" in approval or "available" in approval or "Unavailable" in approval


def test_approval_never_fakes_an_approved_state_after_failed_submit() -> None:
    approval = _read_operator("approval.js")
    app = _read_operator("app.js")
    assert "已通过" not in approval
    # 提交后统一回到 app.js 的刷新路径重新拉取快照。
    assert "requestApprovalRefresh" in approval
    assert "approval-refresh-request" in approval
    assert 'addEventListener("approval-refresh-request", () => refresh())' in app


# ---------------------------------------------------------------------------
# 阶段中间产物阅读器（用户反馈：新壳不能丢九步历史产物）
# ---------------------------------------------------------------------------


def test_step_reader_exposes_every_stage_artifacts() -> None:
    app = _read_operator("app.js")
    approval = _read_operator("approval.js")
    css = _read_operator("styles.css")
    combined = _frontline_combined()
    # 点击任意步骤 → 同一审批工作台切换当前阶段；可回到当前确认门。
    assert "approval-select-stage" in approval
    assert "approval-select-stage" in app
    assert "approval-select-current" in approval
    assert "approval-select-current" in app
    assert "回到当前确认" in combined
    assert "approval-detail" in approval
    assert ".approval-detail" in css
    # 九步中间产物由统一适配器覆盖，不再直接复用旧阶段 renderer。
    assert "buildApprovalViewModel" in approval
    for renderer in ("renderResearch", "renderProposal", "renderScript", "renderAssets", "renderDelivery"):
        assert f"{renderer}(" not in approval, renderer


def test_approval_workbench_uses_one_browsing_state_for_stage_and_artifact() -> None:
    app = _read_operator("app.js")
    approval = _read_operator("approval.js")
    store = _read_operator("store.js")
    model = _read_operator("approval_model.js")
    combined = _frontline_combined()
    assert "reviewGateId" in store
    assert "selectedArtifactId" in store
    assert "selectArtifact" in store
    assert "buildApprovalViewModel" in model
    assert 'addEventListener("approval-select-stage"' in app
    assert 'addEventListener("approval-select-artifact"' in app
    assert "selectedStageId" in approval
    assert "selectedArtifactId" in approval
    assert "aria-current" in approval
    assert "approval-detail" in approval
    assert "回到当前确认" in combined


def test_approval_workbench_keeps_actions_on_current_gate_only() -> None:
    approval = _read_operator("approval.js")
    app = _read_operator("app.js")
    assert "canAct" in approval
    assert "selectedStageId === reviewGateId" in approval
    assert "approval-readonly-state" in approval
    assert "approval-select-artifact" in approval
    assert "renderConfirmation(project, model)" in approval or "renderConfirmation(model)" in approval
    assert "stepReaderStageId" not in app


def test_approval_interactions_are_keyboard_and_refresh_safe() -> None:
    approval = _read_operator("approval.js")
    store = _read_operator("store.js")
    assert "<button" not in approval  # DOM is created through node(), not raw markup.
    assert "setSelectedStage" in store or "selectStage" in store
    assert "history.replaceState" in store
    assert "aria-live" in approval or 'setAttribute("role", "status")' in approval


# ---------------------------------------------------------------------------
# 批量工作台：套用原型深色外框（用户反馈：批量页仍是旧白底管理页）
# ---------------------------------------------------------------------------


def test_batch_workbench_uses_approval_chrome() -> None:
    app = _read_operator("app.js")
    html = _read(UI_ROOT / "operator.html")
    css = _read_operator("styles.css")
    combined = _frontline_combined()
    assert "批量总览" in combined
    assert "renderBatchApproval" in app
    assert "approval-sheet" in app
    assert ".approval-sheet" in css
    # 初始壳保持中性，读取到批次后再切换浅色 batch 模式，避免加载时
    # 被 batch 的强覆盖规则提前显示空审批壳。
    assert 'data-mode="default"' in html
    assert 'setPageMode("batch")' in app
    assert '#operator-shell[data-mode="batch"] .workbench' in css
    # 保留批量比较、当前确认和统一选择能力。
    for term in ("本批视频", "当前要做", "确认勾选的视频", "进入精剪"):
        assert term in app, term


# ---------------------------------------------------------------------------
# 补充 Chunk 5（专项 2026-08-31）Task 2.1/2.2：阶段专用详情阅读器与统一状态
# ---------------------------------------------------------------------------


def test_stage_detail_readers_cover_nine_stage_groups() -> None:
    """Task 2.1：九类阶段详情分流存在，renderArtifactValue 只作为 fallback。"""
    approval = _read_operator("approval.js")
    for reader in (
        "STAGE_DETAIL_READERS",
        "renderReferenceHighlightsDetail",
        "renderConceptDetail",
        "renderControlPlanDetail",
        "renderScriptDetail",
        "renderScriptEntryDetail",
        "renderShotPlanDetail",
        "renderGenerationListDetail",
        "renderGenerationTasksDetail",
        "renderShotComparisonDetail",
        "renderCaptionsVoiceDetail",
        "renderEditResultDetail",
        "renderComposeReadinessDetail",
        "renderQualityConclusionDetail",
        "renderVersionHistoryDetail",
        "renderPlatformsDetail",
        "renderDeliveryPackageDetail",
        "renderQaEvidenceDetail",
    ):
        assert reader in approval, reader
    assert "renderArtifactValue" in approval
    assert "currentApprovalProjectId" in approval


def test_detail_readers_present_business_facts_and_media_actions() -> None:
    """Task 2.1：时间区间、总控单、差异、下载动作使用业务语义，不再由通用递归渲染承担。"""
    approval = _read_operator("approval.js")
    for phrase in (
        "成片时间轴", "源素材区间", "镜头目的", "素材能证明什么", "安排理由",
        "导演总控单", "为什么有效", "行动引导", "段落目标", "画面重点", "证明要求",
        "字幕差异", "导演规则差异", "下载视频", "下载文件", "下载导出文件",
        "打开制作脚本查看完整内容", "付费生成尚未批准",
        # 真实数据联调修复（2026-08-31 第二轮）：
        "参考片段预览", "自有素材预览", "参考时间区间", "实际口播未提供", "实际字幕未提供",
        "任务质量", "实际费用", "失败原因", "已用于本镜头", "生成任务预览", "已用费用",
    ):
        assert phrase in approval, phrase
    assert "mediaDownload(" in approval
    assert "mediaVideo(" in approval


def test_approval_unified_missing_and_failure_copy() -> None:
    """Task 2.2：统一空态/失败态中文与恢复动作；详情阅读器沿用同一套文案。"""
    approval = _read_operator("approval.js")
    combined = _frontline_combined()
    for phrase in (
        "这项材料暂未生成", "这项材料还在准备中", "这项材料处理失败",
        "请重新拉取最新结果", "资料异常", "正在准备",
    ):
        assert phrase in combined, phrase
    assert "approval-select-artifact" in approval


def test_ui_layer_references_engineering_fields_only_in_technical_filter() -> None:
    """Task 3.1：工程字段 token 只出现在技术字段过滤函数内，不被 UI 层消费或渲染。"""
    approval = _read_operator("approval.js")
    for token in ("control_rule_refs", "plan_id", "source_media_id", "model_family"):
        outside = re.sub(r"function isTechnicalArtifactKey\(.*?\n\}", "", approval, flags=re.S)
        assert token not in outside, token
    assert "isTechnicalArtifactKey" in approval


def test_stage_material_jump_and_download_controls_are_keyboard_operable() -> None:
    """Task 3.2：阶段、材料、跳转和下载动作使用原生 button/anchor，键盘可达。"""
    approval = _read_operator("approval.js")
    assert 'node("button", "approval-step"' in approval or 'node("button", cls.join' in approval
    assert 'node("button", `approval-artifact' in approval
    assert 'node("button", "approval-jump"' in approval
    assert 'createElement("a")' in approval
    assert "href = url" in approval


def test_media_refresh_and_material_cards_keep_live_regions_and_stable_anchors() -> None:
    """Task 3.2：媒体失败使用 aria-live；材料卡保留 aria-current 和稳定 data-testid。"""
    approval = _read_operator("approval.js")
    assert '"aria-live", "polite"' in approval
    assert '"aria-current"' in approval
    assert "approval-artifact-${artifact.id}" in approval
    assert "dataset.testid" in approval


def test_sample_gate_narration_copy_uses_actual_not_planned() -> None:
    """P1-3 回归：口播结论只看实际口播音轨与实际字幕，不把计划字幕当成已配好。"""
    approval = _read_operator("approval.js")
    assert "shot.actual?.narration" in approval
    assert "shot.actual?.screen_copy" in approval
    assert "narrationReady && captionsReady" in approval
    assert "口播或字幕还没有完整核对" in approval
    assert "暂无实际口播字幕" in approval
    # 不再把计划字幕当作口播文本来源
    assert "shot.planned?.screen_copy || \"\"" not in approval


def test_business_enum_maps_cover_tasks_operations_and_dimensions() -> None:
    """P2-8 回归：生成任务质量/方式与评价维度集中中文映射，阅读器不直接展示内部枚举。"""
    approval = _read_operator("approval.js")
    for table in ("TASK_QUALITY_LABELS", "GENERATION_OPERATION_LABELS", "EVALUATION_DIMENSION_LABELS"):
        assert table in approval, table
    for phrase in ("快速预览", "清晰版", "文生视频", "图生视频", "开头清楚", "字幕清楚"):
        assert phrase in approval, phrase
    assert "TASK_QUALITY_LABELS[task.quality]" in approval
    assert "GENERATION_OPERATION_LABELS[task.operation]" in approval
    assert "evaluationDimensionLabel(dimension.name)" in approval
    # 评价结论动作不再以英文枚举出现在界面
    for phrase in ("需要修改", "需要修复", "不通过", "继续制作"):
        assert phrase in approval, phrase


def test_original_sound_state_has_business_labels() -> None:
    """P1-4 回归：原声按存在状态表达，缺失信号显示“原声状态未记录”。"""
    approval = _read_operator("approval.js")
    for phrase in ("有原声", "未保留原声", "原声状态未记录"):
        assert phrase in approval, phrase
    assert 'track.kind === "original"' in approval


def test_simple_gate_reject_requires_issue_tags() -> None:
    """P1-1 回归：脚本/制作准备退回必须携带结构化原因标签。"""
    approval = _read_operator("approval.js")
    assert "GATE_ISSUE_TAG_OPTIONS" in approval
    assert "退回需要一个原因类型" in approval
    assert "tagSelections.size === 0" in approval
    assert "tags = decision === \"rejected\" ? [...tagSelections] : null" in approval
    for phrase in ("卖点不够清楚", "制作清单缺项", "字幕会遮挡画面"):
        assert phrase in approval, phrase


def test_confirmation_gated_by_material_and_report_completeness() -> None:
    """P1-2 回归：依据不完整（材料缺失/报告不完整/阶段失败）时阻止审批动作。"""
    approval = _read_operator("approval.js")
    assert "gateMaterialsReady" in approval
    assert "当前依据还不完整" in approval
    assert 'key.health !== "ready"' in approval
    assert 'gateId === "sample"' in approval


def test_done_panel_never_claims_pass_when_qa_requires_adjustment() -> None:
    """P1-6 回归：成片完成面板按 qa_status 呈现，不硬编码检查通过。"""
    approval = _read_operator("approval.js")
    assert "qaOk" in approval
    assert "检查还有问题 · 请先查看检查结果并处理" in approval
    assert "本条候选的成片检查还没有通过" in approval


def test_sample_gate_copy_acknowledges_incomplete_shots() -> None:
    """P1-7 回归：镜头未完整进入样片时不再绿色“已按方案制作”。"""
    approval = _read_operator("approval.js")
    assert "plannedShotCount" in approval
    assert "fullyExecuted" in approval
    assert "未完整进入样片" in approval


def test_timeline_embeds_player_when_media_area_has_no_video() -> None:
    """P1-8 回归：从镜头对照打开时间轴时自带播放器，片段可跳转。"""
    approval = _read_operator("approval.js")
    assert "approval-timeline-video" in approval
    assert "样片还没有生成，暂不能跳转" in approval
    assert 'video.currentTime = segment.start' in approval


def test_system_suggestion_respects_evaluation_conclusion() -> None:
    """P2-9 回归：revise/repair 时不显示“整体正常 · 建议通过”。"""
    approval = _read_operator("approval.js")
    assert "needsRework" in approval
    assert "系统建议修改后再确认" in approval


def test_evaluation_dimension_labels_normalize_real_report_titles() -> None:
    """P2-10 回归：真实报告维度名（Hook Clarity 等）归一化后映射中文。"""
    approval = _read_operator("approval.js")
    assert "evaluationDimensionLabel" in approval
    assert 'raw.toLowerCase().replace(/[\\s\\-_]+/g, "_")' in approval
    assert "EVALUATION_DIMENSION_LABELS[normalized]" in approval


def test_technical_enums_never_render_raw() -> None:
    """P2-11 回归：时长检查状态与制作记录下一步都经 displayValue 中文映射。"""
    approval = _read_operator("approval.js")
    assert 'detailRow("检查状态", displayValue(payload.status))' in approval
    assert 'detailRow("下一步", displayValue(data.evaluation.recommended_action)' in approval

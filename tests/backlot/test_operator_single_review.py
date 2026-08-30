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
    for message in ("结果有更新，请重新拉取", "没有审批权限", "有一项确认未通过"):
        assert message in combined, message
    assert '"stale"' in approval
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

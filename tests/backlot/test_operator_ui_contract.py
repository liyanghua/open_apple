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
        "口播与字幕",
        "镜头映射",
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


def test_research_review_is_read_only_without_business_note_controls() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    editors = _read(OPERATOR_ROOT / "editors.js")

    assert 'if (editor?.type === "research_review") return;' in app
    assert "业务备注" not in editors
    assert 'editor?.type === "research_review"' not in editors


def test_script_uses_inline_editing_without_a_duplicate_editor_form() -> None:
    app = _read(OPERATOR_ROOT / "app.js")
    editors = _read(OPERATOR_ROOT / "editors.js")
    css = _read(OPERATOR_ROOT / "styles.css")

    for term in (
        "script-inline-editor", "编辑这段口播与字幕", "保存修改", "取消",
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
        "data.reference_basis", "参考机制", "素材匹配", "shot.mapping_reason",
    ):
        assert term in app
    assert "reference-analysis" in css
    assert "reference-scene-list" in css
    assert "mapping-rationale" in css

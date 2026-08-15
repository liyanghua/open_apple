"""Static contract for the read-only, business-facing fastline UI."""

from pathlib import Path


UI_DIR = Path(__file__).resolve().parents[2] / "backlot" / "ui"


def test_fastline_ui_uses_ecommerce_business_language() -> None:
    javascript = (UI_DIR / "board.js").read_text(encoding="utf-8")
    stylesheet = (UI_DIR / "board.css").read_text(encoding="utf-8")

    assert "function renderFastlineStatus" in javascript
    for label in (
        "制作进度",
        "预计还需",
        "已节省制作时间",
        "本次修改影响",
        "下一步",
        "查看制作详情",
        "内容复用明细",
        "请回到任务中确认",
    ):
        assert label in javascript
    assert '.fastline-status' in stylesheet
    assert "overflow-wrap: anywhere" in stylesheet

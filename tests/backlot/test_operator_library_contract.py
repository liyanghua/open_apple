from pathlib import Path


UI = Path(__file__).resolve().parents[2] / "backlot/ui"


def test_library_is_chinese_business_workspace_with_skill_intake() -> None:
    source = (UI / "index.html").read_text(encoding="utf-8") + (UI / "library.js").read_text(encoding="utf-8")
    for label in ("视频项目工作台", "新建复刻项目", "商品名称", "参考视频路径", "自有素材路径", "版权"):
        assert label in source
    for old in ("Library", "NO MEDIA YET", "AWAITING YOU", "scenes", "renders"):
        assert old not in source
    assert "ecommerce-viral-remix" in source

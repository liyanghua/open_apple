import json
from pathlib import Path
import shutil
import subprocess

import pytest


UI = Path(__file__).resolve().parents[2] / "backlot/ui"


def test_library_is_chinese_business_workspace_with_skill_intake() -> None:
    source = (UI / "index.html").read_text(encoding="utf-8") + (UI / "library.js").read_text(encoding="utf-8")
    for label in ("视频项目工作台", "新建复刻项目", "商品名称", "参考视频", "自有素材文件夹", "版权"):
        assert label in source
    for old in ("Library", "NO MEDIA YET", "AWAITING YOU", "scenes", "renders"):
        assert old not in source
    assert "ecommerce-viral-remix" in source


def test_library_filters_non_media_files_from_folder_selection() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the Backlot browser UI")
    module_url = (UI / "media-selection.mjs").as_uri()
    script = f"""
      import {{ filterMediaFiles, selectionSummary }} from {json.dumps(module_url)};
      const mb = 1024 * 1024;
      const selected = [
        {{name: '.DS_Store', size: 1}},
        {{name: 'clip.MP4', size: mb}},
        {{name: 'poster.JPEG', size: 2 * mb}},
        {{name: 'voice.M4A', size: 3 * mb}},
        {{name: 'notes.txt', size: 1}},
      ];
      const result = filterMediaFiles(selected);
      console.log(JSON.stringify({{
        names: result.files.map((file) => file.name),
        ignored: result.ignored,
        summary: selectionSummary(selected),
      }}));
    """
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["names"] == ["clip.MP4", "poster.JPEG", "voice.M4A"]
    assert result["ignored"] == 2
    assert result["summary"] == "已选择 3 个素材，共 6MB；已忽略 2 个非媒体文件"

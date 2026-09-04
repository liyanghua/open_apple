"""桌垫模板测试的"完整素材池"夹具。

真实 v8 素材池只有 4 条（缺 防刮 / 防油易擦拭），而 sheet-01 模板的 8 个 slot
覆盖 6 个动作域。新的 fail-closed 语义会拒绝把 generate 缺口静默伪装成 owned，
因此测试夹具必须提供完整池。

实现说明：匹配/容量/映射代码路径只消费 `_clip_stems()`（名称）与
`_clip_durations()`（时长），不探测物理文件——因此夹具直接补丁这两个模块级
函数（纯名称 + 固定时长 8.5s，覆盖证据窗上界 8.0s），无磁盘/ffprobe 依赖，
也不受测试执行顺序与 tmp_path 环境干扰。

用法（断言全链路的测试开头）：
    from tests.lib._tablemat_pool import install_complete_pool
    install_complete_pool(monkeypatch, tmp_path)
"""
from __future__ import annotations

from pathlib import Path

import lib.template_source_match as tsm

ROOT = Path(__file__).resolve().parents[2]
V8_PRODUCT = ROOT / "projects/table-mat-mix-v8/inputs/source/video/product"
COMPLETE_NAMES = [
    "product_透明桌垫-无甲醛检测.MP4",
    "product_透明桌垫-桌角对齐-挤压不变形.MP4",
    "product_透明桌垫-自动铺开对齐.MP4",
    "product_透明桌垫-餐桌场景.MP4",
    "product_透明桌垫-防刮.MP4",
    "product_透明桌垫-防油易擦拭.MP4",
]


def install_complete_pool(monkeypatch, tmp_path: Path) -> Path:
    """把 _clip_stems/_clip_durations 补齐到 6 个动作域（monkeypatch 模块级函数）。"""
    stems = [name.removesuffix(".MP4") for name in COMPLETE_NAMES]
    durations = {stem: 8.5 for stem in stems}
    monkeypatch.setattr(tsm, "_clip_stems", lambda: list(stems))
    monkeypatch.setattr(tsm, "_clip_durations", lambda: dict(durations))
    # PRODUCT_VIDEO_DIR 仅被 _clip_stems 消费（已被补丁）；置为占位防止其他路径误读真实池
    monkeypatch.setattr(tsm, "PRODUCT_VIDEO_DIR", tmp_path / "pool-placeholder")
    return tmp_path / "pool-placeholder"

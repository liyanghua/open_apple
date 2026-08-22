"""music_profile → 检索词映射（固化债：music_profile→搜索词映射）。

v8 的 BGM 选择（"Indie Acoustic"）是 Agent 手工判断。此模块把参考片
music_profile（情绪/速度/能量等自然语言描述）映射为可检索的搜索词列表
（pixabay 等素材库通用），供 asset-director 直接使用，避免每次重新发挥。

provider 无关：只产出搜索词与备注；具体调用走 music_search 工具。
"""

from __future__ import annotations

from typing import Any, Mapping

_KEYWORD_TERMS: list[tuple[tuple[str, ...], str]] = [
    (("indie", "acoustic", "木吉他", "民谣"), "indie acoustic"),
    (("warm", "温馨", "温暖"), "warm instrumental"),
    (("upbeat", "bright", "轻快", "明亮"), "upbeat light"),
    (("energetic", "电子", "electronic", "动感"), "upbeat electronic"),
    (("cinematic", "epic", "史诗", "电影感"), "cinematic emotional"),
    (("lo-fi", "lofi", "chill", "松弛"), "lo-fi chill"),
    (("jazz", "爵士"), "smooth jazz"),
    (("piano", "钢琴"), "solo piano"),
    (("rock", "摇滚"), "indie rock"),
    (("ambient", "氛围", "环境音"), "ambient pad"),
    (("rhythmic", "节奏感", "打击"), "rhythmic percussion"),
    (("hopeful", "inspirational", "励志", "希望"), "inspirational uplifting"),
]


def music_profile_to_search_terms(profile: str | Mapping[str, Any] | None) -> list[str]:
    """Map a music profile (free text or {mood/tempo/energy}) to search terms.

    Returns an ordered list of candidate search terms; empty when the profile
    carries no recognizable signal (caller falls back to its own defaults).
    """
    if not profile:
        return []
    if isinstance(profile, Mapping):
        text = " ".join(
            str(profile.get(key) or "")
            for key in ("mood", "tempo", "energy", "style", "description")
        )
    else:
        text = str(profile)
    lowered = text.lower()
    terms: list[str] = []
    for keywords, term in _KEYWORD_TERMS:
        if any(keyword.lower() in lowered for keyword in keywords):
            if term not in terms:
                terms.append(term)
    return terms

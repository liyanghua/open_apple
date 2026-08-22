"""music_profile → 搜索词映射测试（固化债：music_profile→搜索词映射）。"""

from __future__ import annotations

from lib.music_profile import music_profile_to_search_terms


def test_empty_profile_returns_no_terms():
    assert music_profile_to_search_terms(None) == []
    assert music_profile_to_search_terms("") == []


def test_free_text_mapping():
    assert music_profile_to_search_terms("warm indie acoustic 木吉他") == [
        "indie acoustic",
        "warm instrumental",
    ]


def test_mapping_fields_mapping():
    terms = music_profile_to_search_terms({"mood": "energetic", "tempo": "fast"})
    assert terms == ["upbeat electronic"]


def test_unknown_profile_returns_empty():
    assert music_profile_to_search_terms("纯文字无信号") == []


def test_v8_indie_acoustic_case():
    # v8 的真实选择："Indie Acoustic" 暖色调——映射应命中 indie acoustic。
    terms = music_profile_to_search_terms("温暖、轻松、原声木吉他 indie 风格")
    assert "indie acoustic" in terms
    assert "warm instrumental" in terms

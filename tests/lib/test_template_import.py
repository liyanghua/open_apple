"""Unit tests for lib.template_import (43-sheet template_pack)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.template_import import (
    _make_template_id,
    _normalize_caption_treatment,
    _parse_interval,
    build_template_pack,
)

REPO = Path(__file__).resolve().parents[2]
XLSX = REPO / "docs/insight_source/视频分镜拆解_2026-08-15.xlsx"


def test_normalize_caption_treatment_from_effect_column():
    # I 特效列 → treatment；不根据 H 花字(cell)猜测（doc §1.2）
    assert _normalize_caption_treatment("字幕动画", "贴合桌面") == ("animated", False)
    assert _normalize_caption_treatment("淡入", "贴合桌面") == ("fade_in", False)
    assert _normalize_caption_treatment("淡出", "贴合桌面") == ("fade_out", False)
    assert _normalize_caption_treatment("字幕", "贴合桌面") == ("subtitle", False)
    # I 空 + H 有字 → static（有花字但未记录动画）
    assert _normalize_caption_treatment("", "贴合桌面") == ("static", False)
    # I 空 + H 空 → none
    assert _normalize_caption_treatment("", "") == ("none", False)
    # 未知特效 → unknown + warning
    assert _normalize_caption_treatment("弹跳", "x") == ("unknown", True)


def test_make_template_id_parses_sheet_name():
    # 视频编号不连续 + 商品 slug
    assert _make_template_id("视频1_AKS桌垫", 1) == "sheet-01-video1-aks-zhuodian"
    assert _make_template_id("视频48_岩板桌架", 48) == "sheet-48-video48-yanban-zhuojia"
    assert _make_template_id("视频4_桌垫", 4) == "sheet-04-video4-zhuodian"


def test_parse_interval():
    assert _parse_interval("0.0-2.0s") == {"start_s": 0.0, "end_s": 2.0, "duration_s": 2.0}
    assert _parse_interval("2.0-4.0s")["duration_s"] == 2.0
    assert _parse_interval("bad")["duration_s"] is None


@pytest.mark.skipif(not XLSX.exists(), reason="43-sheet xlsx not present")
def test_build_template_pack_parses_43_templates_and_validates():
    from lib.artifact_hashing import attach_hashes
    from schemas.artifacts import validate_artifact

    pack = build_template_pack(XLSX)
    assert len(pack["templates"]) == 43
    assert pack["source_document"]["sha256"]
    assert len(pack["normalization_warnings"]) == 0
    # 每个模板有稳定 template_id + slots
    for template in pack["templates"]:
        assert template["template_id"]
        assert template["slots"]
    # 首镜 treatment 来自特效列
    assert pack["templates"][0]["slots"][0]["caption_treatment"] in {
        "fade_in", "subtitle", "animated", "static", "fade_out", "none", "unknown"
    }
    # 幂等：同文件连续导入（含相对/绝对路径）产生相同 artifact + semantic hash
    from lib.artifact_hashing import attach_hashes

    s1 = attach_hashes(dict(pack))
    validate_artifact("template_pack", s1)
    s2 = attach_hashes(dict(build_template_pack(str(XLSX.resolve()))))
    assert s1["artifact_sha256"] == s2["artifact_sha256"]
    assert s1["semantic_sha256"] == s2["semantic_sha256"]

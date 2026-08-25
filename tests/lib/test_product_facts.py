"""Unit tests for lib.product_facts (产品事实卡)."""

from __future__ import annotations

import json
from pathlib import Path

from lib.product_facts import (
    check_text_facts,
    expected_facts_from_card,
    fact_continuity_rules,
    load_product_facts,
    load_product_facts_status,
)


def _write_card(project_dir: Path, card: dict) -> None:
    (project_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (project_dir / "artifacts" / "product_facts.json").write_text(
        json.dumps(card, ensure_ascii=False), encoding="utf-8"
    )


def test_load_full_card_and_convert_to_expected_facts(tmp_path: Path):
    _write_card(tmp_path, {
        "version": "1.0", "product_name": "透明桌垫",
        "sku": "TM-2mm", "price": "49.9元", "params": ["厚度 2mm", "尺寸 60×120cm"],
        "provenance": {"sku": "用户填写"}, "filled_by": "user",
    })
    loaded = load_product_facts(tmp_path)
    assert loaded is not None
    assert loaded["product_name"] == "透明桌垫"
    facts = expected_facts_from_card(loaded)
    assert facts == {"sku": "TM-2mm", "price": "49.9元", "params": ["厚度 2mm", "尺寸 60×120cm"]}


def test_load_returns_none_when_missing(tmp_path: Path):
    assert load_product_facts(tmp_path) is None


def test_skipped_card_yields_empty_expected_facts(tmp_path: Path):
    _write_card(tmp_path, {"version": "1.0", "product_name": "透明桌垫", "filled_by": "skipped"})
    assert expected_facts_from_card(load_product_facts(tmp_path)) == {}


def test_empty_string_fields_are_dropped(tmp_path: Path):
    _write_card(tmp_path, {
        "version": "1.0", "product_name": "透明桌垫",
        "sku": "  ", "price": "", "params": ["", "   "],
    })
    assert expected_facts_from_card(load_product_facts(tmp_path)) == {}


def test_none_card_yields_empty(tmp_path: Path):
    assert expected_facts_from_card(None) == {}


def test_load_product_facts_status_absent(tmp_path: Path):
    status, card = load_product_facts_status(tmp_path)
    assert status == "absent" and card is None


def test_load_product_facts_status_skipped(tmp_path: Path):
    _write_card(tmp_path, {"version": "1.0", "product_name": "透明桌垫", "filled_by": "skipped"})
    status, card = load_product_facts_status(tmp_path)
    assert status == "skipped"
    assert card is not None


def test_load_product_facts_status_valid(tmp_path: Path):
    _write_card(tmp_path, {"version": "1.0", "product_name": "透明桌垫", "sku": "TM-2mm"})
    status, _ = load_product_facts_status(tmp_path)
    assert status == "valid"


def test_load_product_facts_status_invalid(tmp_path: Path):
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts" / "product_facts.json").write_text("{not json", encoding="utf-8")
    status, card = load_product_facts_status(tmp_path)
    assert status == "invalid" and card is None


def test_fact_continuity_rules_cover_sku_price_params():
    card = {"sku": "TPU桌垫", "price": "69元", "params": ["透明极简", "防水防油", "0甲醛"]}
    rules = fact_continuity_rules(card)
    assert any("TPU桌垫" in r for r in rules)
    assert any("69元" in r for r in rules)
    assert any("透明极简" in r for r in rules)
    assert any("0甲醛" in r for r in rules)


def test_fact_continuity_rules_empty_when_no_card():
    assert fact_continuity_rules(None) == []
    assert fact_continuity_rules({}) == []


def test_check_text_facts_no_conflict():
    card = {"sku": "TPU桌垫", "price": "69元", "params": ["透明极简", "防水防油", "0甲醛"]}
    assert check_text_facts("透明桌垫 69元 防水防油", card) == []


def test_check_text_facts_price_conflict():
    card = {"price": "69元"}
    assert check_text_facts("只要 49 元", card) == ["价格冲突：出现「49 元」，应为「69元」"]


def test_check_text_facts_sku_conflict():
    card = {"sku": "TM-2mm"}
    conflicts = check_text_facts("型号 TM-9999", card)
    assert conflicts and "SKU 冲突" in conflicts[0]


def test_check_text_facts_empty_when_no_card():
    assert check_text_facts("任何文字 99元", None) == []


def test_fact_continuity_rules_covers_claims_and_visual_identity():
    card = {
        "sku": "TM-2mm", "price": "69元",
        "claims": [
            {"claim": "0甲醛", "status": "needs_evidence", "evidence": "检测报告"},
            {"claim": "全网最低价", "status": "forbidden"},
        ],
        "visual_identity": {"must_preserve": ["透明材质"], "forbidden": ["变色", "变形"]},
    }
    rules = fact_continuity_rules(card)
    assert any("禁止声称「全网最低价」" in r for r in rules)
    assert any("0甲醛" in r and "证据" in r for r in rules)
    assert any("透明材质" in r for r in rules)
    assert any("变色" in r for r in rules)


def test_load_product_facts_accepts_claims_and_visual_identity(tmp_path: Path):
    _write_card(tmp_path, {
        "version": "1.0", "product_name": "透明桌垫", "sku": "TM-2mm",
        "claims": [{"claim": "防水防油", "status": "authorized"}],
        "visual_identity": {"must_preserve": ["透明"], "forbidden": ["变色"]},
    })
    status, card = load_product_facts_status(tmp_path)
    assert status == "valid"
    assert card["claims"][0]["status"] == "authorized"

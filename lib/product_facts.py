"""Product fact card loading (产品事实卡).

生产前由用户填写 SKU/价格/参数 + 出处，落盘为 ``artifacts/product_facts.json``。
此模块负责读取并把卡片转成 ``technical_validator`` 的 ``expected_facts``
（{sku, price, params}），供 L1a 事实类检查从 skip 变为 pass。跳过（无卡片或
字段为空）不报错，只是返回空 expected_facts。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from schemas.artifacts import validate_artifact

_FILENAME = "product_facts.json"

# 与 technical_validator 保持一致的事实识别正则（前向约束复用同一套）。
_SKU_RE = re.compile(r"[A-Za-z]{2,}-?[0-9][A-Za-z0-9\-]{3,}")
_PRICE_RE = re.compile(r"\d+(?:\.\d{1,2})?\s*(?:元|块|RMB|¥|￥)")


def card_path(project_dir: Path) -> Path:
    return Path(project_dir) / "artifacts" / _FILENAME


def load_product_facts(project_dir: Path) -> dict[str, Any] | None:
    """Read + validate the project's product fact card; None if absent/invalid."""
    status, card = load_product_facts_status(project_dir)
    return card if status in {"valid", "skipped"} else None


def load_product_facts_status(project_dir: Path) -> tuple[str, dict[str, Any] | None]:
    """Read the product fact card and classify its state.

    Returns ``(status, card)`` where status is one of:
    - ``absent``   no card file (user never provided one);
    - ``invalid``  card file present but unreadable / schema-invalid;
    - ``skipped``  card valid but has no SKU/price/params (user explicitly skipped);
    - ``valid``    card valid and carries at least one fact.

    ``invalid`` must NOT be treated as "not provided" — it is a provided-but-
    broken input that needs surfacing, not a silent downgrade.
    """
    path = card_path(project_dir)
    if not path.is_file():
        return "absent", None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid", None
    if not isinstance(data, dict):
        return "invalid", None
    try:
        validate_artifact("product_facts", data)
    except Exception:
        return "invalid", None
    if expected_facts_from_card(data):
        return "valid", data
    return "skipped", data


def expected_facts_from_card(card: Mapping[str, Any] | None) -> dict[str, Any]:
    """Convert a fact card into technical_validator's expected_facts.

    Empty fields are dropped so the validator treats them as "skip" rather than
    "provided but empty".
    """
    if not isinstance(card, Mapping):
        return {}
    facts: dict[str, Any] = {}
    for key in ("sku", "price"):
        value = str(card.get(key) or "").strip()
        if value:
            facts[key] = value
    params = [
        str(item).strip()
        for item in (card.get("params") or [])
        if isinstance(item, str) and item.strip()
    ]
    if params:
        facts["params"] = params
    return facts


def fact_continuity_rules(card: Mapping[str, Any] | None) -> list[str]:
    """Derive the creative_control_plan「事实和连续性」rules from the fact card.

    proposal-director 用这些规则约束整条片能说什么：价格/SKU 固定、卖点只
    陈述画面可见事实且不外推。空卡片返回空列表（无约束）。
    """
    if not isinstance(card, Mapping):
        return []
    rules: list[str] = []
    sku = str(card.get("sku") or "").strip()
    price = str(card.get("price") or "").strip()
    params = [str(p).strip() for p in (card.get("params") or []) if isinstance(p, str) and p.strip()]
    if sku:
        rules.append(f"商品编号/SKU 固定为「{sku}」，画面文字不得出现其他编号。")
    if price:
        rules.append(f"价格固定为「{price}」，画面文字不得出现其他价格表述。")
    for param in params:
        rules.append(f"卖点「{param}」表述与事实卡一致；只陈述画面可见事实，不外推。")
    return rules


def check_text_facts(text: str, card: Mapping[str, Any] | None) -> list[str]:
    """Flag conflicts between a text and the fact card (script 前向约束用).

    Returns a list of human-readable conflict messages; empty = no conflict.
    Semantics mirror technical_validator: SKU/价格出现即须一致，参数头 8 字
    出现即须是完整参数表述。
    """
    if not isinstance(card, Mapping) or not isinstance(text, str) or not text:
        return []
    conflicts: list[str] = []
    sku = str(card.get("sku") or "").strip()
    price = str(card.get("price") or "").strip()
    params = [str(p).strip() for p in (card.get("params") or []) if isinstance(p, str) and p.strip()]

    if sku:
        for match in _SKU_RE.finditer(text):
            if match.group(0).upper() != sku.upper():
                conflicts.append(f"SKU 冲突：出现「{match.group(0)}」，应为「{sku}」")
    if price:
        for match in _PRICE_RE.finditer(text):
            if price not in match.group(0):
                conflicts.append(f"价格冲突：出现「{match.group(0)}」，应为「{price}」")
    for param in params:
        head = param[:8]
        if head and head in text and param not in text:
            conflicts.append(f"卖点冲突：出现与「{param}」不一致的表述")
    return conflicts

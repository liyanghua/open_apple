"""Short selling-point copy used by the product-video caption layer."""

from __future__ import annotations

import re


_ATTRIBUTION_PREFIX = re.compile(
    r"^(?:商品页(?:主打|参数标注|标注)|详情页(?:描述|标注)|商品标题(?:宣称|标注))\s*"
)


def core_selling_point(text: str) -> str:
    """Reduce explanatory screen copy to one compact visual selling point."""
    value = str(text or "").strip()
    if not value:
        return ""
    value = _ATTRIBUTION_PREFIX.sub("", value)
    direct = {
        "日常洁面使用画面": "日常洁面",
        "随手取下，进入日常使用": "随手取下",
        "展开挂好，日常取用画面清楚": "展开挂好",
        "一股水浇下，湿润范围清楚可见": "吸水速干",
        "毛圈纹理特写，细节清楚可见": "双面毛圈",
        "手指轻抚毛圈，蓬松纹理看得见": "亲肤柔软",
        "轻揉时，毛圈的蓬松形变画面可见": "亲肤柔软",
        "叠放后的厚度层次，画面看得见": "加厚款",
        "AG+银离子净护": "银离子净护",
    }
    if value in direct:
        return direct[value]
    value = re.split(r"[，,：:；;。]", value, maxsplit=1)[0].strip()
    return value or str(text).strip()

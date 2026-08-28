"""模板动作域标定产物（策略 C：未标定=阻断）。

由 scripts/calibrate_template.py 生成/维护：
- `_CALIBRATIONS`：{template_id: [每 slot 动作域]}（合并后即"标定"）；
- `_CALIBRATION_META`：审计元数据（source/version/calibrated_at/reviewer）。
"""
from __future__ import annotations


_CALIBRATIONS: dict[str, list[str]] = {
    'sheet-02-video2-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防刮', '防油易擦拭'],
}

_CALIBRATION_META: dict[str, dict] = {
    'sheet-02-video2-aks-zhuodian': {'source': 'manual', 'version': '1.0', 'calibrated_at': '2026-08-28T03:38:25', 'reviewer': 'agent'},
}

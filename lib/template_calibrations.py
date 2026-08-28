"""模板动作域标定产物（策略 C：未标定=阻断）+ 标定模板按域口播行。
"""
from __future__ import annotations


_CALIBRATIONS: dict[str, list[str]] = {
    'sheet-02-video2-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防刮', '防油易擦拭'],
    'sheet-03-video3-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '桌角对齐-挤压不变形', '防油易擦拭', '桌角对齐-挤压不变形', '自动铺开对齐', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-06-video6-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防刮', '防油易擦拭', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形'],
    'sheet-07-video7-aks-zhuodian': ['餐桌场景', '防刮', '防刮', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-08-video8-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防刮', '餐桌场景', '防油易擦拭', '防油易擦拭', '防油易擦拭'],
    'sheet-10-video10-aks-zhuodian': ['无甲醛检测', '餐桌场景', '无甲醛检测', '餐桌场景', '餐桌场景', '防油易擦拭', '无甲醛检测', '餐桌场景', '桌角对齐-挤压不变形'],
    'sheet-11-video12-zhuodian': ['防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭'],
    'sheet-12-video13-aks-zhuodian': ['餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景'],
    'sheet-13-video14-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '防油易擦拭', '防刮', '防油易擦拭', '防油易擦拭', '防刮', '餐桌场景'],
    'sheet-15-video17-aks-zhuodian': ['桌角对齐-挤压不变形', '自动铺开对齐', '防刮', '防油易擦拭', '餐桌场景', '防油易擦拭', '桌角对齐-挤压不变形', '无甲醛检测', '餐桌场景'],
    'sheet-16-video18-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防刮', '防油易擦拭', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-17-video19-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '防刮', '防油易擦拭', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-18-video20-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防刮', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '防油易擦拭'],
    'sheet-20-video23-aks-zhuodian': ['桌角对齐-挤压不变形', '防油易擦拭', '防刮', '自动铺开对齐', '餐桌场景', '防油易擦拭', '无甲醛检测', '防油易擦拭', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-21-video25-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '桌角对齐-挤压不变形', '防刮', '餐桌场景', '餐桌场景', '防油易擦拭', '防油易擦拭'],
    'sheet-22-video27-aks-zhuodian': ['餐桌场景', '餐桌场景', '桌角对齐-挤压不变形', '防刮', '防油易擦拭', '防油易擦拭', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-23-video28-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '防刮', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '餐桌场景'],
    'sheet-24-video30-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防刮', '桌角对齐-挤压不变形', '防刮', '桌角对齐-挤压不变形'],
    'sheet-25-video31-aks-zhuodian': ['防刮', '防刮', '防刮', '防刮', '防刮', '防油易擦拭', '桌角对齐-挤压不变形', '防刮', '防刮'],
    'sheet-26-video32-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '防刮', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-27-video33-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '桌角对齐-挤压不变形', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防刮', '防刮'],
    'sheet-28-video34-aks-zhuodian': ['防油易擦拭', '餐桌场景', '自动铺开对齐', '防刮', '自动铺开对齐', '防油易擦拭', '防油易擦拭', '防油易擦拭', '餐桌场景', '防油易擦拭', '防刮', '自动铺开对齐', '防油易擦拭', '无甲醛检测', '无甲醛检测', '无甲醛检测', '防油易擦拭', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形'],
    'sheet-29-video35-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭'],
    'sheet-30-video36-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防刮', '防油易擦拭', '防油易擦拭', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-31-video37-aks-zhuodian': ['餐桌场景', '防油易擦拭', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '防刮', '餐桌场景'],
    'sheet-32-video38-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '防刮', '餐桌场景'],
    'sheet-33-video39-aks-zhuodian': ['餐桌场景', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '餐桌场景', '防油易擦拭', '防油易擦拭', '防刮'],
    'sheet-34-video40-aks-zhuodian': ['餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景'],
    'sheet-35-video41-aks-zhuodian': ['无甲醛检测', '餐桌场景', '餐桌场景', '餐桌场景', '防刮', '防刮', '桌角对齐-挤压不变形', '餐桌场景', '餐桌场景', '餐桌场景', '餐桌场景'],
    'sheet-36-video42-aks-zhuodian': ['自动铺开对齐', '防刮', '防刮', '桌角对齐-挤压不变形', '防油易擦拭', '防油易擦拭', '自动铺开对齐', '防刮', '自动铺开对齐'],
    'sheet-37-video43-aks-zhuodian': ['餐桌场景', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '自动铺开对齐', '餐桌场景', '餐桌场景', '防刮', '桌角对齐-挤压不变形', '自动铺开对齐', '餐桌场景', '防刮', '餐桌场景'],
    'sheet-38-video44-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '桌角对齐-挤压不变形', '防油易擦拭', '防油易擦拭', '防油易擦拭', '无甲醛检测'],
    'sheet-39-video45-aks-zhuodian': ['防油易擦拭', '桌角对齐-挤压不变形', '防刮', '餐桌场景', '防油易擦拭', '餐桌场景', '防刮', '餐桌场景'],
    'sheet-40-video46-aks-zhuodian': ['餐桌场景', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '桌角对齐-挤压不变形', '防油易擦拭', '桌角对齐-挤压不变形'],
    'sheet-41-video47-aks-zhuodian': ['桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '桌角对齐-挤压不变形', '防油易擦拭', '桌角对齐-挤压不变形', '防油易擦拭', '防油易擦拭', '桌角对齐-挤压不变形', '餐桌场景'],
    'sheet-42-video48-yanban-zhuojia': ['防油易擦拭', '餐桌场景', '自动铺开对齐', '餐桌场景', '无甲醛检测', '桌角对齐-挤压不变形', '自动铺开对齐', '自动铺开对齐', '自动铺开对齐', '防刮', '防油易擦拭', '餐桌场景', '餐桌场景'],
    'sheet-43-video49-aks-zhuodian': ['防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭', '防油易擦拭'],
}

_CALIBRATION_META: dict[str, dict] = {
    'sheet-02-video2-aks-zhuodian': {'source': 'manual', 'version': '1.0', 'calibrated_at': '2026-08-28T03:38:25', 'reviewer': 'agent'},
    'sheet-03-video3-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:42:39', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-06-video6-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:43:02', 'reviewer': 'human-check', 'low_conf': [(7, 0.82)]},
    'sheet-07-video7-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:43:17', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-08-video8-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:43:30', 'reviewer': 'human-check', 'low_conf': [(4, 0.7)]},
    'sheet-10-video10-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:43:46', 'reviewer': 'human-check', 'low_conf': [(3, 0.8), (6, 0.75), (7, 0.7), (8, 0.8), (9, 0.65)]},
    'sheet-11-video12-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:44:01', 'reviewer': 'human-check', 'low_conf': [(8, 0.8)]},
    'sheet-12-video13-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:45:48', 'reviewer': 'human-check', 'low_conf': [(7, 0.82), (15, 0.75), (19, 0.78), (23, 0.8), (27, 0.82), (30, 0.83), (32, 0.84), (33, 0.7), (37, 0.8), (40, 0.75), (43, 0.72), (46, 0.78), (47, 0.82), (49, 0.65), (50, 0.7), (51, 0.83), (52, 0.7), (54, 0.84), (55, 0.8), (61, 0.6), (62, 0.82), (63, 0.82), (65, 0.75), (66, 0.75), (67, 0.75), (68, 0.72), (69, 0.75), (72, 0.7), (74, 0.7), (75, 0.83)]},
    'sheet-13-video14-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:46:03', 'reviewer': 'human-check', 'low_conf': [(6, 0.8), (7, 0.75)]},
    'sheet-15-video17-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T04:54:45', 'reviewer': 'human-check', 'low_conf': [(8, 0.75)]},
    'sheet-16-video18-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:46:28', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-17-video19-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:46:43', 'reviewer': 'human-check', 'low_conf': [(8, 0.7)]},
    'sheet-18-video20-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:46:55', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-20-video23-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T04:55:06', 'reviewer': 'human-check', 'low_conf': [(8, 0.82)]},
    'sheet-21-video25-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:47:29', 'reviewer': 'human-check', 'low_conf': [(5, 0.78), (6, 0.82)]},
    'sheet-22-video27-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:47:39', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-23-video28-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:47:55', 'reviewer': 'human-check', 'low_conf': [(9, 0.7)]},
    'sheet-24-video30-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:48:10', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-25-video31-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:48:27', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-26-video32-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:48:41', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-27-video33-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:48:56', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-28-video34-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:49:32', 'reviewer': 'human-check', 'low_conf': [(5, 0.82), (9, 0.8), (11, 0.83), (18, 0.75)]},
    'sheet-29-video35-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:49:48', 'reviewer': 'human-check', 'low_conf': [(8, 0.82)]},
    'sheet-30-video36-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:50:03', 'reviewer': 'human-check', 'low_conf': [(2, 0.82), (6, 0.84)]},
    'sheet-31-video37-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:50:18', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-32-video38-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:50:32', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-33-video39-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:50:46', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-34-video40-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:51:48', 'reviewer': 'human-check', 'low_conf': [(15, 0.84), (17, 0.82), (22, 0.78), (24, 0.83), (35, 0.84)]},
    'sheet-35-video41-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:52:06', 'reviewer': 'human-check', 'low_conf': [(8, 0.8)]},
    'sheet-36-video42-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:52:21', 'reviewer': 'human-check', 'low_conf': [(6, 0.75)]},
    'sheet-37-video43-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:52:42', 'reviewer': 'human-check', 'low_conf': [(10, 0.8)]},
    'sheet-38-video44-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:52:53', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-39-video45-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:53:07', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-40-video46-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:53:22', 'reviewer': 'human-check', 'low_conf': [(9, 0.8)]},
    'sheet-41-video47-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:53:40', 'reviewer': 'auto-accept', 'low_conf': []},
    'sheet-42-video48-yanban-zhuojia': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:54:01', 'reviewer': 'human-check', 'low_conf': [(5, 0.75)]},
    'sheet-43-video49-aks-zhuodian': {'source': 'vlm', 'version': '1.0', 'model': 'qwen-plus', 'threshold': 0.85, 'calibrated_at': '2026-08-28T03:54:13', 'reviewer': 'auto-accept', 'low_conf': []},
}

_GENERATED_ROWS: dict[str, list] = {
    "sheet-15-video17-aks-zhuodian": [
        [
            "软玻璃贴合桌面，不翘边。",
            "贴合 · 不翘边",
            "proof"
        ],
        [
            "自动铺开，轻松对齐。",
            "自动铺开 · 对齐省事",
            "proof"
        ],
        [
            "耐磨防刮，久用如新。",
            "耐刮耐磨 · 久用如新",
            "proof"
        ],
        [
            "油污汤汁，一擦就净。",
            "油污 · 一擦即净",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ],
        [
            "油污汤汁，一擦就净。",
            "油污 · 一擦即净",
            "proof"
        ],
        [
            "软玻璃贴合桌面，不翘边。",
            "贴合 · 不翘边",
            "proof"
        ],
        [
            "0 甲醛，检测报告为证。",
            "0 甲醛 · 报告可查",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ]
    ],
    "sheet-20-video23-aks-zhuodian": [
        [
            "软玻璃贴合桌面，不翘边。",
            "贴合 · 不翘边",
            "proof"
        ],
        [
            "油污汤汁，一擦就净。",
            "油污 · 一擦即净",
            "proof"
        ],
        [
            "耐磨防刮，久用如新。",
            "耐刮耐磨 · 久用如新",
            "proof"
        ],
        [
            "自动铺开，轻松对齐。",
            "自动铺开 · 对齐省事",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ],
        [
            "油污汤汁，一擦就净。",
            "油污 · 一擦即净",
            "proof"
        ],
        [
            "0 甲醛，检测报告为证。",
            "0 甲醛 · 报告可查",
            "proof"
        ],
        [
            "油污汤汁，一擦就净。",
            "油污 · 一擦即净",
            "proof"
        ],
        [
            "软玻璃贴合桌面，不翘边。",
            "贴合 · 不翘边",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ]
    ],
    "sheet-42-video48-yanban-zhuojia": [
        [
            "油污汤汁，一擦就净。",
            "油污 · 一擦即净",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ],
        [
            "自动铺开，轻松对齐。",
            "自动铺开 · 对齐省事",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ],
        [
            "0 甲醛，检测报告为证。",
            "0 甲醛 · 报告可查",
            "proof"
        ],
        [
            "软玻璃贴合桌面，不翘边。",
            "贴合 · 不翘边",
            "proof"
        ],
        [
            "自动铺开，轻松对齐。",
            "自动铺开 · 对齐省事",
            "proof"
        ],
        [
            "自动铺开，轻松对齐。",
            "自动铺开 · 对齐省事",
            "proof"
        ],
        [
            "自动铺开，轻松对齐。",
            "自动铺开 · 对齐省事",
            "proof"
        ],
        [
            "耐磨防刮，久用如新。",
            "耐刮耐磨 · 久用如新",
            "proof"
        ],
        [
            "油污汤汁，一擦就净。",
            "油污 · 一擦即净",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ],
        [
            "餐桌省心，质感如新。",
            "餐桌 · 省心好物",
            "proof"
        ]
    ]
}


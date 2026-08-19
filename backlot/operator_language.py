"""Canonical Chinese business vocabulary for the Backlot operator view."""

from types import MappingProxyType


STAGE_LABELS = MappingProxyType({
    "research": "参考解析与素材体检",
    "proposal": "创意方案",
    "script": "口播与字幕",
    "scene_plan": "分镜",
    "assets": "制作准备",
    "sample": "样片确认",
    "edit": "修改与精剪",
    "compose": "成片生成",
    "publish": "交付下载",
})

STATUS_LABELS = MappingProxyType({
    "pending": "未开始",
    "in_progress": "制作中",
    "awaiting_human": "等待确认",
    "completed": "已完成",
    "failed": "处理失败",
    "unknown": "状态未知",
})

LEGACY_STAGE_LABELS = MappingProxyType({
    "idea": "创意方案",
})

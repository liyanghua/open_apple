"""Canonical Chinese business vocabulary for the Backlot operator view."""

from types import MappingProxyType


STAGE_LABELS = MappingProxyType({
    "research": "了解任务",
    "proposal": "看创意方案",
    "script": "确认脚本",
    "scene_plan": "看分镜",
    "assets": "确认制作准备",
    "sample": "查看样片",
    "edit": "完成剪辑",
    "compose": "检查成片",
    "publish": "确认交付",
})

# 样片五项确认（契约 §4.3；readability 内部枚举保留，业务文案=“字幕”）
EFFECT_CONFIRMATION_LABELS = MappingProxyType({
    "creative_direction": "创意方向是否正确",
    "hook": "开头是否马上抓住人",
    "proof": "产品/主题证明是否清楚",
    "pacing": "节奏和画面是否顺",
    "readability": "字幕是否看得清",
})

CONFIRMATION_VALUE_LABELS = MappingProxyType({
    "pass": "通过",
    "adjust": "需要修改",
    "redirect": "不通过",
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

PUBLISH_STATUS_LABELS = MappingProxyType({
    "exported": "已导出",
    "published": "已发布",
    "failed": "发布失败",
    "draft": "草稿",
    "pending_review": "待审核",
})

PLATFORM_LABELS = MappingProxyType({
    "local": "本地交付",
    "douyin": "抖音",
    "wechat_channels": "视频号",
    "xiaohongshu": "小红书",
})

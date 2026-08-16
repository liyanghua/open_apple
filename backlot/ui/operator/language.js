export const STAGE_ORDER = [
  "参考解析与素材体检",
  "创意方案",
  "口播与字幕",
  "镜头映射",
  "制作准备",
  "样片确认",
  "修改与精剪",
  "成片生成",
  "交付下载",
];

export const VIEW_STATES = {
  loading: "正在读取项目进度",
  empty: "这个项目还没有可展示的制作阶段",
  degraded: "该项目当前为只读查看",
  error: "项目进度暂时无法读取，请稍后重试",
  awaiting: "有内容等待确认",
  completed: "项目制作已完成",
  ready: "项目正在按计划推进",
};

export const STATUS_MARKS = {
  "已完成": "✓",
  "制作中": "●",
  "等待确认": "!",
  "处理失败": "×",
  "未开始": "○",
};

export function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "暂未提供";
  if (value < 60) return `约 ${Math.max(1, Math.round(value))} 秒`;
  const minutes = Math.round(value / 60);
  if (minutes < 60) return `约 ${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `约 ${hours} 小时 ${rest} 分钟` : `约 ${hours} 小时`;
}

export function formatTimeRange(start, end) {
  const safeStart = Number.isFinite(Number(start)) ? Number(start).toFixed(1) : "0.0";
  const safeEnd = Number.isFinite(Number(end)) ? Number(end).toFixed(1) : "0.0";
  return `${safeStart} - ${safeEnd} 秒`;
}

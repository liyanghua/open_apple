export const STAGE_ORDER = [
  "参考解析与素材体检",
  "创意方案",
  "剧本生成",
  "分镜",
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

// ---------------------------------------------------------------------------
// 单条审批工作台业务语言（与 backlot/operator_language.py 的后端映射同源，
// 前端只消费这里的文案，不直接拼接内部阶段名）。
// ---------------------------------------------------------------------------

export const STAGE_LABELS = {
  research: "了解任务",
  proposal: "看创意方案",
  script: "确认脚本",
  scenePlan: "看分镜",
  assets: "确认制作准备",
  sample: "查看样片",
  edit: "完成剪辑",
  compose: "检查成片",
  publish: "确认交付",
};

/** 服务端阶段 id（下划线格式）→ 本映射使用的驼峰键。 */
export function stageLabelKey(id) {
  return String(id || "").replace(/_([a-z])/g, (_, char) => char.toUpperCase());
}

export const GATE_STAGE_IDS = ["script", "assets", "sample"];

export const GATE_LABELS = {
  script: "确认脚本",
  assets: "确认制作准备",
  sample: "查看样片",
};

export const GATE_DETAILS = {
  script: {
    kicker: "请看这段文案",
    heading: "请看脚本，确认可以开始制作",
    confirmTitle: "请确认这段脚本",
    intro: "确认文案、卖点和错别字，没问题就可以继续制作。",
    shownotes: "确认通过后",
  },
  assets: {
    kicker: "请看这份制作清单",
    heading: "请看制作清单，确认可以开始生成",
    confirmTitle: "请确认这份制作清单",
    intro: "确认画面、声音、素材和费用都合适，没问题就可以开始生成。",
    shownotes: "确认通过后",
  },
  sample: {
    kicker: "请看样片",
    heading: "请看样片，并确认 5 件事",
    confirmTitle: "请确认这 5 项",
    intro: "确认画面、开头、证明、节奏和字幕都没有问题。",
    shownotes: "确认通过后",
  },
  done: {
    kicker: "请看成片",
    heading: "请看成片，确认可以交付",
    confirmTitle: "请确认是否交付",
    intro: "确认视频和检查结果都正常，就可以交付。",
    shownotes: "确认通过后",
  },
};

export const CONFIRMATION_ITEMS = [
  { key: "creative_direction", title: "创意方向", prompt: "还是在讲已经确定的核心卖点吗？" },
  { key: "hook", title: "开头", prompt: "前 1–3 秒能让人知道发生了什么并愿意继续看吗？" },
  { key: "proof", title: "证明", prompt: "产品、动作和结果是否看得清楚、说得明白？" },
  { key: "pacing", title: "节奏", prompt: "镜头是否顺畅，没有拖沓、跳跃或重复？" },
  { key: "readability", title: "字幕", prompt: "字幕、产品和重点信息是否清楚且不互相遮挡？" },
];

export const CONFIRMATION_VALUE_LABELS = {
  "pass": "通过",
  "adjust": "需要修改",
  "redirect": "不通过",
};

export const APPROVAL_COPY = {
  brand: "商品视频制作工作台",
  stateAwaiting: "等待确认样片",
  stateDone: "准备交付",
  heroKicker: "当前需要你确认",
  heroKickerIdle: "当前制作进度",
  materialsEyebrow: "本次确认材料",
  materialsHeading: "请先看这些材料",
  railTitle: "制作进度 · 共 9 步",
  railHumanHint: "3 步需要你确认 · 其余自动完成",
  fiveChecksHeading: "请确认这 5 项",
  fiveChecksIntro: "看完样片，逐项选择结果；全部通过后才能继续。",
  approve: "确认通过，继续制作",
  reject: "退回修改",
  activity: "查看制作记录",
  approveOutcomeTitle: "确认通过后",
  rejectOutcomeTitle: "退回修改后",
  approveOutcome: ["保存你的确认结果", "继续完成后续制作", "检查通过后生成可交付视频"],
  rejectOutcome: ["保留现在看到的版本", "记录你指出的问题", "修改后再次给你确认"],
  stale: "结果有更新，请重新拉取",
  alreadyDecided: "该内容已经完成确认，请重新拉取",
  forbidden: "没有审批权限",
  validationFailed: "有一项确认未通过",
  missingMedia: "样片未生成",
  playbackFailed: "样片无法播放，请重新拉取最新结果",
  unavailable: "候选已不可用",
  reportIncomplete: "检查报告不完整，请重新拉取",
  readerBack: "回到当前确认",
  batchKicker: "批量审批",
  batchState: "正在处理",
  batchNote: "先处理当前要确认的内容，再选择要进入精剪的视频。",
};

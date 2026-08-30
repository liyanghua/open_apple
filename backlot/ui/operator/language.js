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
    heading: "请看脚本，并确认是否可以照此制作",
    confirmTitle: "请确认这段脚本",
    intro: "这是下一步制作将使用的文字内容。请确认文案和卖点没错、没有错别字，确认后系统才会开始制作。",
    shownotes: "确认通过后",
  },
  assets: {
    kicker: "请看这份制作清单",
    heading: "请看制作清单，并确认是否开始生成",
    confirmTitle: "请确认这份制作清单",
    intro: "这是本次制作会用到的画面、声音和素材安排。请确认清单完整、金额可接受，确认后系统才会开始生成。",
    shownotes: "确认通过后",
  },
  sample: {
    kicker: "请看样片",
    heading: "请看样片，并确认 5 件事",
    confirmTitle: "请确认这 5 项",
    intro: "这还不是最终成片。请确认画面有没有说清楚卖点、口播和字幕是否正确、观看节奏是否舒服。确认通过后，系统才会继续制作正式成片。",
    shownotes: "确认通过后",
  },
  done: {
    kicker: "请看成片",
    heading: "请看成片，并确认是否交付",
    confirmTitle: "请确认是否交付",
    intro: "这是最终成片和系统检查结果。请确认视频没有问题；如发现问题，请退回修改并说明位置。",
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
  materialsHeading: "请查看以下内容",
  railTitle: "制作进度 · 共 9 步",
  railHumanHint: "3 步需要人工确认 · 其余由系统自动完成",
  fiveChecksHeading: "请确认这 5 项",
  fiveChecksIntro: "5 项都没问题，就点“确认通过”；发现问题，就指出问题并退回修改。",
  approve: "确认通过，继续制作",
  reject: "退回修改",
  activity: "查看制作记录",
  approveOutcomeTitle: "确认通过后",
  rejectOutcomeTitle: "退回修改后",
  approveOutcome: ["保存你的确认结果", "系统自动继续制作", "最终检查通过后才会生成可交付视频"],
  rejectOutcome: ["保留现在看到的版本", "记录你指出的问题", "只修改有问题的部分，再次给你确认"],
  stale: "结果有更新，请重新拉取",
  forbidden: "没有审批权限",
  validationFailed: "有一项确认未通过",
  missingMedia: "样片未生成",
  playbackFailed: "样片无法播放，请重新拉取最新结果",
  unavailable: "候选已不可用",
  reportIncomplete: "系统检查报告不完整，请重新拉取",
};


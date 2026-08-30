import { STAGE_LABELS, stageLabelKey } from "./language.js";

export const APPROVAL_STAGE_ORDER = [
  "research", "proposal", "script", "scene_plan", "assets", "sample", "edit", "compose", "publish",
];

const STAGE_MATERIALS = {
  research: [
    ["task_understanding", "任务理解", ["summary", "task_understanding", "brief"]],
    ["reference_highlights", "参考片重点", ["reference", "highlights", "sources"]],
    ["source_inventory", "素材情况", ["sources", "source_inventory", "source_summary"]],
    ["risks", "制作风险", ["risks", "warnings"]],
  ],
  proposal: [
    ["selected_direction", "采用方向", ["selected_direction", "concept", "visual_approach"]],
    ["alternative_directions", "备选方向", ["alternatives", "alternative_directions"]],
    ["selling_points", "卖点和差异", ["selling_points", "key_selling_points", "why_this_works"]],
  ],
  script: [
    ["production_script", "制作脚本", ["sections", "script", "production_script"]],
    ["narration", "口播", ["narration", "voiceover", "spoken_copy"]],
    ["on_screen_text", "屏幕文字", ["on_screen_text", "screen_copy", "subtitles"]],
    ["duration_check", "时长检查", ["duration_check", "duration_seconds", "checks"]],
  ],
  scene_plan: [
    ["shot_plan", "镜头安排", ["scenes", "shots", "shot_plan"]],
    ["source_mapping", "素材对应", ["source_mapping", "asset_mapping", "sources"]],
    ["action_timing", "动作和时长", ["timing", "total_duration_seconds", "action_timing"]],
  ],
  assets: [
    ["generation_list", "生成清单", ["execution_plan", "generation_list", "shots"]],
    ["visual_assets", "画面素材", ["visual_assets", "assets", "image_assets"]],
    ["narration_subtitles", "口播和字幕", ["narration", "subtitles", "narration_subtitles"]],
    ["music_budget", "音乐和费用", ["audio", "music", "budget", "cost"]],
  ],
  sample: [
    ["sample_video", "样片", ["preview_url", "video_url", "sample_url"]],
    ["shot_comparison", "镜头对照", ["execution_trace", "shots", "shot_comparison"]],
    ["captions_voice", "字幕和口播", ["captions_voice", "narration", "subtitles"]],
    ["sound", "声音", ["audio_tracks", "sound", "audio"]],
    ["system_checks", "系统检查", ["evaluation", "qa_status", "checks"]],
    ["system_suggestions", "系统建议", ["advisory", "suggestions", "recommendations"]],
    ["production_basis", "制作依据", ["production_basis", "execution_trace"]],
  ],
  edit: [
    ["edit_result", "剪辑结果", ["preview_url", "edit_result", "video_url"]],
    ["shot_order", "镜头顺序", ["shot_order", "shots", "scenes"]],
    ["audio_captions", "声音和字幕", ["audio", "subtitles", "audio_captions"]],
  ],
  compose: [
    ["final_video", "完整视频", ["preview_url", "download_url", "final_video", "video_url"]],
    ["picture_sound", "画面声音对照", ["picture_sound", "audio", "video"]],
    ["quality_conclusion", "质量结论", ["qa_status", "quality_conclusion", "checks"]],
  ],
  publish: [
    ["delivery_video", "交付视频", ["download_url", "delivery_video", "preview_url"]],
    ["file_info", "文件信息", ["format_label", "file_info", "duration_seconds"]],
    ["platforms_download", "平台和下载", ["platforms", "entries", "package_files"]],
  ],
};

const STATUS_LABELS = {
  pending: "未开始", in_progress: "制作中", awaiting_human: "等待确认", completed: "已完成", failed: "处理失败",
};
const REVIEW_KIND_TO_STAGE = { script_lock: "script", creative_lock: "assets", sample: "sample" };

function canonicalStageId(stageId) {
  const value = String(stageId || "");
  return value === "scenePlan" ? "scene_plan" : value;
}

function stageStatus(stage) {
  const value = stage?.status;
  return STATUS_LABELS[value] || value || "状态未知";
}

function statusHealth(status, data, editorType) {
  if (status === "处理失败") return "failed";
  if (editorType === "unavailable") return "missing";
  if (!data || typeof data !== "object" || Object.keys(data).length === 0) {
    return status === "制作中" || status === "等待确认" ? "processing" : "missing";
  }
  return "ready";
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== "" && !(Array.isArray(value) && value.length === 0);
}

function dataValue(data, keys) {
  for (const key of keys) {
    const value = key.split(".").reduce((current, part) => current?.[part], data);
    if (hasValue(value)) return value;
  }
  return null;
}

function artifactModel(data, descriptor, stageHealth) {
  const [id, label, keys] = descriptor;
  const payload = dataValue(data, keys);
  return {
    id,
    label,
    summary: payload == null ? "暂未提供" : (typeof payload === "string" ? payload : "已准备，可查看详情"),
    kind: id,
    health: payload == null ? (stageHealth === "failed" ? "failed" : stageHealth === "processing" ? "processing" : "missing") : "ready",
    payload,
  };
}

function reviewFor(project, stageId, status) {
  const pending = project?.pending_review || {};
  const pendingStage = REVIEW_KIND_TO_STAGE[pending.kind] || canonicalStageId(pending.stage || pending.gate);
  const actionable = pendingStage === stageId && status === "等待确认" && Boolean(pending.review_id);
  return {
    actionable,
    reviewId: actionable ? pending.review_id : null,
    subjectHash: actionable ? (pending.subject_hash ?? null) : null,
    subjectVersion: actionable ? (pending.subject_version ?? null) : null,
  };
}

/** Convert the public operator projection into one stable, read-only stage model. */
export function buildApprovalStages(project = {}) {
  const source = new Map((Array.isArray(project.stages) ? project.stages : []).map((stage) => [canonicalStageId(stage.id || stage.name), stage]));
  return APPROVAL_STAGE_ORDER.map((stageId) => {
    const stage = source.get(stageId) || {};
    const data = stage.editor?.data && typeof stage.editor.data === "object" ? stage.editor.data : {};
    const status = stageStatus(stage);
    const health = statusHealth(status, data, stage.editor?.type);
    const descriptors = STAGE_MATERIALS[stageId];
    return {
      stageId,
      stageLabel: STAGE_LABELS[stageLabelKey(stageId)] || stage.label || "制作步骤",
      status,
      version: stage.version ?? stage.editor?.version ?? null,
      summary: stage.summary || (status === "状态未知" ? "该步骤暂无可展示的内容" : `${STAGE_LABELS[stageLabelKey(stageId)] || stage.label || "该步骤"}${status}`),
      artifacts: descriptors.map((descriptor) => artifactModel(data, descriptor, health)),
      review: reviewFor(project, stageId, status),
    };
  });
}

export function buildApprovalViewModel(project = {}) {
  const stages = buildApprovalStages(project);
  const reviewGateId = stages.find((stage) => stage.review.actionable)?.stageId || null;
  return { reviewGateId, stages };
}

export function artifactIdsForStage(stageId) {
  return (STAGE_MATERIALS[canonicalStageId(stageId)] || []).map(([id]) => id);
}

import { STAGE_LABELS, stageLabelKey } from "./language.js";

export const APPROVAL_STAGE_ORDER = [
  "research", "proposal", "script", "scene_plan", "assets", "sample", "edit", "compose", "publish",
];

const STAGE_MATERIALS = {
  research: [
    ["task_understanding", "任务理解", ["task_understanding", "brief", "reference_summary"]],
    ["research_path", "研究步骤", ["substages"]],
    ["research_template", "分析方式", ["template"]],
    ["reference_highlights", "参考片重点", ["reference", "highlights", "breakdown"]],
    ["reference_breakdown", "参考片分镜", ["breakdown"]],
    ["source_inventory", "素材情况", ["sources", "source_inventory", "source_summary"]],
    ["risks", "素材风险", ["risks", "warnings", "quality.warnings"]],
    ["material_matching", "镜头与素材匹配", ["matching"]],
    ["content_directions", "可选方向", ["directions"]],
    ["decision_inbox", "待确认事项", ["decision_inbox"]],
    ["research_quality", "检查结果", ["quality"]],
    ["proposal_handoff", "下一步", ["proposal_handoff"]],
  ],
  proposal: [
    ["selected_direction", "采用方向", ["selected_direction", "concept", "concepts"]],
    ["alternative_directions", "备选方向", ["alternatives", "alternative_directions", "concepts"]],
    ["selling_points", "卖点和差异", ["selling_points", "key_selling_points", "core_message", "concepts"]],
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
    ["narration_subtitles", "口播和字幕", ["narration", "subtitles", "narration_subtitles", "narration_status", "subtitle_status"]],
    ["music_budget", "音乐和费用", ["audio", "music", "budget", "cost", "music_status", "estimated_cost_usd"]],
  ],
  sample: [
    ["sample_video", "样片", ["preview_url", "video_url", "sample_url"]],
    ["shot_comparison", "镜头对照", ["execution_trace", "shots", "shot_comparison"]],
    ["captions_voice", "字幕和口播", ["captions_voice", "narration", "subtitles", "execution_trace.shots"]],
    ["sound", "声音", ["audio_tracks", "sound", "audio"]],
    ["system_checks", "系统检查", ["evaluation", "qa_status", "checks"]],
    ["system_suggestions", "系统建议", ["advisory", "suggestions", "recommendations", "evaluation.advisory"]],
    ["production_basis", "制作依据", ["production_basis", "execution_trace"]],
  ],
  edit: [
    ["edit_result", "剪辑结果", ["preview_url", "edit_result", "video_url"]],
    ["shot_order", "镜头顺序", ["shot_order", "shots", "scenes"]],
    ["audio_captions", "声音和字幕", ["audio", "subtitles", "audio_captions"]],
  ],
  compose: [
    ["final_video", "完整视频", ["preview_url", "download_url", "final_video", "video_url"]],
    ["picture_sound", "画面声音对照", ["picture_sound", "timeline", "audio", "video"]],
    ["quality_conclusion", "质量结论", ["qa_status", "quality_conclusion", "checks"]],
  ],
  publish: [
    ["delivery_video", "交付视频", ["download_url", "delivery_video", "preview_url"]],
    ["file_info", "文件信息", ["format_label", "file_info", "duration_seconds"]],
    ["platforms_download", "平台和下载", ["platforms", "entries", "package_files", "delivery.package_files", "delivery.entries"]],
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
  return STATUS_LABELS[value] || value || "未开始";
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

function compactReference(reference) {
  if (!reference || typeof reference !== "object") return null;
  return {
    title: reference.title,
    summary: reference.summary,
    hook: reference.hook,
    proof_method: reference.proof_method,
    avg_evidence_seconds: reference.avg_evidence_seconds,
    camera_method: reference.camera_method,
    caption_method: reference.caption_method || reference.typography,
    beat_order: reference.beat_order,
    replicate: reference.replicate,
    differentiate: reference.differentiate,
    preview_url: reference.preview_url,
    poster_url: reference.poster_url,
    scenes: Array.isArray(reference.scenes) ? reference.scenes.map((scene, index) => ({
      title: scene?.description || `第 ${index + 1} 段`,
      start_seconds: scene?.start_seconds,
      end_seconds: scene?.end_seconds,
      screen_copy: scene?.screen_copy,
      energy: scene?.energy,
      poster_url: scene?.poster_url,
    })) : [],
  };
}

function compactSubstages(substages) {
  if (!Array.isArray(substages) || !substages.length) return null;
  const fallbackLabels = {
    reference: "参考片怎么拍",
    sources: "我的素材能不能接上",
    matching: "参考镜头和我的素材怎么对应",
    direction: "这条片准备怎么做",
    quality: "还有什么没看清",
  };
  return {
    steps: substages.map((step, index) => ({
      title: step?.label || fallbackLabels[step?.id] || `第 ${index + 1} 步`,
      status: step?.state || step?.status,
      summary: step?.message,
    })),
  };
}

function compactTemplate(template) {
  if (!template || typeof template !== "object") return null;
  return {
    title: template.label || template.name || "本次分析方式",
    status: template.status,
    summary: template.summary || template.description,
  };
}

function compactBreakdown(breakdown) {
  if (!breakdown || typeof breakdown !== "object") return null;
  return {
    identified: breakdown.identified,
    needs_review: breakdown.needs_review,
    missing: breakdown.missing,
    rows: Array.isArray(breakdown.rows) ? breakdown.rows.map((row, index) => ({
      title: row?.visual_content || `第 ${index + 1} 个镜头`,
      time_range: row?.start_seconds != null && row?.end_seconds != null
        ? `${Number(row.start_seconds).toFixed(1)} - ${Number(row.end_seconds).toFixed(1)} 秒` : null,
      shot_size: row?.shot_size,
      camera_angle: row?.camera_angle,
      camera_movement: row?.camera_movement,
      dialogue: row?.dialogue,
      overlay_text: row?.overlay_text,
      effect_treatment: row?.effect_treatment,
      setting: row?.setting,
      audio: Array.isArray(row?.audio_layers) ? row.audio_layers.join("、") : null,
      music: row?.music_profile,
      evidence: row?.evidence_frames?.length ? `${row.evidence_frames.length} 个画面参考` : null,
      note: row?.analyst_note,
    })) : [],
  };
}

function compactSources(data) {
  const sources = Array.isArray(data?.sources) ? data.sources : [];
  return {
    checked_count: data?.source_count,
    usable_count: data?.usable_count,
    items: sources.map((source) => ({
      title: source?.label || "素材",
      media_type: source?.media_type,
      summary: source?.summary,
      reviewed: source?.reviewed ? "已检查" : "待检查",
      usable_for: Array.isArray(source?.usable_for) ? source.usable_for.join("、") : null,
      duration: source?.duration_seconds != null ? `${Number(source.duration_seconds).toFixed(1)} 秒` : null,
      resolution: source?.resolution,
      recommended_range: source?.best_in_seconds != null && source?.best_out_seconds != null
        ? `${Number(source.best_in_seconds).toFixed(1)} - ${Number(source.best_out_seconds).toFixed(1)} 秒` : null,
      risks: Array.isArray(source?.risks) ? source.risks.join("；") : null,
      preview_url: source?.preview_url,
      poster_url: source?.poster_url,
    })),
  };
}

function compactMatching(matching) {
  if (!matching || typeof matching !== "object") return null;
  return {
    rows: Array.isArray(matching.rows) ? matching.rows.map((row, index) => ({
      title: row?.reference_intent || `第 ${index + 1} 个镜头`,
      reason: row?.match_reason,
      recommended_source: row?.source_label || row?.source_media_id,
      status: row?.status,
      gap: row?.gap,
    })) : [],
  };
}

function compactDirections(directions) {
  if (!Array.isArray(directions)) return null;
  return directions.map((direction, index) => ({
    title: direction?.title || `方向 ${index + 1}`,
    promise: direction?.promise,
    keep: Array.isArray(direction?.keep) ? direction.keep.join("、") : null,
    change: Array.isArray(direction?.change) ? direction.change.join("、") : null,
    avoid: Array.isArray(direction?.avoid) ? direction.avoid.join("、") : null,
  }));
}

function compactQuality(quality) {
  if (!quality || typeof quality !== "object") return null;
  return {
    status: quality.status,
    score: quality.score != null && quality.max_score != null ? `${quality.score}/${quality.max_score}` : null,
    checks: Array.isArray(quality.checks) ? quality.checks.map((check) => ({
      title: check?.label || "检查项",
      status: check?.status,
      result: check?.message,
    })) : [],
  };
}

function compactDecisionInbox(decisions) {
  if (!Array.isArray(decisions)) return null;
  return decisions.map((decision, index) => ({
    title: decision?.title || `待确认事项 ${index + 1}`,
    summary: decision?.message,
    impact: decision?.impact,
  }));
}

function compactHandoff(handoff) {
  if (!handoff || typeof handoff !== "object") return null;
  return {
    status: handoff.state,
    summary: handoff.message,
  };
}

function payloadForArtifact(data, descriptor) {
  const [id, , keys] = descriptor;
  if (id === "research_path") return compactSubstages(data.substages);
  if (id === "research_template") return compactTemplate(data.template);
  if (id === "reference_highlights") return compactReference(data.reference) || dataValue(data, keys);
  if (id === "reference_breakdown") return compactBreakdown(data.breakdown);
  if (id === "source_inventory") return compactSources(data);
  if (id === "risks") return Array.isArray(data.risks) ? data.risks : dataValue(data, keys);
  if (id === "material_matching") return compactMatching(data.matching);
  if (id === "content_directions") return compactDirections(data.directions);
  if (id === "decision_inbox") return compactDecisionInbox(data.decision_inbox);
  if (id === "research_quality") return compactQuality(data.quality);
  if (id === "proposal_handoff") return compactHandoff(data.proposal_handoff);
  if (id === "selected_direction" || id === "alternative_directions" || id === "selling_points") {
    const concepts = Array.isArray(data.concepts) ? data.concepts : [];
    const selectedId = data.selected_id;
    const selected = concepts.find((concept) => concept?.id === selectedId) || concepts[0];
    if (id === "selected_direction") return selected || null;
    if (id === "alternative_directions") return concepts.filter((concept) => concept?.id !== selectedId);
    return selected?.key_points || selected?.selling_points || selected?.core_message || null;
  }
  if (["narration", "on_screen_text"].includes(id) && Array.isArray(data.sections)) {
    const field = id === "narration" ? "text" : "screen_copy";
    return data.sections.map((section) => ({
      id: section?.id,
      label: section?.label,
      text: section?.[field],
      start_seconds: section?.start_seconds,
      end_seconds: section?.end_seconds,
    })).filter((section) => hasValue(section.text));
  }
  if (id === "duration_check" && hasValue(data.duration_seconds)) {
    return { duration_seconds: data.duration_seconds, status: data.status || "已检查" };
  }
  if (id === "source_mapping" && Array.isArray(data.shots)) {
    return data.shots.map((shot) => ({
      id: shot?.id || shot?.shot_id,
      title: shot?.title || shot?.purpose,
      source_label: shot?.source_label || shot?.source?.label,
      source_media_id: shot?.source_media_id || shot?.source?.id,
    })).filter((shot) => hasValue(shot.title) || hasValue(shot.source_label) || hasValue(shot.source_media_id));
  }
  if (id === "action_timing" && Array.isArray(data.shots)) {
    return data.shots.map((shot) => ({
      id: shot?.id || shot?.shot_id,
      start_seconds: shot?.start_seconds ?? shot?.source_in_seconds,
      end_seconds: shot?.end_seconds ?? shot?.source_out_seconds,
      duration_seconds: shot?.duration_seconds,
    }));
  }
  if (id === "visual_assets" && Array.isArray(data.items)) {
    return data.items.filter((item) => !["narration", "subtitle", "music", "audio"].includes(String(item?.kind || item?.type || "").toLowerCase()));
  }
  if (id === "captions_voice" && Array.isArray(data.execution_trace?.shots)) {
    return data.execution_trace.shots.map((shot) => ({
      id: shot?.shot_id,
      narration: shot?.planned?.narration || shot?.actual?.narration,
      caption: shot?.planned?.screen_copy || shot?.actual?.screen_copy,
    })).filter((shot) => hasValue(shot.narration) || hasValue(shot.caption));
  }
  if (id === "shot_comparison" && Array.isArray(data.execution_trace?.shots)) {
    return data.execution_trace.shots.map((shot) => ({
      id: shot?.shot_id,
      purpose: shot?.planned?.purpose,
      plan: shot?.planned?.subject_action || shot?.planned?.screen_copy,
      actual: shot?.actual?.source_label || shot?.actual?.screen_copy,
      difference: shot?.deviation?.reason,
    }));
  }
  return dataValue(data, keys);
}

function artifactModel(data, descriptor, stageHealth) {
  const [id, label, keys] = descriptor;
  const rawPayload = payloadForArtifact(data, descriptor);
  const payload = Array.isArray(rawPayload) && rawPayload.length === 0 ? null : rawPayload;
  const summary = payload == null
    ? "暂未提供"
    : typeof payload === "string"
      ? (/^(https?:|\/)/.test(payload) ? "已准备，可查看预览" : payload.slice(0, 120))
      : Array.isArray(payload)
        ? `${payload.length} 项，可查看详情`
        : Array.isArray(payload?.steps)
          ? `${payload.steps.length} 个步骤，可查看详情`
          : Array.isArray(payload?.items)
            ? `${payload.items.length} 条素材，可查看详情`
            : Array.isArray(payload?.rows)
              ? `${payload.rows.length} 个镜头，可查看详情`
        : "已准备，可查看详情";
  return {
    id,
    label,
    summary,
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
    reviewId: pendingStage === stageId ? (pending.review_id ?? null) : null,
    subjectHash: pendingStage === stageId ? (pending.subject_hash ?? null) : null,
    subjectVersion: pendingStage === stageId ? (pending.subject_version ?? null) : null,
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
      summary: stage.summary || (health === "missing" ? "该步骤暂未生成材料" : `${STAGE_LABELS[stageLabelKey(stageId)] || stage.label || "该步骤"}${status}`),
      artifacts: descriptors.map((descriptor) => artifactModel(data, descriptor, health)),
      review: reviewFor(project, stageId, status),
    };
  });
}

export function buildApprovalViewModel(project = {}) {
  const stages = buildApprovalStages(project);
  const pending = project?.pending_review || {};
  const pendingStage = REVIEW_KIND_TO_STAGE[pending.kind] || canonicalStageId(pending.stage || pending.gate);
  const reviewGateId = (pendingStage && stages.some((stage) => stage.stageId === pendingStage))
    ? pendingStage
    : stages.find((stage) => stage.review.actionable)?.stageId
      || stages.find((stage) => stage.status === "等待确认")?.stageId
      || null;
  return { reviewGateId, stages };
}

export function artifactIdsForStage(stageId) {
  return (STAGE_MATERIALS[canonicalStageId(stageId)] || []).map(([id]) => id);
}

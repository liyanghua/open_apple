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
    ["source_risks", "素材风险", ["risks", "warnings", "quality.warnings"]],
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
    ["control_plan", "导演总控单", ["control_plan"]],
    ["production_budget", "预计成本", ["estimated_cost_usd"]],
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
    ["generation_tasks", "生成任务", ["execution_plan.shots", "generation_tasks"]],
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
    ["compose_readiness", "成片检查就绪", ["compose_readiness"]],
  ],
  compose: [
    ["final_video", "完整视频", ["preview_url", "download_url", "final_video", "video_url"]],
    ["picture_sound", "画面声音对照", ["picture_sound", "timeline", "audio", "video"]],
    ["quality_conclusion", "质量结论", ["qa_status", "quality_conclusion", "checks"]],
    ["version_history", "版本变化", ["versions"]],
    ["pending_changes", "待处理问题", ["pending_changes"]],
  ],
  publish: [
    ["delivery_video", "交付视频", ["download_url", "delivery_video", "preview_url"]],
    ["file_info", "文件信息", ["format_label", "file_info", "duration_seconds"]],
    ["platforms_download", "平台和下载", ["platforms", "entries", "package_files", "delivery.package_files", "delivery.entries"]],
    ["delivery_package", "交付文件", ["delivery.package_files", "delivery"]],
    ["qa_evidence", "QA 证据", ["delivery.qa_evidence", "qa_evidence"]],
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

function compactConcept(concept) {
  if (!concept || typeof concept !== "object") return null;
  return {
    title: concept.title,
    hook: concept.hook,
    core_message: concept.core_message,
    target_audience: concept.target_audience,
    tone: concept.tone,
    visual_approach: concept.visual_approach,
    why_effective: concept.why_this_works,
    key_points: Array.isArray(concept.key_points) ? concept.key_points : [],
    cta: concept.cta,
    duration_seconds: concept.duration_seconds,
    target_platform: concept.target_platform,
  };
}

function compactControlPlan(controlPlan) {
  if (!controlPlan || typeof controlPlan !== "object" || !Array.isArray(controlPlan.sections)) return null;
  // plan_id / plan_version / evidence_refs 等工程字段进入制作记录，不进主 payload。
  return {
    sections: controlPlan.sections.map((section) => ({
      label: section?.label,
      summary: section?.summary,
      rules: Array.isArray(section?.rules) ? section.rules : [],
      review: section?.review,
      feedback: section?.feedback,
    })),
  };
}

function scriptSectionPart(sections, index) {
  if (sections.length === 1) return "正文";
  if (index === 0) return "开场";
  if (index === sections.length - 1) return "结尾";
  return "正文";
}

function compactScriptSections(sections) {
  if (!Array.isArray(sections) || !sections.length) return null;
  // 口播与屏幕文字的完整正文唯一主材料；control_rule_refs/review/feedback 等工程字段排除。
  return {
    sections: sections.map((section, index) => ({
      part: scriptSectionPart(sections, index),
      label: section?.label,
      narration: section?.text,
      screen_copy: section?.screen_copy,
      section_goal: section?.section_goal,
      visual_intent: section?.visual_intent,
      pacing: section?.pacing,
      evidence_requirements: Array.isArray(section?.evidence_requirements) ? section.evidence_requirements : [],
      start_seconds: section?.start_seconds,
      end_seconds: section?.end_seconds,
    })),
  };
}

function compactScriptEntry(data, field) {
  // narration / on_screen_text：只保留数量摘要和定位入口，不重复完整正文。
  const sections = Array.isArray(data?.sections) ? data.sections : [];
  const count = sections.filter((section) => hasValue(section?.[field])).length;
  if (!count) return null;
  return {
    section_count: count,
    total_seconds: data.duration_seconds,
    source: "production_script",
  };
}

function shotEvidence(shot) {
  const parts = [shot?.source_summary, Array.isArray(shot?.source_usable_for) && shot.source_usable_for.length ? shot.source_usable_for.join("、") : null];
  return parts.filter(hasValue).join("；") || null;
}

function compactScenePlan(data) {
  const shots = Array.isArray(data.shots) ? data.shots : [];
  if (!shots.length) return null;
  return {
    duration_seconds: data.duration_seconds,
    reference_basis: data.reference_basis && typeof data.reference_basis === "object" ? {
      summary: data.reference_basis.summary,
      beat_order: data.reference_basis.beat_order,
      proof_method: data.reference_basis.proof_method,
      avg_evidence_seconds: data.reference_basis.avg_evidence_seconds,
    } : null,
    shots: shots.map((shot) => ({
      id: shot?.id,
      title: shot?.beat,
      purpose: shot?.intent,
      screen_copy: shot?.screen_copy,
      framing: shot?.framing,
      movement: shot?.movement,
      narrative_role: shot?.narrative_role,
      source_label: shot?.source_label,
      source_in_seconds: shot?.source_in_seconds,
      source_out_seconds: shot?.source_out_seconds,
      timeline_in_seconds: shot?.timeline_in_seconds,
      timeline_out_seconds: shot?.timeline_out_seconds,
      evidence: shotEvidence(shot),
      mapping_reason: shot?.mapping_reason,
      reference_evidence: shot?.reference_evidence && typeof shot.reference_evidence === "object" ? {
        mode: shot.reference_evidence.mode,
        mechanism: shot.reference_evidence.mechanism,
        rationale: shot.reference_evidence.rationale,
      } : null,
      preview_url: shot?.preview_url,
      poster_url: shot?.poster_url,
    })),
  };
}

function compactSourceMapping(data) {
  const shots = Array.isArray(data.shots) ? data.shots : [];
  const rows = shots.map((shot) => ({
    id: shot?.id,
    title: shot?.beat,
    source_label: shot?.source_label,
    evidence: shotEvidence(shot),
    mapping_reason: shot?.mapping_reason,
  })).filter((row) => hasValue(row.source_label) || hasValue(row.mapping_reason));
  return rows.length ? { rows } : null;
}

function compactActionTiming(data) {
  const shots = Array.isArray(data.shots) ? data.shots : [];
  // 只允许成片时间轴语义（timeline_in/out 或投影中同为时间轴语义的 in/out），禁止回退到源素材区间。
  const rows = shots.map((shot) => ({
    id: shot?.id,
    timeline_in_seconds: shot?.timeline_in_seconds ?? shot?.in_seconds,
    timeline_out_seconds: shot?.timeline_out_seconds ?? shot?.out_seconds,
  })).filter((row) => row.timeline_in_seconds != null && row.timeline_out_seconds != null);
  return rows.length ? { rows } : null;
}

function compactGenerationList(data) {
  const items = Array.isArray(data.items) ? data.items.map((item) => ({
    label: item?.label,
    type: item?.type,
    stage_label: item?.stage_label,
    status: item?.status,
    reason: item?.reason,
    paid: Boolean(item?.paid),
    cost_estimate_usd: item?.cost_estimate_usd,
    source_summary: item?.source_summary,
    source_range: item?.source_range,
  })) : [];
  return {
    planned_count: data.planned_count,
    prepared_count: data.prepared_count,
    waiting_confirmation_count: data.waiting_confirmation_count,
    paid_generation_approved: Boolean(data.paid_generation_approved),
    items,
  };
}

function compactVisualAssets(data) {
  const items = (Array.isArray(data.items) ? data.items : []).filter((item) => {
    const kind = String(item?.type || item?.kind || "").toLowerCase();
    return !["narration", "subtitle", "subtitles", "music", "audio"].includes(kind);
  }).map((item) => ({
    label: item?.label,
    type: item?.type,
    status: item?.status,
    reason: item?.reason,
    source_summary: item?.source_summary,
    source_range: item?.source_range,
  }));
  return items.length ? { items } : null;
}

function compactGenerationTasks(data) {
  const execution = data?.execution_plan;
  if (!execution || typeof execution !== "object") return null;
  const shots = Array.isArray(execution.shots) ? execution.shots : [];
  const tasks = shots.flatMap((shot) => (Array.isArray(shot?.generation_proposals) ? shot.generation_proposals : [])
    .map((proposal) => ({
      shot_id: shot?.id,
      shot_purpose: shot?.purpose,
      operation: proposal?.operation,
      duration_seconds: proposal?.duration_seconds,
      aspect_ratio: proposal?.aspect_ratio,
      estimated_fast_cost_usd: proposal?.estimated_fast_cost_usd,
      estimated_standard_cost_usd: proposal?.estimated_standard_cost_usd,
      evidence_risk: proposal?.evidence_risk,
      selected: proposal?.id != null && shot?.selected_generation_task_id === proposal.id,
    })));
  if (!tasks.length) return null;
  return { status: execution.status, tasks };
}

function compactNarrationSubtitles(data) {
  const execution = data?.execution_plan;
  const shots = Array.isArray(execution?.shots) ? execution.shots : [];
  // 逐镜口播/字幕只呈现覆盖情况，不重复完整正文。
  return {
    narration_status: data.narration_status,
    subtitle_status: data.subtitle_status,
    coverage: shots.map((shot) => ({
      id: shot?.id,
      narration_ready: hasValue(shot?.narration),
      subtitle_ready: hasValue(shot?.screen_copy),
    })),
  };
}

function compactMusicBudget(data) {
  if (!hasValue(data.music_status) && !hasValue(data.estimated_cost_usd)) return null;
  return { music_status: data.music_status, estimated_cost_usd: data.estimated_cost_usd };
}

function compactSampleVideo(data) {
  if (!hasValue(data.preview_url)) return null;
  return {
    preview_url: data.preview_url,
    duration_seconds: data.duration_seconds,
    qa_status: data.qa_status,
  };
}

function compactShotComparison(data) {
  const shots = Array.isArray(data.execution_trace?.shots) ? data.execution_trace.shots : [];
  const rows = shots.map((shot) => ({
    id: shot?.shot_id,
    status: shot?.status_label || shot?.status,
    purpose: shot?.planned?.purpose,
    plan_screen_copy: shot?.planned?.screen_copy,
    actual_screen_copy: shot?.actual?.screen_copy,
    actual_source_label: shot?.actual?.source_label,
    difference: shot?.deviation?.reason,
  }));
  return rows.length ? { rows } : null;
}

function compactCaptionsVoice(data) {
  const shots = Array.isArray(data.execution_trace?.shots) ? data.execution_trace.shots : [];
  const rows = shots.map((shot) => ({
    id: shot?.shot_id,
    narration: shot?.actual?.narration || shot?.planned?.narration,
    caption: shot?.actual?.screen_copy || shot?.planned?.screen_copy,
  })).filter((row) => hasValue(row.narration) || hasValue(row.caption));
  if (!rows.length && !data.caption_diff && !data.creative_rule_diff) return null;
  return {
    shots: rows,
    caption_diff: data.caption_diff,
    creative_rule_diff: data.creative_rule_diff,
  };
}

function compactSound(data) {
  const tracks = Array.isArray(data.audio_tracks) ? data.audio_tracks : [];
  return tracks.length ? { tracks } : null;
}

function compactSystemChecks(data) {
  const evaluation = data?.evaluation;
  if (!evaluation || typeof evaluation !== "object") return null;
  return {
    status: evaluation.status,
    recommended_action: evaluation.recommended_action,
    hard_gate_fails: Array.isArray(evaluation.hard_gate_fails) ? evaluation.hard_gate_fails : [],
  };
}

function compactSystemSuggestions(data) {
  const advisory = data?.evaluation?.advisory;
  if (!advisory || typeof advisory !== "object") return null;
  return {
    scored: Boolean(advisory.scored),
    summary: advisory.summary,
    dimensions: Array.isArray(advisory.dimensions) ? advisory.dimensions : [],
  };
}

function compactProductionBasis(data) {
  const trace = data?.execution_trace;
  if (!trace || typeof trace !== "object") return null;
  return {
    summary: trace.summary,
    reference_rules: (Array.isArray(trace.shots) ? trace.shots : []).map((shot) => ({
      id: shot?.shot_id,
      rules: Array.isArray(shot?.planned?.reference_rules) ? shot.planned.reference_rules : [],
    })).filter((row) => row.rules.length),
  };
}

function compactEditResult(data) {
  return {
    change_scope: data.change_scope,
    reasons: Array.isArray(data.reasons) ? data.reasons : [],
    affected_shot_count: data.affected_shot_count,
    preview_url: data.preview_url,
    preview_duration_seconds: data.preview_duration_seconds,
  };
}

function compactShotOrder(data) {
  const shots = Array.isArray(data.shots) ? data.shots.map((shot) => ({
    id: shot?.id,
    title: shot?.title,
    source_label: shot?.source_label,
    source_in_seconds: shot?.source_in_seconds,
    source_out_seconds: shot?.source_out_seconds,
    duration_seconds: shot?.duration_seconds,
    enabled: shot?.enabled,
    caption: shot?.caption,
    narration: shot?.narration,
    preview_url: shot?.preview_url,
    poster_url: shot?.poster_url,
  })) : [];
  return shots.length ? { shots } : null;
}

function compactAudioCaptions(data) {
  const audio = data?.audio;
  if (!audio || typeof audio !== "object") return null;
  return {
    music_volume: audio.music_volume,
    sfx_volume: audio.sfx_volume,
    narration_enabled: audio.narration_enabled,
  };
}

function compactComposeReadiness(data, status) {
  const ready = status === "已完成";
  return {
    ready,
    summary: ready
      ? "精剪已完成，可以进入成片检查"
      : status === "制作中" || status === "等待确认"
        ? "精剪尚未完成，暂不能进入成片检查"
        : status === "处理失败"
          ? "精剪处理失败，需先处理失败原因"
          : "尚未开始精剪",
    change_scope: data.change_scope,
    affected_shot_count: data.affected_shot_count,
    reasons: Array.isArray(data.reasons) ? data.reasons : [],
  };
}

function compactFinalVideo(data) {
  const videoUrl = data?.player?.video_url || data?.video_url || data?.download_url;
  if (!hasValue(videoUrl)) return null;
  return {
    video_url: videoUrl,
    poster_url: data?.player?.poster_url || data?.poster_url,
    duration_seconds: data?.duration_seconds,
    qa_status: data?.qa_status,
    download_url: data?.download_url,
  };
}

function compactPictureSound(data) {
  const timeline = data?.timeline;
  if (!timeline || typeof timeline !== "object" || !Array.isArray(timeline.tracks)) return null;
  return {
    duration_seconds: timeline.duration_seconds,
    tracks: timeline.tracks.map((track) => ({
      kind: track?.kind,
      label: track?.label,
      segments: (Array.isArray(track?.segments) ? track.segments : []).map((segment) => ({
        id: segment?.id,
        label: segment?.label,
        start_seconds: segment?.start_seconds,
        end_seconds: segment?.end_seconds,
        preview_url: segment?.preview_url,
      })),
    })),
  };
}

function compactQualityConclusion(data) {
  const evaluation = data?.evaluation;
  return {
    qa_status: data.qa_status,
    evaluation: evaluation && typeof evaluation === "object" ? {
      status: evaluation.status,
      recommended_action: evaluation.recommended_action,
      hard_gate_fails: Array.isArray(evaluation.hard_gate_fails) ? evaluation.hard_gate_fails : [],
      advisory: evaluation.advisory && typeof evaluation.advisory === "object" ? {
        scored: Boolean(evaluation.advisory.scored),
        summary: evaluation.advisory.summary,
        dimensions: Array.isArray(evaluation.advisory.dimensions) ? evaluation.advisory.dimensions : [],
      } : null,
    } : null,
  };
}

function compactVersionHistory(data) {
  const versions = Array.isArray(data.versions) ? data.versions.map((version) => ({
    id: version?.id,
    label: version?.label,
    active: Boolean(version?.active),
    qa_status: version?.qa_status,
    video_url: version?.video_url,
    poster_url: version?.poster_url,
    change_summary: version?.change_summary,
  })) : [];
  return versions.length ? { versions } : null;
}

function compactPendingChanges(data) {
  const changes = Array.isArray(data.pending_changes) ? data.pending_changes : [];
  return changes.length ? { changes } : null;
}

function compactFileInfo(data) {
  if (!hasValue(data.format_label) && !hasValue(data.duration_seconds)) return null;
  return { format_label: data.format_label, duration_seconds: data.duration_seconds };
}

function compactPlatforms(data) {
  const entries = Array.isArray(data?.delivery?.entries) ? data.delivery.entries.map((entry) => ({
    platform: entry?.platform,
    platform_label: entry?.platform_label,
    status: entry?.status,
    status_label: entry?.status_label,
    title: entry?.title,
    description: entry?.description,
    hashtags: Array.isArray(entry?.hashtags) ? entry.hashtags : [],
    timestamp: entry?.timestamp,
    export_path: entry?.export_path,
  })) : [];
  return entries.length ? { entries } : null;
}

function compactDeliveryPackage(data) {
  const delivery = data?.delivery;
  if (!delivery || typeof delivery !== "object") return null;
  const files = Array.isArray(delivery.package_files) ? delivery.package_files.map((file) => ({
    relative_path: file?.relative_path,
    label: file?.label,
    kind: file?.kind,
    download_url: file?.download_url,
  })) : [];
  if (!files.length && !hasValue(delivery.notes) && !hasValue(delivery.package_path)) return null;
  return { package_path: delivery.package_path, notes: delivery.notes, files };
}

function compactQaEvidence(data) {
  const evidence = Array.isArray(data?.delivery?.qa_evidence) ? data.delivery.qa_evidence : [];
  return evidence.length ? { files: evidence } : null;
}

function payloadForArtifact(data, descriptor, status) {
  const [id, , keys] = descriptor;
  if (id === "research_path") return compactSubstages(data.substages);
  if (id === "research_template") return compactTemplate(data.template);
  if (id === "reference_highlights") return compactReference(data.reference) || dataValue(data, keys);
  if (id === "reference_breakdown") return compactBreakdown(data.breakdown);
  if (id === "source_inventory") return compactSources(data);
  if (id === "source_risks") return Array.isArray(data.risks) ? data.risks : dataValue(data, keys);
  if (id === "material_matching") return compactMatching(data.matching);
  if (id === "content_directions") return compactDirections(data.directions);
  if (id === "decision_inbox") return compactDecisionInbox(data.decision_inbox);
  if (id === "research_quality") return compactQuality(data.quality);
  if (id === "proposal_handoff") return compactHandoff(data.proposal_handoff);
  if (id === "selected_direction" || id === "alternative_directions" || id === "selling_points") {
    const concepts = Array.isArray(data.concepts) ? data.concepts : [];
    const selectedId = data.selected_id;
    const selected = concepts.find((concept) => concept?.id === selectedId) || concepts[0];
    if (id === "selected_direction") return compactConcept(selected);
    if (id === "alternative_directions") {
      const alternatives = concepts.filter((concept) => concept?.id !== selectedId).map(compactConcept);
      return alternatives.length ? alternatives : null;
    }
    return selected?.key_points || selected?.core_message || null;
  }
  if (id === "control_plan") return compactControlPlan(data.control_plan);
  if (id === "production_budget") return hasValue(data.estimated_cost_usd) ? { estimated_cost_usd: data.estimated_cost_usd } : null;
  if (id === "production_script") return compactScriptSections(data.sections);
  if (["narration", "on_screen_text"].includes(id)) {
    const field = id === "narration" ? "text" : "screen_copy";
    return compactScriptEntry(data, field);
  }
  if (id === "duration_check" && hasValue(data.duration_seconds)) {
    return { duration_seconds: data.duration_seconds, status: data.status || "已检查" };
  }
  if (id === "shot_plan") return compactScenePlan(data);
  if (id === "source_mapping") return compactSourceMapping(data);
  if (id === "action_timing") return compactActionTiming(data);
  if (id === "generation_list") return compactGenerationList(data);
  if (id === "visual_assets") return compactVisualAssets(data);
  if (id === "generation_tasks") return compactGenerationTasks(data);
  if (id === "narration_subtitles") return compactNarrationSubtitles(data);
  if (id === "music_budget") return compactMusicBudget(data);
  if (id === "sample_video") return compactSampleVideo(data);
  if (id === "shot_comparison") return compactShotComparison(data);
  if (id === "captions_voice") return compactCaptionsVoice(data);
  if (id === "sound") return compactSound(data);
  if (id === "system_checks") return compactSystemChecks(data);
  if (id === "system_suggestions") return compactSystemSuggestions(data);
  if (id === "production_basis") return compactProductionBasis(data);
  if (id === "edit_result") return compactEditResult(data);
  if (id === "shot_order") return compactShotOrder(data);
  if (id === "audio_captions") return compactAudioCaptions(data);
  if (id === "compose_readiness") return compactComposeReadiness(data, status);
  if (id === "final_video" || id === "delivery_video") return compactFinalVideo(data);
  if (id === "picture_sound") return compactPictureSound(data);
  if (id === "quality_conclusion") return compactQualityConclusion(data);
  if (id === "version_history") return compactVersionHistory(data);
  if (id === "pending_changes") return compactPendingChanges(data);
  if (id === "file_info") return compactFileInfo(data);
  if (id === "platforms_download") return compactPlatforms(data);
  if (id === "delivery_package") return compactDeliveryPackage(data);
  if (id === "qa_evidence") return compactQaEvidence(data);
  return dataValue(data, keys);
}

function artifactModel(data, descriptor, stageHealth, stageStatus) {
  const [id, label, keys] = descriptor;
  const rawPayload = payloadForArtifact(data, descriptor, stageStatus);
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
              : Array.isArray(payload?.shots)
                ? `${payload.shots.length} 个镜头，可查看详情`
                : Array.isArray(payload?.sections)
                  ? `${payload.sections.length} 段，可查看详情`
                  : payload?.section_count != null
                    ? `${payload.section_count} 段${payload.total_seconds != null ? `，共 ${payload.total_seconds} 秒` : ""}`
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
      artifacts: descriptors.map((descriptor) => artifactModel(data, descriptor, health, status)),
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

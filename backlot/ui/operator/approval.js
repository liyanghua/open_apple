// 单条审批工作台：只读展示候选事实、五项确认与通过/退回主动作。
// 制作进度统一由九步 rail 展示，审批动作只绑定当前确认门。
// 业务含义仍是“需要人工确认”，界面改用更直接的“需要你确认”。
// 不含编辑器、草稿、版本历史或影响计算；技术字段只进入“查看制作记录”折叠区。
// 数据全部来自现有 operator-state 投影与 review API
// （script_editor / asset_review / sample_review / delivery_review 均为只读事实）。
import { decideReview } from "./api.js";
import { parseBatchContext } from "./store.js";
import {
  STAGE_LABELS,
  stageLabelKey,
  GATE_STAGE_IDS,
  GATE_LABELS,
  GATE_DETAILS,
  CONFIRMATION_ITEMS,
  CONFIRMATION_VALUE_LABELS,
  APPROVAL_COPY,
} from "./language.js";
import { buildApprovalViewModel } from "./approval_model.js";

const byId = (id) => document.getElementById(id);

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = String(text);
  return element;
}

function detailRow(label, value) {
  const row = node("div", "approval-detail-row");
  row.append(node("span", "approval-detail-label", label), node("strong", "approval-detail-value", value || "暂未提供"));
  return row;
}

function setTestId(element, testId) {
  if (testId) element.dataset.testid = testId;
  return element;
}

export function hasReviewPermission(project) {
  return (project?.permissions || []).includes("review");
}

const KIND_TO_STAGE = { script_lock: "script", creative_lock: "assets", sample: "sample" };
const GATE_TO_INDEX = { script: 1, assets: 2, sample: 3 };

function canonicalStageId(stageId) {
  return String(stageId || "") === "scenePlan" ? "scene_plan" : String(stageId || "");
}

export function isApprovalShellActive(project, snapshot) {
  if (!project) return false;
  // 批级驾驶舱保留原壳（横向比较 + 统一提交入口）。
  if (project.workspace?.editor?.type === "batch_review") return false;
  const hasPending = Boolean(project.pending_review?.review_id);
  const navigation = snapshot.navigation || parseBatchContext();
  // 三种合法入口：审批只读模式 / 存在待确认内容 / 带批次导航上下文。
  if (project.workspace?.view_mode === "approval" || hasPending || navigation) return true;
  // 直接访问的单条项目同样进入审批壳（只读展示，无批次上下文即无返回批量入口）。
  return true;
}

function stageById(project, stageId) {
  const expected = canonicalStageId(stageId);
  return (project.stages || []).find((stage) => canonicalStageId(stage.id || stage.name) === expected) || null;
}

function editorDataFor(project, stageId) {
  const editor = stageById(project, stageId)?.editor;
  return editor?.data || {};
}

function currentGateId(project) {
  const pending = project.pending_review;
  if (pending?.kind && KIND_TO_STAGE[pending.kind]) return KIND_TO_STAGE[pending.kind];
  const stages = project.stages || [];
  const failing = stages.find((stage) => stage.status === "处理失败");
  if (failing) return canonicalStageId(failing.id || failing.name);
  const awaiting = stages.find((stage) => stage.status === "等待确认");
  if (awaiting) return canonicalStageId(awaiting.id || awaiting.name);
  const upcoming = stages.find((stage) => stage.status !== "已完成" && stage.status !== "未开始");
  if (upcoming) return canonicalStageId(upcoming.id || upcoming.name);
  const pendingStep = stages.find((stage) => stage.status === "未开始");
  if (pendingStep) return canonicalStageId(pendingStep.id || pendingStep.name);
  return "done";
}

function currentGateDetail(project) {
  const rawId = currentGateId(project);
  const gateId = (rawId === "compose" || rawId === "publish") ? "done" : rawId;
  const pending = project.pending_review;
  const detail = GATE_DETAILS[gateId] || GATE_DETAILS.done;
  return {
    gateId,
    detail,
    label: gateId === "done" ? "查看成片" : (GATE_LABELS[gateId] || "制作步骤"),
    version: pending?.subject_version || stageById(project, rawId)?.version || 1,
    hasPending: Boolean(pending),
  };
}

// ---------------------------------------------------------------------------
// 顶部上下文 + 轻量九步进度
// ---------------------------------------------------------------------------

function renderTopbar(project, snapshot, model) {
  const selected = model.stages.find((stage) => stage.stageId === model.selectedStageId) || model.stages[0];
  const title = byId("approval-title");
  if (title) title.textContent = project.title || "未命名项目";
  const kicker = byId("approval-hero-kicker");
  if (kicker) {
    kicker.textContent = model.reviewGateId && model.selectedStageId === model.reviewGateId
      ? APPROVAL_COPY.heroKicker : `正在查看：${selected?.stageLabel || "制作步骤"}`;
  }
  const state = byId("approval-meta-state");
  if (state) {
    const pending = project.pending_review;
    const isCurrent = Boolean(model.reviewGateId && model.selectedStageId === model.reviewGateId);
    state.textContent = pending && isCurrent
      ? APPROVAL_COPY.stateAwaiting
      : project.summary?.progress_percent === 100 ? APPROVAL_COPY.stateDone : "制作中";
    state.classList.toggle("is-waiting", pending && isCurrent);
  }
  const note = byId("approval-note");
  if (note) {
    const pending = project.pending_review;
    note.textContent = pending && model.selectedStageId === model.reviewGateId
      ? (pending.summary || "内容已准备完成，等待人工确认")
      : (selected?.summary || project.summary?.current_task || "项目正在按计划推进");
  }
  const returnLink = byId("approval-return-batch");
  if (returnLink) {
    const navigation = snapshot.navigation;
    returnLink.hidden = !navigation;
    if (navigation) {
      returnLink.href = navigation.returnUrl;
      returnLink.onclick = () => {
        try { sessionStorage.setItem(`batch-scroll:${navigation.batchId}`, String(navigation.scrollTop || 0)); } catch { /* no-op */ }
      };
    }
  }
  const diagnosticLink = byId("approval-diagnostic-link");
  if (diagnosticLink) {
    diagnosticLink.href = `/diagnostics/p/${encodeURIComponent(project.project_id || "")}`;
    // 技术诊断不占用审批首屏；异常说明会在“查看制作记录”里保留。
    diagnosticLink.hidden = true;
  }
}

function renderRail(project, model) {
  const rail = byId("approval-rail");
  if (!rail) return;
  rail.replaceChildren();
  const stages = model.stages || [];
  const gateCount = stages.filter((stage) => GATE_STAGE_IDS.includes(stage.stageId)).length;
  const railTitle = byId("approval-rail-title");
  if (railTitle) railTitle.textContent = `${APPROVAL_COPY.railTitle} · 共 ${stages.length || 9} 步`;
  const railHint = byId("approval-rail-hint");
  if (railHint) railHint.textContent = `${gateCount} 步需要你确认 · 其余自动完成`;
  const activeGateId = model.reviewGateId;
  stages.forEach((stage) => {
    const isGate = GATE_STAGE_IDS.includes(stage.stageId);
    const isCurrent = stage.stageId === activeGateId;
    const isDone = stage.status === "已完成";
    const cls = ["approval-step"];
    if (isGate) cls.push("is-gate");
    if (isDone) cls.push("is-done");
    if (isCurrent) cls.push("is-current");
    if (stage.status === "处理失败") cls.push("is-failed");
    if (stage.stageId === model.selectedStageId) cls.push("is-selected");
    const card = node("button", cls.join(" "));
    card.type = "button";
    card.setAttribute("aria-label", `${stage.stageLabel}，${stage.status || "状态未知"}`);
    card.setAttribute("aria-current", stage.stageId === model.selectedStageId ? "step" : "false");
    card.dataset.stageId = stage.stageId;
    card.dataset.testid = `approval-stage-${stage.stageId}`;
    const role = node("span", "approval-step-role", isGate ? `第 ${GATE_TO_INDEX[stage.stageId] || 1} 次确认` : "自动完成");
    const name = node("b", "", stage.stageLabel || stage.label || STAGE_LABELS[stageLabelKey(stage.stageId)] || "制作步骤");
    const stateText = stage.status === "等待确认" && isCurrent ? "现在需要你确认" : stage.status;
    card.append(role, name, node("small", "", stateText));
    card.addEventListener("click", () => {
      document.dispatchEvent(new CustomEvent("approval-select-stage", { detail: { stageId: stage.stageId } }));
    });
    rail.append(card);
  });
  const flownote = byId("approval-flownote");
  if (flownote) {
    const pending = project.pending_review;
    const next = kindToFlownote(pending?.kind);
    const selected = model.stages.find((item) => item.stageId === model.selectedStageId);
    flownote.textContent = model.selectedStageId === model.reviewGateId && next
      ? next : `${selected?.stageLabel || "当前阶段"}：${selected?.summary || "可查看该阶段材料"}`;
  }
}

function kindToFlownote(kind) {
  if (kind === "sample") return "你现在要做：查看样片并确认效果。通过后会继续完成精剪和成片。";
  if (kind) return "你现在要做：确认当前内容。通过后会继续制作。";
  return null;
}

// ---------------------------------------------------------------------------
// 本次确认材料（看什么）
// ---------------------------------------------------------------------------

function sampleFacts(project) {
  const data = editorDataFor(project, "sample");
  const finalData = editorDataFor(project, "compose");
  const trace = data.execution_trace || {};
  const summary = trace.summary || {};
  const counts = summary.status_counts || {};
  const shots = trace.shots || [];
  const tracks = data.audio_tracks || [];
  const evaluation = data.evaluation;
  const advisory = evaluation?.advisory || {};
  const fails = evaluation?.hard_gate_fails || [];
  return {
    videoUrl: data.preview_url,
    posterUrl: data.poster_url,
    duration: data.duration_seconds ?? finalData.duration_seconds ?? finalData.player?.duration_seconds,
    qaStatus: data.qa_status,
    summaryText: data.review_summary,
    shots,
    counts,
    tracks,
    evaluation,
    advisory: advisory.summary || "",
    fails,
    narrationText: shots.map((shot) => shot.planned?.screen_copy || "").filter(Boolean).join("；"),
  };
}

function factsForGate(project, gateId) {
  if (gateId === "script") {
    const data = editorDataFor(project, "script");
    return { ...data, sections: data.sections || [] };
  }
  if (gateId === "assets") {
    const data = editorDataFor(project, "assets");
    return { ...data, items: data.items || [] };
  }
  if (gateId === "done") {
    const data = editorDataFor(project, "compose");
    const delivery = editorDataFor(project, "publish");
    const payload = Object.keys(delivery || {}).length ? delivery : data;
    return {
      videoUrl: payload.player?.video_url || payload.download_url,
      posterUrl: payload.player?.poster_url,
      duration: payload.player?.duration_seconds ?? payload.duration_seconds,
      qaStatus: payload.qa_status,
      formatLabel: payload.format_label,
      evaluation: payload.evaluation || null,
    };
  }
  return sampleFacts(project);
}

function materialCard(label, detail, icon, active, onSelect) {
  const button = node("button", `approval-artifact${active ? " is-on" : ""}`);
  button.type = "button";
  button.dataset.artifact = label;
  button.setAttribute("aria-current", active ? "true" : "false");
  button.setAttribute("aria-label", `${label}：${detail || "暂未提供"}`);
  if (onSelect) button.addEventListener("click", onSelect);
  button.append(
    node("span", "approval-artifact-icon", icon || "▸"),
    (() => {
      const body = node("span", "approval-artifact-body");
      body.append(node("b", "", label), node("small", "", detail));
      return body;
    })(),
  );
  return button;
}

function renderApprovalMaterialsSample(facts, container) {
  container.append(materialCard("样片", facts.videoUrl ? `${Math.round(facts.duration || 0)} 秒 · ${facts.qaStatus || ""}` : "尚未生成", "▶", true));
  const shotText = facts.shots.length
    ? `${facts.counts.executed ?? facts.shots.length} 个镜头按方案完成`
    : "暂无镜头对照";
  container.append(materialCard("镜头对照", shotText, "▦"));
  const subText = facts.narrationText ? "口播和字幕已生成" : "暂无口播字幕";
  container.append(materialCard("字幕和口播", subText, "字"));
  const sound = facts.tracks.length
    ? facts.tracks.map((track) => track.label || track.kind).join("、")
    : "口播和背景音乐";
  container.append(materialCard("声音效果", sound, "♪"));
  container.append(materialCard("系统检查", facts.qaStatus || "等待检查", "✓"));
  const advice = facts.fails.length ? `${facts.fails.length} 项需要处理` : facts.advisory ? "整体正常 · 建议通过" : "尚未给出建议";
  container.append(materialCard("系统建议", advice, "↗"));
  container.append(materialCard("制作依据", "文案、镜头和素材方案", "↳"));
  if (facts.qaStatus === "检查通过" && !facts.evaluation) {
    container.append(node("p", "approval-left-warn", APPROVAL_COPY.reportIncomplete));
  }
  const note = node("p", "approval-left-note");
  note.append(node("strong", "", "你只需要看最终效果"), document.createTextNode("：处理过程已收起；有问题可直接指出哪一秒、哪个画面。"));
  container.append(note);
}

function renderApprovalMaterialsScript(facts, container) {
  container.append(materialCard("制作脚本", facts.sections?.length ? `${facts.sections.length} 段${facts.duration ? ` · ${Math.round(facts.duration)} 秒` : ""}` : "等待生成", "字", true));
  container.append(materialCard("制作依据", "创意方案与已确认卖点", "↳"));
  container.append(node("p", "approval-left-note", "确认通过后会按这段脚本制作；如有错字或表述问题，请退回并说明位置。"));
}

function renderApprovalMaterialsAssets(facts, container) {
  container.append(materialCard("生成清单", facts.items?.length ? `${facts.planned_count ?? facts.items.length} 项 · ${facts.prepared_count ?? 0} 项已就绪` : "等待生成", "▦", true));
  for (const item of (facts.items || []).slice(0, 8)) {
    container.append(materialCard(item.label || item.type || "材料", item.state_label || item.status || "待确认", "•"));
  }
  container.append(node("p", "approval-left-note", "确认清单无误后开始生成画面和声音；费用与预算请一并确认。"));
}

function renderApprovalMaterialsDone(facts, container) {
  container.append(materialCard("成片", facts.videoUrl ? `${Math.round(facts.duration || 0)} 秒 · ${facts.qaStatus || ""}` : "尚未生成", "▶", true));
  container.append(materialCard("交付信息", facts.formatLabel || "竖屏视频", "↳"));
  container.append(materialCard("系统检查", facts.qaStatus || "等待检查", "✓"));
  container.append(node("p", "approval-left-note", "这是最终成片。确认无误后即可交付；发现问题请退回修改。"));
}

function renderApprovalMaterials(project, model) {
  const container = byId("approval-materials");
  if (!container) return;
  container.replaceChildren();
  const selected = model.stages.find((stage) => stage.stageId === model.selectedStageId) || model.stages[0];
  const isCurrent = model.selectedStageId === model.reviewGateId;
  container.append(node("p", "approval-eyebrow", isCurrent ? APPROVAL_COPY.materialsEyebrow : "本阶段材料"));
  container.append(node("h2", "approval-materials-heading", isCurrent ? APPROVAL_COPY.materialsHeading : `${selected?.stageLabel || "制作步骤"} · 可查看`));
  if (!selected) {
    container.append(node("p", "approval-left-note", "当前没有可展示的制作材料。"));
    return;
  }
  selected.artifacts.forEach((artifact) => {
    const detail = artifact.summary && artifact.summary.length > 74 ? `${artifact.summary.slice(0, 74)}…` : artifact.summary;
    const button = materialCard(artifact.label, detail, artifact.kind === "sample_video" || artifact.kind === "final_video" || artifact.kind === "delivery_video" ? "▶" : "•",
      artifact.id === model.selectedArtifactId, () => {
        document.dispatchEvent(new CustomEvent("approval-select-artifact", { detail: { artifactId: artifact.id } }));
      });
    button.dataset.artifactId = artifact.id;
    button.dataset.testid = `approval-artifact-${artifact.id}`;
    container.append(button);
  });
  const note = node("p", "approval-left-note");
  note.append(node("strong", "", isCurrent ? "这一步需要你确认" : "这里先只查看"), document.createTextNode(isCurrent
    ? "：点击材料查看详情，右侧确认结果。" : "：需要确认时，回到当前确认。"));
  container.append(note);
}

// ---------------------------------------------------------------------------
// 视频与说明（看什么 → 判断什么）
// ---------------------------------------------------------------------------

function playerFor(facts, gateId) {
  const wrap = node("div", "approval-player");
  if (!facts.videoUrl) {
    const empty = node("div", "approval-player-empty");
    empty.append(node("p", "approval-muted", APPROVAL_COPY.missingMedia));
    empty.append(node("p", "approval-recover-hint", "请重新拉取最新结果；若仍缺失请联系制作人员。"));
    wrap.append(empty);
    return wrap;
  }
  const video = document.createElement("video");
  video.className = "approval-video";
  video.controls = true;
  video.playsInline = true;
  video.preload = "none";
  if (facts.posterUrl) video.poster = facts.posterUrl;
  video.src = facts.videoUrl;
  video.setAttribute("aria-label", gateId === "done" ? "成片预览" : "样片预览");
  video.addEventListener("error", () => {
    wrap.querySelector(".approval-player-error")?.remove();
    const message = node("p", "approval-player-error", APPROVAL_COPY.playbackFailed);
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
    wrap.append(message);
  });
  wrap.append(video);
  return wrap;
}

function valueLabel(key) {
  return {
    summary: "说明", title: "标题", text: "内容", label: "名称", hook: "开头", kind: "类型",
    core_message: "核心卖点", visual_approach: "画面做法", target_audience: "目标人群",
    tone: "语气", narrative_structure: "叙事结构", duration_seconds: "时长",
    purpose: "镜头目的", subject_action: "画面动作",
    visual_intent: "画面重点", source_label: "使用素材", qa_status: "检查结果",
    recommended_action: "下一步", format_label: "视频格式", status: "状态",
    start_seconds: "开始时间", end_seconds: "结束时间", fixable: "是否可修复",
    duration: "时长", duration_seconds: "时长", screen_copy: "字幕",
    narration: "口播", caption: "字幕", difference: "不同之处",
    checked_count: "已检查素材", usable_count: "可用素材", items: "素材明细",
    reviewed: "检查情况", recommended_range: "建议片段", risks: "需要留意",
    identified: "已识别", needs_review: "需要确认", missing: "未识别",
    rows: "镜头明细", time_range: "时间", audio: "声音", music: "音乐",
    evidence: "画面参考", note: "备注", reason: "匹配原因",
    recommended_source: "推荐素材", result: "检查说明", keep: "建议保留",
    change: "建议调整", avoid: "注意避免", summary: "说明", steps: "研究过程",
    proof_method: "证明方法", avg_evidence_seconds: "证明节奏",
    camera_method: "镜头方法", caption_method: "字幕方法", beat_order: "内容顺序",
    replicate: "可以借鉴", differentiate: "需要做出差异", scenes: "参考片段",
    shot_size: "景别", camera_angle: "机位", camera_movement: "运镜",
    dialogue: "台词", overlay_text: "画面文字", effect_treatment: "画面效果",
    setting: "场景", usable_for: "可以用来", promise: "方向说明", score: "检查得分",
    impact: "会影响",
  }[key] || key;
}

function displayValue(value) {
  if (typeof value !== "string") return value;
  const labels = {
    pass: "通过", rejected: "未通过", completed: "已完成",
    in_progress: "制作中", awaiting_human: "等待确认", pending: "未开始",
    failed: "处理失败", partial: "部分完成", present: "已准备", missing: "缺少材料",
    ready: "已准备好", needs_decision: "等待确认", not_needed: "本项目不需要",
    accepted: "已采用", accept: "已采用", replace_source: "更换素材", bridge: "补充素材",
    rewrite: "调整表达", omit: "已删除", avoid: "暂不采用", peak: "重点段落",
    true: "是", false: "否",
  };
  return labels[value] || value;
}

function isTechnicalArtifactKey(key) {
  const value = String(key || "").toLowerCase();
  return value === "id" || value === "version" || value === "revision"
    || value.includes("hash") || value.includes("sha256") || value.includes("runtime")
    || value.includes("schema") || value.includes("scope") || value.includes("provider")
    || value.includes("model") || value.includes("judge") || value.includes("project_id")
    || value.includes("report_id") || value.includes("source_media_id")
    || value.endsWith("_path") || value.endsWith("_url");
}

function approvalTagList(values) {
  const list = node("div", "approval-detail-tags");
  values.forEach((value) => list.append(node("span", "approval-detail-tag", displayValue(value))));
  return list;
}

function renderSourceInventoryDetail(container, payload) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.items)) return false;
  const counts = node("div", "approval-detail-stats");
  if (payload.checked_count != null) counts.append(detailRow("已检查素材", `${payload.checked_count} 条`));
  if (payload.usable_count != null) counts.append(detailRow("可用素材", `${payload.usable_count} 条`));
  if (counts.childElementCount) container.append(counts);
  const list = node("div", "approval-research-source-list");
  payload.items.forEach((item, index) => {
    const card = node("article", "approval-research-source");
    if (item.preview_url) {
      if (item.media_type === "image") {
        const image = document.createElement("img");
        image.className = "approval-source-preview";
        image.src = item.preview_url;
        image.loading = "lazy";
        image.alt = `${item.title || `素材 ${index + 1}`}预览`;
        card.append(image);
      } else if (item.media_type === "audio") {
        const audio = document.createElement("audio");
        audio.className = "approval-source-audio";
        audio.controls = true;
        audio.preload = "none";
        audio.src = item.preview_url;
        audio.setAttribute("aria-label", `${item.title || `素材 ${index + 1}`}音频预览`);
        card.append(audio);
      } else {
        const video = document.createElement("video");
        video.className = "approval-source-preview";
        video.controls = true;
        video.playsInline = true;
        video.preload = "metadata";
        video.src = item.preview_url;
        if (item.poster_url) video.poster = item.poster_url;
        video.setAttribute("aria-label", `${item.title || `素材 ${index + 1}`}视频预览`);
        card.append(video);
      }
    }
    const body = node("div", "approval-research-source-body");
    body.append(node("h4", "approval-detail-item-title", item.title || `素材 ${index + 1}`));
    if (item.summary) body.append(node("p", "approval-detail-copy", item.summary));
    if (item.reviewed) body.append(detailRow("检查情况", item.reviewed));
    if (item.usable_for) body.append(detailRow("可以用来", item.usable_for));
    if (item.duration) body.append(detailRow("时长", item.duration));
    if (item.resolution) body.append(detailRow("画面尺寸", item.resolution));
    if (item.recommended_range) body.append(detailRow("建议片段", item.recommended_range));
    if (item.risks) body.append(detailRow("需要留意", item.risks));
    card.append(body);
    list.append(card);
  });
  container.append(list);
  return true;
}

function renderArtifactValue(container, value, depth = 0) {
  if (value == null || value === "") return;
  if (typeof value !== "object") {
    container.append(node("p", depth ? "approval-detail-copy" : "approval-detail-lead", displayValue(value)));
    return;
  }
  if (Array.isArray(value)) {
    if (value.every((item) => item == null || typeof item !== "object")) {
      container.append(approvalTagList(value.filter((item) => item != null && item !== "")));
      return;
    }
    const list = node("div", "approval-detail-list");
    value.slice(0, 30).forEach((item, index) => {
      const row = node("article", "approval-detail-item");
      if (typeof item === "object" && item !== null) {
        if (item.poster_url) {
          const image = document.createElement("img");
          image.className = "approval-scene-thumb";
          image.src = item.poster_url;
          image.loading = "lazy";
          image.alt = "";
          row.append(image);
        }
        row.append(node("h4", "approval-detail-item-title", item.label || item.title || `第 ${index + 1} 项`));
        renderArtifactValue(row, item, depth + 1);
      } else {
        row.append(node("p", "approval-detail-copy", displayValue(item)));
      }
      list.append(row);
    });
    container.append(list);
    return;
  }
  Object.entries(value).forEach(([key, item]) => {
    if (item == null || item === "" || isTechnicalArtifactKey(key)) return;
    if (typeof item === "object") {
      const section = node("section", "approval-detail-group");
      section.append(node("h4", "approval-detail-group-title", valueLabel(key)));
      renderArtifactValue(section, item, depth + 1);
      container.append(section);
    } else {
      container.append(detailRow(valueLabel(key), displayValue(item)));
    }
  });
}

function renderArtifactDetail(container, artifact) {
  const detail = node("section", "approval-detail");
  detail.dataset.artifactId = artifact.id;
  detail.append(node("div", "approval-detail-kicker", artifact.health === "failed" ? "资料异常" : artifact.health === "processing" ? "正在准备" : "制作材料"));
  detail.append(node("h2", "approval-detail-title", artifact.label));
  if (artifact.health === "failed") detail.append(node("p", "approval-detail-warning", "这项材料处理失败，请重新拉取最新结果。"));
  else if (artifact.health === "processing") detail.append(node("p", "approval-detail-warning", "这项材料还在准备中，完成后会自动显示。"));
  else if (artifact.health === "missing") detail.append(node("p", "approval-detail-warning", "这项材料暂未生成。"));
  const payload = artifact.payload;
  const referencePreview = artifact.id === "reference_highlights" && typeof payload === "object" ? payload.preview_url : null;
  const mediaUrl = typeof payload === "string" && /^(https?:|\/)/.test(payload) && /video|sample|final|delivery|edit_result/.test(artifact.id);
  if (referencePreview) {
    const video = document.createElement("video");
    video.className = "approval-detail-video";
    video.controls = true; video.playsInline = true; video.preload = "metadata"; video.src = referencePreview;
    if (payload.poster_url) video.poster = payload.poster_url;
    video.setAttribute("aria-label", "参考片预览");
    detail.append(video);
  }
  if (mediaUrl) {
    const video = document.createElement("video");
    video.className = "approval-detail-video";
    video.controls = true; video.playsInline = true; video.preload = "metadata"; video.src = payload;
    video.setAttribute("aria-label", `${artifact.label}预览`);
    video.addEventListener("error", () => {
      const message = node("p", "approval-player-error", APPROVAL_COPY.playbackFailed);
      message.setAttribute("role", "status");
      message.setAttribute("aria-live", "polite");
      detail.append(message);
    }, { once: true });
    detail.append(video);
  } else if (artifact.id === "source_inventory" && renderSourceInventoryDetail(detail, payload)) {
    // 素材库保留缩略图和可播放预览，其余研究材料走统一文字详情。
  } else if (payload != null) {
    renderArtifactValue(detail, payload);
  } else if (artifact.summary) {
    detail.append(node("p", "approval-detail-copy", artifact.summary));
  }
  container.append(detail);
}

function renderApprovalMedia(model) {
  const media = byId("approval-media");
  if (!media) return;
  media.replaceChildren();
  const stage = model.stages.find((item) => item.stageId === model.selectedStageId);
  const artifact = stage?.artifacts.find((item) => item.id === model.selectedArtifactId) || stage?.artifacts[0];
  if (artifact) renderArtifactDetail(media, artifact);
  else media.append(node("p", "approval-muted", "当前没有可展示的制作材料。"));
}

function deliverLine(kind, title, detail) {
  const item = node("div", `approval-delivery${kind === "warn" ? " is-warn" : ""}`);
  item.append(node("i", "", kind === "warn" ? "!" : "✓"));
  const body = node("div", "");
  body.append(node("b", "", title), node("small", "", detail));
  item.append(body);
  return item;
}

function renderGateCopy(project, model) {
  const box = byId("approval-gate-copy");
  if (!box) return;
  box.replaceChildren();
  const stage = model.stages.find((item) => item.stageId === model.selectedStageId);
  const isCurrent = model.selectedStageId === model.reviewGateId;
  const detail = GATE_DETAILS[model.selectedStageId] || GATE_DETAILS.done;
  const kicker = node("span", "approval-kicker", `${isCurrent ? `第 ${GATE_TO_INDEX[model.selectedStageId] || 1} 次确认` : "制作步骤"} · ${stage?.stageLabel || "制作步骤"}`);
  box.append(kicker);
  box.append(node("h2", "approval-gate-heading", isCurrent ? detail.heading : `${stage?.stageLabel || "制作步骤"}的制作材料`));
  box.append(node("p", "approval-gate-intro", isCurrent ? detail.intro : (stage?.summary || "这里展示该阶段的业务材料和制作结果。")));
  const deliveries = node("div", "approval-deliveries");
  if (model.selectedStageId === "sample" && isCurrent) {
    const facts = factsForGate(project, "sample");
    const executed = facts.counts?.executed ?? facts.shots?.length ?? 0;
    deliveries.append(deliverLine("ok", `${executed} 个镜头已按方案制作`, "可在“镜头对照”里逐个查看。"));
    const narration = (facts.tracks || []).some((track) => String(track.kind || track.label || "").includes("口播") || String(track.kind || "").includes("narration"));
    deliveries.append(deliverLine(narration && facts.narrationText ? "ok" : "warn", "口播和字幕已配好", "可在“字幕和口播”里查看。"));
    if (facts.fails?.length || facts.advisory) {
      deliveries.append(deliverLine("warn", "有一项检查需要你留意", facts.fails?.[0]?.message || facts.advisory));
    }
  } else if (model.selectedStageId === "publish" || model.selectedStageId === "compose") {
    const facts = factsForGate(project, "done");
    deliveries.append(deliverLine(facts.qaStatus === "检查通过" ? "ok" : "warn", facts.qaStatus === "检查通过" ? "检查通过" : "检查还有问题", facts.qaStatus === "检查通过" ? "画面、声音和文件都正常，可以交付。" : "请先查看检查结果。"));
  } else if (model.selectedStageId === "script" && isCurrent) {
    deliveries.append(deliverLine("ok", "文案已整理好", "确认没有错别字和表述问题后，就可以开始制作。"));
  } else if (model.selectedStageId === "assets" && isCurrent) {
    deliveries.append(deliverLine("ok", "制作清单已准备好", "画面、声音、素材和费用都已列明。"));
  }
  box.append(deliveries);
}

function renderApprovalTimeline(project, model) {
  const box = byId("approval-timeline");
  if (!box) return;
  box.replaceChildren();
  if (model.selectedStageId !== "sample" || model.selectedArtifactId !== "shot_comparison") { box.hidden = true; return; }
  box.hidden = false;
  const facts = factsForGate(project, "sample");
  const head = node("div", "approval-timeline-head");
  const duration = (Math.round((facts.duration || 0) * 10) / 10).toFixed(1);
  head.append(node("span", "", "画面和声音对照 · 点击片段可跳到对应位置"), node("span", "", `00:00 ──────── 00:${duration}`));
  box.append(head);
  const lanes = node("div", "approval-lanes");
  const video = byId("approval-media")?.querySelector("video");
  const addLane = (label, segments) => {
    const lane = node("div", "approval-lane");
    lane.append(node("b", "", label));
    const segWrap = node("div", "approval-segments");
    (segments || []).forEach((segment, index) => {
      const seg = node("button", "approval-segment", "");
      seg.type = "button";
      seg.setAttribute("aria-label", `${label}片段 ${index + 1}${segment.start != null ? `，从 ${Number(segment.start).toFixed(1)} 秒开始` : ""}`);
      seg.style.flex = String(segment.flex || 1);
      if (segment.start != null && video) {
        seg.addEventListener("click", () => { video.currentTime = segment.start; video.play().catch(() => {}); });
      }
      segWrap.append(seg);
    });
    lane.append(segWrap);
    lanes.append(lane);
  };
  addLane("画面", (facts.shots || []).map((shot) => ({ start: shot.actual?.timeline_start_seconds, flex: 1 })));
  const narration = (facts.tracks || []).find((track) => String(track.kind || track.label || "").includes("口播") || String(track.kind || "").includes("narration"));
  addLane("口播", narration?.state === "present" ? [{ flex: 3 }] : []);
  addLane("字幕", facts.narrationText ? [{ flex: 3 }] : []);
  const music = (facts.tracks || []).find((track) => String(track.kind || track.label || "").includes("音乐") || String(track.kind || "").includes("music") || String(track.kind || "").includes("BGM"));
  addLane("音乐", music?.state === "present" ? [{ flex: 4 }] : []);
  box.append(lanes);
}

function renderApprovalOutcome(model) {
  const box = byId("approval-outcome");
  if (!box) return;
  box.replaceChildren();
  const gate = model?.stages?.find((stage) => stage.stageId === model.reviewGateId);
  if (!gate?.review?.actionable || model.selectedStageId !== model.reviewGateId) return;
  const mini = (title, items, cls) => {
    const card = node("div", "approval-mini");
    card.append(node("h3", "", title));
    const p = node("p", "");
    items.forEach((item, index) => {
      p.append(node("span", cls, `${index + 1}. `), document.createTextNode(item));
      if (index < items.length - 1) p.append(document.createElement("br"));
    });
    card.append(p);
    return card;
  };
  box.append(mini(APPROVAL_COPY.approveOutcomeTitle, APPROVAL_COPY.approveOutcome, "is-green"));
  box.append(mini(APPROVAL_COPY.rejectOutcomeTitle, APPROVAL_COPY.rejectOutcome, "is-amber"));
}

// ---------------------------------------------------------------------------
// 五项确认与主动作（判断什么 → 之后发生什么）
// ---------------------------------------------------------------------------

function mapReviewError(error) {
  if (!error) return "操作暂时无法完成";
  if (error.code === "stale" || error.code === "review_stale") return APPROVAL_COPY.stale;
  if (error.code === "review_already_decided") return APPROVAL_COPY.alreadyDecided;
  if (error.code === "forbidden") return APPROVAL_COPY.forbidden;
  if (error.code === "validation_failed") return APPROVAL_COPY.validationFailed;
  return error.message || "操作暂时无法完成";
}

const ISSUE_TAG_BY_KEY = {
  creative_direction: "unclear_promise",
  hook: "weak_hook",
  proof: "information_gap",
  pacing: "timing",
  readability: "mobile_illegibility",
};

function renderConfirmationSample(facts, project, gate, canAct = hasReviewPermission(project)) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", "样片确认"));
  head.append(node("small", "", `第 ${gate.version} 版 · ${Math.round(facts.duration || 0)} 秒`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", APPROVAL_COPY.fiveChecksHeading));
  box.append(node("p", "approval-confirm-intro", APPROVAL_COPY.fiveChecksIntro));
  const canReview = canAct;
  const selections = {};
  const issueReasons = {};
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  const cards = node("div", "approval-check-list");
  CONFIRMATION_ITEMS.forEach((item, index) => {
    const card = node("div", "approval-check-card");
    card.append(node("b", "", `${index + 1} ${item.title}`), node("p", "approval-check-prompt", item.prompt));
    const choices = node("div", "approval-check-choices");
    Object.entries(CONFIRMATION_VALUE_LABELS).forEach(([value, label]) => {
      const button = node("button", "approval-check-value", label);
      button.type = "button";
      button.disabled = !canReview;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => {
        selections[item.key] = value;
        issueReasons[item.key] = `${item.title}：${CONFIRMATION_VALUE_LABELS[value]}`;
        choices.querySelectorAll("button").forEach((btn) => {
          btn.classList.remove("is-selected");
          btn.setAttribute("aria-pressed", "false");
        });
        button.classList.add("is-selected");
        button.setAttribute("aria-pressed", "true");
        updateActions();
      });
      choices.append(button);
    });
    card.append(choices);
    cards.append(card);
  });
  box.append(cards);
  // 后续流程说明统一放在中间区，右侧只保留判断和提交动作，避免重复。
  const reject = node("button", "approval-reject", APPROVAL_COPY.reject);
  reject.type = "button";
  reject.disabled = !canReview;
  reject.dataset.testid = "approval-reject";
  const approve = node("button", "approval-approve", APPROVAL_COPY.approve);
  approve.type = "button";
  approve.disabled = !canReview;
  approve.dataset.testid = "approval-approve";
  const actions = node("div", "approval-confirm-actions");
  actions.append(reject, approve);
  box.append(actions, message);
  const updateActions = () => {
    const selectedKeys = Object.keys(selections);
    const allPass = selectedKeys.length === CONFIRMATION_ITEMS.length
      && selectedKeys.every((key) => selections[key] === "pass");
    approve.disabled = !canReview || !allPass;
    reject.disabled = !canReview || selectedKeys.length === 0;
    message.textContent = !canReview
      ? APPROVAL_COPY.forbidden
      : allPass ? "五项都已确认通过，可以继续。" : selectedKeys.length ? "有一项或多项需要修改，请退回。" : "请确认这 5 项。";
  };
  const submit = async (decision) => {
    const review = project.pending_review;
    if (!review?.review_id || review.subject_hash == null) {
      message.textContent = "确认信息尚未准备好，请刷新后重试。";
      return;
    }
    approve.disabled = true;
    reject.disabled = true;
    try {
      // 五项确认的 effect_confirmations 与 review_id / 内容 hash / 版本一起
      // 写入现有 review 服务；拒绝时附带问题标签，供批量质量统计使用。
      if (decision === "approved") {
        await decideReview(project.project_id, review.review_id, "approved", "样片效果确认通过", selections, review.subject_version, review.subject_hash, null);
      } else {
        const reasons = Object.keys(issueReasons).length ? Object.values(issueReasons).join("；") : "请按意见调整样片";
        const tags = [...new Set(Object.entries(selections).filter(([, value]) => value !== "pass").map(([key]) => ISSUE_TAG_BY_KEY[key]).filter(Boolean))];
        await decideReview(project.project_id, review.review_id, "rejected", reasons, selections, review.subject_version, review.subject_hash, tags.length ? tags : null);
      }
      message.textContent = decision === "approved" ? "样片已确认，正在继续制作。" : "调整意见已提交，将按意见修改后再次确认。";
      requestApprovalRefresh(project.project_id);
    } catch (error) {
      message.textContent = mapReviewError(error);
      updateActions();
    }
  };
  approve.addEventListener("click", () => submit("approved"));
  reject.addEventListener("click", () => submit("rejected"));
}

function renderConfirmationSimple(gate, project, canAct = hasReviewPermission(project)) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", gate.label));
  head.append(node("small", "", `第 ${gate.version} 版`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", gate.detail.confirmTitle));
  box.append(node("p", "approval-confirm-intro", "看完左侧材料后，确认这一步是否可以继续。"));
  const canReview = canAct;
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  const reasonBox = node("textarea", "approval-reason", "");
  reasonBox.placeholder = "如有问题，请在这里说明需要修改的地方（可选）";
  reasonBox.disabled = !canReview;
  const reject = node("button", "approval-reject", APPROVAL_COPY.reject);
  reject.type = "button";
  reject.disabled = !canReview;
  reject.dataset.testid = "approval-reject";
  const approve = node("button", "approval-approve", APPROVAL_COPY.approve);
  approve.type = "button";
  approve.disabled = !canReview;
  approve.dataset.testid = "approval-approve";
  const actions = node("div", "approval-confirm-actions");
  actions.append(reject, approve);
  box.append(reasonBox, actions, message);
  if (!canReview) message.textContent = APPROVAL_COPY.forbidden;
  const submit = async (decision) => {
    const review = project.pending_review;
    if (!review?.review_id || review.subject_hash == null) {
      message.textContent = "确认信息尚未准备好，请刷新后重试。";
      return;
    }
    approve.disabled = true;
    reject.disabled = true;
    try {
      const reason = decision === "approved" ? "内容确认通过" : (reasonBox.value || "请根据意见修改后再提交");
      await decideReview(project.project_id, review.review_id, decision, reason, null, review.subject_version, review.subject_hash, null);
      message.textContent = decision === "approved" ? "已确认，正在继续制作。" : "修改意见已提交。";
      requestApprovalRefresh(project.project_id);
    } catch (error) {
      message.textContent = mapReviewError(error);
      approve.disabled = !canReview;
      reject.disabled = !canReview;
    }
  };
  approve.addEventListener("click", () => submit("approved"));
  reject.addEventListener("click", () => submit("rejected"));
}

function renderConfirmationDone(gate, project, facts) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", "查看成片"));
  head.append(node("small", "", `第 ${gate.version} 版 · ${Math.round(facts.duration || 0)} 秒`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", gate.detail.confirmTitle));
  box.append(node("p", "approval-confirm-intro", `${facts.formatLabel || "纵向视频"} · ${facts.qaStatus || "等待检查"}。交付确认在批量总览统一进行。`));
  const outcomes = node("div", "approval-confirm-outcome");
  outcomes.append(node("b", "", "确认后会怎样"));
  outcomes.append(node("p", "", "检查通过 · 单条页面不再重复审批 · 交付确认由批量总览统一完成。"));
  box.append(outcomes);
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  message.textContent = "无需在此确认：本条候选已完成成片检查。";
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  box.append(message);
}

function renderConfirmationIdle(gate, project) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", gate.label));
  head.append(node("small", "", `第 ${gate.version} 版`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", gate.detail.confirmTitle));
  box.append(node("p", "approval-confirm-intro", gate.detail.intro));
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  const stage = stageById(project, gate.gateId);
  message.textContent = stage?.status === "处理失败"
    ? "当前没有可以确认的内容：这一步处理失败，请查看制作记录或重新拉取最新结果。"
    : "当前没有需要确认的内容：这一步尚未准备完成，请重新拉取最新结果。";
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  box.append(message);
}

function renderReadonlyConfirmation(project, model) {
  const box = byId("approval-confirmation");
  if (!box) return;
  const stage = model.stages.find((item) => item.stageId === model.selectedStageId);
  box.replaceChildren();
  box.append(node("div", "approval-confirm-head", "本阶段查看"));
  box.append(node("h2", "approval-confirm-title", `${stage?.stageLabel || "制作步骤"} · 只读查看`));
  box.append(node("p", "approval-confirm-intro", stage?.summary || "这里展示已生成的制作材料。审批动作只对当前需要确认的步骤开放。"));
  const state = node("p", "approval-readonly-state", stage?.status === "处理失败"
    ? "这一步处理失败，请重新拉取最新结果。"
    : stage?.status === "未开始" ? "这一步还没有开始，完成后会自动显示。"
    : "你正在查看历史或后续材料。需要确认时，请回到当前确认。");
  state.setAttribute("role", "status");
  state.setAttribute("aria-live", "polite");
  if (stage?.status === "处理失败") state.classList.add("is-failed");
  box.append(state);
  if (model.reviewGateId) {
    const back = node("button", "approval-return-current", "回到当前确认");
    back.type = "button"; back.dataset.testid = "approval-select-current";
    back.addEventListener("click", () => document.dispatchEvent(new CustomEvent("approval-select-current")));
    box.append(back);
  }
}

function renderConfirmation(project, model) {
  const selectedStageId = model.selectedStageId;
  const reviewGateId = model.reviewGateId;
  const selectedStage = model.stages.find((stage) => stage.stageId === selectedStageId);
  const canAct = selectedStageId === reviewGateId && selectedStage?.review?.actionable && hasReviewPermission(project);
  const gate = currentGateDetail(project);
  if (!project.pending_review && ["compose", "publish"].includes(selectedStageId) && selectedStage?.status === "已完成") {
    renderConfirmationDone({ ...gate, gateId: selectedStageId }, project, factsForGate(project, "done"));
  } else if (!canAct) {
    renderReadonlyConfirmation(project, model);
  } else if (selectedStageId === "sample" && project.pending_review) {
    renderConfirmationSample(factsForGate(project, "sample"), project, gate, canAct);
  } else if (selectedStageId === "done" || selectedStageId === "compose" || selectedStageId === "publish") {
    renderConfirmationDone(gate, project, factsForGate(project, "done"));
  } else if (!project.pending_review) {
    renderConfirmationIdle(gate, project);
  } else {
    renderConfirmationSimple(gate, project, canAct);
  }
}

// ---------------------------------------------------------------------------
// 制作记录（技术字段折叠区）+ 降级状态
// ---------------------------------------------------------------------------

function renderRecord(project, model) {
  const box = byId("approval-record");
  if (!box) return;
  box.replaceChildren();
  const selected = model.stages.find((item) => item.stageId === model.selectedStageId);
  const gate = currentGateDetail(project);
  const data = editorDataFor(project, model.selectedStageId);
  const summary = project.summary || {};
  box.append(detailRow("当前步骤", selected?.stageLabel || summary.current_stage || "—"));
  box.append(detailRow("检查结果", data.qa_status || data.status || "待检查"));
  const duration = data.duration_seconds ?? data.preview_duration_seconds;
  box.append(detailRow("时长", duration ? `${Math.round(duration)} 秒` : "暂未提供"));
  box.append(detailRow("视频版本", `第 ${selected?.version || gate.version || 1} 版`));
  if (summary.spent_usd != null) box.append(detailRow("制作花费", `$${Number(summary.spent_usd).toFixed(2)}`));
  if (data.evaluation?.status) {
    box.append(detailRow("检查结论", data.evaluation.status === "pass" ? "通过" : "有待处理项"));
    box.append(detailRow("下一步", data.evaluation.recommended_action || "—"));
  }
  if (data.audio_tracks?.length) {
    const labels = data.audio_tracks.map((track) => `${track.label || track.kind}：${track.state_label || track.state || "未知"}`);
    box.append(detailRow("声音情况", labels.join("、")));
  }
}

export function candidateUnavailable(project) {
  if (!project?.stages?.length) return true;
  const statuses = buildApprovalViewModel(project).stages.map((stage) => stage.status);
  return statuses.every((status) => status === "处理失败" || status === "资料异常");
}

// 通知 app.js 拉取最新快照并重渲染（不直接修改批量投影，读路径保持纯净）。
function requestApprovalRefresh(projectId) {
  document.dispatchEvent(new CustomEvent("approval-refresh-request", { detail: { projectId } }));
}

// ---------------------------------------------------------------------------
// 主渲染
// ---------------------------------------------------------------------------

export function renderApprovalWorkbench(container, project, snapshot) {
  const view = buildApprovalViewModel(project);
  const requestedStage = view.stages.find((stage) => stage.stageId === snapshot.selectedStageId);
  const selectedStage = requestedStage || view.stages.find((stage) => stage.stageId === view.reviewGateId) || view.stages[0];
  view.selectedStageId = selectedStage?.stageId || null;
  const requestedArtifact = selectedStage?.artifacts.find((artifact) => artifact.id === snapshot.selectedArtifactId);
  view.selectedArtifactId = requestedArtifact?.id || selectedStage?.artifacts[0]?.id || null;
  const shell = byId("approval-shell");
  if (shell) shell.hidden = false;
  document.title = `${APPROVAL_COPY.brand} · ${project.title || "项目"}`;
  if (candidateUnavailable(project)) {
    const main = byId("approval-main");
    const materials = byId("approval-materials");
    if (main) {
      main.replaceChildren();
      main.append(node("p", "approval-muted", APPROVAL_COPY.unavailable), node("p", "approval-recover-hint", "请返回批量总览重新拉取，或联系制作人员。"));
    }
    if (materials) materials.replaceChildren();
    return;
  }
  renderTopbar(project, snapshot, view);
  renderRail(project, view);
  renderApprovalMaterials(project, view);
  renderApprovalMedia(view);
  renderGateCopy(project, view);
  renderApprovalTimeline(project, view);
  renderApprovalOutcome(view);
  renderConfirmation(project, view);
  renderRecord(project, view);
}

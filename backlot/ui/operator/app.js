import { fetchProjectState, fetchDraft, watchProject, saveDraft, previewDraft, commitDraft, fetchVersions, restoreVersion, quoteShotGeneration, createShotGeneration, adoptShotGeneration, decideReview, batchSelectForEdit, batchApproveGate, batchRecover } from "./api.js";
import { createOperatorStore } from "./store.js";
import { STATUS_MARKS, VIEW_STATES, formatDuration, formatTimeRange, APPROVAL_COPY } from "./language.js";
import { renderTypedEditor } from "./editors.js";
import { renderImpact } from "./impact.js";
import { renderRevisions } from "./revisions.js";
import { isApprovalShellActive, renderApprovalWorkbench } from "./approval.js";

const byId = (id) => document.getElementById(id);
const projectId = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() || "");
const store = createOperatorStore();
const snapshotStore = store;
let activeResearchSubstage = "reference";

function setTestId(element, testId) {
  if (testId) element.dataset.testid = testId;
  return element;
}

function batchProjectUrl(candidateId, batchId = projectId) {
  return `/p/${encodeURIComponent(candidateId)}?from=batch&batch_id=${encodeURIComponent(batchId)}`;
}

function businessErrorMessage(error) {
  if (!error) return "操作暂时无法完成";
  if (error.code === "stale" || error.code === "candidate_mismatch") return "批次与候选不匹配，请返回批量总览";
  if (error.code === "forbidden") return "审批权限已变化，请重新拉取";
  if (error.code === "timeout") return "刷新超时，请重新拉取最新结果";
  return error.message || "操作暂时无法完成";
}

const CANDIDATE_STATUS_LABELS = {
  planned: "未开始", forking: "准备中", sampling: "生成样片", evaluating: "检查中",
  awaiting_review: "等待确认", evaluated: "已完成检查", editing: "等待精剪",
  approved: "已通过", needs_revision: "需要调整", failed: "处理失败",
  missing: "资料缺失", corrupt: "资料异常", excluded: "不参与本批",
  awaiting_human: "等待确认", completed: "已完成", in_progress: "制作中",
};
const STAGE_STATUS_LABELS = {
  script: "确认脚本", assets: "确认制作准备", sample: "查看样片",
  edit: "完成剪辑", compose: "检查成片", publish: "确认交付",
  research: "了解任务", proposal: "看创意方案", scene_plan: "看分镜",
};
function candidateStatusLabel(status) { return CANDIDATE_STATUS_LABELS[status] || "处理中"; }
function stageStateLabel(stageId, status) {
  return `${STAGE_STATUS_LABELS[stageId] || "制作步骤"}：${candidateStatusLabel(status)}`;
}

function candidateBlockLabel(reason) {
  const copy = String(reason || "");
  if (!copy) return "";
  if (copy.includes("尚未通过样片")) return "样片还没有确认";
  if (copy.includes("评分报告") || copy.includes("评价报告")) return "视频检查还没有完成";
  if (copy.includes("不完整")) return "视频检查结果还不完整";
  return "暂时不能进入精剪，请打开单条复核查看";
}

function evaluationDimensionLabel(value) {
  const key = String(value || "").trim().toLowerCase().replaceAll(" ", "_");
  return {
    hook_clarity: "开头吸引力", visual_hierarchy: "画面层次", rhythm: "观看节奏",
    shot_quality: "画面质量", story_coherence: "内容连贯", audio_quality: "声音效果",
    text_readability: "字幕清晰", product_presence: "产品呈现",
  }[key] || "画面观感";
}

function evaluationSummary(value) {
  const copy = String(value || "");
  return /VLM|advisory|L1a|judge/i.test(copy) ? "画面观感还没有检查" : copy;
}

function setPageMode(mode) {
  const shell = byId("operator-shell");
  if (shell) shell.dataset.mode = mode;
  if (document.body) document.body.dataset.mode = mode;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = String(text);
  return element;
}

function detailRow(label, value) {
  const row = node("div", "detail-row");
  row.append(node("span", "detail-label", label), node("strong", "detail-value", value || "暂未提供"));
  return row;
}

function tagList(values, className = "tag-list") {
  const list = node("div", className);
  (values || []).forEach((value) => list.append(node("span", "tag", value)));
  return list;
}

function rangedVideo(data, className, ariaLabel) {
  if (!data.preview_url) return null;
  const video = document.createElement("video");
  video.className = className;
  video.controls = true;
  video.playsInline = true;
  video.preload = "none";
  video.setAttribute("aria-label", ariaLabel);
  if (data.poster_url) video.poster = data.poster_url;
  const start = Number(data.source_in_seconds ?? data.best_in_seconds ?? 0);
  const endValue = data.source_out_seconds ?? data.best_out_seconds;
  const end = endValue == null ? null : Number(endValue);
  video.src = `${data.preview_url}#t=${start}${end == null ? "" : `,${end}`}`;
  video.addEventListener("play", () => {
    if (video.currentTime < start || (end != null && video.currentTime >= end)) video.currentTime = start;
  });
  video.addEventListener("seeking", () => {
    if (video.currentTime < start) video.currentTime = start;
    if (end != null && video.currentTime > end) video.currentTime = end;
  });
  if (end != null) video.addEventListener("timeupdate", () => {
    if (video.currentTime < start) video.currentTime = start;
    if (video.currentTime >= end) {
      video.pause();
      if (video.currentTime !== end) video.currentTime = end;
    }
  });
  return video;
}

function sourcePreview(source) {
  if (!source.preview_url) return null;
  if (source.media_type === "image") {
    const image = document.createElement("img");
    image.className = "source-preview-image"; image.src = source.preview_url; image.loading = "lazy"; image.alt = source.label;
    return image;
  }
  if (source.media_type === "audio") {
    const audio = document.createElement("audio");
    audio.className = "source-audio"; audio.controls = true; audio.preload = "none"; audio.src = source.preview_url;
    audio.setAttribute("aria-label", `${source.label} 音频预览`);
    return audio;
  }
  return rangedVideo(source, "source-video", `${source.label} 素材预览`);
}

function renderReferenceAnalysis(container, reference) {
  if (!reference) return;
  const section = node("section", "reference-analysis");
  const heading = node("div", "reference-heading");
  const title = node("div", "reference-title");
  title.append(node("span", "status-chip", "仅用于分析"), node("h3", "section-title", reference.title || "参考爆款"));
  heading.append(title);
  if (reference.duration_seconds != null) heading.append(node("span", "row-meta", formatDuration(reference.duration_seconds)));
  section.append(heading, node("p", "lead-copy", reference.summary));
  if (reference.fingerprint_upgrade_notice) {
    section.append(node("p", "source-risk", reference.fingerprint_upgrade_notice));
  }
  const preview = rangedVideo(reference, "reference-preview", `${reference.title || "参考爆款"}分析预览`);
  if (preview) section.append(preview);
  const facts = node("div", "reference-facts");
  facts.append(detailRow("开场钩子", reference.hook));
  facts.append(detailRow("为什么有效", reference.proof_method));
  facts.append(detailRow("证据节奏", reference.avg_evidence_seconds == null ? "暂未提供" : `平均 ${Number(reference.avg_evidence_seconds).toFixed(1)} 秒一个证据`));
  facts.append(detailRow("镜头方法", reference.camera_method));
  facts.append(detailRow("字幕方法", reference.caption_method || reference.typography));
  section.append(facts);
  if (reference.beat_order?.length) section.append(node("h4", "detail-heading", "爆款结构"), tagList(reference.beat_order, "tag-list reference-beats"));
  if (reference.replicate?.length) section.append(node("h4", "detail-heading", "可复刻机制"), tagList(reference.replicate));
  if (reference.differentiate?.length) section.append(node("h4", "detail-heading", "原创差异"), tagList(reference.differentiate, "tag-list differentiation-list"));
  if (reference.scenes?.length) {
    const scenes = node("div", "reference-scene-list");
    reference.scenes.forEach((scene, index) => {
      const item = node("article", "reference-scene");
      if (scene.poster_url) {
        const image = document.createElement("img"); image.src = scene.poster_url; image.loading = "lazy"; image.alt = "";
        item.append(image);
      }
      const body = node("div", "reference-scene-body");
      body.append(node("span", "row-meta", `${String(index + 1).padStart(2, "0")} · ${formatTimeRange(scene.start_seconds, scene.end_seconds)}`));
      body.append(node("h4", "row-title", scene.description || "参考镜头"));
      if (scene.screen_copy) body.append(node("p", "row-copy", `画面文字：${scene.screen_copy}`));
      item.append(body); scenes.append(item);
    });
    section.append(node("h4", "detail-heading", "逐段拆解"), scenes);
  }
  container.append(section);
}

function researchAction(label, operation, onOperation, className = "quiet-button") {
  const button = node("button", className, label);
  button.type = "button";
  button.addEventListener("click", () => {
    onOperation(operation);
    button.textContent = "已记录";
    button.disabled = true;
  });
  return button;
}

function researchOperationKey(operation) {
  if (operation.op === "resolve_matrix_row") return `matrix:${operation.matrix_row_id}`;
  if (operation.op === "set_direction_preference" && operation.preference === "prefer") return "direction:preferred";
  return null;
}

function mergeResearchOperation(operations, operation) {
  const key = researchOperationKey(operation);
  if (!key) return [...operations, operation];
  return [...operations.filter((item) => researchOperationKey(item) !== key), operation];
}

function proposalOperationKey(operation) {
  if (operation.op === "review_control_section") return `control-section:${operation.section_id}`;
  if (operation.op === "approve_control_plan") return "control-plan:approval";
  return null;
}

function mergeProposalOperation(operations, operation) {
  const key = proposalOperationKey(operation);
  if (!key) return [...operations, operation];
  return [...operations.filter((item) => proposalOperationKey(item) !== key), operation];
}

function applyProposalControlPlanDraft(data, operations) {
  if (!operations.length || !data?.control_plan) return data;
  const sections = (data.control_plan.sections || []).map((section) => ({ ...section }));
  const controlPlan = { ...data.control_plan, sections };
  for (const operation of operations) {
    if (operation.op === "review_control_section") {
      const section = sections.find((item) => item.id === operation.section_id);
      if (!section) continue;
      section.review = operation.decision;
      section.feedback = operation.feedback || "";
    }
    if (operation.op === "approve_control_plan") controlPlan.status = "approved";
  }
  return { ...data, control_plan: controlPlan };
}

function scriptOperationKey(operation) {
  if (operation.op === "review_script_section") return `script-section:${operation.section_id}`;
  if (operation.op === "approve_production_script") return "script:approval";
  return null;
}

function executionOperationKey(operation) {
  if (operation.op === "set_shot_gap_strategy") return `shot-gap:${operation.shot_id}`;
  if (operation.op === "approve_shot_execution_plan") return "shot-plan:approval";
  return null;
}

function mergeKeyedOperation(operations, operation, keyFor) {
  const key = keyFor(operation);
  if (!key) return [...operations, operation];
  return [...operations.filter((item) => keyFor(item) !== key), operation];
}

function applyScriptDraft(data, operations) {
  const value = { ...data, sections: (data.sections || []).map((section) => ({ ...section })) };
  operations.forEach((operation) => {
    if (operation.op === "review_script_section") {
      const section = value.sections.find((item) => item.id === operation.section_id);
      if (section) { section.review = operation.decision; section.feedback = operation.feedback || ""; }
    }
    if (operation.op === "approve_production_script") value.status = "approved";
  });
  return value;
}

function applyExecutionPlanDraft(data, operations) {
  if (!data.execution_plan) return data;
  const executionPlan = { ...data.execution_plan, shots: (data.execution_plan.shots || []).map((shot) => ({ ...shot })) };
  operations.forEach((operation) => {
    if (operation.op === "set_shot_gap_strategy") {
      const shot = executionPlan.shots.find((item) => item.id === operation.shot_id);
      if (shot) shot.gap_strategy = operation.strategy;
    }
    if (operation.op === "approve_shot_execution_plan") { executionPlan.status = "approved"; executionPlan.locked = true; }
  });
  return { ...data, execution_plan: executionPlan };
}

function renderDecisionInbox(container, data, { editable, onOperation, onPreview, pendingOperations = [] }) {
  const inbox = data.decision_inbox || [];
  const section = node("section", "decision-inbox");
  section.append(node("h3", "section-title", "需要我确认"));
  if (!inbox.length) {
    section.append(node("p", "editor-help", "关键卖点、素材和方向都已有处理结果，可以进入创意方案。"));
    container.append(section);
    return;
  }
  const selectionFor = (decision) => {
    if (decision.kind === "material_gap") return [...pendingOperations].reverse().find((item) => item.op === "resolve_matrix_row" && item.matrix_row_id === decision.matrix_row_id);
    return [...pendingOperations].reverse().find((item) => item.op === "set_direction_preference" && item.preference === "prefer");
  };
  const selectedCount = inbox.filter((decision) => selectionFor(decision)).length;
  const progress = node("div", "decision-progress");
  progress.append(node("strong", "", `已完成 ${selectedCount}/${inbox.length}`), node("span", "", selectedCount === inbox.length ? "可以统一确认" : `还剩 ${inbox.length - selectedCount} 项`));
  section.append(progress, node("p", "editor-help", "先逐项选择，所有决定会一起预览影响，不会立即进入下一阶段。"));
  inbox.forEach((decision) => {
    const selected = selectionFor(decision);
    const card = node("article", `decision-card${selected ? " is-decided" : ""}`);
    card.append(node("h4", "row-title", decision.title), node("p", "row-copy", decision.message), node("p", "decision-impact", `会影响：${decision.impact}`));
    if (editable) {
      const actions = node("div", "decision-choices");
      const addChoice = (label, detail, operation, isSelected) => {
        const choice = node("button", `decision-choice${isSelected ? " is-selected" : ""}`);
        choice.type = "button"; choice.setAttribute("aria-pressed", String(isSelected));
        const copy = node("span", "decision-choice-copy");
        copy.append(node("strong", "", label));
        if (detail) copy.append(node("small", "", detail));
        choice.append(copy, node("span", "decision-choice-mark", isSelected ? "已选择" : "选择"));
        choice.addEventListener("click", () => { activeResearchSubstage = "quality"; onOperation(operation); });
        actions.append(choice);
      };
      if (decision.kind === "material_gap") {
      const choices = [["需要补拍或补素材", "bridge"], ["改成别的表达", "rewrite"], ["删除这一镜", "omit"]];
        choices.forEach(([label, resolution]) => addChoice(label, resolution === "bridge" ? "保留卖点，补齐可信画面" : resolution === "rewrite" ? "使用现有证据，调整卖点说法" : "从方案中移除这一镜", {
          op: "resolve_matrix_row", matrix_row_id: decision.matrix_row_id, resolution,
          source_media_id: decision.source_media_id, note: label,
        }, selected?.resolution === resolution));
      } else {
        (data.directions || []).forEach((direction) => addChoice(direction.title, direction.promise, {
          op: "set_direction_preference", direction_id: direction.id, preference: "prefer", rationale: "制作人员选择",
        }, selected?.direction_id === direction.id));
      }
      card.append(actions);
    }
    section.append(card);
  });
  if (editable) {
    const confirmBar = node("div", "decision-confirm-bar");
    const summary = node("div", "");
    summary.append(node("strong", "", selectedCount === inbox.length ? `${inbox.length} 项决定已选好` : "完成全部选择后统一确认"), node("small", "", "提交前会展示对创意方案、口播字幕和分镜的影响"));
    const confirm = node("button", "primary-button", "查看影响并确认");
    confirm.type = "button"; confirm.disabled = selectedCount !== inbox.length;
    confirm.addEventListener("click", onPreview);
    confirmBar.append(summary, confirm); section.append(confirmBar);
  }
  container.append(section);
}

function renderProposalHandoff(container, data) {
  const handoff = data.proposal_handoff;
  if (!handoff) return;
  const section = node("section", `proposal-handoff is-${handoff.state}`);
  section.append(node("h3", "section-title", "下一步"), node("p", "row-copy", handoff.message));
  if (handoff.state === "ready") {
    const command = `继续 ${projectId}，读取已确认的 Research 决策并生成创意方案`;
    section.append(node("p", "editor-help", "当前工作台还没有直连 Code Agent。复制下面这句话，到 Agent 窗口发送即可继续。"));
    const commandBox = node("div", "agent-command");
    commandBox.append(node("code", "", command));
    const button = node("button", "primary-button", "复制给 Code Agent");
    button.type = "button";
    button.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(command); button.textContent = "已复制"; }
      catch { button.textContent = "请手动复制上面的指令"; }
    });
    commandBox.append(button); section.append(commandBox);
  }
  container.append(section);
}

function renderResearch(container, data, { editable = false, onOperation = () => {}, onPreview = () => {}, pendingOperations = [] } = {}) {
  const substageNav = node("nav", "research-substage-nav");
  substageNav.setAttribute("aria-label", "Research 子阶段");
  const panelWrap = node("div", "research-substage-panels");
  const panels = new Map();
  const substages = data.substages || [
    { id: "reference", label: "参考片怎么拍", state: data.reference ? "completed" : "not_needed", message: data.reference ? "已拆解参考片" : "本项目没有参考片，这一步不需要处理" },
    { id: "sources", label: "我的素材能不能接上", state: "completed", message: "已检查自有素材" },
    { id: "matching", label: "参考镜头和我的素材怎么对应", state: "completed", message: "已完成逐镜头匹配" },
    { id: "direction", label: "这条片准备怎么做", state: "completed", message: "已整理可选方向" },
    { id: "quality", label: "还有什么没看清", state: "completed", message: "已完成检查" },
  ];
  if (!substages.some((item) => item.id === activeResearchSubstage)) activeResearchSubstage = substages[0]?.id || "reference";
  substages.forEach((substage, index) => {
    const button = node("button", `research-substage${substage.state === "not_needed" ? " is-not-needed" : ""}`);
    button.type = "button";
    button.dataset.researchSubstage = substage.id;
    button.append(node("span", "research-substage-index", String(index + 1).padStart(2, "0")));
    const copy = node("span", "research-substage-copy");
    copy.append(node("strong", "research-substage-label", substage.label), node("small", "research-substage-state", substage.state === "not_needed" ? "本项目不需要" : substage.message));
    button.append(copy);
    button.addEventListener("click", () => {
      activeResearchSubstage = substage.id;
      panels.forEach((panel, id) => panel.hidden = id !== substage.id);
      substageNav.querySelectorAll("button").forEach((item) => item.classList.toggle("is-active", item === button));
    });
    substageNav.append(button);
    const panel = node("section", `research-substage-panel${substage.state === "not_needed" ? " is-not-needed" : ""}`);
    panel.dataset.substage = substage.id;
    panel.hidden = substage.id !== activeResearchSubstage;
    const panelHeading = node("div", "research-substage-panel-heading");
    panelHeading.append(node("h3", "section-title", substage.label), node("p", "research-substage-message", substage.message));
    panel.append(panelHeading);
    panels.set(substage.id, panel);
    panelWrap.append(panel);
  });
  const activeSubstageButton = substageNav.querySelector(`[data-research-substage="${activeResearchSubstage}"]`);
  if (activeSubstageButton) activeSubstageButton.classList.add("is-active");
  container.append(substageNav, panelWrap);
  const referencePanel = panels.get("reference") || container;
  const sourcesPanel = panels.get("sources") || container;
  const matchingPanel = panels.get("matching") || container;
  const directionPanel = panels.get("direction") || container;
  const qualityPanel = panels.get("quality") || container;
  renderDecisionInbox(qualityPanel, data, { editable, onOperation, onPreview, pendingOperations });
  if (data.template) {
    const template = node("section", "content-row research-template");
    template.append(node("h3", "section-title", "本次拆解模板"));
    template.append(detailRow("模板", data.template.label));
    template.append(detailRow("状态", data.template.status));
    referencePanel.prepend(template);
  }
  if (data.reference) renderReferenceAnalysis(referencePanel, data.reference);
  if (data.breakdown) {
    referencePanel.append(node("h3", "section-title", "分镜拆解"));
    const stats = node("div", "inline-stats");
    stats.append(detailRow("已识别", `${data.breakdown.identified} 项`));
    stats.append(detailRow("待确认", `${data.breakdown.needs_review} 项`));
    stats.append(detailRow("没看清", `${data.breakdown.missing} 项`));
    referencePanel.append(stats);
    const rows = node("div", "research-shot-rail research-breakdown-list");
    (data.breakdown.rows || []).forEach((row) => {
      const item = node("article", "content-row research-breakdown-row");
      const heading = node("div", "source-heading");
      heading.append(node("h4", "row-title", row.visual_content || "这一镜暂未识别画面内容"));
      heading.append(node("span", row.needs_review ? "status-chip" : "status-chip is-ready", row.needs_review ? "需要确认" : row.origin));
      item.append(heading, node("p", "row-meta", formatTimeRange(row.start_seconds, row.end_seconds)));
      if (row.shot_size) item.append(detailRow("景别", row.shot_size));
      if (row.camera_angle) item.append(detailRow("机位", row.camera_angle));
      if (row.camera_movement) item.append(detailRow("运镜", row.camera_movement));
      if (row.dialogue) item.append(detailRow("台词", row.dialogue));
      if (row.overlay_text) item.append(detailRow("花字", row.overlay_text));
      if (row.effect_treatment) item.append(detailRow("特效", row.effect_treatment));
      if (row.setting) item.append(detailRow("场景", row.setting));
      if (row.audio_layers?.length) item.append(detailRow("声音", row.audio_layers.join("、")));
      if (row.music_profile) item.append(detailRow("BGM", row.music_profile));
      if (row.evidence_frames?.length) item.append(detailRow("画面参考", `${row.evidence_frames.length} 个关键帧`));
      if (row.analyst_note) item.append(detailRow("备注", row.analyst_note));
      if (editable) {
        item.append(researchAction("重新看这一段", {
          op: "request_local_reanalysis", target_type: "shot", target_id: row.id,
          dimensions: ["visual_content", "dialogue", "overlay_text"], reason: "制作人员请求重新确认",
        }, onOperation));
      }
      rows.append(item);
    });
    referencePanel.append(rows);
  }
  sourcesPanel.append(node("h3", "section-title", "我的素材"));
  const stats = node("div", "inline-stats");
  stats.append(detailRow("已检查素材", `${data.source_count} 条`));
  stats.append(detailRow("可用素材", `${data.usable_count} 条`));
  sourcesPanel.append(stats);
  if (data.sources?.length) {
    const list = node("div", "source-list");
    data.sources.forEach((source) => {
      const item = node("article", "source-card");
      const media = node("div", "source-media");
      if (source.poster_url) {
        const image = document.createElement("img"); image.src = source.poster_url; image.loading = "lazy"; image.alt = "";
        media.append(image);
      }
      const body = node("div", "source-body");
      const heading = node("div", "source-heading");
      heading.append(node("h3", "row-title", source.label));
      heading.append(node("span", source.reviewed ? "status-chip is-ready" : "status-chip", source.reviewed ? "已检查" : "待检查"));
      body.append(heading, node("p", "row-copy", source.summary || "暂无内容摘要"));
      const facts = [source.resolution, source.fps == null ? "" : `${Number(source.fps).toFixed(2)} fps`, formatDuration(source.duration_seconds)].filter(Boolean);
      if (facts.length) body.append(node("p", "source-facts", facts.join(" · ")));
      if (source.best_in_seconds != null && source.best_out_seconds != null) body.append(node("p", "source-range", `建议区间 ${formatTimeRange(source.best_in_seconds, source.best_out_seconds)}`));
      if (source.usable_for?.length) body.append(tagList(source.usable_for));
      if (source.risks?.length) body.append(node("p", "source-risk", source.risks.join("；")));
      const preview = sourcePreview(source);
      if (preview) body.append(preview);
      item.append(media, body); list.append(item);
    });
    sourcesPanel.append(node("h3", "section-title", "素材明细"), list);
  }
  if (data.risks?.length) {
    const list = node("ul", "plain-list");
    data.risks.forEach((risk) => list.append(node("li", "", risk)));
    sourcesPanel.append(node("h3", "section-title", "需要留意"), list);
  }
  if (data.matching?.rows?.length) {
    matchingPanel.append(node("h3", "section-title", "参考镜头 × 我的素材"));
    const list = node("div", "research-shot-rail research-matching-list");
    data.matching.rows.forEach((row) => {
      const item = node("article", "content-row research-matching-row");
      item.append(node("h4", "row-title", row.reference_intent || "参考镜头"));
      item.append(node("p", "row-copy", row.match_reason || "暂未找到可信的匹配理由"));
      item.append(detailRow("推荐素材", row.source_media_id || "还没有合适素材"));
      item.append(detailRow("当前处理", row.status));
      if (row.gap) item.append(node("p", "source-risk", row.gap));
      if (editable) {
        const actions = node("div", "inline-edit-actions");
        const choices = [
          ["采用这段", "accept"], ["换一段", "replace_source"],
          ["需要补拍或补素材", "bridge"], ["改成别的表达", "rewrite"], ["删除这一镜", "omit"],
        ];
        choices.forEach(([label, resolution]) => actions.append(researchAction(label, {
          op: "resolve_matrix_row", matrix_row_id: row.id, resolution,
          source_media_id: row.source_media_id || null, note: label,
        }, onOperation)));
        item.append(actions);
      }
      list.append(item);
    });
    matchingPanel.append(list);
  }
  if (data.directions?.length) {
    directionPanel.append(node("h3", "section-title", "可选方向"));
    data.directions.forEach((direction) => {
      const item = node("article", "content-row research-direction");
      item.append(node("h4", "row-title", direction.title));
      item.append(node("p", "row-copy", direction.promise));
      if (direction.keep?.length) item.append(node("h5", "detail-heading", "建议保留"), tagList(direction.keep));
      if (direction.change?.length) item.append(node("h5", "detail-heading", "换成自己的表达"), tagList(direction.change));
      if (direction.avoid?.length) item.append(node("h5", "detail-heading", "不要照搬"), tagList(direction.avoid));
      if (editable) {
        const actions = node("div", "inline-edit-actions");
        actions.append(researchAction("保留这个方向", {op: "set_direction_preference", direction_id: direction.id, preference: "prefer", rationale: "制作人员选择"}, onOperation, "primary-button"));
        actions.append(researchAction("暂不采用", {op: "set_direction_preference", direction_id: direction.id, preference: "avoid", rationale: "制作人员暂不采用"}, onOperation));
        item.append(actions);
      }
      directionPanel.append(item);
    });
  }
  if (data.quality) {
    const section = node("section", "content-row research-quality");
    section.append(node("h3", "section-title", "研究检查结果"));
    section.append(detailRow("当前结果", data.quality.status));
    if (data.quality.score != null && data.quality.max_score != null) section.append(detailRow("检查得分", `${data.quality.score}/${data.quality.max_score}`));
    (data.quality.checks || []).forEach((check) => section.append(detailRow(check.label, `${check.status} · ${check.message}`)));
    qualityPanel.append(section);
  }
  renderProposalHandoff(qualityPanel, data);
}

function renderControlPlan(container, plan, { editable = false, onOperation = () => {} } = {}) {
  const section = node("section", `control-plan ${plan.status === "approved" ? "is-approved" : ""}`);
  const heading = node("div", "control-plan-heading");
  heading.append(node("div", "eyebrow", "导演总控单"), node("h3", "section-title", plan.status === "approved" ? "已锁定，后面的口播和分镜按这份执行" : "先把整条片的做法定下来"));
  heading.append(node("p", "editor-help", "这不是口播稿，而是整条片共同遵守的五条制作约定。"));
  section.append(heading);
  (plan.sections || []).forEach((item) => {
    const card = node("article", `control-plan-section ${item.review === "approved" ? "is-approved" : item.review === "needs_adjustment" ? "needs-adjustment" : ""}`);
    const title = node("div", "control-plan-section-title");
    title.append(node("h4", "row-title", item.label));
    title.append(node("span", "status-chip", item.review === "approved" ? "已确认" : item.review === "needs_adjustment" ? "需要调整" : "待确认"));
    card.append(title, node("p", "row-copy", item.summary || "Agent 正在整理这一部分"));
    if (item.rules?.length) { card.append(node("h5", "detail-heading", "制作时照着做"), tagList(item.rules, "control-rule-list")); }
    if (item.industry_notes?.length) { card.append(node("h5", "detail-heading", "行业提醒"), tagList(item.industry_notes, "control-note-list")); }
    if (item.feedback) card.append(node("p", "control-feedback", `上次意见：${item.feedback}`));
    if (editable && plan.status !== "approved") {
      const actions = node("div", "control-plan-actions");
      const approve = node("button", "quiet-button", "这部分没问题"); approve.type = "button";
      approve.addEventListener("click", () => {
        item.review = "approved"; card.classList.add("is-approved"); card.classList.remove("needs-adjustment");
        onOperation({ op: "review_control_section", section_id: item.id, decision: "approved", feedback: "" });
        lock.disabled = (plan.sections || []).some((entry) => entry.review !== "approved");
      });
      const adjust = node("button", "quiet-button", "需要调整"); adjust.type = "button";
      adjust.addEventListener("click", () => {
        const feedback = window.prompt("告诉 Agent 需要怎么调整（例如：节奏更快、不要承诺没有证据的功能）", item.feedback || "");
        if (feedback != null && feedback.trim()) {
          item.review = "needs_adjustment"; item.feedback = feedback.trim(); card.classList.add("needs-adjustment"); card.classList.remove("is-approved");
          onOperation({ op: "review_control_section", section_id: item.id, decision: "needs_adjustment", feedback: feedback.trim() });
          lock.disabled = true;
        }
      });
      actions.append(approve, adjust); card.append(actions);
    }
    section.append(card);
  });
  if (editable && plan.status !== "approved") {
    const lock = node("button", "primary-button", "五部分都确认，锁定导演总控单"); lock.type = "button";
    lock.disabled = !(plan.sections || []).length || (plan.sections || []).some((item) => item.review !== "approved");
    lock.addEventListener("click", () => onOperation({ op: "approve_control_plan" }));
    section.append(lock);
  }
  if (plan.status === "approved") {
    const handoff = node("section", "control-plan-handoff");
    handoff.append(node("h4", "detail-heading", "下一步：生成制作剧本"));
    handoff.append(node("p", "row-copy", "导演总控单已锁定。接下来由 Agent 根据这份合同生成口播、字幕、段落节奏和镜头意图。"));
    const command = `继续 ${projectId}，读取已锁定的导演总控单并生成制作剧本`;
    const box = node("div", "agent-command");
    box.append(node("code", "", command));
    const copy = node("button", "primary-button", "复制给 Code Agent"); copy.type = "button";
    copy.addEventListener("click", async () => { try { await navigator.clipboard.writeText(command); copy.textContent = "已复制"; } catch { copy.textContent = "请手动复制上面的指令"; } });
    box.append(copy); handoff.append(box); section.append(handoff);
  }
  container.append(section);
}

function renderProposal(container, data, { editable = false, onOperation = () => {} } = {}) {
  if (!data.concepts?.length) return renderEmpty(container);
  if (data.estimated_cost_usd != null) container.append(detailRow("预计制作成本", `$${Number(data.estimated_cost_usd).toFixed(2)}`));
  data.concepts.forEach((concept) => {
    const item = document.createElement("details"); item.className = `content-row concept-row${concept.id === data.selected_id ? " is-selected" : ""}`; item.open = concept.id === data.selected_id;
    const summary = document.createElement("summary");
    const summaryBody = node("div", "concept-summary");
    const title = node("h3", "row-title", concept.title || "创意方向");
    if (concept.id === data.selected_id) title.append(node("span", "selected-mark", "当前方案"));
    summaryBody.append(title, node("p", "row-copy", concept.hook || "暂未提供开头文案")); summary.append(summaryBody, node("span", "row-meta", formatDuration(concept.duration_seconds)));
    const details = node("div", "concept-details");
    details.append(detailRow("核心信息", concept.core_message), detailRow("目标受众", concept.target_audience), detailRow("语气", concept.tone), detailRow("叙事结构", concept.narrative_structure));
    details.append(node("h4", "detail-heading", "视觉方法"), node("p", "row-copy", concept.visual_approach || "暂未提供"));
    details.append(node("h4", "detail-heading", "为什么有效"), node("p", "row-copy", concept.why_this_works || "暂未提供"));
    if (concept.key_points?.length) details.append(node("h4", "detail-heading", "关键信息"), tagList(concept.key_points));
    if (concept.cta) details.append(detailRow("行动引导", concept.cta));
    item.append(summary, details);
    container.append(item);
  });
  if (data.control_plan) renderControlPlan(container, data.control_plan, { editable, onOperation });
  else {
    const waiting = node("section", "control-plan waiting");
    waiting.append(node("h3", "section-title", data.selected_id ? "下一步：生成导演总控单" : "先选一个创意方向"));
    waiting.append(node("p", "row-copy", data.selected_id ? "方向选定后，Agent 会把五类一致性规则整理成一份可确认的导演总控单。" : "选定方向后，才会生成整条片共同遵守的做法。"));
    container.append(waiting);
  }
}

function renderScript(container, data, { editable, onOperation }) {
  container.append(detailRow("预计成片时长", formatDuration(data.duration_seconds)));
  if (data.script_version) container.append(detailRow("制作剧本版本", `第 ${data.script_version} 版`));
  if (!data.sections?.length) return renderEmpty(container);
  data.sections.forEach((section) => {
    const item = node("article", `content-row script-row${section.review === "approved" ? " is-approved" : section.review === "needs_adjustment" ? " needs-adjustment" : ""}`);
    const heading = node("div", "script-row-heading");
    const title = node("div", "script-row-title");
    title.append(node("span", "row-meta", formatTimeRange(section.start_seconds, section.end_seconds)));
    title.append(node("h3", "row-title", section.label));
    heading.append(title);
    const copy = node("p", "row-copy script-copy", section.text);
    if (editable) {
      const edit = node("button", "inline-edit-button", "编辑");
      edit.type = "button";
      edit.setAttribute("aria-label", `编辑这段剧本：${section.label}`);
      edit.addEventListener("click", () => {
        const form = node("div", "script-inline-editor");
        const input = document.createElement("textarea");
        input.rows = 3;
        input.value = copy.textContent || "";
        input.setAttribute("aria-label", `${section.label} 剧本文案`);
        const actions = node("div", "inline-edit-actions");
        const cancel = node("button", "quiet-button", "取消"); cancel.type = "button";
        const save = node("button", "primary-button", "保存修改"); save.type = "button";
        cancel.addEventListener("click", () => { form.remove(); copy.hidden = false; edit.disabled = false; });
        save.addEventListener("click", () => {
          const text = input.value.trim();
          if (!text) { input.focus(); return; }
          copy.textContent = text;
          onOperation({ op: "replace_section_narration", section_id: section.id, text });
          form.remove(); copy.hidden = false; edit.disabled = false;
        });
        actions.append(cancel, save); form.append(input, actions);
        copy.hidden = true; edit.disabled = true; item.append(form); input.focus();
      });
      heading.append(edit);
    }
    item.append(heading, copy);
    if (section.section_goal) item.append(detailRow("这一段要让观众明白什么", section.section_goal));
    if (section.screen_copy) item.append(detailRow("屏幕上强调什么", section.screen_copy));
    if (section.pacing) item.append(detailRow("时间和节奏", section.pacing));
    if (section.visual_intent) item.append(detailRow("画面要完成什么", section.visual_intent));
    if (section.evidence_requirements?.length) item.append(detailRow("哪些内容必须真实证明", section.evidence_requirements.join("；")));
    if (section.director_rules?.length) item.append(detailRow("本段遵守的导演规则", section.director_rules.join("；")));
    if (section.feedback) item.append(node("p", "control-feedback", `调整意见：${section.feedback}`));
    if (editable && data.status !== "approved") {
      const actions = node("div", "control-plan-actions");
      const approve = node("button", "quiet-button", "这段可以"); approve.type = "button";
      approve.addEventListener("click", () => onOperation({ op: "review_script_section", section_id: section.id, decision: "approved", feedback: "" }));
      const adjust = node("button", "quiet-button", "这段要调整"); adjust.type = "button";
      adjust.addEventListener("click", () => {
        const feedback = window.prompt("告诉 Agent 这段要怎么调整", section.feedback || "");
        if (feedback?.trim()) onOperation({ op: "review_script_section", section_id: section.id, decision: "needs_adjustment", feedback: feedback.trim() });
      });
      actions.append(approve, adjust); item.append(actions);
    }
    container.append(item);
  });
  if (editable && data.status !== "approved") {
    const lock = node("button", "primary-button", "全部段落确认，锁定制作剧本"); lock.type = "button";
    lock.disabled = data.sections.some((section) => section.review !== "approved");
    lock.addEventListener("click", () => onOperation({ op: "approve_production_script" }));
    container.append(lock);
  }
  if (data.status === "approved") {
    const handoff = node("section", "control-plan-handoff");
    handoff.append(node("h4", "detail-heading", "制作剧本已锁定"));
    handoff.append(node("p", "row-copy", "下一步可以按已确认的段落任务和证据要求生成分镜。"));
    container.append(handoff);
  }
}

function renderReferenceEvidence(parent, evidence, index) {
  const panel = node("section", "evidence-panel reference-evidence-panel");
  panel.append(node("h4", "evidence-label", "参考视频怎么拍"));
  const mode = evidence?.mode || "none";
  if (mode === "direct_segment" && evidence.preview_url) {
    const preview = rangedVideo({
      preview_url: evidence.preview_url,
      poster_url: evidence.poster_url,
      source_in_seconds: evidence.start_seconds,
      source_out_seconds: evidence.end_seconds,
    }, "shot-evidence-preview", `镜头 ${index + 1} 参考片段`);
    if (preview) panel.append(preview);
    panel.append(detailRow("参考段落", evidence.description || evidence.reference_scene_id || "已关联"));
    panel.append(detailRow("参考区间", formatTimeRange(evidence.start_seconds, evidence.end_seconds)));
  } else if (mode === "structural_only") {
    panel.append(node("span", "status-chip", "结构对应"));
    panel.append(detailRow("参考视频做法", evidence.mechanism || "已提取整体做法"));
    panel.append(node("p", "empty-copy", "无直接参考片段，不按顺序猜测对应关系"));
  } else {
    panel.append(node("span", "status-chip", "尚未建立对应"));
    panel.append(node("p", "empty-copy", "暂无可靠的参考片段或结构机制证据"));
  }
  parent.append(panel);
}

function renderShots(container, data) {
  if (data.reference_basis) {
    const basis = node("section", "mapping-foundation");
    basis.append(node("h3", "section-title", "这份分镜怎么来的"));
    if (data.reference_basis.summary) basis.append(node("p", "row-copy", data.reference_basis.summary));
    basis.append(detailRow("参考视频的证明方式", data.reference_basis.proof_method));
    if (data.reference_basis.avg_evidence_seconds != null) basis.append(detailRow("参考视频节奏", `平均 ${Number(data.reference_basis.avg_evidence_seconds).toFixed(1)} 秒一个证据`));
    if (data.reference_basis.beat_order?.length) basis.append(node("h4", "detail-heading", "参考视频的段落顺序"), tagList(data.reference_basis.beat_order, "tag-list reference-beats"));
    container.append(basis);
  }
  container.append(detailRow("预计成片时长", formatDuration(data.duration_seconds)));
  if (!data.shots?.length) return renderEmpty(container);
  data.shots.forEach((shot, index) => {
    const item = node("article", "content-row shot-row");
    const header = node("div", "shot-header");
    const heading = node("div", "shot-heading");
    heading.append(node("span", "shot-number", String(index + 1).padStart(2, "0")));
    heading.append(node("h3", "row-title", shot.beat || "镜头内容"));
    header.append(heading, node("span", "row-meta", formatTimeRange(shot.timeline_in_seconds, shot.timeline_out_seconds)));
    item.append(header);
    if (shot.screen_copy) item.append(node("p", "row-copy shot-copy", shot.screen_copy));
    if (shot.intent) item.append(detailRow("这一镜要表达什么", shot.intent));

    const evidenceGrid = node("div", "shot-evidence-grid");
    renderReferenceEvidence(evidenceGrid, shot.reference_evidence, index);
    const ownedPanel = node("section", "evidence-panel owned-evidence-panel");
    ownedPanel.append(node("h4", "evidence-label", "这条分镜用哪条素材"));
    const video = rangedVideo(shot, "shot-evidence-preview", `镜头 ${index + 1} 自有素材预览`); if (video) ownedPanel.append(video);
    ownedPanel.append(detailRow("素材", shot.source_label || "素材待定"));
    ownedPanel.append(detailRow("从素材取哪一段", shot.source_in_seconds == null || shot.source_out_seconds == null ? "尚未选择区间" : formatTimeRange(shot.source_in_seconds, shot.source_out_seconds)));
    if (shot.source_summary) ownedPanel.append(detailRow("这段素材拍了什么", shot.source_summary));
    if (shot.source_usable_for?.length) ownedPanel.append(detailRow("它能证明什么", shot.source_usable_for.join("、")));
    evidenceGrid.append(ownedPanel);
    item.append(evidenceGrid);

    const rationale = node("div", "mapping-rationale");
    rationale.append(node("h4", "detail-heading", "为什么这样安排"));
    if (shot.reference_evidence?.rationale) rationale.append(detailRow("参考视频与本镜头的关系", shot.reference_evidence.rationale));
    rationale.append(node("p", "row-copy", shot.mapping_reason || "暂未记录更详细的安排理由"));
    item.append(rationale);
    const language = [shot.framing, shot.movement, shot.narrative_role].filter(Boolean); if (language.length) item.append(node("p", "source-facts", language.join(" · ")));
    container.append(item);
  });
}

function renderAssets(container, data, { editable = false, onOperation = () => {}, onNavigate = () => {} } = {}) {
  const execution = data.execution_plan;
  if (execution) {
    const plan = node("section", "shot-execution-plan");
    const stateText = execution.locked ? "已锁定" : "待确认";
    plan.append(node("h3", "section-title", "镜头执行单"), detailRow("当前版本", `第 ${execution.plan_version} 版 · ${stateText}`));
    const rail = node("div", "shot-execution-rail");
    (execution.shots || []).forEach((shot) => {
      const card = node("article", "shot-execution-card");
      const heading = node("div", "shot-header");
      heading.append(node("strong", "shot-number", String(shot.order).padStart(2, "0")), node("h4", "row-title", shot.purpose || "镜头任务"));
      card.append(heading, detailRow("时长", formatDuration(shot.duration_seconds)));
      if (shot.narration) card.append(detailRow("口播", shot.narration));
      if (shot.screen_copy) card.append(detailRow("字幕", shot.screen_copy));
      card.append(detailRow("画面动作", shot.subject_action), detailRow("拍摄方式", [shot.setting, shot.framing, shot.camera].filter(Boolean).join(" · ")));
      if (shot.source_label) {
        card.append(detailRow("使用素材", shot.source_label));
        card.append(detailRow("已选片段", shot.source_in_seconds == null || shot.source_out_seconds == null ? "待确认" : formatTimeRange(shot.source_in_seconds, shot.source_out_seconds)));
        card.append(node("span", `status-chip${shot.source_coverage === "需要调整" ? " is-warning" : ""}`, shot.source_coverage || "素材待核对"));
        card.append(node("p", "source-facts", shot.source_reason));
        const adjustSource = node("button", "quiet-button", "调整素材片段"); adjustSource.type = "button";
        adjustSource.addEventListener("click", () => onNavigate());
        card.append(adjustSource);
      }
      else card.append(node("p", "asset-warning", shot.gap_class === "evidential" ? "缺少真实证据素材" : "缺少表达性素材"));
      if (shot.generation_proposals?.length) {
        shot.generation_proposals.forEach((proposal) => {
          const proposalBox = node("section", "generation-proposal");
          proposalBox.append(node("span", "status-chip", "生成演示"));
          proposalBox.append(detailRow("生成方式", `${proposal.model_family} · ${proposal.operation}`));
          proposalBox.append(detailRow("预览费用", proposal.estimated_fast_cost_usd == null ? "待检测" : `$${Number(proposal.estimated_fast_cost_usd).toFixed(2)}`));
          proposalBox.append(node("p", "source-risk", proposal.evidence_risk));
          const generate = node("button", "primary-button", "生成预览"); generate.type = "button";
          generate.disabled = !execution.locked;
          generate.title = execution.locked ? "查看费用并发起生成" : "执行单锁定后才能生成";
          generate.addEventListener("click", async () => {
            try {
              generate.disabled = true; generate.textContent = "正在检查费用";
              const quote = await quoteShotGeneration(projectId, {
                shot_id: shot.id, proposal_id: proposal.id, quality: "fast",
              });
              const confirmed = window.confirm(
                `供应方：${quote.provider}\n模型：${quote.model}\n档位：${quote.variant}\n时长：${quote.duration_seconds} 秒 · ${quote.resolution}\n预计费用：$${Number(quote.estimated_cost_usd).toFixed(2)}\n剩余预算：$${Number(quote.remaining_budget_usd).toFixed(2)}\n风险：${quote.evidence_risk}\n\n确认生成预览吗？`
              );
              if (!confirmed) { generate.disabled = false; generate.textContent = "生成预览"; return; }
              const task = await createShotGeneration(projectId, {
                shot_id: shot.id,
                proposal_id: proposal.id,
                plan_version: quote.plan_version,
                quality: "fast",
                confirmed_estimated_cost_usd: quote.estimated_cost_usd,
              });
              generate.textContent = task.status === "completed" ? "预览已生成" : "已开始生成";
              await refresh();
            } catch (error) {
              generate.disabled = false; generate.textContent = error.message || "生成预览";
            }
          });
          proposalBox.append(generate);
          const relatedTasks = (execution.generation_tasks || []).filter((task) => task.shot_id === shot.id && task.proposal_id === proposal.id);
          relatedTasks.forEach((task) => {
            const taskRow = node("section", "generation-task");
            const label = task.status === "completed" ? "已完成" : task.status === "needs_confirmation" ? "需要确认" : task.status === "failed" ? "生成失败" : task.status === "generating" ? "生成中" : "排队中";
            taskRow.append(node("span", "status-chip", label));
            if (task.output_url) {
              const video = document.createElement("video");
              video.controls = true; video.playsInline = true; video.preload = "metadata"; video.src = task.output_url;
              video.className = "generated-shot-preview"; taskRow.append(video);
            }
            if (task.error) taskRow.append(node("p", "source-risk", task.error));
            proposalBox.append(taskRow);
          });
          const fastTask = [...relatedTasks].reverse().find((task) => task.quality === "fast" && task.status === "completed");
          const standardTask = [...relatedTasks].reverse().find((task) => task.quality === "standard" && task.status === "completed");
          if (fastTask && !standardTask) {
            const standard = node("button", "quiet-button", "方向可用，生成清晰版"); standard.type = "button";
            standard.addEventListener("click", async () => {
              try {
                standard.disabled = true; standard.textContent = "正在检查费用";
                const quote = await quoteShotGeneration(projectId, { shot_id: shot.id, proposal_id: proposal.id, quality: "standard", parent_task_id: fastTask.task_id });
                const confirmed = window.confirm(`供应方：${quote.provider}\n模型：${quote.model}\n档位：${quote.variant}\n时长：${quote.duration_seconds} 秒 · ${quote.resolution}\n预计费用：$${Number(quote.estimated_cost_usd).toFixed(2)}\n剩余预算：$${Number(quote.remaining_budget_usd).toFixed(2)}\n风险：${quote.evidence_risk}\n\n确认生成清晰版吗？`);
                if (!confirmed) { standard.disabled = false; standard.textContent = "方向可用，生成清晰版"; return; }
                await createShotGeneration(projectId, { shot_id: shot.id, proposal_id: proposal.id, plan_version: quote.plan_version, quality: "standard", parent_task_id: fastTask.task_id, confirmed_estimated_cost_usd: quote.estimated_cost_usd });
                standard.textContent = "已开始生成清晰版"; await refresh();
              } catch (error) { standard.disabled = false; standard.textContent = error.message || "生成清晰版"; }
            });
            proposalBox.append(standard);
          }
          if (standardTask) {
            const adopt = node("button", "quiet-button", shot.selected_generation_task_id === standardTask.task_id ? "当前已用于本镜头" : "用于本镜头"); adopt.type = "button";
            adopt.disabled = shot.selected_generation_task_id === standardTask.task_id;
            adopt.addEventListener("click", async () => {
              try { adopt.disabled = true; await adoptShotGeneration(projectId, standardTask.task_id); adopt.textContent = "当前已用于本镜头"; await refresh(); }
              catch (error) { adopt.disabled = false; adopt.textContent = error.message || "用于本镜头"; }
            });
            proposalBox.append(adopt);
          }
          card.append(proposalBox);
        });
      }
      rail.append(card);
    });
    plan.append(rail);
    if (editable && !execution.locked) {
      const lock = node("button", "primary-button", "锁定镜头执行单并查看影响"); lock.type = "button";
      lock.disabled = (execution.shots || []).some((shot) => shot.coverage_status === "gap" && shot.gap_strategy === "none");
      lock.addEventListener("click", () => onOperation({ op: "approve_shot_execution_plan" }));
      plan.append(lock);
      plan.append(node("p", "editor-help", "点击后会自动展示影响；确认提交后，制作准备才会完成并交接给 Code Agent。"));
    }
    if (execution.handoff_ready) {
      const handoff = node("section", "control-plan-handoff");
      handoff.append(node("h4", "detail-heading", "制作准备已完成"));
      handoff.append(node("p", "row-copy", "镜头执行单已锁定。请切换到 Code Agent，按这份执行单生成样片。"));
      const command = `继续 ${projectId}，读取已锁定的镜头执行单并生成样片`;
      const box = node("div", "agent-command");
      box.append(node("code", "", command));
      const copy = node("button", "primary-button", "复制给 Code Agent"); copy.type = "button";
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(command); copy.textContent = "已复制"; }
        catch { copy.textContent = "请手动复制上面的指令"; }
      });
      box.append(copy); handoff.append(box); plan.append(handoff);
    }
    container.append(plan);
  }
  const planned = Number(data.planned_count || 0);
  const prepared = Number(data.prepared_count || 0);
  const waiting = Number(data.waiting_confirmation_count || 0);
  const proxyItems = (data.items || []).filter((item) => item.type === "video_proxy");
  const proxyPrepared = proxyItems.filter((item) => item.status === "已准备").length;
  const proxyWaiting = proxyItems.filter((item) => item.status === "等待确认").length;
  const progress = node("section", "asset-progress");
  progress.append(node("h3", "section-title", "制作就绪"));
  progress.append(node("p", "lead-copy", planned ? `制作方案已锁定，${prepared} / ${planned} 项准备工作已完成` : "制作方案尚未锁定"));
  if (proxyItems.length) {
    const proxyStatus = proxyWaiting
      ? `${proxyWaiting} 条等待确认`
      : proxyPrepared === proxyItems.length
        ? "已就绪"
        : `${proxyItems.length - proxyPrepared} 条待系统处理`;
    progress.append(detailRow("源素材准备", `${proxyItems.length} 条 · ${proxyStatus}`));
  }
  if (waiting) progress.append(node("p", "asset-warning", `${waiting} 项涉及付费生成，等待确认后才会调用模型`));
  if (data.paid_generation_approved === false) progress.append(node("p", "editor-help", "当前未批准付费生成；免费代理和已有素材不受影响。"));
  progress.append(node("p", "editor-help", "镜头内容、素材片段和镜头顺序请看第四步“分镜”；这里仅显示是否具备进入样片的条件。"));
  container.append(progress);

  container.append(detailRow("口播", data.narration_status));
  container.append(detailRow("字幕", data.subtitle_status));
  container.append(detailRow("背景音乐", data.music_status));
  const cost = data.estimated_cost_usd == null ? "暂未提供" : `$${Number(data.estimated_cost_usd).toFixed(2)}`;
  container.append(detailRow("已记录费用", cost));

}

function renderSample(container, data, { project } = {}) {
  const canReview = (project?.permissions || []).includes("review");
  const workbench = node("div", "sample-review-workbench");
  const playerPanel = node("section", "sample-player-panel");
  playerPanel.append(detailRow("检查结果", data.qa_status));
  playerPanel.append(detailRow("样片时长", formatDuration(data.duration_seconds)));
  playerPanel.append(node("p", "lead-copy", data.review_summary));
  if (data.preview_url) {
    const video = document.createElement("video");
    video.className = "preview-video";
    video.controls = true;
    video.playsInline = true;
    video.src = data.preview_url;
    video.setAttribute("aria-label", "样片预览");
    playerPanel.append(video);
  }
  workbench.append(playerPanel);

  // 评审缺口 #4：样片评价卡 + 三轨音频（口播/BGM/原声）
  if (data.evaluation) {
    const evalPanel = node("section", "sample-evaluation");
    evalPanel.append(node("h3", "section-title", "样片评价卡"));
    evalPanel.append(renderEvaluationCard(data.evaluation));
    workbench.append(evalPanel);
  }
  const tracks = data.audio_tracks;
  if (tracks && tracks.length) {
    const audioPanel = node("section", "sample-audio-tracks");
    audioPanel.append(node("h3", "section-title", "音频轨"));
    const stateLabels = { present: "已就位", missing: "缺失", not_planned: "未计划" };
    const trackList = node("div", "sample-audio-track-list");
    tracks.forEach((track) => {
      const chip = node("span", `sample-audio-track state-${track.state || "not_planned"}`);
      chip.append(node("strong", "", track.label || track.kind));
      chip.append(node("span", "track-state", stateLabels[track.state] || track.state || "未知"));
      if (track.planned && track.state === "missing") chip.append(node("span", "track-warn", "计划了但样片没有实际音轨"));
      trackList.append(chip);
    });
    audioPanel.append(trackList);
    workbench.append(audioPanel);
  }

  const trace = data.execution_trace;
  const tracePanel = node("section", "sample-execution-trace");
  tracePanel.append(node("h3", "section-title", "执行对照"));
  if (!trace) {
    tracePanel.append(node("p", "editor-help", "暂无执行对照，当前只能查看样片结果。"));
  } else {
    const summary = trace.summary || {};
    const counts = summary.status_counts || {};
    const summaryText = `本次样片覆盖 ${summary.included_shot_count || 0}/${summary.planned_shot_count || 0} 个镜头 · 按方案执行 ${counts.executed || 0} 个 · 部分执行 ${counts.partial || 0} 个 · 新增内容 ${counts.added || 0} 个 · 尚未进入样片 ${counts.not_in_sample || 0} 个`;
    tracePanel.append(node("p", "trace-summary", summaryText));
    const list = node("div", "sample-trace-list");
    (trace.shots || []).forEach((shot) => {
      const card = node("article", `sample-trace-card status-${shot.status || "unknown"}`);
      const heading = node("div", "sample-trace-heading");
      heading.append(node("strong", "sample-trace-shot", shot.shot_id || "镜头"));
      heading.append(node("span", "status-chip", shot.status_label || "待核对"));
      card.append(heading);
      const planned = shot.planned || {};
      const planText = [planned.purpose, planned.subject_action, planned.screen_copy].filter(Boolean).join(" · ");
      if (planText) card.append(node("p", "sample-trace-copy", `计划：${planText}`));
      if (planned.reference_rules?.length) card.append(node("p", "sample-trace-copy", `参考规则：${planned.reference_rules.join("、")}`));
      const actual = shot.actual;
      if (actual) {
        const actualText = [actual.source_label && `素材：${actual.source_label}`, actual.screen_copy && `画面文字：${actual.screen_copy}`].filter(Boolean).join(" · ");
        if (actualText) card.append(node("p", "sample-trace-copy", `实际：${actualText}`));
      }
      if (shot.deviation?.reason) card.append(node("p", "sample-trace-deviation", shot.deviation.reason));
      if (shot.sample_window && !shot.sample_window.included) card.append(node("p", "sample-trace-muted", "这个镜头尚未进入本次样片窗口"));
      list.append(card);
    });
    tracePanel.append(list);
  }
  workbench.append(tracePanel);
  const effectPanel = node("section", "sample-effect-confirmation");
  effectPanel.append(node("h3", "section-title", "样片效果确认"));
  effectPanel.append(node("p", "editor-help", "先确认这五件事，确认后才会进入下一步。"));
  const checks = [
    ["creative_direction", "创意方向", "还是在讲已经确定的核心卖点吗？"],
    ["hook", "开头钩子", "前 1–3 秒能让人知道发生了什么并愿意继续看吗？"],
    ["proof", "核心证明", "产品、动作和结果是否看得清楚、说得明白？"],
    ["pacing", "节奏与画面切换", "镜头是否顺畅，没有拖沓、跳跃或重复？"],
    ["readability", "字幕与画面可读性", "字幕、产品和重点信息是否清楚且不互相遮挡？"],
  ];
  const selections = {};
  const cards = node("div", "sample-effect-list");
  const submit = node("button", "primary-button", "确认样片并进入下一步");
  submit.type = "button"; submit.disabled = !canReview;
  const message = node("p", "editor-message");
  const updateSubmit = () => {
    const complete = checks.every(([key]) => selections[key]);
    const allPass = checks.every(([key]) => selections[key] === "pass");
    submit.disabled = !canReview || !complete;
    submit.textContent = allPass ? "确认样片并进入下一步" : "提交调整意见";
    message.textContent = !canReview ? "审批权限已变化，请重新拉取" : complete && !allPass ? "有项目需要调整，暂不能直接进入下一步。" : complete ? "五项效果已确认，可以进入下一步。" : "请完成五项效果确认。";
  };
  if (!canReview) message.textContent = "审批权限已变化，请重新拉取";
  checks.forEach(([key, title, prompt]) => {
    const card = node("div", "sample-effect-card");
    card.append(node("strong", "sample-effect-title", title), node("p", "sample-effect-prompt", prompt));
    const choices = node("div", "sample-effect-choices");
    [["pass", "通过"], ["adjust", "需要调整"], ["redirect", "方向不对"]].forEach(([value, label]) => {
      const button = node("button", "quiet-button", label); button.type = "button";
      button.addEventListener("click", () => {
        selections[key] = value;
        choices.querySelectorAll("button").forEach((item) => item.classList.remove("is-selected"));
        button.classList.add("is-selected"); updateSubmit();
      });
      choices.append(button);
    });
    card.append(choices); cards.append(card);
  });
  submit.addEventListener("click", async () => {
    const review = project?.pending_review;
    if (!review?.review_id || review.subject_hash == null) { message.textContent = "确认信息尚未准备好，请刷新后重试。"; return; }
    submit.disabled = true;
    try {
      const allPass = checks.every(([key]) => selections[key] === "pass");
      const labels = Object.fromEntries(checks.map(([key, title]) => [key, title]));
      const issues = Object.entries(selections).filter(([, value]) => value !== "pass").map(([key, value]) => `${labels[key]}：${value === "redirect" ? "方向不对" : "需要调整"}`);
      const issueTagByKey = { creative_direction: "unclear_promise", hook: "weak_hook", proof: "information_gap", pacing: "timing", readability: "mobile_illegibility" };
      const issueTags = [...new Set(Object.entries(selections).filter(([, value]) => value !== "pass").map(([key]) => issueTagByKey[key]))];
      await decideReview(
        project.project_id, review.review_id, allPass ? "approved" : "rejected",
        allPass ? "样片效果确认通过" : issues.join("；"), selections,
        review.subject_version, review.subject_hash, allPass ? null : issueTags,
      );
      message.textContent = allPass ? "样片已确认，正在进入下一步。" : "调整意见已提交，样片将进入返工。";
      await refresh();
    } catch (error) { message.textContent = error.message; updateSubmit(); }
  });
  effectPanel.append(cards, message, submit);
  workbench.append(effectPanel);
  container.append(workbench);
}

function renderEdit(container, data) {
  if (data.summary) container.append(node("p", "lead-copy", data.summary));
  if (data.preview_url) {
    const heading = node("div", "preview-heading");
    heading.append(node("h3", "section-title", "当前样片（修改前）"));
    heading.append(node("span", "row-meta", formatDuration(data.preview_duration_seconds)));
    container.append(heading);
    const video = document.createElement("video");
    video.className = "preview-video edit-preview-video";
    video.controls = true; video.playsInline = true; video.preload = "metadata"; video.src = data.preview_url;
    video.setAttribute("aria-label", "当前样片预览");
    container.append(video);
  }
  container.append(detailRow("本次修改范围", data.change_scope));
  container.append(detailRow("当前修改意见", data.reasons?.length ? data.reasons.join("；") : "还没有提交修改"));
  container.append(detailRow("已标记影响镜头", `${data.affected_shot_count} 个`));
  if (data.capabilities?.length) {
    container.append(node("h3", "section-title", "这一步可以改什么"));
    const list = node("div", "tag-list edit-capabilities");
    data.capabilities.forEach((item) => list.append(node("span", "tag", item)));
    container.append(list);
  }
  if (data.shots?.length) {
    container.append(node("h3", "section-title", "当前分镜清单"));
    const list = node("div", "edit-shot-summary-list");
    data.shots.forEach((shot, index) => {
      const row = node("div", "edit-shot-summary");
      row.append(node("span", "shot-number", `SC${String(index + 1).padStart(2, "0")}`));
      row.append(node("strong", "edit-shot-summary-title", shot.title));
      row.append(node("span", "row-meta", shot.enabled ? "保留" : "已标记删除"));
      list.append(row);
    });
    container.append(list);
  }
  if (data.reasons?.length) {
    const list = node("ul", "plain-list");
    data.reasons.forEach((reason) => list.append(node("li", "", reason)));
    container.append(list);
  }
}

function renderEvaluationCard(evaluation) {
  if (!evaluation) return null;
  const card = node("section", "delivery-evaluation-card");
  card.append(node("h4", "section-title", "视频检查"),
    node("span", "delivery-eval-meta", "系统自动检查"));
  const statusText = evaluation.status === "pass" ? "检查通过" : evaluation.status === "fail" ? "有必须修复的问题" : "有需要处理的问题";
  const statusColor = evaluation.status === "pass" ? "#1f9d55" : evaluation.status === "fail" ? "#c53030" : "#b7791f";
  const statusEl = node("p", "delivery-eval-status", statusText);
  statusEl.style.color = statusColor;
  card.append(statusEl);
  if (evaluation.hard_gate_fails?.length) {
    card.append(node("p", "delivery-eval-heading", "必须处理"));
    for (const fail of evaluation.hard_gate_fails) {
      card.append(node("p", "delivery-eval-note", `${fail.name}：${fail.message}（${fail.fixable ? "可以修复" : "需要停止处理"}）`));
    }
  }
  if (evaluation.advisory?.scored && evaluation.advisory.dimensions?.length) {
    card.append(node("p", "delivery-eval-heading", "画面观感"));
    card.append(node("p", "delivery-eval-note", evaluation.advisory.summary || ""));
    for (const dim of evaluation.advisory.dimensions) {
      const row = node("div", "delivery-eval-dim");
      const name = node("span", "delivery-eval-dim-name", evaluationDimensionLabel(dim.name));
      const score = node("strong", "delivery-eval-dim-score", String(dim.score ?? "—"));
      score.style.color = dim.score >= 8 ? "#1f9d55" : dim.score >= 6 ? "#b7791f" : "#c53030";
      const note = node("span", "delivery-eval-dim-note", dim.note || "");
      row.append(name, score, note);
      card.append(row);
    }
  } else {
    card.append(node("p", "delivery-eval-note", evaluationSummary(evaluation.advisory?.summary) || "画面观感还没有检查"));
  }
  return card;
}

function renderBatch(container, data, { project } = {}) {
  // 批量页面只展示判断当前视频所需的信息；详细处理记录放在折叠区。
  const workbench = setTestId(node("div", "batch-cockpit"), "batch-workbench");
  const phaseLabels = {
    building: "准备中", sampling: "生成样片", scoring: "检查中",
    selection: "等待选择", editing: "精剪中", publishing: "准备交付",
    completed: "已完成", blocked: "暂时停下",
  };
  const gateLabels = { script: "确认脚本", assets: "确认制作准备", sample: "查看样片" };
  const phaseLabel = phaseLabels[data.phase] || "处理中";
  const candidates = data.candidates || [];
  const labelForCandidate = (id) => candidates.find((candidate) => candidate.candidate_id === id)?.label || "视频";
  const pendingGates = (data.pending_gates || []).filter((gate) => gate.candidates?.length);
  const waitingCount = pendingGates[0]?.candidates?.length || 0;
  const eligibleIds = new Set(data.selection?.eligible_candidate_ids || []);
  const selected = data.selection?.selected_candidate_ids || [];
  // 某些旧批次会把所有候选归约为 completed，但仍未写入精剪选择；
  // 只要没有待确认且存在合格候选，就继续展示选择托盘。
  const selectionAvailable = data.phase === "selection"
    || (!selected.length && eligibleIds.size > 0 && pendingGates.length === 0);
  const displayPhaseLabel = selectionAvailable ? "等待选择" : phaseLabel;
  const overviewReason = pendingGates.length
    ? `有 ${waitingCount} 条视频需要${gateLabels[pendingGates[0].gate] || "确认内容"}，看完后再继续。`
    : selectionAvailable
      ? "视频已经完成检查，请从中选择要进入精剪的版本。"
      : {
        selection: "视频已经完成检查，请从中选择要进入精剪的版本。",
        editing: "已经选好视频，正在进入精剪。",
        publishing: "精剪已经完成，正在准备交付。",
        completed: "这批视频已经全部处理完成。",
        blocked: "当前没有可以继续处理的视频，请先查看需要留意的内容。",
      }[data.phase] || "系统正在准备视频，完成后会在这里提示你。";
  const overview = node("section", "batch-overview-panel");
  const overviewHead = node("div", "batch-overview-head");
  const overviewCopy = node("div", "batch-overview-copy");
  overviewCopy.append(node("p", "batch-overview-kicker", "当前进度"));
  overviewCopy.append(node("h2", "batch-overview-title", displayPhaseLabel));
  overviewCopy.append(node("p", "batch-overview-note", overviewReason));
  overviewHead.append(overviewCopy);
  const overviewStats = node("div", "batch-overview-stats");
  const stat = (label, value, tone = "") => {
    const item = node("div", `batch-overview-stat${tone ? ` ${tone}` : ""}`);
    item.append(node("span", "batch-overview-stat-label", label), node("strong", "batch-overview-stat-value", value));
    return item;
  };
  overviewStats.append(
    stat("视频数量", `${candidates.length} 条`),
    stat("待确认", waitingCount ? `${waitingCount} 条` : "没有"),
    stat("可选进入精剪", `${eligibleIds.size} 条`),
    stat("已选择", selected.length ? `${selected.length} 条` : "没有"),
  );
  overviewHead.append(overviewStats);
  overview.append(overviewHead);
  const progress = node("div", "batch-progress", "");
  (data.rail || []).forEach((item) => {
    const status = selectionAvailable && item.phase === "selection" ? "current" : item.status || "pending";
    const step = node("div", `batch-progress-step is-${status}`);
    step.append(node("span", "batch-progress-dot", ""), node("span", "batch-progress-label", {
      building: "准备", sampling: "样片", scoring: "检查", selection: "选择", editing: "精剪", publishing: "交付",
    }[item.phase] || item.label || "处理中"));
    progress.append(step);
  });
  overview.append(progress);
  const workspaceGrid = node("div", "batch-workspace-grid");
  const galleryColumn = node("section", "batch-gallery-column");
  const decisionRail = node("aside", "batch-decision-rail");
  const decisionDetails = node("div", "batch-decision-details");
  galleryColumn.setAttribute("aria-label", "本批视频");
  decisionRail.setAttribute("aria-label", "当前要做");

  let quickViewLayer = null;
  const quickView = (candidate, trigger) => {
    quickViewLayer?.remove();
    const layer = node("div", "batch-quick-view-layer");
    const backdrop = node("button", "batch-quick-view-backdrop");
    backdrop.type = "button";
    backdrop.setAttribute("aria-label", "关闭快速查看");
    const drawer = setTestId(node("aside", "candidate-quick-view"), "candidate-quick-view");
    const headingId = `quick-view-title-${candidate.candidate_id}`;
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-modal", "true");
    drawer.setAttribute("aria-labelledby", headingId);
    const head = node("div", "batch-quick-view-head");
    const title = node("h3", "section-title", candidate.label || "视频");
    title.id = headingId;
    const close = setTestId(node("button", "batch-quick-view-close", "×"), "close-quick-view");
    close.type = "button";
    close.setAttribute("aria-label", "关闭快速查看");
    head.append(title, close);
    drawer.append(head);
    if (candidate.media?.sample_url) {
      const video = document.createElement("video");
      video.controls = true; video.playsInline = true; video.preload = "metadata";
      video.src = candidate.media.sample_url; video.setAttribute("aria-label", "视频预览");
      drawer.append(video);
    } else {
      drawer.append(node("div", "batch-candidate-preview-empty", "样片还没有生成"));
    }
    drawer.append(node("p", "row-copy", candidateBlockLabel(candidate.selection_block_reason) || "这里用于快速浏览，确认操作请在当前要做中完成。"));
    if (candidate.links?.project_page) {
      const link = node("a", "primary-link", "打开单条复核");
      link.href = batchProjectUrl(candidate.project_id || candidate.candidate_id, data.batch_id || project?.project_id || projectId);
      drawer.append(link);
    }
    const closeDrawer = () => {
      layer.remove();
      quickViewLayer = null;
      trigger?.focus();
    };
    close.addEventListener("click", closeDrawer);
    backdrop.addEventListener("click", closeDrawer);
    layer.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
    layer.append(backdrop, drawer);
    workbench.append(layer);
    quickViewLayer = layer;
    close.focus();
  };

  // 费用与处理提醒放在概览之后，避免抢占当前确认任务的注意力。
  const consistencyLabel = { stable: "数据正常", unstable: "内容刚刚更新", degraded: "部分内容需要留意" };
  const budgetPanel = node("section", "batch-budget");
  budgetPanel.append(node("h3", "section-title", "处理概况"));
  budgetPanel.append(node("p", "batch-phase-reason", consistencyLabel[data.consistency] || "数据正常"));
  const budget = data.budget || {};
  budgetPanel.append(node("p", "batch-budget-line",
    `已用费用 $${(budget.spent_usd ?? 0).toFixed(2)}${budget.max_cost_usd ? `，预算 $${budget.max_cost_usd.toFixed(2)}` : ""} · 同时处理 ${(data.concurrency || {}).active_count ?? 0} 条${budget.over_budget ? " · 已超过预算" : ""}`));
  decisionDetails.append(budgetPanel);

  // 降级/警告
  if ((data.warnings || []).length) {
    const warnPanel = node("section", "batch-warnings");
    warnPanel.append(node("h3", "section-title", "需要留意"));
    const warningCopy = {
      candidate_path_invalid: "视频地址有误",
      candidate_missing: "找不到这条视频的资料",
      candidate_corrupt: "这条视频的资料无法读取",
      budget_mismatch: "费用记录需要核对",
      over_budget: "已超过预算",
    };
    const warningAction = {
      candidate_path_invalid: "请重新添加这条视频",
      candidate_missing: "请重新生成或移出本批",
      candidate_corrupt: "请检查资料后重新拉取",
      budget_mismatch: "请重新拉取最新结果",
      over_budget: "请先确认预算后再继续",
    };
    for (const warning of data.warnings) {
      const warningCandidate = warning.candidate_id
        ? candidates.find((candidate) => candidate.candidate_id === warning.candidate_id)
        : null;
      const warningName = warningCandidate ? `${warningCandidate.label || "这条视频"}：` : "";
      warnPanel.append(node("p", "batch-warning",
        `${warningName}${warningCopy[warning.code] || "这条视频暂时不可用"}。${warningAction[warning.code] || "请重新拉取最新结果"}`));
    }
    decisionDetails.append(warnPanel);
  }

  // 当前确认任务：只展示最早需要处理的一道门，避免让一线人员在多个动作间跳转。
  const gates = (data.pending_gates || []).filter((gate) => gate.candidates?.length).slice(0, 1);
  if (gates.length) {
    const gatePanel = node("section", "batch-gates batch-current-action");
    gatePanel.append(node("p", "batch-current-action-kicker", "当前要做"));
    gatePanel.append(node("h3", "section-title", `${gateLabels[gates[0].gate] || "确认内容"} · ${gates[0].candidates.length} 条视频`));
    gatePanel.append(node("p", "row-copy", "逐条看一眼，确认没问题的勾上；只会通过你勾选的视频。"));
    const reviewKinds = { script: "script_lock", assets: "creative_lock", sample: "sample" };
    for (const gate of gates) {
      const row = node("div", "batch-gate-row");
      const info = node("p", "batch-gate-info",
        `${gateLabels[gate.gate] || gate.label || "确认内容"} · 已选 ${gate.candidates.length}/${gate.candidates.length}`);
      info.setAttribute("aria-live", "polite");
      const approve = node("button", "primary-button", `确认勾选的视频（${gate.candidates.length} 条）`);
      approve.type = "button";
      const included = new Set(gate.candidates.map((entry) => entry.candidate_id));
      const list = node("div", "batch-gate-candidates");
      for (const entry of gate.candidates) {
        const view = (data.candidates || []).find((candidate) => candidate.candidate_id === entry.candidate_id) || {};
        const material = view.gate_material || {};
        const item = node("div", "batch-gate-candidate");
        const header = node("div", "batch-gate-candidate-summary");
        const choice = node("label", "batch-gate-choice");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = true;
        checkbox.setAttribute("aria-label", `选择${view.label || entry.candidate_id}`);
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) included.add(entry.candidate_id);
          else included.delete(entry.candidate_id);
          const count = included.size;
          info.textContent = `${gateLabels[gate.gate] || gate.label || "确认内容"} · 已选 ${count}/${gate.candidates.length}`;
          approve.textContent = count ? `确认勾选的视频（${count} 条）` : "请先勾选视频";
          approve.disabled = count === 0;
        });
        choice.append(checkbox, node("span", "", view.label || entry.candidate_id));
        header.append(choice, node("span", "row-meta", ` ${(view.stage_states || []).map((state) => stageStateLabel(state.stage_id, state.status)).join(" · ")}`));
        item.append(header);
        const materialDetails = node("details", "batch-gate-material");
        materialDetails.append(node("summary", "", "查看确认内容"));
        const body = node("div", "batch-gate-candidate-body");
        const materialSummary = gate.gate === "script"
          ? `制作脚本${material.duration_seconds ? ` · ${material.duration_seconds} 秒` : ""}`
          : gate.gate === "assets"
            ? `生成清单${material.plan_summary?.proxy_shots ? ` · ${material.plan_summary.proxy_shots} 个画面` : ""}`
            : material.output_path
              ? `样片${material.probe?.duration_seconds ? ` · ${material.probe.duration_seconds} 秒` : ""}`
              : "样片还没有生成";
        body.append(node("p", "row-copy", materialSummary));
        if (view.links?.project_page) {
          const pageLink = node("a", "batch-candidate-link", "打开单条复核");
          pageLink.href = view.links.project_page;
          pageLink.target = "_blank";
          body.append(pageLink);
        }
        materialDetails.append(body);
        item.append(materialDetails);
        list.append(item);
      }
      approve.disabled = included.size === 0;
      approve.addEventListener("click", async () => {
        approve.disabled = true;
        const chosen = gate.candidates.filter((entry) => included.has(entry.candidate_id));
        if (!chosen.length) { approve.disabled = false; approve.textContent = "请先勾选视频"; return; }
        const participants = chosen.map((entry) => {
          const view = (data.candidates || []).find((candidate) => candidate.candidate_id === entry.candidate_id) || {};
          const review = (view.pending_reviews || []).find((item) => item.kind === reviewKinds[gate.gate]);
          return {
            candidate_id: entry.candidate_id,
            project_id: entry.project_id,
            review_id: review ? review.review_id : "",
            subject_version: review ? review.subject_version : 0,
            subject_hash: review ? review.subject_hash : "",
            ...(gate.gate === "sample" ? { effect_confirmations: {
              creative_direction: "pass", hook: "pass", proof: "pass", pacing: "pass", readability: "pass",
            } } : {}),
          };
        });
        try {
          await batchApproveGate(project.project_id, data.aggregate_revision, gate.gate, participants, "批量确认当前内容");
          window.location.reload();
        } catch (error) {
          approve.disabled = false;
          if (error.code === "needs_recovery") {
            approve.textContent = "这次操作没有完成，点击继续处理";
            approve.addEventListener("click", async () => {
              await batchRecover(project.project_id, error.details?.batch_action_id);
              window.location.reload();
            }, { once: true });
          } else if (error.code === "stale") {
            approve.textContent = "内容已更新，正在刷新…";
            window.location.reload();
          } else {
            approve.textContent = businessErrorMessage(error);
          }
        }
      });
      row.append(info, list, approve);
      gatePanel.append(row);
    }
    decisionRail.append(gatePanel);
  }

  // 视频对比：默认只露出判断所需的信息，成本和音轨等细节收进“更多信息”。
  const matrix = node("section", "batch-matrix");
  matrix.append(node("h3", "section-title", "本批视频"));
  matrix.append(node("p", "batch-matrix-intro", "先比较每条视频的方向和当前状态，需要深入时再打开单条复核。"));
  const table = node("div", "batch-matrix-table batch-candidate-grid");
  candidates.forEach((candidate, candidateIndex) => {
    const cell = setTestId(node("article", `batch-candidate-card status-${candidate.candidate_phase || candidate.status || "planned"}`), `candidate-card-${candidate.candidate_id}`);
    const mediaFrame = node("div", "batch-candidate-media");
    if (candidate.media?.sample_url) {
      const video = document.createElement("video");
      video.className = "batch-candidate-preview";
      video.controls = true; video.playsInline = true; video.preload = "metadata";
      video.src = candidate.media.sample_url;
      video.setAttribute("aria-label", `${candidate.label || "视频"}样片预览`);
      video.addEventListener("error", () => {
        const error = setTestId(node("p", "batch-media-error", "样片无法播放，请检查文件后重新拉取"), `media-error-${candidate.candidate_id}`);
        mediaFrame.replaceChildren(error);
      }, { once: true });
      mediaFrame.append(video);
    } else {
      mediaFrame.append(node("div", "batch-candidate-preview-empty", "样片还没有生成"));
    }
    cell.append(mediaFrame);
    const heading = node("div", "batch-candidate-heading");
    const candidateLabel = candidate.label || `视频 ${candidateIndex + 1}`;
    heading.append(node("strong", "batch-candidate-label", candidateLabel));
    heading.append(node("span", "status-chip", candidateStatusLabel(candidate.candidate_phase || candidate.status || "planned")));
    cell.append(heading);
    const direction = candidate.direction?.label || candidate.direction?.title || candidate.direction?.name
      || Object.values(candidate.direction || {}).filter(Boolean).slice(0, 2).join(" / ");
    if (direction) cell.append(node("p", "batch-candidate-direction", direction));
    const evaluation = candidate.score?.evaluation;
    const score = Number(candidate.score?.weighted_total);
    const resultLabel = evaluation?.status === "pass"
      ? "检查通过"
      : evaluation?.status === "fail"
        ? "有问题需要处理"
        : evaluation?.status === "revise"
          ? "建议再看一遍"
          : Number.isFinite(score) ? `检查得分 ${score.toFixed(1)}` : "等待检查";
    cell.append(node("p", "batch-candidate-result", resultLabel));
    const evidence = [];
    const evidenceLabels = {
      hook_clarity: "开头清楚", visual_hierarchy: "画面层次", rhythm: "节奏顺畅",
      shot_quality: "画面清楚", story_coherence: "内容连贯", audio_quality: "声音清楚",
      text_readability: "字幕清楚", product_presence: "重点突出",
    };
    (evaluation?.advisory?.dimensions || []).forEach((item) => {
      const key = item.id || String(item.name || "").trim().toLowerCase().replaceAll(" ", "_");
      const label = evidenceLabels[key];
      if (label && evidence.length < 3) evidence.push(label);
    });
    if (evaluation?.status === "pass" && evidence.length < 3) evidence.push("系统检查通过");
    if (evidence.length) cell.append(tagList(evidence, "batch-candidate-evidence"));
    const currentStage = (candidate.stage_states || []).find((state) => state.status === "awaiting_human")
      || (candidate.stage_states || []).find((state) => !["completed", "已完成"].includes(state.status));
    if (currentStage) cell.append(node("p", "batch-candidate-stages", stageStateLabel(currentStage.stage_id, currentStage.status)));
    if (candidate.selection_block_reason) cell.append(node("p", "batch-candidate-block", candidateBlockLabel(candidate.selection_block_reason)));
    if (candidate.links?.project_page) {
      const actions = node("div", "batch-candidate-actions");
      const pageLink = setTestId(node("a", "batch-candidate-link", "打开单条复核"), `open-single-${candidate.candidate_id}`);
      pageLink.href = batchProjectUrl(candidate.project_id || candidate.candidate_id, data.batch_id || project?.project_id || projectId);
      const quick = setTestId(node("button", "batch-candidate-link", "快速查看"), `quick-view-${candidate.candidate_id}`);
      quick.type = "button";
      quick.addEventListener("click", () => quickView(candidate, quick));
      actions.append(quick, pageLink);
      cell.append(actions);
    }
    const more = node("details", "batch-card-details");
    more.append(node("summary", "", "更多信息"));
    more.append(node("p", "batch-candidate-cost", `已用费用 $${(candidate.cost?.cost_usd ?? 0).toFixed(2)} · 处理 ${candidate.cost?.attempts ?? 0} 次`));
    const tracks = candidate.media?.audio_tracks || [];
    if (tracks.length) {
      const trackLabel = { narration: "口播", bgm: "背景音乐", original: "原声" };
      const trackLine = tracks.map((track) => `${trackLabel[track.kind] || track.label || "声音"}：${track.state === "present" ? "已准备" : track.state === "missing" ? "缺少" : "未安排"}`).join(" · ");
      more.append(node("p", "batch-candidate-tracks", trackLine));
    }
    if (candidate.score?.evaluation) more.append(renderEvaluationCard(candidate.score.evaluation));
    if (candidate.failure?.failure) more.append(node("p", "batch-candidate-block", "处理遇到问题，请联系制作人员查看记录"));
    cell.append(more);
    table.append(cell);
  });
  matrix.append(table);
  galleryColumn.append(matrix);

  // 进入精剪的选择托盘：只有完成检查且符合条件的视频才会出现。
  const reports = data.reports || {};
  const selectionDisabled = (reports.disabled_actions || []).includes("select");
  const selectPanel = setTestId(node("section", "batch-select batch-selection-tray"), "batch-selection");
  selectPanel.append(node("p", "batch-selection-kicker", "下一步"));
  selectPanel.append(node("h3", "section-title", "选择要进入精剪的视频"));
  selectPanel.append(node("p", "batch-selection-intro", "最多选 2 条。没有合适的视频时，可以先不选择。"));
  if (selected.length) {
    const selectedLabels = selected.map((id) => labelForCandidate(id));
    selectPanel.append(node("p", "batch-select-done", `已选 ${selected.length} 条：${selectedLabels.join("、")}`));
    if (data.selection?.reason) selectPanel.append(node("p", "batch-selection-reason", `选择原因：${data.selection.reason}`));
  } else if (selectionAvailable) {
    const picks = new Set();
    const checkboxes = node("div", "batch-select-list");
    const count = node("p", "batch-selection-count", "已选 0/2");
    count.setAttribute("aria-live", "polite");
    for (const candidate of candidates) {
      if (!eligibleIds.has(candidate.candidate_id)) continue;
      const label = node("label", "batch-select-item");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.disabled = selectionDisabled;
      checkbox.setAttribute("aria-label", `选择${candidate.label || candidate.candidate_id}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) picks.add(candidate.candidate_id); else picks.delete(candidate.candidate_id);
        if (picks.size > 2) { checkbox.checked = false; picks.delete(candidate.candidate_id); }
        count.textContent = `已选 ${picks.size}/2`;
        submit.disabled = picks.size === 0;
      });
      label.append(checkbox, document.createTextNode(` ${candidate.label || "视频"}`));
      checkboxes.append(label);
    }
    selectPanel.append(count, checkboxes);
    if (!checkboxes.childElementCount) selectPanel.append(node("p", "batch-selection-empty", "目前没有符合条件的视频"));
    const reason = document.createElement("textarea");
    reason.className = "batch-select-reason";
    reason.rows = 2;
    reason.placeholder = "为什么选这几条（可选）";
    reason.disabled = selectionDisabled;
    const submit = node("button", "primary-button", "进入精剪");
    submit.type = "button";
    submit.disabled = !selectionDisabled && !checkboxes.childElementCount;
    if (selectionDisabled) submit.textContent = "重新拉取最新结果";
    setTestId(submit, "batch-primary-action");
    submit.addEventListener("click", async () => {
      if (selectionDisabled) { window.location.reload(); return; }
      const ids = [...picks];
      if (!ids.length || ids.length > 2) { submit.textContent = "请选 1–2 条视频"; return; }
      const participants = ids.map((id) => {
        const candidate = candidates.find((item) => item.candidate_id === id) || {};
        return {
          candidate_id: id,
          project_id: candidate.project_id || id,
          subject_hash: candidate.subject_hash,
          workflow_revision: candidate.workflow_revision,
          evaluation_hash: candidate.evaluation_hash,
        };
      });
      if (participants.some((item) => !item.subject_hash || !item.evaluation_hash || item.workflow_revision == null)) {
        submit.textContent = "视频检查还没完成，请重新拉取";
        return;
      }
      submit.disabled = true;
      try {
        await batchSelectForEdit(project.project_id, data.aggregate_revision, participants, reason.value || "人工选择");
        window.location.reload();
      } catch (error) {
        submit.disabled = false;
        submit.textContent = businessErrorMessage(error);
      }
    });
    selectPanel.append(reason, submit);
  }
  if (selectionAvailable && !selected.length && !(data.selection?.eligible_candidate_ids || []).length) {
    selectPanel.append(setTestId(node("p", "batch-issue-summary", "本批没有可用视频"), "batch-issue-summary"));
  }
  if (!gates.length) {
    if (selectionAvailable || selected.length) decisionRail.append(selectPanel);
    else {
      const waiting = node("section", "batch-waiting-state");
      waiting.append(node("p", "batch-selection-kicker", "当前要做"));
      const waitingCopy = {
        scoring: ["等待视频检查", "检查完成后，这里会出现可以进入精剪的视频。"],
        editing: ["等待精剪", "已选视频会继续处理，完成后页面会自动更新。"],
        publishing: ["等待交付", "交付文件准备好后，页面会自动更新。"],
        completed: ["本批已完成", "这批视频已经处理完成，可以查看下面的处理记录。"],
        blocked: ["先处理异常", "请展开处理信息，查看哪些视频需要制作人员处理。"],
      }[data.phase] || ["等待视频生成", "有内容需要确认时，页面会在这里提示你。"];
      waiting.append(node("h3", "section-title", waitingCopy[0]));
      waiting.append(node("p", "batch-selection-intro", waitingCopy[1]));
      decisionRail.append(waiting);
    }
  }

  // 差异与效率信息是辅助判断，默认折叠，避免与当前确认任务争夺注意力。
  const moreDetails = node("details", "batch-more-details");
  moreDetails.append(node("summary", "", "查看批次检查"));
  const diversity = data.diversity || {};
  const divSection = node("section", "batch-diversity");
  divSection.append(node("h3", "section-title", "视频之间的区别"));
  if (diversity.mode) {
    const modeLabel = { hard_gate: "必须有明显区别", warning: "仅作提醒", legacy_read_only: "仅供查看" }[diversity.mode] || "仅供查看";
    divSection.append(node("p", "batch-diversity-mode", `检查方式：${modeLabel}`));
  }
  const pairwise = diversity.pairwise || [];
  if (pairwise.length) {
    const rows = node("div", "batch-diversity-rows");
    for (const pair of pairwise) {
      const row = node("div", `batch-diversity-row ${pair.passes ? "pass" : "fail"}`);
      row.append(node("span", "batch-diversity-pair", `${labelForCandidate(pair.candidate_a)} 和 ${labelForCandidate(pair.candidate_b)}`));
      row.append(node("span", "batch-diversity-metrics", `区别 ${pair.changed_dimensions} 处 · 不同镜头 ${pair.structural_shot_count} 个${pair.visual_risk === "high" ? " · 画面风险较高" : ""}`));
      row.append(node("span", "status-chip", pair.passes ? "通过" : "差异不足"));
      rows.append(row);
    }
    divSection.append(rows);
  } else {
    divSection.append(node("p", "batch-diversity-empty", "暂无视频区别记录"));
  }
  if (diversity.plans_missing?.length) {
    divSection.append(node("p", "batch-diversity-missing", `有 ${diversity.plans_missing.length} 条视频缺少区别记录`));
  }
  moreDetails.append(divSection);

  // 批次报告（辅助信息，不作为一线人员的主操作入口）。
  const repSection = node("section", "batch-reports");
  repSection.append(node("h3", "section-title", "处理记录"));
  const repStatus = reports.status || "missing";
  const statusLabel = { complete: "信息完整", partial: "部分信息", degraded: "部分信息异常", missing: "暂未生成" }[repStatus] || "暂不可用";
  repSection.append(node("p", `batch-reports-status state-${repStatus}`, `处理记录：${statusLabel}`));
  const run = reports.run;
  if (run) {
    const cost = run.cost?.total_usd ?? 0;
    const slowest = run.slowest_stage
      ? `${STAGE_STATUS_LABELS[run.slowest_stage.stage_id] || "制作步骤"}（约 ${Math.max(1, Math.round(run.slowest_stage.wall_seconds / 60))} 分钟）`
      : "暂未提供";
    repSection.append(node("p", "batch-reports-summary", `总费用 $${Number(cost).toFixed(2)} · 用时最长的是${slowest}`));
    if (run.data_quality?.warnings?.length) {
      repSection.append(node("p", "batch-reports-warnings", `需要留意：${run.data_quality.warnings.map((w) => w.message).join("、")}`));
    }
  }
  const quality = reports.quality;
  if (quality?.recommendations?.length) {
    const actionLabel = { select: "可以进入精剪", select_for_edit: "可以进入精剪", revise: "需要调整", hold: "先暂停" };
    repSection.append(node("p", "batch-reports-recommendation", `处理建议：${quality.recommendations.map((r) => `${labelForCandidate(r.candidate_id)}：${actionLabel[r.action] || "请查看"}`).join("、")}`));
  }
  if (reports.disabled_actions?.length) {
    repSection.append(node("p", "batch-reports-disabled", "选择功能暂不可用，请重新拉取最新结果"));
  }
  moreDetails.append(repSection);
  if (decisionDetails.childElementCount) {
    const details = node("details", "batch-decision-more");
    details.append(node("summary", "", "查看处理信息"), decisionDetails);
    decisionRail.append(details);
  }
  workspaceGrid.append(galleryColumn, decisionRail);
  workbench.append(overview, workspaceGrid, moreDetails);

  container.append(workbench);
}

function renderDelivery(container, data, { editable = false, onOperation = () => {}, pendingOperations = [] } = {}) {
  const pendingCandidateIds = {};
  const pendingCopyOverrides = new Map();
  pendingOperations.forEach((operation) => {
    if (operation.op === "select_delivery_candidate") pendingCandidateIds[operation.candidate_kind] = operation.candidate_id;
    if (operation.op === "clear_delivery_selection") pendingCandidateIds[operation.kind] = null;
    if (operation.op === "replace_delivery_copy") pendingCopyOverrides.set(operation.section_id, operation);
  });
  const workbench = node("div", "delivery-review-workbench");
  const versions = node("section", "delivery-version-switcher");
  versions.append(node("h3", "section-title", "切换成片版本"));
  const versionButtons = node("div", "delivery-version-buttons");
  const main = node("div", "delivery-main");
  const playerPanel = node("section", "delivery-player-panel");
  const player = document.createElement("video");
  player.className = "delivery-player";
  player.controls = true;
  player.playsInline = true;
  player.preload = "metadata";
  player.setAttribute("aria-label", "当前成片播放器");
  if (data.player?.video_url) player.src = data.player.video_url;
  if (data.player?.poster_url) player.poster = data.player.poster_url;
  const versionSummary = node("p", "delivery-version-summary", data.versions?.find((item) => item.active)?.change_summary || "当前成片");
  const setVersion = (version) => {
    if (version.video_url) player.src = version.video_url;
    if (version.poster_url) player.poster = version.poster_url;
    versionSummary.textContent = version.change_summary || "该版本暂无变更说明";
    versionButtons.querySelectorAll("button").forEach((button) => button.classList.toggle("is-selected", button.dataset.versionId === version.id));
  };
  (data.versions || []).forEach((version) => {
    const button = node("button", `delivery-version-button${version.active ? " is-selected" : ""}`, version.label);
    button.type = "button"; button.dataset.versionId = version.id;
    button.title = version.change_summary || version.qa_status;
    button.addEventListener("click", () => setVersion(version));
    versionButtons.append(button);
  });
  versions.append(versionButtons, versionSummary);
  playerPanel.append(player);
  const facts = node("div", "delivery-facts");
  facts.append(detailRow("检查结果", data.qa_status), detailRow("视频时长", formatDuration(data.duration_seconds)), detailRow("交付格式", data.format_label));
  playerPanel.append(facts);
  if (data.download_url) {
    const link = node("a", "primary-link", "下载当前版本");
    link.href = data.download_url; link.setAttribute("download", ""); playerPanel.append(link);
  }

  const evaluationCard = renderEvaluationCard(data.evaluation);
  if (evaluationCard) playerPanel.append(evaluationCard);

  const candidates = node("aside", "delivery-candidates");
  candidates.append(node("h3", "section-title", "快速决策"));
  (data.candidate_groups || []).forEach((group) => {
    const section = node("section", "delivery-candidate-group");
    section.append(node("h4", "delivery-candidate-heading", group.label));
    if (group.empty_message) section.append(node("p", "empty-copy", group.empty_message));
    (group.candidates || []).forEach((candidate) => {
      const hasPendingSelection = Object.prototype.hasOwnProperty.call(pendingCandidateIds, group.kind);
      const selected = hasPendingSelection ? pendingCandidateIds[group.kind] === candidate.id : candidate.selected;
      const button = node("button", `delivery-candidate${selected ? " is-selected" : ""}`);
      button.type = "button"; button.disabled = !editable;
      if (candidate.preview_url && group.kind === "cover") {
        const image = document.createElement("img"); image.src = candidate.preview_url; image.alt = ""; image.loading = "lazy"; button.append(image);
      }
      const body = node("span", "delivery-candidate-body");
      body.append(node("strong", "", candidate.label), node("span", "", candidate.summary)); button.append(body);
      button.addEventListener("click", () => onOperation({ op: "select_delivery_candidate", candidate_kind: group.kind, candidate_id: candidate.id }));
      section.append(button);
    });
    candidates.append(section);
  });
  main.append(playerPanel, candidates);

  const timeline = node("section", "delivery-timeline");
  timeline.append(node("h3", "section-title", "画面与声音审核"));
  const duration = Number(data.timeline?.duration_seconds || data.duration_seconds || 0);
  const playhead = node("div", "delivery-playhead");
  playhead.setAttribute("aria-hidden", "true");
  const updatePlayhead = () => { playhead.style.left = `${duration > 0 ? Math.min(100, player.currentTime / duration * 100) : 0}%`; };
  player.addEventListener("timeupdate", updatePlayhead);
  const lanes = node("div", "delivery-track-lanes");
  lanes.append(playhead);
  data.timeline.tracks.forEach((track) => {
    const row = node("div", `delivery-track delivery-track-${track.kind}`);
    row.append(node("strong", "delivery-track-label", track.label));
    const lane = node("div", "delivery-track-lane");
    if (track.empty_message) lane.append(node("span", "delivery-track-empty", track.empty_message));
    (track.segments || []).forEach((segment) => {
      const copyOverride = track.kind === "copy" ? pendingCopyOverrides.get(segment.id) : null;
      const segmentLabel = copyOverride?.text ?? segment.label;
      const item = node("button", "delivery-segment", segmentLabel);
      item.type = "button";
      const start = Number(segment.start_seconds || 0); const end = Number(segment.end_seconds || start);
      item.style.left = `${duration > 0 ? start / duration * 100 : 0}%`;
      item.style.width = `${duration > 0 ? Math.max(2, (end - start) / duration * 100) : 100}%`;
      item.title = `${segmentLabel} · ${formatTimeRange(start, end)}`;
      item.addEventListener("click", () => { player.currentTime = start; updatePlayhead(); });
      lane.append(item);
      if (track.kind === "copy" && editable) {
        const edit = node("button", "delivery-copy-edit", "编辑"); edit.type = "button";
        edit.style.left = item.style.left;
        edit.addEventListener("click", () => {
          const existing = timeline.querySelector(".delivery-copy-editor"); if (existing) existing.remove();
          const form = node("div", "delivery-copy-editor");
          const input = document.createElement("textarea"); input.rows = 2; input.value = segmentLabel;
          const sync = document.createElement("input"); sync.type = "checkbox"; sync.checked = copyOverride?.sync_narration ?? segment.sync_narration !== false;
          const syncLabel = node("label", "edit-choice"); syncLabel.append(sync, node("span", "", "同步更新口播"));
          const save = node("button", "primary-button", "保存修改"); save.type = "button";
          save.addEventListener("click", () => { onOperation({ op: "replace_delivery_copy", section_id: segment.id, text: input.value, sync_narration: sync.checked }); form.remove(); });
          const cancel = node("button", "quiet-button", "取消"); cancel.type = "button"; cancel.addEventListener("click", () => form.remove());
          const actions = node("div", "inline-edit-actions"); actions.append(save, cancel);
          form.append(input, syncLabel, actions); timeline.append(form); input.focus();
        });
        lane.append(edit);
      }
    });
    row.append(lane); lanes.append(row);
  });
  timeline.append(lanes);
  workbench.append(versions, main, timeline);
  if (data.delivery) renderDeliveryInfo(workbench, data.delivery);
  container.append(workbench);
}

function renderDeliveryInfo(container, delivery) {
  // Publish-stage panel: the delivery package differs from the compose review
  // surface (title/description/hashtags, export status and delivery notes).
  const panel = node("section", "delivery-publish-info");
  panel.append(node("h3", "section-title", "交付信息"));
  (delivery.entries || []).forEach((entry) => {
    const card = node("div", "delivery-publish-entry");
    const heading = node("div", "delivery-publish-heading");
    heading.append(
      node("strong", "delivery-publish-title", entry.title || "未命名交付"),
      node("span", `status-chip status-${entry.status || "draft"}`, entry.status_label || entry.status || "未发布"),
    );
    card.append(heading);
    card.append(detailRow("交付平台", entry.platform_label || entry.platform || "本地"));
    if (entry.description) card.append(node("p", "row-copy", entry.description));
    if (entry.hashtags && entry.hashtags.length) {
      const tags = node("div", "tag-list");
      entry.hashtags.forEach((tag) => tags.append(node("span", "tag", tag)));
      card.append(tags);
    }
    if (entry.export_path) card.append(detailRow("交付文件", entry.export_path));
    if (entry.timestamp) card.append(detailRow("导出时间", entry.timestamp));
    panel.append(card);
  });
  if (!(delivery.entries || []).length) panel.append(node("p", "empty-copy", "还没有生成交付包"));
  if (delivery.notes) {
    const notes = node("div", "delivery-publish-notes");
    notes.append(node("h4", "delivery-publish-subheading", "交付说明"));
    notes.append(node("p", "row-copy", delivery.notes));
    panel.append(notes);
  }
  if (delivery.package_path) {
    panel.append(detailRow("交付包位置", delivery.package_path));
  }
  if (delivery.package_files && delivery.package_files.length) {
    const files = node("div", "delivery-package-files");
    files.append(node("h4", "delivery-publish-subheading", `交付包文件（${delivery.package_files.length}）`));
    delivery.package_files.forEach((file) => {
      const row = node("div", "delivery-package-file");
      const label = node("span", "delivery-package-file-label", file.label || file.relative_path);
      row.append(label);
      if (file.download_url) {
        const link = node("a", "quiet-button delivery-package-download", "下载");
        link.href = file.download_url; link.download = file.label || "download";
        link.target = "_blank"; link.rel = "noreferrer"; row.append(link);
      } else {
        row.append(node("span", "row-meta", "文件尚未生成"));
      }
      files.append(row);
    });
    panel.append(files);
  }
  if (delivery.hero_output) panel.append(detailRow("主交付文件", delivery.hero_output));
  if (delivery.qa_evidence && delivery.qa_evidence.length) {
    const evidence = node("div", "delivery-publish-notes");
    evidence.append(node("h4", "delivery-publish-subheading", "QA 证据"));
    delivery.qa_evidence.forEach((item) => {
      const link = node("a", "delivery-evidence-link", item.label || item.relative_path);
      if (item.download_url) { link.href = item.download_url; link.target = "_blank"; link.rel = "noreferrer"; }
      evidence.append(link);
    });
    panel.append(evidence);
  }
  container.append(panel);
}

function renderEmpty(container) {
  container.append(node("p", "empty-copy", "该阶段暂时没有可展示的内容"));
}

function renderEditor(container, stage, editor, project, snapshot) {
  container.replaceChildren();
  const data = editor?.data || {};
  const canEdit = (project.permissions || []).includes("edit");
  // Phase 2 审批只读模式：view_mode=approval → 不渲染 typed editor / 编辑控件（独立于权限）
  const approvalMode = (snapshot?.workspace?.view_mode === "approval");
  const mutationStage = editor?.type === "delivery_review" ? "delivery_review" : stage.id;
  const message = node("span", "editor-message");
  let changes = [...(snapshot.drafts?.[mutationStage]?.changes || [])];
  let timer;
  const saveNow = async () => {
    const draft = await saveDraft(project.project_id, mutationStage, {
      base_revision: project.revision,
      changes,
    });
    snapshotStore.setDraft(mutationStage, draft);
    message.textContent = "修改已保存，可预览影响";
  };
  const scheduleSave = () => {
    clearTimeout(timer);
    message.textContent = "正在保存修改";
    timer = setTimeout(() => saveNow().catch((error) => { message.textContent = error.message; }), 220);
  };
  const flushSave = async () => {
    clearTimeout(timer);
    if (changes.length) await saveNow();
  };
  const onOperation = (operation) => {
    if (editor?.type === "proposal_choice") changes = mergeProposalOperation(changes, operation);
    else if (editor?.type === "script_editor") changes = mergeKeyedOperation(changes, operation, scriptOperationKey);
    else if (editor?.type === "asset_review") changes = mergeKeyedOperation(changes, operation, executionOperationKey);
    else changes = mergeResearchOperation(changes, operation);
    scheduleSave();
    snapshotStore.setDraft(mutationStage, {
      ...(snapshot.drafts?.[mutationStage] || {}),
      stage: mutationStage,
      changes,
      status: "local",
    });
    if (operation.op === "approve_shot_execution_plan") {
      // Locking is a gated handoff: save the draft, then show confirmation.
      setTimeout(() => previewNow(), 260);
    }
  };
  const previewNow = async () => {
    try {
      await flushSave();
      const value = await previewDraft(project.project_id, mutationStage);
      snapshotStore.setPreview(mutationStage, value); message.textContent = "影响预览已生成";
      setTimeout(() => document.querySelector(".impact-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 0);
    } catch (error) { message.textContent = error.message; }
  };
  let editorData = data;
  if (editor?.type === "proposal_choice") editorData = applyProposalControlPlanDraft(data, changes);
  if (editor?.type === "script_editor") editorData = applyScriptDraft(data, changes);
  if (editor?.type === "asset_review") editorData = applyExecutionPlanDraft(data, changes);
  const renderers = {
    research_review: (target, value) => renderResearch(target, value, { editable: canEdit, onOperation, onPreview: previewNow, pendingOperations: changes }),
    proposal_choice: (target, value) => renderProposal(target, value, { editable: canEdit, onOperation }),
    script_editor: (target, value) => renderScript(target, value, { editable: canEdit, onOperation }),
    shot_mapping: renderShots,
    asset_review: (target, value) => renderAssets(target, value, {
      editable: canEdit,
      onOperation,
      onNavigate: () => store.selectStage(project.stages.find((item) => item.label === "分镜")?.id),
    }),
    sample_review: (target, value) => renderSample(target, value, { project }),
    batch_review: (target, value) => renderBatch(target, value, { project }),
    edit_review: renderEdit,
    delivery_review: (target, value) => renderDelivery(target, value, { editable: canEdit, onOperation, pendingOperations: changes }),
    unavailable: (target, value) => target.append(node("p", "empty-copy", value.message)),
  };
  (renderers[editor?.type] || renderEmpty)(container, editorData);
  const editPanel = node("div", "typed-editor-panel");
  const editorBody = node("div", "typed-editor-body");
  const controls = node("div", "editor-controls");
  if (!approvalMode && !["research_review", "script_editor", "asset_review", "delivery_review"].includes(editor?.type)) {
    renderTypedEditor(editorBody, stage, editor, { editable: canEdit, onOperation });
  }
  if (canEdit && !approvalMode) {
    if (editor?.type === "delivery_review") {
      const save = node("button", "quiet-button", "暂存修改"); save.type = "button";
      save.addEventListener("click", () => flushSave().then(() => { message.textContent = "修改已暂存"; }).catch((error) => { message.textContent = error.message; }));
      controls.append(save);
    }
    if (editor?.type !== "research_review") {
      const preview = node("button", "quiet-button", editor?.type === "delivery_review" ? "查看影响" : "预览修改影响"); preview.type = "button";
      preview.addEventListener("click", previewNow);
      controls.append(preview);
    }
  }
  controls.append(message);
  if (!["research_review", "script_editor", "asset_review", "delivery_review"].includes(editor?.type)) editPanel.append(editorBody);
  editPanel.append(controls); container.append(editPanel);
  const impactPanel = node("div", "impact-panel");
  renderImpact(impactPanel, snapshot.previews?.[mutationStage], {
    onCommit: async () => {
      const value = snapshot.previews?.[mutationStage];
      if (!value) return;
      try { await commitDraft(project.project_id, mutationStage, value.preview_token, "运营人员确认修改"); snapshotStore.setDraft(mutationStage, null); message.textContent = editor?.type === "delivery_review" ? "已提交，正在生成新版" : "已提交，正在更新项目"; await refresh(); }
      catch (error) { message.textContent = error.message; }
    }, onClose: () => snapshotStore.setPreview(mutationStage, null),
  }, { commitLabel: editor?.type === "delivery_review" ? "生成新版" : editor?.type === "research_review" ? "确认并保存决定" : "确认并提交" });
  container.append(impactPanel);
  if (editor?.type === "delivery_review") return;
  const history = node("div", "revision-panel");
  fetchVersions(project.project_id, mutationStage).then((versions) => renderRevisions(history, versions, {
    onRestore: async (revisionId) => {
      try {
        const restorePreview = await restoreVersion(project.project_id, stage.id, revisionId);
        message.textContent = "恢复影响已列出，请确认后提交";
        renderImpact(impactPanel, restorePreview, {
          onCommit: async () => { try { await restoreVersion(project.project_id, stage.id, revisionId, restorePreview.preview_token); message.textContent = "历史内容已作为新版本恢复"; await refresh(); } catch (error) { message.textContent = error.message; } },
          onClose: () => impactPanel.replaceChildren(),
        });
      } catch (error) { message.textContent = error.message; }
    },
  })).catch(() => renderRevisions(history, [], { onRestore() {} }));
  container.append(history);
}

// 批量工作台：统一展示候选比较和批量确认入口。
function renderBatchApproval(project, snapshot) {
  setPageMode("batch");
  const approvalShell = byId("approval-shell");
  if (approvalShell) approvalShell.hidden = false;
  document.title = `${APPROVAL_COPY.brand} · ${project.title || "批量"}`;
  const title = byId("approval-title");
  if (title) title.textContent = project.title || "本批视频";
  const kicker = byId("approval-hero-kicker");
  if (kicker) kicker.textContent = APPROVAL_COPY.batchKicker;
  const data = (project.workspace?.editor && project.workspace.editor.data) || {};
  const note = byId("approval-note");
  if (note) note.textContent = APPROVAL_COPY.batchNote;
  const state = byId("approval-meta-state");
  if (state) {
    state.textContent = APPROVAL_COPY.batchState;
    state.classList.remove("is-waiting");
  }
  const returnLink = byId("approval-return-batch");
  if (returnLink) returnLink.hidden = true;
  const main = byId("approval-main");
  if (!main) return;
  main.replaceChildren();
  const sheet = node("div", "approval-sheet");
  renderBatch(sheet, data, { project });
  main.append(sheet);
}

function render(snapshot) {
  const shell = byId("operator-shell");
  shell.dataset.viewState = snapshot.viewState;
  byId("view-message").textContent = snapshot.message || VIEW_STATES[snapshot.viewState] || "";
  if (!snapshot.project) return;

  const project = snapshot.project;
  // 批量工作台使用浅色阅读界面，避免和单条审批的深色播放器混用。
  if (project.workspace?.editor?.type === "batch_review") {
    setPageMode("batch");
    renderBatchApproval(project, snapshot);
    return;
  }
  // 单条审批工作台：所有阶段和材料浏览都由同一套 store 状态驱动。
  const approvalActive = isApprovalShellActive(project, snapshot);
  setPageMode(approvalActive ? "approval" : "default");
  if (approvalActive) {
    renderApprovalWorkbench(byId("approval-shell"), project, snapshot);
    return;
  }

  const returnLink = byId("return-to-batch");
  const navigation = snapshot.navigation;
  if (returnLink) {
    returnLink.hidden = !navigation;
    if (navigation) {
      returnLink.href = navigation.returnUrl;
      returnLink.onclick = () => {
        navigation.scrollTop = window.scrollY;
        try { sessionStorage.setItem(`batch-scroll:${navigation.batchId}`, String(navigation.scrollTop)); } catch { /* no-op */ }
      };
    }
  }
  document.title = `${project.title} · 制作进度`;
  byId("project-title").textContent = project.title;
  byId("progress-value").textContent = `${project.summary.progress_percent}%`;
  byId("current-task").textContent = project.summary.current_task;
  byId("estimated-time").textContent = formatDuration(project.summary.estimated_seconds);
  byId("performance-promise").textContent = project.summary.performance?.promise || project.summary.performance?.message || "实测数据不足";
  byId("next-action").textContent = project.summary.next_action;
  byId("access-mark").textContent = (project.permissions || []).includes("edit") ? "可编辑工作台" : "只读查看";
  byId("diagnostic-link").href = `/diagnostics/p/${encodeURIComponent(project.project_id)}`;

  const stageList = byId("stage-list");
  stageList.replaceChildren();
  project.stages.forEach((stage, index) => {
    const button = node("button", `stage-button${stage.id === snapshot.selectedStageId ? " is-active" : ""}`);
    button.type = "button";
    button.dataset.stageId = stage.id;
    button.setAttribute("aria-pressed", String(stage.id === snapshot.selectedStageId));
    button.addEventListener("click", () => store.selectStage(stage.id));
    button.append(node("span", "stage-index", String(index + 1).padStart(2, "0")));
    const label = node("span", "stage-name", stage.label);
    label.append(node("small", "stage-status", stage.status));
    button.append(label, node("span", "stage-mark", STATUS_MARKS[stage.status] || "○"));
    stageList.append(button);
  });

  const selected = project.stages.find((stage) => stage.id === snapshot.selectedStageId) || project.stages[0];
  if (!selected) return;
  // 无论批次处于哪个阶段，都渲染同一份批量总览，阶段只作为进度提示。
  const batchEditor = project.workspace?.editor?.type === "batch_review" ? project.workspace.editor : null;
  const editor = batchEditor || selected.editor;
  byId("workspace-title").textContent = batchEditor ? "本批视频" : selected.label;
  byId("workspace-status").textContent = batchEditor
    ? `${project.summary.current_stage} · ${project.summary.progress_percent}%`
    : `${selected.status} · 第 ${selected.version || 0} 版`;
  renderEditor(byId("workspace-content"), selected, editor, project, snapshot);

  const review = byId("review-summary");
  review.replaceChildren();
  if (project.pending_review) {
    review.append(node("h3", "section-title", project.pending_review.label));
    review.append(node("p", "row-copy", project.pending_review.summary));
  } else if (project.legacy?.message) {
    review.append(node("p", "row-copy", project.legacy.message));
  } else {
    review.append(node("p", "row-copy", VIEW_STATES[snapshot.viewState] || "项目正在推进"));
  }
}

async function refresh({ showLoading = false } = {}) {
  if (showLoading) store.setLoading();
  try {
    const project = await fetchProjectState(projectId);
    store.setProject(project);
    const isApprovalView = isApprovalShellActive(project, store.get())
      || project.workspace?.editor?.type === "batch_review";
    if (isApprovalView) return;
    const existingDrafts = store.get().drafts || {};
    const [proposalDraft, scriptDraft, assetsDraft, deliveryDraft] = await Promise.all([
      existingDrafts.proposal?.status === "local"
        ? Promise.resolve(existingDrafts.proposal)
        : fetchDraft(projectId, "proposal").catch(() => null),
      existingDrafts.script?.status === "local"
        ? Promise.resolve(existingDrafts.script)
        : fetchDraft(projectId, "script").catch(() => null),
      existingDrafts.assets?.status === "local"
        ? Promise.resolve(existingDrafts.assets)
        : fetchDraft(projectId, "assets").catch(() => null),
      existingDrafts.delivery_review?.status === "local"
        ? Promise.resolve(existingDrafts.delivery_review)
        : fetchDraft(projectId, "delivery_review").catch(() => null),
    ]);
    snapshotStore.setDraft("proposal", proposalDraft?.status === "active" || proposalDraft?.status === "local" ? proposalDraft : null);
    snapshotStore.setDraft("script", scriptDraft?.status === "active" || scriptDraft?.status === "local" ? scriptDraft : null);
    snapshotStore.setDraft("assets", assetsDraft?.status === "active" || assetsDraft?.status === "local" ? assetsDraft : null);
    snapshotStore.setDraft("delivery_review", deliveryDraft?.status === "active" || deliveryDraft?.status === "local" ? deliveryDraft : null);
  } catch (error) {
    store.setError(businessErrorMessage(error));
  }
}

document.addEventListener("approval-select-stage", (event) => {
  const stageId = event.detail?.stageId;
  if (stageId) store.selectStage(stageId);
});
document.addEventListener("approval-select-artifact", (event) => {
  const artifactId = event.detail?.artifactId;
  if (artifactId) store.selectArtifact(artifactId);
});
document.addEventListener("approval-select-current", () => store.returnToReviewGate());
window.addEventListener("popstate", () => {
  store.syncSelectionFromUrl?.();
});

store.subscribe(render);
refresh({ showLoading: true });
// 审批动作完成后由 approval.js 发出刷新请求，本处统一重新拉取快照。
document.addEventListener("approval-refresh-request", () => refresh());
const stopWatching = watchProject(projectId, () => refresh());
// 批量工作台：SSE 只覆盖批根变化，轮询兜底让候选子项目变化
// 也能唤醒批页；事件丢失/缺口时通过 operator-state 重新拉取收敛。
let batchRevision = null;
let batchWatchStopped = false;
const batchWatchTick = async () => {
  if (batchWatchStopped) return;
  try {
    const snapshot = await fetchProjectState(projectId);
    const editor = snapshot?.workspace?.editor;
    if (editor?.type === "batch_review") {
      const nextRevision = editor.data?.aggregate_revision;
      if (batchRevision === null) {
        batchRevision = nextRevision;
      } else if (nextRevision && nextRevision !== batchRevision) {
        batchRevision = nextRevision;
        refresh();
        return;
      }
    }
  } catch { /* 保留当前已确认状态 */ }
  setTimeout(batchWatchTick, 8000);
};
setTimeout(batchWatchTick, 8000);
window.addEventListener("pagehide", () => {
  batchWatchStopped = true;
  stopWatching();
}, { once: true });

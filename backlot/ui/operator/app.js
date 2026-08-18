import { fetchProjectState, watchProject, saveDraft, previewDraft, commitDraft, fetchVersions, restoreVersion } from "./api.js";
import { createOperatorStore } from "./store.js";
import { STATUS_MARKS, VIEW_STATES, formatDuration, formatTimeRange } from "./language.js";
import { renderTypedEditor } from "./editors.js";
import { renderImpact } from "./impact.js";
import { renderRevisions } from "./revisions.js";

const byId = (id) => document.getElementById(id);
const projectId = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() || "");
const store = createOperatorStore();
const snapshotStore = store;

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

function renderResearch(container, data) {
  renderReferenceAnalysis(container, data.reference);
  container.append(node("h3", "section-title", "自有素材理解"));
  const stats = node("div", "inline-stats");
  stats.append(detailRow("已检查素材", `${data.source_count} 条`));
  stats.append(detailRow("可用素材", `${data.usable_count} 条`));
  container.append(stats);
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
    container.append(node("h3", "section-title", "素材明细"), list);
  }
  if (data.risks?.length) {
    const list = node("ul", "plain-list");
    data.risks.forEach((risk) => list.append(node("li", "", risk)));
    container.append(node("h3", "section-title", "需要留意"), list);
  }
}

function renderProposal(container, data) {
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
}

function renderScript(container, data, { editable, onOperation }) {
  container.append(detailRow("预计成片时长", formatDuration(data.duration_seconds)));
  if (!data.sections?.length) return renderEmpty(container);
  data.sections.forEach((section) => {
    const item = node("article", "content-row script-row");
    const heading = node("div", "script-row-heading");
    const title = node("div", "script-row-title");
    title.append(node("span", "row-meta", formatTimeRange(section.start_seconds, section.end_seconds)));
    title.append(node("h3", "row-title", section.label));
    heading.append(title);
    const copy = node("p", "row-copy script-copy", section.text);
    if (editable) {
      const edit = node("button", "inline-edit-button", "编辑");
      edit.type = "button";
      edit.setAttribute("aria-label", `编辑这段口播与字幕：${section.label}`);
      edit.addEventListener("click", () => {
        const form = node("div", "script-inline-editor");
        const input = document.createElement("textarea");
        input.rows = 3;
        input.value = copy.textContent || "";
        input.setAttribute("aria-label", `${section.label} 口播与字幕内容`);
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
    container.append(item);
  });
}

function renderReferenceEvidence(parent, evidence, index) {
  const panel = node("section", "evidence-panel reference-evidence-panel");
  panel.append(node("h4", "evidence-label", "参考机制"));
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
    panel.append(detailRow("参考机制", evidence.mechanism || "已提取整体机制"));
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
    basis.append(node("h3", "section-title", "映射依据"));
    if (data.reference_basis.summary) basis.append(node("p", "row-copy", data.reference_basis.summary));
    basis.append(detailRow("参考机制", data.reference_basis.proof_method));
    if (data.reference_basis.avg_evidence_seconds != null) basis.append(detailRow("参考节奏", `平均 ${Number(data.reference_basis.avg_evidence_seconds).toFixed(1)} 秒一个证据`));
    if (data.reference_basis.beat_order?.length) basis.append(node("h4", "detail-heading", "参考结构"), tagList(data.reference_basis.beat_order, "tag-list reference-beats"));
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
    if (shot.intent) item.append(detailRow("镜头意图", shot.intent));

    const evidenceGrid = node("div", "shot-evidence-grid");
    renderReferenceEvidence(evidenceGrid, shot.reference_evidence, index);
    const ownedPanel = node("section", "evidence-panel owned-evidence-panel");
    ownedPanel.append(node("h4", "evidence-label", "自有素材匹配"));
    const video = rangedVideo(shot, "shot-evidence-preview", `镜头 ${index + 1} 自有素材预览`); if (video) ownedPanel.append(video);
    ownedPanel.append(detailRow("素材", shot.source_label || "素材待定"));
    ownedPanel.append(detailRow("素材区间", shot.source_in_seconds == null || shot.source_out_seconds == null ? "尚未映射" : formatTimeRange(shot.source_in_seconds, shot.source_out_seconds)));
    if (shot.source_summary) ownedPanel.append(detailRow("素材内容", shot.source_summary));
    if (shot.source_usable_for?.length) ownedPanel.append(detailRow("适用能力", shot.source_usable_for.join("、")));
    evidenceGrid.append(ownedPanel);
    item.append(evidenceGrid);

    const rationale = node("div", "mapping-rationale");
    rationale.append(node("h4", "detail-heading", "为什么这样映射"));
    if (shot.reference_evidence?.rationale) rationale.append(detailRow("参考与镜头", shot.reference_evidence.rationale));
    rationale.append(node("p", "row-copy", shot.mapping_reason || "当前 artifact 未记录更细的映射理由"));
    item.append(rationale);
    const language = [shot.framing, shot.movement, shot.narrative_role].filter(Boolean); if (language.length) item.append(node("p", "source-facts", language.join(" · ")));
    container.append(item);
  });
}

function renderAssets(container, data) {
  container.append(detailRow("口播", data.narration_status));
  container.append(detailRow("字幕", data.subtitle_status));
  container.append(detailRow("背景音乐", data.music_status));
  const cost = data.estimated_cost_usd == null ? "暂未提供" : `$${Number(data.estimated_cost_usd).toFixed(2)}`;
  container.append(detailRow("已记录费用", cost));
}

function renderSample(container, data) {
  container.append(detailRow("检查结果", data.qa_status));
  container.append(detailRow("样片时长", formatDuration(data.duration_seconds)));
  container.append(node("p", "lead-copy", data.review_summary));
  if (data.preview_url) {
    const video = document.createElement("video");
    video.className = "preview-video";
    video.controls = true;
    video.playsInline = true;
    video.src = data.preview_url;
    video.setAttribute("aria-label", "样片预览");
    container.append(video);
  }
}

function renderEdit(container, data) {
  container.append(detailRow("本次修改范围", data.change_scope));
  container.append(detailRow("涉及镜头", `${data.affected_shot_count} 个`));
  if (data.reasons?.length) {
    const list = node("ul", "plain-list");
    data.reasons.forEach((reason) => list.append(node("li", "", reason)));
    container.append(list);
  }
}

function renderDelivery(container, data) {
  container.append(detailRow("检查结果", data.qa_status));
  container.append(detailRow("视频时长", formatDuration(data.duration_seconds)));
  container.append(detailRow("交付格式", data.format_label));
  if (data.download_url) {
    const link = node("a", "primary-link", "下载视频");
    link.href = data.download_url;
    link.setAttribute("download", "");
    container.append(link);
  }
}

function renderEmpty(container) {
  container.append(node("p", "empty-copy", "该阶段暂时没有可展示的内容"));
}

function renderEditor(container, stage, editor, project, snapshot) {
  container.replaceChildren();
  const data = editor?.data || {};
  const canEdit = (project.permissions || []).includes("edit");
  const message = node("span", "editor-message");
  let changes = [];
  let timer;
  const saveNow = async () => {
    const draft = await saveDraft(project.project_id, stage.id, {
      base_revision: project.revision,
      changes,
    });
    snapshotStore.setDraft(stage.id, draft);
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
  const onOperation = (operation) => { changes = [...changes, operation]; scheduleSave(); };
  const renderers = {
    research_review: renderResearch,
    proposal_choice: renderProposal,
    script_editor: (target, value) => renderScript(target, value, { editable: canEdit, onOperation }),
    shot_mapping: renderShots,
    asset_review: renderAssets,
    sample_review: renderSample,
    edit_review: renderEdit,
    delivery_review: renderDelivery,
    unavailable: (target, value) => target.append(node("p", "empty-copy", value.message)),
  };
  (renderers[editor?.type] || renderEmpty)(container, data);
  if (editor?.type === "research_review") return;
  const editPanel = node("div", "typed-editor-panel");
  const editorBody = node("div", "typed-editor-body");
  const controls = node("div", "editor-controls");
  if (editor?.type !== "script_editor") {
    renderTypedEditor(editorBody, stage, editor, { editable: canEdit, onOperation });
  }
  if (canEdit) {
    const preview = node("button", "quiet-button", "预览修改影响"); preview.type = "button";
    preview.addEventListener("click", async () => {
      try {
        await flushSave();
        const value = await previewDraft(project.project_id, stage.id);
        snapshotStore.setPreview(stage.id, value); message.textContent = "影响预览已生成";
      } catch (error) { message.textContent = error.message; }
    });
    controls.append(preview);
  }
  controls.append(message);
  if (editor?.type !== "script_editor") editPanel.append(editorBody);
  editPanel.append(controls); container.append(editPanel);
  const impactPanel = node("div", "impact-panel");
  renderImpact(impactPanel, snapshot.previews?.[stage.id], {
    onCommit: async () => {
      const value = snapshot.previews?.[stage.id];
      if (!value) return;
      try { await commitDraft(project.project_id, stage.id, value.preview_token, "运营人员确认修改"); message.textContent = "已提交，正在更新项目"; await refresh(); }
      catch (error) { message.textContent = error.message; }
    }, onClose: () => snapshotStore.setPreview(stage.id, null),
  });
  container.append(impactPanel);
  const history = node("div", "revision-panel");
  fetchVersions(project.project_id, stage.id).then((versions) => renderRevisions(history, versions, {
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

function render(snapshot) {
  const shell = byId("operator-shell");
  shell.dataset.viewState = snapshot.viewState;
  byId("view-message").textContent = snapshot.message || VIEW_STATES[snapshot.viewState] || "";
  if (!snapshot.project) return;

  const project = snapshot.project;
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
  byId("workspace-title").textContent = selected.label;
  byId("workspace-status").textContent = `${selected.status} · 第 ${selected.version || 0} 版`;
  renderEditor(byId("workspace-content"), selected, selected.editor, project, snapshot);

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
    store.setProject(await fetchProjectState(projectId));
  } catch {
    store.setError();
  }
}

store.subscribe(render);
refresh({ showLoading: true });
const stopWatching = watchProject(projectId, () => refresh());
window.addEventListener("pagehide", stopWatching, { once: true });

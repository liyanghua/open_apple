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

function renderResearch(container, data) {
  container.append(node("p", "lead-copy", data.reference_summary));
  const stats = node("div", "inline-stats");
  stats.append(detailRow("已检查素材", `${data.source_count} 条`));
  stats.append(detailRow("可用素材", `${data.usable_count} 条`));
  container.append(stats);
  if (data.risks?.length) {
    const list = node("ul", "plain-list");
    data.risks.forEach((risk) => list.append(node("li", "", risk)));
    container.append(node("h3", "section-title", "需要留意"), list);
  }
}

function renderProposal(container, data) {
  if (!data.concepts?.length) return renderEmpty(container);
  data.concepts.forEach((concept) => {
    const item = node("article", `content-row${concept.id === data.selected_id ? " is-selected" : ""}`);
    item.append(node("h3", "row-title", concept.title || "创意方向"));
    item.append(node("p", "row-copy", concept.hook || "暂未提供开头文案"));
    item.append(node("span", "row-meta", formatDuration(concept.duration_seconds)));
    container.append(item);
  });
}

function renderScript(container, data) {
  container.append(detailRow("预计成片时长", formatDuration(data.duration_seconds)));
  if (!data.sections?.length) return renderEmpty(container);
  data.sections.forEach((section) => {
    const item = node("article", "content-row");
    item.append(node("span", "row-meta", formatTimeRange(section.start_seconds, section.end_seconds)));
    item.append(node("h3", "row-title", section.label));
    item.append(node("p", "row-copy", section.text));
    container.append(item);
  });
}

function renderShots(container, data) {
  container.append(detailRow("预计成片时长", formatDuration(data.duration_seconds)));
  if (!data.shots?.length) return renderEmpty(container);
  data.shots.forEach((shot, index) => {
    const item = node("article", "content-row shot-row");
    item.append(node("span", "shot-number", String(index + 1).padStart(2, "0")));
    const body = node("div", "shot-body");
    body.append(node("h3", "row-title", shot.beat || "镜头内容"));
    if (shot.screen_copy) body.append(node("p", "row-copy", shot.screen_copy));
    body.append(node("span", "row-meta", `${shot.source_label || "素材待定"} · ${formatTimeRange(shot.in_seconds, shot.out_seconds)}`));
    item.append(body);
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
  const renderers = {
    research_review: renderResearch,
    proposal_choice: renderProposal,
    script_editor: renderScript,
    shot_mapping: renderShots,
    asset_review: renderAssets,
    sample_review: renderSample,
    edit_review: renderEdit,
    delivery_review: renderDelivery,
    unavailable: (target, value) => target.append(node("p", "empty-copy", value.message)),
  };
  (renderers[editor?.type] || renderEmpty)(container, data);
  const canEdit = (project.permissions || []).includes("edit");
  const editPanel = node("div", "typed-editor-panel");
  const editorBody = node("div", "typed-editor-body");
  const controls = node("div", "editor-controls");
  const message = node("span", "editor-message");
  let changes = [];
  let timer;
  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const draft = await saveDraft(project.project_id, stage.id, {
          base_revision: project.revision,
          changes,
        });
        snapshotStore.setDraft(stage.id, draft);
        message.textContent = "修改已保存，可预览影响";
      } catch (error) { message.textContent = error.message; }
    }, 220);
  };
  const onOperation = (operation) => { changes = [...changes, operation]; save(); };
  renderTypedEditor(editorBody, stage, editor, { editable: canEdit, onOperation });
  if (canEdit) {
    const preview = node("button", "quiet-button", "预览修改影响"); preview.type = "button";
    preview.addEventListener("click", async () => {
      try {
        const value = await previewDraft(project.project_id, stage.id);
        snapshotStore.setPreview(stage.id, value); message.textContent = "影响预览已生成";
      } catch (error) { message.textContent = error.message; }
    });
    controls.append(preview);
  }
  controls.append(message); editPanel.append(editorBody, controls); container.append(editPanel);
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
    onRestore: async (revisionId) => { try { const restore = await restoreVersion(project.project_id, stage.id, revisionId); message.textContent = restore.requires_impact_preview ? "已准备恢复，请先预览影响" : "恢复已提交"; } catch (error) { message.textContent = error.message; } },
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

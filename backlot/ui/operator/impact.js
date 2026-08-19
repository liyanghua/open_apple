export function renderImpact(container, preview, { onCommit, onClose }, { commitLabel = "确认并提交" } = {}) {
  container.replaceChildren();
  if (!preview) return;
  const title = document.createElement("h3"); title.textContent = "修改影响预览"; container.append(title);
  const summary = document.createElement("p"); summary.className = "impact-summary"; summary.textContent = preview.summary; container.append(summary);
  const mode = document.createElement("strong"); mode.className = "impact-mode"; mode.textContent = preview.render_mode; container.append(mode);
  if (preview.changed_fields?.length) {
    const heading = document.createElement("h4"); heading.className = "detail-heading"; heading.textContent = "具体改动"; container.append(heading);
    const list = document.createElement("div"); list.className = "impact-change-list";
    preview.changed_fields.forEach((change) => {
      const row = document.createElement("div"); row.className = "impact-change-row";
      const field = document.createElement("strong"); field.textContent = change.label || change.field;
      const value = document.createElement("span"); value.textContent = `${change.before ?? "未设置"} → ${change.after ?? "未设置"}`;
      row.append(field, value); list.append(row);
    });
    container.append(list);
  }
  if (preview.affected_stages?.length) {
    const affected = document.createElement("p"); affected.className = "editor-help"; affected.textContent = `提交后会影响：${preview.affected_stages.join("、")}`; container.append(affected);
  }
  (preview.warnings || []).forEach((warning) => { const item = document.createElement("p"); item.className = "impact-warning"; item.textContent = warning; container.append(item); });
  const actions = document.createElement("div"); actions.className = "impact-actions";
  const commit = document.createElement("button"); commit.type = "button"; commit.className = "primary-button"; commit.textContent = commitLabel; commit.addEventListener("click", onCommit);
  const close = document.createElement("button"); close.type = "button"; close.className = "quiet-button"; close.textContent = "继续修改"; close.addEventListener("click", onClose);
  actions.append(commit, close); container.append(actions);
}

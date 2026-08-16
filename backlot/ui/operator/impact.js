export function renderImpact(container, preview, { onCommit, onClose }) {
  container.replaceChildren();
  if (!preview) return;
  container.append(document.createElement("h3")).lastChild.textContent = "修改影响预览";
  const summary = document.createElement("p"); summary.className = "impact-summary"; summary.textContent = preview.summary; container.append(summary);
  const mode = document.createElement("strong"); mode.className = "impact-mode"; mode.textContent = preview.render_mode; container.append(mode);
  (preview.warnings || []).forEach((warning) => { const item = document.createElement("p"); item.className = "impact-warning"; item.textContent = warning; container.append(item); });
  const actions = document.createElement("div"); actions.className = "impact-actions";
  const commit = document.createElement("button"); commit.type = "button"; commit.className = "primary-button"; commit.textContent = "确认并提交"; commit.addEventListener("click", onCommit);
  const close = document.createElement("button"); close.type = "button"; close.className = "quiet-button"; close.textContent = "继续修改"; close.addEventListener("click", onClose);
  actions.append(commit, close); container.append(actions);
}

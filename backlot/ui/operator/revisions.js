export function renderRevisions(container, revisions, { onRestore }) {
  container.replaceChildren();
  if (!revisions?.length) { container.textContent = "暂时没有历史版本"; return; }
  revisions.slice().reverse().forEach((revision) => {
    const row = document.createElement("div"); row.className = "revision-row";
    const title = document.createElement("strong"); title.textContent = revision.reason || "版本更新";
    const time = document.createElement("span"); time.textContent = revision.created_at || "";
    const button = document.createElement("button"); button.type = "button"; button.className = "quiet-button"; button.textContent = "准备恢复"; button.addEventListener("click", () => onRestore(revision.revision_id));
    row.append(title, time, button); container.append(row);
  });
}

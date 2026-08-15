export async function fetchProjectState(projectId) {
  const response = await fetch(`/api/v2/projects/${encodeURIComponent(projectId)}/operator-state`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("项目进度暂时无法读取");
  return response.json();
}

export function watchProject(projectId, onChange) {
  const source = new EventSource(`/api/v2/projects/${encodeURIComponent(projectId)}/events`);
  let timer = null;
  source.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.type !== "change") return;
      clearTimeout(timer);
      timer = setTimeout(onChange, 180);
    } catch {
      // Ignore malformed updates; the current verified state remains visible.
    }
  };
  return () => {
    clearTimeout(timer);
    source.close();
  };
}

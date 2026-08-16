const byId = (id) => document.getElementById(id);
const lines = (value) => String(value || "").split("\n").map((item) => item.trim()).filter(Boolean);
const safeName = (file) => (file.webkitRelativePath || file.name).split("/").slice(-2).join("_").replace(/[^\p{L}\p{N}._ -]/gu, "_");

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text != null) item.textContent = String(text);
  return item;
}

function projectCard(project) {
  const link = node("a", "card");
  link.href = `/p/${encodeURIComponent(project.project_id)}`;
  link.append(node("h3", "", project.title || project.project_id), node("p", "status", project.awaiting_human ? "等待你确认" : project.live ? "正在制作" : "可继续处理"));
  const progress = node("div", "progress");
  (project.stage_states || []).forEach((stage) => progress.append(node("i", stage.status === "completed" ? "done" : stage.status === "awaiting_human" ? "waiting" : "")));
  link.append(progress);
  return link;
}

async function renderProjects() {
  const response = await fetch("/api/projects", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("项目列表暂时无法读取");
  const projects = await response.json();
  const grid = byId("grid");
  grid.replaceChildren();
  projects.forEach((project) => grid.append(projectCard(project)));
  byId("count").textContent = `${projects.length} 个项目`;
  byId("empty").hidden = projects.length > 0;
}

function selectedFiles(id) { return Array.from(byId(id).files || []); }
function showSelection(inputId, outputId) {
  const files = selectedFiles(inputId);
  const size = Math.round(files.reduce((sum, file) => sum + file.size, 0) / 1024 / 1024);
  byId(outputId).textContent = files.length ? `已选择 ${files.length} 个文件，共 ${size}MB` : "尚未选择";
}

async function uploadFile(projectId, kind, file, csrfToken) {
  const response = await fetch(`/api/v2/projects/${encodeURIComponent(projectId)}/inputs/${kind}`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream", "X-CSRF-Token": csrfToken, "X-Upload-Path": safeName(file), "Idempotency-Key": crypto.randomUUID(), Origin: window.location.origin },
    body: file,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result?.error?.message || `上传 ${file.name} 失败`);
  return result.path;
}

const dialog = byId("create-dialog");
byId("new-project").onclick = () => dialog.showModal();
byId("close-dialog").onclick = byId("cancel-create").onclick = () => dialog.close();
byId("reference-files").onchange = () => showSelection("reference-files", "reference-selection");
byId("source-files").onchange = () => showSelection("source-files", "source-selection");

byId("create-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const message = byId("form-message");
  const platforms = form.getAll("platforms");
  const references = selectedFiles("reference-files");
  const sources = selectedFiles("source-files");
  const advancedReferences = lines(form.get("reference_paths"));
  const advancedSources = lines(form.get("source_paths"));
  if (!platforms.length) { message.textContent = "请至少选择一个发布平台"; return; }
  if (!references.length && !advancedReferences.length) { message.textContent = "请选择参考视频，或填写已有参考素材路径"; return; }
  if (!sources.length && !advancedSources.length) { message.textContent = "请选择自有素材文件夹，或填写已有素材路径"; return; }

  const sessionResponse = await fetch("/api/v2/auth/me", { headers: { Accept: "application/json" } });
  const session = sessionResponse.ok ? await sessionResponse.json() : null;
  const csrf = session?.csrf_token || "";
  const projectId = String(form.get("project_id"));
  const referencePaths = [...advancedReferences, ...references.map((file) => `inputs/reference/${safeName(file)}`)];
  const sourcePaths = [...advancedSources, ...sources.map((file) => `inputs/source/video/product/${safeName(file)}`)];
  const payload = {
    project_id: projectId, title: `${form.get("product_name")}复刻`, skill_id: "ecommerce-viral-remix", skill_version: "1.0.0",
    intake: { product_name: form.get("product_name"), category: "home-protection", platforms, duration_seconds: Number(form.get("duration_seconds")), reference_paths: [...new Set(referencePaths)], source_paths: [...new Set(sourcePaths)], copyright_confirmed: form.get("copyright_confirmed") === "on", brand_cta: form.get("brand_cta"), paid_generation_approved: form.get("paid_generation_approved") === "on", narration_required: true, subtitles_required: true, bgm_required: true },
  };

  try {
    message.textContent = "正在创建项目";
    const response = await fetch("/api/v2/projects", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID(), Origin: window.location.origin }, body: JSON["stringify"](payload) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result?.error?.message || "项目创建失败，请检查输入");
    const uploads = [...references.map((file) => ["reference", file]), ...sources.map((file) => ["source", file])];
    for (let index = 0; index < uploads.length; index += 1) {
      const [kind, file] = uploads[index];
      message.textContent = `正在导入素材 ${index + 1}/${uploads.length}：${file.name}`;
      await uploadFile(projectId, kind, file, csrf);
    }
    message.textContent = "素材导入完成，正在进入项目";
    window.location.assign(`/p/${encodeURIComponent(result.project_id)}`);
  } catch (error) { message.textContent = error.message; }
};

renderProjects().catch((error) => { byId("count").textContent = error.message; });

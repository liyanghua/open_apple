(() => {
  const root = document.getElementById("editorial-editor");
  if (!root) return;
  const parts = location.pathname.split("/").filter(Boolean);
  const batchId = parts[1] || root.dataset.batchId || "";
  const candidateId = parts[3] || root.dataset.candidateId || "";
  const $ = (id) => document.getElementById(id);
  const state = { session: null, snapshot: null, actions: [], csrf: "" };

  async function api(path, options = {}) {
    if (!state.csrf) {
      const me = await fetch("/api/v2/auth/me");
      state.csrf = (await me.json()).csrf_token || "";
    }
    const response = await fetch(path, {
      ...options,
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": state.csrf, ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.error?.message || "请求暂时无法完成");
    return data;
  }

  function setStatus(text) { $("editor-status").textContent = text; }
  function render(snapshot) {
    const timeline = snapshot?.timeline || {};
    const tracks = timeline.tracks || [];
    $("timeline").replaceChildren(...tracks.map((track) => {
      const line = document.createElement("div");
      line.className = "timeline-track";
      line.textContent = `${track.kind || "track"} · ${(track.clips || []).length} 个片段`;
      return line;
    }));
    const facts = (snapshot?.asset_catalogue?.assets || []).flatMap((item) => item.fact_scope?.claim_ids || []);
    $("fact-scope").textContent = facts.length ? `已绑定事实：${[...new Set(facts)].join("、")}` : "暂无可展示的商品事实";
    $("approved-assets").textContent = `${(snapshot?.asset_catalogue?.assets || []).length} 个服务端批准素材`;
    $("version-compare").textContent = `当前版本：${snapshot?.revision_id || snapshot?.revision || "基线"}`;
  }
  function unsupported(message) { $("unsupported-warning").hidden = false; $("unsupported-warning").textContent = message; }
  async function boot() {
    if (!batchId || !candidateId) return setStatus("缺少批次或候选参数");
    try {
      const gallery = await api(`/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery`);
      const candidate = (gallery.candidates || []).find((item) => item.candidate_id === candidateId);
      if (!candidate) throw new Error("候选不属于当前批次");
      if (!candidate.studio_eligibility?.eligible) return unsupported("当前候选的合成方式不支持精剪工作室");
      state.session = await api(`/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery/edit-session`, { method: "POST", headers: { "Idempotency-Key": `shell-${batchId}-${candidateId}-${candidate.child_revision}` }, body: JSON.stringify({ candidate_id: candidateId }) });
      const base = `/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery/edit-session/${encodeURIComponent(state.session.session_id)}/snapshot?candidate_id=${encodeURIComponent(candidateId)}`;
      state.snapshot = await api(base);
      render(state.snapshot);
      setStatus("编辑会话已建立，可进行精细剪辑");
    } catch (error) { setStatus(error.message || "编辑会话建立失败"); }
  }
  async function save() {
    if (!state.session || !state.actions.length) return setStatus("没有待保存修改");
    try {
      await api(`/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery/edit-session/${encodeURIComponent(state.session.session_id)}/delta`, { method: "POST", headers: { "Idempotency-Key": `delta-${Date.now()}` }, body: JSON.stringify({ candidate_id: candidateId, actions: state.actions }) });
      state.actions = []; setStatus("修改已保存，事实约束已重新校验");
    } catch (error) { setStatus(error.message); }
  }
  async function preview() {
    if (!state.session) return;
    try { await api(`/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery/edit-session/${encodeURIComponent(state.session.session_id)}/preview?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", body: JSON.stringify({}) }); setStatus("预览已提交，等待服务端 QA"); $("render-progress").textContent = "预览制作中"; } catch (error) { setStatus(error.message); }
  }
  async function finalRender() {
    if (!state.session) return;
    try { await api(`/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery/edit-session/${encodeURIComponent(state.session.session_id)}/run?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", body: JSON.stringify({ operation: "request_final" }) }); setStatus("完整成片已进入制作队列"); $("render-progress").textContent = "成片制作中"; } catch (error) { setStatus(error.message); }
  }
  document.querySelector('[data-action="save"]').addEventListener("click", save);
  document.querySelector('[data-action="preview"]').addEventListener("click", preview);
  document.querySelector('[data-action="final"]').addEventListener("click", finalRender);
  window.openreelBridge = { pushActions: (actions) => { state.actions = Array.isArray(actions) ? actions : []; setStatus(`待保存修改：${state.actions.length} 个动作`); } };
  boot();
})();

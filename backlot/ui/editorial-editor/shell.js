// OpenReel V1 编辑器壳（同源）：解析 /studio/<batch>/edit/<candidate> 上下文，
// 建立编辑会话，挂载真实 @openreel/web 应用（/ui/editorial-editor/openreel/），
// 通过 postMessage 桥接快照/动作，并把保存草稿/预览影响/退出会话接到既有 API。
const shell = document.getElementById("editorial-editor-shell");
const pathParts = window.location.pathname.split("/").filter(Boolean); // studio, <batch>, edit, <candidate>
const batchId = pathParts[1] || "";
const candidateId = pathParts[3] || "";
shell.dataset.batchId = batchId;
shell.dataset.candidateId = candidateId;

const byId = (id) => document.getElementById(id);
const notice = byId("notice");
const OPENREEL_URL = "/ui/editorial-editor/openreel/index.html#/editor";
let csrfCache = null;
let currentSession = null;
let currentSnapshot = null;
let pendingActions = [];
let frame = null;
let flushTimer = null;
let snapshotPosted = false;
let pendingSubmission = null;
let previewFocus = false;

async function csrfToken() {
  if (csrfCache) return csrfCache;
  const response = await fetch("/api/v2/auth/me", { headers: { Accept: "application/json" } });
  const payload = response.ok ? await response.json() : {};
  csrfCache = payload && payload.csrf_token ? payload.csrf_token : "";
  return csrfCache;
}

function showNotice(message) {
  notice.textContent = message;
  notice.hidden = false;
}

function clearNotice() {
  notice.textContent = "";
  notice.hidden = true;
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json",
    "X-CSRF-Token": await csrfToken(),
    ...(options.headers || {}),
  };
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data?.error?.message || "请求失败，请重试");
    error.code = data?.error?.code;
    error.status = response.status;
    throw error;
  }
  return data;
}

function sessionBase() {
  return `/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery/edit-session/${encodeURIComponent(currentSession.session_id)}`;
}

function renderDraftList() {
  const list = byId("draftList");
  list.replaceChildren();
  const unsupportedActions = currentSession?.unsupported_actions || [];
  byId("pendingCount").textContent = String(pendingActions.length);
  byId("unsupportedCount").textContent = String(unsupportedActions.length);
  unsupportedActions.slice(0, 8).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `仅本地草稿：${item.message || item.action_type}`;
    list.append(li);
  });
  if (!list.childElementCount && !pendingActions.length) {
    const li = document.createElement("li");
    li.textContent = "尚未提交编辑修改。";
    list.append(li);
  }
}

function renderEvidence(candidate) {
  const facts = candidate?.fact_summary?.claims || [];
  byId("factsSummary").textContent = facts.length
    ? `已绑定 ${facts.length} 条商品事实，仅允许在对应事实范围内编辑。`
    : "当前候选没有可展示的商品事实摘要。";
  const list = byId("assetList");
  list.replaceChildren();
  (candidate?.fact_summary?.claims || []).slice(0, 8).forEach((claim) => {
    const li = document.createElement("li");
    li.textContent = `${claim.id || "事实"}：${claim.statement || ""}`;
    list.append(li);
  });
}

function setBadge(text, className) {
  const badge = byId("statusBadge");
  badge.textContent = text;
  badge.className = `status-badge ${className || ""}`;
}

function syncPreviewFocus() {
  if (!frame?.contentWindow) return;
  frame.contentWindow.postMessage(
    { kind: "openmontage/preview-focus", enabled: previewFocus },
    window.location.origin,
  );
}

function setPreviewFocus(enabled) {
  previewFocus = enabled;
  shell.classList.toggle("is-preview-focus", enabled);
  byId("editorSurface").classList.toggle("is-preview-focus", enabled);
  const button = byId("focusPreview");
  button.textContent = enabled ? "还原编辑布局" : "⛶ 仅看画面";
  button.setAttribute("aria-label", enabled ? "还原编辑布局" : "仅看画面");
  button.title = enabled ? "还原编辑布局" : "仅看画面";
  byId("exitPreviewFocus").hidden = !enabled;
  syncPreviewFocus();
}

async function togglePreviewFullscreen() {
  const surface = byId("editorSurface");
  try {
    if (document.fullscreenElement || document.webkitFullscreenElement) {
      if (document.exitFullscreen) await document.exitFullscreen();
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
      setPreviewFocus(false);
      return;
    }
    setPreviewFocus(true);
    if (surface.requestFullscreen) await surface.requestFullscreen();
    else if (surface.webkitRequestFullscreen) surface.webkitRequestFullscreen();
    else setPreviewFocus(true);
  } catch {
    // Browser policies can reject fullscreen; the focus mode is still usable.
    setPreviewFocus(true);
  }
}

function mediaUrlForAsset(asset, clip) {
  const path = asset?.path || asset?.source_path || asset?.media_path;
  if (typeof path === "string" && path) {
    return `/media/${encodeURIComponent(currentSession.project_id)}/${path.split("/").map(encodeURIComponent).join("/")}`;
  }
  // Legacy materialization records keep the approved media identity in the
  // fact scope.  The proxy path is deterministic and remains same-origin;
  // missing media is intentionally represented as a placeholder by OpenReel.
  const shotId = String(clip?.fact_scope?.shot_id || "");
  const match = shotId.match(/shot-(\d+)/);
  if (match) {
    const sourceAssetId = String(asset?.source_asset_id || "");
    if (sourceAssetId.startsWith("generated-shotgen-")) {
      const generatedFile = `${sourceAssetId.slice("generated-".length)}.mp4`;
      return `/media/${encodeURIComponent(currentSession.project_id)}/assets/video/generated/generate-shot-${match[1].padStart(2, "0")}/${encodeURIComponent(generatedFile)}`;
    }
    return `/media/${encodeURIComponent(currentSession.project_id)}/assets/video/shot-${match[1].padStart(2, "0")}-proxy.mp4`;
  }
  return null;
}

function openReelPayload(session) {
  const timeline = session?.timeline || {};
  const catalogue = session?.asset_catalogue || {};
  const assets = new Map(
    (catalogue.assets || [])
      .filter((asset) => asset && asset.asset_id)
      .map((asset) => [String(asset.asset_id), asset]),
  );
  const videoTracks = (timeline.tracks || []).filter((track) => track?.kind === "video");
  const videoClips = videoTracks.flatMap((track) => track.clips || []);
  const shotForTime = (time) => {
    const clip = videoClips.find((item) => {
      const start = Number(item.start_seconds || 0);
      const end = Number(item.end_seconds ?? (start + Number(item.source_out_seconds || 0) - Number(item.source_in_seconds || 0)));
      return time >= start && time < end + 0.001;
    });
    return clip?.fact_scope?.shot_id || clip?.id || "";
  };
  const mapping = { clips: {}, subtitles: {}, transitions: {} };
  const tracks = videoTracks.map((track) => ({
    id: track.id,
    label: track.id,
    kind: track.kind,
    clips: (track.clips || []).map((clip) => {
      const sourceIn = Number(clip.source_in_seconds || 0);
      const sourceOut = Number(clip.source_out_seconds || sourceIn);
      const speed = Number(clip.speed || 1) || 1;
      const duration = Math.max(0.001, (sourceOut - sourceIn) / speed);
      const shotId = clip.fact_scope?.shot_id || clip.id;
      mapping.clips[String(clip.id)] = String(clip.id);
      return {
        id: clip.id,
        shot_id: shotId,
        enabled: true,
        start_time: Number(clip.start_seconds || 0),
        duration,
        in_point: sourceIn,
        out_point: sourceOut,
        speed,
        media: {
          url: mediaUrlForAsset(assets.get(String(clip.asset_id)), clip),
          duration_seconds: sourceOut,
        },
      };
    }),
  }));
  const subtitlesTrack = (timeline.tracks || []).find((track) => track?.kind === "subtitle");
  const subtitles = (subtitlesTrack?.clips || []).map((clip) => {
    mapping.subtitles[String(clip.id)] = String(clip.id);
    const start = Number(clip.start_seconds || 0);
    return {
      id: clip.id,
      shot_id: shotForTime(start),
      text: clip.text || "",
      start_time: start,
      end_time: Number(clip.end_seconds || start),
    };
  });
  return {
    session: {
      session_id: session.session_id,
      project_id: session.project_id,
      candidate_id: session.candidate_id,
    },
    snapshot: { mapping, tracks, subtitles },
  };
}

function postSnapshotOnce() {
  if (!frame || !frame.contentWindow || !currentSnapshot) return;
  if (snapshotPosted) return;
  snapshotPosted = true;
  frame.contentWindow.postMessage(
    { kind: "openmontage/snapshot", payload: openReelPayload(currentSnapshot) },
    window.location.origin,
  );
}

async function mountOpenReelSurface() {
  const fallback = byId("editorFallback");
  try {
    const probe = await fetch(OPENREEL_URL.split("#", 1)[0], { method: "HEAD" });
    if (!probe.ok) return;
    if (fallback) fallback.hidden = true;
    snapshotPosted = false;
    frame = document.createElement("iframe");
    frame.className = "editor-surface-frame";
    frame.title = "OpenReel 时间轴";
    frame.src = OPENREEL_URL;
    frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
    frame.setAttribute("allowfullscreen", "true");
    frame.setAttribute("data-testid", "openreel-surface");
    frame.addEventListener("load", () => {
      postSnapshotOnce();
      syncPreviewFocus();
    });
    byId("editorSurface").append(frame);
  } catch {
    // 构建产物未部署：保留 fallback 提示。
  }
}

async function flushDraft() {
  if (!currentSession || !pendingActions.length) {
    showNotice("还没有可保存的编辑修改。");
    return;
  }
  const actions = pendingActions;
  const submittedSignature = JSON.stringify(actions);
  if (!pendingSubmission || pendingSubmission.signature !== submittedSignature) {
    pendingSubmission = {
      signature: submittedSignature,
      key: `shell-delta-${currentSession.session_id}-${Date.now()}`,
    };
  }
  const key = pendingSubmission.key;
  try {
    const saved = await api(`${sessionBase()}/delta`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        actions,
        mapping: (currentSnapshot?.snapshot?.mapping) || { clips: {}, subtitles: {} },
      }),
    });
    const latestSignature = JSON.stringify(pendingActions);
    const hasNewerActions = latestSignature !== submittedSignature;
    pendingSubmission = null;
    if (!hasNewerActions) pendingActions = [];
    currentSession = {
      ...currentSession,
      deltas: saved.deltas,
      unsupported_actions: saved.unsupported_actions,
      status: saved.status,
    };
    byId("sessionState").textContent = hasNewerActions
      ? `已保存上一批，仍有 ${pendingActions.length} 个动作待保存。`
      : "已保存修改，可生成影响预览。";
    byId("previewImpact").disabled = false;
    renderDraftList();
    clearNotice();
    if (hasNewerActions) {
      window.clearTimeout(flushTimer);
      flushTimer = window.setTimeout(flushDraft, 0);
    }
  } catch (error) {
    if (error.code === "stale" || error.code === "revision_conflict") {
      setBadge("版本已变化", "is-stale");
      showNotice(`${error.message} 请刷新后重新打开编辑会话。`);
      pendingActions = [];
      pendingSubmission = null;
    } else {
      showNotice(error.message);
    }
  }
}

async function previewImpact() {
  try {
    const preview = await api(`${sessionBase()}/preview`, { method: "POST", body: JSON.stringify({}) });
    byId("sessionState").textContent = `影响预览：${preview.risk || ""}；${(preview.acceptance_points || []).join("；")}`;
    byId("qaStatus").textContent = preview.qa?.status || "待检查";
    byId("progressState").textContent = "影响预览已生成，等待确认后生成完整成片。";
    byId("finalRender").disabled = false;
    setBadge("已生成预览", "is-active");
    clearNotice();
  } catch (error) {
    showNotice(error.message);
  }
}

async function renderFinal() {
  try {
    await api(`${sessionBase()}/run`, { method: "POST", body: JSON.stringify({ operation: "request_final" }) });
    byId("progressState").textContent = "完整成片已进入制作队列。";
    byId("qaStatus").textContent = "制作中";
    setBadge("成片制作中", "is-active");
  } catch (error) {
    showNotice(error.message);
  }
}

async function discardSession() {
  const reason = window.prompt("填写退出会话的原因（丢弃修改）");
  if (!reason) return;
  try {
    await api(`${sessionBase()}/run`, {
      method: "POST",
      body: JSON.stringify({ action: "discard", reason }),
    });
    setBadge("已退出会话", "");
    byId("sessionState").textContent = "会话已丢弃；旧版本保持不变。";
    byId("saveDraft").disabled = true;
    byId("previewImpact").disabled = true;
    byId("discardSession").disabled = true;
    clearNotice();
  } catch (error) {
    showNotice(error.message);
  }
}

async function boot() {
  const back = byId("backToCandidate");
  back.href = `/studio/${encodeURIComponent(batchId)}`;
  if (!batchId || !candidateId) {
    setBadge("参数缺失", "is-stale");
    showNotice("缺少批次或候选参数，请从批量精剪工作室进入。");
    return;
  }
  try {
    const gallery = await api(`/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery`);
    const candidate = (gallery.candidates || []).find((item) => item.candidate_id === candidateId);
    if (!candidate) {
      setBadge("候选不可用", "is-stale");
      showNotice("候选不属于当前批次，或已被移除。");
      return;
    }
    const session = await api(
      `/api/v2/projects/${encodeURIComponent(batchId)}/editorial-gallery/edit-session`,
      {
        method: "POST",
        headers: { "Idempotency-Key": `shell-${batchId}-${candidateId}-${candidate.child_revision}` },
        body: JSON.stringify({
          candidate_id: candidateId,
          aggregate_revision: gallery.aggregate_revision,
          child_revision: candidate.child_revision,
          intent: "openreel_v1_edit",
          anchor: { type: "time_range", start_seconds: 0, end_seconds: 0 },
          instruction: "",
        }),
      },
    );
    currentSession = session;
    currentSnapshot = await api(`${sessionBase()}/snapshot`);
    byId("candidateTitle").textContent = candidate.label || candidate.candidate_id;
    renderEvidence(candidate);
    byId("versionLine").textContent =
      `候选版本 ${candidate.child_revision || currentSnapshot.child_revision || currentSnapshot.timeline?.base_generation_id || "当前"} · 会话 ${session.session_id}`;
    setBadge("会话已就绪", "is-active");
    byId("sessionState").textContent = "编辑会话已建立；时间轴材料已加载。";
    renderDraftList();
    await mountOpenReelSurface();
    byId("focusPreview").disabled = false;
    byId("togglePreviewFullscreen").disabled = false;
    byId("saveDraft").disabled = false;
    byId("discardSession").disabled = false;
    clearNotice();
  } catch (error) {
    setBadge(error.status === 409 ? "版本已变化" : "会话失败", "is-stale");
    showNotice(error.message || "编辑会话建立失败");
  }
}

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  if (!frame || event.source !== frame.contentWindow) return;
  const message = event.data || {};
  if (message.kind === "openreel/focus-bridge-ready") {
    shell.dataset.focusBridge = "ready";
    syncPreviewFocus();
    return;
  }
  if (message.kind === "openreel/preview-focus") {
    shell.dataset.previewFocus = message.enabled ? "active" : "inactive";
    shell.dataset.previewFocusGrid = message.grid_found ? "found" : "missing";
    shell.dataset.previewFocusArea = message.grid_area || "";
    return;
  }
  if (message.kind === "openreel/ready") {
    byId("sessionState").textContent = "OpenReel 时间轴已同步。";
    return;
  }
  if (message.kind === "openreel/actions" && currentSession
    && message.payload?.session_id === currentSession.session_id) {
    pendingActions = Array.isArray(message.payload.actions) ? message.payload.actions : [];
    byId("sessionState").textContent = `待保存修改：${pendingActions.length} 个动作。`;
    renderDraftList();
    window.clearTimeout(flushTimer);
    flushTimer = window.setTimeout(flushDraft, 1200);
  }
});

byId("saveDraft").addEventListener("click", flushDraft);
byId("previewImpact").addEventListener("click", previewImpact);
byId("discardSession").addEventListener("click", discardSession);
byId("finalRender").addEventListener("click", renderFinal);
byId("focusPreview").addEventListener("click", () => setPreviewFocus(!previewFocus));
byId("exitPreviewFocus").addEventListener("click", () => setPreviewFocus(false));
byId("togglePreviewFullscreen").addEventListener("click", togglePreviewFullscreen);
document.addEventListener("fullscreenchange", () => {
  const active = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
  byId("togglePreviewFullscreen").textContent = active ? "退出全屏" : "全屏预览";
  if (!active && previewFocus) setPreviewFocus(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && previewFocus && !document.fullscreenElement) setPreviewFocus(false);
});

boot();

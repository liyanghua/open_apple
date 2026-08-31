async function call(path, options = {}) {
  const session = await getSession();
  const headers = {
    Accept: "application/json",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(session?.csrf_token ? { "X-CSRF-Token": session.csrf_token } : {}),
    ...(options.mutation ? { "Idempotency-Key": crypto.randomUUID() } : {}),
    Origin: window.location.origin,
    ...(options.headers || {}),
  };
  const response = await fetch(path, {
    ...options,
    headers,
    body: options.body ? JSON["stringify"](options.body) : undefined,
  });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const error = new Error(data?.error?.message || "操作暂时无法完成");
    error.code = data?.error?.code;
    error.fields = data?.error?.field_errors || [];
    throw error;
  }
  return data;
}

export async function getSession() {
  const response = await fetch("/api/v2/auth/me", { headers: { Accept: "application/json" } });
  if (!response.ok) return null;
  return response.json();
}

export async function fetchProjectState(projectId) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/operator-state`);
}

export async function fetchDraft(projectId, stage) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/drafts/${encodeURIComponent(stage)}`);
}

export async function saveDraft(projectId, stage, draft) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/drafts/${encodeURIComponent(stage)}`, {
    method: "PUT", body: { version: "1.0", ...draft }, mutation: true,
  });
}

export async function discardDraft(projectId, stage) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/drafts/${encodeURIComponent(stage)}`, {
    method: "DELETE", mutation: true,
  });
}

export async function previewDraft(projectId, stage) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/drafts/${encodeURIComponent(stage)}/impact`, {
    method: "POST", body: {}, mutation: true,
  });
}

export async function commitDraft(projectId, stage, previewToken, reason) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/drafts/${encodeURIComponent(stage)}/commit`, {
    method: "POST", body: { version: "1.0", preview_token: previewToken, reason }, mutation: true,
  });
}

export async function quoteShotGeneration(projectId, request) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/shot-generations/quote`, {
    method: "POST", body: request, mutation: false,
  });
}

export async function createShotGeneration(projectId, request) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/shot-generations`, {
    method: "POST", body: request, mutation: true,
  });
}

export async function adoptShotGeneration(projectId, taskId) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/shot-generations/${encodeURIComponent(taskId)}/adopt`, {
    method: "POST", body: {}, mutation: true,
  });
}

export async function fetchVersions(projectId, stage) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(stage)}`);
}

export async function compareVersions(projectId, stage, fromId, toId) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(stage)}/compare`, {
    method: "POST", body: { from_revision_id: fromId, to_revision_id: toId }, mutation: false,
  });
}

export async function restoreVersion(projectId, stage, revisionId, previewToken = null) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(stage)}/${encodeURIComponent(revisionId)}/restore`, {
    method: "POST", body: previewToken ? { preview_token: previewToken, reason: "恢复历史版本" } : {}, mutation: true,
  });
}

export async function decideReview(projectId, reviewId, decision, reason, effectConfirmations = null, subjectVersion = null, subjectHash = null, issueTags = null) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/reviews/${encodeURIComponent(reviewId)}/${decision}`, {
    method: "POST", body: {
      reason,
      ...(subjectVersion == null ? {} : { subject_version: subjectVersion }),
      ...(subjectHash == null ? {} : { subject_hash: subjectHash }),
      ...(effectConfirmations ? { effect_confirmations: effectConfirmations } : {}),
      ...(issueTags ? { issue_tags: issueTags } : {}),
    }, mutation: true,
  });
}

export function watchProject(projectId, onChange) {
  const source = new EventSource(`/api/v2/projects/${encodeURIComponent(projectId)}/events`);
  let timer = null;
  source.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.type !== "change") return;
      clearTimeout(timer); timer = setTimeout(onChange, 180);
    } catch { /* 保留当前已确认状态 */ }
  };
  return () => { clearTimeout(timer); source.close(); };
}

export async function batchSelectForEdit(projectId, aggregateRevision, participantsOrIds, reason) {
  const body = { aggregate_revision: aggregateRevision, reason };
  if (Array.isArray(participantsOrIds) && participantsOrIds.some((item) => item && typeof item === "object")) {
    body.participants = participantsOrIds;
  } else {
    // Keep the old payload for older server versions and archived clients.
    body.candidate_ids = participantsOrIds;
  }
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/batch/select`, {
    method: "POST", body, mutation: true,
  });
}

export async function batchApproveGate(projectId, aggregateRevision, gate, participants, reason) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/batch/approve-gate`, {
    method: "POST", body: { aggregate_revision: aggregateRevision, gate, participants, reason }, mutation: true,
  });
}

export async function batchRecover(projectId, batchActionId) {
  return call(`/api/v2/projects/${encodeURIComponent(projectId)}/batch/actions/${encodeURIComponent(batchActionId)}/recover`, {
    method: "POST", body: {}, mutation: true,
  });
}

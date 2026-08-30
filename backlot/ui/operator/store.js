import { buildApprovalStages } from "./approval_model.js";

function currentSearch() {
  return typeof window !== "undefined" ? window.location.search : "";
}

/** Read only the browsing position; approval facts never enter the URL. */
export function parseViewSelection(search = currentSearch()) {
  const params = new URLSearchParams(search || "");
  return {
    stageId: params.get("stage") || null,
    artifactId: params.get("artifact") || null,
  };
}

export const parseOperatorSelection = parseViewSelection;

/** Preserve unrelated query parameters while replacing the browsing position. */
export function serializeViewSelection(selection = {}, search = currentSearch()) {
  const params = new URLSearchParams(search || "");
  params.delete("stage");
  params.delete("artifact");
  const stageId = selection.stageId || selection.stage;
  const artifactId = selection.artifactId || selection.artifact;
  if (stageId) params.set("stage", String(stageId));
  if (artifactId) params.set("artifact", String(artifactId));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const serializeOperatorSelection = serializeViewSelection;

export function parseBatchContext(search = currentSearch()) {
  const params = new URLSearchParams(search || "");
  const batchId = params.get("batch_id");
  if (params.get("from") !== "batch" || !batchId) return null;
  return {
    from: "batch",
    batchId,
    returnUrl: `/p/${encodeURIComponent(batchId)}`,
    candidateId: null,
    selectedIds: [],
    scrollTop: 0,
  };
}

const REVIEW_KIND_TO_STAGE = { script_lock: "script", creative_lock: "assets", sample: "sample" };
const INTERNAL_STATUS = {
  pending: "未开始", in_progress: "制作中", awaiting_human: "等待确认",
  completed: "已完成", failed: "处理失败",
};

function stageIdOf(stage) {
  const id = String(stage?.id || stage?.name || "");
  return id === "scenePlan" ? "scene_plan" : id;
}

function statusIs(stage, expected) {
  const raw = stage?.status;
  return raw === expected || raw === INTERNAL_STATUS[expected];
}

function reviewGateId(project, stages) {
  const pending = project?.pending_review;
  const fromPending = REVIEW_KIND_TO_STAGE[pending?.kind] || pending?.stage || pending?.gate;
  if (fromPending && stages.some((stage) => stageIdOf(stage) === fromPending)) return fromPending;
  const awaiting = stages.find((stage) => statusIs(stage, "awaiting_human"));
  return awaiting ? stageIdOf(awaiting) : null;
}

function defaultStageId(project, stages, gate) {
  if (gate && stages.some((stage) => stageIdOf(stage) === gate)) return gate;
  const completed = stages.filter((stage) => statusIs(stage, "completed"));
  if (completed.length) return stageIdOf(completed[completed.length - 1]);
  const workspaceId = stageIdOf({ id: project?.workspace?.stage_id });
  return stages.some((stage) => stageIdOf(stage) === workspaceId) ? workspaceId : stageIdOf(stages[0]) || null;
}

function updateUrl(selection) {
  if (typeof window === "undefined" || !window.history?.replaceState) return;
  const query = serializeViewSelection(selection, window.location.search);
  const next = `${window.location.pathname}${query}${window.location.hash || ""}`;
  window.history.replaceState(window.history.state, "", next);
}

export function createOperatorStore(initialSearch = currentSearch()) {
  const initialSelection = parseViewSelection(initialSearch);
  let selectionSignature = null;
  let snapshot = {
    viewState: "loading", project: null, reviewGateId: null,
    selectedStageId: initialSelection.stageId, selectedArtifactId: initialSelection.artifactId,
    message: "正在读取项目进度", session: null, drafts: {}, previews: {}, conflict: null,
    navigation: parseBatchContext(initialSearch),
  };
  const listeners = new Set();
  const emit = () => listeners.forEach((listener) => listener(snapshot));
  return {
    subscribe(listener) { listeners.add(listener); listener(snapshot); return () => listeners.delete(listener); },
    get() { return snapshot; },
    setLoading() { snapshot = { ...snapshot, viewState: "loading", message: "正在读取项目进度" }; emit(); },
    setSession(session) { snapshot = { ...snapshot, session }; emit(); },
    setProject(project) {
      const stages = Array.isArray(project?.stages) ? project.stages : [];
      const gate = reviewGateId(project, stages);
      const pending = project?.pending_review || {};
      const gateStage = stages.find((stage) => stageIdOf(stage) === gate);
      const signature = [project?.revision || "", gate || "", gateStage?.version ?? gateStage?.editor?.version ?? "",
        pending.subject_hash || "", pending.subject_version || ""].join("|");
      const changed = selectionSignature !== null && selectionSignature !== signature;
      const models = buildApprovalStages(project);
      const modelById = new Map(models.map((stage) => [stage.stageId, stage]));
      const requestedStage = changed ? null : snapshot.selectedStageId;
      const urlStage = changed ? null : initialSelection.stageId;
      const candidateStage = requestedStage || urlStage;
      const selected = candidateStage && modelById.has(candidateStage)
        ? candidateStage : defaultStageId(project, stages, gate);
      const model = modelById.get(selected);
      const requestedArtifact = changed ? null : snapshot.selectedArtifactId;
      const urlArtifact = changed ? null : initialSelection.artifactId;
      const artifacts = model?.artifacts || [];
      const candidateArtifact = requestedArtifact || urlArtifact;
      const artifact = candidateArtifact && artifacts.some((item) => item.id === candidateArtifact)
        ? candidateArtifact : artifacts[0]?.id || null;
      const viewState = stages.length === 0 ? "empty" : project?.legacy?.upgrade_available ? "degraded"
        : project?.pending_review ? "awaiting" : project?.summary?.progress_percent === 100 ? "completed" : "ready";
      selectionSignature = signature;
      snapshot = { ...snapshot, project, reviewGateId: gate, selectedStageId: selected,
        selectedArtifactId: artifact, viewState, message: "" }; updateUrl({ stageId: selected, artifactId: artifact }); emit();
    },
    setDraft(stage, draft) { snapshot = { ...snapshot, drafts: { ...snapshot.drafts, [stage]: draft } }; emit(); },
    setPreview(stage, preview) { snapshot = { ...snapshot, previews: { ...snapshot.previews, [stage]: preview } }; emit(); },
    setConflict(conflict) { snapshot = { ...snapshot, conflict }; emit(); },
    setError(message = "项目进度暂时无法读取，请稍后重试") { snapshot = { ...snapshot, viewState: "error", message }; emit(); },
    selectStage(stageId) {
      const model = buildApprovalStages(snapshot.project).find((stage) => stage.stageId === stageId);
      if (!model) return;
      const artifactId = model.artifacts[0]?.id || null;
      snapshot = { ...snapshot, selectedStageId: stageId, selectedArtifactId: artifactId };
      updateUrl({ stageId, artifactId }); emit();
    },
    selectArtifact(artifactId) {
      const model = buildApprovalStages(snapshot.project).find((stage) => stage.stageId === snapshot.selectedStageId);
      if (!model?.artifacts.some((artifact) => artifact.id === artifactId)) return;
      snapshot = { ...snapshot, selectedArtifactId: artifactId };
      updateUrl({ stageId: snapshot.selectedStageId, artifactId }); emit();
    },
    returnToReviewGate() {
      const stageId = snapshot.reviewGateId;
      if (!stageId) return;
      const model = buildApprovalStages(snapshot.project).find((stage) => stage.stageId === stageId);
      const artifactId = model?.artifacts[0]?.id || null;
      snapshot = { ...snapshot, selectedStageId: stageId, selectedArtifactId: artifactId };
      updateUrl({ stageId, artifactId }); emit();
    },
    resetToReviewGate() {
      const stageId = snapshot.reviewGateId;
      if (!stageId) return;
      const model = buildApprovalStages(snapshot.project).find((stage) => stage.stageId === stageId);
      const artifactId = model?.artifacts[0]?.id || null;
      snapshot = { ...snapshot, selectedStageId: stageId, selectedArtifactId: artifactId };
      updateUrl({ stageId, artifactId }); emit();
    },
    setNavigation(navigation) { snapshot = { ...snapshot, navigation }; emit(); },
    rememberBatchScroll(scrollTop) {
      if (!snapshot.navigation) return;
      snapshot = { ...snapshot, navigation: { ...snapshot.navigation, scrollTop: Number(scrollTop) || 0 } };
      emit();
    },
  };
}

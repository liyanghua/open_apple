export function createOperatorStore() {
  let snapshot = {
    viewState: "loading",
    project: null,
    selectedStageId: null,
    message: "正在读取项目进度",
  };
  const listeners = new Set();

  const emit = () => listeners.forEach((listener) => listener(snapshot));

  return {
    subscribe(listener) {
      listeners.add(listener);
      listener(snapshot);
      return () => listeners.delete(listener);
    },
    setLoading() {
      snapshot = { ...snapshot, viewState: "loading", message: "正在读取项目进度" };
      emit();
    },
    setProject(project) {
      const stages = Array.isArray(project?.stages) ? project.stages : [];
      const preserved = stages.some((stage) => stage.id === snapshot.selectedStageId)
        ? snapshot.selectedStageId
        : project?.workspace?.stage_id || stages[0]?.id || null;
      const viewState = stages.length === 0
        ? "empty"
        : project?.legacy?.upgrade_available
          ? "degraded"
          : project?.pending_review
            ? "awaiting"
            : project?.summary?.progress_percent === 100
              ? "completed"
              : "ready";
      snapshot = { ...snapshot, project, selectedStageId: preserved, viewState, message: "" };
      emit();
    },
    setError() {
      snapshot = {
        ...snapshot,
        viewState: "error",
        message: "项目进度暂时无法读取，请稍后重试",
      };
      emit();
    },
    selectStage(stageId) {
      snapshot = { ...snapshot, selectedStageId: stageId };
      emit();
    },
  };
}

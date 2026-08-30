// 单条审批工作台：只读展示候选事实、五项确认与通过/退回主动作。
// 不含编辑器、草稿、版本历史或影响计算；技术字段只进入“查看制作记录”折叠区。
// 数据全部来自现有 operator-state 投影与 review API
// （script_editor / asset_review / sample_review / delivery_review 均为只读事实）。
import { decideReview, fetchProjectState } from "./api.js";
import { parseBatchContext } from "./store.js";
import {
  STAGE_LABELS,
  stageLabelKey,
  GATE_STAGE_IDS,
  GATE_LABELS,
  GATE_DETAILS,
  CONFIRMATION_ITEMS,
  CONFIRMATION_VALUE_LABELS,
  APPROVAL_COPY,
} from "./language.js";

const byId = (id) => document.getElementById(id);

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = String(text);
  return element;
}

function detailRow(label, value) {
  const row = node("div", "approval-detail-row");
  row.append(node("span", "approval-detail-label", label), node("strong", "approval-detail-value", value || "暂未提供"));
  return row;
}

function setTestId(element, testId) {
  if (testId) element.dataset.testid = testId;
  return element;
}

export function hasReviewPermission(project) {
  return (project?.permissions || []).includes("review");
}

const KIND_TO_STAGE = { script_lock: "script", creative_lock: "assets", sample: "sample" };
const GATE_TO_INDEX = { script: 1, assets: 2, sample: 3 };

export function isApprovalShellActive(project, snapshot) {
  if (!project) return false;
  // 批级驾驶舱保留原壳（横向比较 + 统一提交入口）。
  if (project.workspace?.editor?.type === "batch_review") return false;
  const hasPending = Boolean(project.pending_review?.review_id);
  const navigation = snapshot.navigation || parseBatchContext();
  // 三种合法入口：审批只读模式 / 存在待确认内容 / 带批次导航上下文。
  if (project.workspace?.view_mode === "approval" || hasPending || navigation) return true;
  // 直接访问的单条项目同样进入审批壳（只读展示，无批次上下文即无返回批量入口）。
  return true;
}

function stageById(project, stageId) {
  return (project.stages || []).find((stage) => stage.id === stageId) || null;
}

function editorDataFor(project, stageId) {
  const editor = stageById(project, stageId)?.editor;
  return editor?.data || {};
}

function currentGateId(project) {
  const pending = project.pending_review;
  if (pending?.kind && KIND_TO_STAGE[pending.kind]) return KIND_TO_STAGE[pending.kind];
  const stages = project.stages || [];
  const failing = stages.find((stage) => stage.status === "处理失败");
  if (failing) return failing.id;
  const awaiting = stages.find((stage) => stage.status === "等待确认");
  if (awaiting) return awaiting.id;
  const upcoming = stages.find((stage) => stage.status !== "已完成" && stage.status !== "未开始");
  if (upcoming) return upcoming.id;
  const pendingStep = stages.find((stage) => stage.status === "未开始");
  if (pendingStep) return pendingStep.id;
  return "done";
}

function currentGateDetail(project) {
  const rawId = currentGateId(project);
  const gateId = (rawId === "compose" || rawId === "publish") ? "done" : rawId;
  const pending = project.pending_review;
  const detail = GATE_DETAILS[gateId] || GATE_DETAILS.done;
  return {
    gateId,
    detail,
    label: gateId === "done" ? "查看成片" : (GATE_LABELS[gateId] || "制作步骤"),
    version: pending?.subject_version || stageById(project, rawId)?.version || 1,
    hasPending: Boolean(pending),
  };
}

// ---------------------------------------------------------------------------
// 顶部上下文 + 轻量九步进度
// ---------------------------------------------------------------------------

function renderTopbar(project, snapshot) {
  const state = byId("approval-meta-state");
  if (state) {
    const pending = project.pending_review;
    state.textContent = pending
      ? APPROVAL_COPY.stateAwaiting
      : project.summary?.progress_percent === 100 ? APPROVAL_COPY.stateDone : "制作中";
    state.classList.toggle("is-waiting", Boolean(pending));
  }
  const note = byId("approval-note");
  if (note) {
    const pending = project.pending_review;
    note.textContent = pending
      ? (pending.summary || "内容已准备完成，等待人工确认")
      : currentGateDetail(project).hasPending ? "内容已准备完成，等待人工确认"
      : (stageById(project, currentGateId(project))?.summary || project.summary?.current_task || "项目正在按计划推进");
  }
  const returnLink = byId("approval-return-batch");
  if (returnLink) {
    const navigation = snapshot.navigation;
    returnLink.hidden = !navigation;
    if (navigation) {
      returnLink.href = navigation.returnUrl;
      returnLink.onclick = () => {
        try { sessionStorage.setItem(`batch-scroll:${navigation.batchId}`, String(navigation.scrollTop || 0)); } catch { /* no-op */ }
      };
    }
  }
}

function renderRail(project) {
  const rail = byId("approval-rail");
  if (!rail) return;
  rail.replaceChildren();
  const stages = project.stages || [];
  const gateCount = stages.filter((stage) => GATE_STAGE_IDS.includes(stage.id)).length;
  const railTitle = byId("approval-rail-title");
  if (railTitle) railTitle.textContent = `制作进度 · 共 ${stages.length || 9} 步`;
  const railHint = byId("approval-rail-hint");
  if (railHint) railHint.textContent = `${gateCount} 步需要人工确认 · 其余由系统自动完成`;
  const awaitingStage = stages.find((stage) => stage.status === "等待确认");
  const activeGateId = currentGateId(project);
  stages.forEach((stage) => {
    const isGate = GATE_STAGE_IDS.includes(stage.id);
    const isCurrent = stage.id === activeGateId;
    const isDone = stage.status === "已完成";
    const cls = ["approval-step"];
    if (isGate) cls.push("is-gate");
    if (isDone) cls.push("is-done");
    if (isCurrent) cls.push("is-current");
    if (stage.status === "处理失败") cls.push("is-failed");
    const card = node("div", cls.join(" "));
    card.dataset.stageId = stage.id;
    const role = node("span", "approval-step-role", isGate ? `第 ${GATE_TO_INDEX[stage.id] || 1} 次确认` : "系统自动");
    const name = node("b", "", stage.label || STAGE_LABELS[stageLabelKey(stage.id)] || "制作步骤");
    const stateText = stage.status === "等待确认" && isCurrent ? "现在需要你确认" : stage.status;
    card.append(role, name, node("small", "", stateText));
    card.addEventListener("click", () => {
      rail.querySelectorAll(".approval-step").forEach((item) => item.classList.remove("is-selected"));
      card.classList.add("is-selected");
      const main = byId("approval-main");
      if (main) main.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    rail.append(card);
  });
  const flownote = byId("approval-flownote");
  if (flownote) {
    const pending = project.pending_review;
    const next = kindToFlownote(pending?.kind);
    flownote.textContent = next || (currentGateDetail(project).detail.heading ? `你现在要做：${currentGateDetail(project).detail.heading}` : "项目正在按计划推进。");
  }
}

function kindToFlownote(kind) {
  if (kind === "sample") return "你现在要做：查看样片并确认效果。确认通过后，系统会自动完成精剪和成片；最终检查不通过时会停下来处理，不会交付有问题的视频。";
  if (kind) return "你现在要做：确认当前内容。确认通过后，系统会自动继续制作。";
  return null;
}

// ---------------------------------------------------------------------------
// 本次确认材料（看什么）
// ---------------------------------------------------------------------------

function sampleFacts(project) {
  const data = editorDataFor(project, "sample");
  const trace = data.execution_trace || {};
  const summary = trace.summary || {};
  const counts = summary.status_counts || {};
  const shots = trace.shots || [];
  const tracks = data.audio_tracks || [];
  const evaluation = data.evaluation;
  const advisory = evaluation?.advisory || {};
  const fails = evaluation?.hard_gate_fails || [];
  return {
    videoUrl: data.preview_url,
    posterUrl: data.poster_url,
    duration: data.duration_seconds,
    qaStatus: data.qa_status,
    summaryText: data.review_summary,
    shots,
    counts,
    tracks,
    evaluation,
    advisory: advisory.summary || "",
    fails,
    narrationText: shots.map((shot) => shot.planned?.screen_copy || "").filter(Boolean).join("；"),
  };
}

function factsForGate(project, gateId) {
  if (gateId === "script") {
    const data = editorDataFor(project, "script");
    return { ...data, sections: data.sections || [] };
  }
  if (gateId === "assets") {
    const data = editorDataFor(project, "assets");
    return { ...data, items: data.items || [] };
  }
  if (gateId === "done") {
    const data = editorDataFor(project, "compose");
    const delivery = editorDataFor(project, "publish");
    const payload = Object.keys(delivery || {}).length ? delivery : data;
    return {
      videoUrl: payload.player?.video_url || payload.download_url,
      posterUrl: payload.player?.poster_url,
      duration: payload.player?.duration_seconds ?? payload.duration_seconds,
      qaStatus: payload.qa_status,
      formatLabel: payload.format_label,
      evaluation: payload.evaluation || null,
    };
  }
  return sampleFacts(project);
}

function materialCard(label, detail, icon, active) {
  const button = node("button", `approval-artifact${active ? " is-on" : ""}`);
  button.type = "button";
  button.dataset.artifact = label;
  button.append(
    node("span", "approval-artifact-icon", icon || "▸"),
    (() => {
      const body = node("span", "approval-artifact-body");
      body.append(node("b", "", label), node("small", "", detail));
      return body;
    })(),
  );
  return button;
}

function renderApprovalMaterialsSample(facts, container) {
  container.append(materialCard("样片", facts.videoUrl ? `${Math.round(facts.duration || 0)} 秒 · ${facts.qaStatus || ""}` : "尚未生成", "▶", true));
  const shotText = facts.shots.length
    ? `${facts.counts.executed ?? facts.shots.length} 个镜头按方案完成`
    : "暂无镜头对照";
  container.append(materialCard("镜头对照", shotText, "▦"));
  const subText = facts.narrationText ? "口播和字幕已生成" : "暂无口播字幕";
  container.append(materialCard("字幕和口播", subText, "字"));
  const sound = facts.tracks.length
    ? facts.tracks.map((track) => track.label || track.kind).join("、")
    : "口播和背景音乐";
  container.append(materialCard("声音效果", sound, "♪"));
  container.append(materialCard("系统检查", facts.qaStatus || "等待检查", "✓"));
  const advice = facts.fails.length ? `${facts.fails.length} 项需要处理` : facts.advisory ? "整体正常 · 建议通过" : "尚未给出建议";
  container.append(materialCard("系统建议", advice, "↗"));
  container.append(materialCard("制作依据", "文案、镜头和素材方案", "↳"));
  if (facts.qaStatus === "检查通过" && !facts.evaluation) {
    container.append(node("p", "approval-left-warn", APPROVAL_COPY.reportIncomplete));
  }
  const note = node("p", "approval-left-note");
  note.append(node("strong", "", "你只需要看最终效果"), document.createTextNode("：系统处理过程和重复尝试已自动收起。如有问题，可直接指出哪一秒、哪个画面需要修改。"));
  container.append(note);
}

function renderApprovalMaterialsScript(facts, container) {
  container.append(materialCard("制作脚本", facts.sections?.length ? `${facts.sections.length} 段${facts.duration ? ` · ${Math.round(facts.duration)} 秒` : ""}` : "等待生成", "字", true));
  container.append(materialCard("制定依据", "创意方案与已确认卖点", "↳"));
  container.append(node("p", "approval-left-note", "确认通过后，系统会按这段脚本开始制作；如有错字或表述问题，请退回并说明位置。"));
}

function renderApprovalMaterialsAssets(facts, container) {
  container.append(materialCard("生成清单", facts.items?.length ? `${facts.planned_count ?? facts.items.length} 项 · ${facts.prepared_count ?? 0} 项已就绪` : "等待生成", "▦", true));
  for (const item of (facts.items || []).slice(0, 8)) {
    container.append(materialCard(item.label || item.type || "材料", item.state_label || item.status || "待确认", "•"));
  }
  container.append(node("p", "approval-left-note", "确认清单无误后，系统才会开始生成画面和声音；费用与预算请一并确认。"));
}

function renderApprovalMaterialsDone(facts, container) {
  container.append(materialCard("成片", facts.videoUrl ? `${Math.round(facts.duration || 0)} 秒 · ${facts.qaStatus || ""}` : "尚未生成", "▶", true));
  container.append(materialCard("交付信息", facts.formatLabel || "竖屏视频", "↳"));
  container.append(materialCard("系统检查", facts.qaStatus || "等待检查", "✓"));
  container.append(node("p", "approval-left-note", "这是最终成片。确认无误后即可交付；发现问题请退回修改。"));
}

function renderApprovalMaterials(project) {
  const container = byId("approval-materials");
  if (!container) return;
  container.replaceChildren();
  container.append(node("p", "approval-eyebrow", APPROVAL_COPY.materialsEyebrow));
  container.append(node("h2", "approval-materials-heading", APPROVAL_COPY.materialsHeading));
  const gateId = currentGateDetail(project).gateId;
  const facts = factsForGate(project, gateId);
  if (gateId === "done") renderApprovalMaterialsDone(facts, container);
  else if (gateId === "script") renderApprovalMaterialsScript(facts, container);
  else if (gateId === "assets") renderApprovalMaterialsAssets(facts, container);
  else renderApprovalMaterialsSample(facts, container);
}

// ---------------------------------------------------------------------------
// 视频与说明（看什么 → 判断什么）
// ---------------------------------------------------------------------------

function playerFor(facts, gateId) {
  const wrap = node("div", "approval-player");
  if (!facts.videoUrl) {
    const empty = node("div", "approval-player-empty");
    empty.append(node("p", "approval-muted", APPROVAL_COPY.missingMedia));
    empty.append(node("p", "approval-recover-hint", "请重新拉取最新结果；若仍缺失请联系制作人员。"));
    wrap.append(empty);
    return wrap;
  }
  const video = document.createElement("video");
  video.className = "approval-video";
  video.controls = true;
  video.playsInline = true;
  video.preload = "none";
  if (facts.posterUrl) video.poster = facts.posterUrl;
  video.src = facts.videoUrl;
  video.setAttribute("aria-label", gateId === "done" ? "成片预览" : "样片预览");
  video.addEventListener("error", () => {
    wrap.querySelector(".approval-player-error")?.remove();
    wrap.append(node("p", "approval-player-error", APPROVAL_COPY.playbackFailed));
  });
  wrap.append(video);
  return wrap;
}

function renderApprovalMedia(facts, gateId) {
  const media = byId("approval-media");
  if (!media) return;
  media.replaceChildren();
  media.append(playerFor(facts, gateId));
}

function deliverLine(kind, title, detail) {
  const item = node("div", `approval-delivery${kind === "warn" ? " is-warn" : ""}`);
  item.append(node("i", "", kind === "warn" ? "!" : "✓"));
  const body = node("div", "");
  body.append(node("b", "", title), node("small", "", detail));
  item.append(body);
  return item;
}

function renderGateCopy(facts, gateId, project) {
  const box = byId("approval-gate-copy");
  if (!box) return;
  box.replaceChildren();
  const gate = currentGateDetail(project);
  const kicker = node("span", "approval-kicker", `${gateId === "done" ? "最终确认" : `第 ${GATE_TO_INDEX[gateId] || 1} 次确认`} · ${gate.label}`);
  box.append(kicker);
  box.append(node("h2", "approval-gate-heading", gate.detail.heading));
  box.append(node("p", "approval-gate-intro", gate.detail.intro));
  const deliveries = node("div", "approval-deliveries");
  if (gateId === "sample") {
    const executed = facts.counts?.executed ?? facts.shots?.length ?? 0;
    deliveries.append(deliverLine("ok", `${executed} 个镜头都按已确认的方案制作`, "可以查看每个镜头使用了哪段素材、想表达什么，以及是否按方案完成。"));
    const narration = (facts.tracks || []).some((track) => String(track.kind || track.label || "").includes("口播") || String(track.kind || "").includes("narration"));
    deliveries.append(deliverLine(narration && facts.narrationText ? "ok" : "warn", "口播和字幕已经配好", "每句口播都有对应字幕，字幕位置不会挡住主要画面。"));
    if (facts.fails?.length || facts.advisory) {
      deliveries.append(deliverLine("warn", "系统检查没有发现问题，但建议你确认", facts.fails?.[0]?.message || facts.advisory));
    }
  } else if (gateId === "done") {
    deliveries.append(deliverLine(facts.qaStatus === "检查通过" ? "ok" : "warn", "系统检查通过", facts.qaStatus === "检查通过" ? "画面、声音和文件均正常，可以交付。" : "请先处理检查中的问题。"));
  } else if (gateId === "script") {
    deliveries.append(deliverLine("ok", "文案已按已确认的方案整理", "确认没有错别字和表述问题后，系统开始制作。"));
  } else if (gateId === "assets") {
    deliveries.append(deliverLine("ok", "制作清单已准备完成", "画面、声音、素材和费用都已列明，确认后开始生成。"));
  }
  box.append(deliveries);
}

function renderApprovalTimeline(facts, gateId) {
  const box = byId("approval-timeline");
  if (!box) return;
  box.replaceChildren();
  if (gateId !== "sample") { box.hidden = true; return; }
  box.hidden = false;
  const head = node("div", "approval-timeline-head");
  const duration = (Math.round((facts.duration || 0) * 10) / 10).toFixed(1);
  head.append(node("span", "", "画面和声音对照 · 点击片段可跳到对应位置"), node("span", "", `00:00 ──────── 00:${duration}`));
  box.append(head);
  const lanes = node("div", "approval-lanes");
  const video = byId("approval-media")?.querySelector("video");
  const addLane = (label, segments) => {
    const lane = node("div", "approval-lane");
    lane.append(node("b", "", label));
    const segWrap = node("div", "approval-segments");
    (segments || []).forEach((segment) => {
      const seg = node("span", "approval-segment", "");
      seg.style.flex = String(segment.flex || 1);
      if (segment.start != null && video) {
        seg.addEventListener("click", () => { video.currentTime = segment.start; video.play().catch(() => {}); });
      }
      segWrap.append(seg);
    });
    lane.append(segWrap);
    lanes.append(lane);
  };
  addLane("画面", (facts.shots || []).map((shot) => ({ start: shot.actual?.timeline_start_seconds, flex: 1 })));
  const narration = (facts.tracks || []).find((track) => String(track.kind || track.label || "").includes("口播") || String(track.kind || "").includes("narration"));
  addLane("口播", narration?.state === "present" ? [{ flex: 3 }] : []);
  addLane("字幕", facts.narrationText ? [{ flex: 3 }] : []);
  const music = (facts.tracks || []).find((track) => String(track.kind || track.label || "").includes("音乐") || String(track.kind || "").includes("music") || String(track.kind || "").includes("BGM"));
  addLane("音乐", music?.state === "present" ? [{ flex: 4 }] : []);
  box.append(lanes);
}

function renderApprovalOutcome() {
  const box = byId("approval-outcome");
  if (!box) return;
  box.replaceChildren();
  const mini = (title, items, cls) => {
    const card = node("div", "approval-mini");
    card.append(node("h3", "", title));
    const p = node("p", "");
    items.forEach((item, index) => {
      p.append(node("span", cls, `${index + 1}. `), document.createTextNode(item));
      if (index < items.length - 1) p.append(document.createElement("br"));
    });
    card.append(p);
    return card;
  };
  box.append(mini(APPROVAL_COPY.approveOutcomeTitle, APPROVAL_COPY.approveOutcome, "is-green"));
  box.append(mini(APPROVAL_COPY.rejectOutcomeTitle, APPROVAL_COPY.rejectOutcome, "is-amber"));
}

// ---------------------------------------------------------------------------
// 五项确认与主动作（判断什么 → 之后发生什么）
// ---------------------------------------------------------------------------

function mapReviewError(error) {
  if (!error) return "操作暂时无法完成";
  if (error.code === "stale" || error.code === "review_stale") return APPROVAL_COPY.stale;
  if (error.code === "review_already_decided") return APPROVAL_COPY.alreadyDecided;
  if (error.code === "forbidden") return APPROVAL_COPY.forbidden;
  if (error.code === "validation_failed") return APPROVAL_COPY.validationFailed;
  return error.message || "操作暂时无法完成";
}

const ISSUE_TAG_BY_KEY = {
  creative_direction: "unclear_promise",
  hook: "weak_hook",
  proof: "information_gap",
  pacing: "timing",
  readability: "mobile_illegibility",
};

function renderConfirmationSample(facts, project, gate) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", "样片确认"));
  head.append(node("small", "", `第 ${gate.version} 版 · ${Math.round(facts.duration || 0)} 秒`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", APPROVAL_COPY.fiveChecksHeading));
  box.append(node("p", "approval-confirm-intro", APPROVAL_COPY.fiveChecksIntro));
  const canReview = hasReviewPermission(project);
  const selections = {};
  const issueReasons = {};
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  const cards = node("div", "approval-check-list");
  CONFIRMATION_ITEMS.forEach((item, index) => {
    const card = node("div", "approval-check-card");
    card.append(node("b", "", `${index + 1} ${item.title}`), node("p", "approval-check-prompt", item.prompt));
    const choices = node("div", "approval-check-choices");
    Object.entries(CONFIRMATION_VALUE_LABELS).forEach(([value, label]) => {
      const button = node("button", "approval-check-value", label);
      button.type = "button";
      button.disabled = !canReview;
      button.addEventListener("click", () => {
        selections[item.key] = value;
        issueReasons[item.key] = `${item.title}：${CONFIRMATION_VALUE_LABELS[value]}`;
        choices.querySelectorAll("button").forEach((btn) => btn.classList.remove("is-selected"));
        button.classList.add("is-selected");
        updateActions();
      });
      choices.append(button);
    });
    card.append(choices);
    cards.append(card);
  });
  box.append(cards);
  const outcomes = node("div", "approval-confirm-outcome");
  outcomes.append(node("b", "", "确认后会怎样"));
  outcomes.append(node("p", "", "不会产生新的付费素材 · 系统自动继续制作 · 最终检查通过后才会生成可交付视频。"));
  box.append(outcomes);
  const reject = node("button", "approval-reject", APPROVAL_COPY.reject);
  reject.type = "button";
  reject.disabled = !canReview;
  reject.dataset.testid = "approval-reject";
  const approve = node("button", "approval-approve", APPROVAL_COPY.approve);
  approve.type = "button";
  approve.disabled = !canReview;
  approve.dataset.testid = "approval-approve";
  const actions = node("div", "approval-confirm-actions");
  actions.append(reject, approve);
  box.append(actions, message);
  const updateActions = () => {
    const selectedKeys = Object.keys(selections);
    const allPass = selectedKeys.length === CONFIRMATION_ITEMS.length
      && selectedKeys.every((key) => selections[key] === "pass");
    approve.disabled = !canReview || !allPass;
    reject.disabled = !canReview || selectedKeys.length === 0;
    message.textContent = !canReview
      ? APPROVAL_COPY.forbidden
      : allPass ? "五项都已确认通过，可以继续。" : selectedKeys.length ? "有一项或多项需要修改，请退回。" : "请确认这 5 项。";
  };
  const submit = async (decision) => {
    const review = project.pending_review;
    if (!review?.review_id || review.subject_hash == null) {
      message.textContent = "确认信息尚未准备好，请刷新后重试。";
      return;
    }
    approve.disabled = true;
    reject.disabled = true;
    try {
      // 五项确认的 effect_confirmations 与 review_id / 内容 hash / 版本一起
      // 写入现有 review 服务；拒绝时附带问题标签，供批量质量统计使用。
      if (decision === "approved") {
        await decideReview(project.project_id, review.review_id, "approved", "样片效果确认通过", selections, review.subject_version, review.subject_hash, null);
      } else {
        const reasons = Object.keys(issueReasons).length ? Object.values(issueReasons).join("；") : "请按意见调整样片";
        const tags = [...new Set(Object.entries(selections).filter(([, value]) => value !== "pass").map(([key]) => ISSUE_TAG_BY_KEY[key]).filter(Boolean))];
        await decideReview(project.project_id, review.review_id, "rejected", reasons, selections, review.subject_version, review.subject_hash, tags.length ? tags : null);
      }
      message.textContent = decision === "approved" ? "样片已确认，正在继续制作。" : "调整意见已提交，将按意见修改后再次确认。";
      requestApprovalRefresh(project.project_id);
    } catch (error) {
      message.textContent = mapReviewError(error);
      updateActions();
    }
  };
  approve.addEventListener("click", () => submit("approved"));
  reject.addEventListener("click", () => submit("rejected"));
}

function renderConfirmationSimple(gate, project) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", gate.label));
  head.append(node("small", "", `第 ${gate.version} 版`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", gate.detail.confirmTitle));
  box.append(node("p", "approval-confirm-intro", gate.detail.intro));
  const canReview = hasReviewPermission(project);
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  const reasonBox = node("textarea", "approval-reason", "");
  reasonBox.placeholder = "如有问题，请在这里说明需要修改的地方（可选）";
  reasonBox.disabled = !canReview;
  const reject = node("button", "approval-reject", APPROVAL_COPY.reject);
  reject.type = "button";
  reject.disabled = !canReview;
  reject.dataset.testid = "approval-reject";
  const approve = node("button", "approval-approve", APPROVAL_COPY.approve);
  approve.type = "button";
  approve.disabled = !canReview;
  approve.dataset.testid = "approval-approve";
  const actions = node("div", "approval-confirm-actions");
  actions.append(reject, approve);
  box.append(reasonBox, actions, message);
  if (!canReview) message.textContent = APPROVAL_COPY.forbidden;
  const submit = async (decision) => {
    const review = project.pending_review;
    if (!review?.review_id || review.subject_hash == null) {
      message.textContent = "确认信息尚未准备好，请刷新后重试。";
      return;
    }
    approve.disabled = true;
    reject.disabled = true;
    try {
      const reason = decision === "approved" ? "内容确认通过" : (reasonBox.value || "请根据意见修改后再提交");
      await decideReview(project.project_id, review.review_id, decision, reason, null, review.subject_version, review.subject_hash, null);
      message.textContent = decision === "approved" ? "已确认，正在继续制作。" : "修改意见已提交。";
      requestApprovalRefresh(project.project_id);
    } catch (error) {
      message.textContent = mapReviewError(error);
      approve.disabled = !canReview;
      reject.disabled = !canReview;
    }
  };
  approve.addEventListener("click", () => submit("approved"));
  reject.addEventListener("click", () => submit("rejected"));
}

function renderConfirmationDone(gate, project, facts) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", "查看成片"));
  head.append(node("small", "", `第 ${gate.version} 版 · ${Math.round(facts.duration || 0)} 秒`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", gate.detail.confirmTitle));
  box.append(node("p", "approval-confirm-intro", `${facts.formatLabel || "纵向视频"} · ${facts.qaStatus || "等待检查"}。系统检查通过，交付确认在批量总览统一进行。`));
  const outcomes = node("div", "approval-confirm-outcome");
  outcomes.append(node("b", "", "确认后会怎样"));
  outcomes.append(node("p", "", "系统检查通过 · 单条页面不再重复审批 · 交付确认由批量总览统一完成。"));
  box.append(outcomes);
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  message.textContent = "无需在此确认：本条候选已完成成片检查。";
  box.append(message);
}

function renderConfirmationIdle(gate, project) {
  const box = byId("approval-confirmation");
  if (!box) return;
  box.replaceChildren();
  const head = node("div", "approval-confirm-head");
  head.append(node("span", "", gate.label));
  head.append(node("small", "", `第 ${gate.version} 版`));
  box.append(head);
  box.append(node("h2", "approval-confirm-title", gate.detail.confirmTitle));
  box.append(node("p", "approval-confirm-intro", gate.detail.intro));
  const message = setTestId(node("p", "approval-message", ""), "approval-message");
  const stage = (project.stages || []).find((item) => item.id === gate.gateId);
  message.textContent = stage?.status === "处理失败"
    ? "当前没有可以确认的内容：这一步处理失败，请查看制作记录或重新拉取最新结果。"
    : "当前没有需要确认的内容：这一步尚未准备完成，请重新拉取最新结果。";
  box.append(message);
}

function renderConfirmation(project) {
  const gate = currentGateDetail(project);
  if (gate.gateId === "sample" && project.pending_review) {
    renderConfirmationSample(factsForGate(project, "sample"), project, gate);
  } else if (gate.gateId === "done") {
    renderConfirmationDone(gate, project, factsForGate(project, "done"));
  } else if (!project.pending_review) {
    renderConfirmationIdle(gate, project);
  } else {
    renderConfirmationSimple(gate, project);
  }
}

// ---------------------------------------------------------------------------
// 制作记录（技术字段折叠区）+ 降级状态
// ---------------------------------------------------------------------------

function renderRecord(project) {
  const box = byId("approval-record");
  if (!box) return;
  box.replaceChildren();
  const gate = currentGateDetail(project);
  const facts = factsForGate(project, gate.gateId);
  const summary = project.summary || {};
  box.append(detailRow("当前步骤", summary.current_stage || "—"));
  box.append(detailRow("检查状态", facts.qaStatus || "待检查"));
  box.append(detailRow("时长", facts.duration ? `${Math.round(facts.duration)} 秒` : "暂未提供"));
  box.append(detailRow("内容版本", `第 ${gate.version} 版`));
  if (summary.spent_usd != null) box.append(detailRow("已花费", `$${Number(summary.spent_usd).toFixed(2)}`));
  if (facts.evaluation?.status) {
    box.append(detailRow("检查结论", facts.evaluation.status === "pass" ? "通过" : "存在待处理项"));
    box.append(detailRow("建议动作", facts.evaluation.recommended_action || "—"));
  }
  if (facts.audio_tracks?.length) {
    const labels = facts.audio_tracks.map((track) => `${track.label || track.kind}：${track.state_label || track.state || "未知"}`);
    box.append(detailRow("音轨明细", labels.join("、")));
  }
}

export function candidateUnavailable(project) {
  if (!project?.stages?.length) return true;
  const statuses = project.stages.map((stage) => stage.status);
  return statuses.every((status) => status === "处理失败");
}

// 通知 app.js 拉取最新快照并重渲染（不直接修改批量投影，读路径保持纯净）。
function requestApprovalRefresh(projectId) {
  fetchProjectState(projectId)
    .then((next) => document.dispatchEvent(new CustomEvent("approval-refresh-request", { detail: { project: next } })))
    .catch(() => { /* 保留当前已确认状态 */ });
}

// ---------------------------------------------------------------------------
// 主渲染
// ---------------------------------------------------------------------------

export function renderApprovalWorkbench(container, project, snapshot) {
  const shell = byId("approval-shell");
  if (shell) shell.hidden = false;
  document.title = `${APPROVAL_COPY.brand} · ${project.title || "项目"}`;
  if (candidateUnavailable(project)) {
    const main = byId("approval-main");
    const materials = byId("approval-materials");
    if (main) {
      main.replaceChildren();
      main.append(node("p", "approval-muted", APPROVAL_COPY.unavailable), node("p", "approval-recover-hint", "请返回批量总览重新拉取，或联系制作人员。"));
    }
    if (materials) materials.replaceChildren();
    return;
  }
  renderTopbar(project, snapshot);
  renderRail(project);
  renderApprovalMaterials(project);
  const gate = currentGateDetail(project);
  const facts = factsForGate(project, gate.gateId);
  renderApprovalMedia(facts, gate.gateId);
  renderGateCopy(facts, gate.gateId, project);
  renderApprovalTimeline(facts, gate.gateId);
  renderApprovalOutcome();
  renderConfirmation(project);
  renderRecord(project);
}

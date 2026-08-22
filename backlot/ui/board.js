// Backlot project board — renders BoardState and stays live via SSE.

import {
  STAGE_ICONS, el, fmtAgo, fmtClock, fmtDuration, fmtMoney,
  getJSON, mediaURL, subscribe, thumbURL, waveBars,
} from "/ui/lib.js";

const rawProjectPath = location.pathname.split("/p/")[1] || "";
const projectId = decodeURIComponent(rawProjectPath);
const encodedProjectId = encodeURIComponent(projectId);
const app = document.getElementById("app");
const modal = document.getElementById("modal");
const player = document.getElementById("player");

const THEME_KEY = "backlot.theme";
let currentTheme = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
let state = null;
let selectedStage = null;   // stage drawer open for this stage name
let activeRender = 0;
let replay = null;          // {t0, t1, t, playing} — replay mode when non-null
let firstPaint = true;

function applyTheme(theme) {
  currentTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = currentTheme;
  localStorage.setItem(THEME_KEY, currentTheme);
}

function renderThemeToggle() {
  const next = currentTheme === "light" ? "dark" : "light";
  return el("button", {
    class: "theme-toggle",
    type: "button",
    title: `Switch to ${next} theme`,
    "aria-label": `Switch to ${next} theme`,
    "aria-pressed": currentTheme === "light" ? "true" : "false",
    onclick: () => {
      applyTheme(next);
      render();
    },
  }, el("span", { class: "theme-toggle-icon", "aria-hidden": "true" }, currentTheme === "light" ? "☾" : "☀"));
}

applyTheme(currentTheme);

// ---------------------------------------------------------------------------
// header slate
// ---------------------------------------------------------------------------

function renderSlate(s) {
  const board = s.storyboard;
  const chips = [
    el("span", { class: "chip" }, `${s.pipeline.pipeline_type} pipeline`),
    board && board.total_duration_seconds
      ? el("span", { class: "chip" }, `${board.scenes.length} scenes · ${fmtDuration(board.total_duration_seconds)}`)
      : null,
    s.style_playbook ? el("span", { class: "chip" }, s.style_playbook) : null,
  ];

  const awaiting = s.stages.find((x) => x.status === "awaiting_human");
  const inProgress = s.stages.find((x) => x.status === "in_progress");
  const stalled = s.stages.find((x) => x.stalled);
  let liveEl;
  if (awaiting) {
    liveEl = el("span", { class: "live" }, el("span", { class: "dot" }), "◈ AWAITING YOU");
  } else if (stalled) {
    liveEl = el("span", { class: "live", style: "color:var(--red)" },
      el("span", { class: "dot", style: "background:var(--red);animation:none" }), "⚠ STALLED?");
  } else if (s.live || inProgress) {
    liveEl = el("span", { class: "live" }, el("span", { class: "dot" }), "LIVE");
  } else {
    liveEl = el("span", { class: "live idle" }, el("span", { class: "dot" }),
      `IDLE${s.last_activity ? " · " + fmtAgo(s.last_activity).toUpperCase() : ""}`);
  }

  const cost = el("div", { class: "cost" });
  if (s.cost) {
    const spent = s.cost.total_spent_usd ?? 0;
    const budget = spent + (s.cost.budget_remaining_usd ?? 0);
    const hasBudget = s.cost.budget_remaining_usd != null;
    const pct = hasBudget && budget > 0 ? Math.min(100, (spent / budget) * 100) : 0;
    cost.append(el("div", { class: "nums" }, el("b", {}, fmtMoney(spent)),
      hasBudget ? el("span", {}, ` / ${fmtMoney(budget)}`) : ""));
    if (hasBudget) {
      cost.append(el("div", { class: "bar" }, el("i", {
        class: pct > 90 ? "crit" : pct > 75 ? "warn" : "", style: `width:${pct}%`,
      })));
    }
    cost.append(el("div", { class: "label" }, "generation spend"));
  }

  return el("header", { class: "slate" },
    el("div", { class: "clapper" }),
    el("div", {},
      el("a", { class: "wordmark", href: "/", style: "text-decoration:none" }, "Backlot"),
      el("h1", {}, s.title),
    ),
    ...chips,
    el("div", { class: "spacer" }),
    renderThemeToggle(),
    liveEl,
    cost,
  );
}

// ---------------------------------------------------------------------------
// stage rail
// ---------------------------------------------------------------------------

function stageSub(st) {
  if (st.status === "awaiting_human") return "awaiting your approval\nreply in chat to continue";
  if (st.status === "in_progress" && st.stalled) {
    return `stalled? no activity for ${st.stalled_minutes}m\nask the agent for status`;
  }
  if (st.status === "in_progress" && st.partial_progress) {
    const done = st.partial_progress.completed_scene_ids;
    if (Array.isArray(done)) return `${done.length} scene${done.length === 1 ? "" : "s"} done`;
    return "in progress";
  }
  if (st.status === "in_progress") return "in progress";
  if (st.status === "failed") return st.error ? String(st.error).slice(0, 60) : "failed";
  if (st.timestamp) {
    const approved = st.gated && st.human_approved ? " · approved" : "";
    return fmtClock(st.timestamp) + approved;
  }
  return "";
}

function renderRail(s) {
  const rail = el("nav", { class: "rail" });
  let pendingIndex = 1;
  for (const st of s.stages) {
    const cls = st.status === "completed" ? "done"
      : st.status === "in_progress" ? (st.stalled ? "active stalled" : "active")
      : st.status === "awaiting_human" ? "await"
      : st.status === "failed" ? "failed" : "";
    const icon = STAGE_ICONS[st.status] || String(pendingIndex);
    if (!STAGE_ICONS[st.status]) pendingIndex += 1;
    const node = el("div", {
      class: `stage ${cls}${selectedStage === st.name ? " selected" : ""}${st.undeclared ? " undeclared" : ""}`,
      title: st.undeclared ? `"${st.name}" ran but isn't declared by this pipeline's manifest` : null,
      onclick: () => toggleDrawer(st.name),
    },
      el("span", { class: "line" }),
      el("span", { class: "node" }, icon),
      el("span", { class: "name" }, st.name),
      el("span", { class: "sub", style: "white-space:pre-line" },
        st.undeclared ? `${stageSub(st)}\nunlisted`.trim() : stageSub(st)),
    );
    rail.append(node);
  }
  return rail;
}

function toggleDrawer(stageName) {
  selectedStage = selectedStage === stageName ? null : stageName;
  render();
}

const STAGE_ARTIFACTS = {
  research: ["research_brief"],
  proposal: ["proposal_packet"],
  idea: ["brief"],
  script: ["script"],
  scene_plan: ["scene_plan"],
  assets: ["asset_manifest"],
  edit: ["edit_decisions"],
  compose: ["render_report", "final_review"],
  publish: ["publish_log"],
};

function artifactNamesForStage(st) {
  const declared = Array.isArray(st.produces) ? st.produces : [];
  const fallback = STAGE_ARTIFACTS[st.name] || [];
  return [...new Set([...declared, ...fallback].filter(Boolean))];
}

function reviewMetrics(review) {
  const nested = review && review.summary && typeof review.summary === "object"
    ? review.summary : {};
  return {
    critical: Number((review && review.critical) ?? nested.critical ?? 0),
    suggestions: Number((review && review.suggestions) ?? nested.suggestions ?? 0),
    nitpicks: Number((review && review.nitpicks) ?? nested.nitpicks ?? 0),
  };
}

function reviewSummaryText(review) {
  if (!review) return "";
  if (typeof review.summary === "string") return review.summary;
  const nested = review.summary && typeof review.summary === "object" ? review.summary : {};
  const counts = reviewMetrics(review);
  return [
    review.decision,
    `${counts.critical} critical`,
    `${counts.suggestions} suggestion${counts.suggestions === 1 ? "" : "s"}`,
    nested.review_focus_met ? `review focus ${nested.review_focus_met}` : null,
    nested.schema_validation,
  ].filter(Boolean).join(" · ");
}

function renderDrawer(s) {
  if (!selectedStage) return null;
  const st = s.stages.find((x) => x.name === selectedStage);
  if (!st) return null;

  const body = el("div", { class: "drawer-body" });

  if (st.review) {
    const metrics = reviewMetrics(st.review);
    const summary = reviewSummaryText(st.review);
    body.append(el("div", { class: "findings", style: "margin-bottom:12px" },
      el("span", { class: `f ${metrics.critical ? "crit" : ""}` }, `${metrics.critical} critical`),
      el("span", { class: `f ${metrics.suggestions ? "sugg" : ""}` }, `${metrics.suggestions} suggestions`),
      el("span", { class: "f" }, `${metrics.nitpicks} nitpicks`),
      summary ? el("span", { style: "font-size:calc(11.5px * var(--fs-scale));color:var(--text-2);margin-left:8px" }, summary) : null,
    ));
  }

  const names = artifactNamesForStage(st);
  let shown = false;
  for (const name of names) {
    const artifact = s.artifacts[name];
    if (!artifact) continue;
    shown = true;
    body.append(
      el("div", { class: "d-cat", style: "font-family:var(--mono);font-size:calc(9.5px * var(--fs-scale));color:var(--text-3);letter-spacing:.1em;text-transform:uppercase;margin:6px 0 4px" }, name),
    );
    if (name === "evaluation_report") {
      body.append(renderEvaluationCard(artifact));
      continue;
    }
    if (name === "sample_execution_trace") {
      body.append(renderTraceCard(artifact));
      continue;
    }
    if (name === "candidate_batch") {
      body.append(renderBatchCard(artifact));
      continue;
    }
    if (name === "repair") {
      body.append(renderRepairCard(artifact));
      continue;
    }
    if (name === "gold_sample") {
      body.append(renderGoldSetCard(artifact));
      continue;
    }
    body.append(el("pre", {}, JSON.stringify(artifact, null, 2)));
  }
  if (!shown) {
    body.append(el("div", { class: "hint" },
      st.status === "pending" ? "This stage hasn't run yet." : "No canonical artifact found on disk for this stage."));
  }

  return el("div", { class: "drawer" },
    el("div", { class: "drawer-head" },
      el("h3", {}, `${st.name} — ${st.status}`),
      st.gate_skipped ? el("span", { class: "gate-chip" }, "⚑ GATE SKIPPED") : null,
      st.versions > 1 ? el("span", { class: "ver-chip" }, `v${st.versions}`) : null,
      st.timestamp ? el("span", { class: "meta", style: "font-family:var(--mono);font-size:calc(10.5px * var(--fs-scale));color:var(--text-3)" }, st.timestamp) : null,
      el("span", { class: "close", onclick: () => toggleDrawer(st.name) }, "CLOSE ✕"),
    ),
    body,
  );
}

// ---------------------------------------------------------------------------
// evaluation card + execution trace card (Design_Review P0-2)
// ---------------------------------------------------------------------------

function statusChip(text, tone) {
  const colors = { pass: "#1f9d55", revise: "#b7791f", fail: "#c53030", executed: "#1f9d55", partial: "#b7791f", missing: "#c53030", not_in_sample: "#718096", bound: "#1f9d55", not_checked: "#718096" };
  return el("span", { class: "gate-chip", style: `background:${colors[tone] || "#718096"}22;color:${colors[tone] || "#718096"}` }, text);
}

function renderEvaluationCard(report) {
  if (!report || typeof report !== "object") return el("pre", {}, "{}");
  const gate = report.hard_gate || {};
  const failed = (gate.checks || []).filter((c) => c.status === "fail");
  const skipped = (gate.checks || []).filter((c) => c.status === "skip");
  const adv = report.creative_advisory || {};
  const nodes = [
    el("div", { class: "approval-facts" },
      el("div", { class: "approval-fact" }, el("span", {}, "硬门"), statusChip(report.status || "unknown", report.status)),
      el("div", { class: "approval-fact" }, el("span", {}, "建议动作"), el("b", {}, String(report.recommended_action || "—"))),
      el("div", { class: "approval-fact" }, el("span", {}, "judge / rubric"), el("b", {}, `${report.judge_version || "—"} / ${report.rubric_version || "—"}`)),
    ),
  ];
  if (failed.length) {
    nodes.push(el("div", { class: "d-cat", style: "color:#c53030;margin-top:8px" }, `未通过项（${failed.length}）`));
    for (const c of failed) {
      nodes.push(el("div", { class: "sp-slug", style: "color:var(--text-1)" },
        `${c.name} — ${c.message}`,
        el("span", { class: "tc" }, c.fixable ? "可修复" : "致命")));
      if (c.affected_shots && c.affected_shots.length) {
        nodes.push(el("div", { class: "sp-paren" }, `影响镜头：${c.affected_shots.join("、")}`));
      }
    }
  }
  if (skipped.length) {
    nodes.push(el("div", { class: "sp-paren" }, `未比对项（${skipped.length}）：${skipped.map((c) => c.name).join("、")}`));
  }
  if ((report.repair_targets || []).length) {
    nodes.push(el("div", { class: "d-cat", style: "margin-top:8px" }, `修复建议（${report.repair_targets.length}）`));
    for (const t of report.repair_targets) {
      nodes.push(el("div", { class: "sp-slug" }, `${t.action} ← ${t.check_id}${t.note ? ` · ${t.note}` : ""}`));
    }
  }
  nodes.push(el("div", { class: "d-cat", style: "margin-top:8px" }, "创意评审（advisory）"));
  if (adv.scored && Array.isArray(adv.dimensions) && adv.dimensions.length) {
    nodes.push(el("div", { class: "sp-paren", style: "margin-bottom:4px" }, adv.summary || ""));
    for (const dim of adv.dimensions) {
      nodes.push(el("div", { class: "sp-slug", style: "color:var(--text-1)" },
        `${dim.name} `,
        el("b", { style: dim.score >= 8 ? "color:#1f9d55" : dim.score >= 6 ? "color:#b7791f" : "color:#c53030" },
          String(dim.score)),
        dim.note ? el("span", { class: "tc" }, ` — ${dim.note}`) : null));
    }
  } else {
    nodes.push(el("div", { class: "sp-paren" }, adv.scored ? `已评分 · ${adv.summary || ""}` : `未评分 · ${adv.summary || "尚未运行 VLM 创意评审，不影响硬门"}`));
  }
  return el("div", { style: "padding:4px 0" }, nodes);
}

function renderTraceCard(trace) {
  if (!trace || typeof trace !== "object") return el("pre", {}, "{}");
  const nodes = [];
  const s = trace.summary || {};
  nodes.push(el("div", { class: "sp-meta" },
    `${s.planned_shot_count} 计划镜头 · ${s.included_shot_count} 进入样片 · 新增 ${s.new_content_count || 0}`));
  if (trace.audio_diff) {
    const a = trace.audio_diff;
    nodes.push(el("div", { class: "d-cat", style: "margin-top:8px" }, "音频轨对照"));
    nodes.push(el("div", { class: "sp-slug" }, statusChip(a.status, a.status), " ", a.summary));
    if (a.reason) nodes.push(el("div", { class: "sp-paren" }, a.reason));
  }
  if (trace.caption_diff) {
    const c = trace.caption_diff;
    nodes.push(el("div", { class: "d-cat", style: "margin-top:8px" }, "字幕对照"));
    nodes.push(el("div", { class: "sp-slug" }, statusChip(c.status, c.status), " ", c.summary));
  }
  if (trace.creative_rule_diff && trace.creative_rule_diff.rules) {
    const cr = trace.creative_rule_diff;
    nodes.push(el("div", { class: "d-cat", style: "margin-top:8px" }, "导演规则执行"));
    nodes.push(el("div", { class: "sp-paren" }, cr.summary));
    for (const r of cr.rules.slice(0, 8)) {
      nodes.push(el("div", { class: "sp-slug" }, statusChip(r.status === "bound" ? "bound" : r.status === "not_in_sample" ? "not_in_sample" : "not_checked", r.status), ` ${r.section} · ${shortText(r.rule, 60)}`));
    }
    if (cr.rules.length > 8) nodes.push(el("div", { class: "sp-fade" }, `… ${cr.rules.length - 8} more rules`));
  }
  const shots = trace.shots || [];
  if (shots.length) {
    nodes.push(el("div", { class: "d-cat", style: "margin-top:8px" }, "镜头执行"));
    for (const shot of shots.slice(0, 10)) {
      nodes.push(el("div", { class: "sp-slug" },
        shot.shot_id, " ", statusChip(shot.status_label || shot.status, shot.status),
        shot.deviation ? el("span", { class: "tc" }, ` · ${shot.deviation.reason || ""}`) : null));
    }
  }
  return el("div", { style: "padding:4px 0" }, nodes);
}

function renderGoldSetCard(goldset) {
  if (!goldset || typeof goldset !== "object") return el("pre", {}, "{}");
  const samples = goldset.samples || [];
  const counts = {gold: 0, silver: 0, bad: 0, hard_negative: 0};
  for (const item of samples) counts[item.tier] = (counts[item.tier] || 0) + 1;
  return el("div", { style: "padding:4px 0" },
    el("div", { class: "sp-meta" },
      `${samples.length} 样本 · gold ${counts.gold} / silver ${counts.silver} / bad ${counts.bad} / hard_negative ${counts.hard_negative}`),
    el("div", { class: "sp-paren" }, `judge ${goldset.judge_version || "—"} · rubric ${goldset.rubric_version || "—"}`),
  );
}

function renderRepairCard(repair) {
  if (!repair || typeof repair !== "object") return el("pre", {}, "{}");
  const targets = (repair.targets || []).map((t) => `${t.type}:${t.id}`).join("、");
  return el("div", { style: "padding:4px 0" },
    el("div", { class: "approval-facts" },
      el("div", { class: "approval-fact" }, el("span", {}, "动作"), statusChip(repair.action || "—", repair.render_route === "full_render" ? "partial" : "executed")),
      el("div", { class: "approval-fact" }, el("span", {}, "渲染路线"), el("b", {}, String(repair.render_route || "—"))),
      el("div", { class: "approval-fact" }, el("span", {}, "第几轮"), el("b", {}, String(repair.rework_round ?? "—"))),
    ),
    el("div", { class: "sp-slug" }, `目标：${targets || "—"}`),
    el("div", { class: "sp-paren" }, `问题标签：${(repair.issue_tags || []).join("、")}`),
    el("div", { class: "sp-paren" }, `影响阶段：${(repair.affected_stages || []).join("、")}`),
    repair.lock_compliant === false
      ? el("div", { class: "sp-paren", style: "color:#c53030" }, "违反锁定规则，需重新审批")
      : null,
  );
}

function renderBatchCard(batch) {
  if (!batch || typeof batch !== "object") return el("pre", {}, "{}");
  const nodes = [];
  const sel = batch.selection || {};
  nodes.push(el("div", { class: "sp-meta" },
    `${(batch.candidates || []).length} 候选 · 并发上限 ${(batch.concurrency || {}).max_parallel ?? "—"} · 共享研究 ${(batch.shared_research?.refs || []).length} 份`));
  if ((sel.selected_candidate_ids || []).length) {
    nodes.push(el("div", { class: "d-cat", style: "margin-top:8px;color:#1f9d55" }, `已选进入精剪：${sel.selected_candidate_ids.join("、")}`));
    if (sel.reason) nodes.push(el("div", { class: "sp-paren" }, sel.reason));
  }
  for (const c of batch.candidates || []) {
    const dir = c.direction || {};
    const axes = ["hook", "pacing", "packaging", "audience", "duration"]
      .filter((k) => dir[k]).map((k) => `${k}:${String(dir[k]).slice(0, 24)}`).join(" · ");
    const evalRef = c.evaluation_report_ref;
    nodes.push(el("div", { class: "sp-slug", style: "margin-top:6px" },
      c.candidate_id, " ", statusChip(c.status, c.status),
      el("span", { class: "tc" }, `  ¥${Number(c.cost_usd || 0).toFixed(2)}`)));
    nodes.push(el("div", { class: "sp-paren" }, `${c.label}${axes ? ` — ${axes}` : ""}`));
    if (c.failure) nodes.push(el("div", { class: "sp-paren", style: "color:#c53030" }, `失败：${c.failure}`));
    if (evalRef) nodes.push(el("div", { class: "sp-paren" }, `评价卡：${evalRef.path || evalRef.name || "有"}`));
    if (c.sample_ref) nodes.push(el("div", { class: "sp-paren" }, `样片：${c.sample_ref.path || "有"}`));
  }
  return el("div", { style: "padding:4px 0" }, nodes);
}

// ---------------------------------------------------------------------------
// script card
// ---------------------------------------------------------------------------

function scriptSections(script, limit) {
  const sections = script.sections || [];
  const shown = limit ? sections.slice(0, limit) : sections;
  const nodes = [];
  for (const sec of shown) {
    nodes.push(el("div", { class: "sp-slug" },
      `${(sec.id || "").toUpperCase()} — ${sec.label || "Section"} `,
      el("span", { class: "tc" }, `${fmtDuration(sec.start_seconds)} – ${fmtDuration(sec.end_seconds)}`)));
    if (sec.text) nodes.push(el("div", { class: "sp-action" }, sec.text));
    if (sec.speaker_directions) nodes.push(el("div", { class: "sp-paren" }, `(${sec.speaker_directions})`));
    const cues = sec.enhancement_cues || [];
    if (cues.length) {
      nodes.push(el("div", { style: "margin-left:42px" },
        cues.map((c) => el("span", { class: "sp-cue" }, `▸ ${c.type} · ${String(c.description || "").slice(0, 60)}`))));
    }
  }
  if (limit && sections.length > limit) {
    nodes.push(el("div", { class: "sp-fade" }, `… ${sections.length - limit} more sections`));
  }
  return nodes;
}

function renderScriptCard(s) {
  const script = s.artifacts.script;
  if (!script) return null;
  const scriptStage = s.stages.find((x) => x.name === "script");
  const status = scriptStage ? scriptStage.status : "unknown";
  const stamp = status === "completed"
    ? el("span", { class: "script-status script-approved" }, "APPROVED")
    : status === "awaiting_human"
      ? el("span", { class: "script-status script-pending" }, "PENDING APPROVAL")
      : status === "in_progress"
        ? el("span", { class: "script-status script-draft" }, "DRAFTING")
        : null;

  const card = el("div", { class: "script-card script-preview", title: "Click to expand full script", onclick: openScriptModal },
    stamp,
    el("div", { class: "sp-title" }, script.title || s.title),
    el("div", { class: "sp-meta" },
      `script · ${fmtDuration(script.total_duration_seconds)} · ${(script.sections || []).length} sections`),
    ...scriptSections(script, 4),
    el("span", { class: "sp-expand" }, "⤢ EXPAND SCRIPT"),
  );
  return card;
}

function humanize(value) {
  return String(value || "artifact").replaceAll("_", " ");
}

function shortText(value, limit = 180) {
  const text = String(value || "").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function reviewFact(label, value) {
  if (value == null || value === "") return null;
  return el("div", { class: "approval-fact" },
    el("span", {}, label),
    el("b", {}, value),
  );
}

function reviewFacts(items) {
  const facts = items.filter(Boolean);
  return facts.length ? el("div", { class: "approval-facts" }, facts) : null;
}

function titledItems(items, selectedId = null) {
  const rows = (items || []).slice(0, 4).map((item, index) => {
    if (item == null) return null;
    if (typeof item !== "object") {
      return el("li", {}, shortText(item));
    }
    const id = item.id || item.concept_id || item.option_id;
    const title = item.title || item.name || item.display_name || item.label || id || item.path || item.platform || item.description || `Item ${index + 1}`;
    const detail = item.hook || item.why_this_works || item.summary || item.description || item.silhouette_notes;
    return el("li", { class: id && id === selectedId ? "selected" : "" },
      el("div", { class: "approval-item-title" }, shortText(title, 100),
        id && id === selectedId ? el("span", { class: "approval-selected" }, "SELECTED") : null),
      detail && detail !== title ? el("p", {}, shortText(detail)) : null,
    );
  }).filter(Boolean);
  return rows.length ? el("ul", { class: "approval-items" }, rows) : null;
}

function genericArtifactSummary(artifact) {
  const facts = [];
  const items = [];
  for (const [key, value] of Object.entries(artifact || {})) {
    if (["version", "decision_log_ref"].includes(key)) continue;
    if (["string", "number", "boolean"].includes(typeof value)) {
      facts.push(reviewFact(humanize(key), shortText(value, 90)));
    } else if (Array.isArray(value)) {
      facts.push(reviewFact(humanize(key), `${value.length} item${value.length === 1 ? "" : "s"}`));
      if (!items.length && value.length) items.push(titledItems(value));
    }
    if (facts.length >= 6) break;
  }
  return [reviewFacts(facts), ...items].filter(Boolean);
}

function artifactReviewContent(name, artifact) {
  if (name === "brief") {
    return [
      artifact.hook ? el("p", { class: "approval-lead" }, artifact.hook) : null,
      reviewFacts([
        reviewFact("platform", artifact.target_platform),
        reviewFact("duration", artifact.target_duration_seconds != null ? fmtDuration(artifact.target_duration_seconds) : null),
        reviewFact("tone", artifact.tone),
        reviewFact("style", artifact.style),
      ]),
      titledItems(artifact.key_points),
    ].filter(Boolean);
  }
  if (name === "proposal_packet") {
    const selected = (artifact.selected_concept || {}).concept_id;
    const plan = artifact.production_plan || {};
    const cost = artifact.cost_estimate || {};
    return [
      reviewFacts([
        reviewFact("runtime", plan.render_runtime),
        reviewFact("pipeline", plan.pipeline),
        reviewFact("estimated cost", cost.total_estimated_usd != null ? fmtMoney(cost.total_estimated_usd) : null),
        reviewFact("concepts", Array.isArray(artifact.concept_options) ? artifact.concept_options.length : null),
      ]),
      titledItems(artifact.concept_options, selected),
      (artifact.selected_concept || {}).rationale
        ? el("p", { class: "approval-rationale" },
          el("b", {}, "WHY THIS CONCEPT  "), shortText(artifact.selected_concept.rationale))
        : null,
    ].filter(Boolean);
  }
  if (name === "research_brief") {
    return [
      artifact.topic ? el("p", { class: "approval-lead" }, artifact.topic) : null,
      reviewFacts([
        reviewFact("sources", Array.isArray(artifact.sources) ? artifact.sources.length : null),
        reviewFact("data points", Array.isArray(artifact.data_points) ? artifact.data_points.length : null),
        reviewFact("angles", Array.isArray(artifact.angles_discovered) ? artifact.angles_discovered.length : null),
      ]),
      titledItems(artifact.angles_discovered),
    ].filter(Boolean);
  }
  if (name === "script") {
    const first = (artifact.sections || [])[0];
    return [
      reviewFacts([
        reviewFact("duration", fmtDuration(artifact.total_duration_seconds)),
        reviewFact("sections", (artifact.sections || []).length),
      ]),
      first && first.text ? el("p", { class: "approval-lead" }, shortText(first.text, 220)) : null,
      el("p", { class: "approval-guidance" }, "The complete script preview is shown directly below."),
    ].filter(Boolean);
  }
  if (name === "scene_plan") {
    const scenes = artifact.scenes || [];
    const end = scenes.reduce((max, scene) => Math.max(max, Number(scene.end_seconds) || 0), 0);
    return [
      reviewFacts([
        reviewFact("scenes", scenes.length),
        reviewFact("duration", end ? fmtDuration(end) : null),
      ]),
      titledItems(scenes),
      el("p", { class: "approval-guidance" }, "Review timing and shot coverage in the storyboard below."),
    ].filter(Boolean);
  }
  if (name === "asset_manifest") {
    const assets = artifact.assets || [];
    const types = [...new Set(assets.map((asset) => asset.type).filter(Boolean))];
    return [
      reviewFacts([
        reviewFact("assets", assets.length),
        reviewFact("types", types.join(", ")),
        reviewFact("generation cost", artifact.total_cost_usd != null ? fmtMoney(artifact.total_cost_usd) : null),
      ]),
      titledItems(assets),
      el("p", { class: "approval-guidance" }, "Inspect every generated take in the filmstrip below before approving compose."),
    ].filter(Boolean);
  }
  if (name === "edit_decisions") {
    return [
      reviewFacts([
        reviewFact("cuts", Array.isArray(artifact.cuts) ? artifact.cuts.length : null),
        reviewFact("runtime", artifact.render_runtime || (artifact.metadata || {}).render_runtime),
      ]),
      titledItems(artifact.cuts),
    ].filter(Boolean);
  }
  if (name === "render_report") {
    return [
      reviewFacts([
        reviewFact("outputs", Array.isArray(artifact.outputs) ? artifact.outputs.length : null),
        reviewFact("duration", artifact.duration_seconds != null ? fmtDuration(artifact.duration_seconds) : null),
      ]),
      titledItems(artifact.outputs),
    ].filter(Boolean);
  }
  if (name === "publish_log") {
    return [
      reviewFacts([reviewFact("destinations", Array.isArray(artifact.entries) ? artifact.entries.length : null)]),
      titledItems((artifact.entries || []).map((entry) => ({
        title: entry.platform || entry.destination || "Publish destination",
        description: [entry.status, entry.url].filter(Boolean).join(" · "),
      }))),
    ].filter(Boolean);
  }
  return genericArtifactSummary(artifact);
}

function artifactReviewTitle(name, artifact, s) {
  if (name === "proposal_packet") {
    const selected = (artifact.selected_concept || {}).concept_id;
    const concept = (artifact.concept_options || []).find((item) => item.id === selected);
    return (concept && concept.title) || "Production proposal";
  }
  if (name === "research_brief") return artifact.topic || "Research brief";
  if (name === "scene_plan") return "Scene plan";
  if (name === "asset_manifest") return "Generated assets";
  if (name === "edit_decisions") return "Edit decisions";
  if (name === "render_report") return "Render report";
  if (name === "publish_log") return "Publish plan";
  return artifact.title || artifact.name || s.title;
}

function renderApprovalReview(s) {
  const awaiting = s.stages.find((item) => item.status === "awaiting_human");
  if (!awaiting) return null;

  const names = artifactNamesForStage(awaiting);
  const entries = names
    .filter((name) => name !== "decision_log")
    .map((name) => [name, s.artifacts[name]])
    .filter(([, artifact]) => artifact && typeof artifact === "object");
  const stageIndex = s.stages.findIndex((item) => item.name === awaiting.name);
  const nextStage = stageIndex >= 0 ? s.stages[stageIndex + 1] : null;
  const review = awaiting.review || {};
  const reviewSummary = reviewSummaryText(review);

  const artifacts = entries.map(([name, artifact]) => el("article", {
    class: "approval-artifact",
    "data-artifact": name,
  },
    el("div", { class: "approval-artifact-kicker" }, humanize(name)),
    el("h2", {}, artifactReviewTitle(name, artifact, s)),
    ...artifactReviewContent(name, artifact),
  ));

  if (!artifacts.length) {
    artifacts.push(el("div", { class: "approval-missing", role: "alert" },
      el("b", {}, "Nothing reviewable was found. "),
      names.length
        ? `The ${awaiting.name} checkpoint declares ${names.map(humanize).join(", ")}, but Backlot could not load it.`
        : `The ${awaiting.name} checkpoint does not declare an artifact.`,
    ));
  }

  return el("section", { class: "approval-review", "data-stage": awaiting.name },
    el("div", { class: "approval-review-head" },
      el("div", {},
        el("div", { class: "approval-eyebrow" }, "REVIEW GATE"),
        el("h2", {}, `${humanize(awaiting.name)} is ready for your review`),
        el("p", {}, "Review the artifact here, then reply in chat to approve it or request changes."),
      ),
      el("span", { class: "approval-status" }, "PENDING APPROVAL"),
    ),
    reviewSummary ? el("div", { class: "approval-review-note" },
      el("b", {}, "SELF-REVIEW  "), shortText(reviewSummary, 260)) : null,
    el("div", { class: "approval-artifacts" }, artifacts),
    el("div", { class: "approval-review-foot" },
      el("span", {}, nextStage
        ? `Approval unlocks ${humanize(nextStage.name)}.`
        : "This is the final approval gate."),
      el("button", { type: "button", onclick: () => toggleDrawer(awaiting.name) }, "OPEN FULL ARTIFACT"),
    ),
  );
}

function openScriptModal() {
  const script = state && state.artifacts.script;
  if (!script) return;
  modal.innerHTML = "";
  modal.append(
    el("span", { class: "modal-close", onclick: closeModal }, "ESC · CLOSE"),
    el("div", { class: "modal-page" },
      el("div", { class: "script-card", style: "cursor:default" },
        el("div", { class: "sp-title" }, script.title || state.title),
        el("div", { class: "sp-meta" },
          `script · ${fmtDuration(script.total_duration_seconds)} · ${(script.sections || []).length} sections`),
        ...scriptSections(script, 0),
        el("div", { class: "sp-fade" }, "END"),
      )),
  );
  modal.classList.add("open");
}

function openNarrModal(card) {
  modal.innerHTML = "";
  const meta = [sceneLabel(card.id), card.section_label, fmtDuration(card.duration_seconds)]
    .filter(Boolean).join(" · ");
  modal.append(
    el("span", { class: "modal-close", onclick: closeModal }, "ESC · CLOSE"),
    el("div", { class: "modal-page" },
      el("div", { class: "script-card", style: "cursor:default" },
        el("div", { class: "sp-meta" }, meta),
        card.narration ? el("div", { class: "sp-action", style: "margin-left:0" }, card.narration) : null,
        card.shot_intent ? el("div", { class: "sp-paren", style: "margin-left:0" }, `Intent — ${card.shot_intent}`) : null,
        card.description ? el("div", { class: "sp-paren", style: "margin-left:0" }, card.description) : null,
      )),
  );
  modal.classList.add("open");
}

function closeModal() { modal.classList.remove("open"); }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

// ---------------------------------------------------------------------------
// right rail: decisions, activity
// ---------------------------------------------------------------------------

const STAGE_LABELS_ZH = {
  research: "参考解析与素材体检",
  proposal: "创意方案",
  idea: "创意方案",
  script: "剧本生成",
  scene_plan: "分镜",
  assets: "制作准备",
  sample: "样片确认",
  edit: "修改与精剪",
  compose: "成片生成",
  publish: "交付下载",
};

const WAIT_REASON_ZH = {
  waiting_user: "等待你的决定",
  retry_backoff: "重试退避中",
  provider_queue: "供应商排队中",
  rendering: "渲染中",
  orchestrating: "编排中",
  none: "—",
};

function stageLabelZh(name) {
  return STAGE_LABELS_ZH[name] || name || "";
}

function waitReasonZh(reason) {
  return WAIT_REASON_ZH[reason] || (reason ? String(reason) : "—");
}

function fmtSeconds(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 60) return `${Math.round(n)} 秒`;
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return m < 60 ? `${m} 分 ${s} 秒` : `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
}

function fmtMachineMs(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1000) return `${Math.round(n)} 毫秒`;
  return fmtSeconds(n / 1000);
}

function unitWord(kind) {
  if (kind === "frame") return "帧";
  if (kind === "scene") return "镜头";
  if (kind === "percent") return "%";
  if (kind === "step") return "步";
  return "";
}

function runEventStatus(r) {
  const unit = r.unit || {};
  const hasUnit = unit.total > 0 && unit.current != null;
  const progress = hasUnit ? `${unit.current}/${unit.total} ${unitWord(unit.kind)}` : "";
  if (r.status === "succeeded") return "完成";
  if (r.status === "failed") return "失败";
  if (r.status === "cancelled") return "已取消";
  if (r.status === "needs_attention") return "需要关注";
  const label = (r.wait_reason && r.wait_reason !== "none")
    ? waitReasonZh(r.wait_reason)
    : (r.status === "queued" ? "排队中" : "处理中");
  return progress ? `${label} ${progress}` : label;
}

// Mutations on the diagnostic board need a session CSRF token, mirroring
// operator/api.js (getSession → X-CSRF-Token header).
async function csrfSession() {
  try {
    const res = await fetch("/api/v2/auth/me", { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

async function postJSON(url, body) {
  const session = await csrfSession();
  const headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
    "X-CSRF-Token": session?.csrf_token || "",
    Origin: window.location.origin,
    "Idempotency-Key": (crypto.randomUUID ? crypto.randomUUID() : `id-${Date.now()}`),
  };
  const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body || {}) });
  if (!res.ok) {
    let message = `${res.status}`;
    try { message = (await res.json())?.error?.message || message; } catch { /* keep status */ }
    throw new Error(message);
  }
  return res.json();
}

async function approveReview(review) {
  try {
    await postJSON(`/api/v2/projects/${encodeURIComponent(projectId)}/reviews/${encodeURIComponent(review.review_id)}/approved`, {
      reason: "批准",
      subject_version: review.subject_version,
      subject_hash: review.subject_hash,
    });
    refresh().catch(console.error);
  } catch (err) {
    window.alert(`批准失败：${String(err)}`);
  }
}

// Canonical issue tags (mirrors decision_log schema enum) with business labels.
const REJECT_TAGS = [
  ["unclear_promise", "卖点不清"], ["unsupported_claim", "无依据断言"], ["information_gap", "信息缺失"],
  ["weak_hook", "钩子弱"], ["slow_start", "开头拖沓"], ["cover_mismatch", "封面不符"],
  ["repetition", "内容重复"], ["density_spike", "信息过密"], ["dead_air", "冷场"], ["weak_payoff", "结尾弱"],
  ["identity_drift", "角色/产品漂移"], ["artifact", "生成伪影"], ["hierarchy_failure", "重点不分"], ["generic_visual", "画面太通用"],
  ["pronunciation", "发音错误"], ["timing", "语音节奏问题"], ["music_masking", "音乐压人声"], ["loudness", "响度问题"],
  ["unsafe_text", "字幕出安全区"], ["wrong_duration", "时长不对"], ["mobile_illegibility", "手机看不清"],
  ["weak_offer", "卖点弱"], ["late_cta", "CTA 太晚"], ["ambiguous_cta", "CTA 含糊"], ["brand_mismatch", "品牌不符"],
  ["blank_frame", "空白帧"], ["crop_mismatch", "裁切问题"], ["claim_rejected", "被拒声明残留"],
  ["caption_overlap", "字幕重叠"], ["render_failure", "渲染缺陷"], ["infra_sidequest", "基建支线干扰"],
];

function openRejectPanel(review, itemEl) {
  const existing = itemEl.querySelector(".inbox-reject-panel");
  if (existing) { existing.remove(); return; }
  const panel = el("div", { class: "inbox-reject-panel" });
  const tagBox = el("div", { class: "inbox-reject-tags" });
  const checked = new Set();
  for (const [id, label] of REJECT_TAGS) {
    const row = el("label", { class: "inbox-reject-tag" },
      el("input", { type: "checkbox", value: id, onchange: (e) => { e.target.checked ? checked.add(id) : checked.delete(id); } }),
      el("span", {}, label),
    );
    tagBox.append(row);
  }
  const reasonInput = el("input", { class: "inbox-reject-reason", type: "text", placeholder: "补充说明（可选）" });
  const doReject = el("button", { class: "inbox-reject", type: "button", onclick: () => rejectReview(review, checked, reasonInput) }, "确认拒绝");
  const cancel = el("button", { class: "inbox-cancel", type: "button", onclick: () => panel.remove() }, "取消");
  panel.append(el("div", { class: "inbox-reject-head" }, "选择拒绝原因（至少一个）"), tagBox, reasonInput, el("div", { class: "inbox-reject-actions" }, doReject, cancel));
  itemEl.append(panel);
}

async function rejectReview(review, checked, reasonInput) {
  const issueTags = [...checked];
  if (!issueTags.length) { window.alert("请至少选择一个原因标签"); return; }
  try {
    await postJSON(`/api/v2/projects/${encodeURIComponent(projectId)}/reviews/${encodeURIComponent(review.review_id)}/rejected`, {
      reason: (reasonInput.value || "").trim(),
      issue_tags: issueTags,
      subject_version: review.subject_version,
      subject_hash: review.subject_hash,
    });
    refresh().catch(console.error);
  } catch (err) {
    window.alert(`拒绝失败：${String(err)}`);
  }
}

async function submitReviewNote(textarea, stage, versionRef) {
  const note = (textarea.value || "").trim();
  if (!note) { window.alert("请先填写审核意见"); return; }
  try {
    await postJSON(`/api/v2/projects/${encodeURIComponent(projectId)}/review-notes`, { note, stage, version_ref: versionRef });
    textarea.value = "";
    refresh().catch(console.error);
  } catch (err) {
    window.alert(`提交失败：${String(err)}`);
  }
}

// U4 — 「进行中操作」 progress card: active run events with frame progress,
// attempt, typed wait reason, ETA, machine time and cost reservation.
function renderProgressCard(s) {
  const ops = (s.run_ops || []).filter((r) => r.status === "running" || r.status === "queued");
  if (!ops.length) return null;
  const body = el("div", { class: "panel-body" });
  for (const r of ops) {
    const unit = r.unit || {};
    const hasProgress = unit.total > 0 && unit.current != null;
    const pct = hasProgress ? Math.min(100, Math.max(0, Math.round((Number(unit.current) / Number(unit.total)) * 100))) : null;
    const chips = [];
    if (r.attempt != null) chips.push(el("span", { class: "op-chip" }, `第 ${r.attempt} 次尝试`));
    chips.push(el("span", { class: `op-chip${r.wait_reason === "waiting_user" ? " op-wait" : ""}` }, waitReasonZh(r.wait_reason)));
    if (r.eta_seconds != null) chips.push(el("span", { class: "op-chip" }, `预计还需 ${fmtSeconds(r.eta_seconds)}`));
    if (r.machine_ms != null) chips.push(el("span", { class: "op-chip" }, `机器耗时 ${fmtMachineMs(r.machine_ms)}`));
    if (r.cost_reservation_id) chips.push(el("span", { class: "op-chip" }, `费用预留 ${r.cost_reservation_id}`));
    if (r.stale_seconds != null && r.stale_seconds > 0) chips.push(el("span", { class: "op-chip op-stale" }, `${r.stale_seconds} 秒未更新`));
    body.append(el("div", { class: "op-card" },
      el("div", { class: "op-head" },
        el("span", { class: "op-title" }, `${stageLabelZh(r.stage) || "操作"} · ${r.operation || ""}`),
        r.needs_attention
          ? el("span", { class: "op-badge" }, "需要关注")
          : el("span", { class: "op-badge op-badge-ok" }, "进行中"),
      ),
      hasProgress ? el("div", { class: "op-bar" },
        el("i", { style: `width:${pct}%` }),
        el("span", {}, `${unit.current}/${unit.total} ${unitWord(unit.kind)}（${pct}%）`)) : null,
      r.message ? el("div", { class: "op-msg" }, String(r.message)) : null,
      chips.length ? el("div", { class: "op-meta" }, chips) : null,
    ));
  }
  return el("div", { class: "panel" },
    el("div", { class: "panel-head" }, el("h2", {}, "进行中操作"), el("span", { class: "meta" }, `${ops.length} 项`)),
    body);
}

// U2 — decision inbox: every awaiting_human stage, with an approve button only
// when a real review exists (no fake buttons for legacy projects).
function renderDecisionInbox(s) {
  const awaiting = s.awaiting || [];
  if (!awaiting.length) return null;
  const body = el("div", { class: "panel-body" });
  for (const item of awaiting) {
    const itemEl = el("div", { class: "inbox-item" },
      el("div", { class: "inbox-head" },
        el("span", { class: "inbox-stage" }, stageLabelZh(item.stage) || item.stage),
        item.timestamp ? el("span", { class: "inbox-time" }, fmtClock(item.timestamp)) : null,
      ),
      item.next_action_summary ? el("div", { class: "inbox-summary" }, String(item.next_action_summary)) : null,
      item.review_id ? el("div", { class: "inbox-actions" },
        el("button", { class: "inbox-approve", type: "button", onclick: () => approveReview(item) }, "批准"),
        el("button", { class: "inbox-reject-open", type: "button", onclick: () => openRejectPanel(item, itemEl) }, "拒绝并要求返工"),
      ) : null,
    );
    body.append(itemEl);
  }
  return el("div", { class: "panel inbox" },
    el("div", { class: "panel-head" }, el("h2", {}, "需要你处理"), el("span", { class: "meta" }, `${awaiting.length} 项`)),
    body);
}

// U3 — review player: latest sample video, stills grid, version compare and
// append-only review notes.
function renderReviewPlayer(s) {
  const samples = (s.media && s.media.samples) || [];
  const stills = (s.media && s.media.stills) || [];
  if (!samples.length && !stills.length) return null;

  const body = el("div", { class: "review-body" });
  const primary = samples[0] || null;
  const second = samples[1] || null;

  if (primary) {
    const mainVideo = el("video", { src: mediaURL(s.project_id, primary.path), controls: "", preload: "metadata" });
    body.append(
      el("div", { class: "review-player" },
        el("div", { class: "review-head" }, el("b", {}, "最新样片"), el("span", { class: "meta" }, primary.path.split("/").pop())),
        el("div", { class: "review-hero" }, mainVideo),
      ),
    );
    if (second) {
      const a = el("video", { src: mediaURL(s.project_id, primary.path), controls: "", preload: "metadata" });
      const b = el("video", { src: mediaURL(s.project_id, second.path), controls: "", preload: "metadata" });
      body.append(
        el("div", { class: "review-compare" },
          el("div", { class: "review-compare-head" }, el("b", {}, "并排对比"), el("span", { class: "meta" }, "不要求同步播放")),
          el("div", { class: "review-compare-grid" },
            el("div", { class: "review-compare-slot" }, el("span", { class: "meta" }, primary.path.split("/").pop()), a),
            el("div", { class: "review-compare-slot" }, el("span", { class: "meta" }, second.path.split("/").pop()), b),
          ),
        ),
      );
    }
    if (samples.length > 1) {
      const versions = el("div", { class: "review-versions" });
      samples.forEach((v) => {
        versions.append(el("span", { class: "review-ver", onclick: () => { mainVideo.src = mediaURL(s.project_id, v.path); mainVideo.load(); } }, v.path.split("/").pop()));
      });
      body.append(versions);
    }
  }

  if (stills.length) {
    const grid = el("div", { class: "review-stills" });
    for (const st of stills.slice(0, 16)) {
      grid.append(el("div", { class: "thumb" }, el("img", { src: thumbURL(s.project_id, st.path, 640), loading: "lazy", alt: "" })));
    }
    body.append(el("div", { class: "review-section-title" }, `静帧 · ${stills.length} 张`), grid);
  }

  const noteStage = ((s.awaiting || [])[0] || {}).stage || "";
  body.append(el("div", { class: "review-section-title" }, "审核意见"));
  const textarea = el("textarea", { class: "review-note-input", rows: "3", placeholder: "写下审核意见（可注明需修改的时间段或原因）" });
  const submit = el("button", { class: "review-note-submit", type: "button", onclick: () => submitReviewNote(textarea, noteStage, primary ? primary.path.split("/").pop() : "") }, "提交审核意见");
  body.append(el("div", { class: "review-note-form" }, textarea, submit));

  const notes = s.review_notes || [];
  if (notes.length) {
    const list = el("div", { class: "review-note-list" });
    for (const n of [...notes].reverse()) {
      list.append(el("div", { class: "review-note" },
        el("div", { class: "review-note-head" },
          el("span", { class: "meta" }, fmtClock(n.ts)),
          n.actor ? el("span", { class: "meta" }, String(n.actor)) : null,
          n.stage ? el("span", { class: "meta" }, stageLabelZh(n.stage)) : null),
        el("div", {}, String(n.note || "")),
      ));
    }
    body.append(list);
  }

  return el("div", { class: "review-section" },
    el("div", { class: "section-title" }, "样片审核", el("span", { class: "meta" }, `${samples.length} 个样片 · ${stills.length} 张静帧`)),
    body);
}

function renderDecisions(s) {
  const log = s.artifacts.decision_log;
  const decisions = (log && log.decisions) || [];
  if (!decisions.length) return null;
  const body = el("div", { class: "panel-body" });
  // Collapse by category+subject: a decision that changed mid-run (e.g. voice
  // openai_onyx → chirp3) is superseded by the later entry — show the CURRENT
  // choice, not the first one recorded, and mark that it was revised.
  const current = new Map();
  decisions.forEach((d, i) => {
    const key = `${d.category || "decision"}::${d.subject || ""}`;
    const prev = current.get(key);
    current.set(key, { d, order: i, revised: prev ? prev.revised + 1 : 0 });
  });
  const shown = [...current.values()].sort((a, b) => b.order - a.order).slice(0, 8);
  for (const { d, revised } of shown) {
    const selLabel = (() => {
      // Prefer the human label of the selected option over its bare id.
      const opt = (d.options_considered || []).find((o) => (o.option_id ?? o.label) === d.selected);
      return (opt && opt.label) || d.selected || "";
    })();
    const alts = (d.options_considered || [])
      .filter((o) => (o.option_id ?? o.label) !== d.selected && (o.option_id || o.label));
    body.append(el("div", { class: "decision" },
      el("div", { class: "d-cat" }, `${d.category || "decision"}${d.confidence ? ` · ${d.confidence}` : ""}`,
        revised ? el("span", { class: "d-revised" }, " · revised") : null),
      el("div", { class: "d-pick" }, `${d.subject || ""} `, el("span", { class: "arrow" }, "→"), ` ${selLabel}`),
      d.reason ? el("div", { class: "d-why" }, d.reason) : null,
      alts.length ? el("div", { class: "d-alt" }, "also considered: ",
        alts.slice(0, 3).map((o, i) => [i ? " · " : "", el("s", {}, o.label || o.option_id)]).flat()) : null,
    ));
  }
  return el("div", { class: "panel" },
    el("div", { class: "panel-head" }, el("h2", {}, "Decisions"), el("span", { class: "meta" }, "decision_log.json")),
    body);
}

function renderActivity(s) {
  const events = s.events || [];
  const runOps = s.run_ops || [];
  if (!events.length && !runOps.length) return null;
  const body = el("div", { class: "panel-body" });
  // A start is "running" only until a later finish/error for the same
  // tool+scene closes it — closed starts are dropped (the finish row tells
  // the story), unmatched starts render as live. Counted (not keyed-single)
  // so parallel runs of the same tool on the same scene stay visible.
  const open = new Map(); // key -> {count, ev}
  const rows = [];
  for (const ev of events) {
    if (ev.schema_version === "1.0") continue; // run events handled below
    const key = `${ev.tool}:${ev.scene_id || ""}`;
    if (ev.event === "start") {
      const slot = open.get(key) || { count: 0, ev };
      slot.count += 1;
      slot.ev = ev;
      open.set(key, slot);
    } else if (ev.event === "finish" || ev.event === "error") {
      const slot = open.get(key);
      if (slot) {
        slot.count -= 1;
        if (slot.count <= 0) open.delete(key);
      }
      rows.push(ev);
    } else {
      rows.push(ev);
    }
  }
  for (const slot of open.values()) rows.push(slot.ev);
  // Run events join the same timeline (one row per run_id, latest state).
  for (const r of runOps) rows.push({ _run: true, op: r, ts: r.last_ts });
  rows.sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  for (const ev of rows.slice(-30).reverse()) {
    if (ev._run) {
      const r = ev.op;
      const tone = r.status === "failed" ? "err" : r.status === "succeeded" ? "ok" : "run";
      body.append(el("div", { class: "act-row" },
        el("span", { class: "t" }, fmtClock(r.last_ts)),
        el("span", { class: "tool" }, stageLabelZh(r.stage) || r.operation || "操作"),
        el("span", { class: "target" }, r.operation || ""),
        el("span", { class: `status ${tone}` }, runEventStatus(r)),
      ));
      continue;
    }
    let statusEl;
    if (ev.event === "finish") {
      statusEl = el("span", { class: `status ${ev.success === false ? "err" : "ok"}` },
        `${ev.success === false ? "✕" : "✓"}${ev.duration_s != null ? ` ${ev.duration_s.toFixed ? ev.duration_s.toFixed(1) : ev.duration_s}s` : ""}${ev.cost_usd ? ` ${fmtMoney(ev.cost_usd)}` : ""}`);
    } else if (ev.event === "cache_hit") {
      statusEl = el("span", { class: "status ok" }, "✓ 已复用");
    } else if (ev.event === "cache_miss") {
      statusEl = el("span", { class: "status" }, "• 新处理");
    } else if (ev.event === "error") {
      statusEl = el("span", { class: "status err" }, "✕");
    } else {
      statusEl = el("span", { class: "status run" }, "● running");
    }
    body.append(el("div", { class: "act-row" },
      el("span", { class: "t" }, fmtClock(ev.ts)),
      el("span", { class: "tool" }, ev.tool || ""),
      el("span", { class: "target" }, ev.scene_id || ""),
      statusEl,
    ));
  }
  return el("div", { class: "panel" },
    el("div", { class: "panel-head" }, el("h2", {}, "Activity"), el("span", { class: "meta" }, "events.jsonl")),
    body);
}

// ---------------------------------------------------------------------------
// storyboard filmstrip
// ---------------------------------------------------------------------------

function sceneLabel(id) {
  // "sc4" → "SC 04", "scene-11" → "SC 11", anything else → uppercased id
  const m = String(id).match(/(\d+)\s*$/);
  if (m) return `SC ${m[1].padStart(2, "0")}`;
  return String(id).toUpperCase().slice(0, 10);
}

function sceneCard(s, card) {
  const dur = card.duration_seconds;
  const width = Math.max(132, Math.min(300, 70 + (dur || 3) * 26));
  const wrap = el("div", { class: "scene-card", style: `width:${width}px` });

  const slate = el("div", { class: "sc-slate" },
    el("span", { class: "num" }, sceneLabel(card.id)),
    card.takes.length > 1 ? el("span", { class: "take" }, `T${card.takes.length}`) : null,
    card.hero_moment ? el("span", { class: "hero" }, "★ HERO") : null,
    el("span", { class: "dur" }, fmtDuration(dur)),
  );
  wrap.append(slate);

  // visual slot
  let thumb;
  if (card.generating) {
    thumb = el("div", { class: "thumb generating" },
      el("div", { class: "shimmer" }),
      el("div", { class: "gen-label" },
        el("span", {}, "◉ GENERATING"),
        el("span", { class: "sub" }, card.generating_tool || "")));
  } else if (card.visual && card.visual.exists) {
    const v = card.visual;
    const badge = [v.model || v.source_tool, v.cost_usd != null ? fmtMoney(v.cost_usd) : null,
      v.quality_score != null ? `q ${v.quality_score}` : null].filter(Boolean).join(" · ");
    if (v.type === "video") {
      thumb = el("div", { class: "thumb approved" },
        el("video", { src: mediaURL(s.project_id, v.path), muted: "", preload: "metadata", playsinline: "" }),
        el("span", { class: "play" }, "▶"),
        badge ? el("span", { class: "badge" }, badge) : null);
      thumb.onclick = () => {
        const vid = thumb.querySelector("video");
        if (vid.paused) vid.play(); else vid.pause();
      };
    } else {
      const img = el("img", { src: thumbURL(s.project_id, v.path, 640), loading: "lazy", alt: "" });
      // A thumbnail that fails to load must never show a broken-image icon —
      // fall back to the shot spec in place (F: broken links).
      img.onerror = () => {
        const t = img.closest(".thumb");
        if (!t) return;
        t.className = "thumb spec";
        t.innerHTML = "";
        t.append(el("div", { class: "spec-in" },
          el("div", { class: "spec-desc" }, card.description || "asset unavailable"),
          el("div", { class: "spec-shot" }, [card.framing, card.movement].filter(Boolean).join(" · ").slice(0, 70))));
      };
      thumb = el("div", { class: "thumb approved" }, img,
        v.snapshot ? el("span", { class: "badge" }, "snapshot") : (badge ? el("span", { class: "badge" }, badge) : null));
    }
  } else if (card.type === "animation") {
    // Bespoke/atelier scene with no snapshot yet — name it as such rather
    // than "no asset yet" (the composition IS the asset).
    thumb = el("div", { class: "thumb spec bespoke" },
      el("div", { class: "spec-in" },
        el("span", { class: "bespoke-tag" }, "◆ BESPOKE"),
        el("div", { class: "spec-desc" }, card.description || ""),
        el("div", { class: "spec-shot" }, "hand-authored composition")));
  } else if (card.visual && !card.visual.exists) {
    thumb = el("div", { class: "thumb missing" },
      el("div", { class: "spec-in" },
        el("span", { class: "warn-ic" }, "⚑"),
        el("div", { class: "spec-desc" }, "asset in manifest, file missing"),
        el("div", { class: "spec-shot" }, card.visual.path || "")));
  } else if (card.type === "text_card") {
    thumb = el("div", { class: "thumb textcard" },
      el("div", { class: "tc-copy" }, (card.narration || card.description || "").slice(0, 48)));
  } else if (card.required_assets.length) {
    thumb = el("div", { class: "thumb missing" },
      el("div", { class: "spec-in" },
        el("span", { class: "warn-ic" }, "⚑"),
        el("div", { class: "spec-desc" }, "no asset yet"),
        el("div", { class: "spec-shot" }, (card.required_assets[0].description || "").slice(0, 60))));
  } else {
    thumb = el("div", { class: "thumb spec" },
      el("div", { class: "spec-in" },
        el("div", { class: "spec-desc" }, card.description || ""),
        el("div", { class: "spec-shot" }, [card.framing, card.movement].filter(Boolean).join(" · ").slice(0, 70))));
  }
  wrap.append(thumb);

  // shot language chips
  const sl = card.shot_language;
  if (sl) {
    wrap.append(el("div", { class: "shotchips", style: "display:flex;flex-wrap:wrap;gap:4px;padding:7px 2px 0" },
      [sl.shot_size, sl.camera_movement, sl.lens_mm ? `${sl.lens_mm}mm` : null, sl.lighting_key]
        .filter(Boolean)
        .map((t) => el("span", { style: "font-family:var(--mono);font-size:calc(8.5px * var(--fs-scale));letter-spacing:.04em;color:#62626c;border:1px solid #212129;border-radius:3px;padding:1px 5px" }, String(t).replaceAll("_", " ")))));
  }

  // takes drawer
  if (card.takes.length > 1) {
    const takes = el("div", { class: "takes" });
    card.takes.forEach((t, i) => {
      const isActive = card.visual && (
        t === card.visual
        || (t.path && t.path === card.visual.path)
        || (t.id && t.id === card.visual.id)
      );
      const tk = el("span", { class: `tk${isActive ? " active" : ""}`, title: `take ${i + 1}` });
      if (t.exists && t.type === "image") tk.append(el("img", { src: thumbURL(s.project_id, t.path, 320), loading: "lazy", alt: "" }));
      takes.append(tk);
    });
    takes.append(el("span", { class: "tk-label" }, `${card.takes.length} TAKES`));
    wrap.append(takes);
  }

  // narration + audio — clickable to read in full (F: narration text cut off)
  if (card.narration) {
    const long = card.narration.length > 90;
    wrap.append(el("div", {
      class: `narr${long ? " clip" : ""}`,
      title: "Click to read the full narration",
      onclick: () => openNarrModal(card),
    }, card.narration, long ? el("span", { class: "narr-more" }, "⤢") : null));
  } else if (card.shot_intent || card.description) {
    wrap.append(el("div", { class: "narr tc-note" }, (card.shot_intent || card.description || "").slice(0, 110)));
  }
  const narrAudio = card.audio.find((a) => a.exists && (a.type === "narration" || a.type === "audio"));
  if (narrAudio) {
    const wave = el("div", { class: "wave", style: "cursor:pointer", title: "Play narration" });
    waveBars(wave, card.id + narrAudio.path);
    wave.append(el("span", { class: "wv-time" }, narrAudio.duration_seconds ? fmtDuration(narrAudio.duration_seconds) : "♪"));
    wave.onclick = () => {
      player.src = mediaURL(s.project_id, narrAudio.path);
      player.play();
    };
    wrap.append(wave);
  }
  return wrap;
}

function renderStoryboard(s) {
  const board = s.storyboard;
  if (!board) return null;
  const strip = el("div", { class: "filmstrip" });
  for (const card of board.scenes) strip.append(sceneCard(s, card));
  return el("div", {},
    el("div", { class: "section-title" }, "Storyboard",
      el("span", { class: "meta" },
        `${board.scenes.length} scenes${board.total_duration_seconds ? ` · ${fmtDuration(board.total_duration_seconds)}` : ""} · card width ∝ duration`)),
    el("div", { class: "strip-outer" }, strip));
}

// ---------------------------------------------------------------------------
// renders + degraded media
// ---------------------------------------------------------------------------

function renderRenders(s) {
  const renders = s.media.renders;
  if (!renders.length) return null;
  if (activeRender >= renders.length) activeRender = 0;
  const current = renders[activeRender];
  // Full re-renders (every SSE refresh) must not reset an in-progress
  // watch: carry playback position/state over to the recreated element.
  const prev = document.querySelector(".render-hero video");
  const src = mediaURL(s.project_id, current.path);
  // preload="metadata" gives the element its intrinsic aspect ratio (and a
  // poster frame) before playback — without it a portrait 9:16 render sits
  // in a letterboxed 100%-wide black box that reads as landscape.
  const video = el("video", { src, controls: "", preload: "metadata" });
  // Click the frame to start playback (controls handle pause/scrub) — the
  // big player was inert to a click on the picture itself.
  video.addEventListener("click", () => { if (video.paused) video.play().catch(() => {}); });
  if (prev && prev.getAttribute("src") === src && (prev.currentTime > 0 || !prev.paused)) {
    const t = prev.currentTime;
    const wasPlaying = !prev.paused && !prev.ended;
    video.addEventListener("loadedmetadata", () => { video.currentTime = t; }, { once: true });
    video.setAttribute("preload", "metadata");
    if (wasPlaying) video.autoplay = true;
  }
  const versions = el("div", { class: "render-meta" },
    renders.map((r, i) => el("span", {
      class: `v${i === activeRender ? " active" : ""}`,
      onclick: () => { activeRender = i; render(); },
    }, `${r.path.split("/").pop()}${r.at_root ? " · root" : ""}`)),
    el("span", { style: "margin-left:auto" }, `${(current.size / 1048576).toFixed(1)} MB`),
  );
  // 成片评价卡：成片生成（compose）阶段，在成片视频下方展示 final 范围评价卡
  const evalReport = s.artifacts.evaluation_report;
  const evalCard = evalReport && evalReport.scope === "final"
    ? el("div", { style: "margin-top:16px" },
        el("div", { class: "section-title" }, "成片评价卡",
          el("span", { class: "meta" }, `judge: ${evalReport.judge_version || "—"}`)),
        el("div", { class: "review-body" }, renderEvaluationCard(evalReport)))
    : null;
  return el("div", {},
    el("div", { class: "section-title" }, "Renders",
      el("span", { class: "meta" }, `${renders.length} version${renders.length === 1 ? "" : "s"}`)),
    el("div", { class: "render-hero" }, video),
    versions,
    evalCard);
}

function renderFoundMedia(s) {
  // Degraded view: show discovered snapshots when there's no storyboard.
  if (s.storyboard || !s.media.snapshots.length) return null;
  const grid = el("div", { class: "found-grid" });
  for (const snap of s.media.snapshots.slice(0, 12)) {
    grid.append(el("div", { class: "thumb" },
      el("img", { src: thumbURL(s.project_id, snap.path, 640), loading: "lazy", alt: "" })));
  }
  return el("div", {},
    el("div", { class: "section-title" }, "What the watcher found",
      el("span", { class: "meta" }, "snapshots / verification frames")),
    grid);
}

function renderNoState(s) {
  if (s.has_pipeline_state) return null;
  return el("div", { class: "notice", style: "border-color:#2b2b33;background:var(--surface-2);color:var(--text-3)" },
    el("span", { style: "font-size:calc(15px * var(--fs-scale))" }, "◌"),
    el("span", {},
      el("b", { style: "color:var(--text-2)" }, "No pipeline state. "),
      "This project has no checkpoints — Backlot is showing what it found on disk. ",
      "Runs that follow the checkpoint protocol get the full board."));
}

function formatWorkTime(seconds, emptyLabel = "暂无法估算") {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return emptyLabel;
  if (value < 60) return value === 0 ? "已完成" : "不到 1 分钟";
  const minutes = Math.ceil(value / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`;
}

function formatSavedTime(seconds) {
  const value = Number(seconds);
  return Number.isFinite(value) && value > 0 ? formatWorkTime(value, "0 分钟") : "0 分钟";
}

function fastlineGateLabel(gate) {
  if (gate === "creative_lock") return "方案与素材待确认";
  if (gate === "sample") return "样片效果待确认";
  return "当前无需确认";
}

function fastlineBundleStatus(status) {
  return ({
    awaiting_human: "待确认",
    approved: "已确认",
    rejected: "需调整",
    superseded: "内容已变化，需重新确认",
  })[status] || "暂无确认包";
}

function renderFastlineStatus(s) {
  const f = s.fastline;
  if (!f) return null;
  const cache = f.cache || {};
  const render = f.render || {};
  const eta = f.eta || {};
  const bundle = f.bundle;
  const details = f.details || {};
  const reusedItems = details.reused_items || [];
  const dirtyCount = (render.dirty_scene_ids || []).length;
  const affected = render.mode === "mux_only"
    ? "0 个镜头，仅声音"
    : dirtyCount
      ? `${dirtyCount} 个镜头`
      : render.mode === "full_render" ? "整条视频" : "暂无画面变更";
  const nextAction = f.next_action || "继续下一步制作";
  const needsApproval = Boolean(f.gate || ["rejected", "superseded"].includes(bundle && bundle.status));
  const metrics = [
    ["是否需要确认", fastlineGateLabel(f.gate), needsApproval ? "attention" : "good"],
    ["预计还需", `${formatWorkTime(eta.seconds)}${eta.confidence === "low" && eta.seconds != null ? " · 参考值" : ""}`, eta.confidence === "low" ? "muted" : ""],
    ["已节省制作时间", cache.hits ? `${formatSavedTime(cache.saved_seconds)} · 复用 ${cache.hits} 项` : "暂未复用"],
    ["本次修改影响", affected],
    ["出片方式", render.business_label || "等待确定"],
    ["下一步", nextAction, needsApproval ? "attention" : ""],
  ];

  const bundleArtifacts = bundle && (bundle.artifacts || []).length
    ? el("div", { class: "fastline-artifact-list" },
      (bundle.artifacts || []).map((artifact) => el("div", { class: "fastline-artifact" },
        el("b", {}, artifact.name || "artifact"),
        el("span", {}, artifact.path || ""),
        artifact.semantic_sha256 ? el("code", {}, artifact.semantic_sha256) : null,
      )))
    : el("div", { class: "fastline-empty-detail" }, "当前没有方案确认包");

  return el("section", { class: `fastline-status${f.blocker ? " has-blocker" : ""}` },
    el("div", { class: "fastline-heading" },
      el("div", {},
        el("div", { class: "fastline-eyebrow" }, "制作进度"),
        el("h2", {}, f.current_task || "正在准备视频"),
      ),
      el("span", { class: `fastline-state${needsApproval ? " attention" : ""}` },
        f.blocker || "制作正常进行中"),
    ),
    el("div", { class: "fastline-metrics" }, metrics.map(([label, value, tone]) =>
      el("div", { class: `fastline-metric ${tone || ""}` },
        el("span", {}, label),
        el("b", {}, value),
      ))),
    needsApproval ? el("div", { class: "fastline-confirm-note" },
      "请回到任务中确认，Backlot 仅展示进度") : null,
    el("details", { class: "fastline-details" },
      el("summary", {}, "查看制作详情"),
      el("div", { class: "fastline-detail-grid" },
        el("div", {},
          el("span", {}, "方案确认包"),
          el("b", {}, bundle ? `第 ${bundle.version} 版 · ${fastlineBundleStatus(bundle.status)}` : "暂无"),
          bundle && bundle.changed_artifacts && bundle.changed_artifacts.length
            ? el("p", {}, `本版调整：${bundle.changed_artifacts.join("、")}`) : null,
        ),
        el("div", {},
          el("span", {}, "缓存记录"),
          el("b", {}, `${cache.hits || 0} 次复用 · ${cache.misses || 0} 次新建`),
          el("p", {}, `累计节省 ${formatSavedTime(cache.saved_seconds)}`),
        ),
        el("div", {},
          el("span", {}, "变更路由"),
          el("b", {}, render.mode || "未确定"),
          (render.dirty_scene_ids || []).length
            ? el("p", {}, `影响镜头：${render.dirty_scene_ids.join("、")}`) : null,
          (render.reasons || []).length
            ? el("p", {}, `变更原因：${render.reasons.join("；")}`) : null,
        ),
        el("div", {},
          el("span", {}, "已锁定制作配置"),
          el("b", {}, details.production_lock_hash || "暂无锁定记录"),
        ),
      ),
      reusedItems.length ? el("div", { class: "fastline-reuse-list" },
        el("div", { class: "fastline-reuse-title" }, "内容复用明细"),
        reusedItems.map((item) => el("div", { class: "fastline-reuse-item" },
          el("b", {}, item.tool || "制作内容"),
          el("span", {}, item.reused_from || item.cache_key || "本地缓存"),
          el("span", {}, `节省 ${formatSavedTime(item.saved_seconds)}`),
        ))) : null,
      bundleArtifacts,
    ),
  );
}

function renderAwaitingNotice(s) {
  if (s.fastline && s.fastline.gate) return null;
  const awaiting = s.stages.find((x) => x.status === "awaiting_human");
  if (!awaiting) return null;
  return el("div", { class: "notice" },
    el("span", { style: "font-size:calc(16px * var(--fs-scale))" }, "◈"),
    el("span", {},
      el("b", {}, `The ${awaiting.name} stage is waiting for your review. `),
      "The agent is paused at this gate — reply ", el("b", {}, "in chat"), " to approve or request changes."));
}

// ---------------------------------------------------------------------------
// replay — scrub a completed run from its timestamps
// ---------------------------------------------------------------------------

// Python writers emit tz-aware UTC isoformat, but treat tz-naive strings as
// UTC too — mixing local-parsed and UTC-parsed timestamps would skew replay
// ordering by the user's UTC offset.
const ts = (iso) => {
  if (!iso) return null;
  let s = String(iso);
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += "Z";
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
};

function replayBounds(s) {
  const moments = [];
  for (const st of s.stages) {
    for (const h of st.history_entries || []) {
      const t = ts(h.timestamp);
      if (t) moments.push(t);
    }
  }
  for (const ev of s.events || []) {
    const t = ts(ev.ts);
    if (t) moments.push(t);
  }
  if (moments.length < 2) return null;
  return { t0: Math.min(...moments), t1: Math.max(...moments) };
}

function stateAt(s, T) {
  const view = structuredClone(s);
  for (const st of view.stages) {
    const past = (st.history_entries || []).filter((h) => ts(h.timestamp) != null && ts(h.timestamp) <= T);
    if (!past.length) {
      st.status = "pending"; st.review = null; st.timestamp = null;
      st.gate_skipped = false; st.partial_progress = null;
    } else {
      const cur = past[past.length - 1];
      st.status = cur.status || "pending";
      st.timestamp = cur.timestamp;
    }
  }
  view.events = (view.events || []).filter((ev) => ts(ev.ts) != null && ts(ev.ts) <= T);

  // Storyboard: visuals appear as their scene finishes (events) or when the
  // assets stage has completed as of T (legacy runs without events).
  if (view.storyboard) {
    const assetsStage = view.stages.find((x) => x.name === "assets");
    const assetsDone = assetsStage && assetsStage.status === "completed";
    const finished = new Set();
    const startedNow = new Map();
    for (const ev of view.events) {
      if (!ev.scene_id) continue;
      if (ev.event === "finish") { finished.add(ev.scene_id); startedNow.delete(ev.scene_id); }
      else if (ev.event === "start") startedNow.set(ev.scene_id, ev);
      else if (ev.event === "error") startedNow.delete(ev.scene_id);
    }
    const scenePlanStage = view.stages.find((x) => x.name === "scene_plan");
    const scenePlanDone = scenePlanStage && ["completed", "awaiting_human"].includes(scenePlanStage.status);
    if (!scenePlanDone) {
      view.storyboard = null;
    } else {
      for (const card of view.storyboard.scenes) {
        const visible = assetsDone || finished.has(card.id);
        if (!visible) { card.visual = null; card.takes = []; card.audio = []; }
        card.generating = startedNow.has(card.id);
        card.generating_tool = (startedNow.get(card.id) || {}).tool;
      }
    }
  }
  // Final artifacts hide until their stage happened — for every project
  // shape, storyboard or not (a degraded run must not show the finished
  // movie before its stages ran).
  const scriptStage = view.stages.find((x) => x.name === "script");
  if (!(scriptStage && ["completed", "awaiting_human"].includes(scriptStage.status))) {
    delete view.artifacts.script;
  }
  const composeStage = view.stages.find((x) => x.name === "compose");
  if (!(composeStage && composeStage.status === "completed")) {
    view.media.renders = [];
  }
  return view;
}

function renderReplayBar(s) {
  const bounds = replayBounds(s);
  if (!bounds) return null;
  if (!replay) {
    // collapsed: just the entry button
    return el("div", { class: "replay-bar", style: "justify-content:flex-end" },
      el("span", { class: "rp-time" }, "scrub the whole run"),
      el("span", { class: "rp-btn", onclick: startReplay }, "▶ REPLAY RUN"));
  }
  const pos = (replay.t - replay.t0) / Math.max(1, replay.t1 - replay.t0);
  const timeLabel = el("span", { class: "rp-time" },
    new Date(replay.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
  const setT = (value) => {
    replay.t = replay.t0 + (Number(value) / 1000) * (replay.t1 - replay.t0);
    timeLabel.textContent = new Date(replay.t)
      .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };
  return el("div", { class: "replay-bar" },
    el("span", { class: "rp-btn", onclick: toggleReplayPlay }, replay.playing ? "❚❚" : "▶"),
    el("input", {
      type: "range", min: "0", max: "1000", value: String(Math.round(pos * 1000)),
      // A full render() would destroy this slider mid-drag: while dragging,
      // only pause + track the time label; re-render the board on release.
      onpointerdown: () => { replay.playing = false; },
      oninput: (e) => setT(e.target.value),
      onchange: (e) => { setT(e.target.value); render(); },
    }),
    timeLabel,
    el("span", { class: "rp-btn", onclick: stopReplay }, "✕ LIVE"),
  );
}

let replayTimer = null;

function startReplay() {
  const bounds = replayBounds(state);
  if (!bounds) return;
  replay = { ...bounds, t: bounds.t0, playing: true };
  document.body.classList.add("replaying");
  scheduleTick();
  render();
}

function stopReplay() {
  replay = null;
  clearTimeout(replayTimer);
  document.body.classList.remove("replaying");
  render();
}

function toggleReplayPlay() {
  if (!replay) return;
  replay.playing = !replay.playing;
  if (replay.playing) scheduleTick();
  render();
}

function scheduleTick() {
  // Single pending tick, ever — rapid pause/play must not stack chains.
  clearTimeout(replayTimer);
  replayTimer = setTimeout(tickReplay, 100);
}

function tickReplay() {
  if (!replay || !replay.playing) return;
  // A full run replays in ~20 seconds regardless of real duration
  // (10 renders/second — full re-render per tick, keep it modest).
  const step = (replay.t1 - replay.t0) / 200;
  replay.t = Math.min(replay.t1, replay.t + step);
  if (replay.t >= replay.t1) replay.playing = false;
  render();
  if (replay.playing) scheduleTick();
}

// ---------------------------------------------------------------------------
// page assembly
// ---------------------------------------------------------------------------

function render() {
  if (!state) return;
  const s = replay ? stateAt(state, replay.t) : state;
  document.title = `Backlot — ${s.title}`;
  document.body.classList.toggle("first", firstPaint);
  firstPaint = false;
  app.innerHTML = "";
  app.append(renderSlate(s));
  app.append(renderRail(s));
  const fastlineStatus = renderFastlineStatus(s);
  if (fastlineStatus) app.append(fastlineStatus);
  const replayBar = renderReplayBar(state);
  if (replayBar) app.append(replayBar);
  const drawer = renderDrawer(s);
  if (drawer) app.append(drawer);
  const awaitingNotice = renderAwaitingNotice(s);
  if (awaitingNotice) app.append(awaitingNotice);
  const noState = renderNoState(s);
  if (noState) app.append(noState);

  const main = el("div", { class: "main-col" });
  const approvalReview = renderApprovalReview(s);
  if (approvalReview) main.append(approvalReview);
  const script = renderScriptCard(s);
  if (script) main.append(script);
  const aside = el("aside", {});
  const progress = renderProgressCard(s);
  const inbox = renderDecisionInbox(s);
  const decisions = renderDecisions(s);
  const activity = renderActivity(s);
  if (progress) aside.append(progress);
  if (inbox) aside.append(inbox);
  if (decisions) aside.append(decisions);
  if (activity) aside.append(activity);

  // Media sections live INSIDE the main column so a tall decisions rail
  // never pushes them below the fold — the column flows beside the rail.
  const storyboard = renderStoryboard(s);
  const reviewPlayer = renderReviewPlayer(s);
  const found = renderFoundMedia(s);
  const renders = renderRenders(s);

  if (approvalReview || script || progress || inbox || decisions || activity) {
    for (const section of [storyboard, reviewPlayer, found, renders]) {
      if (section) main.append(section);
    }
    const hasAside = Boolean(progress || inbox || decisions || activity);
    app.append(el("div", { class: `board${hasAside ? "" : " solo"}` }, main, hasAside ? aside : null));
  } else {
    for (const section of [storyboard, reviewPlayer, found, renders]) {
      if (section) app.append(section);
    }
  }
}

// Defensive normalization (F-02): the server contract guarantees these
// fields, but a sparse/legacy payload must degrade, never crash the board.
function normalize(s) {
  s.pipeline = s.pipeline || { pipeline_type: "unknown", stages: [], known: false };
  s.stages = Array.isArray(s.stages) ? s.stages : [];
  for (const stage of s.stages) {
    stage.produces = Array.isArray(stage.produces) ? stage.produces : [];
  }
  s.artifacts = s.artifacts || {};
  s.media = s.media || {};
  s.media.renders = Array.isArray(s.media.renders) ? s.media.renders : [];
  s.media.snapshots = Array.isArray(s.media.snapshots) ? s.media.snapshots : [];
  s.media.music = Array.isArray(s.media.music) ? s.media.music : [];
  s.media.samples = Array.isArray(s.media.samples) ? s.media.samples : [];
  s.media.stills = Array.isArray(s.media.stills) ? s.media.stills : [];
  s.events = Array.isArray(s.events) ? s.events : [];
  s.fastline = s.fastline || null;
  s.run_ops = Array.isArray(s.run_ops) ? s.run_ops : [];
  s.awaiting = Array.isArray(s.awaiting) ? s.awaiting : [];
  s.review_notes = Array.isArray(s.review_notes) ? s.review_notes : [];
  s.next_action = s.next_action || null;
  if (s.storyboard && Array.isArray(s.storyboard.scenes)) {
    for (const c of s.storyboard.scenes) {
      c.takes = Array.isArray(c.takes) ? c.takes : [];
      c.audio = Array.isArray(c.audio) ? c.audio : [];
      c.required_assets = Array.isArray(c.required_assets) ? c.required_assets : [];
    }
  } else {
    s.storyboard = null;
  }
  return s;
}

async function refresh() {
  state = normalize(await getJSON(`/api/project/${encodeURIComponent(projectId)}/state`));
  render();
}

refresh().catch((err) => {
  app.innerHTML = "";
  app.append(el("div", { class: "empty", style: "margin-top:80px" },
    el("div", { class: "big" }, "PROJECT NOT FOUND"),
    el("div", {}, String(err))));
});
// ?static=1 disables the live feed (screenshots, static exports).
if (!new URLSearchParams(location.search).has("static")) {
  subscribe(`/api/project/${encodeURIComponent(projectId)}/events`, () => refresh().catch(console.error));
}

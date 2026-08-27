// 历史成片总览：只读渲染（数据来自 /api/v2/overview/videos；本页从不触发付费评分）。
const DIM_KEYS = [
  ["hook_clarity", "前3秒钩子"],
  ["visual_hierarchy", "视觉层级"],
  ["rhythm", "节奏"],
  ["shot_quality", "镜头质量"],
  ["story_coherence", "故事连贯"],
  ["audio_quality", "音频质量"],
  ["text_readability", "文字可读"],
  ["product_presence", "商品露出"],
];
const STYLE_CLASS = {
  pass: "chip-pass", partial: "chip-partial", pending: "chip-pending",
  external: "chip-external", fail: "chip-fail",
};

async function fetchOverview() {
  const res = await fetch("/api/v2/overview/videos", { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`加载失败（HTTP ${res.status}）`);
  return res.json();
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children) node.append(child ?? "");
  return node;
}

function chip(text, style) {
  return el("span", { class: `chip ${STYLE_CLASS[style] || "chip-pending"}` }, text);
}

function verifyCells(run) {
  const c = run.checks || {};
  const parts = [];
  if (c.sensitive !== undefined) parts.push(`敏感词:${c.sensitive === "pass" ? "0命中" : "命中"}`);
  if (c.subtitle_bounds !== undefined) parts.push(`字幕:${c.subtitle_bounds}`);
  if (c.black_frames !== undefined) parts.push(`黑帧:${c.black_frames}`);
  if (c.freeze !== undefined) parts.push(`冻结:${c.freeze}`);
  const l = c.loudness || {};
  if (l.integrated_lufs !== undefined) parts.push(`响度:${l.integrated_lufs} LUFS / ${l.true_peak_dbtp} dBTP`);
  return parts.join(" · ");
}

function renderMethodology(m) {
  const items = [
    ["评价体系", "docs/EVALUATION_SYSTEM.md §13（business-policy v1.0）"],
    ["Judge/Rubric", `${m.judge_version} / ${m.rubric_version}`],
    ["VLM 模型与种子", `${m.model} · seeds: ${(m.seeds || []).join(", ") || "未评分"}`],
    ["抽帧数", `${m.frame_count}`],
    ["排序规则", m.ranking_rule],
    ["成本口径", m.cost_note],
  ];
  const body = el("div", { class: "method-body" });
  for (const [k, v] of items) {
    body.append(el("dl", { class: "method-item" }, el("dt", {}, k), el("dd", {}, v)));
  }
  const limits = el("dl", { class: "method-item" },
    el("dt", {}, "已知限制"),
    el("dd", {}, el("ul", {}, ...(m.known_limits || []).map((x) => el("li", {}, x)))));
  body.append(limits);
  document.getElementById("methodology-body").replaceChildren(body);
}

function renderOverview(runs) {
  const t = el("table");
  const head = el("thead", {}, el("tr", {},
    ...["#", "视频名称", "时长", "定档", "L3 均分", "单维最低", "短板", "L1a", "证书", "转场", "成片/看板"].map(
      (h, i) => el("th", { class: i >= 2 ? "num" : "" }, h))));
  const body = el("tbody");
  runs.forEach((r, i) => {
    const tierChip = chip(r.tier, r.tier === "推荐" ? "gold" : r.tier === "达标" ? "pass" : "partial");
    const l3 = r.l3 || {};
    const row = el("tr", {},
      el("td", { class: "num" }, String(i + 1)),
      el("td", {}, el("strong", {}, r.sheet_name), el("div", { class: "badge" }, r.run)),
      el("td", { class: "num" }, `${r.duration_s}s`),
      el("td", {}, tierChip),
      el("td", { class: "num" }, l3.scored ? l3.avg : "未评分"),
      el("td", { class: "num" }, l3.scored ? l3.min : "—"),
      el("td", {}, l3.weakest || "—"),
      el("td", { class: "num" }, chip(r.l1a_status, r.l1a_status === "pass" ? "pass" : "fail")),
      el("td", {}, r.certificate ? chip("✅ 绑定", "pass") : chip("无", "pending")),
      el("td", { class: "num" }, `${r.noncut}/${r.cuts}`),
      el("td", {},
        el("a", { class: "media-link", href: `/media/${r.run}/renders/final.mp4`, target: "_blank" }, "成片"),
        " · ",
        el("a", { class: "media-link", href: `/p/${r.run}`, target: "_blank" }, "工作台"),
        r.cost_note ? el("div", { class: "badge" }, `$${r.cost.toFixed(4)}（估算）`) : el("div", { class: "badge" }, `$${r.cost.toFixed(4)}`)),
    );
    body.append(row);
  });
  t.append(head, body);
  document.getElementById("overview-table").replaceChildren(t);
}

function renderGates(data) {
  const runs = data.slim_runs;
  const t = el("table");
  const head = el("thead", {}, el("tr", {},
    ...["规则ID", "规则", "类别", "实现状态", "判定语义", ...runs.map((r) => r.sheet_name)].map((h) => el("th", {}, h))));
  const body = el("tbody");
  for (const g of data.gates) {
    const cells = runs.map((r) => {
      const cell = (g.cells || []).find((c) => c.run === r.run) || { text: "—", style: "pending" };
      return el("td", {}, el("span", { class: `cell-verdict ${STYLE_CLASS[cell.style] || ""}` }, cell.text));
    });
    body.append(el("tr", {},
      el("td", { class: "num" }, g.rule_id),
      el("td", {}, el("strong", {}, g.rule_name), el("div", { class: "badge" }, g.thresholds || "")),
      el("td", {}, g.rule_category),
      el("td", {}, chip(g.impl_status, g.impl_status === "已核验" ? "pass" : g.impl_status === "部分取证" ? "partial" : "pending")),
      el("td", {}, g.severity === "veto" ? "一票否决" : "计分项"),
      ...cells));
  }
  t.append(head, body);
  document.getElementById("gates-table").replaceChildren(t);
}

function bizValue(prelaunchRules, dims) {
  const vals = [];
  for (const rule of prelaunchRules) {
    for (const check of rule.checks || []) {
      if (check.startsWith("l3_")) {
        const v = dims[check.slice(3)];
        if (v !== undefined) vals.push(v);
      }
    }
  }
  return vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2) : "—";
}

function renderQuality(data) {
  const runs = data.slim_runs;
  const bizCols = (data.prelaunch_rules || []).filter((r) => (r.checks || []).length);
  const t = el("table");
  const head = el("thead", {}, el("tr", {},
    ...["排名", "视频", ...DIM_KEYS.map(([, name]) => name), "L3 均分", "单维最低",
       ...bizCols.map((r) => `${r.rule_id} ${r.rule_name}`), "技术核验"].map((h) => el("th", {}, h))));
  const body = el("tbody");
  runs.forEach((r, i) => {
    const dims = r.l3.dims || {};
    const row = el("tr", {},
      el("td", { class: "num" }, String(i + 1)),
      el("td", {}, r.sheet_name));
    for (const [key] of DIM_KEYS) {
      const v = dims[key];
      row.append(el("td", { class: "num" }, v === undefined ? "—" : v));
    }
    row.append(el("td", { class: "num" }, r.l3.scored ? r.l3.avg : "未评分"));
    row.append(el("td", { class: "num" }, r.l3.scored ? r.l3.min : "—"));
    for (const rule of bizCols) {
      row.append(el("td", { class: "num" }, bizValue([rule], dims)));
    }
    row.append(el("td", {}, verifyCells(r)));
    body.append(row);
  });
  t.append(head, body);
  document.getElementById("quality-table").replaceChildren(t);
}

function renderEvidence(data) {
  const panel = document.getElementById("evidence-panel");
  panel.replaceChildren();
  for (const r of data.slim_runs) {
    const items = [
      `L3 摘要：${r.l3.summary || "未评分（运行 export_top_videos 后刷新）"}`,
      `硬门核验：${verifyCells(r) || "—"}`,
      `分辨率/音频：${r.probe_resolution || "—"} · 时长 ${r.probe_duration ?? "—"}s · 音轨 ${r.probe_audio ? "有" : "无"}`,
      `发布时间：${r.published_at || "—"} · 人工确认：${r.human_approved ? "已批准（批量授权口径）" : "未批准"}`,
    ];
    const links = el("li", {},
      el("a", { class: "media-link", href: `/media/${r.run}/renders/final.mp4`, target: "_blank" }, "打开成片"),
      " · ",
      el("a", { class: "media-link", href: `/p/${r.run}`, target: "_blank" }, "候选工作台"),
      " · ",
      el("a", { class: "media-link", href: `/media/${r.run}/artifacts/l1a_final.json`, target: "_blank" }, "L1a 证据"),
    );
    panel.append(el("details", { class: "evidence" },
      el("summary", {}, `${r.sheet_name}（${r.run}）`),
      el("ul", {}, ...items.map((x) => el("li", {}, x)), links)));
  }
}

async function refresh() {
  const sub = document.getElementById("ov-sub");
  try {
    const data = await fetchOverview();
    sub.textContent = `共 ${data.total_runs} 部历史成片 · ${data.scored_count} 部已 L3 评分 · 生成于 ${data.generated_at}`;
    renderMethodology(data.methodology);
    renderOverview(data.slim_runs);
    renderGates(data);
    renderQuality(data);
    renderEvidence(data);
  } catch (err) {
    sub.textContent = String(err.message || err);
  }
}

document.getElementById("refresh").addEventListener("click", refresh);
refresh();

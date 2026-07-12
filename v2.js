"use strict";

const V2_DATA_URL = "data/v2/decision-system.json";
const STATE_LABELS = {
  confirmed: "已确认",
  candidate: "待确认",
  waiting: "等待触发",
  risk: "风险",
  invalidated: "已失效",
  usable: "可用",
  degraded: "降级",
  blocked: "阻断"
};

let v2State = null;
let activeRadarFilter = "all";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function stateLabel(value) {
  return STATE_LABELS[value] || value || "未知";
}

function compactTime(value) {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
  }).format(parsed);
}

function renderQuality(data) {
  const target = document.getElementById("data-quality-gate");
  const state = data?.state || "blocked";
  target.className = `status-panel ${state}`;
  target.innerHTML = `
    <div class="state-row"><span class="eyebrow">数据决策门</span><span class="pill ${escapeHtml(state)}">${escapeHtml(stateLabel(state))}</span></div>
    <h2>${escapeHtml(data?.headline || "数据质量不可用")}</h2>
    <p>价格复核 ${escapeHtml(data?.price_review_count ?? 0)} · 信号复核 ${escapeHtml(data?.signal_review_count ?? 0)} · 背景复核 ${escapeHtml(data?.background_review_count ?? 0)}</p>
    <p class="decision-rule">${escapeHtml(data?.decision_rule || "无法判断")}</p>`;
}

function renderEnvironment(data) {
  const target = document.getElementById("market-environment");
  const quality = data?.quality_state || "blocked";
  target.className = `status-panel ${quality}`;
  const reasons = list(data?.supporting_reasons).slice(0, 2).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  target.innerHTML = `
    <div class="state-row"><span class="eyebrow">市场环境</span><span class="pill ${escapeHtml(quality)}">${escapeHtml(data?.state || "无法判断")}</span></div>
    <h2>${escapeHtml(data?.action || "等待确认")}</h2>
    <p>${escapeHtml(data?.headline || "当前没有可用市场结论")}</p>
    ${reasons ? `<details class="evidence-details"><summary>查看支持依据</summary><ul>${reasons}</ul></details>` : ""}`;
}

function representativeStocks(items) {
  if (!items.length) return "";
  return `<div class="stock-row">${items.slice(0, 6).map(item => {
    if (typeof item === "string") return `<span class="stock-chip">${escapeHtml(item)}</span>`;
    const pct = Number.isFinite(Number(item.change_pct)) ? ` ${Number(item.change_pct).toFixed(2)}%` : "";
    return `<span class="stock-chip"><b>${escapeHtml(item.name || "未知")}</b>${escapeHtml(pct)}</span>`;
  }).join("")}</div>`;
}

function evidenceDetails(card) {
  const evidence = list(card.evidence);
  const counter = list(card.counter_evidence);
  const confirm = list(card.confirm_conditions);
  const invalidation = list(card.invalidation_conditions);
  const rows = [];
  if (evidence.length) {
    rows.push(`<li class="evidence-group-title">支持证据</li>${evidence.map(item => `<li>${escapeHtml(item.summary || item)}${item.source ? ` · ${escapeHtml(item.source)}` : ""}</li>`).join("")}`);
  }
  if (counter.length) rows.push(`<li class="evidence-group-title">反向证据/缺口</li>${counter.map(item => `<li>${escapeHtml(item)}</li>`).join("")}`);
  if (confirm.length) rows.push(`<li class="evidence-group-title">确认条件</li>${confirm.map(item => `<li>${escapeHtml(item)}</li>`).join("")}`);
  if (invalidation.length) rows.push(`<li class="evidence-group-title">失效条件</li>${invalidation.map(item => `<li>${escapeHtml(item)}</li>`).join("")}`);
  return `<details class="evidence-details"><summary>展开证据链与失效点</summary><ul>${rows.join("")}</ul></details>`;
}

function renderRadar(cards) {
  const target = document.getElementById("opportunity-risk-radar");
  if (!cards.length) {
    target.innerHTML = '<div class="empty-state">当前没有达到展示门槛的机会或风险。</div>';
    return;
  }
  target.innerHTML = cards.map(card => {
    const kind = card.kind === "risk" ? "risk" : "opportunity";
    const waiting = card.state === "waiting" || card.state === "candidate";
    const visible = activeRadarFilter === "all" || activeRadarFilter === kind || (activeRadarFilter === "waiting" && waiting);
    const hidden = visible ? "" : " hidden";
    return `<article class="radar-card ${escapeHtml(card.state)}" data-radar-kind="${escapeHtml(kind)}" data-radar-state="${escapeHtml(card.state)}"${hidden}>
      <div class="radar-head"><h3>${escapeHtml(card.title)}</h3><span class="state-badge ${escapeHtml(card.state)}">${escapeHtml(stateLabel(card.state))}</span></div>
      <div class="radar-trigger">${escapeHtml(card.trigger)}</div>
      <p class="radar-conclusion">${escapeHtml(card.conclusion)}</p>
      <div class="action-line">${escapeHtml(card.action)}</div>
      ${representativeStocks(list(card.representative_stocks))}
      ${evidenceDetails(card)}
    </article>`;
  }).join("");
}

function renderStyle(data) {
  const target = document.getElementById("style-map");
  const dimensions = list(data?.dimensions);
  const shifts = list(data?.theme_shifts);
  target.innerHTML = `<div class="dimension-grid">${dimensions.map(item => `
    <article class="dimension-card">
      <div class="state-row"><h3>${escapeHtml(item.label)}</h3><span class="state-text">${escapeHtml(item.state)}</span></div>
      <p>${escapeHtml(item.conclusion)}</p>
      <details class="evidence-details"><summary>定义口径</summary><p>${escapeHtml(item.definition)}</p></details>
    </article>`).join("")}</div>
    <div class="shift-list">${shifts.slice(0, 8).map(item => `
      <article class="shift-card"><h3>${escapeHtml(item.theme)} · ${escapeHtml(item.state)}</h3><p>${escapeHtml(item.conclusion)}</p>${representativeStocks(list(item.stocks))}</article>`).join("")}</div>`;
}

function renderValidation(items) {
  const target = document.getElementById("validation-queue");
  if (!items.length) {
    target.innerHTML = '<div class="empty-state">没有等待核验的方向。</div>';
    return;
  }
  target.innerHTML = `<div class="queue-list">${items.map(item => `
    <article class="queue-card">
      <div class="state-row"><h3>${escapeHtml(item.theme)}</h3><span class="state-text">${escapeHtml(item.status)}</span></div>
      <p>${escapeHtml(item.why_watch)}</p>
      ${representativeStocks(list(item.representative_stocks))}
      <p class="conditions">下一确认：${escapeHtml(list(item.confirm_conditions)[0] || "等待可审计触发")}</p>
    </article>`).join("")}</div>`;
}

function keyValueBlock(title, values) {
  const entries = Object.entries(values || {});
  if (!entries.length) return "";
  return `<div class="rule-block"><strong>${escapeHtml(title)}</strong>${entries.map(([key, value]) => `<p><b>${escapeHtml(key)}</b>：${escapeHtml(value)}</p>`).join("")}</div>`;
}

function renderPortfolio(data) {
  const target = document.getElementById("portfolio-risk");
  target.innerHTML = `<div class="rule-grid">
    <div class="rule-block"><strong>${escapeHtml(data?.headline || "组合数据不可用")}</strong><div class="tag-list">${list(data?.missing_inputs).map(item => `<span class="tag">缺少：${escapeHtml(item)}</span>`).join("")}</div></div>
    ${keyValueBlock("仓位上限规则", data?.position_limits)}
    ${keyValueBlock("止损规则", data?.stop_loss)}
  </div>`;
}

function renderThemes(items) {
  const target = document.getElementById("research-themes");
  target.innerHTML = items.slice(0, 12).map(item => `<article class="theme-card">
    <div class="state-row"><h3>${escapeHtml(item.name)}</h3><span class="state-text">${escapeHtml(item.status)}</span></div>
    <p>${escapeHtml(item.conclusion)}</p>
    <div class="action-line">${escapeHtml(item.action)}</div>
    <div class="tag-list">${list(item.related_topics).slice(0, 5).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
  </article>`).join("") || '<div class="empty-state">产业研究数据尚未接入。</div>';
}

function renderReview(data) {
  const target = document.getElementById("signal-review");
  target.innerHTML = `<div class="review-empty"><strong>${escapeHtml(data?.headline || "复盘不可用")}</strong><p>观察窗口：${list(data?.windows).map(escapeHtml).join(" / ")}</p></div>`;
}

function renderSources(items) {
  document.getElementById("source-registry").innerHTML = `<div class="source-list">${items.map(item => `<div class="source-item"><b>${escapeHtml(item.path)}</b><span>${escapeHtml(item.status)} · ${escapeHtml(compactTime(item.timestamp))}</span></div>`).join("")}</div>`;
}

function setFilter(value) {
  activeRadarFilter = value;
  document.querySelectorAll("#radar-filters button").forEach(button => button.classList.toggle("active", button.dataset.filter === value));
  document.querySelectorAll("[data-radar-kind]").forEach(card => {
    const waiting = card.dataset.radarState === "waiting" || card.dataset.radarState === "candidate";
    card.hidden = !(value === "all" || card.dataset.radarKind === value || (value === "waiting" && waiting));
  });
}

function bindFilters() {
  document.querySelectorAll("#radar-filters button").forEach(button => {
    button.addEventListener("click", () => setFilter(button.dataset.filter || "all"));
  });
}

function renderAll(data) {
  v2State = data;
  const system = data.system || {};
  document.getElementById("v2-mode").textContent = system.mode === "shadow_only" ? "影子模式" : system.mode || "未知模式";
  document.getElementById("v2-updated").textContent = `证据 ${compactTime(system.decision_as_of)}`;
  const qualityState = data.data_quality_gate?.state || "blocked";
  const status = document.getElementById("v2-status");
  status.textContent = stateLabel(qualityState);
  status.className = `pill ${qualityState}`;
  renderQuality(data.data_quality_gate || {});
  renderEnvironment(data.market_environment || {});
  renderRadar(list(data.opportunity_radar));
  renderStyle(data.style_map || {});
  renderValidation(list(data.validation_queue));
  renderPortfolio(data.portfolio_risk || {});
  renderThemes(list(data.research_themes));
  renderReview(data.signal_review || {});
  renderSources(list(data.source_registry));
}

async function loadV2() {
  try {
    const response = await fetch(`${V2_DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderAll(await response.json());
  } catch (error) {
    const radar = document.getElementById("opportunity-risk-radar");
    radar.innerHTML = `<div class="empty-state error-state">V2数据加载失败：${escapeHtml(error.message || error)}</div>`;
    const status = document.getElementById("v2-status");
    status.textContent = "加载失败";
    status.className = "pill blocked";
  }
}

window.V2App = { loadV2, renderAll, setFilter, escapeHtml };
bindFilters();
loadV2();

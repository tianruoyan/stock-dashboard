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
  blocked: "阻断",
  partial: "部分可用",
  data_missing: "数据缺失",
  degraded_response_date_unverified: "降级：历史日期未获验证"
};

let v2State = null;
let activeRadarFilter = "all";
let stockPoolQuery = "";
let bloggerAccounts = [];
let privatePortfolio = { holdings: [], cash: null, risk_budget: {}, trade_authorization: false };

const BLOGGER_PLATFORM_LABELS = {
  xiaohongshu: "小红书", weibo: "微博", wechat: "微信公众号", douyin: "抖音", bilibili: "哔哩哔哩", other: "其他"
};

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

function sourceLink(value) {
  if (!value) return "来源未知";
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return escapeHtml(value);
    return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noreferrer">${escapeHtml(parsed.hostname)}</a>`;
  } catch (_error) {
    return escapeHtml(value);
  }
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
  const sentiment = data?.sentiment_structure || {};
  const crossMarket = list(data?.cross_market);
  const ladderRows = (ladder, suffix) => list(ladder?.items).map(item => `<div class="ladder-row"><b>${escapeHtml(item.height)}${escapeHtml(suffix)}</b><span>${escapeHtml(item.count)}只</span><p>${list(item.stocks).slice(0, 5).map(stock => escapeHtml(stock.name)).join(" / ") || "无代表股"}</p></div>`).join("");
  target.innerHTML = `
    <div class="state-row"><span class="eyebrow">市场环境</span><span class="pill ${escapeHtml(quality)}">${escapeHtml(data?.state || "无法判断")}</span></div>
    <h2>${escapeHtml(data?.action || "等待确认")}</h2>
    <p>${escapeHtml(data?.headline || "当前没有可用市场结论")}</p>
    <div class="market-stats"><span>涨停 ${escapeHtml(sentiment.limit_up_count ?? "缺失")}</span><span>跌停 ${escapeHtml(sentiment.limit_down_count ?? "缺失")}</span><span>炸板 ${escapeHtml(sentiment.broken_limit_count ?? "缺失")}</span></div>
    <details class="evidence-details market-evidence-bundle"><summary>展开市场证据、梯队与跨市场传导</summary>
      ${reasons ? `<div class="market-detail-section"><strong>支持依据</strong><ul>${reasons}</ul></div>` : ""}
      <div class="market-detail-section"><strong>涨停与跌停梯队</strong><p class="ladder-note">梯队为 ${escapeHtml(compactTime(sentiment.as_of))} 清洗口径 · ${sourceLink(sentiment.source)}；顶部总数来自盘中快照，时点或清洗规则不同，不直接比较。</p><div class="ladder-grid"><div><strong>涨停梯队</strong>${ladderRows(sentiment.limit_up_ladder, "板") || `<p>${escapeHtml(sentiment.limit_up_ladder?.note || "数据缺失")}</p>`}</div><div><strong>跌停梯队</strong>${ladderRows(sentiment.limit_down_ladder, "连跌停") || `<p>${escapeHtml(sentiment.limit_down_ladder?.note || "数据缺失")}</p>`}</div></div><p class="ladder-note">晋级率：${escapeHtml(stateLabel(sentiment.promotion_rate?.state || "data_missing"))} · 高位亏钱效应：${escapeHtml(stateLabel(sentiment.high_level_loss_effect?.state || "data_missing"))}</p></div>
      ${crossMarket.length ? `<div class="market-detail-section"><strong>跨市场传导与数据缺口</strong><div class="cross-market-grid">${crossMarket.map(item => `<div class="cross-market-item"><b>${escapeHtml(item.market)}</b><span>${escapeHtml(item.quality_state || "已读取")}</span><p>${escapeHtml(item.conclusion)}</p></div>`).join("")}</div></div>` : ""}
    </details>`;
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
      <details class="evidence-details"><summary>定义口径</summary>
        <p>${escapeHtml(item.definition)}</p>
        ${list(item.representative_sectors).length ? `<p class="style-sectors">代表方向：${list(item.representative_sectors).map(escapeHtml).join(" / ")}</p>` : ""}
        ${item.proxy ? `<p class="style-proxy">观察代理：${escapeHtml(item.proxy.name)}（${escapeHtml(item.proxy.code)}）<br>${escapeHtml(item.proxy.scope_note)}</p>` : ""}
        <p class="definition-version">口径版本：${escapeHtml(item.definition_version || data?.definition_version || "未知")}</p>
      </details>
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
  renderPrivatePortfolio();
}

function optionalNumber(value) {
  return value === "" || value == null ? null : Number(value);
}

function renderPrivatePortfolio() {
  const listTarget = document.getElementById("portfolio-holding-list");
  const analysisTarget = document.getElementById("portfolio-private-analysis");
  if (!listTarget || !analysisTarget) return;
  const holdings = list(privatePortfolio.holdings);
  const invested = holdings.reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.cost || 0), 0);
  const cashKnown = privatePortfolio.cash !== null && privatePortfolio.cash !== "" && Number.isFinite(Number(privatePortfolio.cash));
  const cash = cashKnown ? Number(privatePortfolio.cash) : 0;
  const basis = invested + cash;
  const stockByCode = new Map(list(v2State?.stock_pool?.stocks).map(item => [String(item.code).toLowerCase(), item]));
  const rows = holdings.map(item => {
    const value = Number(item.quantity || 0) * Number(item.cost || 0);
    const allocation = basis > 0 ? value / basis * 100 : null;
    const stock = stockByCode.get(String(item.code).toLowerCase());
    const domain = list(stock?.domains)[0]?.name || "其他/待归类";
    return { ...item, cost_value: value, allocation_pct: allocation, domain };
  });
  const domainValues = {};
  rows.forEach(item => { domainValues[item.domain] = (domainValues[item.domain] || 0) + item.cost_value; });
  const risk = privatePortfolio.risk_budget || {};
  const flags = [];
  rows.forEach(item => {
    if (risk.max_single_position_pct != null && item.allocation_pct != null && item.allocation_pct > Number(risk.max_single_position_pct)) flags.push(`${item.name} 成本占比 ${item.allocation_pct.toFixed(1)}%，高于单一持仓上限 ${Number(risk.max_single_position_pct).toFixed(1)}%。`);
  });
  Object.entries(domainValues).forEach(([domain, value]) => {
    const pct = basis > 0 ? value / basis * 100 : null;
    if (risk.max_theme_pct != null && pct != null && pct > Number(risk.max_theme_pct)) flags.push(`${domain} 成本占比 ${pct.toFixed(1)}%，高于单一主题上限 ${Number(risk.max_theme_pct).toFixed(1)}%。`);
  });
  const investedPct = basis > 0 ? invested / basis * 100 : null;
  if (risk.max_total_invested_pct != null && investedPct != null && investedPct > Number(risk.max_total_invested_pct)) flags.push(`总投入成本占比 ${investedPct.toFixed(1)}%，高于设置上限 ${Number(risk.max_total_invested_pct).toFixed(1)}%。`);
  analysisTarget.innerHTML = holdings.length ? `<div class="private-portfolio-summary"><span>持仓 ${holdings.length} 只</span><span>持仓成本 ¥${invested.toLocaleString("zh-CN", {maximumFractionDigits:2})}</span><span>${cashKnown ? `现金 ¥${cash.toLocaleString("zh-CN", {maximumFractionDigits:2})}` : "现金未填写"}</span><span>${investedPct == null ? "投入比例未知" : `成本投入 ${investedPct.toFixed(1)}%`}</span></div><p class="private-analysis-note">以下仅按数量×成本计算，不代表当前市值或盈亏；实时行情未核验前不生成个性化买卖动作。</p>${flags.length ? `<div class="private-risk-flags">${flags.map(item => `<p>${escapeHtml(item)} <b>需人工复核</b></p>`).join("")}</div>` : '<p class="private-no-flags">按已填写成本口径，暂未触发自设上限；这不代表组合没有市场风险。</p>'}` : '<div class="empty-state">尚未录入真实持仓。您可以只填写风险预算，也可以稍后再录入。</div>';
  listTarget.innerHTML = rows.map(item => `<article class="private-holding-card"><div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.code)}</span></div><p>数量 ${escapeHtml(item.quantity)} · 成本 ${escapeHtml(item.cost)} · ${escapeHtml(item.domain)}</p><small>${item.allocation_pct == null ? "占比待现金数据" : `成本占比 ${item.allocation_pct.toFixed(1)}%`}</small><div class="managed-source-actions"><button type="button" data-holding-action="edit" data-holding-code="${escapeHtml(item.code)}">编辑</button><button type="button" class="danger" data-holding-action="delete" data-holding-code="${escapeHtml(item.code)}">删除</button></div></article>`).join("");
}

function setPortfolioStatus(message, state = "") {
  const target = document.getElementById("portfolio-private-status");
  if (!target) return;
  target.textContent = message;
  target.className = `source-manager-status ${state}`.trim();
}

function hydratePortfolioSettings() {
  const risk = privatePortfolio.risk_budget || {};
  document.getElementById("portfolio-cash").value = privatePortfolio.cash ?? "";
  document.getElementById("portfolio-max-single").value = risk.max_single_position_pct ?? "";
  document.getElementById("portfolio-max-theme").value = risk.max_theme_pct ?? "";
  document.getElementById("portfolio-max-invested").value = risk.max_total_invested_pct ?? "";
  document.getElementById("portfolio-max-drawdown").value = risk.max_drawdown_pct ?? "";
}

async function persistPrivatePortfolio(next, message) {
  const response = await fetch("/_v2-portfolio", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  privatePortfolio = payload.payload;
  hydratePortfolioSettings();
  renderPrivatePortfolio();
  setPortfolioStatus(message, "success");
}

async function loadPrivatePortfolio() {
  try {
    const response = await fetch("/_v2-portfolio", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    privatePortfolio = await response.json();
    hydratePortfolioSettings();
    renderPrivatePortfolio();
    setPortfolioStatus(`本机组合已读取；持仓 ${list(privatePortfolio.holdings).length} 只，交易授权：否。`);
  } catch (_error) {
    renderPrivatePortfolio();
    setPortfolioStatus("组合管理服务暂未连接；公开驾驶舱仍可正常使用。", "warning");
  }
}

function resetHoldingForm() {
  document.getElementById("portfolio-holding-form")?.reset();
  document.getElementById("portfolio-holding-original-code").value = "";
  document.getElementById("portfolio-holding-cancel").hidden = true;
}

function bindPortfolioManager() {
  const settings = document.getElementById("portfolio-settings-form");
  const holdingForm = document.getElementById("portfolio-holding-form");
  const listTarget = document.getElementById("portfolio-holding-list");
  if (!settings || !holdingForm || !listTarget) return;
  settings.addEventListener("submit", async event => {
    event.preventDefault();
    const next = { holdings: list(privatePortfolio.holdings), cash: optionalNumber(document.getElementById("portfolio-cash").value), risk_budget: { max_single_position_pct: optionalNumber(document.getElementById("portfolio-max-single").value), max_theme_pct: optionalNumber(document.getElementById("portfolio-max-theme").value), max_total_invested_pct: optionalNumber(document.getElementById("portfolio-max-invested").value), max_drawdown_pct: optionalNumber(document.getElementById("portfolio-max-drawdown").value) } };
    try { await persistPrivatePortfolio(next, "组合风险设置已保存。") } catch (error) { setPortfolioStatus(`保存失败：${error.message || error}`, "warning"); }
  });
  holdingForm.addEventListener("submit", async event => {
    event.preventDefault();
    const original = document.getElementById("portfolio-holding-original-code").value;
    const row = { code: document.getElementById("portfolio-holding-code").value.trim(), name: document.getElementById("portfolio-holding-name").value.trim(), quantity: Number(document.getElementById("portfolio-holding-quantity").value), cost: Number(document.getElementById("portfolio-holding-cost").value) };
    const nextHoldings = original ? list(privatePortfolio.holdings).map(item => item.code === original ? row : item) : [...list(privatePortfolio.holdings), row];
    try { await persistPrivatePortfolio({ holdings: nextHoldings, cash: privatePortfolio.cash, risk_budget: privatePortfolio.risk_budget || {} }, original ? "持仓已更新。" : "持仓已添加。"); resetHoldingForm(); } catch (error) { setPortfolioStatus(`保存失败：${error.message || error}`, "warning"); }
  });
  document.getElementById("portfolio-holding-cancel").addEventListener("click", resetHoldingForm);
  listTarget.addEventListener("click", async event => {
    const button = event.target.closest("button[data-holding-action]");
    if (!button) return;
    const item = list(privatePortfolio.holdings).find(row => row.code === button.dataset.holdingCode);
    if (!item) return;
    if (button.dataset.holdingAction === "edit") {
      document.getElementById("portfolio-holding-original-code").value = item.code;
      document.getElementById("portfolio-holding-code").value = item.code;
      document.getElementById("portfolio-holding-name").value = item.name;
      document.getElementById("portfolio-holding-quantity").value = item.quantity;
      document.getElementById("portfolio-holding-cost").value = item.cost;
      document.getElementById("portfolio-holding-cancel").hidden = false;
      holdingForm.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (!window.confirm(`删除持仓“${item.name}”？`)) return;
    try { await persistPrivatePortfolio({ holdings: list(privatePortfolio.holdings).filter(row => row.code !== item.code), cash: privatePortfolio.cash, risk_budget: privatePortfolio.risk_budget || {} }, "持仓已删除。"); } catch (error) { setPortfolioStatus(`保存失败：${error.message || error}`, "warning"); }
  });
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

function renderResearchLibrary(data) {
  const target = document.getElementById("research-themes");
  const domains = list(data?.domains);
  const coverageLabel = value => ({coverage_gap: "覆盖缺口", template_ready_mapping_gap: "模板已建·映射待补", mapped: "已映射"}[value] || value || "未知");
  target.innerHTML = domains.map(domain => {
    const template = domain.research_template;
    return `<article class="theme-card ${escapeHtml(domain.coverage_state)}">
    <div class="state-row"><h3>${escapeHtml(domain.name)}</h3><span class="state-text">${escapeHtml(coverageLabel(domain.coverage_state))}</span></div>
    <p>专题 ${escapeHtml(domain.topic_count)} · 股票 ${escapeHtml(domain.stock_count)}</p>
    <div class="tag-list">${list(domain.topics).slice(0, 6).map(item => `<span class="tag">${escapeHtml(item.name)}</span>`).join("")}</div>
    ${domain.coverage_state === "coverage_gap" ? '<p class="coverage-gap-note">尚未接入明确专题或股票映射，不补造研究结论。</p>' : ""}
    ${domain.coverage_state === "template_ready_mapping_gap" ? '<p class="coverage-gap-note">产业研究框架已建立；上市公司映射等待公告、订单或收入证据。</p>' : ""}
    ${template ? `<details class="evidence-details"><summary>查看研究框架与核验指标</summary>
      <p>${escapeHtml(template.theme_definition)}</p>
      <p class="research-subtitle">跟踪指标</p><ul>${list(template.tracking_indicators).slice(0, 5).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      <p class="research-subtitle">失效/降级</p><ul>${list(template.invalidation_conditions).slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      <div class="source-links">${list(template.source_refs).slice(0, 4).map(item => item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>` : "").join("")}</div>
    </details>` : ""}
  </article>`}).join("") || '<div class="empty-state">产业研究数据尚未接入。</div>';
}

function renderStockPool(data) {
  const summary = document.getElementById("stock-pool-summary");
  const target = document.getElementById("stock-pool-list");
  const allStocks = list(data?.stocks);
  const query = stockPoolQuery.trim().toLowerCase();
  const matches = allStocks.filter(item => {
    const haystack = [item.name, item.code, ...list(item.tags), ...list(item.domains).map(domain => domain.name), ...list(item.themes).map(theme => theme.name)].join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });
  summary.innerHTML = `<div class="pool-summary"><span>全量去重 ${escapeHtml(data?.stock_count ?? allStocks.length)} 只</span><span>角色待核验 ${escapeHtml(data?.role_unclassified_count ?? 0)} 只</span><span>当前显示 ${escapeHtml(Math.min(matches.length, 24))}/${escapeHtml(matches.length)} 只</span></div>`;
  target.innerHTML = matches.slice(0, 24).map(item => `<article class="stock-pool-card">
    <div class="state-row"><h3>${escapeHtml(item.name)}</h3><span class="stock-code">${escapeHtml(item.code)}</span></div>
    <p>${escapeHtml(list(item.domains).map(domain => domain.name).join(" / ") || "待归类")}</p>
    <div class="tag-list">${list(item.tags).slice(0, 5).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
    <details class="evidence-details"><summary>关注依据与触发条件</summary>
      <p>${escapeHtml(item.attention_reason)}</p>
      <p class="condition-copy">确认：${escapeHtml(list(item.trigger_conditions)[0] || "待补明确触发条件")}</p>
      <p class="condition-copy invalidation">失效：${escapeHtml(list(item.invalidation_conditions)[0] || "待补明确失效条件")}</p>
      <p class="definition-version">角色：${escapeHtml(list(item.roles).join(" / "))} · 来源池：${escapeHtml(list(item.source_pools).join(" / "))}</p><p class="definition-version">角色依据：${escapeHtml(list(item.role_evidence)[0] || "缺少显式角色证据")}</p>
    </details>
  </article>`).join("") || '<div class="empty-state">没有匹配的股票。</div>';
}

function renderReview(data, model) {
  const target = document.getElementById("signal-review");
  const workflow = list(data?.workflow);
  const recommendation = model?.recommendation || {};
  target.innerHTML = `<div class="review-grid">
    <div class="review-empty"><strong>${escapeHtml(data?.headline || "复盘不可用")}</strong>
      <p>观察窗口：${list(data?.windows).map(escapeHtml).join(" / ")}</p>
      <div class="pool-summary"><span>快照 ${escapeHtml(data?.snapshot_count ?? 0)}</span><span>待验证信号 ${escapeHtml(data?.pending_signal_count ?? 0)}</span><span>已评估 ${escapeHtml(data?.evaluated_signal_count ?? 0)}</span></div>
      <p class="review-guardrail">${escapeHtml(data?.guardrail || "样本不足不展示命中率。")}</p>
    </div>
    <div class="workflow-flow">${workflow.map((item, index) => `<div class="workflow-step"><span>${escapeHtml(index + 1)}</span><div><b>${escapeHtml(item.stage)}</b><small>${escapeHtml(item.owner)}</small></div></div>`).join("")}</div>
    <div class="model-evaluation-card"><strong>离线模型评估</strong><p>基线 ${escapeHtml(model?.baseline_version || "未配置")} · 主窗口 ${escapeHtml(model?.primary_window || "待定")} · 已评估 ${escapeHtml(model?.record_count ?? 0)}</p><p>${escapeHtml(recommendation.reason || "等待结果数据。")}</p><span>${model?.automatic_live_promotion ? "允许自动晋级" : "禁止自动晋级"}</span></div>
  </div>`;
}

function renderParallelComparison(data) {
  const target = document.getElementById("parallel-comparison");
  if (!target) return;
  const sideCard = side => `<div class="parallel-side-card"><div class="state-row"><strong>${escapeHtml(side?.label || "未知")}</strong><span class="pill ${escapeHtml(side?.quality_state || "degraded")}">${escapeHtml(side?.role || "未知角色")}</span></div><p>市场日 ${escapeHtml(side?.market_date || "未知")} · 质量 ${escapeHtml(side?.quality_state || "缺失")} · 自动化 ${escapeHtml(side?.automation_state || "缺失")}</p><div class="pool-summary"><span>质量问题 ${escapeHtml(side?.quality_issue_count ?? 0)}</span><span>价格复核 ${escapeHtml(side?.price_review_count ?? 0)}</span><span>机会 ${escapeHtml(side?.opportunity_count ?? 0)}</span><span>风险 ${escapeHtml(side?.risk_count ?? 0)}</span></div><small>证据 ${escapeHtml(compactTime(side?.evidence_as_of))}</small></div>`;
  const divergences = list(data?.divergences);
  target.innerHTML = `<div class="parallel-summary"><strong>${escapeHtml(data?.headline || "双轨对照尚未生成")}</strong><span>${data?.cutover?.ready ? "达到切换条件" : "继续并行"}</span></div><div class="parallel-sides">${sideCard(data?.v1)}${sideCard(data?.v2)}</div><div class="parallel-divergences"><strong>需要解释的差异</strong>${divergences.length ? divergences.map(item => `<div class="parallel-diff"><b>${escapeHtml(item.conclusion)}</b><p>${escapeHtml(item.action)}</p>${list(item.only_v1).length ? `<small>仅V1：${list(item.only_v1).map(escapeHtml).join(" / ")}</small>` : ""}${list(item.only_v2).length ? `<small>仅V2：${list(item.only_v2).map(escapeHtml).join(" / ")}</small>` : ""}</div>`).join("") : '<p class="empty-state">当前没有结构性差异。</p>'}</div><p class="parallel-guardrail">${escapeHtml(data?.cutover?.reason || "停用V1仍需再次确认。")}</p>`;
}

function renderGovernance(data, inputStatus) {
  const target = document.getElementById("governance-status");
  const layers = data?.fact_inference_action_layers || {};
  const events = data?.event_registry || {};
  const routing = data?.automation_routing || {};
  const blogger = events.blogger_policy || {};
  const inputs = list(inputStatus?.contracts);
  const publicCollectors = list(inputStatus?.public_collectors);
  const authorizations = data?.user_authorizations || {};
  target.innerHTML = `<div class="governance-grid">
    <div class="governance-card"><strong>结论分层</strong>${Object.entries(layers).map(([key, value]) => `<p><b>${escapeHtml(key)}</b>${escapeHtml(value)}</p>`).join("")}</div>
    <div class="governance-card"><strong>事件来源</strong><p>事件 ${escapeHtml(events.event_count ?? 0)} 条 · ${events.state === "input_pending" ? "输入待接入" : "已接入"}</p><p>已配置博主 ${escapeHtml(events.blogger_enabled_account_count ?? 0)} 个 · ${escapeHtml(blogger.required_role || "仅作预期/情绪")}</p></div>
    <div class="governance-card"><strong>自动化归属</strong><p>已登记 ${escapeHtml(routing.task_count ?? 0)} 项 · ${escapeHtml(routing.state || "未知")}</p><p>${escapeHtml(routing.cutover_rule || "切换规则待配置")}</p></div>
    <div class="governance-card"><strong>数据输入</strong><p>${escapeHtml(inputStatus?.privacy_note || "原始输入不进入公开发布。")}</p><div class="input-status-list">${publicCollectors.map(item => `<span class="${escapeHtml(item.state)}">${escapeHtml(item.id)} · ${escapeHtml(item.state)}</span>`).join("")}${inputs.map(item => `<span class="${escapeHtml(item.status)}">${escapeHtml(item.id)} · ${escapeHtml(item.status)}</span>`).join("") || "尚未运行导入检查"}</div></div>
    <div class="governance-card"><strong>App访问授权</strong><p>${authorizations.routine_external_app_access === "preauthorized" ? "项目内常规读取与核验已授权，无需逐次确认。" : "尚未记录常规访问授权。"}</p><p>${escapeHtml(authorizations.privacy_rule || "只读取本项目所需的最小范围。")}</p></div>
  </div>`;
}

function setBloggerStatus(message, state = "") {
  const target = document.getElementById("blogger-source-status");
  if (!target) return;
  target.textContent = message;
  target.className = `source-manager-status ${state}`.trim();
}

function renderBloggerSources() {
  const target = document.getElementById("blogger-source-list");
  if (!target) return;
  if (!bloggerAccounts.length) {
    target.innerHTML = '<div class="empty-state">尚未添加关注来源。添加后，采集任务会按平台能力读取公开内容。</div>';
    return;
  }
  target.innerHTML = bloggerAccounts.map(item => `<article class="managed-source-card ${item.enabled === false ? "disabled" : ""}">
    <div><span class="source-platform">${escapeHtml(BLOGGER_PLATFORM_LABELS[item.platform] || item.platform)}</span><strong>${escapeHtml(item.display_name)}</strong><small>${item.enabled === false ? "已停用" : "已启用"}</small></div>
    <p>${escapeHtml(item.note || "未填写关注说明")}</p>
    <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">核验原始链接</a>
    <div class="managed-source-actions"><button type="button" data-source-action="edit" data-source-id="${escapeHtml(item.id)}">编辑</button><button type="button" data-source-action="toggle" data-source-id="${escapeHtml(item.id)}">${item.enabled === false ? "启用" : "停用"}</button><button type="button" class="danger" data-source-action="delete" data-source-id="${escapeHtml(item.id)}">删除</button></div>
  </article>`).join("");
}

async function persistBloggerSources(nextAccounts, successMessage) {
  const response = await fetch("/_v2-blogger-accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accounts: nextAccounts })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  bloggerAccounts = list(payload.payload?.accounts);
  renderBloggerSources();
  setBloggerStatus(successMessage, "success");
}

async function loadBloggerSources() {
  try {
    const response = await fetch("/_v2-blogger-accounts", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    bloggerAccounts = list(payload.accounts);
    renderBloggerSources();
    setBloggerStatus(`本机已保存 ${bloggerAccounts.length} 个来源；账号与链接不会进入公开发布。`);
  } catch (_error) {
    renderBloggerSources();
    setBloggerStatus("来源管理服务暂未连接。请从本地投资看板入口打开本页，其他决策模块不受影响。", "warning");
  }
}

function resetBloggerForm() {
  document.getElementById("blogger-source-form")?.reset();
  document.getElementById("blogger-source-id").value = "";
  document.getElementById("blogger-source-cancel").hidden = true;
}

function bindBloggerManager() {
  const form = document.getElementById("blogger-source-form");
  const listTarget = document.getElementById("blogger-source-list");
  if (!form || !listTarget) return;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const id = document.getElementById("blogger-source-id").value;
    const row = {
      id,
      platform: document.getElementById("blogger-source-platform").value,
      display_name: document.getElementById("blogger-source-name").value.trim(),
      url: document.getElementById("blogger-source-url").value.trim(),
      note: document.getElementById("blogger-source-note").value.trim(),
      enabled: id ? bloggerAccounts.find(item => item.id === id)?.enabled !== false : true
    };
    const next = id ? bloggerAccounts.map(item => item.id === id ? row : item) : [...bloggerAccounts, row];
    try {
      await persistBloggerSources(next, id ? "来源已更新。" : "来源已添加。");
      resetBloggerForm();
    } catch (error) {
      setBloggerStatus(`保存失败：${error.message || error}`, "warning");
    }
  });
  document.getElementById("blogger-source-cancel").addEventListener("click", resetBloggerForm);
  listTarget.addEventListener("click", async event => {
    const button = event.target.closest("button[data-source-action]");
    if (!button) return;
    const id = button.dataset.sourceId;
    const item = bloggerAccounts.find(row => row.id === id);
    if (!item) return;
    if (button.dataset.sourceAction === "edit") {
      document.getElementById("blogger-source-id").value = item.id;
      document.getElementById("blogger-source-platform").value = item.platform;
      document.getElementById("blogger-source-name").value = item.display_name;
      document.getElementById("blogger-source-url").value = item.url;
      document.getElementById("blogger-source-note").value = item.note || "";
      document.getElementById("blogger-source-cancel").hidden = false;
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (button.dataset.sourceAction === "delete" && !window.confirm(`删除“${item.display_name}”？`)) return;
    const next = button.dataset.sourceAction === "delete"
      ? bloggerAccounts.filter(row => row.id !== id)
      : bloggerAccounts.map(row => row.id === id ? { ...row, enabled: row.enabled === false } : row);
    try {
      await persistBloggerSources(next, button.dataset.sourceAction === "delete" ? "来源已删除。" : "来源状态已更新。");
    } catch (error) {
      setBloggerStatus(`保存失败：${error.message || error}`, "warning");
    }
  });
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

function bindStockSearch() {
  const input = document.getElementById("stock-pool-search");
  if (!input) return;
  input.addEventListener("input", () => {
    stockPoolQuery = input.value || "";
    renderStockPool(v2State?.stock_pool || {});
  });
}

function renderAll(data) {
  v2State = data;
  const system = data.system || {};
  document.getElementById("v2-mode").textContent = system.operation_strategy === "parallel_shadow" ? "双轨影子" : (system.mode === "shadow_only" ? "影子模式" : system.mode || "未知模式");
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
  renderResearchLibrary(data.research_library || {});
  renderStockPool(data.stock_pool || {});
  renderReview(data.signal_review || {}, data.model_evaluation || {});
  renderParallelComparison(data.parallel_comparison || {});
  renderGovernance(data.governance || {}, data.input_status || {});
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

window.V2App = { loadV2, renderAll, setFilter, renderStockPool, escapeHtml };
bindFilters();
bindStockSearch();
bindBloggerManager();
bindPortfolioManager();
loadBloggerSources();
loadPrivatePortfolio();
loadV2();

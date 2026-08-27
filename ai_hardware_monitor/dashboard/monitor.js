const STATUS_URL = "../data/status.json";
const SIGNALS_URL = "../data/signals.json";
const INTRADAY_TRIGGER_URL = "../data/intraday-trigger-status.json";

function byId(id) { return document.getElementById(id); }
function list(value) { return Array.isArray(value) ? value : []; }
function object(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"}[character]));
}
function number(value, digits = 1) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "--";
}
function signed(value, suffix = "%") {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "--";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(2)}${suffix}`;
}
function shortTime(value) {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}).format(parsed);
}

function renderOverview(status) {
  const state = object(status.state);
  const stateCode = state.code || "observe";
  byId("state-card").className = `state-card ${stateCode}`;
  byId("state-label").textContent = state.label || "🟡观察";
  byId("state-action").textContent = state.action || "等待最新检查结果。";
  byId("checkpoint-label").textContent = object(status.checkpoint).label || "未到检查点";
  byId("evidence-time").textContent = `证据 ${shortTime(status.as_of)}`;
  byId("header-state").textContent = state.label || "观察";
  byId("header-state").className = `pill ${stateCode === "launch" ? "usable" : stateCode === "risk" ? "blocked" : "degraded"}`;
  byId("header-updated").textContent = shortTime(status.generated_at);
  byId("total-score").textContent = Number.isFinite(Number(status.score)) ? String(status.score) : "--";
  byId("score-ring").style.setProperty("--score", Math.max(0, Math.min(100, Number(status.score) || 0)));
  byId("score-copy").textContent = list(status.failed_launch_gates).length ? `仍缺：${list(status.failed_launch_gates).slice(0, 2).join("、")}` : "绿色硬门槛已同时满足。";
  const coverage = Number(status.coverage_ratio);
  byId("coverage-value").textContent = Number.isFinite(coverage) ? `${Math.round(coverage * 100)}%` : "--";
  byId("coverage-bar").style.width = `${Math.max(0, Math.min(100, coverage * 100 || 0))}%`;
  const quality = object(status.data_quality);
  byId("quality-copy").textContent = quality.usable ? quality.freshness || "当前证据可用" : quality.freshness || "等待数据补齐";
  const next = object(status.next_checkpoint);
  byId("next-checkpoint").textContent = next.scheduled_at ? `下一节点：${next.label || next.scheduled_at}` : "今日检查已完成";
}

function renderCategories(status) {
  byId("category-grid").innerHTML = list(status.categories).map(category => {
    const maximum = Number(category.max_points) || 1;
    const score = Number(category.score) || 0;
    const components = list(category.components).map(component => `
      <div class="component-row ${component.available ? "" : "missing"}">
        <span title="${escapeHtml(component.detail)}">${escapeHtml(component.label)}</span>
        <b>${component.available ? `${escapeHtml(component.points)} / ${escapeHtml(component.max_points)}` : "缺数据"}</b>
      </div>`).join("");
    return `<section class="category-card">
      <div class="category-head"><h3>${escapeHtml(category.label)}</h3><strong>${score}<small>/${maximum}</small></strong></div>
      <div class="dimension-track"><span style="width:${Math.round(score / maximum * 100)}%"></span></div>
      <div class="component-list">${components}</div>
    </section>`;
  }).join("") || '<p class="empty-copy">暂无评分结果。</p>';
}

function renderGates(status) {
  byId("gate-list").innerHTML = list(status.launch_gates).map(gate => `
    <div class="gate-row ${gate.passed ? "pass" : ""}">
      <span class="gate-mark">${gate.passed ? "✓" : "×"}</span>
      <span>${escapeHtml(gate.label)}</span>
      <small>${gate.actual === null || gate.actual === undefined ? "缺失" : escapeHtml(number(gate.actual, Number(gate.actual) < 5 ? 2 : 0))}</small>
    </div>`).join("") || '<p class="empty-copy">暂无门槛结果。</p>';
}

function renderStocks(status) {
  byId("stock-rows").innerHTML = list(status.stocks).map(stock => {
    const change = Number(stock.change_pct);
    const changeClass = !Number.isFinite(change) ? "unknown" : change >= 0 ? "positive" : "negative";
    const trend = stock.above_ma5 === true && stock.above_ma10 === true ? "5/10日线上" : stock.above_ma5 === null || stock.above_ma10 === null ? "待数据" : "未同时站上";
    return `<tr>
      <td>${escapeHtml(stock.name)}</td><td>${escapeHtml(stock.segment)}</td><td>${escapeHtml(stock.role)}</td>
      <td class="${changeClass}">${signed(stock.change_pct)}</td><td>${stock.turnover_pace === null || stock.turnover_pace === undefined ? "--" : `${number(stock.turnover_pace, 2)}x`}</td>
      <td>${escapeHtml(trend)}</td><td>${escapeHtml(shortTime(stock.quote_as_of))}</td>
    </tr>`;
  }).join("") || '<tr><td colspan="7">当前检查点尚未取得有效股票行情。</td></tr>';
}

function renderMissing(status) {
  const missing = list(object(status.data_quality).missing);
  byId("missing-list").innerHTML = missing.length ? missing.map(item => `<div class="missing-item">${escapeHtml(item)}</div>`).join("") : '<p class="empty-copy">当前没有已登记的数据缺口。</p>';
}

function renderAlerts(signals) {
  const alerts = list(signals.alerts).slice(-4).reverse();
  byId("alert-list").innerHTML = alerts.length ? alerts.map(alert => `
    <div class="alert-item"><strong>${escapeHtml(alert.headline)}</strong><span>${escapeHtml(alert.reason)}</span><small>${escapeHtml(shortTime(alert.emitted_at))}</small></div>`).join("") : '<p class="empty-copy">尚未产生状态变化提醒。</p>';
}

function renderIntradayTrigger(status) {
  const trigger = object(status.trigger);
  const active = trigger.active === true;
  const notificationSent = object(status.notification).state === "sent";
  const card = document.querySelector(".intraday-trigger-card");
  if (card) card.classList.toggle("active", active);
  byId("intraday-trigger-state").textContent = trigger.label || "⚪等待首次巡检";
  byId("intraday-trigger-badge").textContent = active ? "已触发" : "未触发";
  byId("intraday-trigger-badge").className = `state-badge ${active ? "confirmed" : "waiting"}`;
  const failed = list(trigger.failed_conditions);
  byId("intraday-trigger-copy").textContent = active
    ? notificationSent
      ? "盘中共振条件已满足，本机提醒已经送达；仍需等待固定检查点确认。"
      : "盘中共振条件已满足，提醒已按去重与冷却规则处理；仍需等待固定检查点确认。"
    : failed.length ? `尚缺：${failed.slice(0, 3).join("、")}` : "09:40-11:25、13:05-14:50 每3分钟检查一次。";
  byId("intraday-trigger-time").textContent = `最近巡检：${shortTime(status.generated_at)}`;
  byId("intraday-trigger-conditions").innerHTML = list(trigger.conditions).map(condition => `
    <div class="trigger-condition ${condition.passed ? "pass" : ""}">
      <span>${condition.passed ? "✓" : "×"}</span><span>${escapeHtml(condition.label)}</span>
      <small>${condition.actual === null || condition.actual === undefined ? "缺失" : escapeHtml(condition.actual)}</small>
    </div>`).join("") || '<p class="empty-copy">等待首次盘中巡检。</p>';
}

async function loadJson(url) {
  const response = await fetch(`${url}?v=${Date.now()}`, {cache: "no-store"});
  if (!response.ok) throw new Error(`${url} 返回 ${response.status}`);
  return response.json();
}

async function boot() {
  try {
    const [status, signals, intradayTrigger] = await Promise.all([loadJson(STATUS_URL), loadJson(SIGNALS_URL), loadJson(INTRADAY_TRIGGER_URL)]);
    renderOverview(status);
    renderCategories(status);
    renderGates(status);
    renderStocks(status);
    renderMissing(status);
    renderAlerts(signals);
    renderIntradayTrigger(intradayTrigger);
  } catch (error) {
    byId("page-load-error").textContent = `雷达数据尚未生成或无法读取：${error.message}`;
    byId("header-state").textContent = "等待数据";
  }
}

boot();

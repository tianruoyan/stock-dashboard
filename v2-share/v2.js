"use strict";

const SHARE_READ_ONLY = true;

const V2_DATA_URL = "data/v2/decision-system.json";
const WATCHLIST_MIGRATION_AUDIT_URL = "data/v2/v22/watchlist-migration-audit.json";
const V22_STOCK_POOL_URL = "data/v2/v22/stock-pool-shadow.json";
const V22_MARKET_ENVIRONMENT_URL = "data/v2/v22/market-environment.json";
const V22_ENVIRONMENT_DECISION_URL = "data/v2/v22/environment-decision.json";
const V22_DECISION_CANDIDATE_URL = "data/v2/v22/decision-system-candidate.json";
const V22_REPLAY_URL = "data/v2/v22/replay-index.json";
const V22_EVALUATION_URL = "data/v2/v22/model-evaluation.json";
const V22_PARALLEL_URL = "data/v2/v22/parallel-comparison.json";
const STATE_LABELS = {
  confirmed: "已确认",
  candidate: "待确认",
  waiting: "等待触发",
  risk: "风险",
  invalidated: "已失效",
  expired: "已过有效时间",
  usable: "可用",
  degraded: "降级",
  blocked: "阻断",
  partial: "部分可用",
  data_missing: "数据缺失",
  degraded_response_date_unverified: "降级：历史日期未获验证",
  observed_by_themes: "主题样本观察",
  usable_proxy: "可用代理",
  crowded: "抱团拥挤",
  warming: "升温",
  emerging: "初现",
  loaded: "已加载",
  missing: "缺失",
  ok: "正常",
  current: "当前可用",
  updated: "已更新",
  unchanged: "无变化",
  pending: "待补充",
  valid: "有效",
  collecting: "积累中",
  production_primary: "V1 生产主入口",
  shadow_observer: "V2 影子观察",
  rule_screen: "规则筛选",
  deterministic_rules: "确定性规则",
  ai_explain: "AI 解释",
  ai: "AI",
  human_decide: "人工决策",
  user: "用户"
};

const SOURCE_LABELS = {
  "alert.json": "盘中异动监测",
  "opportunity-watch.json": "交易预案",
  "decision-feed.json": "决策线索",
  "intraday.json": "盘中市场快照",
  "quality-report.json": "数据质量检查",
  "data-trust.json": "来源可信度检查",
  "automation-health.json": "数据任务状态"
};

const ROLE_LABELS = { unclassified: "待核验", core: "中军", leader: "龙头", platform: "平台", high_beta: "弹性" };
const POOL_LABELS = { watch_only: "个人观察", small_deng: "小登观察", old_deng: "老登观察", middle_deng: "中登观察" };
const LAYER_LABELS = { fact: "事实", inference: "推断", action: "建议" };
const INPUT_LABELS = {
  microcap: "微盘结构", sentiment: "情绪结构", official_events: "官方事件", outcome_prices: "结果价格",
  microcap_observation: "微盘观察", sentiment_structure: "涨跌停梯队", market_breadth_snapshot: "市场宽度", market_liquidity_snapshot: "市场流动性", portfolio_context: "组合上下文", events: "事件输入"
};

let v2State = null;
let activeRadarFilter = "all";
let stockPoolQuery = "";
let bloggerAccounts = [];
let privatePortfolio = { holdings: [], cash: null, risk_budget: {}, trade_authorization: false };
let privateUserAssets = { "状态": "尚未读取", "数量": 0, "用户自选": [] };
let v22StockPool = null;
let v22MarketEnvironment = null;
let v22EnvironmentDecision = null;
let v22DecisionCandidate = null;
let v2LoadInFlight = false;
let radarRefreshTimer = null;

const BLOGGER_PLATFORM_LABELS = {
  xiaohongshu: "小红书", weibo: "微博", wechat: "微信公众号", douyin: "抖音", bilibili: "哔哩哔哩", other: "其他"
};
const USER_PRIORITY_LABELS = { high: "高", normal: "普通", low: "低" };
const USER_INTENT_LABELS = { holding: "持仓", swing: "波段关注", watch: "等待机会", research: "长期研究", event: "事件跟踪", "未设置": "未设置" };
const USER_SOURCE_LABELS = { ths_cloud: "同花顺云", manual_add: "手动添加", broker_sync: "券商同步" };

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function prepareShareMode() {
  if (!SHARE_READ_ONLY) return;
  document.querySelectorAll('a[href="index.html"]').forEach(link => {
    link.href = "v2.html";
    link.textContent = "安全只读版";
  });
  document.getElementById("source-manager")?.remove();
  document.getElementById("watchlist-sync-shadow")?.remove();
  document.getElementById("portfolio-manager")?.remove();
  document.querySelector(".cockpit-user-context")?.remove();
}

function humanText(value) {
  return String(value ?? "")
    .replace(/本地盘中监控日志\s*monitor\.log/gi, "盘中异动监测记录")
    .replace(/\bmonitor\.log\b/gi, "盘中异动监测记录")
    .replace(/\bdegraded_response_date_unverified\b/gi, "历史日期尚未核验")
    .replace(/\bdegraded\b/gi, "数据降级")
    .replace(/risk candidate/gi, "风险候选")
    .replace(/\bcandidate\b/gi, "待确认")
    .replace(/\bconfirmed\b/gi, "已确认")
    .replace(/\bexpired\b/gi, "已过有效时间")
    .replace(/\bevaluation_eligible\b/gi, "有效复盘样本")
    .replace(/\bfreshness_state\b/gi, "信息时效")
    .replace(/\bvalidity_missing\b/gi, "有效时间待补")
    .replace(/\bcanonical_key\b/gi, "复盘样本标识")
    .replace(/\bblocked_validation\b/gi, "等待核验")
    .replace(/\bsource_reason\b/gi, "关注依据")
    .replace(/>=/g, "不低于")
    .replace(/<=/g, "不高于")
    .replace(/->/g, "传导至")
    .replace(/[\[\]{}]/g, "")
    .replace(/"\s*,\s*"/g, "、")
    .replace(/^\s*[",]+|[",]+\s*$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function stateLabel(value) {
  return STATE_LABELS[value] || "状态待核验";
}

function sourceLabel(value) {
  const raw = String(value || "");
  const labels = raw.split(",").map(item => SOURCE_LABELS[item.trim()]).filter(Boolean);
  return [...new Set(labels)].join("、") || "来源记录可核验";
}

function compactTime(value) {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
  }).format(parsed);
}

function compactTimeWithSeconds(value) {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
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
  if (!target) return;
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
  if (!target) return;
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
      ${crossMarket.length ? `<div class="market-detail-section"><strong>跨市场传导与数据缺口</strong><div class="cross-market-grid">${crossMarket.map(item => `<div class="cross-market-item"><b>${escapeHtml(item.market)}</b><span>${escapeHtml(stateLabel(item.quality_state || "loaded"))}</span><p>${escapeHtml(item.conclusion)}</p></div>`).join("")}</div></div>` : ""}
    </details>`;
}

const ENVIRONMENT_LEVEL_LABELS = {
  support: "支持", partial_support: "部分支持", neutral: "中性", suppress: "抑制", risk_release: "风险释放", unknown: "待补证据"
};
const ENVIRONMENT_QUALITY_LABELS = { usable: "事实可用", degraded: "部分可用", blocked: "关键冲突", unknown: "数据不足" };
const ENVIRONMENT_SOURCE_STATE_LABELS = { current: "同日可用", stale: "旧时点已排除", missing: "尚未取得", conflict: "口径冲突" };
const ENVIRONMENT_STATE_LABELS = {
  risk_release: "风险释放", repair: "修复", rotation_trial: "轮动试探", mainline_confirmed: "主线确认",
  diffusion_strengthening: "扩散增强", crowding_divergence: "拥挤分歧", retreat: "退潮"
};
const STYLE_STATE_LABELS = { strengthening: "走强候选", weakening: "走弱候选", mixed: "内部分化", unknown: "证据不足" };
const TRANSMISSION_STATE_LABELS = { background_only: "仅作背景", pending: "等待A股验证", confirmed: "传导确认", divergent: "A股背离" };
const G5_LABELS = { support: "环境支持", partial_support: "局部支持", neutral: "环境中性", suppress: "环境抑制", block: "环境阻断" };

function renderEnvironmentV22(data) {
  const summary = document.getElementById("market-environment-v22-summary");
  const dimensionsTarget = document.getElementById("market-environment-v22-dimensions");
  const sourcesTarget = document.getElementById("market-environment-v22-sources");
  if (!summary || !dimensionsTarget || !sourcesTarget) return;
  v22MarketEnvironment = data;
  const view = data?.user_view || {};
  const dimensions = list(data?.dimensions);
  const evidence = new Map(list(data?.evidence_refs).map(item => [item.evidence_ref_id, item]));
  summary.innerHTML = `<div class="environment-shadow-summary"><div><span class="pill ${escapeHtml(data?.quality_state || "unknown")}">${escapeHtml(ENVIRONMENT_QUALITY_LABELS[data?.quality_state] || "数据待核验")}</span><strong>${escapeHtml(view["标题"] || "八维事实尚未形成")}</strong><p>${escapeHtml(view["当前判断"] || "等待同一交易日事实。")}</p><p class="environment-action-copy">当前允许：${escapeHtml(view["当前允许"] || "等待确认")}</p></div><div class="environment-shadow-counts"><span><b>${escapeHtml(view["支持项"] ?? 0)}</b>支持</span><span><b>${escapeHtml(view["抑制项"] ?? 0)}</b>抑制</span><span><b>${escapeHtml(view["待补项"] ?? 0)}</b>待补</span><span><b>${escapeHtml(view["冲突项"] ?? 0)}</b>冲突</span></div></div><p class="environment-shadow-time">${escapeHtml(view["交易日"] || "交易日待核验")} · ${escapeHtml(view["阶段"] || "时点待核验")} · 行情截至 ${escapeHtml(compactTime(view["行情时点"]))}。${escapeHtml(view["说明"] || "")}</p>`;
  dimensionsTarget.innerHTML = dimensions.map(item => {
    const refs = list(item.evidence_ref_ids).map(id => evidence.get(id)).filter(Boolean);
    const stockMap = new Map();
    refs.flatMap(ref => list(ref.representative_securities)).filter(stock => stock?.name && stock?.code).forEach(stock => stockMap.set(`${stock.code}-${stock.role || ""}`, stock));
    const stocks = [...stockMap.values()];
    const representative = stocks.length ? `<div class="environment-representatives"><strong>代表性证据</strong>${stocks.slice(0, 5).map(stock => `<span><b>${escapeHtml(stock.name)}</b> ${escapeHtml(stockCodeLabel(stock.code))}${Number.isFinite(Number(stock.change_pct)) ? ` ${Number(stock.change_pct) > 0 ? "+" : ""}${Number(stock.change_pct).toFixed(2)}%` : ""}<small>${escapeHtml(compactTime(stock.as_of))} · ${escapeHtml(humanText(stock.source || "来源待核验"))}</small></span>`).join("")}</div>` : "";
    const facts = list(item.fact_summary);
    const counters = list(item.counter_evidence);
    const missing = list(item.missing_evidence);
    return `<article class="environment-dimension-card ${escapeHtml(item.support_level || "unknown")}"><div class="state-row"><h3>${escapeHtml(item.label || "环境维度")}</h3><span class="environment-level">${escapeHtml(ENVIRONMENT_LEVEL_LABELS[item.support_level] || "待核验")}</span></div><p>${escapeHtml(item.conclusion || "等待事实。")}</p><div class="environment-fact-line"><b>依据</b>${escapeHtml(facts[0] || "当前没有足够事实")}</div>${counters.length ? `<div class="environment-fact-line counter"><b>反向证据</b>${escapeHtml(counters[0])}</div>` : ""}${missing.length ? `<div class="environment-fact-line missing"><b>待补</b>${escapeHtml(missing.slice(0, 2).join("；"))}</div>` : ""}<details><summary>展开全部证据</summary>${facts.length ? `<ul>${facts.map(value => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : ""}${counters.length ? `<strong>反向证据</strong><ul>${counters.map(value => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : ""}${missing.length ? `<strong>数据缺口</strong><ul>${missing.map(value => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : ""}${representative}</details></article>`;
  }).join("") || '<div class="empty-state">八维事实暂未生成。</div>';
  const conflicts = list(data?.conflicts);
  const sourceRows = list(data?.source_status);
  sourcesTarget.innerHTML = `<div class="environment-source-grid">${sourceRows.map(item => `<div><strong>${escapeHtml(item.label || "数据来源")}</strong><span>${escapeHtml(ENVIRONMENT_SOURCE_STATE_LABELS[item.state] || "待核验")} · ${escapeHtml(compactTime(item.as_of))}</span><p>${escapeHtml(item.note || "")}</p></div>`).join("")}</div>${conflicts.length ? `<div class="environment-conflict-note"><strong>当前冲突</strong>${conflicts.map(item => `<p>${escapeHtml(item.metric_name || "数据口径")}：${escapeHtml(humanText(item.resolution || "已保留原值，暂不用于判断。"))}</p>`).join("")}</div>` : '<p class="environment-no-conflict">当前没有同一时点、同一范围的数值冲突。</p>'}`;
}

async function loadMarketEnvironmentV22() {
  const target = document.getElementById("market-environment-v22-summary");
  if (!target) return;
  try {
    const response = await fetch(`${V22_MARKET_ENVIRONMENT_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("八维环境暂不可用");
    renderEnvironmentV22(await response.json());
  } catch (_error) {
    target.innerHTML = '<div class="empty-state">八维环境影子结果暂时没有更新成功；当前V2环境结论保持不变。</div>';
  }
}

function renderEnvironmentDecisionV22(data) {
  const decisionTarget = document.getElementById("market-environment-v22-decision");
  const styleTarget = document.getElementById("style-regime-v22");
  const crossTarget = document.getElementById("cross-market-v22");
  if (!decisionTarget || !styleTarget || !crossTarget) return;
  const transition = data?.state_transition || {};
  const currentState = ENVIRONMENT_STATE_LABELS[data?.primary_state] || "等待判断";
  decisionTarget.innerHTML = `<div class="environment-decision-summary"><div><span class="eyebrow">当前环境状态</span><strong>${escapeHtml(currentState)}</strong><p>${escapeHtml(data?.action_constraint || "等待确认")}</p></div><div><b>为什么</b><p>${escapeHtml(transition.transition_reason || "等待连续事实快照。")}</p><small>积极变化需连续两次确认；可靠风险可先降低行动许可。</small></div></div>`;
  const styles = list(data?.style_regimes);
  styleTarget.innerHTML = `<div class="environment-subsection-title"><strong>风格观察</strong><span>风格池不等于用户股票池</span></div><div class="style-regime-grid">${styles.map(item => {
    const representative = list(item.representative_securities).slice(0, 4);
    return `<article><div class="state-row"><h3>${escapeHtml(item.label || "风格")}</h3><span>${escapeHtml(STYLE_STATE_LABELS[item.price_state] || "待核验")}</span></div><p>${escapeHtml(item.conclusion || "等待证据。")}</p>${representative.length ? `<div class="compact-evidence-list">${representative.map(stock => `<span><b>${escapeHtml(stock.name || "代表对象")}</b>${Number.isFinite(Number(stock.change_pct)) ? ` ${Number(stock.change_pct) > 0 ? "+" : ""}${Number(stock.change_pct).toFixed(2)}%` : ""}<small>${escapeHtml(stockCodeLabel(stock.code))} · ${escapeHtml(compactTime(stock.as_of))} · ${escapeHtml(humanText(stock.source || "来源待核验"))}</small></span>`).join("")}</div>` : '<small>同日代表行情不足，不判断方向。</small>'}<p class="counter-note">反向检查：${escapeHtml(list(item.counter_evidence)[0] || "等待反向证据")}</p></article>`;
  }).join("")}</div>`;
  const mappings = list(data?.cross_market_mappings);
  crossTarget.innerHTML = `<div class="environment-subsection-title"><strong>外盘到A股的验证</strong><span>不采用“外盘涨=A股涨”</span></div><div class="cross-validation-grid">${mappings.map(item => `<article><div class="state-row"><h3>${escapeHtml(list(item.origin_objects).slice(0, 2).join(" / ") || "外盘线索")}</h3><span>${escapeHtml(TRANSMISSION_STATE_LABELS[item.transmission_state] || "待核验")}</span></div><p>${escapeHtml(item.conclusion || "等待传导证据。")}</p><small>A股观察：${escapeHtml(list(item.representative_securities).map(stock => stock.name).join(" / ") || "代表股行情待补")}</small><p class="counter-note">失效检查：${escapeHtml(list(item.counter_evidence)[0] || "等待反向证据")}</p></article>`).join("")}</div>`;
}

async function loadEnvironmentDecisionV22() {
  if (!document.getElementById("market-environment-v22-decision") && !document.getElementById("opportunity-risk-radar")) return;
  try {
    const response = await fetch(`${V22_ENVIRONMENT_DECISION_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("环境状态暂不可用");
    v22EnvironmentDecision = await response.json();
    renderEnvironmentDecisionV22(v22EnvironmentDecision);
    if (v2State) {
      if (v22DecisionCandidate) renderDecisionCandidateV22(v22DecisionCandidate);
      else {
        const radar = radarByCurrentTime(v2State);
        renderRadar(radar.current);
        renderValidation(list(v2State.validation_queue));
      }
    }
  } catch (_error) {
    const target = document.getElementById("market-environment-v22-decision");
    if (target) target.innerHTML = '<div class="empty-state">环境状态影子结果暂未更新；现有机会状态保持不变。</div>';
  }
}

function environmentGateFor(card) {
  if (card?.environment_gate) return card.environment_gate;
  return list(v22EnvironmentDecision?.g5_links).find(item => item.opportunity_id === card?.id) || null;
}

function renderEnvironmentGate(card) {
  const gate = environmentGateFor(card);
  if (!gate) return '<div class="environment-gate neutral"><strong>环境门禁</strong><span>等待环境核验</span><p>现有机会状态保持不变。</p></div>';
  return `<div class="environment-gate ${escapeHtml(gate.g5_result || "neutral")}"><strong>环境门禁</strong><span>${escapeHtml(G5_LABELS[gate.g5_result] || "等待核验")}</span><p>${escapeHtml(gate.reason || "等待环境证据。")}</p><small>${escapeHtml(gate.effective_action || "仅保留观察")}</small></div>`;
}

function representativeStocks(items) {
  if (!items.length) return "";
  return `<div class="stock-row">${items.slice(0, 6).map(item => {
    if (typeof item === "string") return `<span class="stock-chip">${escapeHtml(item)}</span>`;
    const quoteReady = Number.isFinite(Number(item.stock_change_pct)) && Boolean(item.stock_quote_as_of) && Boolean(item.stock_quote_source);
    const pct = quoteReady ? ` ${Number(item.stock_change_pct).toFixed(2)}%` : "";
    const code = item.stock_code ? `<small class="stock-code-label">${escapeHtml(stockCodeLabel(item.stock_code))}</small>` : `<small class="stock-code-label missing">代码待补</small>`;
    const role = item.role ? `<small>${escapeHtml(item.role)}</small>` : "";
    const basis = item.basis ? `<em>${escapeHtml(humanText(item.basis))}</em>` : "";
    const quoteAudit = quoteReady
      ? `<small class="stock-quote-audit">行情 ${escapeHtml(compactTime(item.stock_quote_as_of))} · ${escapeHtml(humanText(item.stock_quote_source))}</small>`
      : `<small class="stock-quote-audit missing">行情待补，不用于当前判断</small>`;
    return `<span class="stock-chip"><b>${escapeHtml(item.name || "未知")}</b>${escapeHtml(pct)}${code}${role}${quoteAudit}${basis}</span>`;
  }).join("")}</div>`;
}

function stockCodeLabel(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (/^sh\d{6}$/.test(raw)) return `${raw.slice(2)}.SH`;
  if (/^sz\d{6}$/.test(raw)) return `${raw.slice(2)}.SZ`;
  if (/^bj\d{6}$/.test(raw)) return `${raw.slice(2)}.BJ`;
  if (/^hk\d{5}$/.test(raw)) return `${raw.slice(2)}.HK`;
  return String(value || "代码待补");
}

function visibleRiskAndInvalidation(card) {
  const risks = list(card.risk_factors).length ? list(card.risk_factors) : list(card.counter_evidence);
  const invalidation = list(card.invalidation_conditions);
  const riskText = risks.slice(0, 2).map(item => humanText(item)).filter(Boolean).join("；") || "暂无新增风险依据，仍需核验代表股与板块是否同向。";
  const invalidationText = invalidation.slice(0, 3).map(item => humanText(item)).filter(Boolean).join("；") || "关键证据失效或代表股与板块背离。";
  return `<div class="risk-invalidation-grid"><div><strong>主要风险</strong><p>${escapeHtml(riskText)}</p></div><div><strong>失效条件</strong><p>${escapeHtml(invalidationText)}</p></div></div>`;
}

function triggerMetrics(data) {
  if (!data?.metric_scope) return "";
  const pct = Number.isFinite(Number(data.change_pct)) ? `${Number(data.change_pct).toFixed(2)}%` : "数值待核验";
  const window = data.window ? ` · ${escapeHtml(data.window.replace("m", "分钟"))}` : "";
  return `<div class="trigger-metrics"><strong>${escapeHtml(data.scope_label || "触发指标")}</strong><span>${escapeHtml(pct)}${window}</span><small>指标时点 ${escapeHtml(compactTime(data.as_of))}</small></div>`;
}

function evidenceDetails(card) {
  const evidence = list(card.evidence);
  const counter = list(card.counter_evidence);
  const confirm = list(card.confirm_conditions);
  const invalidation = list(card.invalidation_conditions);
  const rows = [];
  if (evidence.length) {
    rows.push(`<li class="evidence-group-title">支持证据</li>${evidence.map(item => `<li>${escapeHtml(humanText(item.summary || item))}${item.source ? ` · ${escapeHtml(sourceLabel(item.source))}` : ""}</li>`).join("")}`);
  }
  if (counter.length) rows.push(`<li class="evidence-group-title">反向证据/缺口</li>${counter.map(item => `<li>${escapeHtml(humanText(item))}</li>`).join("")}`);
  if (confirm.length) rows.push(`<li class="evidence-group-title">确认条件</li>${confirm.map(item => `<li>${escapeHtml(humanText(item))}</li>`).join("")}`);
  if (invalidation.length) rows.push(`<li class="evidence-group-title">失效条件</li>${invalidation.map(item => `<li>${escapeHtml(humanText(item))}</li>`).join("")}`);
  return `<details class="evidence-details"><summary>展开证据链与失效点</summary><ul>${rows.join("")}</ul></details>`;
}

function renderRadar(cards) {
  const target = document.getElementById("opportunity-risk-radar");
  if (!target) return;
  if (!cards.length) {
    target.innerHTML = '<div class="empty-state">当前没有同时满足有效时间和代表股依据的机会或风险。保持等待，不追旧信号；下方可查看待核验方向和历史触发。</div>';
    return;
  }
  target.innerHTML = cards.map(card => {
    const kind = card.kind === "risk" ? "risk" : "opportunity";
    const waiting = card.state === "waiting" || card.state === "candidate";
    const visible = activeRadarFilter === "all" || activeRadarFilter === kind || (activeRadarFilter === "waiting" && waiting);
    const hidden = visible ? "" : " hidden";
    return `<article class="radar-card ${escapeHtml(card.state)}" data-radar-kind="${escapeHtml(kind)}" data-radar-state="${escapeHtml(card.state)}"${hidden}>
      <div class="radar-head"><h3>${escapeHtml(humanText(card.title))}</h3><span class="state-badge ${escapeHtml(card.state)}">${escapeHtml(stateLabel(card.state))}</span></div>
      <div class="radar-trigger">${escapeHtml(humanText(card.trigger))}</div>
      ${triggerMetrics(card.trigger_metrics)}
      <p class="radar-conclusion">${escapeHtml(humanText(card.conclusion))}</p>
      ${renderEnvironmentGate(card)}
      <div class="action-line">${escapeHtml(humanText(card.action))}</div>
      ${representativeStocks(list(card.representative_stocks))}
      ${visibleRiskAndInvalidation(card)}
      ${evidenceDetails(card)}
    </article>`;
  }).join("");
}

function renderRadarHistory(cards) {
  const target = document.getElementById("opportunity-history");
  if (!target) return;
  if (!cards.length) {
    target.innerHTML = '<div class="empty-state">暂无需要回看的历史触发。</div>';
    return;
  }
  target.innerHTML = `<div class="history-list">${cards.slice(0, 8).map(card => `<article class="history-card">
    <div class="state-row"><h3>${escapeHtml(humanText(card.title))}</h3><span>仅供复盘</span></div>
    <p><strong>当时发生：</strong>${escapeHtml(humanText(card.trigger))}</p>
    ${triggerMetrics(card.trigger_metrics)}
    <p><strong>当时判断：</strong>${escapeHtml(humanText(card.conclusion))}</p>
    <p class="history-action">${escapeHtml(humanText(card.action || "有效时间已结束，不作为当前操作依据。"))}</p>
    ${representativeStocks(list(card.representative_stocks))}
    ${evidenceDetails(card)}
  </article>`).join("")}</div>`;
}

function renderStyle(data) {
  const target = document.getElementById("style-map");
  if (!target) return;
  const dimensions = list(data?.dimensions);
  const shifts = list(data?.theme_shifts);
  target.innerHTML = `<div class="dimension-grid">${dimensions.map(item => `
    <article class="dimension-card">
      <div class="state-row"><h3>${escapeHtml(item.label)}</h3><span class="state-text">${escapeHtml(stateLabel(item.state))}</span></div>
      <p>${escapeHtml(item.conclusion)}</p>
      <details class="evidence-details"><summary>定义口径</summary>
        <p>${escapeHtml(item.definition)}</p>
        ${list(item.representative_sectors).length ? `<p class="style-sectors">代表方向：${list(item.representative_sectors).map(escapeHtml).join(" / ")}</p>` : ""}
        ${item.proxy ? `<p class="style-proxy">观察代理：${escapeHtml(item.proxy.name)}（${escapeHtml(item.proxy.code)}）<br>${escapeHtml(item.proxy.scope_note)}</p>` : ""}
        <p class="definition-version">口径版本：${escapeHtml(item.definition_version || data?.definition_version || "未知")}</p>
      </details>
    </article>`).join("")}</div>
    <div class="shift-list">${shifts.slice(0, 8).map(item => `
      <article class="shift-card"><h3>${escapeHtml(item.theme)} · ${escapeHtml(stateLabel(item.state))}</h3><p>${escapeHtml(item.conclusion)}</p>${representativeStocks(list(item.stocks))}</article>`).join("")}</div>`;
}

function renderValidation(items) {
  const target = document.getElementById("validation-queue");
  if (!target) return;
  if (!items.length) {
    target.innerHTML = '<div class="empty-state">没有等待核验的方向。</div>';
    return;
  }
  target.innerHTML = `<div class="queue-list">${items.slice(0, 12).map(item => `
    <article class="queue-card">
      <div class="state-row"><h3>${escapeHtml(humanText(item.theme))}</h3><span class="state-text">${escapeHtml(item.maturity_label || stateLabel(item.status))}</span></div>
      ${item.path_label ? `<div class="case-path-line"><span>${escapeHtml(item.path_label)}</span><span>${escapeHtml(item.signal_label || "候选")}</span></div>` : ""}
      ${item.path_label ? `<div class="case-decision-copy"><strong>当前判断</strong><p>${escapeHtml(item.maturity_label || "等待确认")}：${escapeHtml(humanText(item.action || "等待确认"))}</p></div><div class="case-why-copy"><strong>为什么</strong><p>${escapeHtml(humanText(item.why_watch_summary || item.why_watch || "关联证据等待核验"))}</p></div>` : `<p>${escapeHtml(humanText(item.why_watch_summary || item.why_watch || "关联证据等待核验"))}</p>`}
      ${representativeStocks(list(item.representative_stocks))}
      ${renderEnvironmentGate(item)}
      ${item.action ? `<div class="action-line"><strong>操作建议</strong>${escapeHtml(humanText(item.action))}</div>` : ""}
      <p class="conditions">${item.path_label ? "加强条件" : "下一确认"}：${escapeHtml(humanText(list(item.confirm_conditions)[0] || "等待可审计触发"))}</p>
      ${visibleRiskAndInvalidation(item)}
      ${item.valid_window_display ? `<p class="valid-window-copy">${escapeHtml(humanText(item.valid_window_display))}</p>` : ""}
      ${list(item.waiting_reasons).length ? `<details class="decision-gate-details"><summary>为什么仍在等待</summary><ul>${list(item.waiting_reasons).map(reason => `<li><b>${escapeHtml(reason.label || "待核验")}</b>：${escapeHtml(humanText(reason.conclusion || "等待证据"))}</li>`).join("")}</ul></details>` : ""}
      ${list(item.evidence_refs).length ? `<details class="evidence-details"><summary>查看已采用与未采用依据</summary><ul>${list(item.evidence_refs).slice(0, 8).map(ref => `<li><b>${ref.accepted === false ? "未采用" : "已采用"}</b>：${escapeHtml(humanText(ref.summary || "依据待核验"))}</li>`).join("")}</ul></details>` : ""}
    </article>`).join("")}</div>`;
}

function keyValueBlock(title, values) {
  const entries = Object.entries(values || {});
  if (!entries.length) return "";
  return `<div class="rule-block"><strong>${escapeHtml(title)}</strong>${entries.map(([key, value]) => `<p><b>${escapeHtml(key)}</b>：${escapeHtml(value)}</p>`).join("")}</div>`;
}

function renderPortfolio(data) {
  const target = document.getElementById("portfolio-risk");
  if (!target) return;
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
  if (!target) return;
  target.innerHTML = items.slice(0, 12).map(item => `<article class="theme-card">
    <div class="state-row"><h3>${escapeHtml(item.name)}</h3><span class="state-text">${escapeHtml(item.status)}</span></div>
    <p>${escapeHtml(item.conclusion)}</p>
    <div class="action-line">${escapeHtml(item.action)}</div>
    <div class="tag-list">${list(item.related_topics).slice(0, 5).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
  </article>`).join("") || '<div class="empty-state">产业研究数据尚未接入。</div>';
}

function renderResearchLibrary(data) {
  const target = document.getElementById("research-themes");
  if (!target) return;
  const domains = list(data?.domains);
  const coverageLabel = value => ({coverage_gap: "覆盖缺口", template_ready_mapping_gap: "模板已建·映射待补", mapped: "已映射"}[value] || value || "未知");
  target.innerHTML = domains.map(domain => {
    const template = domain.research_template;
    const caseLink = list(v22DecisionCandidate?.research_links).find(item => item.domain === domain.name);
    return `<article class="theme-card ${escapeHtml(domain.coverage_state)}">
    <div class="state-row"><h3>${escapeHtml(domain.name)}</h3><span class="state-text">${escapeHtml(coverageLabel(domain.coverage_state))}</span></div>
    <p>专题 ${escapeHtml(domain.topic_count)} · 股票 ${escapeHtml(domain.stock_count)}</p>
    ${caseLink ? `<p class="research-case-link">当前关联观察案例 ${escapeHtml(caseLink.active_case_count)} 个；盘中状态只在交易驾驶舱维护。</p>` : ""}
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
  if (!summary || !target) return;
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
      <p class="definition-version">角色：${escapeHtml(list(item.roles).map(value => ROLE_LABELS[value] || value).join(" / "))} · 来源池：${escapeHtml(list(item.source_pools).map(value => POOL_LABELS[value] || value).join(" / "))}</p><p class="definition-version">角色依据：${escapeHtml(list(item.role_evidence)[0] || "缺少显式角色证据")}</p>
    </details>
  </article>`).join("") || '<div class="empty-state">没有匹配的股票。</div>';
}

function renderWatchlistSyncShadow(data) {
  const target = document.getElementById("watchlist-sync-shadow-content");
  if (!target) return;
  const view = data?.user_view || {};
  const state = view["状态"] || "等待首次影子读取";
  const stateClass = state.includes("阻断") || state.includes("失败") ? "blocked" : (state.includes("完整") ? "usable" : "partial");
  target.innerHTML = `<div class="watchlist-shadow-summary">
    <div><span class="pill ${escapeHtml(stateClass)}">${escapeHtml(state)}</span><strong>${escapeHtml(view["应用状态"] || "影子核对，尚未应用到我的关注")}</strong><p>${escapeHtml(view["说明"] || "同步结果等待生成。")}</p></div>
    <div class="watchlist-shadow-counts"><span><b>${escapeHtml(view["当前读取数量"] ?? 0)}</b>本次读取</span><span><b>${escapeHtml(view["现有个人观察数量"] ?? 0)}</b>现有观察</span><span><b>${escapeHtml(view["新增线索数量"] ?? 0)}</b>新增线索</span><span><b>${escapeHtml(view["疑似缺失数量"] ?? 0)}</b>疑似缺失</span><span><b>${escapeHtml(view["冲突数量"] ?? 0)}</b>待核对冲突</span></div>
  </div><p class="watchlist-shadow-time">最近读取：${escapeHtml(compactTime(view["最近读取"]))}。缺失只表示本次未观察到，不代表已从你的自选中删除。</p>`;
}

async function loadWatchlistSyncShadow() {
  const target = document.getElementById("watchlist-sync-shadow-content");
  if (!target) return;
  try {
    const response = await fetch(`${WATCHLIST_MIGRATION_AUDIT_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("同步对照暂不可用");
    renderWatchlistSyncShadow(await response.json());
  } catch (_error) {
    target.innerHTML = '<div class="empty-state">自选同步对照暂时没有更新成功；现有关注保持不变。</div>';
  }
}

function renderLayerQuote(quote) {
  if (!quote || quote.change_pct == null || !quote.as_of || !quote.source) return '<span class="asset-quote missing">行情待核验</span>';
  const value = Number(quote.change_pct);
  const direction = value > 0 ? "up" : (value < 0 ? "down" : "flat");
  return `<span class="asset-quote ${direction}">${escapeHtml(value > 0 ? "+" : "")}${escapeHtml(value.toFixed(2))}% · ${escapeHtml(compactTime(quote.as_of))} · ${escapeHtml(quote.source)}</span>`;
}

function findUserAssetQuote(code) {
  const normalized = String(code || "").toLowerCase();
  const publicRows = [
    ...list(v22StockPool?.formal_observation?.items),
    ...list(v22StockPool?.formal_observation?.near_ready_items),
    ...list(v22StockPool?.temporary_candidates?.items),
    ...list(v22StockPool?.trading_candidates?.items)
  ];
  const publicMatch = publicRows.find(item => String(item.code || "").toLowerCase() === normalized && item.quote);
  if (publicMatch) return publicMatch.quote;
  const cards = v2State ? [...list(v2State.opportunity_radar), ...list(v2State.opportunity_history), ...list(v2State.validation_queue)] : [];
  for (const card of cards) {
    const stock = list(card.representative_stocks).find(item => String(item.stock_code || "").toLowerCase() === normalized);
    if (stock?.stock_change_pct != null && stock.stock_quote_as_of && stock.stock_quote_source) return { change_pct: stock.stock_change_pct, as_of: stock.stock_quote_as_of, source: stock.stock_quote_source };
  }
  return null;
}

function renderStockPoolLayers() {
  const summary = document.getElementById("stock-pool-v22-summary");
  const userTarget = document.getElementById("user-asset-layer");
  const formalTarget = document.getElementById("formal-observation-layer");
  const temporaryTarget = document.getElementById("temporary-candidate-layer");
  if (!summary || !userTarget || !formalTarget || !temporaryTarget) return;
  const userItems = list(privateUserAssets?.["用户自选"]);
  const formal = v22StockPool?.formal_observation || {};
  const activeFormal = list(formal.items);
  const nearReady = list(formal.near_ready_items);
  const displayedFormal = activeFormal.length ? activeFormal : nearReady;
  const temporary = list(v22StockPool?.temporary_candidates?.items);
  const formalCards = displayedFormal.slice(0, 8).map(item => {
    const styleCopy = list(item.style_relations).length ? `风格关联：${list(item.style_relations).join(" / ")}；仅作环境证据` : "无风格归属替代";
    return `<article class="asset-layer-card"><div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.code)}</span></div>${renderLayerQuote(item.quote)}<p>AI当前判断：${escapeHtml(item.ai_view || "等待确认")}</p><p>待补：${list(item.missing_requirements).slice(0, 3).map(escapeHtml).join("、") || "无"}</p><small>${escapeHtml(styleCopy)}</small></article>`;
  }).join("");
  summary.innerHTML = `<div class="layer-summary"><span>我的关注 <b>${escapeHtml(userItems.length)}</b></span><span>正式观察 <b>${escapeHtml(formal.active_count ?? 0)}</b></span><span>研究待补 <b>${escapeHtml(formal.near_ready_count ?? 0)}</b></span><span>交易候选 <b>${escapeHtml(v22StockPool?.trading_candidates?.count ?? 0)}</b></span><span>系统发现 <b>${escapeHtml(v22StockPool?.temporary_candidates?.count ?? 0)}</b></span></div><p>调用顺序：我的关注 → 正式观察 → 系统发现；同一股票只显示一次，风格样本不改变归属。</p>`;
  userTarget.innerHTML = userItems.slice(0, 8).map(item => `<article class="asset-layer-card user-owned"><div><strong>${escapeHtml(item["名称"] || "名称待核验")}</strong><span>${escapeHtml(item["代码"] || "代码待核验")}</span></div>${renderLayerQuote(findUserAssetQuote(item["代码"]))}<p>我的优先级：${escapeHtml(USER_PRIORITY_LABELS[item["用户优先级"]] || "未设置")} · 关注目的：${escapeHtml(USER_INTENT_LABELS[item["关注目的"]] || "未设置")}</p><p>我的备注：${escapeHtml(item["用户备注"] || "未填写")}</p><small>来源：${list(item["有效来源"]).map(value => escapeHtml(USER_SOURCE_LABELS[value] || "用户确认来源")).join(" / ") || "等待核验"}</small></article>`).join("") || '<div class="layer-empty">安全分享版不包含用户自选、优先级、备注或账户来源。</div>';
  formalTarget.innerHTML = `${activeFormal.length ? "" : '<p class="layer-warning">当前没有完全满足研究门槛的正式观察；以下是要素较完整的候选。</p>'}${formalCards || '<div class="layer-empty">研究要素尚不足，未形成正式观察。</div>'}`;
  temporaryTarget.innerHTML = temporary.slice(0, 8).map(item => `<article class="asset-layer-card temporary"><div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.code)}</span></div>${renderLayerQuote(item.quote)}<p>${escapeHtml(item.ai_view || "系统发现，尚未加入我的关注")}</p><p>发现依据：${escapeHtml(item.discovery_context || "等待补充")}</p><small>风险：${escapeHtml(item.risk || "等待核验")}</small></article>`).join("") || '<div class="layer-empty">当前系统线索没有可核验代表股，不自动扩充股票池。</div>';
}

function renderCockpitUserContext() {
  const target = document.getElementById("cockpit-user-assets");
  if (!target) return;
  const userItems = list(privateUserAssets?.["用户自选"]);
  if (!userItems.length) {
    target.innerHTML = '<div class="cockpit-asset-message"><strong>当前没有已确认的用户资产</strong><p>旧观察池和老登/中登/小登风格样本不会被当作你的自选；机会雷达继续运行，但不会伪造“用户关注参与”。</p></div>';
    return;
  }
  const currentRadar = v2State ? radarByCurrentTime(v2State).current : [];
  const radarStocks = new Map();
  currentRadar.forEach(card => list(card.representative_stocks).forEach(stock => {
    const code = String(stock.stock_code || "").toLowerCase();
    if (code) radarStocks.set(code, { card, stock });
  }));
  const matches = userItems.map(item => ({ item, match: radarStocks.get(String(item["代码"] || "").toLowerCase()) })).filter(row => row.match);
  if (!matches.length) {
    target.innerHTML = `<div class="cockpit-asset-message"><strong>当前机会未见用户关注标的参与</strong><p>已检查 ${escapeHtml(userItems.length)} 只用户确认资产；这是一条反向证据，不代表相关板块一定无效。</p></div>`;
    return;
  }
  target.innerHTML = `<div class="cockpit-asset-list">${matches.slice(0, 8).map(({item, match}) => `<article><strong>${escapeHtml(item["名称"])}</strong><span>${escapeHtml(item["代码"])}</span><p>当前关联：${escapeHtml(match.card.title || "机会待核验")} · ${escapeHtml(match.card.action || "等待确认")}</p><small>用户身份只提高展示优先级，仍需满足全部交易条件。</small></article>`).join("")}</div>`;
}

async function loadStockPoolLayers() {
  if (!document.getElementById("stock-pool-v22") && !document.getElementById("cockpit-user-assets")) return;
  try {
    const publicResponse = await fetch(`${V22_STOCK_POOL_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!publicResponse.ok) throw new Error("股票池分层暂不可用");
    v22StockPool = await publicResponse.json();
    privateUserAssets = { "状态": "安全分享版不发布", "数量": 0, "用户自选": [] };
    renderStockPoolLayers();
    renderCockpitUserContext();
  } catch (_error) {
    const target = document.getElementById("stock-pool-v22-summary") || document.getElementById("cockpit-user-assets");
    if (target) target.innerHTML = '<div class="empty-state">股票池分层暂时没有更新成功；现有V2页面继续可用。</div>';
  }
}

function renderReview(data, model) {
  const target = document.getElementById("signal-review");
  if (!target) return;
  const workflow = list(data?.workflow);
  const recommendation = model?.recommendation || {};
  target.innerHTML = `<div class="review-grid">
    <div class="review-empty"><strong>${escapeHtml(data?.headline || "复盘不可用")}</strong>
      <p>观察窗口：${list(data?.windows).map(escapeHtml).join(" / ")}</p>
      <div class="pool-summary"><span>有效复盘样本 ${escapeHtml(data?.snapshot_count ?? 0)}</span><span>待验证信号 ${escapeHtml(data?.pending_signal_count ?? 0)}</span><span>已完成结果检验 ${escapeHtml(data?.evaluated_signal_count ?? 0)}</span></div>
      <p class="review-guardrail">${escapeHtml(data?.guardrail || "样本不足不展示命中率。")}</p>
    </div>
    <div class="workflow-flow">${workflow.map((item, index) => `<div class="workflow-step"><span>${escapeHtml(index + 1)}</span><div><b>${escapeHtml(stateLabel(item.stage))}</b><small>${escapeHtml(stateLabel(item.owner))}</small></div></div>`).join("")}</div>
    <div class="model-evaluation-card"><strong>历史结果检验</strong><p>当前规则基线 · 主要观察窗口 ${escapeHtml(model?.primary_window || "待定")} · 已评估 ${escapeHtml(model?.record_count ?? 0)}</p><p>${escapeHtml(recommendation.reason || "等待结果数据。")}</p><span>${model?.automatic_live_promotion ? "等待人工确认" : "不会自动改变交易规则"}</span></div>
  </div>`;
}

function renderParallelComparison(data) {
  const target = document.getElementById("parallel-comparison");
  if (!target) return;
  const sideCard = side => `<div class="parallel-side-card"><div class="state-row"><strong>${escapeHtml(side?.label || "未知")}</strong><span class="pill ${escapeHtml(side?.quality_state || "degraded")}">${escapeHtml(stateLabel(side?.role))}</span></div><p>市场日 ${escapeHtml(side?.market_date || "未知")} · 质量 ${escapeHtml(stateLabel(side?.quality_state || "missing"))} · 自动化 ${escapeHtml(stateLabel(side?.automation_state || "missing"))}</p><div class="pool-summary"><span>质量问题 ${escapeHtml(side?.quality_issue_count ?? 0)}</span><span>价格复核 ${escapeHtml(side?.price_review_count ?? 0)}</span><span>机会 ${escapeHtml(side?.opportunity_count ?? 0)}</span><span>风险 ${escapeHtml(side?.risk_count ?? 0)}</span></div><small>证据 ${escapeHtml(compactTime(side?.evidence_as_of))}</small></div>`;
  const divergences = list(data?.divergences);
  target.innerHTML = `<div class="parallel-summary"><strong>${escapeHtml(data?.headline || "双轨对照尚未生成")}</strong><span>${data?.cutover?.ready ? "达到切换条件" : "继续并行"}</span></div><div class="parallel-sides">${sideCard(data?.v1)}${sideCard(data?.v2)}</div><div class="parallel-divergences"><strong>需要解释的差异</strong>${divergences.length ? divergences.map(item => `<div class="parallel-diff"><b>${escapeHtml(item.conclusion)}</b><p>${escapeHtml(item.action)}</p>${list(item.only_v1).length ? `<small>仅V1：${list(item.only_v1).map(escapeHtml).join(" / ")}</small>` : ""}${list(item.only_v2).length ? `<small>仅V2：${list(item.only_v2).map(escapeHtml).join(" / ")}</small>` : ""}</div>`).join("") : '<p class="empty-state">当前没有结构性差异。</p>'}</div><p class="parallel-guardrail">${escapeHtml(data?.cutover?.reason || "停用V1仍需再次确认。")}</p>`;
}

function renderGovernance(data, inputStatus) {
  const target = document.getElementById("governance-status");
  if (!target) return;
  const layers = data?.fact_inference_action_layers || {};
  const events = data?.event_registry || {};
  const routing = data?.automation_routing || {};
  const blogger = events.blogger_policy || {};
  const inputs = list(inputStatus?.contracts);
  const publicCollectors = list(inputStatus?.public_collectors);
  const authorizations = data?.user_authorizations || {};
  target.innerHTML = `<div class="governance-grid">
    <div class="governance-card"><strong>结论分层</strong>${Object.entries(layers).map(([key, value]) => `<p><b>${escapeHtml(LAYER_LABELS[key] || key)}</b>${escapeHtml(value)}</p>`).join("")}</div>
    <div class="governance-card"><strong>事件来源</strong><p>事件 ${escapeHtml(events.event_count ?? 0)} 条 · ${events.state === "input_pending" ? "输入待接入" : "已接入"}</p><p>已配置博主 ${escapeHtml(events.blogger_enabled_account_count ?? 0)} 个 · 仅作市场预期/情绪</p></div>
    <div class="governance-card"><strong>自动化归属</strong><p>已登记 ${escapeHtml(routing.task_count ?? 0)} 项 · ${escapeHtml(stateLabel(routing.state))}</p><p>${escapeHtml(routing.cutover_rule || "切换规则待配置")}</p></div>
    <div class="governance-card"><strong>数据输入</strong><p>${escapeHtml(inputStatus?.privacy_note || "原始输入不进入公开发布。")}</p><div class="input-status-list">${publicCollectors.map(item => `<span class="${escapeHtml(item.state)}">${escapeHtml(INPUT_LABELS[item.id] || item.id)} · ${escapeHtml(stateLabel(item.state))}</span>`).join("")}${inputs.map(item => `<span class="${escapeHtml(item.status)}">${escapeHtml(INPUT_LABELS[item.id] || item.id)} · ${escapeHtml(stateLabel(item.status))}</span>`).join("") || "尚未运行导入检查"}</div></div>
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
  const target = document.getElementById("source-registry");
  if (!target) return;
  target.innerHTML = `<div class="source-list">${items.map(item => `<div class="source-item"><b>${escapeHtml(sourceLabel(item.path))}</b><span>${escapeHtml(stateLabel(item.status))} · ${escapeHtml(compactTime(item.timestamp))}</span></div>`).join("")}</div>`;
}

function setText(id, value) {
  const target = document.getElementById(id);
  if (target) target.textContent = value;
}

function renderHome(data) {
  const quality = data.data_quality_gate || {};
  const environment = data.market_environment || {};
  const radar = radarByCurrentTime(data).current;
  const opportunities = radar.filter(item => item.kind !== "risk").length;
  const risks = radar.filter(item => item.kind === "risk").length;
  setText("home-quality-state", stateLabel(quality.state));
  setText("home-quality-copy", quality.headline || "数据质量状态等待生成");
  setText("home-market-action", environment.action || "等待确认");
  setText("home-market-copy", environment.headline || "市场环境等待生成");
  setText("home-opportunity-count", opportunities);
  setText("home-risk-count", risks);
  setText("home-validation-count", list(data.validation_queue).length);
  setText("home-stock-count", data.stock_pool?.stock_count ?? 0);
  setText("home-role-gap", data.stock_pool?.role_unclassified_count ?? 0);
  setText("home-snapshot-count", data.signal_review?.snapshot_count ?? 0);
  setText("home-parallel-state", data.parallel_comparison?.cutover?.ready ? "达到切换条件" : "继续双轨观察");
  setText("home-evidence-time", compactTime(data.system?.decision_as_of));
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

function radarByCurrentTime(data) {
  const now = Date.now();
  const current = [];
  const history = [...list(data.opportunity_history)];
  for (const card of list(data.opportunity_radar)) {
    const until = card.valid_until ? new Date(card.valid_until).getTime() : NaN;
    if (!Number.isFinite(until) || until < now) history.push({ ...card, state: "expired" });
    else current.push(card);
  }
  const seen = new Set();
  return {
    current,
    history: history.filter(card => {
      const key = card.id || `${card.title}-${card.triggered_at || card.valid_until || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
  };
}

function renderAll(data, refreshReason = "自动更新") {
  v2State = data;
  const system = data.system || {};
  const radar = radarByCurrentTime(data);
  setText("v2-mode", system.operation_strategy === "parallel_shadow" ? "双轨观察" : (system.mode === "shadow_only" ? "影子模式" : stateLabel(system.mode)));
  setText("v2-updated", `证据 ${compactTime(system.decision_as_of)}`);
  setText("v2-refresh-status", `更新于 ${compactTimeWithSeconds(new Date().toISOString())} · ${refreshReason}`);
  const qualityState = data.data_quality_gate?.state || "blocked";
  const status = document.getElementById("v2-status");
  if (status) {
    status.textContent = stateLabel(qualityState);
    status.className = `pill ${qualityState}`;
  }
  renderHome(data);
  renderQuality(data.data_quality_gate || {});
  renderEnvironment(data.market_environment || {});
  renderRadar(radar.current);
  renderRadarHistory(radar.history);
  renderStyle(data.style_map || {});
  renderValidation(list(data.validation_queue));
  renderPortfolio(data.portfolio_risk || {});
  renderResearchLibrary(data.research_library || {});
  renderStockPool(data.stock_pool || {});
  renderReview(data.signal_review || {}, data.model_evaluation || {});
  renderParallelComparison(data.parallel_comparison || {});
  renderGovernance(data.governance || {}, data.input_status || {});
  renderSources(list(data.source_registry));
  renderCockpitUserContext();
  if (v22DecisionCandidate) renderDecisionCandidateV22(v22DecisionCandidate);
}

function renderDecisionCandidateV22(data) {
  v22DecisionCandidate = data;
  const summary = data?.summary || {};
  setText("home-v22-candidate-state", data?.availability === "可用" ? "案例影子可用" : "暂不可用");
  setText("home-v22-candidate-copy", `决策就绪 ${summary.decision_ready ?? 0} · 等待确认 ${summary.awaiting_confirmation ?? 0} · 未成卡线索 ${summary.unformed_clues ?? 0}`);
  setText("v22-case-projection-note", `V2.2影子案例：合并重复触发 ${summary.deduplicated_occurrences ?? 0} 个；${summary.unformed_clues ?? 0} 条证据不足线索不显示为交易卡。`);
  if (document.getElementById("opportunity-risk-radar")) {
    renderRadar(list(data?.current_cases));
    renderValidation(list(data?.validation_cases));
    renderRadarHistory(list(data?.history_cases));
  }
  if (document.getElementById("research-themes") && v2State?.research_library) renderResearchLibrary(v2State.research_library);
}

async function loadDecisionCandidateV22() {
  if (!document.getElementById("opportunity-risk-radar") && !document.getElementById("home-v22-candidate-state") && !document.getElementById("research-themes")) return;
  try {
    const response = await fetch(`${V22_DECISION_CANDIDATE_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("候选案例暂不可用");
    renderDecisionCandidateV22(await response.json());
  } catch (_error) {
    setText("home-v22-candidate-state", "暂未更新");
    setText("home-v22-candidate-copy", "现有V2基线继续可用。");
    setText("v22-case-projection-note", "V2.2案例暂未更新，现有V2基线继续可用。");
  }
}

function renderV22Learning(replay, evaluation, comparison) {
  const target = document.getElementById("v22-learning-summary");
  if (!target) return;
  const baseline = comparison?.v2_baseline || {};
  const candidate = comparison?.v22_candidate || {};
  target.innerHTML = `<div class="v22-learning-grid"><article><span>触发行情快照</span><strong>${escapeHtml(replay?.trigger_quote_snapshot_count ?? 0)} 个</strong><p>另保留 ${escapeHtml(replay?.decision_case_snapshot_count ?? replay?.snapshot_count ?? 0)} 批原始判断；只有同交易日、近触发时点行情完整时才新增。</p></article><article><span>离线评价</span><strong>${escapeHtml(evaluation?.record_count ?? 0)} 例</strong><p>${escapeHtml(evaluation?.recommendation?.reason || "等待结果。")}</p></article><article><span>观察卡降噪</span><strong>${escapeHtml(baseline.validation_count ?? 0)} → ${escapeHtml(candidate.validation_count ?? 0)}</strong><p>另有 ${escapeHtml(candidate.unformed_clue_count ?? 0)} 条证据不足线索不显示为交易卡。</p></article></div><div class="v22-learning-hold"><strong>继续双轨，不切换生产</strong><p>${escapeHtml(comparison?.cutover?.reason || "仍需积累结果并由用户确认。")}</p></div>`;
}

async function loadV22Learning() {
  const target = document.getElementById("v22-learning-summary");
  if (!target) return;
  try {
    const [replayResponse, evaluationResponse, parallelResponse] = await Promise.all([
      fetch(`${V22_REPLAY_URL}?v=${Date.now()}`, { cache: "no-store" }),
      fetch(`${V22_EVALUATION_URL}?v=${Date.now()}`, { cache: "no-store" }),
      fetch(`${V22_PARALLEL_URL}?v=${Date.now()}`, { cache: "no-store" })
    ]);
    if (!replayResponse.ok || !evaluationResponse.ok || !parallelResponse.ok) throw new Error("回溯结果暂不可用");
    renderV22Learning(await replayResponse.json(), await evaluationResponse.json(), await parallelResponse.json());
  } catch (_error) {
    target.innerHTML = '<div class="empty-state">V2.2回溯结果暂未更新；现有V2复盘保持可用。</div>';
  }
}

async function loadV2(refreshReason = "自动更新") {
  if (v2LoadInFlight) return;
  v2LoadInFlight = true;
  try {
    const response = await fetch(`${V2_DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderAll(await response.json(), refreshReason);
  } catch (_error) {
    const radar = document.getElementById("opportunity-risk-radar") || document.getElementById("page-load-error");
    if (radar && !v2State) radar.innerHTML = '<div class="empty-state error-state">数据暂时没有更新成功，请稍后重试。</div>';
    setText("v2-refresh-status", `更新失败 · ${refreshReason} · 当前信息可能已过时`);
    const status = document.getElementById("v2-status");
    if (status) {
      status.textContent = "加载失败";
      status.className = "pill blocked";
    }
  } finally {
    v2LoadInFlight = false;
  }
}

function startRadarAutoRefresh() {
  if (!document.getElementById("opportunity-risk-radar") || radarRefreshTimer) return;
  radarRefreshTimer = setInterval(() => {
    if (document.visibilityState === "visible") loadV2("30秒自动更新");
  }, 30000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadV2("返回页面更新");
  });
  if (typeof window.addEventListener === "function") {
    window.addEventListener("focus", () => loadV2("重新聚焦更新"));
    window.addEventListener("pagehide", () => {
      if (radarRefreshTimer) clearInterval(radarRefreshTimer);
      radarRefreshTimer = null;
    });
  }
}

window.V2App = { loadV2, renderAll, setFilter, renderStockPool, renderWatchlistSyncShadow, renderStockPoolLayers, renderCockpitUserContext, renderEnvironmentV22, renderEnvironmentDecisionV22, renderEnvironmentGate, renderDecisionCandidateV22, escapeHtml };
prepareShareMode();
bindFilters();
bindStockSearch();
bindBloggerManager();
bindPortfolioManager();
if (document.getElementById("blogger-source-list")) loadBloggerSources();
if (document.getElementById("portfolio-holding-list")) loadPrivatePortfolio();
if (document.getElementById("watchlist-sync-shadow-content")) loadWatchlistSyncShadow();
loadStockPoolLayers();
loadMarketEnvironmentV22();
loadEnvironmentDecisionV22();
loadDecisionCandidateV22();
loadV22Learning();
startRadarAutoRefresh();
loadV2("首次加载");

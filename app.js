const FILES = [
  "data/alert.json",
  "data/intraday.json",
  "data/premarket.json",
  "data/midday.json",
  "data/postmarket.json",
  "data/evening-sentiment.json",
  "data/topics.json",
  "data/signal-review.json",
  "config/watchlist.json",
  "config/alert-config.json",
  "data/requirements.json",
  "data/source-health.json"
];

let cache = {};

// Debug: show errors on page
window.onerror = function(msg, url, line) {
  const status = document.getElementById('status');
  if (status) status.textContent = '🔴 JS ERROR: ' + msg + ' line ' + line;
};

init();
setInterval(updateAll, 30000);
setInterval(updateTime, 1000);

function init() { updateAll(); }

/* =========================
   主更新
========================= */
async function updateAll() {
  for (const file of FILES) {
    try {
      const res = await fetch(file + "?t=" + Date.now());
      const data = await res.json();
      const dataKey = JSON.stringify(data);
      if (!cache[file] || cache[file]._cacheKey !== dataKey) {
        Object.defineProperty(data, "_cacheKey", { value: dataKey, enumerable: false });
        cache[file] = data;
        render(file, data);
      }
    } catch (e) {
      if (file.includes("signal-review")) {
        cache[file] = null;
        renderSignalReview(null);
      } else {
        console.error("load failed:", file);
      }
    }
  }
  renderGlobalDecisionModules();
  document.getElementById("lastUpdate").innerText = new Date().toLocaleTimeString();
}

/* =========================
   渲染路由
========================= */
function render(file, data) {
  if (file === "data/alert.json") renderAlerts(data);
  else if (file === "data/intraday.json") renderIntraday(data);
  else if (file === "data/premarket.json") renderPremarket(data);
  else if (file === "data/midday.json") renderMidday(data);
  else if (file === "data/postmarket.json") renderPostmarket(data);
  else if (file === "data/evening-sentiment.json") renderEvening(data);
  else if (file === "data/topics.json") renderTopics(data);
  else if (file === "data/signal-review.json") renderSignalReview(data);
  else if (file === "config/watchlist.json") renderWatchlistDecision();
  else if (file === "config/alert-config.json") renderPortfolioRisk();
  else if (file === "data/requirements.json") renderRequirements(data);
  else if (file === "data/source-health.json") renderSourceHealth(data);
}

function formatUpdateTime(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return String(timestamp);
  return date.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).replace(/\//g, "-");
}

function updatePanelMeta(targetId, timestamp) {
  const target = document.getElementById(targetId);
  const panel = target?.closest(".panel");
  if (!panel) return;
  let meta = panel.querySelector(".update-meta");
  if (!meta) {
    meta = document.createElement("div");
    meta.className = "update-meta";
    const heading = panel.querySelector("h2");
    heading?.insertAdjacentElement("afterend", meta);
  }
  const text = formatUpdateTime(timestamp);
  meta.innerHTML = text ? `<span class="updated-dot"></span>已更新 · ${text}` : "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function cached(path) {
  return cache[path] || null;
}

function renderGlobalDecisionModules() {
  renderDashboardControl();
  renderDataQualityGate();
  renderOpportunityRiskRadar();
  renderWatchlistDecision();
  renderPortfolioRisk();
}

function renderDashboardControl() {
  const el = document.getElementById("dashboard-control");
  if (!el) return;
  const intraday = cached("data/intraday.json") || {};
  const postmarket = cached("data/postmarket.json") || {};
  const evening = currentDayData(cached("data/evening-sentiment.json"));
  const alert = cached("data/alert.json") || {};
  const riskConfig = cached("config/alert-config.json") || {};
  const themes = getIntradayThemes(intraday);
  const strong = themes.filter(isPriorityTheme);
  const risks = themes.filter(t => isAvoidTheme(t) && !strong.some(s => trendName(s) === trendName(t)));
  const p0 = evening.p0_alerts || [];
  const alertStocks = (alert.alerts || []).flatMap(a => (a.leaders || []).map(l => l.name)).filter(Boolean);
  const attackCandidate = buildPersonalWatchTargets(strong[0], alertStocks);
  const attackWatch = uniqueList([
    ...attackCandidate.stocks,
    ...(attackCandidate.source === "个人池" ? alertStocks : [])
  ]).slice(0, 5);
  const riskCandidate = buildPersonalWatchTargets(risks[0], []);
  const riskWatch = uniqueList(riskCandidate.stocks).filter(s => !attackWatch.includes(s)).slice(0, 5);
  const eventWatch = uniqueList(p0.map(p => p.title || p.text || p.event)).slice(0, 5);
  const style = inferMarketStyle(intraday, postmarket, evening);
  const position = inferPositionRange(style, riskConfig);
  const latest = latestTimestamp([intraday, postmarket, alert]);
  const priority = strong.slice(0, 3).map(themeDisplayName);
  const avoid = risks.slice(0, 3).map(themeDisplayName);
  const relatedTags = positiveRelatedTopicTags(priority.join(" "), avoid.join(" "), alertStocks.join(" "), p0.map(p => p.title || p.text || "").join(" "));

  el.innerHTML = `<div class="control-hero ${style.cls}">
    <div>
      <div class="control-eyebrow">核心结论</div>
      <div class="control-title">${escapeHtml(style.title)}</div>
      <div class="control-sub">${escapeHtml(style.reason)}</div>
      <div class="control-meta">有效时间：${escapeHtml(latest ? formatUpdateTime(latest) : "待更新")} · ${escapeHtml(dataFreshness(latest))}</div>
    </div>
    <div class="control-position">
      <span>建议仓位</span>
      <b>${escapeHtml(position.range)}</b>
      <em>${escapeHtml(position.note)}</em>
    </div>
  </div>
  <div class="decision-strip control-strip">
    <div class="decision-card primary"><span class="decision-label">优先方向</span><b>${escapeHtml(priority[0] || "等待确认")}</b><span>${escapeHtml(priority.slice(1).join(" / ") || "没有共振前不抢")}</span></div>
    <div class="decision-card action"><span class="decision-label">关联题材</span><b>${escapeHtml(relatedTags[0] || "等待映射")}</b><span>${escapeHtml(relatedTags.slice(1).join(" / ") || "按母题材合并观察")}</span></div>
    <div class="decision-card primary"><span class="decision-label">进攻盯 · ${escapeHtml(attackCandidate.source)}</span><b>${escapeHtml(attackWatch[0] || "暂无")}</b><span>${escapeHtml(attackWatch.slice(1).join(" / ") || attackCandidate.note)}</span></div>
    <div class="decision-card risk"><span class="decision-label">风险盯 · ${escapeHtml(riskCandidate.source)}</span><b>${escapeHtml(riskWatch[0] || "暂无")}</b><span>${escapeHtml(riskWatch.slice(1).join(" / ") || riskCandidate.note)}</span></div>
    <div class="decision-card risk"><span class="decision-label">回避/降级</span><b>${escapeHtml(avoid[0] || "暂无明确")}</b><span>${escapeHtml(avoid.slice(1).join(" / ") || eventWatch[0] || "看弱线和P0是否扩散")}</span></div>
  </div>`;
}

function inferMarketStyle(intraday, postmarket, evening) {
  const text = [
    intraday.sentiment?.judgement,
    ...(getIntradayThemes(intraday).map(t => [trendStatus(t), t.risk, t.continuity].join(" "))),
    postmarket.review?.summary,
    postmarket.closing_auction_patch?.impact,
    ...(evening.p0_alerts || []).map(p => [p.title, p.why_p0].join(" "))
  ].filter(Boolean).join(" ");
  if (/风险|弱|退潮|压制|不支持|负反馈|下线|减持|分歧/.test(text)) {
    return { title: "分化偏防御", cls: "warn", reason: "风险词和尾盘/舆情压力占优，优先控制回撤。" };
  }
  if (/强主线|进攻|扩散|共振|修复/.test(text)) {
    return { title: "进攻观察", cls: "good", reason: "主线仍有扩散迹象，但需继续看前排承接。" };
  }
  return { title: "等待确认", cls: "neutral", reason: "缺少足够强的方向证据，降低操作频率。" };
}

function inferPositionRange(style, cfg) {
  const risk = cfg.july_portfolio_risk || {};
  const alphaLimit = risk.position_limits?.["Alpha总仓位上限"] || "22%";
  if (style.cls === "warn") return { range: "20%-40%", note: `去Alpha，Alpha上限参考${alphaLimit}` };
  if (style.cls === "good") return { range: "50%-70%", note: `保留弹性，但Alpha不超过${alphaLimit}` };
  return { range: "30%-50%", note: "只保留龙头/中军观察仓" };
}

function latestTimestamp(items) {
  return items.map(d => d?.timestamp).filter(Boolean).sort((a, b) => Date.parse(b) - Date.parse(a))[0] || "";
}

function currentDayData(data) {
  return signalDate(data?.timestamp) === currentSignalDate() ? data : {};
}

function dataFreshness(timestamp) {
  if (!timestamp) return "暂无有效数据";
  const ms = Date.now() - Date.parse(timestamp);
  if (Number.isNaN(ms)) return "时间格式待确认";
  if (ms < 10 * 60 * 1000) return "实时有效";
  if (ms < 90 * 60 * 1000) return "盘中可用";
  return "注意是否为上一阶段数据";
}

function renderDataQualityGate() {
  const el = document.getElementById("data-quality-gate");
  if (!el) return;
  const report = buildDataQualityReport();
  const cards = [
    {
      label: "数据可信度",
      title: report.level,
      detail: report.summary,
      cls: report.cls
    },
    {
      label: "最新有效",
      title: formatUpdateTime(report.latest) || "待更新",
      detail: dataFreshness(report.latest),
      cls: "neutral"
    },
    {
      label: "降级源",
      title: report.degraded.length ? `${report.degraded.length} 条` : "无",
      detail: report.degraded.slice(0, 2).join(" / ") || "核心行情源正常",
      cls: report.degraded.length ? "warn" : "good"
    }
  ];
  el.innerHTML = `<div class="decision-strip quality-strip">${cards.map(card => `
    <div class="decision-card ${card.cls}">
      <span class="decision-label">${escapeHtml(card.label)}</span>
      <b>${escapeHtml(card.title)}</b>
      <span>${escapeHtml(card.detail)}</span>
    </div>`).join("")}</div>
    ${report.issues.length ? `<div class="quality-issues">${report.issues.slice(0, 4).map(item => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}`;
}

function buildDataQualityReport() {
  const files = [
    ["盘中", cached("data/intraday.json")],
    ["盘前", cached("data/premarket.json")],
    ["午盘", cached("data/midday.json")],
    ["盘后", cached("data/postmarket.json")],
    ["专题", cached("data/topics.json")],
    ["异动", cached("data/alert.json")]
  ];
  const sourceHealth = cached("data/source-health.json") || {};
  const issues = [];
  const currentDate = currentSignalDate();
  files.forEach(([label, data]) => {
    if (!data) {
      issues.push(`${label}未接入`);
      return;
    }
    const ts = data.timestamp || "";
    if (!ts) issues.push(`${label}无时间戳`);
    else if (signalDate(ts) !== currentDate) issues.push(`${label}非当日数据`);
    const text = JSON.stringify(data);
    if (/\[object Object\]|undefined|None%|NaN|Infinity/.test(text)) issues.push(`${label}含异常文本`);
    if (data.source_status === "invalidated") issues.push(`${label}已撤下污染批次`);
  });
  const degraded = Object.entries(sourceHealth.sources || {})
    .filter(([, src]) => src?.status === "degraded" || src?.status === "bad")
    .map(([name, src]) => src.usage || src.detail || src.note || name);
  if (sourceHealth.overall_status === "degraded" || sourceHealth.status === "degraded") {
    issues.push("数据源整体降级");
  }
  const latest = latestTimestamp(files.map(([, data]) => data).filter(Boolean));
  const critical = issues.filter(item => /异常文本|未接入/.test(item)).length;
  const stale = issues.filter(item => /非当日|无时间戳/.test(item)).length;
  if (critical) return { level: "谨慎使用", cls: "warn", latest, degraded, issues, summary: "存在污染/异常字段，信号需二次确认" };
  if (stale || degraded.length) return { level: "降级可用", cls: "neutral", latest, degraded, issues, summary: "核心数据可用，但部分来源需降权" };
  return { level: "可用", cls: "good", latest, degraded, issues, summary: "核心数据结构正常" };
}

function renderOpportunityRiskRadar() {
  const el = document.getElementById("opportunity-risk-radar");
  if (!el) return;
  const radar = buildOpportunityRiskRadar();
  el.innerHTML = `<div class="radar-grid">
    <div class="radar-column">
      <div class="radar-head"><b>机会候选</b><span>${radar.opportunities.length ? "需要验证，不直接追高" : "暂无高置信机会"}</span></div>
      ${radar.opportunities.length ? radar.opportunities.map(renderRadarItem).join("") : '<div class="empty-sm">等待主线扩散或观察池个股确认</div>'}
    </div>
    <div class="radar-column">
      <div class="radar-head"><b>风险提示</b><span>${radar.risks.length ? "优先控制回撤" : "暂无新增风险"}</span></div>
      ${radar.risks.length ? radar.risks.map(renderRadarItem).join("") : '<div class="empty-sm">等待跌停/尾盘/舆情信号</div>'}
    </div>
    <div class="radar-column">
      <div class="radar-head"><b>下一步验证</b><span>盘中只看可证伪信号</span></div>
      ${radar.verifications.length ? radar.verifications.map(renderRadarItem).join("") : '<div class="empty-sm">暂无验证条件</div>'}
    </div>
  </div>`;
}

function renderRadarItem(item) {
  const tone = item.tone || "neutral";
  const tags = (item.tags || []).slice(0, 4).map(tag => `<span>${escapeHtml(tag)}</span>`).join("");
  return `<div class="radar-item ${tone}">
    <div class="radar-item-head">
      <b>${escapeHtml(item.title)}</b>
      <em>${escapeHtml(item.confidence || "观察")}</em>
    </div>
    <div class="radar-reason">${escapeHtml(item.reason)}</div>
    ${tags ? `<div class="topic-related">${tags}</div>` : ""}
  </div>`;
}

function buildOpportunityRiskRadar() {
  const intraday = cached("data/intraday.json") || {};
  const postmarket = cached("data/postmarket.json") || {};
  const midday = cached("data/midday.json") || {};
  const topics = cached("data/topics.json") || {};
  const watchlistSignals = buildWatchlistSignalRows();
  const themes = [
    ...getIntradayThemes(intraday),
    ...(Array.isArray(postmarket.hotspots) ? postmarket.hotspots : []),
    ...(Array.isArray(topics.topics) ? topics.topics : [])
  ].filter(Boolean);
  const strongThemes = dedupeRadarItems(themes
    .filter(isPriorityTheme)
    .map(theme => ({
      title: themeDisplayName(theme),
      reason: radarThemeReason(theme),
      confidence: radarConfidence(theme, "opportunity"),
      tone: "good",
      tags: themeSubDirections(theme)
    })));
  const riskThemes = dedupeRadarItems(themes
    .filter(isAvoidTheme)
    .map(theme => ({
      title: themeDisplayName(theme),
      reason: radarThemeRisk(theme),
      confidence: radarConfidence(theme, "risk"),
      tone: "risk",
      tags: themeSubDirections(theme)
    })));
  const strongStocks = watchlistSignals
    .filter(item => item.signal.tone === "strong")
    .slice(0, 4)
    .map(item => ({
      title: displayStockName(item.name),
      reason: `${item.signal.reason}；${item.signal.badge || "强势待验证"}`,
      confidence: "观察池强信号",
      tone: "good",
      tags: [stockProfileLabel(item)].filter(Boolean)
    }));
  const weakStocks = watchlistSignals
    .filter(item => item.signal.tone === "weak")
    .slice(0, 4)
    .map(item => ({
      title: displayStockName(item.name),
      reason: `${item.signal.reason}；${item.signal.badge || "风险待验证"}`,
      confidence: "观察池风险",
      tone: "risk",
      tags: [stockProfileLabel(item)].filter(Boolean)
    }));
  const breadthRisk = marketBreadthRisk(intraday, postmarket);
  const verifications = [
    ...verificationItems(intraday, midday, postmarket),
    ...strongThemes.slice(0, 2).map(item => ({
      title: `${item.title}能否升级`,
      reason: "看核心个股是否同步强于ETF、后排是否扩散、尾盘是否承接。",
      confidence: "盘中验证",
      tone: "neutral",
      tags: item.tags
    }))
  ];
  return {
    opportunities: [...strongStocks, ...strongThemes].slice(0, 6),
    risks: [...(breadthRisk ? [breadthRisk] : []), ...weakStocks, ...riskThemes].slice(0, 7),
    verifications: dedupeRadarItems(verifications).slice(0, 6)
  };
}

function buildWatchlistSignalRows() {
  const wl = cached("config/watchlist.json") || {};
  const signals = collectSignalText();
  return (wl.watch_only?.stocks || [])
    .map(stock => ({ ...stock, signal: stockSignal(stock, signals, "watch_only") }))
    .sort((a, b) => (b.signal.score || 0) - (a.signal.score || 0));
}

function radarThemeReason(theme) {
  const parts = [
    trendStatus(theme),
    theme.continuity,
    theme.reason,
    ...(Array.isArray(theme.evidence) ? theme.evidence : []),
    theme.note
  ].filter(Boolean);
  return truncateText(parts.join("；") || "主线强度有待盘中继续确认", 108);
}

function radarThemeRisk(theme) {
  const parts = [
    trendStatus(theme),
    theme.risk,
    theme.continuity,
    theme.note,
    ...(Array.isArray(theme.evidence) ? theme.evidence : [])
  ].filter(Boolean);
  return truncateText(parts.join("；") || "风险线需观察是否扩散", 108);
}

function radarConfidence(theme, mode) {
  const text = JSON.stringify(theme);
  if (/涨停|封板|证据|evidence|尾盘|成交|放量/.test(text)) return mode === "risk" ? "证据风险" : "证据支持";
  if (/观察|待验证|分化/.test(text)) return "待验证";
  return "模型推断";
}

function marketBreadthRisk(intraday, postmarket) {
  const s = intraday.sentiment || {};
  const idx = postmarket.index || {};
  const down5 = Number(idx["跌幅5%以上"] || postmarket.market_breadth?.down5_count || 0);
  const limitDown = Number(s.limit_down_count || idx["跌停"] || 0);
  const broken = Number(s.broken_limit_count || idx["炸板"] || 0);
  if (down5 >= 500 || limitDown >= 20 || broken >= 25) {
    return {
      title: "全市场亏钱效应",
      reason: `跌5%以上${down5 || "-"}只，跌停${limitDown || "-"}只，炸板${broken || "-"}只；强线不能外推成全面进攻。`,
      confidence: "高优先级风险",
      tone: "risk",
      tags: ["仓位", "回撤"]
    };
  }
  return null;
}

function verificationItems(intraday, midday, postmarket) {
  return uniqueList([
    ...arrayTextItems(intraday.actions),
    ...arrayTextItems(midday.afternoon_watch),
    ...arrayTextItems(postmarket.next_day_watch),
    ...arrayTextItems(postmarket.closing_auction_patch?.watch_next_day)
  ]).slice(0, 5).map(text => ({
    title: "验证条件",
    reason: truncateText(text, 108),
    confidence: "可证伪",
    tone: /风险|跌停|弱|回落|低开/.test(text) ? "risk" : "neutral",
    tags: positiveRelatedTopicTags(text)
  }));
}

function dedupeRadarItems(items) {
  const seen = new Set();
  return (items || []).filter(item => {
    const key = item.title;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function uniqueList(items) {
  return Array.from(new Set((items || []).filter(Boolean).map(v => String(v).trim()).filter(Boolean)));
}

function relatedTopicTags(...parts) {
  const text = parts.flat().filter(Boolean).join(" ");
  const groups = [
    { name: "科技硬件链", re: /半导体|设备|材料|CPO|光模块|存储|HBM|PCB|电子布|封装|硅片|算力|芯片|北方|中微|华海|安集|雅克|澜起|兆易|中际|新易盛|沪电|胜宏/ },
    { name: "机器人/工业自动化", re: /机器人|工业自动化|通用设备|自动化设备|减速器|伺服|控制器|机器视觉|步科|绿的|埃斯顿|中大力德|双环|拓斯达|汇川|奥普特/ },
    { name: "医药修复链", re: /医药|化学制药|创新药|原料药|制剂|CRO|恒瑞|科伦|普洛|九典|金城|赛托|共同药业|广生堂|艾力斯|百济|诺诚|荣昌/ },
    { name: "老登风格切换", re: /券商|证券|保险|白酒|酒|畜牧|银行|地产|中字头|权重|中信证券|国泰海通|东方财富|平安|茅台|五粮液|牧原|温氏/ },
    { name: "回避/降级集合", re: /风险|回避|降级|光伏|逆变器|功率半导体|SiC|第三代半导体|新能源出海|AIDC电源|暴跌|减持|监管|澄清/ }
  ];
  const matched = groups.filter(g => g.re.test(text)).map(g => g.name);
  return uniqueList(matched).slice(0, 5);
}

function positiveRelatedTopicTags(...parts) {
  return relatedTopicTags(...parts).filter(tag => tag !== "回避/降级集合");
}

function extractStocks(item) {
  if (!item || typeof item === "string") return [];
  return (item.stocks || item.leaders || item.representatives || [])
    .map(s => typeof s === "string" ? s : s.name || s.symbol)
    .filter(Boolean);
}

function allWatchlistStocks() {
  const wl = cached("config/watchlist.json") || {};
  return ["small_deng", "old_deng", "watch_only"].flatMap(key =>
    (wl[key]?.stocks || []).map(stock => ({ ...stock, pool: key }))
  );
}

function buildPersonalWatchTargets(theme, alertStocks = []) {
  if (!theme) return { stocks: [], source: "待确认", note: "等待强主线出现" };
  const themeName = trendName(theme);
  const themeStocks = extractStocks(theme);
  const keywords = uniqueList([
    themeName,
    ...themeName.split(/[\\/、,，\s-]+/),
    ...themeStocks
  ]).filter(k => k.length >= 2);
  const poolHits = allWatchlistStocks().filter(stock => {
    const tags = stock.tags || [];
    const hay = [stock.name, stock.code, stock.source, ...tags].filter(Boolean).join(" ");
    return keywords.some(k => hay.includes(k)) || themeStocks.includes(stock.name);
  });
  const personal = uniqueList(poolHits.map(s => s.name)).slice(0, 5);
  if (personal.length) {
    return { stocks: personal, source: "个人池", note: `匹配${themeName}` };
  }
  const market = uniqueList([...themeStocks, ...alertStocks]).slice(0, 5);
  return { stocks: market, source: "市场样本", note: "未命中个人池，只作强线样本观察" };
}

function isPriorityTheme(item) {
  const status = trendStatus(item);
  return /强|强化|主线|资金/.test(status) && !/风险|弱|退潮|回避|降级/.test(status);
}

function isAvoidTheme(item) {
  const status = trendStatus(item);
  const fullText = [status, item?.risk, item?.continuity, item?.note].join(" ");
  if (/风险|弱|退潮|回避|降级/.test(status)) return true;
  return !isPriorityTheme(item) && /风险|弱|退潮|回落|分歧|压制|补跌/.test(fullText);
}

function renderWatchlistDecision() {
  const el = document.getElementById("watchlist-decision");
  if (!el) return;
  const wl = cached("config/watchlist.json");
  if (!wl) {
    el.innerHTML = '<div class="empty">观察池配置待接入</div>';
    return;
  }
  const signals = collectSignalText();
  const pools = [
    ["watch_only", "观察池", "个人跟踪"]
  ];
  el.innerHTML = `<div class="watchlist-grid">${pools.map(([key, title, desc]) => renderWatchPool(key, title, desc, wl[key]?.stocks || [], signals)).join("")}</div>`;
}

function renderWatchPool(key, title, desc, stocks, signals) {
  const hits = stocks
    .map(s => ({ ...s, signal: stockSignal(s, signals, key) }))
    .sort((a, b) => (b.signal.score || 0) - (a.signal.score || 0));
  const displayLimit = key === "watch_only" ? Number.POSITIVE_INFINITY : 5;
  const strong = hits.filter(s => s.signal.tone === "strong").slice(0, displayLimit);
  const weak = hits.filter(s => s.signal.tone === "weak").slice(0, displayLimit);
  const neutral = hits.filter(s => s.signal.tone === "neutral").slice(0, displayLimit);
  const lines = [
    ["强势股", strong],
    ["弱势股", weak],
    ["一般股", neutral]
  ];
  return `<div class="watch-pool-card ${weak.length > strong.length ? "risk" : strong.length ? "hot" : ""}">
    <div class="watch-pool-head"><b>${escapeHtml(title)}</b><span>${stocks.length} 只 · ${escapeHtml(desc)}</span></div>
    ${lines.map(([label, rows]) => renderWatchLine(label, rows)).join("")}
  </div>`;
}

function renderWatchLine(label, rows) {
  if (!rows.length) return `<div class="watch-line"><span>${label}</span><b>暂无</b></div>`;
  return `<div class="watch-line"><span>${label}</span><b>${renderGroupedWatchStocks(rows)}</b></div>`;
}

function renderGroupedWatchStocks(rows) {
  const groups = new Map();
  rows.forEach(stock => {
    const label = stockProfileLabel(stock) || "待确认方向";
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(stock);
  });
  return Array.from(groups.entries()).map(([label, stocks]) =>
    `<span class="watch-reason-group"><em>${escapeHtml(label)}</em>${stocks.map(renderWatchStockName).join(" / ")}</span>`
  ).join("");
}

function renderWatchStock(stock) {
  const name = escapeHtml(stock.name || stock.code);
  const reason = stock.signal?.reason ? `<em>${escapeHtml(stock.signal.reason)}</em>` : "";
  return `<span class="watch-stock">${name}${reason}</span>`;
}

function renderWatchStockName(stock) {
  const label = watchSignalBadge(stock.signal);
  const tone = stock.signal?.tone || "neutral";
  return `<span class="watch-stock-name">${escapeHtml(displayStockName(stock.name || stock.code))}${label ? `<small class="watch-signal-${tone}">${escapeHtml(label)}</small>` : ""}</span>`;
}

function watchSignalBadge(signal) {
  const base = {
    strong: "强势",
    weak: "弱势",
    neutral: "一般"
  }[signal?.tone] || "";
  return signal?.badge ? `${base} · ${signal.badge}` : base;
}

function stockSignal(stock, signals, pool) {
  const name = stock.name || "";
  const tags = signalTags([...(stock.tags || []), ...inferredStockTags(stock)]);
  const currentDate = currentSignalDate();
  const todaySignals = filterSignalsByDate(signals, currentDate)
    .filter(signal => !(hasCurrentPostmarket() && signal.source === "alert"));
  const context = stockContextText(name, todaySignals, { includeCurrentData: true });
  const contextAll = stockContextText(name, signals, { includeCurrentData: false });
  const latestChangePct = latestStockChangePct(name);
  const changePct = Number.isFinite(latestChangePct) ? latestChangePct : stockChangePct(name, context);
  const volumeBadge = stockVolumeBadge(context);
  const hardEventRiskPattern = /减持|监管|问询|立案|处罚|澄清|业绩雷/;
  const priceRiskPattern = /跌停|接近跌停|暴跌|放量大跌|放量下跌|破位|跌破|降级|风险核心|负反馈核心/;
  const pressurePattern = /风险|弱|退潮|回落|下跌|压制|分歧|补跌/;
  const hardStrongPattern = /涨停|封板|急拉|大涨|放量上涨|放量走强|强势|领涨|突破|加速/;
  const watchPattern = /交易|强|主线|强化|修复|承接|高开|扩散/;
  const directSegments = todaySignals
    .flatMap(s => s.text.split(/[。；;，,\n]/))
    .filter(part => name && part.includes(name));
  const allDirectSegments = signals
    .flatMap(s => s.text.split(/[。；;，,\n]/))
    .filter(part => name && part.includes(name));
  const tagMatched = signals.filter(s => tags.some(t => t && s.text.includes(t)));
  const tagText = tagMatched.map(s => s.text).join(" ");
  const strongTag = matchedStrongThemeTag(tags);
  const pressureTag = matchedPressureThemeTag(tags, signals);
  const directEventRisk = allDirectSegments.some(part => hardEventRiskPattern.test(part));
  const directRisk = directSegments.some(part => priceRiskPattern.test(part) || hasLargeDrop(part, 7));
  const directPressure = directSegments.some(part => !isConditionalSignal(part) && (pressurePattern.test(part) || hasAnyDrop(part)));
  const directTrigger = directSegments.some(part => !isConditionalSignal(part) && (hardStrongPattern.test(part) || hasLargeGain(part, 5)));
  const contextStrong = namedContextHasPattern(name, context, hardStrongPattern);
  const contextRisk = namedContextHasPattern(name, context, priceRiskPattern);
  const contextPressure = namedContextHasPattern(name, context, pressurePattern);
  const positiveMove = Number.isFinite(changePct) && changePct >= 3;
  const strongMove = Number.isFinite(changePct) && changePct >= 5;
  const weakMove = Number.isFinite(changePct) && changePct <= -3;
  const hardWeakMove = Number.isFinite(changePct) && changePct <= -7;
  const currentNamedStrong = directTrigger || contextStrong;
  const currentStrong = currentNamedStrong || strongMove;
  const currentWeak = directRisk || contextRisk || hardWeakMove || (directPressure && (weakMove || !Number.isFinite(changePct))) || (contextPressure && weakMove);
  if (directEventRisk) return watchTone("weak", "事件风险", eventRiskBadge(directSegments), changePct, volumeBadge, 100);
  if (currentStrong) {
    const badge = currentNamedStrong
      ? strongSignalBadge([...strongSegments(directSegments), namedStrongContext(name, context)]) || pctBadge(changePct) || volumeBadge
      : [pctBadge(changePct), volumeBadge].filter(Boolean).join("/") || "走强";
    return watchTone("strong", currentNamedStrong ? shortReason(strongSegments([...directSegments, namedStrongContext(name, context)]), "强信号") : "当日大涨", badge, changePct, volumeBadge, 90);
  }
  if (currentWeak) return watchTone("weak", directRisk || contextRisk ? "硬风险" : pressureReason(directSegments), priceRiskBadge([...directSegments, namedRiskContext(name, context)]) || pressureBadge([...directSegments, namedRiskContext(name, context)]) || pctBadge(changePct), changePct, volumeBadge, 85);
  if (strongTag && positiveMove) return watchTone("strong", `${strongTag}强线内走强`, [pctBadge(changePct), volumeBadge].filter(Boolean).join("/") || "强线走强", changePct, volumeBadge, 72);
  if (pressureTag && weakMove) return watchTone("weak", `${pressureTag}承压`, [pctBadge(changePct), volumeBadge].filter(Boolean).join("/") || "方向承压", changePct, volumeBadge, 70);
  if (positiveMove) return watchTone("strong", directSegments.length ? shortReason(directSegments, "个股走强") : "当日走强", [pctBadge(changePct), volumeBadge].filter(Boolean).join("/") || "上涨", changePct, volumeBadge, 62);
  if (weakMove) return watchTone("weak", directSegments.length ? shortReason(directSegments, "个股转弱") : "当日转弱", [pctBadge(changePct), volumeBadge].filter(Boolean).join("/") || "下跌", changePct, volumeBadge, 62);
  if (strongTag) return watchTone("neutral", `${strongTag}主线内待确认`, "主线待确认", changePct, volumeBadge, 50);
  if (pressureTag) return watchTone("neutral", `${pressureTag}方向待确认`, "方向待确认", changePct, volumeBadge, 48);
  if (watchPattern.test(tagText) || directSegments.some(part => hasAnyGain(part))) {
    return watchTone("neutral", directSegments.length ? shortReason(directSegments, "待确认") : matchedTagReason(tags, tagText, "方向观察"), pctBadge(changePct) || volumeBadge || "待确认", changePct, volumeBadge, 40);
  }
  if (directSegments.length || tagMatched.length || contextAll) return watchTone("neutral", directSegments.length ? "个股被提及" : matchedTagReason(tags, tagText, "标签命中"), pctBadge(changePct) || "待观察", changePct, volumeBadge, 30);
  return watchTone("neutral", "暂无信号", pctBadge(changePct), changePct, volumeBadge, 0);
}

function watchTone(tone, reason, badge, changePct, volumeBadge, score) {
  const moveScore = Number.isFinite(changePct) ? Math.min(Math.abs(changePct), 20) : 0;
  return { tone, reason, badge, changePct, volumeBadge, score: score + moveScore };
}

function stockContextText(name, signals, options = {}) {
  const cleanName = displayStockName(name);
  if (!cleanName) return "";
  const corpus = [
    ...(signals || []).map(s => s.text || ""),
    ...(options.includeCurrentData ? currentDayDataTexts() : [])
  ].join("\n");
  const windows = [];
  let start = 0;
  while (windows.length < 8) {
    const idx = corpus.indexOf(cleanName, start);
    if (idx < 0) break;
    windows.push(corpus.slice(Math.max(0, idx - 180), idx + 420));
    start = idx + cleanName.length;
  }
  return windows.join("\n");
}

function currentDayDataTexts() {
  const currentDate = currentSignalDate();
  return [
    ["data/intraday.json", cached("data/intraday.json")],
    ...(hasCurrentPostmarket() ? [] : [["data/alert.json", cached("data/alert.json")]]),
    ["data/midday.json", cached("data/midday.json")],
    ["data/postmarket.json", cached("data/postmarket.json")]
  ]
    .filter(([, data]) => signalDate(data?.timestamp) === currentDate)
    .map(([, data]) => JSON.stringify(data || {}));
}

function latestStockChangePct(name) {
  const currentDate = currentSignalDate();
  const sources = [
    cached("data/postmarket.json"),
    cached("data/intraday.json"),
    cached("data/midday.json"),
    ...(hasCurrentPostmarket() ? [] : [cached("data/alert.json")])
  ];
  for (const data of sources) {
    if (signalDate(data?.timestamp) !== currentDate) continue;
    const value = stockChangePct(name, JSON.stringify(data || {}));
    if (Number.isFinite(value)) return value;
  }
  return NaN;
}

function stockChangePct(name, context) {
  const cleanName = escapeRegExp(displayStockName(name));
  const exact = String(context || "").match(new RegExp(`\\{[^{}]{0,160}"name"\\s*:\\s*"[^"]*${cleanName}[^"]*"[^{}]{0,220}"change_pct"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)`));
  if (exact) return Number(exact[1]);
  const percent = String(context || "").match(new RegExp(`${cleanName}\\s*[:：]?\\s*([+-]?\\d+(?:\\.\\d+)?)%`));
  if (percent) return Number(percent[1]);
  return NaN;
}

function stockVolumeBadge(context) {
  const text = String(context || "");
  if (/放量走强|放量上涨/.test(text)) return "放量走强";
  if (/放量大跌|放量下跌/.test(text)) return "放量走弱";
  const match = text.match(/(?:成交放大|较昨同期|3分钟放大)(?:至|约)?\s*(\d+(?:\.\d+)?)x/i);
  if (match && Number(match[1]) >= 2) return `${match[1]}x放量`;
  return "";
}

function namedContextHasPattern(name, context, pattern) {
  const cleanName = escapeRegExp(displayStockName(name));
  const text = String(context || "");
  const clauses = text.split(/[。；;\n]/).filter(part => part.includes(displayStockName(name)));
  return clauses.some(part => {
    if (isConditionalSignal(part)) return false;
    const afterName = part.match(new RegExp(`${cleanName}([^。；;\\n]{0,80})`));
    return afterName ? pattern.test(afterName[1]) : false;
  });
}

function namedStrongContext(name, context) {
  const cleanName = escapeRegExp(displayStockName(name));
  const text = String(context || "");
  const clauses = text.split(/[。；;\n]/).filter(part => part.includes(displayStockName(name)));
  return clauses.filter(part => {
    if (isConditionalSignal(part)) return false;
    const afterName = part.match(new RegExp(`${cleanName}([^。；;\\n]{0,80})`));
    return afterName ? /涨停|封板|急拉|大涨|放量上涨|放量走强|强势|领涨|突破|加速/.test(afterName[1]) : false;
  }).join(" ");
}

function namedRiskContext(name, context) {
  const cleanName = escapeRegExp(displayStockName(name));
  const text = String(context || "");
  const clauses = text.split(/[。；;\n]/).filter(part => part.includes(displayStockName(name)));
  return clauses.filter(part => {
    if (isConditionalSignal(part)) return false;
    const afterName = part.match(new RegExp(`${cleanName}([^。；;\\n]{0,80})`));
    return afterName ? /跌停|接近跌停|暴跌|放量大跌|放量下跌|破位|跌破|降级|风险核心|负反馈核心|-\d+(?:\.\d+)?%/.test(afterName[1]) : false;
  }).join(" ");
}

function pctBadge(changePct) {
  if (!Number.isFinite(changePct)) return "";
  return `${changePct > 0 ? "+" : ""}${Number(changePct).toFixed(2).replace(/\.?0+$/, "")}%`;
}

function escapeRegExp(text) {
  return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function signalTags(tags) {
  const management = /^(观察池|个人跟踪|观察仓|小登池|中登池|老登池|风格切换|科技题材|A股|同花顺自选|设置页新增|同花顺自选导入|待标注方向)$/;
  return (tags || []).filter(tag => tag && !management.test(tag));
}

function stockProfileLabel(stock) {
  const code = normalizeStockCodeForMatch(stock.code);
  const name = String(stock.name || "").replace(/^XD/, "");
  const precise = {
    sh603650: "光刻胶",
    sz301526: "电子布/玻纤",
    sz300033: "金融科技",
    sh688160: "工业自动化",
    sh688017: "机器人减速器",
    sz002747: "工业机器人",
    sz300536: "待确认方向",
    sh688777: "工业自动化",
    sz300418: "AI应用",
    sz002261: "华为算力",
    sh688111: "AI办公",
    sh688549: "半导体材料",
    sz300346: "光刻胶",
    sh603078: "湿电子化学品",
    sz002409: "半导体材料",
    sh688019: "CMP抛光液",
    sh688120: "CMP设备",
    sz002371: "半导体设备",
    sh688012: "半导体设备",
    sh688432: "硅材料",
    sh688126: "半导体硅片",
    sh688795: "国产GPU",
    sh603986: "存储/MCU",
    sh688008: "存储/HBM",
    sh588170: "半导体ETF",
    sh515230: "软件ETF",
    sh515120: "创新药ETF",
    sz159530: "机器人ETF",
    hk2513: "AI应用",
    hk9880: "人形机器人"
  };
  const byName = {
    金山办: "AI办公",
    中巨芯: "半导体材料",
    摩尔线程: "国产GPU",
    科创半导体: "半导体ETF",
    软件ETF: "软件ETF",
    创新药ETF: "创新药ETF",
    机器人ETF: "机器人ETF",
    优必选: "人形机器人",
    智谱: "AI应用"
  };
  const mapped = precise[code] || Object.entries(byName).find(([key]) => name.includes(key))?.[1];
  if (mapped) return mapped;
  const tags = signalTags([...(stock.tags || []), ...inferredStockTags(stock)]);
  return tags.find(tag => /半导体|设备|材料|光刻胶|机器人|自动化|AI|算力|软件|ETF|创新药|GPU|存储|硅|电子布|金融|医药|CPO|PCB/.test(tag)) || tags[0] || "待确认方向";
}

function displayStockName(name) {
  const text = String(name || "");
  if (text === "XD金山办") return "金山办公";
  return text.replace(/^XD/, "");
}

function inferredStockTags(stock) {
  const code = normalizeStockCodeForMatch(stock.code);
  const name = String(stock.name || "").replace(/^XD/, "");
  const map = {
    sz300536: ["待标注方向"],
    sh688777: ["工业自动化"],
    sz300418: ["AI应用"],
    sz002261: ["华为算力"],
    sh688111: ["AI办公"],
    sh688549: ["半导体材料"],
    sz300346: ["光刻胶"],
    sh603078: ["湿电子化学品"],
    sz002409: ["半导体材料"],
    sh688019: ["CMP抛光液"],
    sh688120: ["CMP设备"],
    sz002371: ["半导体设备"],
    sh688012: ["半导体设备"],
    sh688432: ["硅材料"],
    sh688126: ["硅片材料"],
    sh688795: ["国产GPU"],
    sh603986: ["存储/MCU"],
    sh688008: ["存储/HBM"],
    sh588170: ["半导体ETF"],
    sh515230: ["软件ETF"],
    sh515120: ["创新药ETF"],
    sz159530: ["机器人ETF"],
    hk2513: ["AI应用"],
    hk9880: ["机器人"]
  };
  const nameMap = {
    农尚环境: ["待标注方向"],
    中控技术: ["工业自动化"],
    昆仑万维: ["AI应用"],
    拓维信息: ["华为算力"],
    金山办公: ["AI办公"],
    中巨芯: ["半导体材料"],
    南大光电: ["光刻胶"],
    江化微: ["湿电子化学品"],
    雅克科技: ["半导体材料"],
    安集科技: ["CMP抛光液"],
    华海清科: ["CMP设备"],
    北方华创: ["半导体设备"],
    中微公司: ["半导体设备"],
    有研硅: ["硅材料"],
    沪硅产业: ["硅片材料"],
    摩尔线程: ["国产GPU"],
    兆易创新: ["存储/MCU"],
    澜起科技: ["存储/HBM"],
    智谱: ["AI应用"],
    优必选: ["机器人"]
  };
  return map[code] || Object.entries(nameMap).find(([key]) => name.includes(key))?.[1] || [];
}

function normalizeStockCodeForMatch(code) {
  const raw = String(code || "").toLowerCase();
  if (/^hk\d+/.test(raw)) return raw;
  if (/^(sh|sz|bj)\d{6}$/.test(raw)) return raw;
  const digits = raw.replace(/\D/g, "");
  if (digits.length !== 6) return raw;
  if (/^[56]/.test(digits)) return `sh${digits}`;
  if (/^[013]/.test(digits)) return `sz${digits}`;
  if (/^[489]/.test(digits)) return `bj${digits}`;
  return raw;
}

function shortReason(segments, fallback) {
  const hit = (segments || []).find(Boolean) || "";
  const cleaned = hit
    .replace(/^[a-zA-Z0-9_]+[:：]/, "")
    .replace(/[{}"\\[\\]]/g, "")
    .replace(/\s+/g, "");
  if (!cleaned) return fallback;
  return truncateText(cleaned, 16);
}

function pressureReason(segments) {
  const text = (segments || []).join(" ");
  const drop = text.match(/-\d+(?:\.\d+)?%/);
  if (drop) return `${drop[0]}承压`;
  if (/回落/.test(text)) return "回落承压";
  if (/补跌/.test(text)) return "补跌承压";
  if (/压制/.test(text)) return "受压制";
  return "个股承压";
}

function eventRiskBadge(segments) {
  const text = (segments || []).join(" ");
  const labels = [
    ["减持", /减持/],
    ["监管", /监管|问询/],
    ["立案", /立案/],
    ["处罚", /处罚/],
    ["澄清", /澄清/],
    ["业绩雷", /业绩雷/]
  ].filter(([, re]) => re.test(text)).map(([label]) => label);
  return labels.slice(0, 2).join("/");
}

function strongSignalBadge(segments) {
  const text = (segments || []).join(" ");
  const labels = [
    ["涨停", /涨停|20cm|20CM/],
    ["封板", /封板/],
    ["大涨", /大涨|\+\d+(?:\.\d+)?%/],
    ["放量走强", /放量上涨|放量走强/],
    ["急拉", /急拉|加速/],
    ["突破", /突破/],
    ["领涨", /领涨|强势/]
  ].filter(([, re]) => re.test(text)).map(([label]) => label);
  return labels.slice(0, 2).join("/");
}

function priceRiskBadge(segments) {
  const text = (segments || []).join(" ");
  const labels = [
    ["跌停", /跌停|接近跌停/],
    ["大跌", /暴跌|放量大跌|放量下跌|-\d+(?:\.\d+)?%/],
    ["破位", /破位|跌破/],
    ["降级", /降级|风险核心|负反馈核心/]
  ].filter(([, re]) => re.test(text)).map(([label]) => label);
  return labels.slice(0, 2).join("/");
}

function pressureBadge(segments) {
  const text = (segments || []).join(" ");
  const labels = [
    ["回落", /回落/],
    ["分歧", /分歧/],
    ["下跌", /下跌|-\d+(?:\.\d+)?%/],
    ["压制", /压制/],
    ["补跌", /补跌/]
  ].filter(([, re]) => re.test(text)).map(([label]) => label);
  return labels.slice(0, 2).join("/");
}

function strongSegments(segments) {
  const pattern = /涨停|封板|急拉|大涨|放量上涨|放量走强|强势|领涨|突破|加速|\+\d+(\.\d+)?%/;
  const hits = (segments || []).filter(part => pattern.test(part) && !isConditionalSignal(part));
  return hits.length ? hits : segments;
}

function matchedTagReason(tags, text, fallback) {
  const tag = (tags || []).find(t => t && text.includes(t));
  return tag ? `${tag}${fallback.replace(/^方向/, "")}` : fallback;
}

function matchedStrongThemeTag(tags) {
  const intraday = cached("data/intraday.json") || {};
  const postmarket = cached("data/postmarket.json") || {};
  const themes = [
    ...getIntradayThemes(intraday),
    ...(postmarket.hotspots || []),
    ...(postmarket.strong_themes || [])
  ];
  const strongThemes = themes.filter(isPriorityTheme);
  return (tags || []).find(tag =>
    tag && strongThemes.some(theme => JSON.stringify(theme).includes(tag))
  ) || "";
}

function matchedPressureThemeTag(tags, signals) {
  const riskPattern = /退潮|回落|补跌|弱|压制|风险/;
  const conditionalPattern = /若|如果|是否|能否|等待|观察|看|需|需要|验证|不能|未|不构成|不升级/;
  const parts = (signals || []).flatMap(s => s.text.split(/[。；;\n]/));
  return (tags || []).find(tag => tag && parts.some(part =>
    part.includes(tag) && riskPattern.test(part) && !conditionalPattern.test(part)
  )) || "";
}

function hasAnyDrop(text) {
  return /-\d+(\.\d+)?%/.test(String(text || ""));
}

function hasLargeDrop(text, threshold) {
  const matches = String(text || "").matchAll(/-(\d+(?:\.\d+)?)%/g);
  for (const match of matches) {
    if (Number(match[1]) >= threshold) return true;
  }
  return false;
}

function hasAnyGain(text) {
  return /\+\d+(\.\d+)?%/.test(String(text || ""));
}

function hasLargeGain(text, threshold) {
  const matches = String(text || "").matchAll(/\+(\d+(?:\.\d+)?)%/g);
  for (const match of matches) {
    if (Number(match[1]) >= threshold) return true;
  }
  return false;
}

function isConditionalSignal(text) {
  return /若|如果|是否|能否|等待|观察|看|需|需要|验证|不能|未|不构成|不升级/.test(String(text || ""));
}

function collectSignalText() {
  const intraday = cached("data/intraday.json") || {};
  const postmarket = cached("data/postmarket.json") || {};
  const evening = cached("data/evening-sentiment.json") || {};
  const topics = cached("data/topics.json") || {};
  const alert = cached("data/alert.json") || {};
  return [
    ...signalsFromItems(alert.alerts, alert.timestamp, "alert"),
    ...signalsFromItems(intraday.main_trends, intraday.timestamp, "intraday"),
    ...signalsFromItems(themeGroupsToItems(intraday.themes), intraday.timestamp, "intraday"),
    ...signalsFromItems(postmarket.hotspots, postmarket.timestamp, "postmarket"),
    ...signalsFromItems(evening.p0_alerts, evening.timestamp, "evening"),
    ...signalsFromItems(topics.topics, topics.timestamp, "topics")
  ];
}

function signalsFromItems(items, fallbackTimestamp, source) {
  return asArray(items).map(item => {
    const timestamp = item?.updated_at || item?.timestamp || fallbackTimestamp || "";
    return {
      text: JSON.stringify(item, null, 0),
      date: signalDate(timestamp),
      timestamp,
      source
    };
  });
}

function currentSignalDate() {
  const dates = [
    cached("data/alert.json")?.timestamp,
    cached("data/intraday.json")?.timestamp,
    cached("data/midday.json")?.timestamp,
    cached("data/topics.json")?.timestamp,
    cached("data/postmarket.json")?.timestamp
  ].map(signalDate).filter(Boolean).sort();
  return dates[dates.length - 1] || "";
}

function filterSignalsByDate(signals, date) {
  if (!date) return signals || [];
  return (signals || []).filter(signal => signal.date === date);
}

function signalDate(timestamp) {
  const text = String(timestamp || "");
  const match = text.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function hasCurrentPostmarket() {
  return signalDate(cached("data/postmarket.json")?.timestamp) === currentSignalDate();
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function themeGroupsToItems(value) {
  if (Array.isArray(value)) return value;
  if (!value || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([group, items]) =>
    (Array.isArray(items) ? items : [items]).filter(Boolean).map(item =>
      typeof item === "string" ? { name: item, status: themeGroupLabel(group) } : { group, ...item }
    )
  );
}

function themeGroupLabel(group) {
  return {
    strong: "强主线",
    watch: "观察",
    funds_game: "资金博弈",
    risk: "风险"
  }[group] || group;
}

function renderPortfolioRisk() {
  const el = document.getElementById("portfolio-risk");
  if (!el) return;
  const cfg = cached("config/alert-config.json");
  if (!cfg?.july_portfolio_risk) {
    el.innerHTML = '<div class="empty">仓位风控配置待接入</div>';
    return;
  }
  const risk = cfg.july_portfolio_risk;
  const style = inferMarketStyle(cached("data/intraday.json") || {}, cached("data/postmarket.json") || {}, currentDayData(cached("data/evening-sentiment.json")));
  const pos = inferPositionRange(style, cfg);
  const techRisk = /半导体材料|科技|AI应用|光刻胶/.test(JSON.stringify([cached("data/intraday.json"), cached("data/postmarket.json"), currentDayData(cached("data/evening-sentiment.json"))])) && style.cls === "warn";
  const alphaState = techRisk ? "暂停/去Alpha" : "允许但受限";
  const limits = risk.position_limits || {};
  const etf = risk.sector_drawdown || {};
  const stop = risk.stop_loss || {};
  el.innerHTML = `<div class="decision-strip risk-decision">
    <div class="decision-card ${style.cls}"><span class="decision-label">风险状态</span><b>${escapeHtml(style.title)}</b><span>${escapeHtml(style.reason)}</span></div>
    <div class="decision-card action"><span class="decision-label">建议总仓</span><b>${escapeHtml(pos.range)}</b><span>${escapeHtml(pos.note)}</span></div>
    <div class="decision-card risk"><span class="decision-label">Alpha</span><b>${escapeHtml(alphaState)}</b><span>上限 ${escapeHtml(limits["Alpha总仓位上限"] || "待配置")}</span></div>
    <div class="decision-card neutral"><span class="decision-label">强制降仓</span><b>ETF回撤规则</b><span>${escapeHtml(Object.entries(etf).slice(0, 2).map(([k, v]) => `${k}:${v}`).join("；") || "待配置")}</span></div>
  </div>
  <div class="risk-rule-row">
    <span>单票上限：${escapeHtml(Object.entries(limits).slice(0, 3).map(([k, v]) => `${k}${v}`).join(" / ") || "待配置")}</span>
    <span>止损：${escapeHtml(Object.entries(stop).slice(0, 2).map(([k, v]) => `${k}${v}`).join(" / ") || "待配置")}</span>
  </div>`;
}

function renderSignalReview(data) {
  const el = document.getElementById("signal-review");
  if (!el) return;
  const rows = data?.signals || data?.reviews || [];
  if (!data || !rows.length) {
    el.innerHTML = `<div class="decision-strip signal-review-empty">
      <div class="decision-card neutral"><span class="decision-label">复盘状态</span><b>待接入</b><span>data/signal-review.json 不存在或暂无记录</span></div>
      <div class="decision-card action"><span class="decision-label">后续格式</span><b>昨日判断 → 今日验证</b><span>支持 命中 / 失效 / 待验证 和失效原因</span></div>
    </div>`;
    return;
  }
  el.innerHTML = `<div class="signal-review-list">${rows.slice(0, 6).map(r => {
    const status = r.status || r.result || "待验证";
    const cls = /命中|有效/.test(status) ? "good" : /失效|错误/.test(status) ? "risk" : "neutral";
    return `<div class="signal-review-item ${cls}">
      <b>${escapeHtml(r.title || r.signal || r.yesterday || "信号复盘")}</b>
      <span>${escapeHtml(status)}</span>
      <p>${escapeHtml(r.today || r.verify || r.reason || r.note || "等待验证")}</p>
    </div>`;
  }).join("")}</div>`;
}

/* =========================
   盘中异动（保留最近10条）
========================= */
const ALERT_KEY = "stock_alerts_history";
const MAX_ALERTS = 10;
const ALERT_TTL = 6 * 60 * 60 * 1000; // 6小时过期
const FUTURE_ALERT_TOLERANCE = 60 * 1000; // 行情源/浏览器轻微时间差容忍1分钟

function loadAlertHistory() {
  try {
    const raw = localStorage.getItem(ALERT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) { return []; }
}

function saveAlertHistory(alerts) {
  const now = Date.now();
  const valid = alerts.filter(a =>
    now - (a._received || 0) < ALERT_TTL &&
    (!a._eventTime || a._eventTime <= now + FUTURE_ALERT_TOLERANCE)
  );
  const latest = sortAlertsByEventTime(valid).slice(0, MAX_ALERTS);
  localStorage.setItem(ALERT_KEY, JSON.stringify(latest));
  return latest;
}

function mergeAlerts(history, incoming, baseTimestamp) {
  const now = Date.now();
  const merged = history.map(a => normalizeAlertTime(a, baseTimestamp, now));
  const ids = new Set(history.map(a => a.id));
  for (const a of incoming) {
    if (!ids.has(a.id)) {
      merged.push(normalizeAlertTime({ ...a, _received: now }, baseTimestamp, now));
      ids.add(a.id);
    } else {
      const index = merged.findIndex(item => item.id === a.id);
      if (index >= 0) {
        merged[index] = normalizeAlertTime({ ...merged[index], ...a }, baseTimestamp, now);
      }
    }
  }
  return sortAlertsByEventTime(merged);
}

function normalizeAlertTime(alert, baseTimestamp, fallbackMs) {
  if (!alert._received) alert._received = fallbackMs;
  alert._eventTime = alertEventTime(alert, baseTimestamp, fallbackMs);
  return alert;
}

function sortAlertsByEventTime(alerts) {
  return alerts.slice().sort((a, b) =>
    (b._eventTime || 0) - (a._eventTime || 0) ||
    (b._received || 0) - (a._received || 0)
  );
}

function alertEventTime(alert, baseTimestamp, fallbackMs) {
  const rawTime = String(alert.time || "");
  if (/^\d{4}-\d{2}-\d{2}T/.test(rawTime)) {
    const parsedIso = Date.parse(rawTime);
    return Number.isNaN(parsedIso) ? fallbackMs : parsedIso;
  }
  const idDate = String(alert.id || "").match(/^(\d{4})(\d{2})(\d{2})/);
  const base = idDate
    ? `${idDate[1]}-${idDate[2]}-${idDate[3]}`
    : (baseTimestamp ? String(baseTimestamp).slice(0, 10) : new Date(fallbackMs).toISOString().slice(0, 10));
  const time = /^\d{2}:\d{2}:\d{2}$/.test(rawTime) ? rawTime : "00:00:00";
  const parsed = Date.parse(`${base}T${time}+08:00`);
  return Number.isNaN(parsed) ? fallbackMs : parsed;
}

function displayAlertTime(alert) {
  const rawTime = String(alert?.time || "");
  const iso = rawTime.match(/T(\d{2}:\d{2}:\d{2})/);
  if (iso) return iso[1];
  return /^\d{2}:\d{2}:\d{2}$/.test(rawTime) ? rawTime : "--:--:--";
}

function renderAlerts(data) {
  updatePanelMeta("alerts", data.timestamp);
  const el = document.getElementById("alerts");
  const now = Date.now();
  localStorage.removeItem(ALERT_KEY);
  const saved = sortAlertsByEventTime(
    (data.alerts || [])
      .map(a => normalizeAlertTime({ ...a, _received: alertEventTime(a, data.timestamp, now) }, data.timestamp, now))
      .filter(a => !a._eventTime || a._eventTime <= now + FUTURE_ALERT_TOLERANCE)
  ).slice(0, MAX_ALERTS);

  renderAlertsSummary(saved, data.timestamp);

  if (!saved.length) { el.innerHTML = '<div class="empty">暂无盘中异动</div>'; return; }

  el.innerHTML = saved.map((a, i) => {
    const age = now - (a._eventTime || a._received || now);
    const ageMin = Math.floor(age / 60000);
    const isOld = ageMin > 30;
    const isStale = ageMin > 60;

    const cls = a.is_old_economy ? "card sentiment" :
                a.signal_type?.includes("交易") ? "card hot" : "card";
    const fadeCls = isStale ? " faded" : isOld ? " dim" : "";
    const ageLabel = ageMin < 1 ? "刚刚" : ageMin < 60 ? `${ageMin}分钟前` : `${Math.floor(ageMin / 60)}小时前`;

    const badge = a.is_old_economy ? '<span class="badge old">老登</span>' :
                  a.signal_type?.includes("交易") ? '<span class="badge signal">交易信号</span>' :
                  a.signal_type?.includes("观察") ? '<span class="badge watch">观察</span>' :
                  a.signal_type?.includes("放量") ? '<span class="badge volume">放量</span>' :
                  a.signal_type?.includes("风险") ? '<span class="badge risk">风险</span>' : '';
    const leaders = (a.leaders || []).slice(0, 3).map(l => {
      const move = Number(l.change_pct);
      const moveText = Number.isFinite(move)
        ? `<span class="pct ${move >= 0 ? 'up' : 'down'}">3m ${move > 0 ? '+' : ''}${move.toFixed(2)}%</span>`
        : '<span class="pct muted">3m --</span>';
      return `<span class="leader" title="触发窗口的3分钟涨跌幅，不是实时股价">${l.name} ${moveText}</span>`;
    }).join(" ");
    const reason = String(a.reason || "");
    const shortReason = truncateText(reason, 58);
    const reasonDetail = reason.length > shortReason.length
      ? `<details class="alert-detail"><summary>触发说明</summary><div>${escapeHtml(reason)}</div></details>`
      : "";
    const factors = (a.leaders || []).slice(0, 3)
      .flatMap(l => Array.isArray(l.factors) ? l.factors.slice(0, 2).map(f => `${l.name}：${f}`) : [])
      .slice(0, 4);
    const factorHtml = factors.length ? `<div class="alert-factors">${factors.map(f => `<span>${escapeHtml(f)}</span>`).join("")}</div>` : "";

    return `<div class="${cls}${fadeCls}">
      <div class="card-head">${badge}<b>${a.sector}</b><span class="time">${displayAlertTime(a)} · ${ageLabel}</span></div>
      <div class="card-body"><b>${escapeHtml(a.type || "异动")}</b>${shortReason ? ` · ${escapeHtml(shortReason)}` : ""}</div>
      ${leaders ? `<div class="card-leaders">${leaders}</div>` : ""}
      ${factorHtml}
      ${reasonDetail}
    </div>`;
  }).join("");
}

function renderAlertsSummary(alerts, timestamp) {
  const el = document.getElementById("alerts-summary");
  if (!el) return;
  if (!alerts.length) {
    el.innerHTML = '<div class="alert-summary-empty">暂无新异动，等待触发</div>';
    return;
  }
  const latest = alerts[0];
  const riskCount = alerts.filter(a => /风险|跌|回落|弱/.test([a.signal_type, a.type, a.reason].join(" "))).length;
  const tradeCount = alerts.filter(a => /交易|急拉|强化|买/.test([a.signal_type, a.type, a.reason].join(" "))).length;
  const volumeCount = alerts.filter(a => /放量|成交/.test([a.signal_type, a.type, a.reason].join(" "))).length;
  const leaders = Array.from(new Set(alerts.flatMap(a => (a.leaders || []).map(l => l.name)).filter(Boolean))).slice(0, 4);
  const tone = riskCount >= tradeCount ? "risk" : "hot";
  const timeText = formatUpdateTime(timestamp);
  const relatedTags = positiveRelatedTopicTags(alerts.map(a => [a.sector, a.type, a.reason].join(" ")).join(" "), leaders.join(" "));
  el.innerHTML = `
    <div class="decision-strip alerts-decision">
    <div class="decision-card ${tone === "hot" ? "primary" : "risk"}">
      <span class="decision-label">核心结论</span>
      <b>${escapeHtml(latest.sector || "盘中异动")}</b>
      <span>${escapeHtml(latest.type || latest.signal_type || "等待分类")} · ${escapeHtml(displayAlertTime(latest) || timeText || "")}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">关联题材</span>
      <b>${escapeHtml(relatedTags[0] || "等待映射")}</b>
      <span>${escapeHtml(relatedTags.slice(1).join(" / ") || "按母题材合并观察")}</span>
    </div>
    <div class="decision-card primary">
      <span class="decision-label">相关个股</span>
      <b>${leaders.length ? leaders.map(escapeHtml).join(" / ") : "暂无"}</b>
      <span>${escapeHtml(`交易 ${tradeCount} / 放量 ${volumeCount}`)}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">回避/降级</span>
      <b>${escapeHtml(riskCount ? `风险 ${riskCount}` : "暂无明确")}</b>
      <span>${escapeHtml(riskCount ? "看是否从单点扩散成板块压力" : "无风险信号前不预设降级")}</span>
    </div>
    </div>
  `;
}

/* =========================
   盘中全景（双格式兼容）
========================= */
function renderIntraday(data) {
  updatePanelMeta("intraday-indices", data.timestamp);
  renderIntradayDecision(data);
  // 指数行
  const idxEl = document.getElementById("intraday-indices");
  if (data.indices) {
    idxEl.innerHTML = renderIndexRow(data.indices);
  } else {
    idxEl.innerHTML = '<span class="empty-sm">指数数据待更新</span>';
  }

  const sectorLists = buildIntradaySectorLists(data);
  document.querySelectorAll('.sector-grid').forEach(el => el.style.display = '');
  renderSectorList("concept-top", sectorLists.conceptTop, "up");
  renderSectorList("concept-bot", sectorLists.conceptBottom, "down");
  renderSectorList("industry-top", sectorLists.industryTop, "up");
  renderSectorList("industry-bot", sectorLists.industryBottom, "down");
  data._hasSectorDisplay = sectorLists.hasAny;

  // Codex 格式: 深度分析（main_trends 含 status 或 themes 存在）
  if (data.main_trends && data.main_trends.length && (typeof data.main_trends[0] === 'object' ? data.main_trends[0].status : true)) {
    renderCodexIntraday(data);
    return;
  }

  // Cola 格式: 概念/行业涨跌榜
  // 先恢复四栏网格
  const analysisEl = document.getElementById('intraday-analysis');
  if (analysisEl) analysisEl.style.display = 'none';

  if (data.concept_top5 || data.industry_top5) {
    return;
  }

  // 老格式兼容
  if (data.main_trends && data.main_trends.length) {
    renderSectorList("concept-top", data.main_trends, "up");
  }
}

function renderIntradayDecision(data) {
  const el = document.getElementById("intraday-decision");
  if (!el) return;
  const themes = getIntradayThemes(data);
  const strong = themes.filter(isPriorityTheme);
  const risks = themes.filter(t => isAvoidTheme(t) && !strong.some(s => trendName(s) === trendName(t)));
  const primary = strong[0] || themes[0];
  const primaryName = primary ? themeDisplayName(primary) : "等待主线确认";
  const primaryStatus = primary ? trendStatus(primary) || "观察" : "暂无";
  const riskNames = risks.slice(0, 2).map(t => themeDisplayName(t)).join(" / ") || "暂无明确风险线";
  const sentiment = intradayMood(data);
  const action = intradayActionText(data, strong, risks, sentiment);
  const relatedTags = positiveRelatedTopicTags(themes.map(t => [trendName(t), trendStatus(t), t.reason, t.continuity].join(" ")).join(" "));

  el.innerHTML = `
    <div class="decision-card primary">
      <span class="decision-label">核心结论</span>
      <b>${escapeHtml(primaryName)}</b>
      <span>${escapeHtml(primaryStatus)}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">关联题材</span>
      <b>${escapeHtml(relatedTags[0] || "等待映射")}</b>
      <span>${escapeHtml(relatedTags.slice(1).join(" / ") || sentiment.detail)}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">回避/降级</span>
      <b>${escapeHtml(riskNames)}</b>
      <span>${escapeHtml(risks[0]?.risk || "看是否扩散")}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">下一步验证</span>
      <b>${escapeHtml(action.title)}</b>
      <span>${escapeHtml(action.detail)}</span>
    </div>
  `;
}

function getIntradayThemes(data) {
  const source = Array.isArray(data.main_trends) && data.main_trends.length
    ? data.main_trends
    : (Array.isArray(data.themes) ? data.themes : []);
  return source.filter(Boolean);
}

function intradayMood(data) {
  const s = data.sentiment || {};
  const up = Number(s.limit_up_count ?? data.limit_up_count ?? 0);
  const down = Number(s.limit_down_count ?? data.limit_down_count ?? 0);
  const broken = Number(s.broken_limit_count ?? data.broken_limit_count ?? 0);
  const judgement = s.judgement || s.interpretation || "";
  if (judgement) {
    const cls = /风险|弱|分歧|退潮|回落/.test(judgement) ? "warn" : /强|修复|进攻/.test(judgement) ? "good" : "neutral";
    return { title: judgement, detail: up || down ? `涨停${up} / 跌停${down} / 炸板${broken || "-"}` : "等待量化确认", cls };
  }
  if (down >= 15 || broken >= 40) return { title: "分歧偏强", detail: `涨停${up} / 跌停${down} / 炸板${broken}`, cls: "warn" };
  if (up >= 80 && down <= 10) return { title: "进攻占优", detail: `涨停${up} / 跌停${down}`, cls: "good" };
  return { title: "中性观察", detail: up || down ? `涨停${up} / 跌停${down}` : "情绪数据待更新", cls: "neutral" };
}

function intradayActionText(data, strong, risks, sentiment) {
  const actions = Array.isArray(data.actions) ? data.actions.filter(Boolean) : [];
  if (actions.length) {
    return {
      title: `看${Math.min(actions.length, 3)}个验证信号`,
      detail: truncateText(actions.slice(0, 2).join("；"), 58)
    };
  }
  if (sentiment.cls === "warn" || risks.length >= 2) {
    return { title: "先控风险", detail: "只看前排承接，弱线不做反抽" };
  }
  if (strong.length) {
    return { title: "跟随主线", detail: "优先前排确认，后排只做观察" };
  }
  return { title: "等待确认", detail: "没有共振前降低操作频率" };
}

function renderCodexIntraday(data) {
  let html = '';

  // 涨停情绪（只有有实际数据才显示）
  if (data.limit_up_count != null || (data.sentiment && (data.sentiment.limit_up_count || data.sentiment.limit_ratio))) {
    const s = data.sentiment || {};
    const lu = s.limit_up_count || data.limit_up_count || 0;
    const ld = s.limit_down_count || data.limit_down_count || 0;
    if (lu > 0 || ld > 0) {
      html += `<div class="subsection"><h3>⚡ 涨停情绪</h3><div class="breadth">涨停 <b>${lu}</b> / 跌停 <b>${ld}</b> · 差值 <span class="up">+${lu-ld}</span>${s.limit_ratio ? ' · '+s.limit_ratio : ''}${s.interpretation ? `<br><span class="muted">${s.interpretation}</span>` : ''}</div></div>`;
    }
  }

  // 主线分析（兼容字符串和对象数组两种格式）
  if (data.main_trends) {
    html += '<div class="subsection"><h3>🔥 主线研判</h3>';
    if (typeof data.main_trends === 'string') {
      html += `<div class="breadth">${data.main_trends}</div>`;
    } else {
      html += data.main_trends.map(t => {
        const name = themeDisplayName(t);
        const status = trendStatus(t);
        const cls = status.includes('强') ? 'strong-theme' : '';
        const evidence = t.evidence ? renderEvidenceDetails(t.evidence) : "";
        const continuity = t.continuity ? `<div class="theme-line">${escapeHtml(truncateText(t.continuity, 90))}</div>` : "";
        const risk = t.risk ? `<div class="theme-line risk-text">风险：${escapeHtml(truncateText(t.risk, 90))}</div>` : "";
        return `<div class="theme-item ${cls}"><b>${escapeHtml(name)}</b>${status ? ` <span class="muted">— ${escapeHtml(status)}</span>` : ""}${renderThemeSubTags(t)}${continuity}${risk}${evidence}</div>`;
      }).join('');
    }
    html += '</div>';
  }

  // 板块分类（Codex themes 新格式）
  if (data.themes && data.themes.length) {
    html += '<div class="subsection"><h3>📊 板块分类</h3>';
    html += data.themes.map(t => {
      if (typeof t === 'string') {
        return `<div class="theme-item">➖ <b>${t}</b></div>`;
      }
      const status = trendStatus(t);
      const cls = status.includes('强') ? 'strong-theme' : status.includes('弱') || status.includes('风险') ? 'sentiment' : '';
      const icon = status.includes('强') ? '✅' : status.includes('弱') || status.includes('风险') ? '🔻' : '➖';
      const evidence = t.evidence ? renderEvidenceDetails(t.evidence) : "";
      const continuity = t.continuity ? `<div class="theme-line">${escapeHtml(truncateText(t.continuity, 90))}</div>` : "";
      const risk = t.risk ? `<div class="theme-line risk-text">风险：${escapeHtml(truncateText(t.risk, 90))}</div>` : "";
      return `<div class="theme-item ${cls}"><b>${icon} ${escapeHtml(themeDisplayName(t))}</b>${status ? ` <span class="muted">— ${escapeHtml(status)}</span>` : ""}${renderThemeSubTags(t)}${continuity}${risk}${evidence}</div>`;
    }).join('');
    html += '</div>';
  }

  // 情绪详情
  if (data.sentiment && typeof data.sentiment === 'object' && Object.keys(data.sentiment).length > 0) {
    html += renderIntradaySentimentBlock(data.sentiment);
  }

  // 操作建议
  const afternoonAdvice = intradayAdviceItems(data);
  if (afternoonAdvice.length) {
    html += '<div class="subsection"><h3>💡 午后建议</h3><ul class="news-list strong">';
    html += afternoonAdvice.slice(0, 6).map(a => `<li>${escapeHtml(a)}</li>`).join('');
    html += '</ul></div>';
  }

  // 专项观察
  if (data.special_watch) {
    html += '<div class="subsection"><h3>🔍 专项观察</h3>';
    const groups = Object.entries(data.special_watch);
    for (const [key, stocks] of groups) {
      if (!Array.isArray(stocks) || !stocks.length) continue;
      const label = { semiconductor_five: '半导体五只', electronic_cloth_glassfiber: '电子布/玻纤链' }[key] || key;
      html += `<h4 style="font-size:12px;color:#8B949E;margin:8px 0 4px">${label}</h4>`;
      html += stocks.map(s => {
        if (typeof s === "string") {
          return `<div class="theme-item" style="font-size:12px;padding:6px 10px;margin-bottom:3px"><b>${escapeHtml(s)}</b></div>`;
        }
        const pct = s.pct ?? s.change_pct;
        const pctHtml = pct !== undefined ? ` <span class="${pct >= 0 ? 'up' : 'down'}">${pct > 0 ? '+' : ''}${pct}%</span>` : "";
        const status = s.status ? ` · ${escapeHtml(s.status)}` : "";
        const risk = s.risk ? ` <span class="muted" style="font-size:10px">⚠ ${escapeHtml(s.risk)}</span>` : "";
        return `<div class="theme-item" style="font-size:12px;padding:6px 10px;margin-bottom:3px"><b>${escapeHtml(s.name || s.symbol || "未命名")}</b>${pctHtml}${status}${risk}</div>`;
      }).join('');
    }
    html += '</div>';
  }

  let analysisEl = document.getElementById('intraday-analysis');
  if (!analysisEl) {
    analysisEl = document.createElement('div');
    analysisEl.id = 'intraday-analysis';
    const indicesEl = document.getElementById('intraday-indices');
    indicesEl.parentNode.insertBefore(analysisEl, indicesEl.nextSibling);
  }
  analysisEl.innerHTML = html;
  analysisEl.style.display = 'block';
}

function renderIntradaySentimentBlock(sentiment) {
  const items = Object.entries(sentiment || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!items.length) return "";
  const judgement = sentiment.judgement || sentiment.interpretation || "";
  const headline = judgement ? `<div class="breadth"><b>${escapeHtml(judgement)}</b></div>` : "";
  let html = `<div class="subsection"><h3>📈 盘面情绪</h3>${headline}<ul class="news-list">`;
  for (const [k, v] of items) {
    if (["judgement", "interpretation"].includes(k)) continue;
    const label = intradaySentimentLabel(k);
    html += `<li><b>${label}</b>：${escapeHtml(formatDisplayValue(v))}</li>`;
  }
  html += '</ul></div>';
  return html;
}

function intradayAdviceItems(data) {
  const midday = cached("data/midday.json") || {};
  const items = [
    ...arrayTextItems(data.actions),
    ...arrayTextItems(data.afternoon_watch),
    ...arrayTextItems(midday.afternoon_watch)
  ];
  return uniqueList(items).filter(Boolean);
}

function arrayTextItems(value) {
  if (!Array.isArray(value)) return [];
  return value.map(item => {
    if (typeof item === "string") return item;
    if (!item || typeof item !== "object") return "";
    return item.text || item.action || item.note || item.name || JSON.stringify(item);
  }).filter(Boolean);
}

function renderSectorList(elId, sectors, dir) {
  const el = document.getElementById(elId);
  if (!sectors || !sectors.length) {
    el.innerHTML = '<div class="empty-sm">数据待接入</div>';
    return;
  }
  const cls = dir === 'up' ? 'up' : 'down';
  const rows = sectors.map((s, i) => renderSectorRow(s, i, cls));
  if (rows.length <= 3) {
    el.innerHTML = rows.join("");
    return;
  }
  el.innerHTML = rows.slice(0, 3).join("") + `<details class="compact-details"><summary>展开完整榜单（${rows.length}）</summary>${rows.slice(3).join("")}</details>`;
}

function renderSectorRow(s, i, cls) {
    if (typeof s === "string") s = { name: s };
    const pct = s.change_pct !== undefined ? s.change_pct : (s.pct !== undefined ? s.pct : null);
    const detail = s.detail || s.status || "";
    const barW = pct != null ? Math.min(Math.abs(pct) * 5, 100) : 0;
    const pctStr = pct != null ? `${pct > 0 ? '+' : ''}${pct}%` : '';
    return `<div class="sector-row">
      <span class="rank">${i + 1}</span>
      <span class="sector-name">${escapeHtml(s.name || s.sector || "未命名板块")}${detail ? ` <span class="muted" style="font-size:10px">${escapeHtml(detail)}</span>` : ''}</span>
      <span class="sector-pct ${cls}">${pctStr}</span>
      <div class="bar"><div class="bar-fill ${cls}" style="width:${barW}%"></div></div>
    </div>`;
}

function buildIntradaySectorLists(data) {
  const conceptTop = data.concept_top5 || data.concept_top || data.conceptTop || [];
  const conceptBottom = data.concept_bottom5 || data.concept_bottom || data.conceptBottom || [];
  const industryTop = data.industry_top5 || data.industry_top || data.industryTop || [];
  const industryBottom = data.industry_bottom5 || data.industry_bottom || data.industryBottom || [];
  const source = Array.isArray(data.themes) && data.themes.length ? data.themes : (Array.isArray(data.main_trends) ? data.main_trends : []);
  const inferredTop = source
    .filter(t => typeof t === "object" && /强|强化|资金|观察/.test(trendStatus(t)) && !/风险|弱|退潮/.test(trendStatus(t)))
    .map(t => ({ name: themeDisplayName(t), status: trendStatus(t), detail: themeSubDirections(t).join(" / ") || trendStatus(t) }))
    .slice(0, 5);
  const inferredBottom = source
    .filter(t => typeof t === "object" && /风险|弱|退潮|回落/.test(trendStatus(t)))
    .map(t => ({ name: themeDisplayName(t), status: trendStatus(t), detail: themeSubDirections(t).join(" / ") || trendStatus(t) }))
    .slice(0, 5);
  return {
    conceptTop: conceptTop.length ? conceptTop : inferredTop,
    conceptBottom: conceptBottom.length ? conceptBottom : inferredBottom,
    industryTop,
    industryBottom,
    hasAny: !!(conceptTop.length || conceptBottom.length || industryTop.length || industryBottom.length || inferredTop.length || inferredBottom.length)
  };
}

function trendName(item) {
  if (typeof item === "string") return item;
  return item?.name || item?.sector || item?.theme || item?.title || "未命名主线";
}

function themeDisplayName(item) {
  const name = trendName(item);
  const text = [name, item?.status, item?.continuity, item?.risk, ...themeStockText(item)].join(" ");
  if (/汽车零部件|汽车零部|机器人|通用设备|自动化设备/.test(text) && /机器人|通用设备|自动化设备/.test(text)) {
    return "机器人/工业自动化";
  }
  if (/电子布|玻纤|PCB|覆铜板/.test(text)) return "PCB材料链";
  if (/半导体设备|CMP设备|刻蚀|沉积|清洗/.test(text)) return "半导体设备";
  if (/半导体材料|光刻胶|硅片|硅材料|CMP抛光|靶材/.test(text)) return "半导体材料";
  if (/CPO|光模块|光通信/.test(text)) return "CPO/光模块";
  if (/存储|HBM|DDR|兆易|澜起|佰维|江波龙/.test(text)) return "存储/HBM";
  if (/AI应用|视频生成|办公|软件|传媒/.test(text)) return "AI应用";
  if (/化学制药|创新药|原料药|医药/.test(text)) return "医药修复链";
  if (/券商|证券|保险|白酒|畜牧|权重/.test(text)) return "老登风格切换";
  return name;
}

function themeSubDirections(item) {
  const name = trendName(item);
  const text = [name, item?.status, item?.continuity, item?.risk, ...themeStockText(item)].join(" ");
  const rules = [
    ["汽车零部件", /汽车零部件|汽车零部|飞龙股份|圣龙股份|明新旭腾|晋拓股份/],
    ["机器人", /机器人|绿的谐波|埃斯顿|中大力德|优必选/],
    ["通用设备", /通用设备|日发精机|夏厦精密|杭齿前进|丰光精密/],
    ["自动化设备", /自动化设备|步科股份|雷赛智能|中控技术|汇川技术/],
    ["半导体设备", /半导体设备|北方华创|中微公司|华海清科|芯源微|拓荆科技/],
    ["半导体材料", /半导体材料|雅克科技|安集科技|江丰电子|中巨芯|南大光电|晶瑞电材/],
    ["CPO/光模块", /CPO|光模块|新易盛|中际旭创|天孚通信|光迅科技/],
    ["存储/HBM", /存储|HBM|兆易创新|澜起科技|佰维存储|江波龙/],
    ["PCB材料", /PCB|电子布|玻纤|覆铜板|中国巨石|国际复材|生益科技|沪电股份|胜宏科技/],
    ["AI应用", /AI应用|视频生成|昆仑万维|金山办公|智谱|商汤|快手/],
    ["医药", /化学制药|创新药|原料药|恒瑞|科伦|百济|艾力斯/],
    ["老登切换", /券商|证券|保险|白酒|畜牧|权重/]
  ];
  return rules.filter(([, re]) => re.test(text)).map(([label]) => label).slice(0, 6);
}

function renderThemeSubTags(item) {
  const tags = themeSubDirections(item);
  return tags.length ? `<div class="topic-related theme-subtags">${tags.map(tag => `<span>${escapeHtml(tag)}</span>`).join("")}</div>` : "";
}

function themeStockText(item) {
  const stocks = item?.stocks || item?.leaders || item?.representatives || [];
  if (!Array.isArray(stocks)) return [String(stocks || "")];
  return stocks.map(stock => typeof stock === "string" ? stock : (stock?.name || stock?.symbol || stock?.code || "")).filter(Boolean);
}

function trendStatus(item) {
  if (!item || typeof item === "string") return "";
  return item.status || item.state || item.judgement || item.action || "";
}

function intradaySentimentLabel(key) {
  return {
    market: "大盘",
    limit_up_count: "涨停数",
    limit_down_count: "跌停数",
    limit_diff: "涨跌停差值",
    broken_limit_count: "炸板数",
    limit_up_pct_estimated: "涨停占比估算",
    limit_down_pct_estimated: "跌停占比估算",
    compare_with_last: "较上一时点",
    limit_ratio: "涨跌停比",
    judgement: "情绪判断",
    interpretation: "解读",
    silan_micro: "士兰微",
    nanda_opto: "南大光电"
  }[key] || key.replace(/_/g, " ");
}

function externalLabel(key) {
  return {
    nikkei225_change_pct: "日经225",
    kospi_change_pct: "韩国KOSPI",
    samsung_change_pct: "三星电子",
    sk_hynix_change_pct: "SK海力士",
    judgement: "判断",
    indices: "指数",
    hot_sectors: "强势方向",
    weak_sectors: "弱势方向",
    conclusion: "结论",
    reason: "原因"
  }[key] || key.replace(/_/g, " ");
}

function formatDisplayValue(value) {
  if (Array.isArray(value)) return value.map(formatDisplayValue).join("、");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([k, v]) => `${externalLabel(k)}：${formatDisplayValue(v)}`)
      .join("；");
  }
  if (typeof value === "number") return `${value > 0 ? "+" : ""}${value.toFixed(2).replace(/\.00$/, "")}`;
  return String(value ?? "");
}

function formatMarketTag(item) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "";
  const name = item.name || item.symbol || item.market || item.sector || item.source_asset || "";
  const pct = item.change_pct !== undefined ? ` ${formatPct(item.change_pct)}` : "";
  const status = item.status || item.strength || item.note || item.impact || "";
  return `${name}${pct}${status ? `：${status}` : ""}`;
}

function formatPct(value) {
  if (typeof value === "string") return value;
  if (typeof value !== "number") return "--";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function pctClass(value) {
  if (typeof value === "string") return value.trim().startsWith("-") ? "down" : "up";
  return typeof value === "number" && value < 0 ? "down" : "up";
}

function renderIndexRow(indices) {
  if (Array.isArray(indices)) {
    return indices.map(i => {
      const v = i.change_pct !== undefined ? i.change_pct : i.pct;
      const note = i.note ? ` <span class="muted">${escapeHtml(i.note)}</span>` : "";
      const close = i.close !== undefined ? ` <span class="muted">${formatIndexClose(i.close)}</span>` : "";
      return `<span class="index-item">${escapeHtml(i.name || i.market || "指数")}${close} <span class="${pctClass(v)}">${formatPct(v)}</span>${note}</span>`;
    }).join("");
  }
  return Object.entries(indices).map(([name, v]) => {
    const value = typeof v === "object" && v !== null ? (v.change_pct ?? v.pct ?? v.value) : v;
    const close = typeof v === "object" && v !== null && v.close !== undefined ? ` <span class="muted">${formatIndexClose(v.close)}</span>` : "";
    return `<span class="index-item">${escapeHtml(externalLabel(name))}${close} <span class="${pctClass(value)}">${formatPct(value)}</span></span>`;
  }).join("");
}

function formatIndexClose(value) {
  return typeof value === "number" ? value.toFixed(2) : escapeHtml(value);
}

function splitPremarketText(text) {
  if (Array.isArray(text)) return text.flatMap(splitPremarketText);
  const raw = String(text || "").trim();
  if (!raw) return [];
  return raw
    .replace(/；/g, "。\n")
    .replace(/; /g, "。\n")
    .split(/\n|(?<=。)/)
    .map(s => s.trim().replace(/。$/, ""))
    .filter(Boolean);
}

function renderBulletList(items, className = "news-list") {
  const list = (items || []).map(item => String(item || "").trim()).filter(Boolean);
  if (!list.length) return "";
  return `<ul class="${className}">${list.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function takePremarketPoints(text, limit = 2, maxLength = 140) {
  return splitPremarketText(text)
    .slice(0, limit)
    .map(item => truncateText(item, maxLength));
}

function summarizePremarketStrategy(text) {
  const raw = String(text || "");
  if (raw.includes("扩产+技术迭代") || raw.includes("BOM/token")) {
    return [
      "核心结论：扩产/技术迭代逻辑只算部分确认偏弱，今日先看风险释放，不预设修复。",
      "板块判断：半导体硬件不作日内强主线；观察AI应用、创新药、低位资源，风险在设备材料、存储、PCB/CPO。",
      "判断依据：看半导体跌停是否收缩、北方/雅克是否开板、港股中芯/华虹是否止跌；核心继续封跌停则维持风险线。"
    ];
  }
  const blocks = raw.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
  const core = blocks.find(b => b.startsWith("1）")) || blocks[0] || "";
  const verify = blocks.find(b => b.startsWith("5）")) || "";
  const upgrade = blocks.find(b => b.startsWith("3）")) || "";
  return [
    core.replace(/^1）一句话结论[:：]?/, "核心结论："),
    upgrade.replace(/^3）板块升降级[:：]?/, "板块判断："),
    verify.replace(/^5）今日重点验证指标和失效条件[:：]?/, "验证条件：")
  ].filter(Boolean).map(item => truncateText(item, 120));
}

function truncateText(text, maxLength = 140) {
  const raw = String(text || "").replace(/\s+/g, " ").trim();
  return raw.length > maxLength ? `${raw.slice(0, maxLength)}...` : raw;
}

function renderMappingChain(items) {
  if (!items || !items.length) return "";
  return '<ul class="news-list mapping-chain">' + items.slice(0, 2).map(item => {
    if (typeof item === "string") return `<li>${escapeHtml(item)}</li>`;
    const source = item.source_asset || item.source || item.name || "映射标的";
    const pct = item.change_pct !== undefined ? ` ${formatPct(item.change_pct)}` : "";
    const reason = item.reason ? `：${escapeHtml(item.reason)}` : "";
    const target = item.a_share_mapping || item.target || item.mapping || "";
    const logic = item.mapping_logic || item.logic || "";
    return `<li><b>${escapeHtml(source)}${escapeHtml(pct)}</b>${reason}${target ? `<br><span class="muted">→ ${escapeHtml(truncateText(target, 80))}</span>` : ""}${logic ? `<br><span class="muted">逻辑：${escapeHtml(truncateText(logic, 90))}</span>` : ""}</li>`;
  }).join("") + '</ul>';
}

/* =========================
   盘前简报
========================= */
function renderPremarket(data) {
  updatePanelMeta("premarket", data.timestamp);
  const el = document.getElementById("premarket");
  let html = "";
  const concisePremarket = typeof data.strategy === "string";
  html += renderPremarketDecision(data);

  // === Codex 格式: 集合竞价 + 情绪判断 ===
  if (data.market_context || data.strong_lines || data.watch_lines) {
    const ctx = data.market_context || {};
    // 竞价情绪
    if (data.market_context) {
      const mood = (ctx.limit_diff || 0) >= 0 ? 'up' : 'down';
      html += '<div class="subsection"><h3>⚡ 集合竞价情绪</h3>';
      html += `<div class="breadth">涨停 <b>${ctx.limit_up_count||0}</b> / 跌停 <b>${ctx.limit_down_count||0}</b> · 差值 <span class="${mood}">${ctx.limit_diff||0}</span> · 涨停:跌停 <b>${ctx.limit_ratio||'-'}</b>${ctx.denominator ? `<span class="muted"> (${ctx.denominator})</span>` : ''}</div>`;
      html += '</div>';
    }
    if (ctx.open_style || ctx.sentiment_judgement || ctx.benefit_themes || ctx.risk_points) {
      html += '<div class="subsection"><h3>🧭 开盘情绪预判</h3>';
      if (ctx.open_style || ctx.sentiment_judgement) {
        html += `<div class="theme-item premarket-lead"><b>${escapeHtml(ctx.open_style || "待判断")}</b></div>`;
        if (ctx.sentiment_judgement) {
          html += renderBulletList(takePremarketPoints(ctx.sentiment_judgement, 2, 140), "premarket-points");
        }
      }
      if (ctx.benefit_themes) {
        html += '<div class="tag-row">受益：' + ctx.benefit_themes.slice(0, 5).map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>';
      }
      if (ctx.risk_points) {
        html += '<div class="tag-row">风险：' + ctx.risk_points.slice(0, 5).map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>';
      }
      html += '</div>';
    }

    // 总结
    if (data.strategy && typeof data.strategy === 'string') {
      html += `<div class="subsection"><h3>📋 盘前研判</h3>${renderBulletList(summarizePremarketStrategy(data.strategy), "premarket-points")}</div>`;
    }
    if (data.summary) {
      html += `<div class="subsection"><h3>💡 操作思路</h3>${renderBulletList(takePremarketPoints(data.summary, 2, 150), "premarket-points")}</div>`;
    }

    // 强主线/观察线/风险线 三栏
    if (data.strong_lines || data.watch_lines || data.risk_lines) {
      html += '<div class="subsection"><div class="line-grid">';
      if (data.strong_lines) {
        html += '<div><h3>🔥 强主线</h3>' + renderBulletList(data.strong_lines.slice(0, 1).map(s => truncateText(s, 80)), "news-list strong") + '</div>';
      }
      if (data.watch_lines) {
        html += '<div><h3>👀 观察线</h3>' + renderBulletList(data.watch_lines.slice(0, 3).map(s => truncateText(s, 50)), "news-list") + '</div>';
      }
      if (data.risk_lines) {
        html += '<div><h3>⚠️ 风险线</h3>' + renderBulletList(data.risk_lines.slice(0, 3).map(s => truncateText(s, 50)), "news-list risk") + '</div>';
      }
      html += '</div></div>';
    }

    // 来源
    if (data.sources) {
      html += '<div class="subsection"><span class="muted" style="font-size:11px">数据源：' + data.sources.map(s => s.url ? `<a href="${s.url}" target="_blank" style="color:#58A6FF">${s.name}</a>` : s.name).join(" · ") + '</span></div>';
    }
  }

  // === 旧格式兼容: 美股隔夜 + 要闻 + 策略卡片 ===
  if (data.us_overnight) {
    html += '<div class="subsection"><h3>🇺🇸 隔夜外部环境</h3>';
    if (data.us_overnight.conclusion) {
      html += renderBulletList(takePremarketPoints(data.us_overnight.conclusion, 2, 150), "premarket-points");
    }
    if (data.us_overnight.indices) {
      html += '<div class="index-row">' + renderIndexRow(data.us_overnight.indices) + '</div>';
    }
    if (data.us_overnight.reason) {
      html += renderBulletList(takePremarketPoints(data.us_overnight.reason, 1, 150), "premarket-points compact");
    }
    if (data.us_overnight.tech_stocks) {
      html += '<div class="tag-row">重点科技股：' + data.us_overnight.tech_stocks.map(s => `<span class="tag">${escapeHtml(formatMarketTag(s))}</span>`).join(" ") + '</div>';
    }
    if (data.us_overnight.japan_korea) {
      html += renderJapanKoreaMorning(data.us_overnight.japan_korea);
    }
    if (data.us_overnight.hot_sectors) {
      html += '<div class="tag-row">热点：' + data.us_overnight.hot_sectors.map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>';
    }
    if (data.us_overnight.weak_sectors) {
      html += '<div class="tag-row">弱势：' + data.us_overnight.weak_sectors.map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>';
    }
    if (data.us_overnight.impact_to_a_share) {
      html += `<h3>A股影响</h3>${renderBulletList(takePremarketPoints(data.us_overnight.impact_to_a_share, 2, 130), "premarket-points")}`;
    }
    if (data.us_overnight.mapping_chain && !concisePremarket) {
      html += '<h3>科技映射链</h3>' + renderMappingChain(data.us_overnight.mapping_chain);
    }
    html += '</div>';
  }
  if (data.hk_auction) {
    html += '<div class="subsection"><h3>🇭🇰 港股竞价</h3>';
    if (data.hk_auction.indices) {
      html += '<div class="index-row">' + renderIndexRow(data.hk_auction.indices) + '</div>';
    }
    if (data.hk_auction.sectors) {
      html += '<div class="tag-row">板块：' + data.hk_auction.sectors.map(s => `<span class="tag">${escapeHtml(formatMarketTag(s))}</span>`).join(" ") + '</div>';
    }
    if (data.hk_auction.stocks) {
      html += '<div class="tag-row">代表股：' + data.hk_auction.stocks.slice(0, 6).map(s => `<span class="tag">${escapeHtml(formatMarketTag(s))}</span>`).join(" ") + '</div>';
    }
    if (data.hk_auction.sentiment) {
      html += renderBulletList(takePremarketPoints(data.hk_auction.sentiment, 2, 140), "premarket-points");
    }
    if (data.hk_auction.mapping_chain && !concisePremarket) {
      html += '<h3>港股映射</h3>' + renderMappingChain(data.hk_auction.mapping_chain);
    }
    html += '</div>';
  }
  if (data.overnight_news && !concisePremarket) {
    html += '<div class="subsection"><h3>📰 隔夜要闻</h3>';
    html += renderBulletList(data.overnight_news.slice(0, 4).map(n => truncateText(typeof n === "string" ? n : n.text || n.title || "", 120)), "news-list");
    html += '</div>';
  }
  if (data.strategy && Array.isArray(data.strategy)) {
    html += '<div class="subsection"><h3>🎯 今日策略</h3><div class="grid">';
    html += data.strategy.map(s => {
      const actionCls = (s.action || "").includes("加") ? "action-buy" : (s.action || "").includes("减") ? "action-sell" : "action-hold";
      return `<div class="card strategy-card ${actionCls}"><div class="card-head"><span class="badge ${actionCls}">${s.action}</span></div><div class="card-body">${(s.logic||[]).map(l=>'· '+l).join("<br>")}</div>${s.target?`<div class="card-body muted">关注：${s.target}</div>`:""}</div>`;
    }).join("");
    html += '</div></div>';
  }

  el.innerHTML = html || '<div class="empty">盘前数据待更新</div>';
}

function renderJapanKoreaMorning(jk) {
  if (typeof jk === "string") {
    return `<div class="source-note"><b>日韩早盘：</b>${escapeHtml(truncateText(jk, 120))}</div>`;
  }
  if (Array.isArray(jk)) {
    return '<div class="tag-row">日韩早盘：' + jk.map(s => `<span class="tag">${escapeHtml(formatMarketTag(s))}</span>`).join(" ") + '</div>';
  }
  if (jk && typeof jk === "object") {
    return '<div class="tag-row">日韩早盘：' + Object.entries(jk).map(([k, v]) => `<span class="tag">${escapeHtml(externalLabel(k))}：${escapeHtml(formatDisplayValue(v))}</span>`).join(" ") + '</div>';
  }
  return "";
}

function renderPremarketDecision(data) {
  const ctx = data.market_context || {};
  const style = ctx.open_style || inferPremarketStyle(data) || "等待竞价确认";
  const riskPoints = ctx.risk_points || data.risk_lines || [];
  const watchLines = ctx.benefit_themes || data.watch_lines || data.strong_lines || [];
  const strongLines = data.strong_lines || [];
  const verify = ctx.sentiment_judgement || data.summary || "";
  const tone = /防御|风险|压制|弱|分化/.test(style + " " + verify) ? "warn" : /进攻|提振|强/.test(style + " " + verify) ? "good" : "neutral";
  const primary = watchLines.find(line => !/暂无/.test(String(line))) || strongLines.find(line => !/暂无/.test(String(line))) || "等待9:25竞价确认";
  const risk = riskPoints[0] || "暂无明确风险点";
  const news = Array.isArray(data.overnight_news) ? data.overnight_news[0] : null;
  const newsText = news ? (news.text || news.title || "") : "";
  const relatedTags = positiveRelatedTopicTags(primary, watchLines.join(" "), strongLines.join(" "), newsText, verify);

  return `<div class="decision-strip premarket-decision">
    <div class="decision-card ${tone}">
      <span class="decision-label">核心结论</span>
      <b>${escapeHtml(style)}</b>
      <span>${escapeHtml(truncateText(data.summary || verify, 62))}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">关联题材</span>
      <b>${escapeHtml(relatedTags[0] || truncateText(primary, 24))}</b>
      <span>${escapeHtml(relatedTags.slice(1).join(" / ") || watchLines.slice(0, 3).join(" / ") || "等集合竞价扩散")}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">回避/降级</span>
      <b>${escapeHtml(truncateText(risk, 24))}</b>
      <span>${escapeHtml(truncateText(riskPoints.slice(1, 3).join("；") || risk, 62))}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">下一步验证</span>
      <b>${escapeHtml(ctx.limit_up_count == null ? "等9:25数据" : "看竞价强弱")}</b>
      <span>${escapeHtml(truncateText(newsText || verify || "看涨跌停、低开收敛和承接扩散", 62))}</span>
    </div>
  </div>`;
}

function inferPremarketStyle(data) {
  const text = [data.summary, data.us_overnight?.conclusion, data.hk_auction?.sentiment].filter(Boolean).join(" ");
  if (/防御|压制|承压|风险/.test(text)) return "分化偏防御";
  if (/提振|共振|强/.test(text)) return "偏进攻";
  if (/中性|分化/.test(text)) return "分化中性";
  return "";
}

/* =========================
   午盘盘前（11:30午间产出）
========================= */
function renderMidday(data) {
  updatePanelMeta("midday", data.timestamp);
  const el = document.getElementById("midday");
  let html = "";
  html += renderMiddayDecision(data);

  // 上午数据快照
  if (data.morning_snapshot) {
    html += '<div class="subsection"><h3>📈 上午快照</h3><div class="breadth">';
    if (typeof data.morning_snapshot === 'string') {
      html += data.morning_snapshot;
    } else {
      const ms = data.morning_snapshot;
      if (ms.indices) {
        html += ms.indices.map(i => {
          const p = parseFloat(i.change_pct ?? i.pct) || 0;
          const cls = p >= 0 ? 'up' : 'down';
          return `<span style="margin-right:12px"><b>${i.name}</b> <span class="${cls}">${p > 0 ? '+' : ''}${p.toFixed(2)}%</span></span>`;
        }).join('');
      }
      const breadth = ms.breadth || ms.sentiment;
      if (breadth) {
        html += `<br><span style="font-size:12px">涨停${breadth.limit_up || breadth.limit_up_count || '?'}家 跌停${breadth.limit_down || breadth.limit_down_count || '?'}家${breadth.break_board_count ? ` 炸板${breadth.break_board_count}家` : ""}</span>`;
      }
    }
    html += '</div></div>';
  }

  // 上午复盘
  if (data.morning_review) {
    html += '<div class="subsection"><h3>📋 上午复盘</h3>';
    const mr = data.morning_review;
    if (mr.one_sentence) html += `<div class="breadth">${mr.one_sentence}</div>`;
    if (mr.main_trends) {
      html += mr.main_trends.map(t =>
        `<div class="theme-item ${(t.status||'').includes('强')?'strong-theme':''}"><b>${escapeHtml(t.name)}</b> <span class="muted">— ${escapeHtml(t.status || "")}</span>${t.evidence ? renderEvidenceDetails(t.evidence) : ""}</div>`
      ).join('');
    }
    html += '</div>';
  }

  // 下午信号
  if (data.afternoon_watch) {
    html += '<div class="subsection"><h3>🔮 下午信号</h3><ul class="news-list">';
    html += data.afternoon_watch.map(w => `<li>${w}</li>`).join('');
    html += '</ul></div>';
  }

  // 风险提示
  const risks = data.risk || data.risks;
  if (risks) {
    html += '<div class="subsection"><h3>⚠️ 下午风险</h3><ul class="news-list risk">';
    html += risks.map(r => `<li>${typeof r==="string"?r:r.text}</li>`).join('');
    html += '</ul></div>';
  }

  // 旧格式兼容（纯文本）
  if (!html && data.content) {
    html = `<pre style="white-space:pre-wrap;font-size:13px">${data.content}</pre>`;
  }

  el.innerHTML = html || '<div class="empty">午间休市后更新</div>';
}

function renderMiddayDecision(data) {
  const review = data.morning_review || {};
  const trends = Array.isArray(review.main_trends) ? review.main_trends : [];
  const strong = trends.find(t => /强/.test(t.status || "")) || trends[0];
  const watch = Array.isArray(data.afternoon_watch) ? data.afternoon_watch : [];
  const risks = data.risk || data.risks || [];
  const sentiment = data.morning_snapshot?.sentiment || {};
  const limitUp = Number(sentiment.limit_up_count || sentiment.limit_up || 0);
  const limitDown = Number(sentiment.limit_down_count || sentiment.limit_down || 0);
  const broken = Number(sentiment.break_board_count || sentiment.broken_limit_count || 0);
  const mood = broken >= 30 || limitDown >= 15 ? "分歧警戒" : limitUp >= 60 && limitDown <= 10 ? "午后可攻可守" : "等待确认";
  const moodCls = mood.includes("警戒") ? "warn" : mood.includes("攻") ? "good" : "neutral";
  const riskText = Array.isArray(risks) && risks.length ? (typeof risks[0] === "string" ? risks[0] : risks[0].text) : "暂未给出风险阈值";
  const relatedTags = positiveRelatedTopicTags(trends.map(t => [trendName(t), t.status, t.reason].join(" ")).join(" "), watch.join(" "), riskText);
  return `<div class="decision-strip midday-decision">
    <div class="decision-card primary">
      <span class="decision-label">核心结论</span>
      <b>${escapeHtml(strong ? themeDisplayName(strong) : "等待主线确认")}</b>
      <span>${escapeHtml(strong?.status || review.one_sentence || "暂无")}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">关联题材</span>
      <b>${escapeHtml(relatedTags[0] || mood)}</b>
      <span>${escapeHtml(relatedTags.slice(1).join(" / ") || `涨停${limitUp || "-"} / 跌停${limitDown || "-"} / 炸板${broken || "-"}`)}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">下一步验证</span>
      <b>${escapeHtml(watch.length ? `看${Math.min(watch.length, 3)}个信号` : "等待信号")}</b>
      <span>${escapeHtml(truncateText(watch.slice(0, 2).join("；"), 62) || "无")}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">回避/降级</span>
      <b>${escapeHtml(risks.length ? "先盯分歧" : "暂无")}</b>
      <span>${escapeHtml(truncateText(riskText, 62))}</span>
    </div>
  </div>`;
}

/* =========================
   午盘盘后
========================= */
function renderPostmarket(data) {
  updatePanelMeta("postmarket", data.timestamp);
  const el = document.getElementById("postmarket");
  let html = "";
  html += renderPostmarketDecision(data);

  // === Codex 格式: hotspots + review ===
  if (data.hotspots || data.review) {
    // 摘要
    if (data.index?.summary) {
      html += `<div class="subsection"><h3>📋 收盘摘要</h3><div class="breadth">${data.index.summary}</div></div>`;
    }

    // 一句话总结
    if (data.review?.one_sentence) {
      html += `<div class="subsection"><h3>📋 收盘总结</h3><div class="breadth">${data.review.one_sentence}</div></div>`;
    }

    // 收盘竞价/尾盘补丁
    if (data.closing_auction_patch) {
      const cap = data.closing_auction_patch;
      html += '<div class="subsection closing-auction"><h3>⏱️ 收盘竞价补丁</h3>';
      if (cap.summary) html += `<div class="breadth">${escapeHtml(cap.summary)}</div>`;
      if (cap.signals?.length) {
        html += '<ul class="news-list">' + cap.signals.map(s => `<li>${escapeHtml(typeof s === "string" ? s : `${s.name || s.signal || "尾盘信号"}：${s.detail || s.text || s.impact || ""}`)}</li>`).join('') + '</ul>';
      }
      if (cap.impact) html += `<div class="evidence-line"><b>影响：</b>${escapeHtml(cap.impact)}</div>`;
      if (cap.watch_next_day?.length) html += `<div class="evidence-line"><b>次日验证：</b>${formatEvidenceList(cap.watch_next_day)}</div>`;
      html += '</div>';
    }

    // 涨跌统计（新格式：index.market_breadth；旧格式：index 顶层）
    if (data.index) {
      const mb = data.index.market_breadth || {};
      const stats = [
        { k: '涨停', v: mb.limit_up ?? data.index['涨停'] },
        { k: '跌停', v: mb.limit_down ?? data.index['跌停'] },
        { k: '炸板', v: mb.broken_board ?? data.index['炸板'] },
        { k: '5%-8%', v: mb.up5_8 ?? data.index['涨幅5%至不足8%'] },
        { k: '8%+', v: mb.up8 ?? data.index['涨幅8%以上'] },
        { k: '跌5%+', v: mb.down5 },
        { k: '涨跌比', v: mb.limit_up_down_ratio ? mb.limit_up_down_ratio.toFixed(1) : null },
      ].filter(x => x.v !== undefined && x.v !== null);
      if (stats.length) {
        html += '<div class="subsection"><h3>📊 涨跌统计</h3><div class="index-row">';
        html += stats.map(s => `<span class="index-item"><b>${s.k}</b> <span class="up">${s.v}</span></span>`).join('');
        html += '</div></div>';
      }
    }

    // 强/弱线分布（新格式：strong_lines/weak_lines 字符串数组；旧格式：limit_pool_industries 对象数组）
    if (data.review?.strong_lines || data.review?.weak_lines) {
      html += '<div class="subsection"><h3>📈 强弱线分布</h3>';
      if (data.review.strong_lines?.length) {
        html += '<div style="margin-bottom:8px"><b class="up">✅ 强线</b><br>';
        html += data.review.strong_lines.map(l => `<span style="font-size:11px;margin-right:10px">• ${l}</span>`).join('');
        html += '</div>';
      }
      if (data.review.weak_lines?.length) {
        html += '<div><b class="down">🔻 弱线</b><br>';
        html += data.review.weak_lines.map(l => `<span style="font-size:11px;margin-right:10px">• ${l}</span>`).join('');
        html += '</div>';
      }
      html += '</div>';
    }

    // 涨停行业分布（旧格式兼容）
    if (data.review?.limit_pool_industries) {
      html += '<div class="subsection"><h3>🏭 涨停行业分布</h3><div class="index-row">';
      html += data.review.limit_pool_industries.slice(0,6).map(i =>
        `<span class="index-item">${i.industry} <b>${i.limit_up_count}</b>家</span>`
      ).join('');
      html += '</div></div>';
    }

    // 收盘总评证据
    if (data.review?.evidence?.length) {
      html += '<div class="subsection"><h3>🧾 总评证据</h3><div class="evidence-list">';
      html += data.review.evidence.map(e => `<div class="evidence-line">${escapeHtml(typeof e === "string" ? e : `${e.label || e.name || "证据"}：${e.detail || e.text || e.value || ""}`)}</div>`).join('');
      html += '</div></div>';
    }

    // 主线研判
    if (data.hotspots) {
      html += '<div class="subsection"><h3>🔥 主线研判</h3>';
      html += data.hotspots.map(h => {
        const cls = (h.status||'').includes('强') ? 'strong-theme' : (h.status||'').includes('潮') ? 'sentiment' : '';
        // 新格式：stocks数组（含name/pct）；旧格式：representatives/continuity
        let detail = '';
        if (h.stocks && h.stocks.length) {
          detail = h.stocks.slice(0,8).map(s => {
            if (typeof s === "string") {
              return `<span style="font-size:11px;margin-right:8px">${escapeHtml(s)}</span>`;
            }
            const pct = s.pct ?? s.change_pct;
            if (pct === undefined) {
              return `<span style="font-size:11px;margin-right:8px">${escapeHtml(s.name || s.symbol || "未命名")}</span>`;
            }
            const pctCls = pct >= 0 ? 'up' : 'down';
            return `<span style="font-size:11px;margin-right:8px">${escapeHtml(s.name || s.symbol || "未命名")} <span class="${pctCls}">${pct > 0 ? '+' : ''}${pct}%</span></span>`;
          }).join('');
        } else {
          const reps = (h.representatives||[]).slice(0,6).join('、');
          detail = (h.count_summary ? `<span style="font-size:12px">${h.count_summary}</span><br>` : '') +
            (reps ? `<span style="font-size:11px;color:#8B949E">代表：${reps}</span>` : '') +
            (h.continuity ? `<br><span style="font-size:11px">${h.continuity}</span>` : '');
        }
        const evidence = h.evidence ? renderEvidenceDetails(h.evidence) : '';
        const riskNote = h.risk ? `<br><span style="font-size:10px;color:#FF6B6B">⚠ ${escapeHtml(h.risk)}</span>` : '';
        return `<div class="theme-item ${cls}">
          <b>${escapeHtml(h.name)}</b> <span class="muted">— ${escapeHtml(h.status || '')}</span>
          ${detail ? `<br>${detail}` : ''}
          ${evidence}
          ${riskNote}
        </div>`;
      }).join('');
      html += '</div>';
    }

    // 强弱股分布（Codex groups 新字段）
    if (data.groups) {
      const g = data.groups;
      html += '<div class="subsection"><h3>📊 强弱分布</h3><div class="index-row" style="flex-wrap:wrap;gap:4px">';
      if (g.up_8_plus_count) html += `<span class="index-item">8%+ <b class="up">${g.up_8_plus_count}</b>家</span>`;
      if (g.up_5_to_8_count) html += `<span class="index-item">5%-8% <b class="up">${g.up_5_to_8_count}</b>家</span>`;
      if (g.down_5_plus_count) html += `<span class="index-item">跌5%+ <b class="down">${g.down_5_plus_count}</b>家</span>`;
      html += '</div></div>';
    }

    // 次日观察
    if (data.next_day_watch) {
      html += '<div class="subsection"><h3>🔮 次日观察</h3><ul class="news-list">';
      html += data.next_day_watch.map(w => `<li>${w}</li>`).join('');
      html += '</ul></div>';
    }

    // 风险
    const risks = data.risk || data.risks;
    if (risks) {
      html += '<div class="subsection"><h3>⚠️ 风险</h3><ul class="news-list risk">';
      if (Array.isArray(risks)) {
        html += risks.map(r => `<li>${typeof r === "string" ? r : r.text}</li>`).join('');
      } else {
        html += `<li>${risks}</li>`;
      }
      html += '</ul></div>';
    }

    el.innerHTML = html;
    return;
  }

  // === 旧格式兼容 ===
  if (data.index) {
    html += '<div class="subsection"><h3>📈 收盘指数</h3><div class="index-row">';
    html += Object.entries(data.index).map(([name, v]) => {
      const label = { shanghai: "上证", shenzhen: "深证", chuangye: "创业板", kechuang: "科创板", hang_seng: "恒生", hstech: "恒生科技" }[name] || name;
      return `<span class="index-item"><b>${label}</b> <span class="${v >= 0 ? 'up' : 'down'}">${v > 0 ? '+' : ''}${v}%</span></span>`;
    }).join("");
    html += '</div></div>';
  }
  if (data.strong_themes) {
    html += '<div class="subsection"><h3>🔥 强主线</h3><div class="theme-list">';
    html += data.strong_themes.map(t => `<div class="theme-item strong-theme"><b>${t.name}</b>${t.reason?`<span class="muted"> — ${t.reason}</span>`:''}</div>`).join('');
    html += '</div></div>';
  }
  if (data.watch_themes) {
    html += '<div class="subsection"><h3>👀 观察线</h3><div class="theme-list">';
    html += data.watch_themes.map(t => `<div class="theme-item">${typeof t==="string"?t:t.name}</div>`).join('');
    html += '</div></div>';
  }
  if (data.risks) {
    html += '<div class="subsection"><h3>⚠️ 风险提示</h3><ul class="news-list risk">';
    html += data.risks.map(r => `<li>${typeof r==="string"?r:r.text||r.desc}</li>`).join('');
    html += '</ul></div>';
  }

  el.innerHTML = html || '<div class="empty">盘后数据待更新</div>';
}

function renderPostmarketDecision(data) {
  const hotspots = Array.isArray(data.hotspots) ? data.hotspots : [];
  const strong = hotspots.find(h => /强/.test(h.status || "")) || hotspots[0];
  const riskLine = hotspots.find(h => /风险|弱|退潮/.test([h.status, h.risk, h.continuity].join(" ")));
  const patch = data.closing_auction_patch || {};
  const watch = data.next_day_watch || patch.watch_next_day || [];
  const reviewText = data.review?.summary || data.review?.one_sentence || data.index?.summary || "";
  const mb = data.index?.market_breadth || {};
  const limitUp = mb.limit_up ?? data.index?.["涨停"];
  const limitDown = mb.limit_down ?? data.index?.["跌停"];
  const broken = mb.broken_board ?? data.index?.["炸板"];
  const tone = /负反馈|不支持|风险|分歧/.test([patch.summary, patch.impact, reviewText].join(" ")) ? "warn" : /强|支持|扩散/.test([patch.summary, patch.impact, reviewText].join(" ")) ? "good" : "neutral";
  const relatedTags = positiveRelatedTopicTags(hotspots.map(h => [trendName(h), h.status, h.continuity, h.risk].join(" ")).join(" "), reviewText, patch.summary, patch.impact);

  return `<div class="decision-strip postmarket-decision">
    <div class="decision-card primary">
      <span class="decision-label">核心结论</span>
      <b>${escapeHtml(strong ? themeDisplayName(strong) : "等待主线确认")}</b>
      <span>${escapeHtml(strong?.status || reviewText || "暂无")}</span>
    </div>
    <div class="decision-card ${tone}">
      <span class="decision-label">关联题材</span>
      <b>${escapeHtml(relatedTags[0] || (patch.impact ? "尾盘已校验" : "待校验"))}</b>
      <span>${escapeHtml(relatedTags.slice(1).join(" / ") || truncateText(patch.summary || patch.impact || reviewText, 62))}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">回避/降级</span>
      <b>${escapeHtml(riskLine ? themeDisplayName(riskLine) : "暂无明确风险线")}</b>
      <span>${escapeHtml(truncateText(riskLine?.risk || "看炸板/跌停是否继续扩大", 62))}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">下一步验证</span>
      <b>${escapeHtml(watch.length ? `看${Math.min(watch.length, 3)}个条件` : "等待确认")}</b>
      <span>${escapeHtml(truncateText(watch.slice(0, 2).join("；") || `涨停${limitUp || "-"} / 跌停${limitDown || "-"} / 炸板${broken || "-"}`, 62))}</span>
    </div>
  </div>`;
}

/* =========================
   晚间舆情
========================= */
function renderEvening(data) {
  updatePanelMeta("evening", data.timestamp);
  const el = document.getElementById("evening");

  let html = "";
  const news = data.news || [];
  const p0Alerts = data.p0_alerts || [];
  const filteredNews = news.filter(item => !isCoveredByP0(item, p0Alerts));
  const summary = data.sentiment_summary || {};
  const counts = sentimentCounts(filteredNews, summary.counts || {});
  html += renderEveningDecision(data, filteredNews, p0Alerts, counts);

  if (summary.headline || summary.overall) {
    html += `<div class="sentiment-brief">
      <div class="sentiment-title">
        <span class="badge sentiment-overall">${escapeHtml(summary.overall || "待判断")}</span>
        <b>${escapeHtml(summary.headline || "晚间舆情待研判")}</b>
      </div>
      <div class="sentiment-counts">
        <span class="sentiment-pill positive">正面 ${counts["正面"] || 0}</span>
        <span class="sentiment-pill negative">负面 ${counts["负面"] || 0}</span>
        <span class="sentiment-pill neutral">中性 ${counts["中性"] || 0}</span>
      </div>
    </div>`;
  }

  const groups = [
    ["正面", "偏正面", "positive"],
    ["负面", "偏负面", "negative"],
    ["中性", "中性 / 待验证", "neutral"]
  ];

  if (p0Alerts.length) {
    html += '<div class="p0-alerts"><h3>🚨 晚间 P0</h3>';
    html += p0Alerts.map(renderP0Alert).join('');
    html += '</div>';
  }

  if (filteredNews.length) {
    html += '<div class="sentiment-grid">';
    html += groups.map(([key, title, cls]) => {
      const items = filteredNews.filter(n => (typeof n === "string" ? "中性" : n.sentiment || "中性") === key);
      const first = items.slice(0, 1).map(renderEveningItem).join("");
      const rest = items.slice(1).map(renderEveningItem).join("");
      return `<div class="sentiment-col ${cls}">
        <h3>${title}</h3>
        ${items.length ? first + (rest ? `<details class="compact-details"><summary>展开更多 ${items.length - 1} 条</summary>${rest}</details>` : "") : '<div class="empty-sm">暂无</div>'}
      </div>`;
    }).join("");
    html += '</div>';
  }

  el.innerHTML = html || '<div class="empty">晚间舆情待更新</div>';
}

function sentimentCounts(news, fallback) {
  if (!news.length && fallback) return fallback;
  return news.reduce((acc, item) => {
    const key = typeof item === "string" ? "中性" : item.sentiment || "中性";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, { "正面": 0, "负面": 0, "中性": 0 });
}

function isCoveredByP0(newsItem, p0Alerts) {
  if (!p0Alerts.length) return false;
  const fields = eveningDedupeFields(newsItem).filter(v => normalizeEveningText(v).length >= 2);
  if (!fields.length) return false;
  return p0Alerts.some(alert => {
    const haystack = normalizeEveningText(eveningDedupeFields(alert).join(" "));
    return fields.some(field => {
      const needle = normalizeEveningText(field);
      if (!needle) return false;
      return haystack.includes(needle) ||
        (needle.length >= 10 && haystack.includes(needle.slice(0, 10))) ||
        (needle.length >= 16 && haystack.includes(needle.slice(0, 16))) ||
        hasEveningTextOverlap(needle, haystack);
    });
  });
}

function hasEveningTextOverlap(needle, haystack) {
  if (needle.length < 12) return haystack.includes(needle);
  const grams = new Set();
  for (let i = 0; i <= needle.length - 4; i += 2) {
    const gram = needle.slice(i, i + 4);
    if (!/^\d+$/.test(gram)) grams.add(gram);
  }
  if (!grams.size) return false;
  let hits = 0;
  grams.forEach(gram => {
    if (haystack.includes(gram)) hits += 1;
  });
  return hits >= 3 || hits / grams.size >= 0.35;
}

function eveningDedupeFields(item) {
  if (typeof item === "string") return [item];
  const evidence = Array.isArray(item.evidence)
    ? item.evidence.map(e => typeof e === "string" ? e : e.detail || e.text || e.source || "").join(" ")
    : "";
  return [
    item.title,
    item.text,
    item.stock,
    item.tag,
    item.why_p0,
    item.impact,
    item.mapping,
    evidence
  ].filter(Boolean);
}

function normalizeEveningText(value) {
  return String(value || "")
    .replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, "")
    .toLowerCase();
}

function renderEveningItem(item) {
  if (typeof item === "string") {
    return `<div class="sentiment-item neutral"><div class="sentiment-text">${escapeHtml(item)}</div></div>`;
  }
  const sentiment = item.sentiment || "中性";
  const cls = sentiment === "正面" ? "positive" : sentiment === "负面" ? "negative" : "neutral";
  const title = item.stock ? `${item.stock} · ${item.tag || "公告"}` : (item.tag || "舆情");
  const source = item.source ? `<span class="muted">${escapeHtml(item.source)}</span>` : "";
  const takeaway = item.takeaway || item.impact || "";
  const evidence = item.evidence ? renderEvidenceDetails(item.evidence) : "";
  const verify = item.verify_next_day ? `<div class="sentiment-verify">验证：${formatEvidenceList(item.verify_next_day)}</div>` : "";
  return `<div class="sentiment-item ${cls}">
    <div class="sentiment-item-head">
      <span class="tag">${escapeHtml(title)}</span>
      ${source}
    </div>
    <div class="sentiment-text">${escapeHtml(item.text || item.title || "")}</div>
    ${takeaway ? `<div class="sentiment-takeaway">${escapeHtml(takeaway)}</div>` : ""}
    ${evidence}
    ${verify}
  </div>`;
}

function renderP0Alert(item) {
  const severity = item.severity || "P0";
  const title = item.title || item.text || "晚间 P0";
  const why = item.why_p0 || item.impact || "";
  const evidence = item.evidence ? renderEvidenceDetails(item.evidence) : "";
  const watch = item.watch_next_day ? `<div class="sentiment-verify">次日观察：${formatEvidenceList(item.watch_next_day)}</div>` : "";
  return `<div class="sentiment-item p0">
    <div class="sentiment-item-head">
      <span class="tag">${escapeHtml(severity)}</span>
      ${item.source ? `<span class="muted">${escapeHtml(item.source)}</span>` : ""}
    </div>
    <div class="sentiment-text"><b>${escapeHtml(title)}</b></div>
    ${why ? `<div class="sentiment-takeaway">${escapeHtml(why)}</div>` : ""}
    ${evidence}
    ${watch}
  </div>`;
}

function renderEveningDecision(data, news, p0Alerts, counts) {
  const topP0 = p0Alerts[0];
  const riskP0 = p0Alerts.find(item => /风险|压制|下线|减持|弱|监管/.test([item.title, item.why_p0].join(" "))) || topP0;
  const positive = counts["正面"] || 0;
  const negative = counts["负面"] || 0;
  const neutral = counts["中性"] || 0;
  const overall = data.sentiment_summary?.overall || (p0Alerts.length ? "P0优先" : positive > negative ? "偏正面" : negative > positive ? "偏负面" : "中性");
  const watch = topP0?.watch_next_day || news.find(n => Array.isArray(n.verify_next_day))?.verify_next_day || [];
  const tone = /负|风险|P0|警惕/.test(overall) || p0Alerts.length ? "warn" : /正/.test(overall) ? "good" : "neutral";
  const relatedTags = positiveRelatedTopicTags(p0Alerts.map(p => [p.title, p.why_p0].join(" ")).join(" "), news.map(n => [n.title, n.text, n.tag].join(" ")).join(" "));
  return `<div class="decision-strip evening-decision">
    <div class="decision-card ${tone}">
      <span class="decision-label">核心结论</span>
      <b>${escapeHtml(overall)}</b>
      <span>P0 ${p0Alerts.length} / 正${positive} 负${negative} 中${neutral}</span>
    </div>
    <div class="decision-card primary">
      <span class="decision-label">关联题材</span>
      <b>${escapeHtml(relatedTags[0] || truncateText(topP0?.title || "暂无P0", 24))}</b>
      <span>${escapeHtml(relatedTags.slice(1).join(" / ") || truncateText(topP0?.why_p0 || "等待晚间新增舆情", 62))}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">回避/降级</span>
      <b>${escapeHtml(truncateText(riskP0?.title || "暂无明确风险", 24))}</b>
      <span>${escapeHtml(truncateText(riskP0?.why_p0 || "看核心观察池是否批量高低开", 62))}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">下一步验证</span>
      <b>${escapeHtml(watch.length ? `看${Math.min(watch.length, 3)}个信号` : "等待验证")}</b>
      <span>${escapeHtml(truncateText(watch.slice(0, 2).join("；") || "看9:25竞价、核心池高低开和风格切换", 62))}</span>
    </div>
  </div>`;
}

function renderEvidenceDetails(value) {
  const count = Array.isArray(value) ? value.length : 1;
  const summary = Array.isArray(value) && value.length
    ? summarizeEvidence(value[0])
    : summarizeEvidence(value);
  return `<details class="evidence-details">
    <summary>证据 ${count} 条${summary ? ` · ${escapeHtml(summary)}` : ""}</summary>
    <div class="evidence-line">${formatEvidenceList(value)}</div>
  </details>`;
}

function summarizeEvidence(value) {
  if (!value) return "";
  if (typeof value === "object") return truncateText(value.detail || value.text || value.value || value.source || "", 42);
  const raw = String(value);
  if (raw.includes("近5日涨停池对照")) return "近5日涨停池对照";
  return truncateText(raw, 42);
}

function formatEvidenceList(value) {
  if (Array.isArray(value)) {
    return value.map(v => {
      if (typeof v === "string") {
        return formatEvidenceString(v);
      }
      return escapeHtml(`${v.label || v.name || v.title || "\u8bc1\u636e"}\uff1a${v.detail || v.text || v.value || v.source || ""}`);
    }).join('<br>');
  }
  if (value && typeof value === "object") {
    return escapeHtml(`${value.label || value.name || value.title || "证据"}：${value.detail || value.text || value.value || value.source || ""}`);
  }
  return escapeHtml(value || "");
}

function formatEvidenceString(text) {
  const raw = String(text || "");
  if (raw.includes("近5日涨停池对照") && raw.includes("[{")) {
    const prefix = raw.split("[{")[0].replace(/[:：]\s*$/, "");
    const rows = parseLimitHistory(raw);
    if (rows.length) {
      return `<div>${escapeHtml(prefix)}</div><div class="history-table">${rows.map(row => {
        const industries = Object.entries(row.top_industries || {})
          .slice(0, 4)
          .map(([name, count]) => `${name}${count}`)
          .join(" / ");
        return `<div class="history-row"><span>${formatCompactDate(row.date)}</span><b>${row.limit_up_count || "--"}家</b><span>${escapeHtml(industries)}</span></div>`;
      }).join("")}</div>`;
    }
  }
  if (raw.length > 260 && (raw.includes("[{") || raw.includes("{'"))) {
    return escapeHtml(raw.substring(0, 160) + "...");
  }
  return escapeHtml(raw);
}

function parseLimitHistory(text) {
  try {
    const start = text.indexOf("[{");
    if (start < 0) return [];
    const jsonish = text.slice(start)
      .replace(/'/g, '"')
      .replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:/g, '$1"$2":');
    const parsed = JSON.parse(jsonish);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

function formatCompactDate(value) {
  const s = String(value || "");
  if (/^\d{8}$/.test(s)) return `${s.slice(4, 6)}-${s.slice(6, 8)}`;
  return escapeHtml(s);
}

/* =========================
   专题跟踪
========================= */
function renderTopics(data) {
  updatePanelMeta("topics", data.timestamp);
  const el = document.getElementById("topics");
  const topics = data.topics || [];
  if (!topics.length) { el.innerHTML = '<div class="empty">暂无专题跟踪</div>'; return; }

  const visible = pickVisibleTopics(topics);
  const hidden = topics.filter(t => !visible.includes(t));
  el.innerHTML = renderTopicsDecision(topics) + '<div class="grid">' + visible.map(t => renderTopicCard(t, data.timestamp)).join("") + '</div>' +
    (hidden.length ? `<details class="compact-details topics-all"><summary>展开全部专题（${topics.length}）</summary><div class="grid">${hidden.map(t => renderTopicCard(t, data.timestamp)).join("")}</div></details>` : "");
}

function renderTopicCard(t, fallbackTimestamp) {
    const statusText = String(t.status || "");
    const statusCls = statusText.includes("强化") || statusText.includes("强主线") ? "strong" :
                      statusText.includes("弱化") || statusText.includes("退潮") || statusText.includes("风险") ? "sentiment" : "";
    const statusBadge = statusCls === "strong" ? "🔥" :
                        statusCls === "sentiment" ? "🔻" : "➖";
    const updatedAt = formatUpdateTime(t.updated_at || t.timestamp || fallbackTimestamp);
    const conclusion = t.conclusion || t.core_view || "";
    const related = Array.isArray(t.related_topics) ? t.related_topics : [];
    return `<div class="card ${statusCls}">
      <div class="card-head"><b>${t.name}</b></div>
      ${updatedAt ? `<div class="card-updated"><span class="updated-dot"></span>已更新 · ${updatedAt}</div>` : ""}
      <div class="card-body">${statusBadge} ${escapeHtml(t.status || "观察")}</div>
      ${conclusion ? `<div class="topic-conclusion">${escapeHtml(conclusion)}</div>` : ""}
      ${related.length ? `<div class="topic-related">${related.slice(0, 6).map(v => `<span>${escapeHtml(v)}</span>`).join("")}</div>` : ""}
      ${t.action ? `<div class="card-body">${escapeHtml(truncateText(t.action, 92))}</div>` : ""}
      ${t.note ? `<details class="alert-detail"><summary>更新依据</summary><div>${escapeHtml(t.note)}</div></details>` : ""}
    </div>`;
}

function pickVisibleTopics(topics) {
  const integrated = topics.filter(t => t.display === "integrated" || t.level === "母题材");
  if (integrated.length) return integrated.slice(0, 4);
  const focus = topics.find(t => /强化|强|观察|博弈/.test([t.status, t.action].join(" ")) && !/风险|弱|降级|回避/.test([t.status, t.action, t.note].join(" "))) || topics[0];
  const risk = topics.find(t => /风险|弱|降级|回避/.test([t.status, t.action, t.note].join(" ")));
  const pending = topics.find(t => t !== focus && t !== risk && /观察|待|验证/.test([t.status, t.action, t.note].join(" ")));
  const seen = new Set();
  return [focus, risk, pending].filter(Boolean).filter(t => {
    const key = t.name || JSON.stringify(t);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderTopicsDecision(topics) {
  const integrated = topics.filter(t => t.display === "integrated" || t.level === "母题材");
  const decisionTopics = integrated.length ? integrated : topics;
  const riskTopics = decisionTopics.filter(t => /风险|弱|降级|回避/.test([t.status, t.action, t.note].join(" ")));
  const activeTopics = decisionTopics.filter(t => /强化|强|观察|博弈|择强|监控/.test([t.status, t.action].join(" ")) && !riskTopics.includes(t));
  const focus = activeTopics[0] || decisionTopics[0];
  const risk = riskTopics[0];
  const updatedCount = topics.length;
  const watchText = focus?.conclusion || focus?.action || "等待专题更新";
  return `<div class="decision-strip topics-decision">
    <div class="decision-card primary">
      <span class="decision-label">7月主线焦点</span>
      <b>${escapeHtml(focus?.name || "暂无")}</b>
      <span>${escapeHtml(focus?.status || "观察")}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">有意义的结论</span>
      <b>${escapeHtml(truncateText(focus?.conclusion || focus?.action || "等待盘面确认", 30))}</b>
      <span>${escapeHtml(truncateText(watchText, 62))}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">回避/降级</span>
      <b>${escapeHtml(risk?.name || "暂无明确风险")}</b>
      <span>${escapeHtml(truncateText(risk?.action || risk?.note || "继续观察是否扩散", 62))}</span>
    </div>
    <div class="decision-card neutral">
      <span class="decision-label">关联题材</span>
      <b>${integrated.length || updatedCount} 组</b>
      <span>${escapeHtml(decisionTopics.slice(0, 3).map(t => t.name).join(" / "))}</span>
    </div>
  </div>`;
}

/* =========================
   需求板块
========================= */
function renderRequirements(data) {
  updatePanelMeta("requirements", data.timestamp);
  const el = document.getElementById("requirements");
  if (!el) return;
  const items = data.requirements || [];
  if (!items.length) {
    el.innerHTML = '<div class="empty">暂无需求</div>';
    return;
  }

  const summary = data.summary ? `<div class="breadth">${escapeHtml(data.summary)}</div>` : "";
  const cards = items.map(item => {
    const priorityCls = item.priority === "P0" ? "p0" : item.priority === "P1" ? "p1" : "p2";
    const scope = (item.scope || []).map(v => `<span class="tag">${escapeHtml(v)}</span>`).join("");
    const acceptance = (item.acceptance || []).map(v => `<li>${escapeHtml(v)}</li>`).join("");
    const links = (item.links || []).map(v => `<span class="muted">${escapeHtml(v)}</span>`).join(" · ");
    return `<div class="requirement-card ${priorityCls}">
      <div class="requirement-head">
        <span class="badge ${priorityCls === "p0" ? "risk" : "watch"}">${escapeHtml(item.priority || "P2")}</span>
        <b>${escapeHtml(item.title || item.id || "未命名需求")}</b>
        <span class="requirement-status">${escapeHtml(item.status || "待处理")}</span>
      </div>
      <div class="card-body muted">${escapeHtml(item.id || "")} · ${escapeHtml(item.owner || "")}</div>
      ${scope ? `<div class="tag-row">${scope}</div>` : ""}
      ${acceptance ? `<ul class="requirement-list">${acceptance}</ul>` : ""}
      ${links ? `<div class="requirement-links">${links}</div>` : ""}
    </div>`;
  }).join("");

  el.innerHTML = summary + `<div class="requirements-grid">${cards}</div>`;
}

/* =========================
   数据源健康
========================= */
function renderSourceHealth(data) {
  updatePanelMeta("source-health", data.timestamp);
  const el = document.getElementById("source-health");
  if (!el) return;
  const sources = Array.isArray(data.sources)
    ? data.sources
    : Object.entries(data.sources || {}).map(([id, source]) => ({ id, ...(source || {}) }));
  const rules = data.rules || [];
  const sourceCards = sources.map(source => {
    const status = source.status || "unknown";
    const cls = status === "ok" ? "ok" : status === "degraded" ? "warn" : "bad";
    const label = status === "ok" ? "正常" : status === "degraded" ? "降级" : "异常";
    const cadence = source.cadence ? `<div class="source-meta">频率：${escapeHtml(source.cadence)}</div>` : "";
    const note = source.note ? `<div class="source-note">${escapeHtml(source.note)}</div>` : "";
    return `<div class="source-card ${cls}">
      <div class="source-head">
        <b>${escapeHtml(source.name || source.id || "未命名数据源")}</b>
        <span class="source-status">${label}</span>
      </div>
      <div class="source-meta">${escapeHtml(source.role || source.usage || source.detail || "")}</div>
      ${cadence}
      ${note}
    </div>`;
  }).join("");
  const ruleList = rules.length ? `<div class="subsection"><h3>执行原则</h3>${renderBulletList(rules, "news-list")}</div>` : "";
  el.innerHTML = `
    <div class="source-grid">${sourceCards || '<div class="empty">数据源状态待更新</div>'}</div>
    ${ruleList}
  `;
}

/* =========================
   时间 / 状态
========================= */
function updateTime() {
  document.getElementById("status").innerText = navigator.onLine ? "🟢 LIVE" : "🔴 OFFLINE";
}

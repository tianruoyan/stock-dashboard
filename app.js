const FILES = [
  "data/alert.json",
  "data/intraday.json",
  "data/premarket.json",
  "data/midday.json",
  "data/postmarket.json",
  "data/evening-sentiment.json",
  "data/topics.json",
  "data/quality-report.json",
  "data/data-trust.json",
  "data/monitoring-coverage.json",
  "data/decision-feed.json",
  "data/theme-shifts.json",
  "data/automation-health.json",
  "data/signal-review.json",
  "config/watchlist.json",
  "config/alert-config.json",
  "data/requirements.json",
  "data/source-health.json",
  "data/section-health.json"
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
      if (file.includes("signal-review") || file.includes("quality-report") || file.includes("data-trust") || file.includes("monitoring-coverage") || file.includes("decision-feed") || file.includes("theme-shifts") || file.includes("automation-health") || file.includes("section-health")) {
        cache[file] = null;
        if (file.includes("signal-review")) renderSignalReview(null);
        if (file.includes("quality-report")) renderDataQualityGate();
        if (file.includes("data-trust")) renderDataQualityGate();
        if (file.includes("monitoring-coverage")) renderDataQualityGate();
        if (file.includes("decision-feed")) renderOpportunityRiskRadar();
        if (file.includes("theme-shifts")) renderOpportunityRiskRadar();
        if (file.includes("automation-health")) renderDataQualityGate();
        if (file.includes("section-health")) renderDataQualityGate();
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
  else if (file === "data/quality-report.json") renderDataQualityGate();
  else if (file === "data/data-trust.json") {
    renderDataQualityGate();
    rerenderAlertsIfLoaded();
  }
  else if (file === "data/monitoring-coverage.json") {
    renderDataQualityGate();
    rerenderAlertsIfLoaded();
  }
  else if (file === "data/decision-feed.json") renderOpportunityRiskRadar();
  else if (file === "data/theme-shifts.json") renderOpportunityRiskRadar();
  else if (file === "data/automation-health.json") renderDataQualityGate();
  else if (file === "data/signal-review.json") renderSignalReview(data);
  else if (file === "config/watchlist.json") renderWatchlistDecision();
  else if (file === "config/alert-config.json") renderPortfolioRisk();
  else if (file === "data/requirements.json") renderRequirements(data);
  else if (file === "data/source-health.json") renderSourceHealth(data);
  else if (file === "data/section-health.json") {
    renderDataQualityGate();
    renderSectionHealthBadges();
  }
}

function rerenderAlertsIfLoaded() {
  const alertData = cached("data/alert.json");
  if (alertData) renderAlerts(alertData);
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

function hasMojibake(value) {
  return /[�ÃÂ]|(?:æ|å|ç|è|é)[A-Za-z0-9_\- ]{0,8}/.test(String(value ?? ""));
}

function userFacingText(value) {
  let text = String(value ?? "");
  if (!text) return "";
  text = text
    .replace(/\bths_sina_or_akshare_quote_decode\b/g, "A股行情源")
    .replace(/\btencent_hk_http\b/g, "港股腾讯报价")
    .replace(/\beastmoney_hk_akshare\b/g, "港股东方财富/akshare")
    .replace(/\bofficial_policy_global_web_scan\b/g, "政策与全球事件扫描")
    .replace(/\bsource-health\.json\b/g, "数据源健康")
    .replace(/\bquality-report\.json\b/g, "质量报告")
    .replace(/\bdata-trust\.json\b/g, "文件可信度");
  if (/Can not decode value starting with|JSON decode failed|proxy disconnect|decode failed|failed with/i.test(text)) {
    if (/hk|港股|Eastmoney|stock_hk/i.test(text)) {
      return "港股行情源连接/解码异常，港股与日韩映射需人工复核。";
    }
    if (/japan|korea|nikkei|kospi|日韩|日经|韩国/i.test(text)) {
      return "日韩早盘实时源异常，页面仅保留待复核清单，不展示未核实数值。";
    }
    return "行情源解码异常，相关行情与异动信号需二次复核。";
  }
  return text;
}

function userFacingList(items) {
  return (items || []).map(userFacingText).filter(Boolean);
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
  renderSectionHealthBadges();
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
  const decisionGate = dashboardDecisionGate();
  let style = inferMarketStyle(intraday, postmarket, evening);
  if (decisionGate) {
    style = { title: decisionGate.title, cls: decisionGate.cls, reason: decisionGate.reason };
  }
  const position = inferPositionRange(style, riskConfig);
  const latest = dashboardEffectiveTimestamp() || latestTimestamp([intraday, postmarket, alert]);
  const trustGate = dashboardTrustGate();
  let priority = strong.slice(0, 3).map(themeDisplayName);
  let avoid = risks.slice(0, 3).map(themeDisplayName);
  if (decisionGate?.riskFirst) {
    priority = ["风险优先", "只做验证", "暂停追高"];
    avoid = decisionGate.avoid.length ? decisionGate.avoid : ["全市场亏钱效应", "数据质量降级", "污染异动未重产"];
  }
  const relatedTags = positiveRelatedTopicTags(priority.join(" "), avoid.join(" "), alertStocks.join(" "), p0.map(p => p.title || p.text || "").join(" "));

  el.innerHTML = `<div class="control-hero ${style.cls}">
    <div>
      <div class="control-eyebrow">核心结论</div>
      <div class="control-title">${escapeHtml(style.title)}</div>
      <div class="control-sub">${escapeHtml(style.reason)}</div>
      <div class="control-meta">有效时间：${escapeHtml(latest ? formatUpdateTime(latest) : "待更新")} · ${escapeHtml(dataFreshness(latest))}</div>
      ${trustGate ? `<div class="control-data-gate ${escapeHtml(trustGate.cls)}">${trustGate.items.map(item => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    </div>
    <div class="control-position">
      <span>建议仓位</span>
      <b>${escapeHtml(position.range)}</b>
      <em>${escapeHtml(position.note)}</em>
    </div>
  </div>
  <div class="decision-strip control-strip">
    <div class="decision-card ${decisionGate?.riskFirst ? "risk" : "primary"}"><span class="decision-label">优先方向</span><b>${escapeHtml(priority[0] || "等待确认")}</b><span>${escapeHtml(priority.slice(1).join(" / ") || "没有共振前不抢")}</span></div>
    <div class="decision-card action"><span class="decision-label">关联题材</span><b>${escapeHtml(decisionGate?.riskFirst ? "候选只验证" : (relatedTags[0] || "等待映射"))}</b><span>${escapeHtml(decisionGate?.riskFirst ? "有承接、有扩散、数据恢复后再升级" : (relatedTags.slice(1).join(" / ") || "按母题材合并观察"))}</span></div>
    <div class="decision-card ${decisionGate?.riskFirst ? "neutral" : "primary"}"><span class="decision-label">进攻盯 · ${escapeHtml(decisionGate?.riskFirst ? "暂停" : attackCandidate.source)}</span><b>${escapeHtml(decisionGate?.riskFirst ? "暂无可用机会" : (attackWatch[0] || "暂无"))}</b><span>${escapeHtml(decisionGate?.riskFirst ? "只看验证条件，不做追高触发" : (attackWatch.slice(1).join(" / ") || attackCandidate.note))}</span></div>
    <div class="decision-card risk"><span class="decision-label">风险盯 · ${escapeHtml(riskCandidate.source)}</span><b>${escapeHtml(riskWatch[0] || "暂无")}</b><span>${escapeHtml(riskWatch.slice(1).join(" / ") || riskCandidate.note)}</span></div>
    <div class="decision-card risk"><span class="decision-label">回避/降级</span><b>${escapeHtml(avoid[0] || "暂无明确")}</b><span>${escapeHtml(avoid.slice(1).join(" / ") || eventWatch[0] || "看弱线和P0是否扩散")}</span></div>
  </div>`;
}

function dashboardTrustGate() {
  const trust = cached("data/data-trust.json");
  if (!trust || !Array.isArray(trust.files) || trust.current_signal_date !== currentSignalDate()) return null;
  const items = [];
  for (const file of trust.files) {
    if (["invalidated", "missing"].includes(file.status)) {
      items.push(`${file.label}不可用`);
      continue;
    }
    if (file.freshness_status === "future") {
      items.push(`${file.label}超前`);
      continue;
    }
    if (file.session_relevance === "current" && file.freshness_status === "stale") {
      items.push(`${file.label}超时`);
      continue;
    }
    if (file.session_relevance === "current" && file.freshness_status === "aging") {
      items.push(`${file.label}临近超时`);
      continue;
    }
    if (file.session_relevance === "current" && file.status === "degraded") {
      items.push(`${file.label}降权`);
    }
  }
  if (!items.length) return null;
  return {
    cls: items.some(item => /不可用|超时|超前/.test(item)) ? "risk" : "warn",
    items: uniqueList(items).slice(0, 4)
  };
}

function dashboardEffectiveTimestamp() {
  const trust = cached("data/data-trust.json");
  if (!trust || !Array.isArray(trust.files) || trust.current_signal_date !== currentSignalDate()) return "";
  const usable = trust.files
    .filter(file => file && file.timestamp)
    .filter(file => !["invalidated", "missing", "stale"].includes(file.status))
    .filter(file => ["current", "background"].includes(file.session_relevance))
    .filter(file => !["blocked", "unknown", "phase_expired", "future"].includes(file.freshness_status));
  return latestTimestamp(usable.map(file => ({ timestamp: file.timestamp })));
}

function dashboardDecisionGate() {
  const feed = currentDecisionFeed();
  if (!feed) return null;
  const opportunities = (feed.opportunities || []).map(item => decisionFeedToRadarItem(item, "good"));
  const actionable = opportunities.filter(isActionableOpportunity);
  const downgraded = opportunities.filter(item => !isActionableOpportunity(item));
  const risks = (feed.risks || []).filter(item => ["A", "B"].includes(String(item.signal_grade || "").toUpperCase()));
  const riskFirstConflicts = (feed.conflicts || []).filter(item => item.severity === "risk_first");
  if (riskFirstConflicts.length) {
    const focus = riskFirstConflicts[0];
    return {
      riskFirst: true,
      cls: "warn",
      title: "主线冲突，风险优先",
      reason: `${focus.theme || "关键主线"}：${focus.verdict || "风险优先，只做验证"}。${focus.action || "先按风险栏处理，满足验证条件后再升级。"}`,
      avoid: uniqueList([
        ...riskFirstConflicts.map(item => item.theme).filter(Boolean),
        ...risks.slice(0, 3).map(item => item.title).filter(Boolean),
        "数据质量降级"
      ])
    };
  }
  if (!actionable.length && downgraded.length) {
    return {
      riskFirst: true,
      cls: "warn",
      title: "无可用机会，风险优先",
      reason: `当前 ${downgraded.length} 条机会均为降权/仅复核；只做验证，不直接追高。${risks.length ? `A/B级风险 ${risks.length} 条优先处理。` : ""}`,
      avoid: uniqueList([
        ...risks.slice(0, 3).map(item => item.title).filter(Boolean),
        "数据质量降级"
      ])
    };
  }
  if (/degraded|critical|blocked|invalidated/.test(String(feed.quality_gate?.status || ""))) {
    return {
      riskFirst: false,
      cls: "warn",
      title: "数据降级，机会降权",
      reason: feed.quality_gate?.summary || "核心数据需复核，机会只能按验证条件升级。",
      avoid: []
    };
  }
  return null;
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
      label: "交易影响",
      title: report.impactTitle || "无阻断",
      detail: report.impactDetail || "无交易阻断",
      cls: report.impactCls || "good"
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
      detail: userFacingList(report.degraded).slice(0, 2).join(" / ") || "核心行情源正常",
      cls: report.degraded.length ? "warn" : "good"
    },
    {
      label: "区块健康",
      title: report.sectionTitle || "待接入",
      detail: report.sectionDetail || "区块级健康矩阵待生成",
      cls: report.sectionCls || "neutral"
    },
    {
      label: "文件可信",
      title: report.fileTrustTitle || "待接入",
      detail: report.fileTrustDetail || "数据文件可信度待生成",
      cls: report.fileTrustCls || "neutral"
    },
    {
      label: "监测盲区",
      title: report.coverageTitle || "待接入",
      detail: report.coverageDetail || "监测盲区待生成",
      cls: report.coverageCls || "neutral"
    },
    {
      label: "自动化心跳",
      title: report.automationTitle || "待接入",
      detail: report.automationDetail || "产出心跳待生成",
      cls: report.automationCls || "neutral"
    }
  ];
  el.innerHTML = `<div class="decision-strip quality-strip">${cards.map(card => `
    <div class="decision-card ${card.cls}">
      <span class="decision-label">${escapeHtml(card.label)}</span>
      <b>${escapeHtml(card.title)}</b>
      <span>${escapeHtml(userFacingText(card.detail))}</span>
    </div>`).join("")}</div>
    ${report.impactBadges?.length ? `<div class="quality-impact-row">${report.impactBadges.map(item => `<span class="${escapeHtml(item.cls)}">${escapeHtml(item.text)}</span>`).join("")}</div>` : ""}
    ${report.actionPlan?.length ? `<div class="quality-action-plan">${report.actionPlan.slice(0, 3).map(item => `
      <div>
        <span>${escapeHtml(item.label || "处置")}</span>
        <b>${escapeHtml(item.file || "unknown")}：${escapeHtml(userFacingText(item.next_step || item.decision_action || ""))}</b>
        <em>${escapeHtml(userFacingText(item.unblock_condition || ""))}</em>
      </div>`).join("")}</div>` : ""}
    ${report.issues.length ? `<div class="quality-issues">${userFacingList(report.issues).slice(0, 4).map(item => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}`;
}

function buildDataQualityReport() {
  const audited = cached("data/quality-report.json");
  const sectionHealth = cached("data/section-health.json");
  const dataTrust = cached("data/data-trust.json");
  const coverage = cached("data/monitoring-coverage.json");
  const automation = cached("data/automation-health.json");
  if (audited?.status && audited.current_signal_date === currentSignalDate()) {
    const latest = latestTimestamp([
      cached("data/intraday.json"),
      cached("data/premarket.json"),
      cached("data/midday.json"),
      cached("data/postmarket.json"),
      cached("data/topics.json"),
      cached("data/alert.json")
    ].filter(Boolean));
    const statusMap = {
      ok: { level: "可用", cls: "good" },
      degraded: { level: "降级可用", cls: "neutral" },
      critical: { level: "谨慎使用", cls: "warn" }
    };
    const mapped = statusMap[audited.status] || statusMap.degraded;
    const issues = (audited.issues || []).map(item => userFacingText(item.message || item.code || "")).filter(Boolean);
    const impactSummary = summarizeQualityImpact(audited.counts || {});
    const degraded = (audited.issues || [])
      .filter(item => item.code === "source_degraded")
      .map(item => userFacingText(item.message || ""))
      .filter(Boolean);
    const sectionSummary = summarizeSectionHealth(sectionHealth);
    const trustSummary = summarizeDataTrust(dataTrust);
    const coverageSummary = summarizeMonitoringCoverage(coverage);
    const automationSummary = summarizeAutomationHealth(automation);
    return {
      level: mapped.level,
      cls: mapped.cls,
      latest,
      degraded,
      issues: [...automationSummary.issues, ...coverageSummary.issues, ...trustSummary.issues, ...sectionSummary.issues, ...issues],
      summary: userFacingText(audited.summary || "数据审计报告已接入"),
      impactTitle: impactSummary.title,
      impactDetail: impactSummary.detail,
      impactCls: impactSummary.cls,
      impactBadges: impactSummary.badges,
      actionPlan: audited.action_plan || [],
      sectionTitle: sectionSummary.title,
      sectionDetail: sectionSummary.detail,
      sectionCls: sectionSummary.cls,
      fileTrustTitle: trustSummary.title,
      fileTrustDetail: trustSummary.detail,
      fileTrustCls: trustSummary.cls,
      coverageTitle: coverageSummary.title,
      coverageDetail: coverageSummary.detail,
      coverageCls: coverageSummary.cls,
      automationTitle: automationSummary.title,
      automationDetail: automationSummary.detail,
      automationCls: automationSummary.cls
    };
  }
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
    .map(([name, src]) => userFacingText(src.usage || src.detail || src.note || name));
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

function summarizeAutomationHealth(report) {
  if (!report || !Array.isArray(report.processes)) {
    return { title: "待接入", detail: "自动化产出心跳待生成", cls: "neutral", issues: [] };
  }
  const bad = report.processes.filter(item => ["missing", "invalidated", "late"].includes(item.status));
  const blocking = bad.filter(item => item.blocking);
  const waiting = report.processes.filter(item => item.status === "waiting");
  const focus = [...blocking, ...bad, ...waiting].slice(0, 4);
  const title = blocking.length
    ? `${blocking.length} 个阻断`
    : (bad.length ? `${bad.length} 个异常` : (waiting.length ? `${waiting.length} 个等待` : "产出正常"));
  const detail = report.summary || (focus.length ? focus.map(item => item.label).join(" / ") : "关键自动化产出均已到位");
  const issues = focus.map(item => {
    const action = Array.isArray(item.next_actions) && item.next_actions.length ? item.next_actions[0] : (item.action || item.status);
    return `${item.label}：${item.failure_type || item.status}，${action}`;
  });
  return {
    title,
    detail: truncateText(detail, 90),
    cls: blocking.length ? "warn" : (bad.length || waiting.length ? "neutral" : "good"),
    issues
  };
}

function summarizeQualityImpact(counts) {
  const blocking = Number(counts.blocking || 0);
  const priceReview = Number(counts.price_review || 0);
  const signalReview = Number(counts.signal_review || 0);
  const backgroundReview = Number(counts.background_review || 0);
  const reviewTotal = priceReview + signalReview;
  const badges = [
    { key: "blocking", label: "交易阻断", count: blocking, cls: blocking ? "risk" : "good" },
    { key: "price", label: "行情复核", count: priceReview, cls: priceReview ? "warn" : "good" },
    { key: "signal", label: "信号复核", count: signalReview, cls: signalReview ? "warn" : "good" },
    { key: "background", label: "背景复核", count: backgroundReview, cls: backgroundReview ? "neutral" : "good" }
  ].map(item => ({ ...item, text: `${item.label} ${item.count}` }));
  if (blocking) {
    return {
      title: `${blocking} 阻断 / ${reviewTotal} 复核`,
      detail: "阻断项不得用于交易触发；行情和信号需二次确认",
      cls: "warn",
      badges
    };
  }
  if (reviewTotal) {
    return {
      title: `${reviewTotal} 项需复核`,
      detail: "结论可看，但行情/信号需确认后升级",
      cls: "neutral",
      badges
    };
  }
  if (backgroundReview) {
    return {
      title: "仅背景复核",
      detail: `${backgroundReview} 项背景覆盖不足，不阻断交易触发`,
      cls: "good",
      badges
    };
  }
  return {
    title: "无阻断",
    detail: "未发现交易阻断或行情复核项",
    cls: "good",
    badges
  };
}

function summarizeMonitoringCoverage(report) {
  if (!report || !Array.isArray(report.blind_spots)) {
    return { title: "待接入", detail: "监测盲区待生成", cls: "neutral", issues: [] };
  }
  const critical = report.blind_spots.filter(item => item.severity === "critical");
  const warning = report.blind_spots.filter(item => item.severity === "warning");
  const info = report.blind_spots.filter(item => item.severity === "info");
  const focus = [...critical, ...warning, ...info].slice(0, 4);
  const title = critical.length ? `${critical.length} 个核心盲区` : (warning.length ? `${warning.length} 个降权盲区` : (info.length ? `${info.length} 个背景盲区` : "无明显盲区"));
  const detail = report.summary || (focus.length ? focus.map(item => item.title).join(" / ") : "核心监测链路可用");
  const issues = focus.map(item => `${item.title}：${item.fallback_action || item.conclusion}`);
  return {
    title,
    detail: truncateText(detail, 90),
    cls: critical.length ? "warn" : (warning.length || info.length ? "neutral" : "good"),
    issues
  };
}

function summarizeDataTrust(report) {
  if (!report || !Array.isArray(report.files)) {
    return { title: "待接入", detail: "文件级可信度待生成", cls: "neutral", issues: [] };
  }
  const blocked = report.files.filter(item => ["invalidated", "missing"].includes(item.status));
  const stale = report.files.filter(item => item.status === "stale");
  const degraded = report.files.filter(item => item.status === "degraded");
  const historical = report.files.filter(item => item.session_relevance === "historical" && !["invalidated", "missing", "stale"].includes(item.status));
  const freshnessFuture = report.files.filter(item => item.freshness_status === "future");
  const freshnessBad = report.files.filter(item => item.freshness_status === "stale" && item.session_relevance === "current");
  const freshnessAging = report.files.filter(item => item.freshness_status === "aging" && item.session_relevance === "current");
  const focus = [...blocked, ...freshnessFuture, ...freshnessBad, ...degraded, ...stale, ...historical, ...freshnessAging].slice(0, 5);
  const title = blocked.length
    ? `${blocked.length} 个不可用`
    : (freshnessFuture.length ? `${freshnessFuture.length} 个时间超前 / ${degraded.length + stale.length} 个降权`
      : (freshnessBad.length ? `${freshnessBad.length} 个超时 / ${degraded.length + stale.length} 个降权`
        : (degraded.length || stale.length || historical.length || freshnessAging.length ? `${degraded.length + stale.length} 个降权 / ${historical.length} 个阶段回看` : "全部可信")));
  const detail = report.summary || (focus.length ? focus.map(item => `${item.label}:${item.use_action}`).join(" / ") : "核心数据文件可正常使用");
  const issues = focus.map(item => {
    const sessionText = item.session_action ? `；${item.session_action}` : "";
    const freshnessText = ["future", "stale", "aging"].includes(item.freshness_status) ? `；${item.freshness_action}` : "";
    const reason = ["future", "stale", "aging"].includes(item.freshness_status)
      ? item.freshness_reason
      : (item.session_relevance === "historical" && item.session_reason ? item.session_reason : (item.reason || item.status));
    return `${item.label}：${item.use_action}${sessionText}${freshnessText}，${reason}`;
  });
  return {
    title,
    detail: truncateText(detail, 90),
    cls: blocked.length || freshnessFuture.length || freshnessBad.length ? "warn" : (degraded.length || stale.length || freshnessAging.length ? "neutral" : "good"),
    issues
  };
}

function summarizeSectionHealth(report) {
  if (!report || !Array.isArray(report.sections)) {
    return { title: "待接入", detail: "区块级健康矩阵待生成", cls: "neutral", issues: [] };
  }
  const bad = report.sections.filter(item => ["invalidated", "missing"].includes(item.status));
  const stale = report.sections.filter(item => item.status === "stale");
  const degraded = report.sections.filter(item => item.status === "degraded");
  const focus = [...bad, ...stale, ...degraded].slice(0, 4);
  const title = bad.length ? `${bad.length} 块不可用` : (stale.length || degraded.length ? `${stale.length + degraded.length} 块降权` : "全部可用");
  const detail = report.summary || (focus.length ? focus.map(item => `${item.label}:${item.action}`).join(" / ") : "核心区块可正常使用");
  const issues = focus.map(item => `${item.label}：${item.action}，${item.reason || item.status}`);
  return {
    title,
    detail: truncateText(detail, 90),
    cls: bad.length ? "warn" : (stale.length || degraded.length ? "neutral" : "good"),
    issues
  };
}

function renderSectionHealthBadges() {
  const report = cached("data/section-health.json");
  if (!report || !Array.isArray(report.sections)) return;
  report.sections.forEach(section => {
    const panel = document.getElementById(`section-${section.id}`);
    if (!panel) return;
    let badge = panel.querySelector(".section-health-badge");
    if (!badge) {
      badge = document.createElement("div");
      badge.className = "section-health-badge";
      const heading = panel.querySelector("h2");
      heading?.insertAdjacentElement("afterend", badge);
    }
    const cls = sectionHealthClass(section.status);
    badge.className = `section-health-badge ${cls}`;
    badge.innerHTML = `<span>${escapeHtml(section.action || section.status || "待确认")}</span><b>${escapeHtml(truncateText(userFacingText(section.reason || "区块状态待确认"), 120))}</b>`;
  });
}

function sectionHealthClass(status) {
  if (status === "ok") return "ok";
  if (status === "invalidated" || status === "missing") return "bad";
  if (status === "stale") return "stale";
  return "degraded";
}

function renderOpportunityRiskRadar() {
  const el = document.getElementById("opportunity-risk-radar");
  if (!el) return;
  const radar = buildOpportunityRiskRadar();
  const gate = radar.gate ? `<div class="radar-gate ${escapeHtml(radar.gate.cls || "neutral")}">
    <span>${escapeHtml(radar.gate.label || "雷达闸门")}</span>
    <b>${escapeHtml(radar.gate.title || "等待确认")}</b>
    <em>${escapeHtml(radar.gate.detail || "只按验证条件跟踪，不生成交易指令。")}</em>
  </div>` : "";
  const brief = renderDecisionBrief(radar.decisionBrief);
  const observation = renderObservationCoverage(radar.observationCoverage);
  const conflicts = renderRadarConflicts(radar.conflicts || []);
  el.innerHTML = `${gate}${brief}${observation}${conflicts}<div class="radar-grid">
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
  const gradeClass = `grade-${String(item.signalGrade || "C").toLowerCase()}`;
  const displayDetail = value => Array.isArray(value)
    ? userFacingList(value).join("；")
    : userFacingText(value);
  const details = [
    item.triggerReason ? ["触发", item.triggerReason] : null,
    item.discoveryType ? ["发现", discoveryTypeLabel(item.discoveryType)] : null,
    item.observationSource ? ["来源类型", `${item.observationSource}${item.independentObservation ? " · 独立观察" : " · 继承/验证"}`] : null,
    item.evidenceScore !== undefined ? ["证据分", `${item.evidenceScore}分`] : null,
    item.missingEvidence?.length ? ["缺口", item.missingEvidence.slice(0, 2)] : null,
    item.nextAction ? ["动作", item.nextAction] : null,
    item.upgradeRank ? ["升级", `#${item.upgradeRank} ${item.upgradePriority || "观察验证"}：${item.upgradeCondition || "等待确认后再升级。"}`] : null,
    item.useReasons ? ["口径", item.useReasons] : null,
    item.qualityFlags ? ["降权", item.qualityFlags] : null,
    item.evidence ? ["证据", item.evidence] : null,
    item.watchNext ? ["验证", item.watchNext] : null,
    item.invalidation ? ["证伪", item.invalidation] : null,
    item.sourceTrust ? ["源状态", item.sourceTrust] : null,
    item.sources ? ["来源", item.sources] : null
  ].filter(Boolean).map(([label, value]) => `<div class="radar-detail ${["降权", "缺口"].includes(label) ? "quality" : (["动作", "升级"].includes(label) ? "action" : "")}"><span>${label}</span><b>${escapeHtml(displayDetail(value))}</b></div>`).join("");
  return `<div class="radar-item ${tone}">
    <div class="radar-item-head">
      <b>${escapeHtml(item.title)}</b>
      <em class="${gradeClass}">${escapeHtml(item.signalGrade ? `${item.signalGrade}级 · ${item.useAction}` : item.confidence || "观察")}</em>
    </div>
    <div class="radar-use">${escapeHtml(item.confidence || "观察")}${item.signalScore !== undefined ? ` · ${item.signalScore}分` : ""}</div>
    <div class="radar-reason">${escapeHtml(userFacingText(item.reason))}</div>
    ${details}
    ${tags ? `<div class="topic-related">${tags}</div>` : ""}
  </div>`;
}

function buildOpportunityRiskRadar() {
  const feed = currentDecisionFeed();
  if (feed) {
    const coverage = monitoringCoverageRadarItems();
    const opportunityItems = (feed.opportunities || []).map(item => decisionFeedToRadarItem(item, "good"));
    const actionableOpportunities = opportunityItems.filter(isActionableOpportunity);
    const downgradedOpportunities = opportunityItems.filter(item => !isActionableOpportunity(item));
    return {
      gate: radarGateFromFeed(feed, actionableOpportunities, downgradedOpportunities),
      decisionBrief: feed.decision_brief,
      observationCoverage: feed.observation_coverage,
      conflicts: (feed.conflicts || []).map(decisionConflictToRadarItem),
      opportunities: actionableOpportunities.slice(0, 6),
      risks: dedupeRadarItems([
        ...coverage.risks,
        ...(feed.risks || []).map(item => decisionFeedToRadarItem(item, "risk"))
      ]).slice(0, 8),
      verifications: dedupeRadarItems([
        ...coverage.verifications,
        ...downgradedOpportunities.map(downgradedOpportunityToVerification),
        ...(feed.verifications || []).map(item => decisionFeedToRadarItem(item, "neutral"))
      ]).slice(0, 7)
    };
  }
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
    gate: null,
    decisionBrief: null,
    observationCoverage: null,
    conflicts: [],
    opportunities: [...strongStocks, ...strongThemes].slice(0, 6),
    risks: [...(breadthRisk ? [breadthRisk] : []), ...weakStocks, ...riskThemes].slice(0, 7),
    verifications: dedupeRadarItems(verifications).slice(0, 6)
  };
}

function renderDecisionBrief(brief) {
  if (!brief) return "";
  const reasons = (brief.reasons || []).slice(0, 3).map(item => `<span>${escapeHtml(item)}</span>`).join("");
  const upgrades = (brief.upgrade_watch || []).slice(0, 2).map(item => `<em>${escapeHtml(item)}</em>`).join("");
  const risks = (brief.risk_focus || []).slice(0, 3).map(item => `<b>${escapeHtml(item)}</b>`).join("");
  const actions = (brief.quality_actions || []).slice(0, 2).map(item => {
    const label = [item.label, item.file].filter(Boolean).join(" · ");
    const detail = item.next_step || item.unblock_condition || "";
    return `<em>${escapeHtml(label)}：${escapeHtml(userFacingText(detail))}</em>`;
  }).join("");
  const cls = /风险|回撤|无明确/.test(String(brief.stance || "")) ? "risk" : (/等待|验证/.test(String(brief.stance || "")) ? "watch" : "good");
  return `<div class="radar-brief ${cls}">
    <div class="radar-brief-main">
      <span>决策口径</span>
      <b>${escapeHtml(brief.stance || "等待确认")}</b>
      <p>${escapeHtml(brief.action || "只按验证条件跟踪，不生成交易指令。")}</p>
    </div>
    <div class="radar-brief-side">
      ${actions ? `<div><label>处置动作</label>${actions}</div>` : ""}
      ${risks ? `<div><label>风险焦点</label>${risks}</div>` : ""}
      ${upgrades ? `<div><label>升级条件</label>${upgrades}</div>` : ""}
    </div>
    ${reasons ? `<div class="radar-brief-reasons">${reasons}</div>` : ""}
  </div>`;
}

function renderObservationCoverage(coverage) {
  if (!coverage) return "";
  const statusClass = coverage.status === "active" ? "good" : (coverage.status === "independent" ? "watch" : "risk");
  const active = Number(coverage.active_market_count || 0);
  const independent = Number(coverage.independent_count || 0);
  const inherited = Number(coverage.topic_inherited_count || 0);
  const titles = Array.isArray(coverage.active_titles) && coverage.active_titles.length
    ? `<em>${coverage.active_titles.slice(0, 3).map(escapeHtml).join(" / ")}</em>`
    : "<em>暂无非预设新线，继续等待盘面扫描确认</em>";
  return `<div class="radar-observation ${statusClass}">
    <div><span>主动观察覆盖</span><b>${escapeHtml(coverage.summary || "主动观察覆盖待生成")}</b>${titles}</div>
    <p>主动扫描 ${active} · 独立观察 ${independent} · 专题继承 ${inherited}</p>
  </div>`;
}

function renderRadarConflicts(conflicts) {
  if (!conflicts.length) return "";
  return `<div class="radar-conflicts">
    <div class="radar-conflicts-head"><b>冲突校验</b><span>同一主线多空信号统一口径</span></div>
    ${conflicts.slice(0, 3).map(item => `<div class="radar-conflict ${escapeHtml(item.severity || "watch")}">
      <b>${escapeHtml(item.theme)}</b>
      <span>${escapeHtml(item.verdict)}</span>
      <em>${escapeHtml(item.action)}</em>
    </div>`).join("")}
  </div>`;
}

function decisionConflictToRadarItem(item) {
  return {
    theme: item.theme || "未命名主线",
    verdict: item.verdict || "等待确认",
    severity: item.severity || "watch",
    action: item.action || "只做验证，不直接升级。",
    evidence: item.evidence || []
  };
}

function radarGateFromFeed(feed, actionableOpportunities, downgradedOpportunities) {
  const risks = Array.isArray(feed.risks) ? feed.risks : [];
  const highRiskCount = risks.filter(item => ["A", "B"].includes(String(item.signal_grade || "").toUpperCase())).length;
  const qualityStatus = feed.quality_gate?.status || "";
  if (!actionableOpportunities.length && downgradedOpportunities.length) {
    return {
      cls: "risk",
      label: "交易闸门",
      title: "无可用机会，风险优先",
      detail: `当前 ${downgradedOpportunities.length} 条机会均为降权/仅复核；只做验证，不直接追高。${highRiskCount ? `A/B级风险 ${highRiskCount} 条优先处理。` : ""}`
    };
  }
  if (/degraded|critical|blocked|invalidated/.test(String(qualityStatus))) {
    return {
      cls: "warn",
      label: "交易闸门",
      title: "数据降级，机会降权",
      detail: feed.quality_gate?.summary || "核心数据需复核，机会只能按验证条件升级。"
    };
  }
  return {
    cls: "good",
    label: "交易闸门",
    title: "存在可跟踪机会",
    detail: "仍需按证据、验证和证伪条件执行。"
  };
}

function monitoringCoverageRadarItems() {
  const coverage = cached("data/monitoring-coverage.json");
  if (!coverage || !Array.isArray(coverage.blind_spots)) {
    return { risks: [], verifications: [] };
  }
  const currentDate = currentSignalDate();
  const coverageDate = coverage.current_signal_date || signalDate(coverage.timestamp);
  if (coverageDate && coverageDate !== currentDate) {
    return { risks: [], verifications: [] };
  }
  const important = coverage.blind_spots
    .filter(item => item && ["critical", "warning"].includes(item.severity))
    .sort((a, b) => severityRank(b.severity) - severityRank(a.severity));
  const risks = important.map(item => ({
    title: item.title || "监测盲区",
    reason: truncateText(item.conclusion || "", 108),
    confidence: item.severity === "critical" ? "核心盲区" : "降权盲区",
    tone: "risk",
    tags: uniqueList(["监测盲区", ...(item.source_files || []).map(sourceShortName)]).slice(0, 5),
    evidence: (item.evidence || []).slice(0, 2),
    watchNext: (item.fallback_checks || item.impacted_decisions || []).slice(0, 3),
    invalidation: item.fallback_action,
    sources: (item.source_files || []).map(sourceShortName),
    signalGrade: item.severity === "critical" ? "A" : "B",
    signalScore: item.severity === "critical" ? 95 : 72,
    useAction: item.severity === "critical" ? "优先处理" : "降权观察",
    useReasons: ["自动监测断点", "影响盘中决策", "已给替代观察"]
  }));
  const verifications = important.slice(0, 3).map(item => ({
    title: `${item.title || "监测盲区"}替代观察`,
    reason: truncateText(item.fallback_action || item.conclusion || "", 108),
    confidence: "替代验证",
    tone: "neutral",
    tags: uniqueList(["盲区替代", ...(item.source_files || []).map(sourceShortName)]).slice(0, 5),
    evidence: (item.impacted_decisions || []).slice(0, 2),
    watchNext: (item.fallback_checks || (item.fallback_action ? [item.fallback_action] : [])).slice(0, 4),
    invalidation: "对应数据文件恢复 trusted，且盲区报告不再提示该断点。",
    sources: (item.source_files || []).map(sourceShortName),
    signalGrade: "B",
    signalScore: 70,
    useAction: "等待确认",
    useReasons: ["替代观察动作", "可证伪"]
  }));
  return { risks, verifications };
}

function severityRank(severity) {
  return { info: 1, warning: 2, critical: 3 }[severity] || 0;
}

function currentDecisionFeed() {
  const feed = cached("data/decision-feed.json");
  if (!feed || typeof feed !== "object") return null;
  const feedDate = feed.current_signal_date || signalDate(feed.timestamp);
  if (feedDate && feedDate !== currentSignalDate()) return null;
  if (!Array.isArray(feed.opportunities) && !Array.isArray(feed.risks) && !Array.isArray(feed.verifications)) return null;
  return feed;
}

function decisionFeedToRadarItem(item, fallbackTone) {
  const evidence = (item.evidence || []).filter(Boolean);
  const watchNext = (item.watch_next || []).filter(Boolean);
  const sources = (item.source_files || []).filter(Boolean);
  return {
    title: item.title || "未命名信号",
    reason: truncateText(item.conclusion || "", 108),
    confidence: confidenceLabel(item.confidence),
    tone: item.tone || fallbackTone || "neutral",
    tags: uniqueList([...(item.tags || []), ...sources.map(sourceShortName)]).slice(0, 5),
    evidence: evidence.slice(0, 2),
    watchNext: watchNext.slice(0, 1),
    invalidation: item.invalidation,
    sources: sources.map(sourceShortName),
    qualityFlags: (item.quality_flags || []).slice(0, 3),
    triggerReason: item.trigger_reason,
    signalGrade: item.signal_grade,
    signalScore: item.signal_score,
    useAction: item.use_action,
    useReasons: (item.use_reasons || []).slice(0, 4),
    discoveryType: item.discovery_type,
    evidenceScore: item.evidence_score,
    missingEvidence: (item.missing_evidence || []).slice(0, 4),
    nextAction: item.next_action,
    upgradeRank: item.upgrade_rank,
    upgradePriority: item.upgrade_priority,
    upgradeCondition: item.upgrade_condition,
    observationSource: item.observation_source,
    independentObservation: item.independent_observation,
    sourceTrust: radarSourceTrustSummary(sources)
  };
}

function radarSourceTrustSummary(sources) {
  if (!sources.length) return "";
  const trust = cached("data/data-trust.json");
  const rows = Array.isArray(trust?.files) ? trust.files : [];
  const byFile = new Map(rows.map(row => [String(row.file || "").replace(/^data\//, ""), row]));
  return sources.slice(0, 3).map(source => {
    const normalized = String(source || "").replace(/^data\//, "");
    const row = byFile.get(normalized);
    if (!row) return systemSourceTrustSummary(normalized);
    const action = trustActionShort(row.use_action || row.status);
    const phase = trustPhaseShort(row.session_relevance);
    return `${row.label || sourceShortName(source)}:${action}/${phase}`;
  }).join("；");
}

function systemSourceTrustSummary(source) {
  const normalized = String(source || "").replace(/^data\//, "");
  const systemSources = {
    "quality-report.json": ["质量报告", cached("data/quality-report.json")?.status],
    "source-health.json": ["数据源健康", cached("data/source-health.json")?.overall_status || cached("data/source-health.json")?.status],
    "build-report.json": ["构建报告", cached("data/build-report.json")?.status],
    "smoke-report.json": ["静态门禁", cached("data/smoke-report.json")?.status],
    "runtime-smoke-report.json": ["运行时门禁", cached("data/runtime-smoke-report.json")?.status],
    "automation-health.json": ["自动化心跳", cached("data/automation-health.json")?.overall_status || cached("data/automation-health.json")?.status],
    "monitoring-coverage.json": ["监测盲区", cached("data/monitoring-coverage.json")?.status],
    "section-health.json": ["区块健康", cached("data/section-health.json")?.overall_status || cached("data/section-health.json")?.status]
  };
  const row = systemSources[normalized];
  if (!row) return `${sourceShortName(source)}:未纳入可信矩阵`;
  return `${row[0]}:${systemStatusShort(row[1])}/当前`;
}

function systemStatusShort(value) {
  const text = String(value || "");
  if (/critical|blocked|invalidated|missing|blind_spot/.test(text)) return "不可用";
  if (/degraded|warning/.test(text)) return "降权";
  if (/ok|trusted/.test(text)) return "正常";
  return text || "待确认";
}

function trustActionShort(value) {
  const text = String(value || "");
  if (/等待|不可|重产|修复/.test(text)) return "不可用";
  if (/降权/.test(text)) return "降权";
  if (/正常|trusted/.test(text)) return "正常";
  if (/stale|过期/.test(text)) return "过期";
  return text || "待确认";
}

function trustPhaseShort(value) {
  return {
    current: "当前",
    historical: "阶段回看",
    background: "背景",
    upcoming: "待产出",
    blocked: "阻断"
  }[value] || value || "未知";
}

function isActionableOpportunity(item) {
  const grade = String(item.signalGrade || "").toUpperCase();
  const action = String(item.useAction || "");
  const confidence = String(item.confidence || "");
  const blocked = /仅复核|降权|等待|低|low|不可|候选/.test(`${action} ${confidence}`);
  return ["A", "B"].includes(grade) && !blocked;
}

function downgradedOpportunityToVerification(item) {
  return {
    ...item,
    title: `${item.title}候选验证`,
    tone: "neutral",
    confidence: item.confidence || "候选待验证",
    reason: item.reason || "机会证据不足，先转入验证队列。",
    triggerReason: item.triggerReason || "降权候选触发：证据或数据质量不足，先转入验证队列。",
    watchNext: item.watchNext?.length ? item.watchNext : ["等待板块扩散、核心承接和数据质量恢复后再升级。"],
    nextAction: item.nextAction || (item.watchNext?.[0] || "等待板块扩散、核心承接和数据质量恢复后再升级。"),
    invalidation: item.invalidation || "风险项不收敛或核心股不放量承接，则不升级为机会。",
    useAction: "等待确认",
    useReasons: uniqueList([...(item.useReasons || []), "C/D级机会不进入机会栏", "先验证再升级"])
  };
}

function discoveryTypeLabel(value) {
  return {
    active_market_scan: "主动盘面扫描",
    active_stock_scan: "主动个股扫描",
    postmarket_theme_scan: "盘后主线扫描",
    postmarket_risk_scan: "盘后风险扫描",
    topic_watch_scan: "专题观察继承",
    risk_guardrail: "风控兜底",
    verification_queue: "待验证队列",
    theme_shift_scan: "主线变化扫描",
    derived_signal: "模型派生"
  }[value] || String(value || "模型派生");
}

function confidenceLabel(value) {
  const map = {
    high: "高置信",
    medium: "中置信",
    low: "低置信",
    actionable: "可验证"
  };
  return map[value] || value || "观察";
}

function sourceShortName(source) {
  return String(source || "").replace(/^data\//, "").replace(/\.json$/, "");
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
  const invalidated = alertInvalidationState(data);
  if (invalidated.invalidated) {
    renderAlertsSummary([], data.timestamp, invalidated);
    el.innerHTML = renderAlertInvalidatedState(invalidated);
    return;
  }
  const saved = sortAlertsByEventTime(
    (data.alerts || [])
      .map(a => normalizeAlertTime({ ...a, _received: alertEventTime(a, data.timestamp, now) }, data.timestamp, now))
      .filter(a => !a._eventTime || a._eventTime <= now + FUTURE_ALERT_TOLERANCE)
  ).slice(0, MAX_ALERTS);

  renderAlertsSummary(saved, data.timestamp, null, data);

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

function alertInvalidationState(data) {
  const trust = cached("data/data-trust.json");
  const trustRow = Array.isArray(trust?.files)
    ? trust.files.find(item => item.file === "data/alert.json")
    : null;
  const invalidated = data?.source_status === "invalidated" || trustRow?.status === "invalidated";
  const coverage = cached("data/monitoring-coverage.json");
  const blindSpot = Array.isArray(coverage?.blind_spots)
    ? coverage.blind_spots.find(item => item.id === "intraday-alert-trigger" || /盘中异动/.test(item.title || ""))
    : null;
  return {
    invalidated,
    reason: data?.note || trustRow?.reason || blindSpot?.conclusion || "盘中异动当前不可用，等待修复后重产。",
    action: trustRow?.use_action || blindSpot?.fallback_action || "等待重产",
    fallbackChecks: Array.isArray(blindSpot?.fallback_checks) ? blindSpot.fallback_checks.slice(0, 4) : [],
    evidence: Array.isArray(blindSpot?.evidence) ? blindSpot.evidence.slice(0, 2) : []
  };
}

function renderAlertInvalidatedState(state) {
  const checks = state.fallbackChecks.length
    ? renderAlertFallbackChecks(state.fallbackChecks)
    : '<div class="alert-fallback-list"><span>替代观察：先看盘中全景、涨跌停/炸板宽度、观察池强弱和专题静态结论。</span></div>';
  const evidence = state.evidence.length
    ? `<details class="alert-detail"><summary>撤下依据</summary><div>${state.evidence.map(escapeHtml).join("<br>")}</div></details>`
    : "";
  return `<div class="alert-blocked">
    <div class="alert-blocked-head">
      <span class="badge risk">不可用</span>
      <b>盘中异动已撤下污染批次</b>
    </div>
    <p>${escapeHtml(state.reason)}</p>
    <div class="source-note source-note-warning">
      <b>交易处理：</b>
      <span>异动卡不能作为买卖触发依据，${escapeHtml(state.action)}。</span>
    </div>
    <h3>替代观察</h3>
    ${checks}
    ${evidence}
  </div>`;
}

function renderAlertFallbackChecks(checks) {
  return `<div class="alert-fallback-list">${checks.map(item => {
    const parsed = parseFallbackCheck(item);
    return `<div class="alert-fallback-item">
      <span>${escapeHtml(parsed.label)}</span>
      <b>${escapeHtml(parsed.detail)}</b>
    </div>`;
  }).join("")}</div>`;
}

function parseFallbackCheck(text) {
  const raw = String(text || "").trim();
  const match = raw.match(/^([^：:]{2,16})[：:]\s*(.+)$/);
  if (!match) return { label: "替代观察", detail: raw };
  return { label: match[1], detail: match[2] };
}

function renderAlertsSummary(alerts, timestamp, invalidatedState = null, sourceData = null) {
  const el = document.getElementById("alerts-summary");
  if (!el) return;
  if (invalidatedState?.invalidated) {
    el.innerHTML = `
      <div class="decision-strip alerts-decision">
        <div class="decision-card risk">
          <span class="decision-label">核心结论</span>
          <b>异动触发不可用</b>
          <span>污染批次已撤下，不能当交易触发</span>
        </div>
        <div class="decision-card action">
          <span class="decision-label">当前动作</span>
          <b>${escapeHtml(invalidatedState.action || "等待重产")}</b>
          <span>修复前只看替代观察和盘中全景</span>
        </div>
        <div class="decision-card neutral">
          <span class="decision-label">替代信号</span>
          <b>宽度 / 主线 / 新线</b>
          <span>涨跌停、炸板、观察池承接优先</span>
        </div>
        <div class="decision-card risk">
          <span class="decision-label">风险提示</span>
          <b>不要恢复旧 alert</b>
          <span>必须由修复后的行情源重产</span>
        </div>
      </div>`;
    return;
  }
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
  const audit = alertQuoteAuditSummary(sourceData);
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
    <div class="decision-card ${audit.cls}">
      <span class="decision-label">行情审计</span>
      <b>${escapeHtml(audit.title)}</b>
      <span>${escapeHtml(audit.detail)}</span>
    </div>
    </div>
  `;
}

function alertQuoteAuditSummary(data) {
  const audit = data?.quote_audit;
  if (!audit || typeof audit !== "object") {
    return { title: "待补 quote_audit", detail: "active alert 需声明行情源和交叉验证", cls: "risk" };
  }
  const sanity = audit.sanity_checks || {};
  const provider = audit.provider || audit.source || "未知源";
  const verified = sanity.cross_source_verified === true;
  const maxMove = Number(sanity.max_abs_leader_change_pct);
  const maxText = Number.isFinite(maxMove) ? `最大${maxMove.toFixed(2)}%` : "最大值待补";
  return {
    title: verified ? "已交叉验证" : "待交叉验证",
    detail: `${provider} · ${formatUpdateTime(audit.quote_time) || audit.quote_time || "时间待补"} · ${maxText}`,
    cls: verified ? "good" : "risk"
  };
}

/* =========================
   盘中全景（双格式兼容）
========================= */
function renderIntraday(data) {
  updatePanelMeta("intraday-indices", data.timestamp);
  renderIntradayDecision(data);
  // 指数行
  const idxEl = document.getElementById("intraday-indices");
  const intradayIndices = intradayIndexItems(data);
  if (intradayIndices.length) {
    idxEl.innerHTML = renderIndexRow(intradayIndices);
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

  if (data.summary) {
    html += `<div class="subsection"><h3>📌 盘中结论</h3><div class="breadth">${escapeHtml(data.summary)}</div></div>`;
  }

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
        const rawName = trendName(t);
        const status = trendStatus(t);
        const cls = status.includes('强') ? 'strong-theme' : '';
        const rawLabel = rawName && rawName !== name ? ` <span class="muted">原始：${escapeHtml(rawName)}</span>` : "";
        const evidence = t.evidence ? renderEvidenceDetails(t.evidence) : "";
        const continuity = t.continuity ? `<div class="theme-line">${escapeHtml(truncateText(t.continuity, 90))}</div>` : "";
        const risk = t.risk ? `<div class="theme-line risk-text">风险：${escapeHtml(truncateText(t.risk, 90))}</div>` : "";
        return `<div class="theme-item ${cls}"><b>${escapeHtml(name)}</b>${rawLabel}${status ? ` <span class="muted">— ${escapeHtml(status)}</span>` : ""}${renderThemeSubTags(t)}${continuity}${risk}${evidence}</div>`;
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

function intradayIndexItems(data) {
  if (Array.isArray(data.indices)) return data.indices;
  if (data.indices && typeof data.indices === "object") return data.indices;
  const index = data.index || {};
  if (Array.isArray(index.indices)) return index.indices;
  if (Array.isArray(index.a_share_indices)) return index.a_share_indices;
  if (Array.isArray(index.hk_indices)) return index.hk_indices;
  if (Array.isArray(index.HK_close_window_snapshot)) {
    const priority = ["hkHSI", "hkHSTECH", "hk00981", "hk01347", "hk01024", "hk00020"];
    return priority
      .map(code => index.HK_close_window_snapshot.find(item => item.code === code))
      .filter(Boolean)
      .map(item => ({
        name: item.name || item.code,
        change_pct: item.change_pct,
        close: item.price,
        note: item.quote_time ? `快照 ${item.quote_time.slice(11)}` : ""
      }));
  }
  return [];
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
    tokyo_electron_change_pct: "东京电子",
    advantest_change_pct: "Advantest",
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
      const sources = data.sources
        .map(s => typeof s === "string" ? { name: "", url: s } : (s || {}))
        .map(s => ({ name: cleanShortNote(s.name || s.title || s.source || ""), url: s.url || s.href || "" }))
        .filter(s => s.name);
      if (sources.length) {
        html += '<div class="subsection"><span class="muted" style="font-size:11px">数据源：' + sources.map(s => s.url ? `<a href="${s.url}" target="_blank" style="color:#58A6FF">${escapeHtml(s.name)}</a>` : escapeHtml(s.name)).join(" · ") + '</span></div>';
      }
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
  const fallback = renderJapanKoreaDegraded();
  if (typeof jk === "string") {
    const degraded = /降级|未核实|待确认|再确认|乱码|decode|failed|error/i.test(jk) || hasMojibake(jk);
    if (degraded) {
      return renderJapanKoreaDegraded();
    }
    const tags = japanKoreaTextTags(jk);
    return tags.length
      ? '<div class="tag-row">日韩早盘：' + tags.map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>'
      : fallback;
  }
  if (Array.isArray(jk)) {
    const rendered = jk.flatMap(s => {
      if (typeof s === "string") return japanKoreaTextTags(s);
      const tag = formatMarketTag(s);
      return tag ? [tag] : [];
    }).filter(v => v && !hasMojibake(v));
    return rendered.length
      ? '<div class="tag-row">日韩早盘：' + rendered.map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>'
      : fallback;
  }
  if (jk && typeof jk === "object") {
    const statusText = JSON.stringify(jk);
    if (/降级|未核实|待确认|再确认|乱码|decode|failed|error/i.test(statusText) || hasMojibake(statusText)) {
      return renderJapanKoreaDegraded(jk.pending_confirmation || jk.confirm_list || jk.watch || jk.watch_list);
    }
    const allowedKeys = new Set([
      "nikkei225_change_pct",
      "kospi_change_pct",
      "samsung_change_pct",
      "sk_hynix_change_pct",
      "tokyo_electron_change_pct",
      "advantest_change_pct",
      "judgement"
    ]);
    const tags = Object.entries(jk)
      .filter(([k, v]) => allowedKeys.has(k) && v !== undefined && v !== null && !hasMojibake(v))
      .map(([k, v]) => `<span class="tag">${escapeHtml(externalLabel(k))}：${escapeHtml(formatDisplayValue(v))}</span>`);
    return tags.length ? '<div class="tag-row">日韩早盘：' + tags.join(" ") + '</div>' : fallback;
  }
  return "";
}

function japanKoreaTextTags(text) {
  if (!text || hasMojibake(text)) return [];
  const raw = String(text);
  const rules = [
    ["日经225", /(?:日经(?:225)?|Nikkei(?:\s*225)?)[：:\s]*([+-]?\d+(?:\.\d+)?%?)/i],
    ["韩国KOSPI", /(?:韩国\s*)?KOSPI[：:\s]*([+-]?\d+(?:\.\d+)?%?)/i],
    ["三星电子", /(?:三星(?:电子)?|Samsung(?:\s*Electronics)?)[：:\s]*([+-]?\d+(?:\.\d+)?%?)/i],
    ["SK海力士", /(?:SK\s*海力士|SK\s*Hynix)[：:\s]*([+-]?\d+(?:\.\d+)?%?)/i],
    ["东京电子", /(?:东京电子|Tokyo\s*Electron)[：:\s]*([+-]?\d+(?:\.\d+)?%?)/i],
    ["Advantest", /Advantest[：:\s]*([+-]?\d+(?:\.\d+)?%?)/i]
  ];
  return rules.map(([label, re]) => {
    const match = raw.match(re);
    if (!match) return "";
    const value = match[1].includes("%") ? match[1] : `${match[1]}%`;
    return `${label}：${value}`;
  }).filter(Boolean);
}

function normalizeJapanKoreaWatchList(value) {
  const defaults = ["日经225", "韩国KOSPI", "三星电子", "SK海力士", "东京电子", "Advantest"];
  const list = Array.isArray(value)
    ? value
    : String(value || "").split(/[、,，/／\s]+/);
  const cleaned = list
    .map(item => cleanShortNote(item))
    .filter(item => item && !hasMojibake(item) && !/降级|未核实|待确认|再确认|decode|failed|error/i.test(item));
  return cleaned.length ? cleaned.slice(0, 6) : defaults;
}

function renderJapanKoreaDegraded(confirmList) {
  const watchList = normalizeJapanKoreaWatchList(confirmList);
  return `<div class="source-note source-note-warning">
    <b>日韩早盘：待复核</b>
    <span>实时源未取得可靠行情，页面不展示未核实数值。</span>
    <span>复核清单：${watchList.map(item => escapeHtml(item)).join(" / ")}</span>
  </div>`;
}

function extractAfter(text, marker) {
  if (!text || !marker) return "";
  const idx = String(text).indexOf(marker);
  if (idx < 0) return "";
  return String(text).slice(idx + marker.length);
}

function cleanShortNote(text) {
  return String(text || "")
    .replace(/^[：:，,；;\s]+/, "")
    .replace(/[。；;\s]+$/, "")
    .trim();
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
    const noteText = userFacingText(source.note || source.detail || "");
    const note = noteText ? `<div class="source-note">${escapeHtml(noteText)}</div>` : "";
    return `<div class="source-card ${cls}">
      <div class="source-head">
        <b>${escapeHtml(source.name || source.id || "未命名数据源")}</b>
        <span class="source-status">${label}</span>
      </div>
      <div class="source-meta">${escapeHtml(userFacingText(source.role || source.usage || source.detail || ""))}</div>
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

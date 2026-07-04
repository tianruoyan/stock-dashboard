const FILES = [
  "data/alert.json",
  "data/intraday.json",
  "data/premarket.json",
  "data/midday.json",
  "data/postmarket.json",
  "data/evening-sentiment.json",
  "data/topics.json",
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
  const debug = [];
  for (const file of FILES) {
    try {
      const res = await fetch(file + "?t=" + Date.now());
      const data = await res.json();
      if (!cache[file] || cache[file].timestamp !== data.timestamp) {
        cache[file] = data;
        render(file, data);
        debug.push('✅ ' + file.split('/').pop());
      } else {
        debug.push('⏭ ' + file.split('/').pop());
      }
    } catch (e) {
      console.error("load failed:", file);
      debug.push('❌ ' + file.split('/').pop() + ': ' + e.message);
    }
  }
  document.getElementById("lastUpdate").innerText = new Date().toLocaleTimeString();
  // Debug: write status to premarket section so it's visible
  const pm = document.getElementById("premarket");
  if (pm && (!pm.innerText || pm.innerText.length < 10)) {
    pm.innerText = 'DEBUG: ' + debug.join(' | ');
  }
}

/* =========================
   渲染路由
========================= */
function render(file, data) {
  if (file.includes("alert"))    renderAlerts(data);
  if (file.includes("intraday")) renderIntraday(data);
  if (file.includes("premarket")) renderPremarket(data);
  if (file.includes("midday"))   renderMidday(data);
  if (file.includes("postmarket")) renderPostmarket(data);
  if (file.includes("evening"))  renderEvening(data);
  if (file.includes("topics"))   renderTopics(data);
  if (file.includes("requirements")) renderRequirements(data);
  if (file.includes("source-health")) renderSourceHealth(data);
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
  const idDate = String(alert.id || "").match(/^(\d{4})(\d{2})(\d{2})/);
  const base = idDate
    ? `${idDate[1]}-${idDate[2]}-${idDate[3]}`
    : (baseTimestamp ? String(baseTimestamp).slice(0, 10) : new Date(fallbackMs).toISOString().slice(0, 10));
  const time = /^\d{2}:\d{2}:\d{2}$/.test(alert.time || "") ? alert.time : "00:00:00";
  const parsed = Date.parse(`${base}T${time}+08:00`);
  return Number.isNaN(parsed) ? fallbackMs : parsed;
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

    return `<div class="${cls}${fadeCls}">
      <div class="card-head">${badge}<b>${a.sector}</b><span class="time">${a.time} · ${ageLabel}</span></div>
      <div class="card-body">${a.type} · ${a.reason || ""}</div>
      ${leaders ? `<div class="card-leaders">${leaders}</div>` : ""}
    </div>`;
  }).join("");
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
  const strong = themes.filter(t => /强|强化|主线|资金/.test(trendStatus(t)) && !/风险|弱|退潮/.test(trendStatus(t)));
  const risks = themes.filter(t => /风险|弱|退潮|回落|分歧/.test([trendStatus(t), t.risk, t.continuity].join(" ")));
  const primary = strong[0] || themes[0];
  const primaryName = primary ? trendName(primary) : "等待主线确认";
  const primaryStatus = primary ? trendStatus(primary) || "观察" : "暂无";
  const riskNames = risks.slice(0, 2).map(t => trendName(t)).join(" / ") || "暂无明确风险线";
  const sentiment = intradayMood(data);
  const action = intradayActionText(data, strong, risks, sentiment);

  el.innerHTML = `
    <div class="decision-card primary">
      <span class="decision-label">主线</span>
      <b>${escapeHtml(primaryName)}</b>
      <span>${escapeHtml(primaryStatus)}</span>
    </div>
    <div class="decision-card ${sentiment.cls}">
      <span class="decision-label">情绪</span>
      <b>${escapeHtml(sentiment.title)}</b>
      <span>${escapeHtml(sentiment.detail)}</span>
    </div>
    <div class="decision-card risk">
      <span class="decision-label">风险</span>
      <b>${escapeHtml(riskNames)}</b>
      <span>${escapeHtml(risks[0]?.risk || "看是否扩散")}</span>
    </div>
    <div class="decision-card action">
      <span class="decision-label">动作</span>
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
        const name = trendName(t);
        const status = trendStatus(t);
        const cls = status.includes('强') ? 'strong-theme' : '';
        const evidence = t.evidence ? renderEvidenceDetails(t.evidence) : "";
        const continuity = t.continuity ? `<div class="theme-line">${escapeHtml(truncateText(t.continuity, 90))}</div>` : "";
        const risk = t.risk ? `<div class="theme-line risk-text">风险：${escapeHtml(truncateText(t.risk, 90))}</div>` : "";
        return `<div class="theme-item ${cls}"><b>${escapeHtml(name)}</b>${status ? ` <span class="muted">— ${escapeHtml(status)}</span>` : ""}${continuity}${risk}${evidence}</div>`;
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
      return `<div class="theme-item ${cls}"><b>${icon} ${escapeHtml(trendName(t))}</b>${status ? ` <span class="muted">— ${escapeHtml(status)}</span>` : ""}${continuity}${risk}${evidence}</div>`;
    }).join('');
    html += '</div>';
  }

  // 情绪详情
  if (data.sentiment && typeof data.sentiment === 'object' && Object.keys(data.sentiment).length > 0) {
    html += '<div class="subsection"><h3>📈 盘面情绪</h3><ul class="news-list">';
    for (const [k, v] of Object.entries(data.sentiment)) {
      if (v === null || v === undefined || v === "") continue;
      const label = intradaySentimentLabel(k);
      html += `<li><b>${label}</b>：${escapeHtml(formatDisplayValue(v))}</li>`;
    }
    html += '</ul></div>';
  }

  // 操作建议
  if (data.actions) {
    html += '<div class="subsection"><h3>💡 午后建议</h3><ul class="news-list">';
    html += data.actions.map(a => `<li>${a}</li>`).join('');
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

function renderSectorList(elId, sectors, dir) {
  const el = document.getElementById(elId);
  if (!sectors || !sectors.length) {
    el.innerHTML = '<div class="empty-sm">数据待接入</div>';
    return;
  }
  const cls = dir === 'up' ? 'up' : 'down';
  el.innerHTML = sectors.map((s, i) => {
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
  }).join("");
}

function buildIntradaySectorLists(data) {
  const conceptTop = data.concept_top5 || data.concept_top || data.conceptTop || [];
  const conceptBottom = data.concept_bottom5 || data.concept_bottom || data.conceptBottom || [];
  const industryTop = data.industry_top5 || data.industry_top || data.industryTop || [];
  const industryBottom = data.industry_bottom5 || data.industry_bottom || data.industryBottom || [];
  const source = Array.isArray(data.themes) && data.themes.length ? data.themes : (Array.isArray(data.main_trends) ? data.main_trends : []);
  const inferredTop = source
    .filter(t => typeof t === "object" && /强|强化|资金|观察/.test(trendStatus(t)) && !/风险|弱|退潮/.test(trendStatus(t)))
    .map(t => ({ name: trendName(t), status: trendStatus(t), detail: trendStatus(t) }))
    .slice(0, 5);
  const inferredBottom = source
    .filter(t => typeof t === "object" && /风险|弱|退潮|回落/.test(trendStatus(t)))
    .map(t => ({ name: trendName(t), status: trendStatus(t), detail: trendStatus(t) }))
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

  // === Codex 格式: 集合竞价 + 情绪判断 ===
  if (data.market_context || data.strong_lines || data.watch_lines) {
    // 竞价情绪
    if (data.market_context) {
      const ctx = data.market_context;
      const mood = (ctx.limit_diff || 0) >= 0 ? 'up' : 'down';
      html += '<div class="subsection"><h3>⚡ 集合竞价情绪</h3>';
      html += `<div class="breadth">涨停 <b>${ctx.limit_up_count||0}</b> / 跌停 <b>${ctx.limit_down_count||0}</b> · 差值 <span class="${mood}">${ctx.limit_diff||0}</span> · 涨停:跌停 <b>${ctx.limit_ratio||'-'}</b>${ctx.denominator ? `<span class="muted"> (${ctx.denominator})</span>` : ''}</div>`;
      html += '</div>';
    }
    if (data.market_context.open_style || data.market_context.sentiment_judgement || data.market_context.benefit_themes || data.market_context.risk_points) {
      html += '<div class="subsection"><h3>🧭 开盘情绪预判</h3>';
      if (data.market_context.open_style || data.market_context.sentiment_judgement) {
        html += `<div class="theme-item premarket-lead"><b>${escapeHtml(data.market_context.open_style || "待判断")}</b></div>`;
        if (data.market_context.sentiment_judgement) {
          html += renderBulletList(takePremarketPoints(data.market_context.sentiment_judgement, 2, 140), "premarket-points");
        }
      }
      if (data.market_context.benefit_themes) {
        html += '<div class="tag-row">受益：' + data.market_context.benefit_themes.slice(0, 5).map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>';
      }
      if (data.market_context.risk_points) {
        html += '<div class="tag-row">风险：' + data.market_context.risk_points.slice(0, 5).map(s => `<span class="tag">${escapeHtml(s)}</span>`).join(" ") + '</div>';
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
      const jk = data.us_overnight.japan_korea;
      if (Array.isArray(jk)) {
        html += '<div class="tag-row">日韩早盘：' + jk.map(s => `<span class="tag">${escapeHtml(formatMarketTag(s))}</span>`).join(" ") + '</div>';
      } else {
        html += '<div class="tag-row">日韩早盘：' + Object.entries(jk).map(([k, v]) => `<span class="tag">${escapeHtml(externalLabel(k))}：${escapeHtml(formatDisplayValue(v))}</span>`).join(" ") + '</div>';
      }
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

/* =========================
   午盘盘前（11:30午间产出）
========================= */
function renderMidday(data) {
  updatePanelMeta("midday", data.timestamp);
  const el = document.getElementById("midday");
  let html = "";

  // 上午数据快照
  if (data.morning_snapshot) {
    html += '<div class="subsection"><h3>📈 上午快照</h3><div class="breadth">';
    if (typeof data.morning_snapshot === 'string') {
      html += data.morning_snapshot;
    } else {
      const ms = data.morning_snapshot;
      if (ms.indices) {
        html += ms.indices.map(i => {
          const p = parseFloat(i.pct) || 0;
          const cls = p >= 0 ? 'up' : 'down';
          return `<span style="margin-right:12px"><b>${i.name}</b> <span class="${cls}">${p > 0 ? '+' : ''}${p.toFixed(2)}%</span></span>`;
        }).join('');
      }
      if (ms.breadth) {
        html += `<br><span style="font-size:12px">涨停${ms.breadth.limit_up||'?'}家 跌停${ms.breadth.limit_down||'?'}家</span>`;
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
        `<div class="theme-item ${(t.status||'').includes('强')?'strong-theme':''}"><b>${t.name}</b> <span class="muted">— ${t.status}</span>${t.evidence?`<br><span style="font-size:12px">${typeof t.evidence==='string'?t.evidence:formatEvidenceList(t.evidence)}</span>`:''}</div>`
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

/* =========================
   午盘盘后
========================= */
function renderPostmarket(data) {
  updatePanelMeta("postmarket", data.timestamp);
  const el = document.getElementById("postmarket");
  let html = "";

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
        const evidence = h.evidence ? `<div class="evidence-line"><b>证据：</b>${formatEvidenceList(h.evidence)}</div>` : '';
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
      return `<div class="sentiment-col ${cls}">
        <h3>${title}</h3>
        ${items.length ? items.map(renderEveningItem).join("") : '<div class="empty-sm">暂无</div>'}
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
  const evidence = item.evidence ? `<div class="sentiment-verify">证据：${formatEvidenceList(item.evidence)}</div>` : "";
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
  const evidence = item.evidence ? `<div class="sentiment-verify">证据：${formatEvidenceList(item.evidence)}</div>` : "";
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

  el.innerHTML = topics.map(t => {
    const statusText = String(t.status || "");
    const statusCls = statusText.includes("强化") || statusText.includes("强主线") ? "strong" :
                      statusText.includes("弱化") || statusText.includes("退潮") ? "sentiment" : "";
    const statusBadge = statusCls === "strong" ? "🔥" :
                        statusCls === "sentiment" ? "🔻" : "➖";
    const updatedAt = formatUpdateTime(t.updated_at || t.timestamp || data.timestamp);
    return `<div class="card ${statusCls}">
      <div class="card-head"><b>${t.name}</b></div>
      ${updatedAt ? `<div class="card-updated"><span class="updated-dot"></span>已更新 · ${updatedAt}</div>` : ""}
      <div class="card-body">${statusBadge} ${t.status}${t.action ? ` · ${t.action}` : ""}</div>
      ${t.note ? `<div class="card-body muted">${t.note}</div>` : ""}
    </div>`;
  }).join("");
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
  const sources = data.sources || [];
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
      <div class="source-meta">${escapeHtml(source.role || "")}</div>
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

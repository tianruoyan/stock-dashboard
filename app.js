const FILES = [
  "data/alert.json",
  "data/intraday.json",
  "data/premarket.json",
  "data/midday.json",
  "data/postmarket.json",
  "data/evening-sentiment.json",
  "data/topics.json",
  "data/requirements.json"
];

let cache = {};

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
      if (!cache[file] || cache[file].timestamp !== data.timestamp) {
        cache[file] = data;
        render(file, data);
      }
    } catch (e) {
      console.error("load failed:", file);
    }
  }
  document.getElementById("lastUpdate").innerText = new Date().toLocaleTimeString();
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
  // 指数行
  const idxEl = document.getElementById("intraday-indices");
  if (data.indices) {
    if (Array.isArray(data.indices)) {
      idxEl.innerHTML = data.indices.map(i => {
        const v = i.change_pct || i.pct || 0;
        const cls = v >= 0 ? 'up' : 'down';
        return `<span class="index-item"><b>${i.name}</b> <span class="${cls}">${v > 0 ? '+' : ''}${v.toFixed(2)}%</span></span>`;
      }).join("");
    } else {
      idxEl.innerHTML = Object.entries(data.indices).map(([k, v]) => {
        const cls = v >= 0 ? 'up' : 'down';
        return `<span class="index-item"><b>${k}</b> <span class="${cls}">${v > 0 ? '+' : ''}${v}%</span></span>`;
      }).join("");
    }
  }

  // Codex 格式: 深度分析（main_trends 含 status 或 themes 存在）
  if (data.main_trends && data.main_trends.length && (typeof data.main_trends[0] === 'object' ? data.main_trends[0].status : true)) {
    // 同时显示板块排行（如果有）
    if (data.concept_top5 || data.industry_top5) {
      document.querySelectorAll('.sector-grid').forEach(el => el.style.display = '');
      const analysisEl = document.getElementById('intraday-analysis');
      if (analysisEl) analysisEl.style.display = 'none';
      renderSectorList("concept-top", data.concept_top5, "up");
      renderSectorList("concept-bot", data.concept_bottom5, "down");
      renderSectorList("industry-top", data.industry_top5, "up");
      renderSectorList("industry-bot", data.industry_bottom5, "down");
    }
    renderCodexIntraday(data);
    return;
  }

  // Cola 格式: 概念/行业涨跌榜
  // 先恢复四栏网格
  document.querySelectorAll('.sector-grid').forEach(el => el.style.display = '');
  const analysisEl = document.getElementById('intraday-analysis');
  if (analysisEl) analysisEl.style.display = 'none';

  if (data.concept_top5 || data.industry_top5) {
    renderSectorList("concept-top", data.concept_top5, "up");
    renderSectorList("concept-bot", data.concept_bottom5, "down");
    renderSectorList("industry-top", data.industry_top5, "up");
    renderSectorList("industry-bot", data.industry_bottom5, "down");
    return;
  }

  // 老格式兼容
  if (data.main_trends && data.main_trends.length) {
    renderSectorList("concept-top", data.main_trends, "up");
    ["concept-bot","industry-top","industry-bot"].forEach(id => document.getElementById(id).innerHTML = '<div class="empty-sm">--</div>');
  }
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
        const cls = (t.status||'').includes('强') ? 'strong-theme' : '';
        return `<div class="theme-item ${cls}"><b>${t.name}</b> <span class="muted">— ${t.status}</span><br><span style="font-size:12px">${t.evidence||''}</span></div>`;
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
      const cls = (t.status||'').includes('强') ? 'strong-theme' : (t.status||'').includes('弱') ? 'sentiment' : '';
      const icon = (t.status||'').includes('强') ? '✅' : (t.status||'').includes('弱') ? '🔻' : '➖';
      return `<div class="theme-item ${cls}"><b>${icon} ${t.name}</b> <span class="muted">— ${t.status}</span><br><span style="font-size:12px">${t.evidence||''}</span></div>`;
    }).join('');
    html += '</div>';
  }

  // 情绪详情
  if (data.sentiment && typeof data.sentiment === 'object' && Object.keys(data.sentiment).length > 0) {
    html += '<div class="subsection"><h3>📈 盘面情绪</h3><ul class="news-list">';
    for (const [k, v] of Object.entries(data.sentiment)) {
      if (typeof v === 'string' && v) {
        const label = { market: '大盘', silan_micro: '士兰微', nanda_opto: '南大光电' }[k] || k;
        html += `<li><b>${label}</b>：${v}</li>`;
      }
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
      html += stocks.map(s => `<div class="theme-item" style="font-size:12px;padding:6px 10px;margin-bottom:3px"><b>${s.name}</b> <span class="${(s.pct||0)>=0?'up':'down'}">${(s.pct||0)>0?'+':''}${s.pct}%</span> · ${s.status}${s.risk?` <span class="muted" style="font-size:10px">⚠ ${s.risk}</span>`:''}</div>`).join('');
    }
    html += '</div>';
  }

  // 隐藏四栏网格，显示全宽分析
  const hasSectorData = data.concept_top5 || data.industry_top5;
  if (!hasSectorData) {
    document.querySelectorAll('.sector-grid').forEach(el => el.style.display = 'none');
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
    el.innerHTML = '<div class="empty-sm">--</div>';
    return;
  }
  const cls = dir === 'up' ? 'up' : 'down';
  el.innerHTML = sectors.map((s, i) => {
    const pct = s.change_pct || 0;
    const barW = Math.min(Math.abs(pct) * 5, 100);
    return `<div class="sector-row">
      <span class="rank">${i + 1}</span>
      <span class="sector-name">${s.name || s.sector}</span>
      <span class="sector-pct ${cls}">${pct > 0 ? '+' : ''}${pct}%</span>
      <div class="bar"><div class="bar-fill ${cls}" style="width:${barW}%"></div></div>
    </div>`;
  }).join("");
}

function formatPct(value) {
  if (typeof value !== "number") return "--";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function pctClass(value) {
  return typeof value === "number" && value < 0 ? "down" : "up";
}

function renderMappingChain(items) {
  if (!items || !items.length) return "";
  return '<ul class="news-list mapping-chain">' + items.map(item => {
    if (typeof item === "string") return `<li>${item}</li>`;
    const source = item.source_asset || item.source || item.name || "映射标的";
    const pct = item.change_pct !== undefined ? ` ${formatPct(item.change_pct)}` : "";
    const reason = item.reason ? `：${item.reason}` : "";
    const target = item.a_share_mapping || item.target || item.mapping || "";
    const logic = item.mapping_logic || item.logic || "";
    return `<li><b>${source}${pct}</b>${reason}${target ? `<br><span class="muted">→ ${target}</span>` : ""}${logic ? `<br><span class="muted">逻辑：${logic}</span>` : ""}</li>`;
  }).join("") + '</ul>';
}

/* =========================
   盘前简报
========================= */
function renderPremarket(data) {
  updatePanelMeta("premarket", data.timestamp);
  const el = document.getElementById("premarket");
  let html = "";

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
        html += `<div class="theme-item"><b>${data.market_context.open_style || "待判断"}</b>${data.market_context.sentiment_judgement ? `：${data.market_context.sentiment_judgement}` : ""}</div>`;
      }
      if (data.market_context.benefit_themes) {
        html += '<div class="tag-row">受益：' + data.market_context.benefit_themes.map(s => `<span class="tag">${s}</span>`).join(" ") + '</div>';
      }
      if (data.market_context.risk_points) {
        html += '<div class="tag-row">风险：' + data.market_context.risk_points.map(s => `<span class="tag">${s}</span>`).join(" ") + '</div>';
      }
      html += '</div>';
    }

    // 总结
    if (data.strategy && typeof data.strategy === 'string') {
      html += `<div class="subsection"><h3>📋 盘前研判</h3><div class="theme-item">${data.strategy}</div></div>`;
    }
    if (data.summary) {
      html += `<div class="subsection"><h3>💡 操作思路</h3><div class="theme-item">${data.summary}</div></div>`;
    }

    // 强主线/观察线/风险线 三栏
    if (data.strong_lines || data.watch_lines || data.risk_lines) {
      html += '<div class="subsection"><div class="line-grid">';
      if (data.strong_lines) {
        html += '<div><h3>🔥 强主线</h3><ul class="news-list strong">' + data.strong_lines.map(l => `<li>${l}</li>`).join("") + '</ul></div>';
      }
      if (data.watch_lines) {
        html += '<div><h3>👀 观察线</h3><ul class="news-list">' + data.watch_lines.map(l => `<li>${l}</li>`).join("") + '</ul></div>';
      }
      if (data.risk_lines) {
        html += '<div><h3>⚠️ 风险线</h3><ul class="news-list risk">' + data.risk_lines.map(l => `<li>${l}</li>`).join("") + '</ul></div>';
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
      html += `<div class="theme-item">${data.us_overnight.conclusion}</div>`;
    }
    if (data.us_overnight.indices) {
      html += '<div class="index-row">' + Object.entries(data.us_overnight.indices).map(([name, v]) =>
        `<span class="index-item">${name} <span class="${pctClass(v)}">${formatPct(v)}</span></span>`
      ).join("") + '</div>';
    }
    if (data.us_overnight.reason) {
      html += `<div class="theme-item">${data.us_overnight.reason}</div>`;
    }
    if (data.us_overnight.tech_stocks) {
      html += '<div class="tag-row">重点科技股：' + data.us_overnight.tech_stocks.map(s => `<span class="tag">${typeof s === "string" ? s : `${s.name || s.symbol || ""}${s.change_pct !== undefined ? ` ${formatPct(s.change_pct)}` : ""}`}</span>`).join(" ") + '</div>';
    }
    if (data.us_overnight.japan_korea) {
      html += '<div class="tag-row">日韩早盘：' + data.us_overnight.japan_korea.map(s => `<span class="tag">${typeof s === "string" ? s : `${s.name || s.market || ""}${s.change_pct !== undefined ? ` ${formatPct(s.change_pct)}` : ""}`}</span>`).join(" ") + '</div>';
    }
    if (data.us_overnight.hot_sectors) {
      html += '<div class="tag-row">热点：' + data.us_overnight.hot_sectors.map(s => `<span class="tag">${s}</span>`).join(" ") + '</div>';
    }
    if (data.us_overnight.weak_sectors) {
      html += '<div class="tag-row">弱势：' + data.us_overnight.weak_sectors.map(s => `<span class="tag">${s}</span>`).join(" ") + '</div>';
    }
    if (data.us_overnight.impact_to_a_share) {
      html += `<div class="theme-item">A股影响：${data.us_overnight.impact_to_a_share}</div>`;
    }
    if (data.us_overnight.mapping_chain) {
      html += '<h3>科技映射链</h3>' + renderMappingChain(data.us_overnight.mapping_chain);
    }
    html += '</div>';
  }
  if (data.hk_auction) {
    html += '<div class="subsection"><h3>🇭🇰 港股竞价</h3>';
    if (data.hk_auction.indices) {
      html += '<div class="index-row">' + Object.entries(data.hk_auction.indices).map(([name, v]) =>
        `<span class="index-item">${name} <span class="${pctClass(v)}">${formatPct(v)}</span></span>`
      ).join("") + '</div>';
    }
    if (data.hk_auction.sectors) {
      html += '<div class="tag-row">板块：' + data.hk_auction.sectors.map(s => `<span class="tag">${typeof s === "string" ? s : `${s.name || s.sector || ""}${s.strength ? `：${s.strength}` : ""}`}</span>`).join(" ") + '</div>';
    }
    if (data.hk_auction.stocks) {
      html += '<div class="tag-row">代表股：' + data.hk_auction.stocks.map(s => `<span class="tag">${typeof s === "string" ? s : `${s.name || s.symbol || ""}${s.change_pct !== undefined ? ` ${formatPct(s.change_pct)}` : ""}`}</span>`).join(" ") + '</div>';
    }
    if (data.hk_auction.sentiment) {
      html += `<div class="theme-item">${data.hk_auction.sentiment}</div>`;
    }
    if (data.hk_auction.mapping_chain) {
      html += '<h3>港股映射</h3>' + renderMappingChain(data.hk_auction.mapping_chain);
    }
    html += '</div>';
  }
  if (data.overnight_news) {
    html += '<div class="subsection"><h3>📰 隔夜要闻</h3><ul class="news-list">';
    html += data.overnight_news.map(n => `<li>${typeof n === "string" ? n : n.text || n.title}</li>`).join("");
    html += '</ul></div>';
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
        `<div class="theme-item ${(t.status||'').includes('强')?'strong-theme':''}"><b>${t.name}</b> <span class="muted">— ${t.status}</span>${t.evidence?`<br><span style="font-size:12px">${t.evidence}</span>`:''}</div>`
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
            const pctCls = s.pct >= 0 ? 'up' : 'down';
            return `<span style="font-size:11px;margin-right:8px">${s.name} <span class="${pctCls}">${s.pct>0?'+':''}${s.pct}%</span></span>`;
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
      html += risks.map(r => `<li>${typeof r === "string" ? r : r.text}</li>`).join('');
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
  const summary = data.sentiment_summary || {};
  const counts = summary.counts || {};

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

  if (news.length) {
    html += '<div class="sentiment-grid">';
    html += groups.map(([key, title, cls]) => {
      const items = news.filter(n => (typeof n === "string" ? "中性" : n.sentiment || "中性") === key);
      return `<div class="sentiment-col ${cls}">
        <h3>${title}</h3>
        ${items.length ? items.map(renderEveningItem).join("") : '<div class="empty-sm">暂无</div>'}
      </div>`;
    }).join("");
    html += '</div>';
  }

  el.innerHTML = html || '<div class="empty">晚间舆情待更新</div>';
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

function formatEvidenceList(value) {
  if (Array.isArray(value)) {
    return value.map(v => escapeHtml(typeof v === "string" ? v : `${v.label || v.name || v.title || "证据"}：${v.detail || v.text || v.value || v.source || ""}`)).join('；');
  }
  if (value && typeof value === "object") {
    return escapeHtml(`${value.label || value.name || value.title || "证据"}：${value.detail || value.text || value.value || value.source || ""}`);
  }
  return escapeHtml(value || "");
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
   时间 / 状态
========================= */
function updateTime() {
  document.getElementById("status").innerText = navigator.onLine ? "🟢 LIVE" : "🔴 OFFLINE";
}

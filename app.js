const FILES = [
  "data/alert.json",
  "data/intraday.json",
  "data/premarket.json",
  "data/postmarket.json",
  "data/evening-sentiment.json",
  "data/topics.json"
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
  if (file.includes("postmarket")) renderPostmarket(data);
  if (file.includes("evening"))  renderEvening(data);
  if (file.includes("topics"))   renderTopics(data);
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
                  a.signal_type?.includes("放量") ? '<span class="badge volume">放量</span>' :
                  a.signal_type?.includes("风险") ? '<span class="badge risk">风险</span>' : '';
    const leaders = (a.leaders || []).slice(0, 3).map(l =>
      `<span class="leader">${l.name} <span class="pct ${l.change_pct >= 0 ? 'up' : 'down'}">${l.change_pct > 0 ? '+' : ''}${l.change_pct}%</span></span>`
    ).join(" ");

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
  // 指数行
  const idxEl = document.getElementById("intraday-indices");
  if (data.indices) {
    idxEl.innerHTML = Object.entries(data.indices).map(([k, v]) => {
      const cls = v >= 0 ? 'up' : 'down';
      return `<span class="index-item"><b>${k}</b> <span class="${cls}">${v > 0 ? '+' : ''}${v}%</span></span>`;
    }).join("");
  }

  // Codex 格式: 深度分析（main_trends 含 status/evidence）
  if (data.main_trends && data.main_trends.length && data.main_trends[0].status) {
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

  // 涨停情绪
  if (data.sentiment || data.limit_up_count) {
    const s = data.sentiment || {};
    const lu = s.limit_up_count || data.limit_up_count || 0;
    const ld = s.limit_down_count || data.limit_down_count || 0;
    html += `<div class="subsection"><h3>⚡ 涨停情绪</h3><div class="breadth">涨停 <b>${lu}</b> / 跌停 <b>${ld}</b> · 差值 <span class="up">+${lu-ld}</span> · ${s.limit_ratio||''}${s.interpretation ? `<br><span class="muted">${s.interpretation}</span>` : ''}</div></div>`;
  }

  // 主线分析
  if (data.main_trends) {
    html += '<div class="subsection"><h3>🔥 主线研判</h3>';
    html += data.main_trends.map(t => {
      const cls = (t.status||'').includes('强') ? 'strong-theme' : '';
      return `<div class="theme-item ${cls}"><b>${t.name}</b> <span class="muted">— ${t.status}</span><br><span style="font-size:12px">${t.evidence||''}</span></div>`;
    }).join('');
    html += '</div>';
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
  document.querySelectorAll('.sector-grid').forEach(el => el.style.display = 'none');
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
   盘后复盘
========================= */
function renderPostmarket(data) {
  const el = document.getElementById("postmarket");
  let html = "";

  // === Codex 格式: hotspots + review ===
  if (data.hotspots || data.review) {
    // 一句话总结
    if (data.review?.one_sentence) {
      html += `<div class="subsection"><h3>📋 收盘总结</h3><div class="breadth">${data.review.one_sentence}</div></div>`;
    }

    // 涨跌统计
    if (data.index) {
      html += '<div class="subsection"><h3>📊 涨跌统计</h3><div class="index-row">';
      const idx = data.index;
      const stats = [
        { k: '涨停', v: idx['涨停'] },
        { k: '跌停', v: idx['跌停'] },
        { k: '炸板', v: idx['炸板'] },
        { k: '5%-8%', v: idx['涨幅5%至不足8%'] },
        { k: '8%以上', v: idx['涨幅8%以上'] },
      ].filter(x => x.v !== undefined);
      html += stats.map(s => `<span class="index-item"><b>${s.k}</b> <span class="up">${s.v}</span></span>`).join('');
      html += '</div></div>';
    }

    // 涨停行业分布
    if (data.review?.limit_pool_industries) {
      html += '<div class="subsection"><h3>🏭 涨停行业分布</h3><div class="index-row">';
      html += data.review.limit_pool_industries.slice(0,6).map(i =>
        `<span class="index-item">${i.industry} <b>${i.limit_up_count}</b>家</span>`
      ).join('');
      html += '</div></div>';
    }

    // 主线研判
    if (data.hotspots) {
      html += '<div class="subsection"><h3>🔥 主线研判</h3>';
      html += data.hotspots.map(h => {
        const cls = (h.status||'').includes('强') ? 'strong-theme' : '';
        const reps = (h.representatives||[]).slice(0,6).join('、');
        return `<div class="theme-item ${cls}">
          <b>${h.name}</b> <span class="muted">— ${h.status}</span>
          <br><span style="font-size:12px">${h.count_summary||''}</span>
          ${reps ? `<br><span style="font-size:11px;color:#8B949E">代表：${reps}</span>` : ''}
          ${h.continuity ? `<br><span style="font-size:11px">${h.continuity}</span>` : ''}
          ${h.risk ? `<br><span style="font-size:10px;color:#FF6B6B">⚠ ${h.risk}</span>` : ''}
        </div>`;
      }).join('');
      html += '</div>';
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
  const el = document.getElementById("evening");

  let html = "";

  if (data.news) {
    html += '<ul class="news-list">';
    html += data.news.map(n => {
      const text = typeof n === "string" ? n : n.text || n.title;
      const source = n.source ? `<span class="muted">— ${n.source}</span>` : "";
      const tag = n.tag ? `<span class="tag">${n.tag}</span>` : "";
      return `<li>${tag}${text}${source}</li>`;
    }).join("");
    html += '</ul>';
  }

  el.innerHTML = html || '<div class="empty">晚间舆情待更新</div>';
}

/* =========================
   专题跟踪
========================= */
function renderTopics(data) {
  const el = document.getElementById("topics");
  const topics = data.topics || [];
  if (!topics.length) { el.innerHTML = '<div class="empty">暂无专题跟踪</div>'; return; }

  el.innerHTML = topics.map(t => {
    const statusText = String(t.status || "");
    const statusCls = statusText.includes("强化") || statusText.includes("强主线") ? "strong" :
                      statusText.includes("弱化") || statusText.includes("退潮") ? "sentiment" : "";
    const statusBadge = statusCls === "strong" ? "🔥" :
                        statusCls === "sentiment" ? "🔻" : "➖";
    return `<div class="card ${statusCls}">
      <div class="card-head"><b>${t.name}</b></div>
      <div class="card-body">${statusBadge} ${t.status}${t.action ? ` · ${t.action}` : ""}</div>
      ${t.note ? `<div class="card-body muted">${t.note}</div>` : ""}
    </div>`;
  }).join("");
}

/* =========================
   时间 / 状态
========================= */
function updateTime() {
  document.getElementById("status").innerText = navigator.onLine ? "🟢 LIVE" : "🔴 OFFLINE";
}

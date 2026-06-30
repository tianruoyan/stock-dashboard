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

function loadAlertHistory() {
  try {
    const raw = localStorage.getItem(ALERT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) { return []; }
}

function saveAlertHistory(alerts) {
  const now = Date.now();
  const valid = alerts.filter(a => now - (a._received || 0) < ALERT_TTL);
  const latest = valid.slice(0, MAX_ALERTS);
  localStorage.setItem(ALERT_KEY, JSON.stringify(latest));
  return latest;
}

function mergeAlerts(history, incoming) {
  const now = Date.now();
  const merged = [...history];
  const ids = new Set(history.map(a => a.id));
  for (const a of incoming) {
    if (!ids.has(a.id)) {
      a._received = now;
      merged.unshift(a);
      ids.add(a.id);
    }
  }
  return merged;
}

function renderAlerts(data) {
  const el = document.getElementById("alerts");
  const history = loadAlertHistory();
  const incoming = data.alerts || [];
  const merged = mergeAlerts(history, incoming);
  const saved = saveAlertHistory(merged);
  const now = Date.now();

  if (!saved.length) { el.innerHTML = '<div class="empty">暂无盘中异动</div>'; return; }

  el.innerHTML = saved.map((a, i) => {
    const age = now - (a._received || now);
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
   盘中全景
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

  // 概念涨跌榜
  renderSectorList("concept-top", data.concept_top5, "up");
  renderSectorList("concept-bot", data.concept_bottom5, "down");
  renderSectorList("industry-top", data.industry_top5, "up");
  renderSectorList("industry-bot", data.industry_bottom5, "down");
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

/* =========================
   盘前简报
========================= */
function renderPremarket(data) {
  const el = document.getElementById("premarket");

  let html = "";

  // 美股隔夜
  if (data.us_overnight) {
    html += '<div class="subsection"><h3>🇺🇸 美股隔夜</h3>';
    if (data.us_overnight.indices) {
      html += '<div class="index-row">' + Object.entries(data.us_overnight.indices).map(([name, v]) =>
        `<span class="index-item">${name} <span class="${v >= 0 ? 'up' : 'down'}">${v > 0 ? '+' : ''}${v}%</span></span>`
      ).join("") + '</div>';
    }
    if (data.us_overnight.hot_sectors) {
      html += '<div class="tag-row">热点：' + data.us_overnight.hot_sectors.map(s => `<span class="tag">${s}</span>`).join(" ") + '</div>';
    }
    html += '</div>';
  }

  // 盘前资讯
  if (data.overnight_news) {
    html += '<div class="subsection"><h3>📰 隔夜要闻</h3><ul class="news-list">';
    html += data.overnight_news.map(n => `<li>${typeof n === "string" ? n : n.text || n.title}</li>`).join("");
    html += '</ul></div>';
  }

  // 策略建议
  if (data.strategy) {
    html += '<div class="subsection"><h3>🎯 今日策略</h3><div class="grid">';
    html += data.strategy.map(s => {
      const actionCls = (s.action || "").includes("加") ? "action-buy" :
                        (s.action || "").includes("减") ? "action-sell" : "action-hold";
      return `<div class="card strategy-card ${actionCls}">
        <div class="card-head"><span class="badge ${actionCls}">${s.action}</span></div>
        <div class="card-body">${(s.logic || []).map(l => `· ${l}`).join("<br>")}</div>
        ${s.target ? `<div class="card-body muted">关注：${s.target}</div>` : ""}
      </div>`;
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

  // 指数
  if (data.index) {
    html += '<div class="subsection"><h3>📈 收盘指数</h3><div class="index-row">';
    html += Object.entries(data.index).map(([name, v]) => {
      const label = { shanghai: "上证", shenzhen: "深证", chuangye: "创业板", kechuang: "科创板", hang_seng: "恒生", hstech: "恒生科技" }[name] || name;
      return `<span class="index-item"><b>${label}</b> <span class="${v >= 0 ? 'up' : 'down'}">${v > 0 ? '+' : ''}${v}%</span></span>`;
    }).join("");
    html += '</div></div>';
  }

  // 强主线
  if (data.strong_themes) {
    html += '<div class="subsection"><h3>🔥 强主线</h3><div class="theme-list">';
    html += data.strong_themes.map(t => {
      const s = typeof t === "string" ? { name: t, reason: "" } : t;
      return `<div class="theme-item strong-theme"><b>${s.name}</b>${s.reason ? `<span class="muted"> — ${s.reason}</span>` : ""}</div>`;
    }).join("");
    html += '</div></div>';
  }

  // 观察线
  if (data.watch_themes) {
    html += '<div class="subsection"><h3>👀 观察线</h3><div class="theme-list">';
    html += data.watch_themes.map(t => `<div class="theme-item">${typeof t === "string" ? t : t.name}</div>`).join("");
    html += '</div></div>';
  }

  // 风险提示
  if (data.risks) {
    html += '<div class="subsection"><h3>⚠️ 风险提示</h3><ul class="news-list risk">';
    html += data.risks.map(r => `<li>${typeof r === "string" ? r : r.text || r.desc}</li>`).join("");
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
    const statusCls = t.status === "强化" ? "strong" :
                      t.status === "弱化" ? "sentiment" : "";
    const statusBadge = t.status === "强化" ? "🔥" :
                        t.status === "弱化" ? "🔻" : "➖";
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

const FILES = [
  "data/alert.json",
  "data/intraday.json",
  "data/premarket.json",
  "data/postmarket.json",
  "data/evening-sentiment.json",
  "data/topics.json"
];

let cache = {};

// 初始化
init();

// 30秒轮询
setInterval(updateAll, 30000);

// 时间显示
setInterval(updateTime, 1000);

function init() {
  updateAll();
}

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

  document.getElementById("lastUpdate").innerText =
    new Date().toLocaleTimeString();
}

/* =========================
   渲染入口
========================= */
function render(file, data) {
  if (file.includes("alert")) renderAlerts(data);
  if (file.includes("intraday")) renderText("intraday", data);
  if (file.includes("premarket")) renderText("premarket", data);
  if (file.includes("postmarket")) renderText("postmarket", data);
  if (file.includes("evening")) renderText("evening", data);
  if (file.includes("topics")) renderTopics(data);
}

/* =========================
   盘中异动
========================= */
function renderAlerts(data) {
  const el = document.getElementById("alerts");
  el.innerHTML = "";

  (data.alerts || []).forEach(a => {
    const div = document.createElement("div");

    const cls =
      a.is_old_economy ? "card sentiment" :
      a.signal_type?.includes("交易") ? "card hot" :
      "card";

    div.className = cls;

    div.innerHTML = `
      <b>${a.sector}</b><br/>
      ⏱ ${a.time}<br/>
      ${a.type}<br/>
      ${a.reason || ""}<br/>
      ${a.leaders?.[0]?.name || ""}
    `;

    el.appendChild(div);
  });
}

/* =========================
   文本渲染（简单稳定版）
========================= */
function renderText(id, data) {
  document.getElementById(id).textContent =
    JSON.stringify(data, null, 2);
}

/* =========================
   专题
========================= */
function renderTopics(data) {
  const el = document.getElementById("topics");
  el.innerHTML = "";

  (data.topics || []).forEach(t => {
    const div = document.createElement("div");

    const cls =
      t.status === "强化" ? "card strong" :
      t.status === "弱化" ? "card sentiment" :
      "card";

    div.className = cls;

    div.innerHTML = `
      <b>${t.name}</b><br/>
      ${t.status}<br/>
      ${t.action || ""}
    `;

    el.appendChild(div);
  });
}

/* =========================
   时间
========================= */
function updateTime() {
  document.getElementById("status").innerText =
    navigator.onLine ? "🟢 LIVE" : "🔴 OFFLINE";
}

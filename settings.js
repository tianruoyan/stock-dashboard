/* =========================
   配置面板
========================= */
let settingsData = { watchlist: {}, alerts: {}, topics: [] };
const CONFIG_HOST = window.location.hostname === '127.0.0.1' ? 'http://127.0.0.1:8877' : '';

async function loadSettings() {
  try {
    const [wl, ac, tl] = await Promise.all([
      fetch(CONFIG_HOST + '/config/watchlist.json?t=' + Date.now()).then(r => r.json()),
      fetch(CONFIG_HOST + '/config/alert-config.json?t=' + Date.now()).then(r => r.json()),
      fetch(CONFIG_HOST + '/config/topics-list.json?t=' + Date.now()).then(r => r.json())
    ]);
    settingsData.watchlist = wl;
    settingsData.alerts = ac;
    settingsData.topics = tl.topics || [];
    renderSettingsForms();
  } catch (e) {
    console.log('config load failed, using localStorage');
    const cached = localStorage.getItem('cola-settings');
    if (cached) { settingsData = JSON.parse(cached); renderSettingsForms(); }
  }
}

function renderSettingsForms() {
  const wl = settingsData.watchlist;
  renderStockEditor('small_deng', wl.small_deng?.stocks || []);
  renderStockEditor('old_deng', wl.old_deng?.stocks || []);
  renderStockEditor('watch_only', wl.watch_only?.stocks || []);

  const ac = settingsData.alerts;
  if (ac.small_deng?.momentum) {
    const sm = ac.small_deng.momentum;
    setVal('cfg-sd-avg', sm.avg_change_pct);
    setVal('cfg-sd-dir', sm.direction_ratio);
    setVal('cfg-sd-vol', sm.volume_ratio);
    setVal('cfg-sd-win', sm.window_minutes);
    setVal('cfg-sd-limit', ac.small_deng.limit_move?.limit_count || 2);
  }
  if (ac.old_deng?.strict_move) {
    const om = ac.old_deng.strict_move;
    setVal('cfg-od-avg', om.avg_change_pct);
    setVal('cfg-od-vol', om.volume_ratio);
    setVal('cfg-od-win', om.window_minutes);
    setVal('cfg-od-res', ac.old_deng.resonance?.min_boards || 3);
  }
  if (ac.volume_watch) {
    setVal('cfg-vw-vol', ac.volume_watch.volume_ratio);
    setVal('cfg-vw-dir', ac.volume_watch.direction_ratio);
  }
  renderTopicEditor();
}

function setVal(id, val) { const el = document.getElementById(id); if (el) el.value = val; }
function cfgPoolId(pool) { return pool.replace(/_/g, '-'); }

function renderStockEditor(pool, stocks) {
  const el = document.getElementById('cfg-' + cfgPoolId(pool));
  if (!el) return;
  el.innerHTML = stocks.map((s, i) =>
    '<div class="stock-row">' +
    '<input class="sr-code" value="' + (s.code||'') + '" placeholder="代码">' +
    '<input class="sr-name" value="' + (s.name||'') + '" placeholder="名称">' +
    '<input class="sr-tags" value="' + (s.tags||[]).join(',') + '" placeholder="标签(逗号分隔)">' +
    '<button class="btn-xs btn-del" onclick="removeStock(\'' + pool + '\',' + i + ')">✕</button>' +
    '</div>'
  ).join('');
}

function addStockRow(pool) {
  if (!settingsData.watchlist[pool]) settingsData.watchlist[pool] = { stocks: [] };
  settingsData.watchlist[pool].stocks.push({ code: '', name: '', tags: [] });
  renderStockEditor(pool, settingsData.watchlist[pool].stocks);
}

function removeStock(pool, idx) {
  settingsData.watchlist[pool].stocks.splice(idx, 1);
  renderStockEditor(pool, settingsData.watchlist[pool].stocks);
}

function renderTopicEditor() {
  const el = document.getElementById('cfg-topics');
  if (!el) return;
  el.innerHTML = settingsData.topics.map((t, i) =>
    '<div class="topic-cfg-row">' +
    '<input class="tcr-name" value="' + (t.name||'') + '" placeholder="专题名称">' +
    '<select class="tcr-pri">' +
    '<option value="1"' + (t.priority===1?' selected':'') + '>优先级 1</option>' +
    '<option value="2"' + (t.priority===2?' selected':'') + '>优先级 2</option>' +
    '<option value="3"' + (t.priority===3?' selected':'') + '>优先级 3</option>' +
    '</select>' +
    '<input class="tcr-stocks" value="' + (t.stocks||[]).join(',') + '" placeholder="关注个股">' +
    '<input class="tcr-focus" value="' + (t.focus||[]).join(',') + '" placeholder="关注方向">' +
    '<button class="btn-xs btn-del" onclick="removeTopic(' + i + ')">✕</button>' +
    '</div>'
  ).join('');
}

function addTopicRow() {
  settingsData.topics.push({ name: '', priority: 2, stocks: [], focus: [] });
  renderTopicEditor();
}

function removeTopic(idx) {
  settingsData.topics.splice(idx, 1);
  renderTopicEditor();
}

function collectSettingsFromForms() {
  ['small_deng','old_deng','watch_only'].forEach(pool => {
    const rows = document.querySelectorAll('#cfg-' + cfgPoolId(pool) + ' .stock-row');
    const stocks = [];
    rows.forEach(row => {
      const code = row.querySelector('.sr-code')?.value?.trim();
      const name = row.querySelector('.sr-name')?.value?.trim();
      const tags = (row.querySelector('.sr-tags')?.value || '').split(',').map(t => t.trim()).filter(Boolean);
      if (code || name) stocks.push({ code, name, tags });
    });
    if (!settingsData.watchlist[pool]) settingsData.watchlist[pool] = {};
    settingsData.watchlist[pool].stocks = stocks;
  });

  const sd = settingsData.alerts.small_deng || {};
  sd.momentum = sd.momentum || {};
  sd.momentum.avg_change_pct = parseFloat(document.getElementById('cfg-sd-avg')?.value) || 1.5;
  sd.momentum.direction_ratio = parseFloat(document.getElementById('cfg-sd-dir')?.value) || 0.7;
  sd.momentum.volume_ratio = parseFloat(document.getElementById('cfg-sd-vol')?.value) || 5;
  sd.momentum.window_minutes = parseInt(document.getElementById('cfg-sd-win')?.value) || 3;
  sd.limit_move = { limit_count: parseInt(document.getElementById('cfg-sd-limit')?.value) || 2 };

  const od = settingsData.alerts.old_deng || {};
  od.strict_move = od.strict_move || {};
  od.strict_move.avg_change_pct = parseFloat(document.getElementById('cfg-od-avg')?.value) || 2;
  od.strict_move.volume_ratio = parseFloat(document.getElementById('cfg-od-vol')?.value) || 10;
  od.strict_move.window_minutes = parseInt(document.getElementById('cfg-od-win')?.value) || 3;
  od.resonance = { min_boards: parseInt(document.getElementById('cfg-od-res')?.value) || 3 };

  const vw = settingsData.alerts.volume_watch || {};
  vw.volume_ratio = parseFloat(document.getElementById('cfg-vw-vol')?.value) || 10;
  vw.direction_ratio = parseFloat(document.getElementById('cfg-vw-dir')?.value) || 0.8;

  const topicRows = document.querySelectorAll('#cfg-topics .topic-cfg-row');
  settingsData.topics = [];
  topicRows.forEach(row => {
    const name = row.querySelector('.tcr-name')?.value?.trim();
    if (!name) return;
    settingsData.topics.push({
      name,
      priority: parseInt(row.querySelector('.tcr-pri')?.value) || 2,
      stocks: (row.querySelector('.tcr-stocks')?.value || '').split(',').map(s => s.trim()).filter(Boolean),
      focus: (row.querySelector('.tcr-focus')?.value || '').split(',').map(s => s.trim()).filter(Boolean),
      frequency: '午盘、盘后实时更新'
    });
  });
}

async function saveSettings() {
  document.getElementById('cfg-status').textContent = '保存中...';
  collectSettingsFromForms();
  localStorage.setItem('cola-settings', JSON.stringify(settingsData));

  try {
    const resp = await fetch(CONFIG_HOST + '/_save-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        watchlist: settingsData.watchlist,
        alerts: settingsData.alerts,
        topics: settingsData.topics
      })
    });
    if (resp.ok) {
      document.getElementById('cfg-status').textContent = '✅ 已保存到本地文件';
      return;
    }
  } catch (e) {}

  const wlOut = {};
  ['small_deng','old_deng','watch_only'].forEach(k => { if (settingsData.watchlist[k]) wlOut[k] = settingsData.watchlist[k]; });
  const cfgJson = JSON.stringify({
    'config/watchlist.json': wlOut,
    'config/alert-config.json': settingsData.alerts,
    'config/topics-list.json': { topics: settingsData.topics }
  }, null, 2);
  try {
    await navigator.clipboard.writeText(cfgJson);
    document.getElementById('cfg-status').textContent = '📋 配置已复制到剪贴板，请粘贴给 Cola 写入文件';
  } catch {
    document.getElementById('cfg-status').textContent = '⚠️ 无法保存，请检查网络';
  }
}

function switchSettingsTab(tab) {
  document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.settings-content').forEach(d => d.style.display = 'none');
  const btn = document.querySelector('[onclick="switchSettingsTab(\'' + tab + '\')"]');
  if (btn) btn.classList.add('active');
  const el = document.getElementById('stab-' + tab);
  if (el) el.style.display = 'block';
}

let settingsLoaded = false;
const settingsSection = document.getElementById('section-settings');
if (settingsSection) {
  settingsLoaded = true;
  loadSettings();
}

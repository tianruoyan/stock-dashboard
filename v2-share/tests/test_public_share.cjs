/* Public bundle contract tests using the unchanged July 2026 share data. No browser/pixel assertion. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vm = require('node:vm');
const ROOT = path.resolve(__dirname, '..');
const code = fs.readFileSync(path.join(ROOT, 'v2.js'), 'utf8');
const pages = fs.readdirSync(ROOT).filter(n => /^(?:v2.*|index)\.html$/.test(n));
const fixture = name => JSON.parse(fs.readFileSync(path.join(ROOT, name), 'utf8'));
const BASE = fixture('data/v2/decision-system.json');
const MARKET = fixture('data/v2/v22/market-environment.json');
const CANDIDATE = fixture('data/v2/v22/decision-system-candidate.json');

class Element {
  constructor(attrs = '') {
    this.innerHTML = ''; this.textContent = ''; this.hidden = false; this.disabled = false; this.value = ''; this.dataset = {};
    this.className = attrs.match(/class="([^"]*)"/)?.[1] || '';
    for (const m of attrs.matchAll(/data-([\w-]+)="([^"]*)"/g)) this.dataset[m[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = m[2];
    this.classList = {contains: name => this.className.split(/\s+/).includes(name), toggle() {}, add() {}, remove() {}};
  }
  addEventListener() {} remove() {} reset() {} scrollIntoView() {}
}
function harness(page = 'v2.html', boot = false) {
  const html = fs.readFileSync(path.join(ROOT, page), 'utf8');
  const elements = new Map();
  for (const m of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) elements.set(m[1], new Element(m[0]));
  const calls = []; let fail = false;
  const FixedDate = class extends Date { constructor(...args) { super(...(args.length ? args : ['2026-10-12T11:00:00Z'])); } static now() { return Date.parse('2026-10-12T11:00:00Z'); } };
  const context = { Date: FixedDate, Intl, URL, console, setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {},
    document: { body: new Element(html.match(/<body[^>]*>/)?.[0]), visibilityState: 'visible', getElementById: id => elements.get(id) || null, querySelectorAll: () => [], addEventListener() {} },
    fetch: async (url, options = {}) => {
      calls.push({ url: String(url), method: options.method || 'GET' });
      if (fail) throw Error('INTERNAL_TEST_FAILURE');
      const rel = String(url).split('?')[0];
      assert.ok(rel.startsWith('data/v2/'), rel);
      assert.equal(options.method || 'GET', 'GET');
      assert.ok(fs.existsSync(path.join(ROOT, rel)), 'No request for unpublished asset: ' + rel);
      return { ok: true, json: async () => fixture(rel) };
    }
  };
  context.window = { location: { pathname: '/stock-dashboard/v2-share/' + page }, addEventListener() {} };
  vm.createContext(context);
  vm.runInContext(boot ? code : code.slice(0, code.indexOf('\nprepareShareMode();')), context, {filename:'v2-share/v2.js'});
  return { run: text => vm.runInContext(text, context), put: (key, value) => {context[key] = value;}, el: id => elements.get(id), calls, fail: value => {fail = value;}, html: () => [...elements.values()].map(e => e.textContent + ' ' + e.innerHTML).join('\n') };
}

test('all eight public data assets retain their exact source Git blob SHA', () => {
  const manifest = fixture('tests/public-data-manifest.json');
  assert.equal(manifest.length, 8);
  for (const row of manifest) {
    const bytes = fs.readFileSync(path.join(ROOT, row.path));
    assert.equal(bytes.length, row.size, row.path);
    const hash = crypto.createHash('sha1').update('blob ' + bytes.length + '\0').update(bytes).digest('hex');
    assert.equal(hash, row.sha, row.path);
  }
});
test('index route is exactly the new V2 landing page', () => assert.equal(fs.readFileSync(path.join(ROOT,'index.html'),'utf8'), fs.readFileSync(path.join(ROOT,'v2.html'),'utf8')));
test('public static pages contain no local links, private managers, write forms or hidden personal data inputs', () => {
  assert.doesNotMatch(code, /\/_v2-|127\.0\.0\.1|localhost|method\s*:\s*["'](?:POST|PUT|PATCH|DELETE)/i);
  assert.match(code, /const SHARE_READ_ONLY = true/);
  for (const name of pages) {
    const html = fs.readFileSync(path.join(ROOT,name),'utf8');
    assert.doesNotMatch(html, /127\.0\.0\.1|localhost|<form\b|id="(?:source-manager|watchlist-sync-shadow|portfolio-manager|portfolio-holding-list|cockpit-user-assets)"/, name);
    assert.match(html, /公开只读历史展示/, name);
    assert.match(html, /v2-data-notice/, name);
  }
});
test('all local navigation, script and stylesheet targets exist', () => {
  for (const name of pages) {
    const html = fs.readFileSync(path.join(ROOT,name),'utf8');
    for (const m of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
      const rel = m[1].split(/[?#]/)[0];
      if (!rel || /^https:\/\//.test(rel)) continue;
      if (rel === '../index.html') continue; // Existing production entry outside this isolated bundle.
      assert.ok(fs.existsSync(path.join(ROOT, rel)), name + ': ' + rel);
    }
  }
});
test('all 15 public routes bootstrap with only existing public JSON reads', async () => {
  assert.equal(pages.length, 15);
  for (const page of pages) {
    const h = harness(page, true); await new Promise(r => setTimeout(r, 20));
    assert.ok(h.calls.length > 0, page);
    assert.doesNotMatch(h.html(), /\[object Object\]|undefined|NaN%|INTERNAL_TEST_FAILURE/, page);
    assert.ok(h.calls.every(c => c.method === 'GET' && c.url.startsWith('data/v2/')), page);
  }
});
test('actual historical evidence never becomes a current opportunity or zero-risk signal', () => {
  const h = harness(); h.put('data', BASE); h.run('renderAll(data)');
  assert.match(h.el('home-market-action').textContent, /历史资料/);
  assert.match(h.el('v2-data-notice').textContent, /2026-07-13/);
  assert.equal(h.el('home-risk-count').textContent, '—');
  assert.match(h.el('home-risk-summary').textContent, /无法判断/);
});
test('historical market evidence retains July 17 source time and is visibly folded', () => {
  const h = harness('v2-trading.html'); h.put('data', BASE); h.put('market', MARKET); h.run('renderAll(data);renderEnvironmentV22(market)');
  assert.match(h.el('market-environment').innerHTML, /历史资料（2026-07-17）/);
  assert.match(h.el('market-environment').innerHTML, /historical-content/);
});
test('personal watchlist is unpublished, never reported as an empty user list', async () => {
  const h = harness('v2-stock-pool.html'); await h.run('loadStockPoolLayers()');
  assert.match(h.el('user-asset-layer').innerHTML, /公开分享不提供用户自选/);
  assert.doesNotMatch(h.el('user-asset-layer').innerHTML, /当前清单中没有已确认/);
  assert.match(h.el('stock-pool-v22-summary').innerHTML, /我的关注 <b>—<\/b>/);
  assert.equal(h.calls.length, 1);
});
test('missing share-only phase, tracking and method data are explained without fake data or 404 probes', async () => {
  for (const [page, loader, id] of [['v2-premarket.html','loadCockpitPhaseView','cockpit-phase-view'], ['v2-research.html','loadIndustryTracking','industry-tracking-cards'], ['v2-logic.html','loadLogicCatalog','logic-catalog']]) {
    const h = harness(page); await h.run(loader+'()');
    assert.match(h.el(id).innerHTML, /公开历史分享未包含/);
    assert.equal(h.calls.length,0);
    if (page==='v2-logic.html') {assert.equal(h.el('logic-search').disabled,true);assert.equal(h.el('logic-category-filter').disabled,true);}
  }
});
test('failed main refresh retains prior dates and clears correctly on recovery', async () => {
  const h = harness(); await h.run('loadV2()'); const old=h.el('home-evidence-time').textContent;
  h.fail(true); await h.run('loadV2()'); assert.equal(h.el('home-evidence-time').textContent,old); assert.match(h.el('v2-data-notice').textContent,/更新失败/);
  h.fail(false); await h.run('loadV2()'); assert.doesNotMatch(h.el('v2-data-notice').textContent,/更新失败/);
});
test('renderers do not mutate source data or shadow authorization', () => {
  const h=harness('v2-radar.html'); const data=structuredClone(BASE),candidate=structuredClone(CANDIDATE),before=JSON.stringify({data,candidate});
  h.put('data',data);h.put('candidate',candidate);h.run('renderAll(data);renderDecisionCandidateV22(candidate);setFilter("risk")');
  assert.equal(JSON.stringify({data,candidate}),before);
  assert.equal(data.system.mode,'shadow_only');assert.equal(data.system.production_behavior_changed,false);
});
test('readability CSS and full conditions remain present in public derivative', () => {
  const css=fs.readFileSync(path.join(ROOT,'v2.css'),'utf8');
  assert.match(css,/font-size: 14px !important/); assert.match(css,/overflow-wrap: anywhere/);
  assert.match(css,/\.public-share \.stock-layout \{ grid-template-columns: minmax\(0, 1fr\); \}/);
  const h=harness();const output=h.run('visibleRiskAndInvalidation({risk_factors:["风险一","风险二","风险三","风险四"],invalidation_conditions:["条件一","条件二","条件三","条件四"]})');
  assert.match(output,/风险四/);assert.match(output,/条件四/);
});

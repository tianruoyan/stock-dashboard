/* Isolated DOM-contract regression tests; these are not browser/pixel tests. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const ROOT = path.resolve(__dirname, '..');
const code = fs.readFileSync(path.join(ROOT, 'v2.js'), 'utf8');
const fixture = name => JSON.parse(fs.readFileSync(path.join(ROOT, name), 'utf8'));
const BASE = fixture('data/v2/decision-system.json');
const MARKET = fixture('data/v2/v22/market-environment.json');
const CANDIDATE = fixture('data/v2/v22/decision-system-candidate.json');

class Element {
  constructor(attrs = '') {
    this.innerHTML = ''; this.textContent = ''; this.hidden = /\bhidden\b/.test(attrs); this.value = ''; this.dataset = {};
    this.className = attrs.match(/class="([^"]*)"/)?.[1] || '';
    for (const match of attrs.matchAll(/data-([\w-]+)="([^"]*)"/g)) this.dataset[match[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = match[2];
    this.classList = {contains: name => this.className.split(/\s+/).includes(name), toggle: () => {}, add: () => {}, remove: () => {}};
  }
  addEventListener() {} reset() {} scrollIntoView() {}
}
function harness(page = 'v2.html', now = '2026-10-11T14:00:00Z', boot = false) {
  const html = fs.readFileSync(path.join(ROOT, page), 'utf8');
  const elements = new Map();
  for (const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) elements.set(match[1], new Element(match[0]));
  const document = {body: new Element(html.match(/<body[^>]*>/)?.[0]), visibilityState: 'visible', getElementById: id => elements.get(id) || null, querySelectorAll: () => [], addEventListener() {}};
  let fetchMode = 'ok', calls = 0;
  const FixedDate = class extends Date {constructor(...args) {super(...(args.length ? args : [now]));} static now() {return Date.parse(now);}};
  const context = {document, Date: FixedDate, Intl, console, URL, setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout,
    fetch: async url => {calls++; if (fetchMode === 'reject') throw Error('INTERNAL_FAILURE_TOKEN'); if (fetchMode === 'http') return {ok:false,status:503}; if(fetchMode === 'json') return {ok:true,json:async()=>{throw Error('RAW_JSON_TOKEN')}};
      const rel = String(url).split('?')[0];
      const file = rel === '/_v2-cockpit-phase' ? 'data/v2/v22/cockpit-phase-view.json' : rel;
      if (file.startsWith('/_') || !fs.existsSync(path.join(ROOT,file))) return {ok:false,status:404,json:async()=>({})};
      return {ok:true,json:async()=>fixture(file)};
    }};
  context.window = {location:{pathname:'/'+page}, addEventListener() {}};
  vm.createContext(context);
  vm.runInContext(boot ? code : code.slice(0, code.indexOf('\nbindFilters();')), context, {filename:'v2.js'});
  return {context, elements, el: id=>elements.get(id), run: expression=>vm.runInContext(expression,context), mode: mode=>{fetchMode=mode;}, calls:()=>calls, put:(name,value)=>{context[name]=value;}, html:()=>[...elements.values()].map(e=>e.textContent+' '+e.innerHTML).join('\n')};
}
// A page cycle now has independent per-source deadlines, not one main-file timeout.
function installTimeoutClock(h) {
  let next = 0;
  const timers = new Map();
  h.context.setTimeout = fn => { timers.set(++next, fn); return next; };
  h.context.clearTimeout = id => timers.delete(id);
  return () => { const due = [...timers.values()]; timers.clear(); due.forEach(fn => fn()); };
}
function currentBase() { const data = structuredClone(BASE); data.system.decision_as_of='2026-10-11T15:00:00+08:00'; return data; }
function currentCard(i=1,kind='opportunity') {return {id:'case-'+i,title:'方向'+i,theme:'方向'+i,kind,state:'candidate',conclusion:'等待确认',trigger:'观察事实',action:'继续观察',valid_until:'2026-10-11T23:59:00+08:00',representative_stocks:[],confirm_conditions:['先确认量能或价格','再核对板块扩散','最后核对ETF'],risk_factors:['风险1','风险2','风险3','风险4'],invalidation_conditions:['失效1','失效2','失效3','失效4']};}

test('timestamps include the year and use Beijing time independent of device timezone',()=>{
 const h=harness(); const value=h.run('compactTime("2026-08-25T08:09:57Z")'); assert.match(value,/2026/); assert.match(value,/16:09/); assert.match(h.run('compactTimeWithSeconds("2026-08-25T08:09:57Z")'),/16:09:57/); assert.equal(h.run('compactTime("invalid_time_key")'),'时间未确认');
});
test('generated_at never becomes the evidence date',()=>{const h=harness(); assert.equal(h.run('snapshotInfo({generated_at:"2026-10-11T15:00:00+08:00"}).current'),false);});
test('actual old snapshot does not present current opportunities or zero risk',()=>{
 const h=harness();h.put('data',BASE);h.run('renderAll(data)');assert.match(h.el('home-market-action').textContent,/历史资料/);assert.match(h.el('v2-data-notice').textContent,/2026-08-25/);assert.equal(h.el('home-risk-count').textContent,'—');assert.match(h.el('home-risk-summary').textContent,/无法判断/);assert.match(h.el('home-evidence-label').textContent,/结论依据/);
});
test('market source time remains distinct from decision time',()=>{const h=harness();h.put('base',BASE);h.put('market',MARKET);h.run('renderAll(base);renderEnvironmentV22(market)');assert.match(h.el('home-evidence-time').textContent,/16:09/);assert.match(h.el('home-evidence-label').textContent,/市场资料/);assert.match(h.el('home-market-action').textContent,/历史资料/);});
test('successful main render cannot hide a later failed refresh; recovery clears warning',async()=>{
 const h=harness();await h.run('loadV2()');const old=h.el('home-evidence-time').textContent;h.mode('reject');await h.run('loadV2()');assert.equal(h.el('v2-status').hidden,false);assert.match(h.el('v2-data-notice').textContent,/更新失败.*保留上次资料/);assert.equal(h.el('home-evidence-time').textContent,old);assert.doesNotMatch(h.html(),/INTERNAL_FAILURE_TOKEN/);h.mode('ok');await h.run('loadV2()');assert.doesNotMatch(h.el('v2-data-notice').textContent,/更新失败/);
});
test('initial HTTP/JSON failure leaves no endless home placeholders or raw errors',async()=>{
 for (const mode of ['http','json']) {const h=harness();h.mode(mode);await h.run('loadV2()');assert.match(h.el('home-market-action').textContent,/暂不可用/);assert.match(h.el('home-risk-summary').textContent,/无法判断/);assert.equal(h.el('v2-status').hidden,false);assert.doesNotMatch(h.html(),/RAW_JSON_TOKEN|HTTP 503|undefined|\[object Object\]/);}
});
test('parallel source successes do not erase another source failure',()=>{const h=harness();h.put('data',currentBase());h.run('recordDataStatus("market","市场资料",null,true); renderAll(data)');assert.match(h.el('v2-data-notice').textContent,/市场资料更新失败/);});
test('rerendering a cached candidate cannot clear its failed fetch warning',()=>{const h=harness('v2-radar.html');h.put('candidate',CANDIDATE);h.run('renderDecisionCandidateV22(candidate);recordDataStatus("candidate","机会观察资料",null,true);renderDecisionCandidateV22(candidate)');assert.match(h.el('v2-data-notice').textContent,/更新失败/);});
test('unknown gate remains unknown and does not invent weak market or sentiment facts',()=>{const h=harness();assert.match(h.run('renderEnvironmentGate({})'),/尚未核验/);assert.doesNotMatch(h.run('renderEnvironmentGate({})'),/市场不支持/);assert.equal(h.run('humanText("全市场风险状态和抑制维度限制机会升级。")'),'部分市场条件不满足，暂时只观察。');assert.equal(h.run('humanText("环境门禁等待核验。")'),'市场条件尚未确认，先等待。');});
test('missing risk/invalidations are not described as no risk',()=>{const h=harness();const value=h.run('visibleRiskAndInvalidation({})');assert.match(value,/风险资料暂缺/);assert.match(value,/失效条件尚未记录/);assert.doesNotMatch(value,/没有新增风险/);});
test('all confirmation, risk and invalidation clauses remain available',()=>{
 const h=harness('v2-radar.html');h.put('data',currentBase());h.put('card',currentCard());h.run('renderAll(data);renderValidation([card])');const value=h.el('validation-queue').innerHTML;for (const clause of [...currentCard().confirm_conditions,...currentCard().risk_factors,...currentCard().invalidation_conditions]) assert.ok(value.includes(clause),clause);
});
test('current radar displays required confirmation clauses outside supplementary evidence',()=>{const h=harness('v2-radar.html');h.put('data',currentBase());h.put('card',currentCard());h.run('renderAll(data);renderRadar([card])');const value=h.el('opportunity-risk-radar').innerHTML;assert.ok(value.indexOf('最后核对ETF') < value.indexOf('展开补充依据'));});
test('actual candidate third confirmation condition is retained',()=>{const h=harness('v2-radar.html');h.put('candidate',CANDIDATE);h.run('renderDecisionCandidateV22(candidate)');assert.match(h.el('validation-queue').innerHTML,/板块ETF或指数不再创新低并出现承接/);assert.match(h.el('validation-queue').innerHTML,/历史资料（2026-08-25）/);});
test('risk beyond first five is accessible and filters re-render all source cards',()=>{
 const h=harness('v2-radar.html');h.put('data',currentBase());h.put('cards',Array.from({length:6},(_,i)=>currentCard(i+1,i===5?'risk':'opportunity')));h.run('renderAll(data);renderRadar(cards)');assert.match(h.el('opportunity-risk-radar').innerHTML,/查看其余 1 个方向/);h.run('setFilter("risk")');assert.match(h.el('opportunity-risk-radar').innerHTML,/方向6/);assert.doesNotMatch(h.el('opportunity-risk-radar').innerHTML,/方向1/);h.run('setFilter("all")');assert.match(h.el('opportunity-risk-radar').innerHTML,/方向1/);
});
test('expired candidate current_cases cannot bypass existing valid_until display guard',()=>{const h=harness('v2-radar.html');const card=currentCard();card.valid_until='2026-08-25T15:00:00+08:00';h.put('candidate',{...CANDIDATE,current_cases:[card],history_cases:[]});h.run('renderDecisionCandidateV22(candidate)');assert.doesNotMatch(h.el('opportunity-risk-radar').innerHTML,/方向1/);assert.match(h.el('opportunity-history').innerHTML,/方向1/);});
test('source inputs and authorization flags are never modified by display',()=>{const h=harness('v2-radar.html');const data=structuredClone(BASE);const candidate=structuredClone(CANDIDATE);const before=JSON.stringify({data,candidate});h.put('data',data);h.put('candidate',candidate);h.run('renderAll(data);renderDecisionCandidateV22(candidate);setFilter("risk")');assert.equal(JSON.stringify({data,candidate}),before);});
test('structured prose and malicious text are displayed safely',()=>{const h=harness();assert.equal(h.run('humanText({level:"blocked",strategy:"等待资料"})'),'等待资料');assert.equal(h.run('humanText({technical_key:true})'),'');assert.match(h.run('conditionList("条件",["<img src=x onerror=alert(1)>"])'),/&lt;img/);assert.doesNotMatch(h.run('conditionList("条件",["<img src=x onerror=alert(1)>"])'),/<img/);});
test('every V2 route has the visible date/error notice and current cache version',()=>{for (const name of fs.readdirSync(ROOT).filter(n=>/^v2.*\.html$/.test(n))) {const html=fs.readFileSync(path.join(ROOT,name),'utf8');assert.match(html,/id="v2-data-notice"[^>]*role="status"/,name);assert.match(html,/v2.js\?v=20261012-freshness-recovery/,name);assert.match(html,/v2.css\?v=investor-readability-2/,name);}});
test('historical market and saved phase ready snapshot are visibly dated',()=>{const h=harness('v2-trading.html');h.put('market',MARKET);h.put('phase',fixture('data/v2/v22/cockpit-phase-view.json'));h.run('renderEnvironmentV22(market);renderCockpitPhaseView(phase)');assert.match(h.el('market-environment').innerHTML,/历史资料/);assert.match(h.el('cockpit-phase-view').innerHTML,/历史资料/);assert.match(h.el('cockpit-phase-view').innerHTML,/<details class="historical-content">/);});
test('all V2 routes bootstrap with safe missing private services (no browser used)',async()=>{for (const page of fs.readdirSync(ROOT).filter(n=>/^v2.*\.html$/.test(n))) {const h=harness(page,undefined,true);await new Promise(resolve=>setTimeout(resolve,10));assert.doesNotMatch(h.html(),/\[object Object\]|undefined|NaN%/,page);assert.ok(h.calls()>0,page);}});
test('today target date cannot disguise old, missing, invalid or future evidence',()=>{const h=harness();for(const asOf of ['2026-08-25T16:00:00+08:00','invalid_time_key','2026-10-11T23:00:00+08:00','']){h.put('sample',{trade_date:'2026-10-11',as_of:asOf});assert.equal(h.run('snapshotInfo(sample).current'),false,asOf);}h.put('sample',{trade_date:'2026-10-12',as_of:'2026-10-11T15:00:00+08:00'});assert.equal(h.run('snapshotInfo(sample).current'),false);});
test('quality result does not claim current usefulness or freshness',()=>{const h=harness('v2-governance.html');h.put('data',BASE);h.run('renderAll(data);renderQuality({state:"usable"})');assert.match(h.el('data-quality-gate').innerHTML,/当次资料检查通过/);assert.doesNotMatch(h.el('data-quality-gate').innerHTML,/当前结论可以使用|信息已更新/);});
test('mixed-date home keeps old market and new opportunity evidence distinct',()=>{const h=harness();h.put('data',currentBase());h.put('market',MARKET);h.run('renderAll(data);renderEnvironmentV22(market)');assert.match(h.el('home-market-action').textContent,/市场资料待更新/);assert.equal(h.el('home-risk-count').textContent,'—');});
test('mixed-date home keeps new market and old opportunity evidence distinct',()=>{const h=harness();const market=structuredClone(MARKET);market.trade_date='2026-10-11';market.as_of='2026-10-11T15:00:00+08:00';market.user_view['行情时点']=market.as_of;h.put('data',BASE);h.put('market',market);h.run('renderAll(data);renderEnvironmentV22(market)');assert.match(h.el('home-market-action').textContent,/市场资料已更新，机会仍待核验/);assert.match(h.el('home-risk-summary').textContent,/无法判断/);});
test('invalid numeric quote never becomes NaN or a false zero',()=>{const h=harness();for(const value of [null,'bad','',true]){h.put('quote',{change_pct:value,as_of:'2026-10-11T15:00:00+08:00',source:'公开行情'});assert.match(h.run('renderLayerQuote(quote)'),/行情待核验/);assert.doesNotMatch(h.run('renderLayerQuote(quote)'),/NaN|0.00%/);}});
test('never-resolving request times out, releases lock and recovers next refresh',async()=>{
 const h=harness();await h.run('loadV2()');const old=h.el('home-evidence-time').textContent;const originalFetch=h.context.fetch;const expire=installTimeoutClock(h);h.context.fetch=()=>new Promise(()=>{});const pending=h.run('loadV2()');assert.equal(h.run('v2LoadInFlight'),true);expire();await pending;assert.equal(h.run('v2LoadInFlight'),false);assert.equal(h.el('home-evidence-time').textContent,old);assert.match(h.el('v2-data-notice').textContent,/更新失败/);h.context.fetch=originalFetch;await h.run('loadV2()');assert.equal(h.run('v2LoadInFlight'),false);assert.doesNotMatch(h.el('v2-data-notice').textContent,/更新失败/);
});
test('never-resolving response body times out without poisoning prior data',async()=>{
 const h=harness();await h.run('loadV2()');const expire=installTimeoutClock(h);h.context.fetch=async()=>({ok:true,json:()=>new Promise(()=>{})});const before=h.run('JSON.stringify(v2State)');const pending=h.run('loadV2()');await Promise.resolve();expire();await pending;assert.equal(h.run('v2LoadInFlight'),false);assert.equal(h.run('JSON.stringify(v2State)'),before);
});
test('HTTP 200 error object does not replace previously valid conclusion data',async()=>{
 const h=harness();await h.run('loadV2()');const before=h.run('JSON.stringify(v2State)');h.context.fetch=async()=>({ok:true,json:async()=>({error:'INTERNAL_FAILURE_TOKEN'})});await h.run('loadV2()');assert.equal(h.run('JSON.stringify(v2State)'),before);assert.match(h.el('v2-data-notice').textContent,/更新失败/);assert.doesNotMatch(h.html(),/INTERNAL_FAILURE_TOKEN/);
});
test('first-load timeout shows unavailable state instead of indefinite waiting',async()=>{
 const h=harness();const expire=installTimeoutClock(h);h.context.fetch=()=>new Promise(()=>{});const pending=h.run('loadV2()');expire();await pending;assert.equal(h.run('v2LoadInFlight'),false);assert.equal(h.run('v2State'),null);assert.match(h.el('home-market-action').textContent,/暂不可用/);assert.match(h.el('home-risk-summary').textContent,/无法判断/);assert.match(h.el('v2-data-notice').textContent,/相关结论暂不可用/);assert.doesNotMatch(h.el('v2-data-notice').textContent,/保留上次/);
});
test('late timed-out response cannot overwrite a newer successful refresh',async()=>{
 const h=harness();const originalFetch=h.context.fetch;let resolveOld;const expire=installTimeoutClock(h);h.context.fetch=()=>new Promise(resolve=>{resolveOld=resolve;});const old=h.run('loadV2()');expire();await old;h.context.fetch=async url=>String(url).startsWith('data/v2/decision-system.json') ? {ok:true,json:async()=>currentBase()} : originalFetch(url);await h.run('loadV2()');const after=h.run('JSON.stringify(v2State)');resolveOld({ok:true,json:async()=>structuredClone(BASE)});await new Promise(resolve=>setImmediate(resolve));assert.equal(h.run('JSON.stringify(v2State)'),after);assert.match(h.run('v2State.system.decision_as_of'),/2026-10-11/);assert.doesNotMatch(h.el('v2-data-notice').textContent,/更新失败/);
});
test('request timeout aborts the request when AbortController is available',async()=>{
 const h=harness();let signal;h.context.AbortController=AbortController;const expire=installTimeoutClock(h);h.context.fetch=(_url,options)=>{signal=options.signal;return new Promise(()=>{});};const pending=h.run('loadV2()');expire();await pending;assert.equal(signal.aborted,true);
});
test('phase request timeout uses the bounded saved-data fallback with its historical date',async()=>{
 const h=harness('v2-trading.html');const expire=installTimeoutClock(h);h.context.fetch=async url=>String(url).startsWith('/_v2-cockpit-phase') ? new Promise(()=>{}) : {ok:true,json:async()=>fixture('data/v2/v22/cockpit-phase-view.json')};const pending=h.run('loadCockpitPhaseView()');expire();await pending;assert.match(h.el('cockpit-phase-view').innerHTML,/历史资料/);
});
test('static CSS keeps key body/condition/risk text at least 14px including explicit child overrides',()=>{
 const css=fs.readFileSync(path.join(ROOT,'v2.css'),'utf8');const floor=css.slice(css.indexOf('/* Investor readability floor:'));
 for(const selector of ['.v2-shell p','.v2-shell li','.v2-shell .action-line strong','.v2-shell .investor-conditions > strong','.v2-shell .risk-invalidation-grid strong','.v2-shell .environment-gate span','.v2-shell .stock-chip b']) assert.ok(floor.includes(selector),selector);
 assert.match(floor,/font-size: 14px !important/);assert.match(floor,/p :is\(span, strong, b, em, a\)/);assert.match(floor,/font-size: inherit !important/);assert.match(floor,/white-space: normal !important/);assert.match(floor,/overflow-wrap: anywhere/);
});

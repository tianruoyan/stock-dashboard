/* Deterministic DOM + transport contracts. No browser, sockets, or market collection. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ROOT = path.resolve(__dirname, '..');
const code = fs.readFileSync(path.join(ROOT, 'v2.js'), 'utf8');
const PUBLIC = code.includes('const SHARE_READ_ONLY = true');
const P = 'data/v2/';
const files = {
  decision: P+'decision-system.json', market: P+'v22/market-environment.json', environment: P+'v22/environment-decision.json',
  candidate: P+'v22/decision-system-candidate.json', stockPool: P+'v22/stock-pool-shadow.json', industry: P+'v22/industry-tracking.json',
  replay: P+'v22/replay-index.json', evaluation: P+'v22/model-evaluation.json', comparison: P+'v22/parallel-comparison.json',
  phase: '/_v2-cockpit-phase', fallback: P+'v22/cockpit-phase-view.json', logic: P+'logic-catalog.json',
  audit: P+'v22/watchlist-migration-audit.json', userAssets: '/_v2-user-assets'
};
class Element {
  constructor(attrs = '') {
    this.innerHTML = ''; this.textContent = ''; this.value = ''; this.dataset = {}; this.hidden = false; this.disabled = false;
    this.className = attrs.match(/class="([^"]*)"/)?.[1] || '';
    for (const m of attrs.matchAll(/data-([\w-]+)="([^"]*)"/g)) this.dataset[m[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = m[2];
    this.classList = { contains: name => this.className.split(/\s+/).includes(name), toggle() {}, add() {}, remove() {} };
  }
  addEventListener() {} remove() {} reset() {} scrollIntoView() {}
}
function fixtures(round = 1) {
  const file = n => JSON.parse(fs.readFileSync(path.join(ROOT,n),'utf8'));
  const asOf = '2026-10-12T06:00:00Z';
  const card = { id:'case-1', title:'Direction-'+round, theme:'Research-'+round, kind:'opportunity', state:'confirmed',
    valid_until:'2026-10-12T06:01:00Z', representative_stocks:[], confirm_conditions:['条件'], risk_factors:['风险'], invalidation_conditions:['失效'] };
  const base = file(files.decision); base.system.decision_as_of = asOf; base.opportunity_radar = [{...card,title:'Decision-'+round}]; base.opportunity_history = []; base.validation_queue = [];
  const market = file(files.market); market.as_of = asOf; market.trade_date = '2026-10-12'; market.user_view['行情时点'] = asOf; market.user_view['当前允许'] = 'Market-'+round;
  const environment = file(files.environment); environment.as_of = asOf; environment.trade_date = '2026-10-12'; environment.action_constraint = 'Gate-'+round;
  const candidate = file(files.candidate); candidate.as_of = asOf; candidate.trade_date = '2026-10-12'; candidate.summary = {decision_ready:1}; candidate.current_cases = [card]; candidate.history_cases = []; candidate.validation_cases = [];
  const phase = {availability:'ready',sections:{},source_as_of:asOf,trade_date:'2026-10-12',headline:'Phase-'+round};
  phase.sessions = Object.fromEntries(['premarket','intraday','closing','postmarket','evening','auction'].map(key=>[key,{...phase}]));
  const data = {
    [files.decision]:base, [files.market]:market, [files.environment]:environment, [files.candidate]:candidate,
    [files.stockPool]:{formal_observation:{items:[{name:'Stock-'+round,code:'sh600001'}],near_ready_items:[],active_count:1},temporary_candidates:{items:[],count:0}},
    [files.industry]:{items:[{name:'Industry-'+round,conclusion:'Research-'+round}]},
    [files.replay]:{snapshot_count:round,snapshots:[],trigger_quote_snapshot_count:round},
    [files.evaluation]:{record_count:round,recommendation:{reason:'Evaluation-'+round}},
    [files.comparison]:{v2_baseline:{validation_count:round},v22_candidate:{validation_count:round+1},cutover:{reason:'Comparison-'+round}},
    [files.phase]:phase, [files.fallback]:phase,
    [files.logic]:{entries:[{title:'Method-'+round,category:'方法',summary:'Rule-'+round}],categories:['方法']},
    [files.audit]:{user_view:{'状态':'完整','当前读取数量':round}},
    [files.userAssets]:{'状态':'已读取','用户自选':[{'名称':'User-'+round,'代码':'sh600001'}]}
  };
  return data;
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness(page = 'combined', boot = false) {
  const pages = page === 'combined' ? fs.readdirSync(ROOT).filter(n=>/^v2.*\.html$/.test(n)) : [page];
  const html = pages.map(n=>fs.readFileSync(path.join(ROOT,n),'utf8')).join('\n');
  const elements = new Map();
  for (const m of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) elements.set(m[1], new Element(m[0]));
  if (page==='combined' && elements.has('cockpit-phase-view')) elements.get('cockpit-phase-view').dataset = {};
  let now = Date.parse('2026-10-12T06:00:00Z'), next = 0, data = fixtures();
  const timers = new Map(), intervals = new Map(), docEvents = new Map(), winEvents = new Map(), modes = new Map(), calls = [], late = [];
  const FixedDate = class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } };
  const add = (map, name, fn) => { if (!map.has(name)) map.set(name, []); map.get(name).push(fn); };
  const context = {Date:FixedDate,Intl,URL,console,AbortController,
    setTimeout:(fn,ms)=>{timers.set(++next,{fn,at:now+ms});return next;}, clearTimeout:id=>timers.delete(id),
    setInterval:(fn,ms)=>{intervals.set(++next,{fn,ms});return next;}, clearInterval:id=>intervals.delete(id),
    document:{body:new Element(html.match(/<body[^>]*>/)?.[0]),visibilityState:'visible',getElementById:id=>elements.get(id)||null,querySelectorAll:()=>[],addEventListener:(name,fn)=>add(docEvents,name,fn)},
    fetch:async (url, options = {}) => {
      const name = String(url).split('?')[0], mode = modes.get(name);
      calls.push({name,options});
      if (PUBLIC) {assert.ok(Object.values(files).slice(0,5).concat([files.replay,files.evaluation,files.comparison]).includes(name),name);assert.equal(options.method || 'GET','GET');}
      if (mode==='fetchHang') return new Promise(resolve=>late.push({name,resolve}));
      if (mode==='reject') throw Error('INTERNAL_TEST_ERROR');
      if (mode==='http') return {ok:false,status:503};
      const payload = structuredClone(data[name]);
      return {ok:Boolean(payload),status:payload?200:404,json:async()=>{
        if (mode==='bodyHang') return new Promise(resolve=>late.push({name,resolve}));
        if (mode==='json') throw Error('RAW_JSON_ERROR');
        if (mode==='shape') return {error:'INTERNAL_SCHEMA_ERROR'};
        return payload;
      }};
    }
  };
  context.window = {location:{pathname:'/'+page},addEventListener:(name,fn)=>add(winEvents,name,fn)};
  vm.createContext(context);
  vm.runInContext(boot ? code : code.slice(0, code.indexOf(PUBLIC?'\nprepareShareMode();':'\nbindFilters();')),context);
  const run = text=>vm.runInContext(text,context);
  return {run,context,elements,calls,modes,timers,intervals,docEvents,winEvents,late,
    el:id=>elements.get(id), round:n=>{data=fixtures(n);}, data:()=>data,
    event:async(name,win=false)=>{for(const fn of (win?winEvents:docEvents).get(name)||[])fn();await flush();},
    tick:async ms=>{now+=ms;const due=[...timers.entries()].filter(([,t])=>t.at<=now);for(const [id,t]of due){timers.delete(id);t.fn();}await flush();},
    html:()=>[...elements.values()].map(e=>e.innerHTML+' '+e.textContent).join('\n')};
}

test('two complete rounds refresh every displayed source and keep read-only boundaries',async()=>{
  const h=harness();await h.run('loadV2()');h.round(2);await h.run('loadV2()');
  for(const name of [files.decision,files.market,files.environment,files.candidate,files.stockPool,files.replay,files.evaluation,files.comparison]) assert.equal(h.calls.filter(c=>c.name===name).length,2,name);
  assert.match(h.el('home-market-action').textContent,/Market-2/);assert.match(h.el('opportunity-risk-radar').innerHTML,/Direction-2/);assert.match(h.el('market-environment-v22-decision').innerHTML,/Gate-2/);
  assert.match(h.el('formal-observation-layer').innerHTML,/Stock-2/);assert.match(h.el('v22-learning-summary').innerHTML,/Evaluation-2|Comparison-2/);
  if(!PUBLIC){assert.match(h.el('industry-tracking-cards').innerHTML,/Industry-2/);assert.match(h.el('cockpit-phase-view').innerHTML,/Phase-2/);assert.match(h.el('logic-catalog').innerHTML,/Method-2/);}
  assert.ok(h.calls.every(c=>(c.options.method||'GET')==='GET'));
});

test('one failed source keeps its good cache while siblings publish their new round; recovery clears only its warning',async()=>{
  const h=harness();await h.run('loadV2()');h.round(2);h.modes.set(files.market,'http');await h.run('loadV2()');
  assert.match(h.el('home-market-action').textContent,/Market-1/);assert.match(h.el('opportunity-risk-radar').innerHTML,/Direction-2/);assert.match(h.el('v2-data-notice').textContent,/市场资料更新失败/);
  h.modes.delete(files.market);await h.run('loadV2()');assert.match(h.el('home-market-action').textContent,/Market-2/);assert.doesNotMatch(h.el('v2-data-notice').textContent,/更新失败/);
});

test('failed main decision read does not block independent current market or candidate updates',async()=>{
  const h=harness();await h.run('loadV2()');h.round(2);h.modes.set(files.decision,'reject');await h.run('loadV2()');
  assert.match(h.el('home-market-action').textContent,/Market-2/);assert.match(h.el('opportunity-risk-radar').innerHTML,/Direction-2/);assert.match(h.el('v2-data-notice').textContent,/结论依据更新失败/);
});

for(const mode of ['http','json','shape']) test(mode+' failure never replaces any previously valid source cache',async()=>{
  const h=harness();await h.run('loadV2()');const before=h.run('JSON.stringify([...v2ReadCache].map(([key,value])=>[key,value.data]))');
  for(const {name}of h.calls)h.modes.set(name,mode);if(!PUBLIC)h.modes.set(files.fallback,mode);
  await h.run('loadV2()');assert.equal(h.run('JSON.stringify([...v2ReadCache].map(([key,value])=>[key,value.data]))'),before);assert.match(h.el('v2-data-notice').textContent,/更新失败/);assert.doesNotMatch(h.html(),/INTERNAL_SCHEMA_ERROR|RAW_JSON_ERROR/);
});

for(const mode of ['fetchHang','bodyHang']) test(mode+' is bounded, allows healthy siblings immediately, and recovers next cycle',async()=>{
  const h=harness();await h.run('loadV2()');h.round(2);h.modes.set(files.market,mode);
  const pending=h.run('loadV2()');await flush();assert.match(h.el('opportunity-risk-radar').innerHTML,/Direction-2/);assert.equal(h.run('v2LoadInFlight'),true);
  await h.tick(12000);await pending;assert.equal(h.run('v2LoadInFlight'),false);assert.equal(h.run('v2SourceReads.size'),0);assert.match(h.el('home-market-action').textContent,/Market-1/);
  h.modes.delete(files.market);await h.run('loadV2()');assert.match(h.el('home-market-action').textContent,/Market-2/);
  for(const old of h.late)old.resolve(mode==='fetchHang'?{ok:true,json:async()=>fixtures()[files.market]}:fixtures()[files.market]);await flush();
  assert.match(h.el('home-market-action').textContent,/Market-2/);assert.doesNotMatch(h.el('v2-data-notice').textContent,/更新失败/);
});

test('overlapping timer, focus and visible triggers share the same bounded cycle',async()=>{
  const h=harness();h.modes.set(files.market,'fetchHang');h.run('startRadarAutoRefresh()');const a=h.run('loadV2()'), b=h.run('loadV2()');assert.equal(a,b);
  await h.event('focus',true);await h.event('visibilitychange');for(const {fn}of h.intervals.values())fn();
  assert.equal(h.calls.filter(c=>c.name===files.market).length,1);assert.equal(h.calls.filter(c=>c.name===files.decision).length,1);
  await h.tick(12000);await a;assert.equal(h.run('v2LoadInFlight'),false);assert.equal(h.timers.size,0);
});

test('unchanged files and failed reads still expire displayed opportunities and date warnings',async()=>{
  const h=harness();await h.run('loadV2()');assert.match(h.el('opportunity-risk-radar').innerHTML,/Direction-1/);
  await h.tick(61000);await h.run('loadV2()');assert.doesNotMatch(h.el('opportunity-risk-radar').innerHTML,/Direction-1/);assert.match(h.el('opportunity-history').innerHTML,/Direction-1/);
  for(const {name}of h.calls)h.modes.set(name,'reject');if(!PUBLIC)h.modes.set(files.fallback,'reject');
  await h.tick(24*60*60*1000);await h.run('loadV2()');assert.match(h.el('market-environment').innerHTML,/历史资料/);assert.match(h.el('v2-data-notice').textContent,/更新失败/);assert.equal(h.el('home-risk-count').textContent,'—');
});

test('every route owns one timer, pauses while hidden, and restarts once after BFCache pageshow',async()=>{
  for(const page of fs.readdirSync(ROOT).filter(n=>/^v2.*\.html$/.test(n))){
    const h=harness(page,true);await flush();assert.equal(h.intervals.size,1,page);h.run('startRadarAutoRefresh()');assert.equal(h.intervals.size,1,page);
    h.context.document.visibilityState='hidden';await h.event('visibilitychange');assert.equal(h.intervals.size,0,page);const before=h.calls.length;await h.event('focus',true);assert.equal(h.calls.length,before,page);
    h.context.document.visibilityState='visible';await h.event('visibilitychange');assert.equal(h.intervals.size,1,page);assert.ok(h.calls.length>before,page);
    await h.event('pagehide',true);assert.equal(h.intervals.size,0,page);await h.event('pageshow',true);assert.equal(h.intervals.size,1,page);
    h.run('startRadarAutoRefresh()');assert.equal(h.docEvents.get('visibilitychange').length,1,page);assert.equal(h.winEvents.get('pageshow').length,1,page);
  }
});

test('failed learning source leaves its own missing value explicit while other results update',async()=>{
  const h=harness();h.modes.set(files.evaluation,'http');await h.run('loadV2()');assert.match(h.el('v22-learning-summary').innerHTML,/评估资料暂不可用/);assert.match(h.el('v22-learning-summary').innerHTML,/Comparison-1/);
  h.round(2);h.modes.delete(files.evaluation);await h.run('loadV2()');assert.match(h.el('v22-learning-summary').innerHTML,/Evaluation-2/);
});

if(PUBLIC)test('public reader rejects nonallowlisted URLs before sending a request',async()=>{
  const h=harness();for(const url of ['/private.json','https://example.com/data.json',P+'v22/cockpit-phase-view.json'])await assert.rejects(h.run('readV2Json('+JSON.stringify(url)+')'));assert.equal(h.calls.length,0);
});
else test('two sequential hung phase sources cannot hold the cycle or suppress stock pool updates',async()=>{
  const h=harness();h.modes.set(files.phase,'fetchHang');h.modes.set(files.fallback,'bodyHang');const pending=h.run('loadV2()');await flush();assert.match(h.el('formal-observation-layer').innerHTML,/Stock-1/);
  await h.tick(12000);await h.tick(12000);await pending;assert.equal(h.run('v2LoadInFlight'),false);assert.match(h.el('cockpit-phase-view').innerHTML,/读取失败/);assert.equal(h.timers.size,0);
  h.modes.clear();await h.run('loadV2()');assert.match(h.el('cockpit-phase-view').innerHTML,/Phase-1/);
});


test('missing pool is unavailable rather than a zero count even when other sources succeed',async()=>{
  const h=harness();h.modes.set(files.stockPool,'http');await h.run('loadV2()');
  assert.equal(h.run('v22StockPool'),null);assert.match(h.el('formal-observation-layer').innerHTML,/暂不可用/);assert.match(h.el('temporary-candidate-layer').innerHTML,/暂不可用/);
  assert.doesNotMatch(h.el('stock-pool-v22-summary').innerHTML,/正式观察 <b>0/);
  h.modes.delete(files.stockPool);await h.run('loadV2()');assert.match(h.el('formal-observation-layer').innerHTML,/Stock-1/);
});

test('missing required structure and nested null rows never overwrite good state',async()=>{
  const h=harness();await h.run('loadV2()');const before=h.run('JSON.stringify(v2State)');
  h.data()[files.decision].source_registry=[null];h.data()[files.market].dimensions=[null];h.data()[files.stockPool].formal_observation={};
  await h.run('loadV2()');assert.equal(h.run('JSON.stringify(v2State)'),before);assert.match(h.el('home-market-action').textContent,/Market-1/);assert.match(h.el('formal-observation-layer').innerHTML,/Stock-1/);
  assert.equal(h.run('dataReadStatus.get("decision").failed'),true);assert.equal(h.run('dataReadStatus.get("market").failed'),true);assert.equal(h.run('dataReadStatus.get("stockPool").failed'),true);
});

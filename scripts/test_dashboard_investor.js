#!/usr/bin/env node
// Deterministic DOM and network regression tests; no external requests or browser sockets.
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = path.resolve(__dirname, '..');
const smoke = fs.readFileSync(path.join(__dirname, 'smoke_dashboard_runtime.js'), 'utf8');
const dom = { require, __dirname, console };
vm.createContext(dom);
vm.runInContext(smoke.slice(0, smoke.indexOf('async function main()')) + '\nthis.FakeDocument = FakeDocument;', dom);
const document = new dom.FakeDocument(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'));
let mode = 'ok', requests = [], release, timerId = 0;
let now = Date.parse('2026-10-11T21:00:00+08:00');
const timers = new Map(), errors = [];
const disk = file => JSON.parse(fs.readFileSync(path.join(ROOT, file), 'utf8'));
const Clock = class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } };
const context = {
  document, navigator: {onLine: true}, Date: Clock, Intl, JSON, Math, Number, String, Array, Object, RegExp, Set, Map, Promise, URL, AbortController,
  console: {log() {}, warn() {}, error(...args) { errors.push(args.map(String).join(' ')); }},
  localStorage: {store: new Map(), getItem(k) { return this.store.get(k) || null; }, setItem(k,v) {this.store.set(k,String(v));}, removeItem(k) {this.store.delete(k);}},
  setInterval() {return 0;}, clearInterval() {},
  setTimeout(fn, ms) {const id=++timerId;timers.set(id,{fn,ms});return id;}, clearTimeout(id) {timers.delete(id);},
  fetch: async (url, options) => {
    const file = url.split('?')[0]; requests.push({file, options});
    if (mode === 'offline') throw new Error('offline');
    if (mode === 'hang' && file === 'data/alert.json') await new Promise(resolve => release = resolve);
    if (file === 'data/intraday.json') {
      if (mode === '503') return {ok:false,status:503,json:async()=>({error:'unavailable'})};
      if (mode === 'malformed') return {ok:true,status:200,json:async()=>{throw new SyntaxError('invalid JSON');}};
      if (mode === 'error-payload') return {ok:true,status:200,json:async()=>({error:'unavailable'})};
      if (mode === 'bad-shape') return {ok:true,status:200,json:async()=>({indices:'not an array',timestamp:'2026-10-11T10:00:00+08:00'})};
      if (mode === 'null') return {ok:true,status:200,json:async()=>null};
      if (mode === 'body-hang') return {ok:true,status:200,json:()=>new Promise(resolve => release=()=>resolve(disk(file)))};
    }
    return {ok:true,status:200,json:async()=>disk(file)};
  }
};
context.window=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'app.js'),'utf8').replace(/^init\(\);$/m,''), context);
const run = () => context.updateAll({scheduleNext:true});
const read = code => vm.runInContext(code, context);
const tick = async () => {for(let i=0;i<12;i++) await Promise.resolve();};
const fireTimeouts = () => {for(const [id,t] of [...timers]) if(t.ms===12000) {timers.delete(id);t.fn();}};
const text = html => html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ');
let checks=0;
function check(value, label) {assert.ok(value,label);checks++;}
(async () => {
  await run();
  const old = JSON.stringify(context.cached('data/intraday.json'));
  const oldHtml = document.getElementById('intraday-analysis').innerHTML;
  check(requests.length===22,'all 22 files loaded');
  check(errors.length===0,'normal render without errors');
  check([...timers.values()].some(t=>t.ms===300000),'weekend refresh rescheduled');
  check(requests.every(r=>r.options.signal),'all fetches have abort signal');
  check(document.getElementById('lastUpdate').innerText.includes('页面检查'),'page check time clearly named');
  for(const failure of ['503','malformed','error-payload','bad-shape','null','offline']) {
    mode=failure; await run();
    check(JSON.stringify(context.cached('data/intraday.json'))===old,`${failure}: valid cache preserved`);
    check(document.getElementById('intraday-analysis').innerHTML===oldHtml,`${failure}: quote panel preserved`);
    check(document.getElementById('refresh-notice').textContent.includes('上次有效结果'),`${failure}: visible retry notice`);
    check([...timers.values()].some(t=>t.ms===300000),`${failure}: refresh rescheduled`);
    mode='ok';await run();
    check(!document.getElementById('refresh-notice').textContent,`${failure}: recovery clears notice`);
  }
  for(const hang of ['hang','body-hang']) {
    mode=hang;requests=[];let finished=false;
    const pending=run().then(()=>finished=true);
    await tick();
    check(requests.length===22,`${hang}: one hung request does not block other requests`);
    check(!finished,`${hang}: awaiting finite timeout`);
    const count=requests.length;const repeated=run();await tick();
    check(requests.length===count,`${hang}: repeated refresh is single-flight`);
    fireTimeouts();await pending;await repeated;
    check(finished,`${hang}: request timeout completes refresh`);
    check([...timers.values()].some(t=>t.ms===300000),`${hang}: next refresh scheduled`);
    check(JSON.stringify(context.cached('data/intraday.json'))===old,`${hang}: cached quote retained`);
    mode='ok';await run();release();await tick();
    check(read('loadFailures.size')===0,`${hang}: recovery succeeds, late completion cannot mark failure`);
    check(JSON.stringify(context.cached('data/intraday.json'))===old,`${hang}: late completion cannot overwrite cache`);
  }
  const original=context.renderGlobalDecisionModules;
  context.renderGlobalDecisionModules=()=>{throw new Error('render failure');};
  await assert.rejects(run(),/render failure/);checks++;
  check([...timers.values()].some(t=>t.ms===300000),'render exception still reschedules');
  context.renderGlobalDecisionModules=original;await run();
  // Fixed synthetic plan: daily production files may omit or reshape optional fields.
  // Coverage of today's actual payload belongs to smoke_dashboard_runtime.js.
  const mapping = (market, coreCounts, elasticCounts) => coreCounts.map((count,index) => ({
    theme:`${market}测试方向${index+1}`, read:`${market}测试方向${index+1}的观察说明`,
    core:Array.from({length:count},(_,n)=>`${market}重点样本${index+1}-${n+1}`),
    elastic:Array.from({length:elasticCounts[index]},(_,n)=>`${market}关联样本${index+1}-${n+1}`),
    ...(market==='A股'?{pressure:[`${market}方向${index+1}的风险提示`]}:{})
  }));
  const plan={
    date:'2026-10-12',trade_date:'2026-10-12',timestamp:'2026-10-11T20:00:00+08:00',analysis_time:'2026-10-11T20:00:00+08:00',
    summary:'测试预案：等待后续资料确认。',
    a_share_mapping:mapping('A股',[4,5,5,4,4],[3,3,4,2,3]),hk_mapping:mapping('港股',[3,2,3],[2,2,1]),
    opening_plan:Array.from({length:5},(_,n)=>`开盘观察步骤${n+1}`),
    action_conditions:Array.from({length:3},(_,n)=>`继续观察的条件${n+1}`),
    invalidation_conditions:Array.from({length:3},(_,n)=>`原判断失效的条件${n+1}`),
    weekend_news:Array.from({length:5},(_,n)=>({text:`测试消息${n+1}`,source:'测试来源'})),
    strategy:[{action:'等待确认',logic:['本地V2状态为risk_release']}],
    risk_lines:['本地V2状态为risk_release'],strong_lines:[],watch_lines:[]
  };
  context.renderPremarket(plan);
  let html=document.getElementById('premarket').innerHTML;
  for(const key of ['opening_plan','action_conditions','invalidation_conditions']) for(const value of plan[key]) check(html.includes(context.escapeHtml(value)),`${key}: ${value}`);
  for(const key of ['a_share_mapping','hk_mapping']) for(const row of plan[key]) {
    check(html.includes(context.escapeHtml(row.theme)),`${key} theme visible`);
    check(html.includes(context.escapeHtml(row.read)),`${key} rationale visible`);
    for(const name of [...row.core,...row.elastic,...(row.pressure||[])]) check(html.includes(context.escapeHtml(name)),`${key} company/risk visible`);
  }
  for(const item of plan.weekend_news) check(html.includes(context.escapeHtml(item.text)),'weekend news accessible');
  check(html.includes('2026-10-12') && html.includes('待开盘验证'),'future plan correctly labeled');
  check(html.includes('待竞价') && !html.includes('涨停 <b>0</b>'),'missing auction data not fabricated zero');
  check(!/risk_release|本地V2|waiting_monday_preopen_validation|undefined|\[object Object\]/.test(html),'investor text without raw status keys');
  check(context.premarketPlanState({...plan,trade_date:'2026-02-30'}).state==='unknown','invalid target date not accepted');
  check(context.premarketPlanState({...plan,timestamp:'2026-10-13T10:00:00+08:00',analysis_time:'2026-10-13T10:00:00+08:00'}).state==='uncertain','future analysis time not accepted as pending plan');
  now=Date.parse('2026-10-12T09:00:00+08:00');context.renderPremarket(plan);html=document.getElementById('premarket').innerHTML;
  check(html.includes('仍需竞价和开盘确认'),'Monday plan remains unconfirmed');
  now=Date.parse('2026-10-12T14:00:00+08:00');context.renderPremarket(plan);
  check(document.getElementById('premarket').innerHTML.includes('盘前预案回看'),'expired stage properly labeled');
  context.renderPremarket({summary:'仅有摘要'});
  check(document.getElementById('premarket').innerHTML.includes('仅有摘要') && document.getElementById('premarket').innerHTML.includes('统计待补充'),'missing fields render useful empty state');
  check(context.currentRefreshIntervalMs(new Date('2026-10-12T01:30:00Z'))===30000,'refresh uses Shanghai clock');
  check(context.inferSessionPhaseByTime(new Date('2026-10-12T02:00:00Z'))==='morning','phase uses Shanghai clock');
  check(!context.renderMiddayDecision({historical_backfill:true,evaluation_eligible:false}).includes('看1个信号'),'historical midday not current signal');
  check(context.renderMiddayDecision({historical_backfill:true,evaluation_eligible:false}).includes('历史记录'),'historical midday explanation visible');
  now=Date.parse('2026-10-11T21:00:00+08:00');await run();
  read(`for (const file of ['data/intraday.json','data/watchlist-quotes.json','data/postmarket.json']) cache[file] = {...cache[file], market_data_as_of:'2026-10-09T15:00:00+08:00'};`);
  context.renderDashboardControl();
  const control=text(document.getElementById('dashboard-control').innerHTML);
  check(control.includes('上次观察记录') && control.includes('10-09'),'historical cards explicitly dated');
  check(!control.includes('待映射') && !control.includes('优先方向 盘中市场状态'),'generic market summary not priority sector');
  const shell=fs.readFileSync(path.join(ROOT,'index.html'),'utf8');
  check(!shell.includes('Terminal') && shell.includes('维护与诊断'),'investor title and separated diagnostics');
  check(!/undefined|\[object Object\]|NaN/.test(document.body.collectHtml()),'no broken text in rendered output');
  check(context.sectionBadgeView({id:'premarket'},{session_relevance:'upcoming',freshness_status:'pending',session_action:'预案已备好，等待确认',session_reason:'用于2026-10-12'}).action.includes('预案已备好'),'pending plan badge not treated as missing');
  check(context.sectionBadgeView({id:'premarket'},{session_relevance:'upcoming',freshness_status:'future'}).action==='时间待核对','future time overrides pending plan badge');
  check(context.premarketPlanState({...plan,timestamp:'2026-10-13T10:00:00+08:00'}).state==='uncertain','future timestamp cannot hide behind older analysis time');
  check(context.premarketPlanState({...plan,date:'2026-10-13'}).state==='unknown','conflicting plan dates stay unconfirmed');
  check(context.userFacingText('成交放大>=5x、同向占比>=70%')==='成交放大至少5倍、同向占比不低于70%','threshold wording preserves exact values');
  for (const invalid of ['', null, 20261012]) check(context.premarketPlanState({...plan,trade_date:invalid}).state==='unknown','invalid explicit trade_date does not fall back to date');
  const css = fs.readFileSync(path.join(ROOT,'style.css'),'utf8');
  const readingFloor = css.slice(css.indexOf('/* Investor reading floor:'));
  const floorBlock = readingFloor.slice(0,readingFloor.indexOf('}')+1);
  for (const selector of ['.panel .card-body','.panel .premarket-points li','.panel .premarket-points.compact li','.panel .news-list li','.panel .sentiment-verify','.panel .watch-line b','.panel .risk-rule-row span','.panel .radar-detail','.panel .decision-card > span:not(.decision-label)']) {
    check(floorBlock.includes(selector) && /font-size:\s*14px/.test(floorBlock),`CSS static reading floor: ${selector}`);
  }
  check(/overflow-wrap:\s*anywhere/.test(floorBlock) && /min-width:\s*0/.test(floorBlock),'CSS static conditions wrap without minimum-width overflow');
  check(readingFloor.includes('.panel .control-strip { grid-template-columns: 1fr; }'),'CSS static mobile cards have one column');
  mode='offline';read('cache = {}');await run();
  check(document.getElementById('refresh-notice').textContent.includes('暂未获取到数据'),'first-load failure explains no data');
  check(!document.getElementById('refresh-notice').textContent.includes('保留上次'),'first-load failure does not invent previous cache');
  mode='ok';await run();
  check(read('FILES.every(file => !!cached(file))'),'first-load failure recovers all files');
  console.log(`PASS ${checks} assertions: refresh failures, recovery, plan dates, complete conditions and investor rendering.`);
})().catch(error=>{console.error(error);process.exitCode=1;});

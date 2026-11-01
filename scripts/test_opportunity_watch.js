#!/usr/bin/env node
// Synthetic fixtures and fake DOM only. Never write them to dashboard data.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ROOT = path.resolve(__dirname, '..');
const smoke = fs.readFileSync(path.join(__dirname, 'smoke_dashboard_runtime.js'), 'utf8');
const fixture = {require, __dirname, console};
vm.createContext(fixture);
vm.runInContext(smoke.slice(0, smoke.indexOf('async function main()')) + '\nthis.FakeDocument = FakeDocument;', fixture);
const document = new fixture.FakeDocument(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'));
let now = Date.parse('2026-10-22T10:10:00+08:00');
const Clock = class extends Date { constructor(...args) {super(...(args.length ? args : [now]));} static now() {return now;} };
const context = {document, Date:Clock, Intl, console, setInterval(){}, setTimeout(){}, clearInterval(){}, clearTimeout(){},
  localStorage:{getItem(){return null;},setItem(){},removeItem(){}}};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8').replace(/^init\(\);$/m,''), context);
const read = code => vm.runInContext(code, context);
const put = (file, data) => read(`cache[${JSON.stringify(file)}] = ${JSON.stringify(data)}`);
put('config/cn-market-calendar.json', JSON.parse(fs.readFileSync(path.join(ROOT,'config/cn-market-calendar.json'),'utf8')));
const rows = [
  {name:'新易盛',code:'sz300502',change_pct:-9,quote_time:'2026-10-22T10:06:03+08:00',source:'测试行情'},
  {name:'中际旭创',code:'sz300308',change_pct:-6,quote_time:'2026-10-22T10:06:04+08:00',source:'测试行情'}
];
const item = {theme:'CPO/光模块',status:'risk_observation',priority:'high',watch_stocks:['新易盛','中际旭创'],
  assessment:'代表股明显走弱，先看下跌风险，暂不列为优先机会。', representative_quotes:rows,
  last_checked_at:'2026-10-22T10:10:00+08:00',confirm_rules:['等待止跌并与板块同步回升'],invalidate_rules:['继续下探时不按修复机会看待']};
const report = {schema_version:2,current_signal_date:'2026-10-22',timestamp:'2026-10-22T10:10:00+08:00',items:[item]};
put('data/opportunity-watch.json',report);put('data/watchlist-quotes.json',{stocks:rows});
let checks=0;const check=(value,label)=>{assert.ok(value,label);checks++;};
let html=context.renderOpportunityWatchQueue();
check(html.includes('盘中跟踪 · 观察与风险'),'intraday title no longer says premarket');
check(html.includes('风险观察') && html.includes('暂不列为优先机会'),'risk is explicit');
for (const value of ['300502','300308','-9.00%','-6.00%','测试行情']) check(html.includes(value),`actual quote evidence ${value}`);
check(!/高优先|中优先|等待触发的盘前重点/.test(html),'legacy priority never leaks');
check(!/risk_observation|last_checked_at|source_as_of|undefined|NaN|\[object Object\]/.test(html),'no engineering states');
const staleAlert={sector:'CPO/光模块',reason:'CPO/光模块',time:'09:30:00',valid_until:'2026-10-22T09:35:00+08:00'};
check(context.renderOpportunityWatchQueue([staleAlert]).includes('风险观察'),'old alerts cannot suppress current risk');
now=Date.parse('2026-10-22T10:27:00+08:00');html=context.renderOpportunityWatchQueue();
check(html.includes('等待行情核对') && !html.includes('先看下跌风险'),'clock expiry withdraws old risk conclusion');
check(!html.includes('-9.00%'),'expired quote is not presented as current');
now=Date.parse('2026-10-22T10:10:00+08:00');
put('data/watchlist-quotes.json',{stocks:rows.map(q=>({...q,change_pct:3,quote_time:'20261022100959'}))});
html=context.renderOpportunityWatchQueue();
check(html.includes('等待行情核对') && !html.includes('先看下跌风险'),'new quote withdraws old conclusion until rechecked');
let rerenders=0;context.renderWatchlistDecision=()=>{};context.rerenderAlertsIfLoaded=()=>{rerenders++;};
context.render('data/watchlist-quotes.json',{});check(rerenders===1,'quote update rerenders queue');
put('data/watchlist-quotes.json',{stocks:[]});
put('data/opportunity-watch.json',{...report,items:[{...item,status:'waiting',priority:'high',representative_quotes:[],assessment:'等待确认'}]});
check(!context.renderOpportunityWatchQueue().includes('高优先'),'unconfirmed data cannot restore high priority');
put('data/opportunity-watch.json',{...report,schema_version:1});
check(context.renderOpportunityWatchQueue()==='','old schema is not shown as current');
put('data/opportunity-watch.json',{...report,current_signal_date:'2026-10-19'});
check(context.renderOpportunityWatchQueue()==='','fresh build timestamp cannot renew old trading date');
put('data/opportunity-watch.json',report);
now=Date.parse('2026-10-22T15:00:00+08:00');
check(context.renderOpportunityWatchQueue()==='','closed session no longer waits for current trigger');
now=Date.parse('2026-10-23T10:10:00+08:00');
check(context.renderOpportunityWatchQueue()==='','next day clears yesterday queue');
now=Date.parse('2026-10-22T09:20:00+08:00');
put('data/opportunity-watch.json',{...report,timestamp:'2026-10-22T09:20:00+08:00',items:[{...item,
  status:'premarket_watch',assessment:'盘前关注，开盘再看',representative_quotes:[],last_checked_at:'2026-10-22T09:20:00+08:00'}]});
check(context.renderOpportunityWatchQueue().includes('盘前关注 · 等开盘确认'),'preopen label distinct');
now=Date.parse('2026-10-22T09:30:00+08:00');
check(context.renderOpportunityWatchQueue().includes('等待行情核对'),'market open requires new evaluation');
console.log(`PASS ${checks} opportunity watch UI assertions.`);

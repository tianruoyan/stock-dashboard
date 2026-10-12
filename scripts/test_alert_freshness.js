#!/usr/bin/env node
// Clock, lifecycle and stale-cache regressions. No sockets or live market requests.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ROOT = path.resolve(__dirname, '..');
const smoke = fs.readFileSync(path.join(__dirname, 'smoke_dashboard_runtime.js'), 'utf8');
const fixture = { require, __dirname, console };
vm.createContext(fixture);
vm.runInContext(smoke.slice(0, smoke.indexOf('async function main()')) + '\nthis.FakeDocument = FakeDocument;', fixture);
const document = new fixture.FakeDocument(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'));
const handlers = {}, timers = new Map();
let now = Date.parse('2026-10-12T10:04:00+08:00'), id = 0, count = 0, offline = false;
const Clock = class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } };
const row = { id:'20261012-test', time:'10:00:00', sector:'测试方向', alert_class:'opportunity', type:'放量拉升',
  confirmation_level:'confirmed', valid_until:'2026-10-12T10:05:00+08:00',
  quote_audit:{provider:'测试源',quote_time:'2026-10-12T10:00:00+08:00',sanity_checks:{cross_source_verified:true},secondary_verification:{state:'passed'}}, leaders:[] };
let payload = {timestamp:'2026-10-12T10:04:00+08:00',source_status:'monitor_live',alerts:[row]};
const context = { document, navigator:{onLine:true},Date:Clock,Intl,JSON,Math,Number,String,Array,Object,RegExp,Set,Map,Promise,URL,AbortController,
  console:{log(){},warn(){},error(){}},localStorage:{getItem(){return null;},setItem(){},removeItem(){}},
  setInterval(){return 0;},clearInterval(){},setTimeout(fn,ms){timers.set(++id,{fn,ms});return id;},clearTimeout(i){timers.delete(i);},
  addEventListener(name,fn){handlers[name]=fn;},
  fetch:async()=>{count++;if(offline) throw Error('offline');return {ok:true,json:async()=>JSON.parse(JSON.stringify(payload))};}
};
context.window=context; document.addEventListener=(name,fn)=>handlers[name]=fn;
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(ROOT,'app.js'),'utf8').replace(/^init\(\);$/m,''),context);
const read=code=>vm.runInContext(code,context);
read('FILES.splice(0,FILES.length,"data/alert.json")');
const normalized=extra=>context.normalizeAlertTime({...row,...extra},payload.timestamp,now);
let checks=0;const check=(value,label)=>{assert.ok(value,label);checks++;};
(async()=>{
  await context.updateAll({scheduleNext:true});
  check(document.getElementById('alerts').innerHTML.includes('确认机会'),'current verified alert is shown');
  now=Date.parse('2026-10-12T10:05:00+08:00');
  context.updateTime();
  check(!document.getElementById('alerts').innerHTML.includes('确认机会'),'clock alone expires the card at deadline');
  check(document.getElementById('alerts').innerHTML.includes('有效期已过'),'deadline is explained honestly');
  now=Date.parse('2026-10-12T10:04:00+08:00'); await context.updateAll();
  check(document.getElementById('alerts').innerHTML.includes('确认机会'),'unchanged cached JSON rerenders when clock changes');
  offline=true;now+=60000;await context.updateAll();
  check(!document.getElementById('alerts').innerHTML.includes('确认机会'),'failed refresh still expires retained evidence');
  check(context.cached('data/alert.json').alerts.length===1,'expiry retains original history');
  now=Date.parse('2026-10-12T10:04:00+08:00');
  for(const deadline of [undefined,null,'','invalid','2026-10-12T10:05:00','2026-02-30T10:05:00+08:00','2026-10-12T24:00:00+08:00','2026-10-12T09:59:00+08:00']) check(!context.isAlertFresh(normalized({valid_until:deadline}),now),'missing/invalid/contradictory deadline not current');
  check(!context.isAlertFresh(normalized({time:'bad'}),now),'invalid event time cannot become receipt time');
  check(!context.isAlertFresh(normalized({time:'2026-10-12T10:06:00+08:00'}),now),'future event outside existing tolerance rejected');
  check(context.isAlertFresh(normalized({time:'2026-10-12T10:04:30+08:00'}),now),'existing one-minute clock tolerance retained');
  check(!context.isAlertFresh(normalized({_sessionClosed:true}),now),'closed session overrides still-live deadline');
  check(!context.isAlertFresh(normalized({confirmation_level:'invalidated'}),now),'explicit invalidation overrides timing');
  check(context.alertConfirmationLevel(normalized(),false)==='invalidated','confirmed label cannot bypass expiry');
  const failedAudit={...row.quote_audit,secondary_verification:{state:'failed'}};
  check(context.alertConfirmationLevel(normalized({quote_audit:failedAudit}),true)==='candidate','contradictory quote audit cannot confirm');
  for(const key of ['price_move_valid','volume_valid','direction_ratio_valid']) {
    const quote_audit={...row.quote_audit,sanity_checks:{cross_source_verified:true,[key]:false}};
    check(!context.hasTrustedQuoteAudit({quote_audit}),`${key}: contradicting audit never trusted`);
    check(context.alertConfirmationLevel(normalized({quote_audit}),true)==='candidate',`${key}: contradicting audit never confirmed`);
  }
  check(context.alertConfirmationLevel(normalized({confirmation_level:'candidate'}),true)==='candidate','candidate is not auto-promoted');
  offline=false;payload={...payload,source_status:'monitor_session_closed'};await context.updateAll();
  check(document.getElementById('alerts').innerHTML.includes('已收盘，仅供回看'),'all closed-session cards become historical');
  check(!document.getElementById('alerts').innerHTML.includes('确认机会'),'closed cards never keep confirmation badge');
  handlers.pagehide();check(read('refreshTimer')===null,'pagehide clears refresh timer');
  await context.updateAll({scheduleNext:true});check(read('refreshTimer')===null,'in-flight completion cannot restart hidden page timer');
  const before=count;handlers.pageshow();await read('refreshInFlight');
  check(count>before && read('refreshTimer')!==null,'BFCache pageshow resumes refresh and scheduling');
  const beforeVisible=count;document.hidden=false;handlers.visibilitychange();await read('refreshInFlight');check(count>beforeVisible,'returning to visible tab checks data');
  check(context.topicNeedsReview({updated_at:'2026-10-12T10:00:00+08:00',update_scope:'closing_representatives_only'}),'representative-only facts do not qualify as fresh research');
  const topicHtml=context.renderTopicCard({name:'主题',updated_at:'2026-10-09T10:00:00+08:00',conclusion:'原研究',representative_facts:{summary:'实际样本事实',source_as_of:'2026-10-12T10:00:00+08:00'}});
  check(topicHtml.includes('实际样本事实') && topicHtml.includes('不等同于专题研究更新') && topicHtml.includes('旧研究待复核'),'facts remain visible without rejuvenating old research');
  check(context.topicNeedsReview({updated_at:'2026-10-13T10:00:00+08:00'}),'future topic timestamp never presented current');
  for (const topic of [
    {updated_at:'2026-10-09T10:00:00+08:00',source_as_of:'2026-10-12T10:00:00+08:00'},
    {source_as_of:'2026-10-12T10:00:00+08:00'},
    {updated_at:'2026-10-12T10:00:00',source_as_of:'2026-10-12T10:00:00+08:00'},
    {analysis_time:null,updated_at:'2026-10-12T10:00:00+08:00'},
    {updated_at:'2026-10-12T10:04:01+08:00'},
    {updated_at:'2026-10-12T10:00:00+08:00',valid_until:'2026-10-12T10:04:00+08:00'}
  ]) check(context.topicNeedsReview(topic),'source refresh cannot renew missing/old/ambiguous/future/expired research');
  check(!context.topicNeedsReview({updated_at:'2026-10-12T10:00:00+08:00',source_as_of:'2026-10-12T10:00:00+08:00'}),'real current authored research remains usable');
  const oldResearch=context.renderTopicCard({name:'旧研究',updated_at:'2026-10-09T10:00:00+08:00',source_as_of:'2026-10-12T10:00:00+08:00'});
  check(oldResearch.includes(context.formatUpdateTime('2026-10-09T10:00:00+08:00')),'historical topic displays authored date, not newer source date');
  console.log(`PASS ${checks} alert clock/lifecycle/topic-truth assertions.`);
})().catch(error=>{console.error(error);process.exitCode=1;});

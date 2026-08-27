"use strict";

const V2_DATA_URL = "data/v2/decision-system.json";
const WATCHLIST_MIGRATION_AUDIT_URL = "data/v2/v22/watchlist-migration-audit.json";
const V22_STOCK_POOL_URL = "data/v2/v22/stock-pool-shadow.json";
const V22_INDUSTRY_TRACKING_URL = "data/v2/v22/industry-tracking.json";
const V22_MARKET_ENVIRONMENT_URL = "data/v2/v22/market-environment.json";
const V22_ENVIRONMENT_DECISION_URL = "data/v2/v22/environment-decision.json";
const V22_DECISION_CANDIDATE_URL = "data/v2/v22/decision-system-candidate.json";
const V22_COCKPIT_PHASE_URL = "/_v2-cockpit-phase";
const V22_COCKPIT_PHASE_FALLBACK_URL = "data/v2/v22/cockpit-phase-view.json";
const V22_REPLAY_URL = "data/v2/v22/replay-index.json";
const V22_EVALUATION_URL = "data/v2/v22/model-evaluation.json";
const V22_PARALLEL_URL = "data/v2/v22/parallel-comparison.json";
const V2_LOGIC_CATALOG_URL = "data/v2/logic-catalog.json";
const STATE_LABELS = {
  confirmed: "已确认",
  candidate: "待确认",
  waiting: "等待触发",
  risk: "风险",
  invalidated: "已失效",
  expired: "历史记录",
  usable: "可用",
  degraded: "部分信息待补",
  blocked: "暂不判断",
  partial: "部分可用",
  data_missing: "数据缺失",
  degraded_response_date_unverified: "历史日期没有确认",
  observed_by_themes: "主题样本观察",
  usable_proxy: "可用代理",
  crowded: "抱团拥挤",
  warming: "升温",
  emerging: "初现",
  loaded: "已加载",
  missing: "缺失",
  ok: "正常",
  current: "当前可用",
  updated: "已更新",
  unchanged: "无变化",
  pending: "待补充",
  valid: "有效",
  collecting: "积累中",
  production_primary: "V1 生产主入口",
  shadow_observer: "V2 试用版",
  rule_screen: "规则筛选",
  deterministic_rules: "确定性规则",
  ai_explain: "AI 解释",
  ai: "AI",
  human_decide: "人工决策",
  user: "用户"
};

const SOURCE_LABELS = {
  "alert.json": "盘中异动监测",
  "opportunity-watch.json": "交易预案",
  "decision-feed.json": "决策线索",
  "intraday.json": "盘中市场快照",
  "quality-report.json": "数据质量检查",
  "data-trust.json": "来源可信度检查",
  "automation-health.json": "数据任务状态"
};

const ROLE_LABELS = { unclassified: "角色未确定", core: "中军", leader: "龙头", platform: "平台", high_beta: "弹性" };
const POOL_LABELS = { watch_only: "个人观察", small_deng: "小登观察", old_deng: "老登观察", middle_deng: "中登观察" };
const LAYER_LABELS = { fact: "事实", inference: "推断", action: "建议" };
const INPUT_LABELS = {
  microcap: "微盘结构", sentiment: "情绪结构", official_events: "官方事件", outcome_prices: "结果价格",
  microcap_observation: "微盘观察", sentiment_structure: "涨停与跌停表现", market_breadth_snapshot: "上涨与下跌家数", market_liquidity_snapshot: "成交是否活跃", mainline_structure_snapshot: "主线表现", external_market_snapshot: "外盘表现", portfolio_context: "持仓情况", events: "市场事件"
};

let v2State = null;
let activeRadarFilter = "all";
let stockPoolQuery = "";
let bloggerAccounts = [];
let privatePortfolio = { holdings: [], cash: null, risk_budget: {}, trade_authorization: false };
let privateUserAssets = { "状态": "尚未读取", "数量": 0, "用户自选": [] };
let v22StockPool = null;
let v22MarketEnvironment = null;
let v22EnvironmentDecision = null;
let v22DecisionCandidate = null;
let v2LoadInFlight = false;
let radarRefreshTimer = null;
let logicCatalogState = { entries: [], categories: [] };
let logicSearchQuery = "";
let logicCategory = "all";

const BLOGGER_PLATFORM_LABELS = {
  xiaohongshu: "小红书", weibo: "微博", wechat: "微信公众号", douyin: "抖音", bilibili: "哔哩哔哩", other: "其他"
};
const USER_PRIORITY_LABELS = { high: "高", normal: "普通", low: "低" };
const USER_INTENT_LABELS = { holding: "持仓", swing: "波段关注", watch: "等待机会", research: "长期研究", event: "事件跟踪", "未设置": "未设置" };
const USER_SOURCE_LABELS = { ths_cloud: "同花顺云", manual_add: "手动添加", broker_sync: "券商同步" };

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function humanText(value) {
  return String(value ?? "")
    .replace(/当前没有决策就绪案例/g, "当前没有值得出手的机会")
    .replace(/决策就绪案例/g, "值得行动的方向")
    .replace(/决策就绪/g, "值得行动")
    .replace(/环境门禁等待核验。?/g, "当前市场还不支持出手。")
    .replace(/环境门禁/g, "市场是否支持")
    .replace(/全局或案例证据仍有降级项，只能保守使用。?/g, "部分关键信息还没跟上，只能保守看待。")
    .replace(/风险路径可以提前提醒，但仍需核验位置、流动性与恢复条件。?/g, "风险已经出现，但还要看股价位置、成交和是否止跌。")
    .replace(/盘前预案已转入实盘验证；只有当日市场事实与代表股同向确认后，才可能升级机会。?/g, "盘前判断已经进入盘中检查；只有代表股和板块一起走强，才考虑行动。")
    .replace(/海外方向与A股代表股同向，传导得到阶段性确认。?/g, "外盘和A股代表股方向一致，但仍要看清是一起上涨还是一起下跌。")
    .replace(/等待风险收敛，不追/g, "先不追高，等跌停减少、高位股止跌")
    .replace(/行情闭环/g, "行情信息完整")
    .replace(/候选投影/g, "观察结果")
    .replace(/V1继续生产，V2继续影子/g, "V1继续正常使用，V2继续试用观察")
    .replace(/影子观察/g, "试用观察")
    .replace(/影子结果/g, "试用结果")
    .replace(/影子模式/g, "试用状态")
    .replace(/影子/g, "试用")
    .replace(/本地盘中监控日志\s*monitor\.log/gi, "盘中异动监测记录")
    .replace(/\bmonitor\.log\b/gi, "盘中异动监测记录")
    .replace(/\bdegraded_response_date_unverified\b/gi, "历史日期尚未核验")
    .replace(/\bdegraded\b/gi, "部分信息待补")
    .replace(/risk candidate/gi, "风险候选")
    .replace(/\bcandidate\b/gi, "待确认")
    .replace(/\bconfirmed\b/gi, "已确认")
    .replace(/\bexpired\b/gi, "已过有效时间")
    .replace(/\bevaluation_eligible\b/gi, "有效复盘样本")
    .replace(/\bfreshness_state\b/gi, "信息时效")
    .replace(/\bvalidity_missing\b/gi, "有效时间待补")
    .replace(/\bcanonical_key\b/gi, "复盘样本标识")
    .replace(/\bblocked_validation\b/gi, "等待核验")
    .replace(/\bsource_reason\b/gi, "关注依据")
    .replace(/\bquote_audit\b/gi, "个股行情核对")
    .replace(/\bG[0-7]\b/g, "判断条件")
    .replace(/有效时间待补，不能进入决策就绪/g, "尚未设定有效观察时间，只能继续观察")
    .replace(/有效时间待补，不能进入值得行动/g, "没有明确观察期限，先不行动")
    .replace(/来自当前交易日可审计市场事实；个股涨跌幅由独立行情字段计算。?/g, "来自当前交易日市场事实；涨跌幅为该股票当时真实行情。")
    .replace(/可审计/g, "可核验")
    .replace(/环境门禁/g, "市场环境判断")
    .replace(/回避\/降级集合/g, "降低关注方向")
    .replace(/流动性仍待数据源补采，?AI不会凭空生成。?/g, "流动性尚未确认，当前以风险控制为先。")
    .replace(/流动性仍待数据源补采/g, "流动性尚未确认")
    .replace(/；两侧使用同一交易日和过滤规则。?/g, "。")
    .replace(/(?:和|与)来源共同确认/g, "共振确认")
    .replace(/完整行业上涨下跌宽度/g, "板块扩散程度尚未确认")
    .replace(/行业成交额与历史基线/g, "板块成交承接尚未确认")
    .replace(/核心、中军和后排的连续时点确认/g, "核心、中军和后排持续共振尚未确认")
    .replace(/板块成交承接尚未确认/g, "还不知道放量后有没有资金接住")
    .replace(/核心、中军和后排持续共振尚未确认/g, "核心股和板块内其他股票还没有一起走强")
    .replace(/涨停代表较集中，但仍需行业宽度、成交和非涨停中军确认。?/g, "涨停股集中在这个板块，但还要看板块内多数股票是否跟涨、成交是否放大，以及核心股以外是否有资金跟进。")
    .replace(/行业上涨宽度、成交和非涨停中军同向确认/g, "板块内多数股票上涨、成交放大，核心股以外也有资金跟进")
    .replace(/市场宽度、情绪和核心代表股至少两项继续走弱/g, "下跌股票继续增多、跌停没有减少、核心股继续走弱，三项中出现两项就按风险处理")
    .replace(/风险维度收敛，市场宽度和核心代表股转为同向承接/g, "下跌股票和跌停明显减少，核心股止跌回升时，原风险判断失效")
    .replace(/全市场风险状态和抑制维度限制机会升级。?/g, "大盘和赚钱效应都偏弱，暂时不能把它当成可操作机会。")
    .replace(/A\/H任一侧共振断裂/g, "A股或港股代表股不再一起走强")
    .replace(/代表股转为背离/g, "代表股走势不一致")
    .replace(/涨跌停集中度消失或行业宽度反向/g, "涨跌停不再集中在该板块，或板块内多数股票转向")
    .replace(/核心股低开后放量收复开盘价或跌幅明显收敛/g, "核心股低开后放量站回开盘价，或跌幅明显收窄")
    .replace(/修复只停留在单股反抽/g, "只有一只股票反弹，板块没有跟随")
    .replace(/核心股重新跌回分时均价/g, "核心股重新跌破盘中平均成交价")
    .replace(/后排不扩散且成交萎缩/g, "板块内其他股票没有跟涨，成交也在缩小")
    .replace(/行业宽度/g, "板块内多数股票表现")
    .replace(/非涨停中军/g, "没有涨停的核心股")
    .replace(/同向承接/g, "一起止跌回升")
    .replace(/风险维度/g, "风险信号")
    .replace(/早期候选/g, "初步观察")
    .replace(/机会升级/g, "加强关注")
    .replace(/候选版本/g, "可比较版本")
    .replace(/结果窗口等待可核验价格数据。?/g, "还在等待后续股价结果。")
    .replace(/V2\.2尚无触发价格与主要结果窗口均完整的案例，不计算命中率，也不改变规则。?/g, "目前还没有同时记录当时价格和后续表现的完整案例，因此不统计胜率，也不调整判断方法。")
    .replace(/V2证据属于\d{4}-\d{2}-\d{2}，V2\.2市场事实属于\d{4}-\d{2}-\d{2}；交易日未统一，暂不比较命中率。?/g, "两个版本使用的交易日期不同，目前不能公平比较胜率。")
    .replace(/适用与不适用市场环境/g, "什么行情适合关注、什么行情应该回避")
    .replace(/情绪或市场宽度已有改善，但另一侧证据尚未同步，当前仍属于修复观察。?/g, "上涨股票增多了，但强势股能否继续上涨、高位股回落时是否有人接盘还没有确认。多数股票在修复，追高仍容易亏钱。")
    .replace(/篮子成交额已完整覆盖/g, "代表股成交额已有数据")
    .replace(/已有同日篮子成交额/g, "代表股已有当天成交额")
    .replace(/篮子成交额覆盖不足/g, "代表股成交额数据不完整")
    .replace(/>=/g, "不低于")
    .replace(/<=/g, "不高于")
    .replace(/->/g, "传导至")
    .replace(/[\[\]{}]/g, "")
    .replace(/"\s*,\s*"/g, "、")
    .replace(/^\s*[",]+|[",]+\s*$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function uniqueHumanTexts(values, limit = 3) {
  const seen = new Set();
  return list(values).map(item => humanText(item)).filter(item => {
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  }).slice(0, limit);
}

function hasFiniteNumber(value) {
  return value !== null && value !== undefined && value !== "" && typeof value !== "boolean" && Number.isFinite(Number(value));
}

function stateLabel(value) {
  return STATE_LABELS[value] || "状态待核验";
}

function sourceLabel(value) {
  const raw = String(value || "");
  const labels = raw.split(",").map(item => SOURCE_LABELS[item.trim()]).filter(Boolean);
  return [...new Set(labels)].join("、") || "可查看原始来源";
}

function compactTime(value) {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
  }).format(parsed);
}

function compactTimeWithSeconds(value) {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
  }).format(parsed);
}

function humanTimeText(value) {
  return humanText(value).replace(
    /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?/g,
    match => compactTime(match)
  );
}

function sourceLink(value) {
  if (!value) return "来源未知";
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return escapeHtml(value);
    return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noreferrer">${escapeHtml(parsed.hostname)}</a>`;
  } catch (_error) {
    return escapeHtml(value);
  }
}

function renderQuality(data) {
  const target = document.getElementById("data-quality-gate");
  if (!target) return;
  const state = data?.state || "blocked";
  const display = state === "usable"
    ? { label: "信息已更新", headline: "当前结论可以使用", copy: "事实、时点与来源已完成当前轮核对。" }
    : state === "blocked"
      ? { label: "关键数据不足", headline: "暂不形成操作结论", copy: "关键事实不足或存在冲突，当前页面只保留等待。" }
      : { label: "部分信息待更新", headline: "结论仅基于已确认事实", copy: "仍在核对的内容不会被 AI 补写，也不会作为交易依据。" };
  target.className = `status-panel ${state}`;
  target.innerHTML = `
    <div class="state-row"><span class="eyebrow">信息完整度</span><span class="pill ${escapeHtml(state)}">${escapeHtml(display.label)}</span></div>
    <h2>${escapeHtml(display.headline)}</h2>
    <p>${escapeHtml(display.copy)}</p>
    <a class="logic-inline-link quality-detail-link" href="v2-governance.html">需要时查看数据状态 →</a>`;
}

function renderEnvironment(data) {
  const target = document.getElementById("market-environment");
  if (!target) return;
  const quality = data?.quality_state || "blocked";
  target.className = `status-panel ${quality}`;
  const reasons = list(data?.supporting_reasons).slice(0, 2).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  const sentiment = data?.sentiment_structure || {};
  const crossMarket = list(data?.cross_market);
  const ladderRows = (ladder, suffix) => list(ladder?.items).map(item => `<div class="ladder-row"><b>${escapeHtml(item.height)}${escapeHtml(suffix)}</b><span>${escapeHtml(item.count)}只</span><p>${list(item.stocks).slice(0, 5).map(stock => escapeHtml(stock.name)).join(" / ") || "无代表股"}</p></div>`).join("");
  target.innerHTML = `
    <div class="state-row"><span class="eyebrow">市场环境</span><span class="pill ${escapeHtml(quality)}">${escapeHtml(data?.state || "无法判断")}</span></div>
    <h2>${escapeHtml(data?.action || "等待确认")}</h2>
    <p>${escapeHtml(data?.headline || "当前没有可用市场结论")}</p>
    <div class="market-stats"><span>涨停 ${escapeHtml(sentiment.limit_up_count ?? "缺失")}</span><span>跌停 ${escapeHtml(sentiment.limit_down_count ?? "缺失")}</span><span>炸板 ${escapeHtml(sentiment.broken_limit_count ?? "缺失")}</span></div>
    <details class="evidence-details market-evidence-bundle"><summary>展开市场证据、梯队与跨市场传导</summary>
      ${reasons ? `<div class="market-detail-section"><strong>支持依据</strong><ul>${reasons}</ul></div>` : ""}
      <div class="market-detail-section"><strong>涨停与跌停梯队</strong><p class="ladder-note">数据截至 ${escapeHtml(compactTime(sentiment.as_of))} · ${sourceLink(sentiment.source)}</p><div class="ladder-grid"><div><strong>涨停梯队</strong>${ladderRows(sentiment.limit_up_ladder, "板") || `<p>${escapeHtml(sentiment.limit_up_ladder?.note || "数据缺失")}</p>`}</div><div><strong>跌停梯队</strong>${ladderRows(sentiment.limit_down_ladder, "连跌停") || `<p>${escapeHtml(sentiment.limit_down_ladder?.note || "数据缺失")}</p>`}</div></div><p class="ladder-note">晋级表现：${escapeHtml(stateLabel(sentiment.promotion_rate?.state || "data_missing"))} · 高位亏钱效应：${escapeHtml(stateLabel(sentiment.high_level_loss_effect?.state || "data_missing"))}</p></div>
      ${crossMarket.length ? `<div class="market-detail-section"><strong>外盘对A股的影响</strong><div class="cross-market-grid">${crossMarket.map(item => `<div class="cross-market-item"><b>${escapeHtml(item.market)}</b><span>${escapeHtml(stateLabel(item.quality_state || "loaded"))}</span><p>${escapeHtml(humanText(item.conclusion))}</p></div>`).join("")}</div></div>` : ""}
    </details>`;
}

const ENVIRONMENT_LEVEL_LABELS = {
  support: "支持", partial_support: "部分支持", neutral: "中性", suppress: "抑制", risk_release: "风险释放", unknown: "待补证据"
};
const ENVIRONMENT_QUALITY_LABELS = { usable: "数据完整", degraded: "部分信息未更新", blocked: "数据不一致", unknown: "数据不足" };
const ENVIRONMENT_SOURCE_STATE_LABELS = { current: "今天已更新", stale: "旧数据未使用", missing: "尚未取得", conflict: "数据说法不一致" };
const ENVIRONMENT_STATE_LABELS = {
  risk_release: "亏钱效应明显", repair: "修复观察", rotation_trial: "板块快速轮动", mainline_confirmed: "主线已确认",
  diffusion_strengthening: "主线向更多股票扩散", crowding_divergence: "高位拥挤分歧", retreat: "市场退潮"
};
const STYLE_STATE_LABELS = { strengthening: "正在走强", weakening: "正在走弱", mixed: "涨跌分化", unknown: "暂时看不清" };
const TRANSMISSION_STATE_LABELS = { background_only: "仅作背景", pending: "等待A股验证", confirmed: "传导确认", divergent: "A股背离" };

const MARKET_NAME_LABELS = { US: "美股", HK: "港股", KR: "韩国市场" };

function crossMarketTradeView(item) {
  const market = MARKET_NAME_LABELS[String(item?.origin_market || "").toUpperCase()] || "外盘";
  const themes = list(item?.a_share_themes).join("、") || "相关方向";
  const originDirection = String(item?.origin_direction || "").toLowerCase();
  const aShareDirection = String(item?.a_share_direction || "").toLowerCase();
  const state = String(item?.transmission_state || "").toLowerCase();
  const stocks = list(item?.representative_securities).slice(0, 2).map(stock => {
    const pct = hasFiniteNumber(stock?.change_pct) ? `${Number(stock.change_pct) > 0 ? "+" : ""}${Number(stock.change_pct).toFixed(2)}%` : "";
    return `${stock?.name || "代表股"}${pct}`;
  }).join("、");
  const stockNote = stocks ? `，代表股${stocks}` : "";
  if (state === "confirmed" && originDirection === "down" && aShareDirection === "down") {
    return { signal: "风险", conclusion: `${themes}：${market}走弱，A股相关股票也在下跌${stockNote}。`, action: "先回避，不抄底；等代表股止跌并重新走强。" };
  }
  if (state === "confirmed" && originDirection === "up" && aShareDirection === "up") {
    return { signal: "机会", conclusion: `${themes}：${market}上涨，A股相关股票也在走强${stockNote}。`, action: "可以关注，但不追高；等回踩承接或板块继续扩散。" };
  }
  if (state === "divergent" || (originDirection && aShareDirection && originDirection !== aShareDirection)) {
    return { signal: "不操作", conclusion: `${themes}：${market}与A股走势相反${stockNote}。`, action: "外盘没有形成可用指引，暂不操作。" };
  }
  if (state === "pending") {
    const direction = originDirection === "up" ? "上涨" : (originDirection === "down" ? "下跌" : "方向不明");
    return { signal: "观察", conclusion: `${themes}：${market}${direction}，但A股相关股票还没有跟随${stockNote}。`, action: "先观察，不提前下注。" };
  }
  return { signal: "仅供参考", conclusion: `${themes}：${market}变化暂时只能作背景${stockNote}。`, action: "不能单独作为买卖理由。" };
}
const G5_LABELS = { support: "大盘支持", partial_support: "部分板块可做", neutral: "大盘方向不明", suppress: "大盘偏弱，先不做", block: "风险较高，停止操作" };

function renderEnvironmentV22(data) {
  v22MarketEnvironment = data;
  const summary = document.getElementById("market-environment-v22-summary");
  const dimensionsTarget = document.getElementById("market-environment-v22-dimensions");
  const sourcesTarget = document.getElementById("market-environment-v22-sources");
  if (!summary || !dimensionsTarget || !sourcesTarget) {
    applyV22MarketPageCurrentView();
    renderIntradayMarketOverview();
    return;
  }
  const view = data?.user_view || {};
  const dimensions = list(data?.dimensions);
  const evidence = new Map(list(data?.evidence_refs).map(item => [item.evidence_ref_id, item]));
  summary.innerHTML = `<div class="environment-shadow-summary"><div><span class="eyebrow">今日市场结论</span><strong>${escapeHtml(view["当前允许"] || "等待确认")}</strong><p>${escapeHtml(view["当前判断"] || "今天的数据还没有更新完整。")}</p></div><div class="environment-summary-aside"><span>市场状态</span><b>${escapeHtml(view["标题"] || "等待判断")}</b><small>${escapeHtml(view["交易日"] || "日期待确认")} · ${escapeHtml(view["阶段"] || "时间待确认")}</small></div></div><p class="environment-shadow-time">行情与信息截至 ${escapeHtml(compactTime(view["行情时点"]))}</p>`;
  renderMarketSentimentV22(data?.sentiment_view || {});
  dimensionsTarget.innerHTML = dimensions.map(item => {
    const refs = list(item.evidence_ref_ids).map(id => evidence.get(id)).filter(Boolean);
    const stockMap = new Map();
    refs.flatMap(ref => list(ref.representative_securities)).filter(stock => stock?.name && stock?.code).forEach(stock => stockMap.set(`${stock.code}-${stock.role || ""}`, stock));
    const stocks = [...stockMap.values()];
    const representative = stocks.length ? `<div class="environment-representatives"><strong>代表股表现</strong>${stocks.slice(0, 5).map(stock => `<span><b>${escapeHtml(stock.name)}</b> ${escapeHtml(stockCodeLabel(stock.code))}${hasFiniteNumber(stock.change_pct) ? ` ${Number(stock.change_pct) > 0 ? "+" : ""}${Number(stock.change_pct).toFixed(2)}%` : ""}<small>${escapeHtml(compactTime(stock.as_of))} · ${escapeHtml(humanText(stock.source || "来源待确认"))}</small></span>`).join("")}</div>` : "";
    const facts = list(item.fact_summary);
    const counters = list(item.counter_evidence);
    const missing = list(item.missing_evidence);
    return `<article class="environment-dimension-card ${escapeHtml(item.support_level || "unknown")}"><div class="state-row"><h3>${escapeHtml(item.label || "市场方面")}</h3><span class="environment-level">${escapeHtml(ENVIRONMENT_LEVEL_LABELS[item.support_level] || "等待确认")}</span></div><strong class="dimension-conclusion">${escapeHtml(humanText(item.conclusion || "当前还看不清。"))}</strong><div class="environment-fact-line"><b>为什么</b>${escapeHtml(humanText(facts[0] || "当前信息不足"))}</div><details><summary>查看更多依据与风险</summary>${facts.length > 1 ? `<strong>更多依据</strong><ul>${facts.slice(1).map(value => `<li>${escapeHtml(humanText(value))}</li>`).join("")}</ul>` : ""}${counters.length ? `<strong>什么情况可能看错</strong><ul>${counters.map(value => `<li>${escapeHtml(humanText(value))}</li>`).join("")}</ul>` : ""}${missing.length ? `<strong>还缺什么</strong><ul>${missing.map(value => `<li>${escapeHtml(humanText(value))}</li>`).join("")}</ul>` : ""}${representative}</details></article>`;
  }).join("") || '<div class="empty-state">八维事实暂未生成。</div>';
  const conflicts = list(data?.conflicts);
  const sourceRows = list(data?.source_status);
  sourcesTarget.innerHTML = `<div class="environment-source-grid">${sourceRows.map(item => `<div><strong>${escapeHtml(item.label || "数据来源")}</strong><span>${escapeHtml(ENVIRONMENT_SOURCE_STATE_LABELS[item.state] || "等待确认")} · ${escapeHtml(compactTime(item.as_of))}</span><p>${escapeHtml(humanText(item.note || ""))}</p></div>`).join("")}</div>${conflicts.length ? `<div class="environment-conflict-note"><strong>数据不一致</strong>${conflicts.map(item => `<p>${escapeHtml(item.metric_name || "这项数据")}：${escapeHtml(humanText(item.resolution || "暂时不用于交易判断。"))}</p>`).join("")}</div>` : '<p class="environment-no-conflict">当前数据之间没有明显矛盾。</p>'}`;
  applyV22MarketPageCurrentView();
  renderIntradayMarketOverview();
}

function renderMarketSentimentV22(view) {
  const target = document.getElementById("market-sentiment-v22");
  if (!target) return;
  const drivers = list(view?.drivers);
  const counter = view?.counter_evidence ? `<p class="sentiment-counter"><b>容易误判的地方</b>${escapeHtml(view.counter_evidence)}</p>` : "";
  target.innerHTML = `<section class="market-sentiment-card ${escapeHtml(view?.status || "unknown")}"><div class="market-sentiment-summary"><span class="eyebrow">市场情绪判断</span><strong>${escapeHtml(view?.headline || "等待市场数据")}</strong><p>${escapeHtml(view?.judgment || "涨停、跌停、上涨家数和高位股表现还没有更新完整。")}</p><div class="market-sentiment-action"><b>当前应对</b>${escapeHtml(view?.action || "先观察")}</div>${counter}</div><div class="sentiment-driver-grid">${drivers.map(item => `<article><div class="state-row"><b>${escapeHtml(item.label || "判断依据")}</b><span>${escapeHtml(item.state || "还需确认")}</span></div><p>${escapeHtml(item.evidence || "暂时没有可用数据")}</p></article>`).join("") || '<div class="empty-state">市场强弱分项尚未更新。</div>'}</div></section>`;
}

async function loadMarketEnvironmentV22() {
  const target = document.getElementById("market-environment-v22-summary");
  try {
    const response = await fetch(`${V22_MARKET_ENVIRONMENT_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("八维环境暂不可用");
    renderEnvironmentV22(await response.json());
  } catch (_error) {
    if (target) target.innerHTML = '<div class="empty-state">市场环境暂时没有更新成功，保留上次可用结果。</div>';
  }
}

function renderEnvironmentDecisionV22(data) {
  const decisionTarget = document.getElementById("market-environment-v22-decision");
  const styleTarget = document.getElementById("style-regime-v22");
  const crossTarget = document.getElementById("cross-market-v22");
  renderIntradayMarketOverview();
  if (!decisionTarget || !styleTarget || !crossTarget) {
    applyV22MarketPageCurrentView();
    return;
  }
  const transition = data?.state_transition || {};
  const currentState = ENVIRONMENT_STATE_LABELS[data?.primary_state] || "等待判断";
  decisionTarget.innerHTML = `<div class="environment-decision-summary"><div><span class="eyebrow">当前市场状态</span><strong>${escapeHtml(currentState)}</strong><p>${escapeHtml(humanText(data?.action_constraint || "等待确认"))}</p></div><div><b>为什么</b><p>${escapeHtml(humanText(transition.transition_reason || "等待新的市场变化。"))}</p></div></div>`;
  const styles = list(data?.style_regimes);
  styleTarget.innerHTML = `<div class="environment-subsection-title"><strong>当前风格表现</strong><span>截至 ${escapeHtml(compactTime(data?.as_of))}</span></div><div class="style-regime-grid">${styles.map(item => {
    const representative = list(item.representative_securities).slice(0, 4);
    return `<article><div class="state-row"><h3>${escapeHtml(item.label || "风格")}</h3><span>${escapeHtml(STYLE_STATE_LABELS[item.price_state] || "还需确认")}</span></div><p>${escapeHtml(humanText(item.conclusion || "暂时看不清这个方向。"))}</p>${representative.length ? `<div class="compact-evidence-list">${representative.map(stock => `<span><b>${escapeHtml(stock.name || "代表对象")}</b>${hasFiniteNumber(stock.change_pct) ? ` ${Number(stock.change_pct) > 0 ? "+" : ""}${Number(stock.change_pct).toFixed(2)}%` : ""}<small>${escapeHtml(stockCodeLabel(stock.code))} · ${escapeHtml(compactTime(stock.as_of))} · ${escapeHtml(humanText(stock.source || "来源待核验"))}</small></span>`).join("")}</div>` : '<small>当天代表股行情不足，暂时不判断方向。</small>'}<p class="counter-note">需要警惕：${escapeHtml(humanText(list(item.counter_evidence)[0] || "暂时没有反向风险信息"))}</p></article>`;
  }).join("")}</div>`;
  const mappings = list(data?.cross_market_mappings);
  crossTarget.innerHTML = `<div class="environment-subsection-title"><strong>外盘对A股的影响</strong><span>直接看方向和应对</span></div><div class="cross-validation-grid">${mappings.map(item => {
    const view = crossMarketTradeView(item);
    return `<article><div class="state-row"><h3>${escapeHtml(list(item.origin_objects).slice(0, 2).join(" / ") || "外盘线索")}</h3><span>${escapeHtml(view.signal)}</span></div><p>${escapeHtml(view.conclusion)}</p><p class="cross-market-action"><b>怎么做</b>${escapeHtml(view.action)}</p><p class="counter-note">什么情况可能看错：${escapeHtml(humanText(list(item.counter_evidence)[0] || "A股代表股没有继续沿当前方向运行"))}</p></article>`;
  }).join("")}</div>`;
  applyV22MarketPageCurrentView();
  renderIntradayMarketOverview();
}

function v22EnvironmentDimension(code) {
  return list(v22MarketEnvironment?.dimensions).find(item => item.dimension_code === code) || null;
}

function applyV22MarketPageCurrentView() {
  if (!v22MarketEnvironment) return;
  const view = v22MarketEnvironment.user_view || {};
  const quality = v22MarketEnvironment.quality_state || "unknown";
  const marketTarget = document.getElementById("market-environment");
  setText("v2-updated", `信息截至 ${compactTime(v22MarketEnvironment.as_of || view["行情时点"])}`);
  setText("home-evidence-time", compactTime(v22MarketEnvironment.as_of || view["行情时点"]));
  setText("home-market-action", view["当前允许"] || v22MarketEnvironment.action_constraint || "等待确认");
  setText("home-market-copy", view["当前判断"] || v22MarketEnvironment.conclusion || "当前没有可用市场结论");
  if (marketTarget) {
    const breadth = v22EnvironmentDimension("market_breadth");
    const liquidity = v22EnvironmentDimension("liquidity");
    const sentiment = v22EnvironmentDimension("sentiment_structure");
    const mainline = v22EnvironmentDimension("mainline_structure");
    const facts = [breadth, liquidity, sentiment].filter(Boolean).map(item => list(item.fact_summary)[0]).filter(Boolean);
    const phaseLabel = view["阶段"] === "收盘" ? "当前收盘环境" : "当前市场环境";
    marketTarget.className = "status-panel";
    marketTarget.innerHTML = `
      <div class="state-row"><span class="eyebrow">${escapeHtml(phaseLabel)}</span></div>
      <h2>${escapeHtml(view["当前允许"] || v22MarketEnvironment.action_constraint || "等待确认")}</h2>
      <p>${escapeHtml(humanText(view["当前判断"] || v22MarketEnvironment.conclusion || "当前没有可用市场结论"))}</p>
      <div class="market-stats">${facts.map(item => `<span>${escapeHtml(humanText(item))}</span>`).join("")}</div>
      <details class="evidence-details market-evidence-bundle"><summary>查看当前主线与情绪约束</summary>
        <div class="market-detail-section"><strong>主线判断</strong><p>${escapeHtml(humanText(mainline?.conclusion || "等待主线确认。"))}</p></div>
        <div class="market-detail-section"><strong>情绪判断</strong><p>${escapeHtml(humanText(sentiment?.conclusion || "等待情绪确认。"))}</p></div>
      </details>`;
  }
  if (!document.getElementById("market-environment-v22")) return;
  const styleTarget = document.getElementById("style-map");
  if (!styleTarget || !v22EnvironmentDecision) return;
  const styles = list(v22EnvironmentDecision.style_regimes);
  styleTarget.innerHTML = `<p class="decision-rule">截至同一交易日的四类市场风格结果。</p><div class="dimension-grid">${styles.map(item => {
    const representative = list(item.representative_securities).slice(0, 4);
    return `<article class="dimension-card"><div class="state-row"><h3>${escapeHtml(item.label || "风格观察")}</h3><span class="state-text">${escapeHtml(STYLE_STATE_LABELS[item.price_state] || "还需确认")}</span></div><p>${escapeHtml(humanText(item.conclusion || "暂时看不清这个方向。"))}</p><details class="evidence-details"><summary>查看代表股和风险</summary>${representative.length ? `<div class="compact-evidence-list">${representative.map(stock => `<span><b>${escapeHtml(stock.name || "代表对象")}</b>${hasFiniteNumber(stock.change_pct) ? ` ${Number(stock.change_pct) > 0 ? "+" : ""}${Number(stock.change_pct).toFixed(2)}%` : ""}<small>${escapeHtml(stockCodeLabel(stock.code))} · ${escapeHtml(compactTime(stock.as_of))} · ${escapeHtml(humanText(stock.source || "来源待核验"))}</small></span>`).join("")}</div>` : "<p>当天代表股行情不足，暂时不判断方向。</p>"}<p class="counter-note">需要警惕：${escapeHtml(humanText(list(item.counter_evidence)[0] || "暂时没有反向风险信息"))}</p></details></article>`;
  }).join("")}</div>`;
}

function renderIntradayMarketOverview() {
  const target = document.getElementById("intraday-market-overview");
  if (!target) return;
  if (!v22MarketEnvironment) {
    target.innerHTML = '<div class="empty-state">当前市场结果尚未更新。</div>';
    return;
  }
  const dimension = code => list(v22MarketEnvironment.dimensions).find(item => item.dimension_code === code) || {};
  const index = dimension("index_structure");
  const liquidity = dimension("liquidity");
  const breadth = dimension("market_breadth");
  const mainline = dimension("mainline_structure");
  const sentiment = v22MarketEnvironment.sentiment_view || {};
  const styles = list(v22EnvironmentDecision?.style_regimes);
  const mappings = list(v22EnvironmentDecision?.cross_market_mappings);
  const styleEvidence = uniqueHumanTexts(styles.slice(0, 4).map(item => `${item.label || "风格"}：${humanText(item.conclusion || "等待确认")}`), 4);
  const mappingViews = mappings.map(crossMarketTradeView);
  const mappingEvidence = uniqueHumanTexts(mappingViews.map(item => item.conclusion), 2);
  const externalAction = mappingViews.some(item => item.signal === "风险")
    ? "外盘和A股相关股票一起走弱，先回避，不抄底。"
    : (mappingViews.some(item => item.signal === "机会") ? "方向偏强，但不追高；等回踩承接或继续扩散。" : "外盘暂时不能指导买卖，先观察。")
  const cards = [
    {
      title: "市场强弱",
      conclusion: humanText(index.conclusion || breadth.conclusion || "市场强弱等待更新。"),
      evidence: uniqueHumanTexts([list(index.fact_summary)[0], list(breadth.fact_summary)[0], list(liquidity.fact_summary)[0]], 2),
      action: v22MarketEnvironment.user_view?.["当前允许"] || "先观察",
    },
    {
      title: "赚钱与亏钱效应",
      conclusion: humanText(sentiment.judgment || dimension("sentiment_structure").conclusion || "市场情绪等待更新。"),
      evidence: uniqueHumanTexts(list(sentiment.drivers).map(item => item.evidence), 2),
      action: sentiment.action || "不因少数强股追高",
    },
    {
      title: "主线与市场风格",
      conclusion: humanText(mainline.conclusion || "当前主线尚未确认。"),
      evidence: styleEvidence,
      action: "只有代表股和后排一起走强，才加强关注。",
    },
    {
      title: "外盘对A股的影响",
      conclusion: mappingEvidence[0] || "外盘影响仍需A股代表股确认。",
      evidence: mappingEvidence.slice(1),
      action: externalAction,
    },
  ];
  target.innerHTML = `<div class="intraday-market-grid">${cards.map(card => `<article><span>${escapeHtml(card.title)}</span><strong>${escapeHtml(card.conclusion)}</strong>${card.evidence.length ? `<ul>${card.evidence.map(item => `<li>${escapeHtml(humanText(item))}</li>`).join("")}</ul>` : ""}<p><b>对交易的影响</b>${escapeHtml(humanText(card.action))}</p></article>`).join("")}</div>`;
}

async function loadEnvironmentDecisionV22() {
  if (!document.getElementById("market-environment-v22-decision") && !document.getElementById("opportunity-risk-radar")) return;
  try {
    const response = await fetch(`${V22_ENVIRONMENT_DECISION_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("环境状态暂不可用");
    v22EnvironmentDecision = await response.json();
    renderEnvironmentDecisionV22(v22EnvironmentDecision);
    if (v2State) {
      if (v22DecisionCandidate) renderDecisionCandidateV22(v22DecisionCandidate);
      else {
        const radar = radarByCurrentTime(v2State);
        renderRadar(radar.current);
        renderValidation(list(v2State.validation_queue));
      }
    }
  } catch (_error) {
    const target = document.getElementById("market-environment-v22-decision");
    if (target) target.innerHTML = '<div class="empty-state">环境状态暂未更新，保留上次可用结果。</div>';
  }
}

function environmentGateFor(card) {
  if (card?.environment_gate) return card.environment_gate;
  return list(v22EnvironmentDecision?.g5_links).find(item => item.opportunity_id === card?.id) || null;
}

function renderEnvironmentGate(card) {
  const gate = environmentGateFor(card);
  if (!gate) return '<div class="environment-gate neutral"><strong>大盘是否支持</strong><span>保持观察</span><p>当前市场不支持出手。</p></div>';
  const rawReason = humanText(gate.reason || "当前市场不支持出手。");
  const reason = rawReason.includes("等待核验") ? "当前市场不支持出手。" : rawReason;
  return `<div class="environment-gate ${escapeHtml(gate.g5_result || "neutral")}"><strong>大盘是否支持</strong><span>${escapeHtml(G5_LABELS[gate.g5_result] || "保持观察")}</span><p>${escapeHtml(reason)}</p></div>`;
}

function representativeStocks(items) {
  if (!items.length) return "";
  const resultOnly = document.body.classList.contains("page-radar");
  return `<div class="stock-row">${items.slice(0, 6).map(item => {
    if (typeof item === "string") return `<span class="stock-chip">${escapeHtml(item)}</span>`;
    const quoteReady = hasFiniteNumber(item.stock_change_pct) && Boolean(item.stock_quote_as_of) && Boolean(item.stock_quote_source);
    const pct = quoteReady ? ` ${Number(item.stock_change_pct).toFixed(2)}%` : "";
    const code = item.stock_code ? `<small class="stock-code-label">${escapeHtml(stockCodeLabel(item.stock_code))}</small>` : `<small class="stock-code-label missing">代码待补</small>`;
    const role = item.role ? `<small>${escapeHtml(item.role)}</small>` : "";
    const basis = !resultOnly && item.basis ? `<em>${escapeHtml(humanText(item.basis))}</em>` : "";
    const quoteAudit = quoteReady
      ? `<small class="stock-quote-audit">行情 ${escapeHtml(compactTime(item.stock_quote_as_of))} · ${escapeHtml(humanText(item.stock_quote_source))}</small>`
      : `<small class="stock-quote-audit missing">行情待补，不用于当前判断</small>`;
    return `<span class="stock-chip"><b>${escapeHtml(item.name || "未知")}</b>${escapeHtml(pct)}${code}${role}${quoteAudit}${basis}</span>`;
  }).join("")}</div>`;
}

function stockCodeLabel(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (/^sh\d{6}$/.test(raw)) return `${raw.slice(2)}.SH`;
  if (/^sz\d{6}$/.test(raw)) return `${raw.slice(2)}.SZ`;
  if (/^bj\d{6}$/.test(raw)) return `${raw.slice(2)}.BJ`;
  if (/^hk\d{5}$/.test(raw)) return `${raw.slice(2)}.HK`;
  return String(value || "代码待补");
}

function cockpitPhaseList(title, values, tone = "") {
  const rows = uniqueHumanTexts(values, 3);
  return `<section class="cockpit-phase-list ${escapeHtml(tone)}"><strong>${escapeHtml(title)}</strong>${rows.length ? `<ul>${rows.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : '<p>等待当日数据。</p>'}</section>`;
}

function cockpitPhaseEvidence(values, limit = 2) {
  const rows = uniqueHumanTexts(values, limit);
  return rows.length ? `<ul>${rows.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "";
}

function renderCockpitPhaseView(data) {
  const target = document.getElementById("cockpit-phase-view");
  if (!target) return;
  setText("cockpit-phase-title", data?.stage_label || "当前交易阶段");
  const sections = data?.sections || {};
  const availability = data?.availability || "waiting_update";
  const ready = availability === "ready" || availability === "partial";
  if (!ready) {
    const lastTime = data?.last_available_at ? `<small>最近一次资料：${escapeHtml(compactTime(data.last_available_at))}，不作为今日依据。</small>` : "";
    target.innerHTML = `<div class="cockpit-phase-waiting"><div class="state-row"><span>${escapeHtml(data?.status_label || "等待今日更新")}</span>${lastTime}</div><h3>${escapeHtml(humanText(data?.headline || "当前阶段尚无可执行结论。"))}</h3><p>${escapeHtml(humanText(data?.transition_note || "保持等待。"))}</p></div>`;
    return;
  }
  const external = sections.external_market || {};
  const sentiment = sections.sentiment || {};
  const mainline = sections.mainline || {};
  const representatives = list(sections.representative_stocks);
  target.innerHTML = `
    <div class="cockpit-phase-summary">
      <div class="state-row"><span>${escapeHtml(data?.status_label || "已更新")}</span><small>${escapeHtml(compactTime(data?.source_as_of))}</small></div>
      <div><h3>${escapeHtml(humanText(data?.headline || "当前判断等待生成。"))}</h3><p>${escapeHtml(humanText(data?.transition_note || "盘前预案将在开盘后转入盘中验证。"))}</p></div>
    </div>
    <div class="cockpit-phase-top-grid">
      <section><span>${escapeHtml(external.title || "隔夜外盘")}</span><strong>${escapeHtml(humanText(external.conclusion || "等待当日数据"))}</strong>${cockpitPhaseEvidence(external.evidence)}</section>
      <section><span>${escapeHtml(sentiment.title || "情绪判断")}</span><strong>${escapeHtml(humanText(sentiment.conclusion || "等待当日数据"))}</strong>${cockpitPhaseEvidence(sentiment.evidence)}</section>
      <section><span>${escapeHtml(mainline.title || "主线判断")}</span><div class="cockpit-mainline-tags">${list(mainline.names).length ? list(mainline.names).slice(0, 5).map(item => `<b>${escapeHtml(humanText(item))}</b>`).join("") : "<b>等待确认</b>"}</div>${cockpitPhaseEvidence(mainline.evidence, 5)}</section>
    </div>
    <section class="cockpit-phase-representatives"><div><span>代表股</span></div><div class="cockpit-phase-stock-grid">${representatives.map(stock => {
      const quoteReady = hasFiniteNumber(stock.change_pct) && Boolean(stock.quote_as_of) && Boolean(stock.source);
      const pct = quoteReady ? `${Number(stock.change_pct) > 0 ? "+" : ""}${Number(stock.change_pct).toFixed(2)}%` : humanText(stock.quote_status_label || "该时段行情未保存");
      const quoteLine = quoteReady ? `行情 ${compactTime(stock.quote_as_of)} · ${humanText(stock.source)}` : humanText(stock.source || "等待该时段行情");
      return `<article><div><strong>${escapeHtml(stock.name || "代表股待定")}</strong><b class="${quoteReady && Number(stock.change_pct) < 0 ? "down" : (quoteReady ? "up" : "waiting")}">${escapeHtml(pct)}</b></div><span>${escapeHtml(stockCodeLabel(stock.code))} · ${escapeHtml(stock.role || "观察对象")}</span><small>${escapeHtml(quoteLine)}</small></article>`;
    }).join("") || `<div class="empty-state">${escapeHtml(humanText(sections.representative_note || "这个时段没有保存可核验的代表股行情，因此不展示涨跌幅。"))}</div>`}</div></section>
    <div class="cockpit-phase-bottom-grid">
      ${cockpitPhaseList("操作条件", sections.action_conditions)}
      ${cockpitPhaseList("风险因素", sections.risks, "risk")}
      ${cockpitPhaseList("失效条件", sections.invalidation_conditions, "invalid")}
    </div>`;
}

async function loadCockpitPhaseView() {
  if (!document.getElementById("cockpit-phase-view")) return;
  try {
    let response = await fetch(`${V22_COCKPIT_PHASE_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) response = await fetch(`${V22_COCKPIT_PHASE_FALLBACK_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("阶段结果暂不可用");
    const payload = await response.json();
    const target = document.getElementById("cockpit-phase-view");
    const sessionKey = target?.dataset.sessionKey;
    const view = sessionKey ? payload?.sessions?.[sessionKey] : payload;
    if (view?.source_as_of) setText("v2-updated", `信息截至 ${compactTime(view.source_as_of)}`);
    renderCockpitPhaseView(view || {
      stage_label: "当前交易阶段",
      availability: "waiting_update",
      status_label: "等待更新",
      headline: "当前页面结果尚未形成。",
      transition_note: "不使用旧日期结论代替。",
    });
  } catch (_error) {
    const target = document.getElementById("cockpit-phase-view");
    if (target) target.innerHTML = '<div class="empty-state error-state">当前交易阶段结果暂未更新；旧预案不会作为今天的操作依据。</div>';
  }
}

function visibleRiskAndInvalidation(card) {
  const risks = list(card.risk_factors).length ? list(card.risk_factors) : list(card.counter_evidence);
  const invalidation = list(card.invalidation_conditions);
  const riskText = risks.slice(0, 2).map(item => humanText(item)).filter(Boolean).join("；") || "暂时没有新增风险，但仍要看代表股与板块是否同向。";
  const invalidationText = invalidation.slice(0, 3).map(item => humanText(item)).filter(Boolean).join("；") || "关键证据失效或代表股与板块背离。";
  return `<div class="risk-invalidation-grid"><div><strong>主要风险</strong><p>${escapeHtml(riskText)}</p></div><div><strong>失效条件</strong><p>${escapeHtml(invalidationText)}</p></div></div>`;
}

function triggerMetrics(data) {
  if (!data?.metric_scope) return "";
  if (!hasFiniteNumber(data.change_pct)) return "";
  const pct = `${Number(data.change_pct).toFixed(2)}%`;
  const window = data.window ? ` · ${escapeHtml(data.window.replace("m", "分钟"))}` : "";
  return `<div class="trigger-metrics"><strong>异动时</strong><span>${escapeHtml(pct)}${window}</span></div>`;
}

function userEvidenceText(value) {
  const raw = typeof value === "object" && value !== null
    ? (value.detail || value.summary || value.conclusion || value.text || "")
    : value;
  const text = humanText(raw);
  if (!text || /(?:\btype\b|\bmetric\b|\btimestamp\b|\bsource\b)\s*[":]/i.test(text)) return "";
  return text;
}

function evidenceDetails(card) {
  const evidence = list(card.evidence);
  const counter = list(card.counter_evidence);
  const confirm = list(card.confirm_conditions);
  const invalidation = list(card.invalidation_conditions);
  const rows = [];
  const visibleEvidence = evidence.map(userEvidenceText).filter(Boolean).slice(0, 4);
  if (visibleEvidence.length) {
    rows.push(`<li class="evidence-group-title">支持证据</li>${visibleEvidence.map(item => `<li>${escapeHtml(item)}</li>`).join("")}`);
  }
  const visibleCounter = counter.map(userEvidenceText).filter(Boolean).slice(0, 3);
  const visibleConfirm = confirm.map(userEvidenceText).filter(Boolean).slice(0, 3);
  const visibleInvalidation = invalidation.map(userEvidenceText).filter(Boolean).slice(0, 3);
  if (visibleCounter.length) rows.push(`<li class="evidence-group-title">反向证据与缺口</li>${visibleCounter.map(item => `<li>${escapeHtml(item)}</li>`).join("")}`);
  if (visibleConfirm.length) rows.push(`<li class="evidence-group-title">确认条件</li>${visibleConfirm.map(item => `<li>${escapeHtml(item)}</li>`).join("")}`);
  if (visibleInvalidation.length) rows.push(`<li class="evidence-group-title">失效条件</li>${visibleInvalidation.map(item => `<li>${escapeHtml(item)}</li>`).join("")}`);
  return rows.length ? `<details class="evidence-details"><summary>展开补充依据</summary><ul>${rows.join("")}</ul></details>` : "";
}

function renderRadar(cards) {
  const target = document.getElementById("opportunity-risk-radar");
  if (!target) return;
  if (!cards.length) {
    target.innerHTML = '<div class="empty-state">当前没有同时满足有效时间和代表股依据的机会或风险。保持等待，不追旧信号；下方可查看待核验方向和历史触发。</div>';
    return;
  }
  const featured = cards.slice(0, 5);
  target.innerHTML = featured.map(card => {
    const kind = card.kind === "risk" ? "risk" : "opportunity";
    const waiting = card.state === "waiting" || card.state === "candidate";
    const visible = activeRadarFilter === "all" || activeRadarFilter === kind || (activeRadarFilter === "waiting" && waiting);
    const hidden = visible ? "" : " hidden";
    return `<article class="radar-card ${escapeHtml(card.state)}" data-radar-kind="${escapeHtml(kind)}" data-radar-state="${escapeHtml(card.state)}"${hidden}>
      <div class="radar-card-kicker"><span>${kind === "risk" ? "风险提醒" : "机会观察"}</span><span class="state-badge ${escapeHtml(card.state)}">${escapeHtml(stateLabel(card.state))}</span></div>
      <div class="radar-head"><h3>${escapeHtml(humanText(card.title))}</h3></div>
      <div class="radar-conclusion"><strong>当前判断</strong><p>${escapeHtml(humanText(card.conclusion))}</p></div>
      <div class="radar-trigger"><strong>发生了什么</strong><p>${escapeHtml(humanText(card.trigger))}</p></div>
      ${renderEnvironmentGate(card)}
      <div class="radar-evidence-lead"><strong>代表股依据</strong>${representativeStocks(list(card.representative_stocks))}</div>
      ${triggerMetrics(card.trigger_metrics)}
      <div class="action-line"><strong>现在怎么办</strong>${escapeHtml(humanText(card.action))}</div>
      ${visibleRiskAndInvalidation(card)}
      ${evidenceDetails(card)}
    </article>`;
  }).join("") + (cards.length > featured.length ? `<div class="radar-cap-note">当前共${escapeHtml(cards.length)}个方向，首屏只保留前5个重点，其余继续观察。</div>` : "");
}

function renderRadarHistory(cards) {
  const target = document.getElementById("opportunity-history");
  if (!target) return;
  if (!cards.length) {
    target.innerHTML = '<div class="empty-state">暂无需要回看的历史触发。</div>';
    return;
  }
  target.innerHTML = `<div class="history-list">${cards.slice(0, 5).map(card => `<article class="history-card">
    <div class="state-row"><h3>${escapeHtml(humanText(card.title))}</h3><span>仅供复盘</span></div>
    <p><strong>当时发生：</strong>${escapeHtml(humanText(card.trigger))}</p>
    ${triggerMetrics(card.trigger_metrics)}
    <p><strong>当时判断：</strong>${escapeHtml(humanText(card.conclusion))}</p>
    <p class="history-action">${escapeHtml(humanText(card.action || "有效时间已结束，不作为当前操作依据。"))}</p>
    ${representativeStocks(list(card.representative_stocks))}
    ${evidenceDetails(card)}
  </article>`).join("")}</div>`;
}

function renderStyle(data) {
  const target = document.getElementById("style-map");
  if (!target) return;
  const dimensions = list(data?.dimensions);
  const shifts = list(data?.theme_shifts);
  target.innerHTML = `<div class="dimension-grid">${dimensions.map(item => `
    <article class="dimension-card">
      <div class="state-row"><h3>${escapeHtml(item.label)}</h3><span class="state-text">${escapeHtml(stateLabel(item.state))}</span></div>
      <p>${escapeHtml(item.conclusion)}</p>
    </article>`).join("")}</div>
    <div class="shift-list">${shifts.slice(0, 8).map(item => `
      <article class="shift-card"><h3>${escapeHtml(item.theme)} · ${escapeHtml(stateLabel(item.state))}</h3><p>${escapeHtml(item.conclusion)}</p>${representativeStocks(list(item.stocks))}</article>`).join("")}</div>`;
}

function renderValidation(items) {
  const target = document.getElementById("validation-queue");
  if (!target) return;
  if (!items.length) {
    target.innerHTML = '<div class="empty-state">没有等待核验的方向。</div>';
    return;
  }
  const queueCard = item => {
    const why = userEvidenceText(item.why_watch_summary || item.why_watch) || "还没有足够的主题依据，先观察，不行动";
    return `<article class="queue-card">
      <div class="state-row"><h3>${escapeHtml(humanText(item.theme))}</h3><span class="state-text">${escapeHtml(item.maturity_label || stateLabel(item.status))}</span></div>
      <div class="case-decision-copy"><strong>当前判断</strong><p>${escapeHtml(item.maturity_label || "等待确认")}：${escapeHtml(humanText(item.action && item.action !== "等待确认" ? item.action : "保持观察，不行动"))}</p></div>
      <div class="case-why-copy"><strong>为什么关注</strong><p>${escapeHtml(why)}</p></div>
      <div class="radar-evidence-lead"><strong>代表股依据</strong>${representativeStocks(list(item.representative_stocks)) || '<p>代表股行情尚未形成，暂不升级。</p>'}</div>
      ${renderEnvironmentGate(item)}
      <p class="conditions"><strong>什么情况下可以加强关注</strong>${escapeHtml(humanText(list(item.confirm_conditions)[0] || "等代表股和板块一起走强"))}</p>
      ${visibleRiskAndInvalidation(item)}
      ${item.valid_window_display ? `<p class="valid-window-copy">${escapeHtml(humanTimeText(item.valid_window_display))}</p>` : ""}
    </article>`;
  };
  const visible = items.slice(0, 10);
  const overflow = items.slice(10);
  target.innerHTML = `<div class="queue-list">${visible.map(queueCard).join("")}</div>${overflow.length ? `<details class="queue-overflow"><summary>查看其余 ${escapeHtml(overflow.length)} 个观察方向</summary><div class="queue-list">${overflow.map(queueCard).join("")}</div></details>` : ""}`;
}

function keyValueBlock(title, values) {
  const entries = Object.entries(values || {});
  if (!entries.length) return "";
  return `<div class="rule-block"><strong>${escapeHtml(title)}</strong>${entries.map(([key, value]) => `<p><b>${escapeHtml(key)}</b>：${escapeHtml(value)}</p>`).join("")}</div>`;
}

function renderPortfolio(data) {
  const target = document.getElementById("portfolio-risk");
  if (!target) return;
  target.innerHTML = `<div class="rule-grid">
    <div class="rule-block"><strong>${escapeHtml(data?.headline || "组合数据不可用")}</strong><div class="tag-list">${list(data?.missing_inputs).map(item => `<span class="tag">缺少：${escapeHtml(item)}</span>`).join("")}</div></div>
    ${keyValueBlock("当前仓位上限", data?.position_limits)}
    ${keyValueBlock("当前风险保护设置", data?.stop_loss)}
  </div>`;
  renderPrivatePortfolio();
}

function optionalNumber(value) {
  return value === "" || value == null ? null : Number(value);
}

function renderPrivatePortfolio() {
  const listTarget = document.getElementById("portfolio-holding-list");
  const analysisTarget = document.getElementById("portfolio-private-analysis");
  if (!listTarget || !analysisTarget) return;
  const holdings = list(privatePortfolio.holdings);
  const invested = holdings.reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.cost || 0), 0);
  const cashKnown = privatePortfolio.cash !== null && privatePortfolio.cash !== "" && Number.isFinite(Number(privatePortfolio.cash));
  const cash = cashKnown ? Number(privatePortfolio.cash) : 0;
  const basis = invested + cash;
  const stockByCode = new Map(list(v2State?.stock_pool?.stocks).map(item => [String(item.code).toLowerCase(), item]));
  const rows = holdings.map(item => {
    const value = Number(item.quantity || 0) * Number(item.cost || 0);
    const allocation = basis > 0 ? value / basis * 100 : null;
    const stock = stockByCode.get(String(item.code).toLowerCase());
    const domain = list(stock?.domains)[0]?.name || "其他/待归类";
    return { ...item, cost_value: value, allocation_pct: allocation, domain };
  });
  const domainValues = {};
  rows.forEach(item => { domainValues[item.domain] = (domainValues[item.domain] || 0) + item.cost_value; });
  const risk = privatePortfolio.risk_budget || {};
  const flags = [];
  rows.forEach(item => {
    if (risk.max_single_position_pct != null && item.allocation_pct != null && item.allocation_pct > Number(risk.max_single_position_pct)) flags.push(`${item.name} 成本占比 ${item.allocation_pct.toFixed(1)}%，高于单一持仓上限 ${Number(risk.max_single_position_pct).toFixed(1)}%。`);
  });
  Object.entries(domainValues).forEach(([domain, value]) => {
    const pct = basis > 0 ? value / basis * 100 : null;
    if (risk.max_theme_pct != null && pct != null && pct > Number(risk.max_theme_pct)) flags.push(`${domain} 成本占比 ${pct.toFixed(1)}%，高于单一主题上限 ${Number(risk.max_theme_pct).toFixed(1)}%。`);
  });
  const investedPct = basis > 0 ? invested / basis * 100 : null;
  if (risk.max_total_invested_pct != null && investedPct != null && investedPct > Number(risk.max_total_invested_pct)) flags.push(`总投入成本占比 ${investedPct.toFixed(1)}%，高于设置上限 ${Number(risk.max_total_invested_pct).toFixed(1)}%。`);
  analysisTarget.innerHTML = holdings.length ? `<div class="private-portfolio-summary"><span>持仓 ${holdings.length} 只</span><span>持仓成本 ¥${invested.toLocaleString("zh-CN", {maximumFractionDigits:2})}</span><span>${cashKnown ? `现金 ¥${cash.toLocaleString("zh-CN", {maximumFractionDigits:2})}` : "现金未填写"}</span><span>${investedPct == null ? "投入比例未知" : `成本投入 ${investedPct.toFixed(1)}%`}</span></div><p class="private-analysis-note">以下仅按数量×成本计算，不代表当前市值或盈亏；实时行情未核验前不生成个性化买卖动作。</p>${flags.length ? `<div class="private-risk-flags">${flags.map(item => `<p>${escapeHtml(item)} <b>需人工复核</b></p>`).join("")}</div>` : '<p class="private-no-flags">按已填写成本口径，暂未触发自设上限；这不代表组合没有市场风险。</p>'}` : '<div class="empty-state">尚未录入真实持仓。您可以只填写风险预算，也可以稍后再录入。</div>';
  listTarget.innerHTML = rows.map(item => `<article class="private-holding-card"><div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.code)}</span></div><p>数量 ${escapeHtml(item.quantity)} · 成本 ${escapeHtml(item.cost)} · ${escapeHtml(item.domain)}</p><small>${item.allocation_pct == null ? "占比待现金数据" : `成本占比 ${item.allocation_pct.toFixed(1)}%`}</small><div class="managed-source-actions"><button type="button" data-holding-action="edit" data-holding-code="${escapeHtml(item.code)}">编辑</button><button type="button" class="danger" data-holding-action="delete" data-holding-code="${escapeHtml(item.code)}">删除</button></div></article>`).join("");
}

function setPortfolioStatus(message, state = "") {
  const target = document.getElementById("portfolio-private-status");
  if (!target) return;
  target.textContent = message;
  target.className = `source-manager-status ${state}`.trim();
}

function hydratePortfolioSettings() {
  const risk = privatePortfolio.risk_budget || {};
  document.getElementById("portfolio-cash").value = privatePortfolio.cash ?? "";
  document.getElementById("portfolio-max-single").value = risk.max_single_position_pct ?? "";
  document.getElementById("portfolio-max-theme").value = risk.max_theme_pct ?? "";
  document.getElementById("portfolio-max-invested").value = risk.max_total_invested_pct ?? "";
  document.getElementById("portfolio-max-drawdown").value = risk.max_drawdown_pct ?? "";
}

async function persistPrivatePortfolio(next, message) {
  const response = await fetch("/_v2-portfolio", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  privatePortfolio = payload.payload;
  hydratePortfolioSettings();
  renderPrivatePortfolio();
  setPortfolioStatus(message, "success");
}

async function loadPrivatePortfolio() {
  try {
    const response = await fetch("/_v2-portfolio", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    privatePortfolio = await response.json();
    hydratePortfolioSettings();
    renderPrivatePortfolio();
    setPortfolioStatus(`本机组合已读取；持仓 ${list(privatePortfolio.holdings).length} 只，交易授权：否。`);
  } catch (_error) {
    renderPrivatePortfolio();
    setPortfolioStatus("组合管理服务暂未连接；公开驾驶舱仍可正常使用。", "warning");
  }
}

function resetHoldingForm() {
  document.getElementById("portfolio-holding-form")?.reset();
  document.getElementById("portfolio-holding-original-code").value = "";
  document.getElementById("portfolio-holding-cancel").hidden = true;
}

function bindPortfolioManager() {
  const settings = document.getElementById("portfolio-settings-form");
  const holdingForm = document.getElementById("portfolio-holding-form");
  const listTarget = document.getElementById("portfolio-holding-list");
  if (!settings || !holdingForm || !listTarget) return;
  settings.addEventListener("submit", async event => {
    event.preventDefault();
    const next = { holdings: list(privatePortfolio.holdings), cash: optionalNumber(document.getElementById("portfolio-cash").value), risk_budget: { max_single_position_pct: optionalNumber(document.getElementById("portfolio-max-single").value), max_theme_pct: optionalNumber(document.getElementById("portfolio-max-theme").value), max_total_invested_pct: optionalNumber(document.getElementById("portfolio-max-invested").value), max_drawdown_pct: optionalNumber(document.getElementById("portfolio-max-drawdown").value) } };
    try { await persistPrivatePortfolio(next, "组合风险设置已保存。") } catch (error) { setPortfolioStatus(`保存失败：${error.message || error}`, "warning"); }
  });
  holdingForm.addEventListener("submit", async event => {
    event.preventDefault();
    const original = document.getElementById("portfolio-holding-original-code").value;
    const row = { code: document.getElementById("portfolio-holding-code").value.trim(), name: document.getElementById("portfolio-holding-name").value.trim(), quantity: Number(document.getElementById("portfolio-holding-quantity").value), cost: Number(document.getElementById("portfolio-holding-cost").value) };
    const nextHoldings = original ? list(privatePortfolio.holdings).map(item => item.code === original ? row : item) : [...list(privatePortfolio.holdings), row];
    try { await persistPrivatePortfolio({ holdings: nextHoldings, cash: privatePortfolio.cash, risk_budget: privatePortfolio.risk_budget || {} }, original ? "持仓已更新。" : "持仓已添加。"); resetHoldingForm(); } catch (error) { setPortfolioStatus(`保存失败：${error.message || error}`, "warning"); }
  });
  document.getElementById("portfolio-holding-cancel").addEventListener("click", resetHoldingForm);
  listTarget.addEventListener("click", async event => {
    const button = event.target.closest("button[data-holding-action]");
    if (!button) return;
    const item = list(privatePortfolio.holdings).find(row => row.code === button.dataset.holdingCode);
    if (!item) return;
    if (button.dataset.holdingAction === "edit") {
      document.getElementById("portfolio-holding-original-code").value = item.code;
      document.getElementById("portfolio-holding-code").value = item.code;
      document.getElementById("portfolio-holding-name").value = item.name;
      document.getElementById("portfolio-holding-quantity").value = item.quantity;
      document.getElementById("portfolio-holding-cost").value = item.cost;
      document.getElementById("portfolio-holding-cancel").hidden = false;
      holdingForm.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (!window.confirm(`删除持仓“${item.name}”？`)) return;
    try { await persistPrivatePortfolio({ holdings: list(privatePortfolio.holdings).filter(row => row.code !== item.code), cash: privatePortfolio.cash, risk_budget: privatePortfolio.risk_budget || {} }, "持仓已删除。"); } catch (error) { setPortfolioStatus(`保存失败：${error.message || error}`, "warning"); }
  });
}

function renderThemes(items) {
  const target = document.getElementById("research-themes");
  if (!target) return;
  target.innerHTML = items.slice(0, 12).map(item => `<article class="theme-card">
    <div class="state-row"><h3>${escapeHtml(item.name)}</h3><span class="state-text">${escapeHtml(item.status)}</span></div>
    <p>${escapeHtml(item.conclusion)}</p>
    <div class="action-line">${escapeHtml(item.action)}</div>
    <div class="tag-list">${list(item.related_topics).slice(0, 5).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
  </article>`).join("") || '<div class="empty-state">产业研究数据尚未接入。</div>';
}

function renderResearchLibrary(data) {
  const target = document.getElementById("research-themes");
  if (!target) return;
  const domains = list(data?.domains);
  const coverageLabel = value => ({coverage_gap: "等待研究证据", template_ready_mapping_gap: "持续研究", mapped: "重点跟踪"}[value] || "持续研究");
  target.innerHTML = domains.map(domain => {
    const caseLink = list(v22DecisionCandidate?.research_links).find(item => item.domain === domain.name);
    const topics = list(domain.topics).slice(0, 6);
    const focus = topics.map(item => item.name).filter(Boolean);
    const template = domain.research_template || {};
    const currentResearch = template.current_research_judgement || {};
    const researchJudgment = domain.coverage_state === "coverage_gap"
      ? "当前证据不足，暂不形成上市公司映射。"
      : domain.coverage_state === "template_ready_mapping_gap"
        ? "产业方向已进入研究，但标的映射仍需公告、订单或收入证据确认。"
        : humanText(currentResearch.summary || `当前重点跟踪：${focus.slice(0, 3).join("、") || "等待明确方向"}。`);
    const researchDetails = domain.research_template ? `<details class="evidence-details"><summary>持续跟踪点与失效条件</summary>
      ${currentResearch.classification ? `<p><strong>${escapeHtml(currentResearch.classification)}</strong></p>` : ""}
      ${list(template.tracking_indicators).map(item => `<p class="condition-copy">观察：${escapeHtml(item)}</p>`).join("")}
      ${list(template.invalidation_conditions).map(item => `<p class="condition-copy invalidation">失效：${escapeHtml(item)}</p>`).join("")}
    </details>` : "";
    return `<article class="theme-card ${escapeHtml(domain.coverage_state)}">
    <div class="state-row"><span class="research-domain-index">${String(domains.indexOf(domain) + 1).padStart(2, "0")}</span><span class="state-text">${escapeHtml(coverageLabel(domain.coverage_state))}</span></div>
    <h3>${escapeHtml(domain.name)}</h3>
    <strong class="research-judgment">${escapeHtml(researchJudgment)}</strong>
    <div class="tag-list">${topics.map(item => `<span class="tag">${escapeHtml(humanText(item.name))}</span>`).join("")}</div>
    ${caseLink?.active_case_count ? `<p class="research-case-link">当前与 ${escapeHtml(caseLink.active_case_count)} 个盘中观察方向有关联。</p>` : '<p class="research-case-link">当前没有进入盘中观察的方向。</p>'}
    <small class="research-coverage-note">已覆盖 ${escapeHtml(domain.topic_count)} 个研究方向 · ${escapeHtml(domain.stock_count)} 只关联标的</small>
    ${researchDetails}
  </article>`}).join("") || '<div class="empty-state">产业研究数据尚未接入。</div>';
}

function renderIndustryTracking(data) {
  const target = document.getElementById("industry-tracking-cards");
  const summary = document.getElementById("industry-tracking-summary");
  if (!target || !summary) return;
  const items = list(data?.items);
  summary.innerHTML = `<div class="layer-summary"><span>持续跟踪 <b>${escapeHtml(data?.tracking_count ?? items.length)}</b> 条</span><span>自动升级 <b>关闭</b></span><span>交易 <b>关闭</b></span></div><p class="layer-boundary-note">行业结论只随正式证据复核；个股单日上涨不会自动升级行业状态。</p>`;
  target.innerHTML = items.map(item => {
    const stocks = list(item.representative_stocks).map(stock => {
      const pct = Number(stock.change_pct);
      const quote = Number.isFinite(pct) ? `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%` : "行情待更新";
      return `<span class="tag">${escapeHtml(stock.name)} ${escapeHtml(quote)}</span>`;
    }).join("");
    const contexts = list(item.linked_market_topics).slice(0, 5).map(topic => `<span class="tag">${escapeHtml(topic.name)} · ${escapeHtml(humanText(topic.state || "待更新"))}</span>`).join("");
    return `<article class="theme-card"><div class="state-row"><span class="research-domain-index">持续跟踪</span><span class="state-text">${escapeHtml(item.classification || "证据不足")}</span></div><h3>${escapeHtml(item.name)}</h3><strong class="research-judgment">${escapeHtml(item.conclusion || "等待研究结论。")}</strong><p class="action-line">${escapeHtml(item.action || "持续观察。")}</p><div class="tag-list">${stocks}</div><div class="tag-list">${contexts}</div><details class="evidence-details"><summary>还差什么与何时失效</summary>${list(item.missing_evidence).map(value => `<p class="condition-copy">待确认：${escapeHtml(value)}</p>`).join("")}<p class="condition-copy invalidation">失效：${escapeHtml(item.failure_trigger || "等待明确失效条件")}</p></details></article>`;
  }).join("") || '<div class="empty-state">行业跟踪数据尚未接入。</div>';
}

async function loadIndustryTracking() {
  if (!document.getElementById("industry-tracking-cards")) return;
  try {
    const response = await fetch(`${V22_INDUSTRY_TRACKING_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("行业跟踪暂不可用");
    renderIndustryTracking(await response.json());
  } catch (_error) {
    document.getElementById("industry-tracking-cards").innerHTML = '<div class="empty-state">行业跟踪暂未更新，保留原有产业研究结果。</div>';
  }
}

function renderStockPool(data) {
  const summary = document.getElementById("stock-pool-summary");
  const target = document.getElementById("stock-pool-list");
  if (!summary || !target) return;
  const allStocks = list(data?.stocks);
  const query = stockPoolQuery.trim().toLowerCase();
  const matches = allStocks.filter(item => {
    const haystack = [item.name, item.code, ...list(item.tags), ...list(item.domains).map(domain => domain.name), ...list(item.themes).map(theme => theme.name)].join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });
  summary.innerHTML = `<div class="pool-summary"><span>共收录 ${escapeHtml(data?.stock_count ?? allStocks.length)} 只</span><span>角色还不明确 ${escapeHtml(data?.role_unclassified_count ?? 0)} 只</span><span>当前显示 ${escapeHtml(Math.min(matches.length, 24))}/${escapeHtml(matches.length)} 只</span></div>`;
  target.innerHTML = matches.slice(0, 24).map(item => `<article class="stock-pool-card">
    <div class="state-row"><h3>${escapeHtml(item.name)}</h3><span class="stock-code">${escapeHtml(item.code)}</span></div>
    <p>${escapeHtml(list(item.domains).map(domain => domain.name).join(" / ") || "待归类")}</p>
    <div class="tag-list">${list(item.tags).slice(0, 5).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
    <details class="evidence-details"><summary>关注依据与触发条件</summary>
      <p>${escapeHtml(item.attention_reason)}</p>
      <p class="condition-copy">确认：${escapeHtml(list(item.trigger_conditions)[0] || "待补明确触发条件")}</p>
      <p class="condition-copy invalidation">失效：${escapeHtml(list(item.invalidation_conditions)[0] || "待补明确失效条件")}</p>
      <p class="definition-version">板块角色：${escapeHtml(list(item.roles).map(value => ROLE_LABELS[value] || value).join(" / "))} · 关注来源：${escapeHtml(list(item.source_pools).map(value => POOL_LABELS[value] || value).join(" / "))}</p><p class="definition-version">为什么这样判断：${escapeHtml(humanText(list(item.role_evidence)[0] || "还缺少明确依据"))}</p>
    </details>
  </article>`).join("") || '<div class="empty-state">没有匹配的股票。</div>';
}

function renderWatchlistSyncShadow(data) {
  const target = document.getElementById("watchlist-sync-shadow-content");
  if (!target) return;
  const view = data?.user_view || {};
  const state = humanText(view["状态"] || "等待首次读取");
  const stateClass = state.includes("阻断") || state.includes("失败") ? "blocked" : (state.includes("完整") ? "usable" : "partial");
  target.innerHTML = `<div class="watchlist-shadow-summary">
    <div><span class="pill ${escapeHtml(stateClass)}">${escapeHtml(state)}</span><strong>我的自选保持不变</strong><p>本次读取到 ${escapeHtml(view["当前读取数量"] ?? 0)} 只。完整性尚未确认前，不会自动删除、替换或降低现有关注。</p></div>
  </div><p class="watchlist-shadow-time">最近读取 ${escapeHtml(compactTime(view["最近读取"]))} · 手动确认始终优先</p>`;
}

async function loadWatchlistSyncShadow() {
  const target = document.getElementById("watchlist-sync-shadow-content");
  if (!target) return;
  try {
    const response = await fetch(`${WATCHLIST_MIGRATION_AUDIT_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("同步对照暂不可用");
    renderWatchlistSyncShadow(await response.json());
  } catch (_error) {
    target.innerHTML = '<div class="empty-state">自选同步对照暂时没有更新成功；现有关注保持不变。</div>';
  }
}

function renderLayerQuote(quote) {
  if (!quote || quote.change_pct == null || !quote.as_of || !quote.source) return '<span class="asset-quote missing">行情待核验</span>';
  const value = Number(quote.change_pct);
  const direction = value > 0 ? "up" : (value < 0 ? "down" : "flat");
  return `<span class="asset-quote ${direction}">${escapeHtml(value > 0 ? "+" : "")}${escapeHtml(value.toFixed(2))}% · ${escapeHtml(compactTime(quote.as_of))} · ${escapeHtml(quote.source)}</span>`;
}

function findUserAssetQuote(code) {
  const normalized = String(code || "").toLowerCase();
  const publicRows = [
    ...list(v22StockPool?.formal_observation?.items),
    ...list(v22StockPool?.formal_observation?.near_ready_items),
    ...list(v22StockPool?.temporary_candidates?.items),
    ...list(v22StockPool?.trading_candidates?.items)
  ];
  const publicMatch = publicRows.find(item => String(item.code || "").toLowerCase() === normalized && item.quote);
  if (publicMatch) return publicMatch.quote;
  const cards = v2State ? [...list(v2State.opportunity_radar), ...list(v2State.opportunity_history), ...list(v2State.validation_queue)] : [];
  for (const card of cards) {
    const stock = list(card.representative_stocks).find(item => String(item.stock_code || "").toLowerCase() === normalized);
    if (stock?.stock_change_pct != null && stock.stock_quote_as_of && stock.stock_quote_source) return { change_pct: stock.stock_change_pct, as_of: stock.stock_quote_as_of, source: stock.stock_quote_source };
  }
  return null;
}

function renderStockPoolLayers() {
  const summary = document.getElementById("stock-pool-v22-summary");
  const userTarget = document.getElementById("user-asset-layer");
  const formalTarget = document.getElementById("formal-observation-layer");
  const temporaryTarget = document.getElementById("temporary-candidate-layer");
  if (!summary || !userTarget || !formalTarget || !temporaryTarget) return;
  const userItems = list(privateUserAssets?.["用户自选"]);
  const formal = v22StockPool?.formal_observation || {};
  const activeFormal = list(formal.items);
  const nearReady = list(formal.near_ready_items);
  const displayedFormal = activeFormal.length ? activeFormal : nearReady;
  const temporary = list(v22StockPool?.temporary_candidates?.items);
  const formalCards = displayedFormal.slice(0, 8).map(item => {
    const sideLabel = { training: "训练侧", edge: "端侧推理" }[item.chain_side] || "跨主题";
    const tierLabel = { high_certainty: "高确定性", high_elasticity: "高弹性" }[item.benefit_tier] || "待分层";
    const observationLabel = [sideLabel, tierLabel, item.evidence_grade ? `证据 ${item.evidence_grade}` : ""].filter(Boolean).join(" · ");
    return `<article class="asset-layer-card"><div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(stockCodeLabel(item.code))}</span></div>${renderLayerQuote(item.quote)}<p>当前判断：${escapeHtml(humanText(item.ai_view || "等待确认"))}</p><p>${escapeHtml(observationLabel)}</p><p>还需补充：${list(item.missing_requirements).slice(0, 3).map(value => escapeHtml(humanText(value))).join("、") || "无"}</p></article>`;
  }).join("");
  summary.innerHTML = `<div class="layer-summary"><span>我的关注 <b>${escapeHtml(userItems.length)}</b></span><span>正式观察 <b>${escapeHtml(formal.active_count ?? 0)}</b></span><span>系统发现 <b>${escapeHtml(v22StockPool?.temporary_candidates?.count ?? 0)}</b></span></div><p class="layer-boundary-note">系统发现不会自动进入我的关注；正式观察也不会自动成为交易候选，需明确允许并通过市场门禁。</p>`;
  userTarget.innerHTML = userItems.slice(0, 8).map(item => `<article class="asset-layer-card user-owned"><div><strong>${escapeHtml(item["名称"] || "名称待核验")}</strong><span>${escapeHtml(stockCodeLabel(item["代码"]))}</span></div>${renderLayerQuote(findUserAssetQuote(item["代码"]))}<p>我的优先级：${escapeHtml(USER_PRIORITY_LABELS[item["用户优先级"]] || "未设置")} · 关注目的：${escapeHtml(USER_INTENT_LABELS[item["关注目的"]] || "未设置")}</p><p>我的备注：${escapeHtml(item["用户备注"] || "未填写")}</p><small>来源：${list(item["有效来源"]).map(value => escapeHtml(USER_SOURCE_LABELS[value] || "用户确认来源")).join(" / ") || "等待核验"}</small></article>`).join("") || '<div class="layer-empty">当前没有已确认的用户关注；同花顺同步对照仍在进行。</div>';
  formalTarget.innerHTML = `${activeFormal.length ? "" : '<p class="layer-warning">当前没有正式观察结果；以下标的是研究信息较完整的待确认对象。</p>'}${formalCards || '<div class="layer-empty">当前未形成正式观察。</div>'}`;
  temporaryTarget.innerHTML = temporary.slice(0, 8).map(item => `<article class="asset-layer-card temporary"><div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(stockCodeLabel(item.code))}</span></div>${renderLayerQuote(item.quote)}<p>${escapeHtml(humanText(item.ai_view || "系统发现，尚未加入我的关注"))}</p><p>发现依据：${escapeHtml(humanText(item.discovery_context || "等待补充"))}</p><small>风险：${escapeHtml(humanText(item.risk || "等待核验"))}</small></article>`).join("") || '<div class="layer-empty">当前系统线索没有可核验代表股。</div>';
}

function renderCockpitUserContext() {
  const target = document.getElementById("cockpit-user-assets");
  if (!target) return;
  const userItems = list(privateUserAssets?.["用户自选"]);
  if (!userItems.length) {
    target.innerHTML = '<div class="cockpit-asset-message"><strong>当前没有已确认的用户资产</strong><p>机会雷达继续展示市场结果。</p></div>';
    return;
  }
  const currentRadar = v2State ? radarByCurrentTime(v2State).current : [];
  const radarStocks = new Map();
  currentRadar.forEach(card => list(card.representative_stocks).forEach(stock => {
    const code = String(stock.stock_code || "").toLowerCase();
    if (code) radarStocks.set(code, { card, stock });
  }));
  const matches = userItems.map(item => ({ item, match: radarStocks.get(String(item["代码"] || "").toLowerCase()) })).filter(row => row.match);
  if (!matches.length) {
    target.innerHTML = `<div class="cockpit-asset-message"><strong>当前机会未见用户关注标的参与</strong><p>已检查 ${escapeHtml(userItems.length)} 只用户确认资产；这是一条反向证据，不代表相关板块一定无效。</p></div>`;
    return;
  }
  target.innerHTML = `<div class="cockpit-asset-list">${matches.slice(0, 8).map(({item, match}) => `<article><strong>${escapeHtml(item["名称"])}</strong><span>${escapeHtml(item["代码"])}</span><p>当前关联：${escapeHtml(match.card.title || "机会待核验")} · ${escapeHtml(match.card.action || "等待确认")}</p></article>`).join("")}</div>`;
}

async function loadStockPoolLayers() {
  if (!document.getElementById("stock-pool-v22") && !document.getElementById("cockpit-user-assets")) return;
  try {
    const [publicResponse, privateResponse] = await Promise.all([
      fetch(`${V22_STOCK_POOL_URL}?v=${Date.now()}`, { cache: "no-store" }),
      fetch("/_v2-user-assets", { cache: "no-store" })
    ]);
    if (!publicResponse.ok) throw new Error("股票池分层暂不可用");
    v22StockPool = await publicResponse.json();
    privateUserAssets = privateResponse.ok ? await privateResponse.json() : { "状态": "暂不可用", "数量": 0, "用户自选": [] };
    renderStockPoolLayers();
    renderCockpitUserContext();
  } catch (_error) {
    const target = document.getElementById("stock-pool-v22-summary") || document.getElementById("cockpit-user-assets");
    if (target) target.innerHTML = '<div class="empty-state">股票池分层暂时没有更新成功；现有V2页面继续可用。</div>';
  }
}

function renderReview(data, model) {
  const target = document.getElementById("signal-review");
  if (!target) return;
  const recommendation = model?.recommendation || {};
  target.innerHTML = `<div class="review-grid">
    <div class="review-empty"><strong>${escapeHtml(humanText(data?.headline || "复盘暂不可用"))}</strong>
      <p>后续观察：${list(data?.windows).map(escapeHtml).join(" / ")}</p>
      <div class="pool-summary"><span>已记录判断 ${escapeHtml(data?.snapshot_count ?? 0)}</span><span>等待结果 ${escapeHtml(data?.pending_signal_count ?? 0)}</span><span>已有结果 ${escapeHtml(data?.evaluated_signal_count ?? 0)}</span></div>
      <p class="review-guardrail">${escapeHtml(humanText(data?.guardrail || "样本不足不展示命中率。"))}</p>
    </div>
    <div class="model-evaluation-card"><strong>目前可以得出什么</strong><p>主要观察窗口 ${escapeHtml(model?.primary_window || "待定")} · 已有 ${escapeHtml(model?.record_count ?? 0)} 例结果</p><p>${escapeHtml(humanText(recommendation.reason || "等待更多结果。"))}</p></div>
  </div>`;
}

function renderParallelComparison(data) {
  const target = document.getElementById("parallel-comparison");
  if (!target) return;
  const sideCard = side => `<div class="parallel-side-card"><div class="state-row"><strong>${escapeHtml(side?.label || "未知")}</strong><span>${escapeHtml(side?.market_date || "日期待核验")}</span></div><div class="parallel-number-grid"><span><b>${escapeHtml(side?.opportunity_count ?? 0)}</b>机会</span><span><b>${escapeHtml(side?.risk_count ?? 0)}</b>风险</span></div><small>信息截至 ${escapeHtml(compactTime(side?.evidence_as_of))}</small></div>`;
  const divergences = list(data?.divergences)
    .filter(item => !/质量问题|自动化|价格复核|仅V1|仅V2/.test(`${item?.conclusion || ""}${item?.action || ""}`))
    .slice(0, 2);
  target.innerHTML = `<div class="parallel-summary"><strong>${escapeHtml(humanText(data?.headline || "版本对照尚未形成"))}</strong><span>${data?.cutover?.ready ? "可以申请扩大使用" : "继续观察"}</span></div><div class="parallel-sides">${sideCard(data?.v1)}${sideCard(data?.v2)}</div><div class="parallel-divergences"><strong>当前差异</strong>${divergences.length ? divergences.map(item => `<div class="parallel-diff"><b>${escapeHtml(humanText(item.conclusion))}</b><p>${escapeHtml(humanText(item.action))}</p></div>`).join("") : '<p class="empty-state">当前没有需要特别解释的差异。</p>'}</div><p class="parallel-guardrail">${escapeHtml(humanText(data?.cutover?.reason || "继续积累同日结果。"))}</p>`;
}

function renderGovernance(data, inputStatus) {
  const target = document.getElementById("governance-status");
  if (!target) return;
  const events = data?.event_registry || {};
  const routing = data?.automation_routing || {};
  const inputs = list(inputStatus?.contracts);
  const publicCollectors = list(inputStatus?.public_collectors);
  const authorizations = data?.user_authorizations || {};
  target.innerHTML = `<div class="governance-grid">
    <div class="governance-card"><strong>事件与关注来源</strong><p>事件 ${escapeHtml(events.event_count ?? 0)} 条 · ${events.state === "input_pending" ? "输入待接入" : "已接入"}</p><p>已配置关注账号 ${escapeHtml(events.blogger_enabled_account_count ?? 0)} 个</p></div>
    <div class="governance-card"><strong>数据任务状态</strong><p>已登记 ${escapeHtml(routing.task_count ?? 0)} 项 · ${escapeHtml(stateLabel(routing.state))}</p></div>
    <div class="governance-card"><strong>数据输入</strong><p>${escapeHtml(inputStatus?.privacy_note || "原始输入不进入公开发布。")}</p><div class="input-status-list">${publicCollectors.map(item => `<span class="${escapeHtml(item.state)}">${escapeHtml(INPUT_LABELS[item.id] || item.id)} · ${escapeHtml(stateLabel(item.state))}</span>`).join("")}${inputs.map(item => `<span class="${escapeHtml(item.status)}">${escapeHtml(INPUT_LABELS[item.id] || item.id)} · ${escapeHtml(stateLabel(item.status))}</span>`).join("") || "尚未运行导入检查"}</div></div>
    <div class="governance-card"><strong>本机访问状态</strong><p>${authorizations.routine_external_app_access === "preauthorized" ? "常规读取与核验已授权。" : "尚未记录常规访问授权。"}</p></div>
  </div>`;
}

function logicSearchText(item) {
  return [item.title, item.category, item.summary, ...list(item.rules), ...list(item.exceptions), ...list(item.keywords)].join(" ").toLowerCase();
}

function renderLogicCatalog() {
  const target = document.getElementById("logic-catalog");
  const summary = document.getElementById("logic-result-summary");
  if (!target || !summary) return;
  const query = logicSearchQuery.trim().toLowerCase();
  const entries = list(logicCatalogState.entries).filter(item => {
    const categoryMatches = logicCategory === "all" || item.category === logicCategory;
    return categoryMatches && (!query || logicSearchText(item).includes(query));
  });
  summary.textContent = query || logicCategory !== "all"
    ? `找到 ${entries.length} 条相关逻辑`
    : `共 ${entries.length} 条逻辑，更新于 ${logicCatalogState.updated_at || "待确认"}`;
  target.innerHTML = entries.map(item => `<article class="logic-card">
    <div class="logic-card-head"><span>${escapeHtml(item.category || "其他")}</span><h2>${escapeHtml(item.title || "未命名逻辑")}</h2></div>
    <p class="logic-card-summary">${escapeHtml(humanText(item.summary || "暂无说明"))}</p>
    <details><summary>查看完整逻辑</summary>
      <div class="logic-detail-grid"><section><strong>当前规则</strong><ul>${list(item.rules).map(value => `<li>${escapeHtml(humanText(value))}</li>`).join("")}</ul></section><section><strong>例外与失效</strong><ul>${list(item.exceptions).map(value => `<li>${escapeHtml(humanText(value))}</li>`).join("")}</ul></section></div>
      ${list(item.sources).length ? `<div class="logic-sources"><strong>参考依据</strong>${list(item.sources).map(source => source.url ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.title || "查看来源")}</a>` : "").join("")}</div>` : ""}
    </details>
    ${item.result_page?.url ? `<a class="logic-result-link" href="${escapeHtml(item.result_page.url)}">查看${escapeHtml(item.result_page.label || "对应结果")} →</a>` : ""}
  </article>`).join("") || '<div class="empty-state">没有找到匹配的逻辑。可以尝试“中登”“什么情况下可以关注”或“外盘对A股的影响”。</div>';
}

function bindLogicCatalog() {
  const search = document.getElementById("logic-search");
  const category = document.getElementById("logic-category-filter");
  if (!search || !category) return;
  search.addEventListener("input", () => {
    logicSearchQuery = search.value || "";
    renderLogicCatalog();
  });
  category.addEventListener("change", () => {
    logicCategory = category.value || "all";
    renderLogicCatalog();
  });
}

async function loadLogicCatalog() {
  const target = document.getElementById("logic-catalog");
  const category = document.getElementById("logic-category-filter");
  if (!target || !category) return;
  try {
    const response = await fetch(`${V2_LOGIC_CATALOG_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("逻辑目录暂不可用");
    logicCatalogState = await response.json();
    category.innerHTML = '<option value="all">全部类别</option>' + list(logicCatalogState.categories).map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
    renderLogicCatalog();
  } catch (_error) {
    target.innerHTML = '<div class="empty-state error-state">逻辑目录暂时没有加载成功，请稍后刷新。</div>';
    const summary = document.getElementById("logic-result-summary");
    if (summary) summary.textContent = "加载失败";
  }
}

function setBloggerStatus(message, state = "") {
  const target = document.getElementById("blogger-source-status");
  if (!target) return;
  target.textContent = message;
  target.className = `source-manager-status ${state}`.trim();
}

function renderBloggerSources() {
  const target = document.getElementById("blogger-source-list");
  if (!target) return;
  if (!bloggerAccounts.length) {
    target.innerHTML = '<div class="empty-state">尚未添加关注来源。添加后，采集任务会按平台能力读取公开内容。</div>';
    return;
  }
  target.innerHTML = bloggerAccounts.map(item => `<article class="managed-source-card ${item.enabled === false ? "disabled" : ""}">
    <div><span class="source-platform">${escapeHtml(BLOGGER_PLATFORM_LABELS[item.platform] || item.platform)}</span><strong>${escapeHtml(item.display_name)}</strong><small>${item.enabled === false ? "已停用" : "已启用"}</small></div>
    <p>${escapeHtml(item.note || "未填写关注说明")}</p>
    <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">核验原始链接</a>
    <div class="managed-source-actions"><button type="button" data-source-action="edit" data-source-id="${escapeHtml(item.id)}">编辑</button><button type="button" data-source-action="toggle" data-source-id="${escapeHtml(item.id)}">${item.enabled === false ? "启用" : "停用"}</button><button type="button" class="danger" data-source-action="delete" data-source-id="${escapeHtml(item.id)}">删除</button></div>
  </article>`).join("");
}

async function persistBloggerSources(nextAccounts, successMessage) {
  const response = await fetch("/_v2-blogger-accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accounts: nextAccounts })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  bloggerAccounts = list(payload.payload?.accounts);
  renderBloggerSources();
  setBloggerStatus(successMessage, "success");
}

async function loadBloggerSources() {
  try {
    const response = await fetch("/_v2-blogger-accounts", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    bloggerAccounts = list(payload.accounts);
    renderBloggerSources();
    setBloggerStatus(`本机已保存 ${bloggerAccounts.length} 个来源；账号与链接不会进入公开发布。`);
  } catch (_error) {
    renderBloggerSources();
    setBloggerStatus("来源管理服务暂未连接。请从本地投资看板入口打开本页，其他决策模块不受影响。", "warning");
  }
}

function resetBloggerForm() {
  document.getElementById("blogger-source-form")?.reset();
  document.getElementById("blogger-source-id").value = "";
  document.getElementById("blogger-source-cancel").hidden = true;
}

function bindBloggerManager() {
  const form = document.getElementById("blogger-source-form");
  const listTarget = document.getElementById("blogger-source-list");
  if (!form || !listTarget) return;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const id = document.getElementById("blogger-source-id").value;
    const row = {
      id,
      platform: document.getElementById("blogger-source-platform").value,
      display_name: document.getElementById("blogger-source-name").value.trim(),
      url: document.getElementById("blogger-source-url").value.trim(),
      note: document.getElementById("blogger-source-note").value.trim(),
      enabled: id ? bloggerAccounts.find(item => item.id === id)?.enabled !== false : true
    };
    const next = id ? bloggerAccounts.map(item => item.id === id ? row : item) : [...bloggerAccounts, row];
    try {
      await persistBloggerSources(next, id ? "来源已更新。" : "来源已添加。");
      resetBloggerForm();
    } catch (error) {
      setBloggerStatus(`保存失败：${error.message || error}`, "warning");
    }
  });
  document.getElementById("blogger-source-cancel").addEventListener("click", resetBloggerForm);
  listTarget.addEventListener("click", async event => {
    const button = event.target.closest("button[data-source-action]");
    if (!button) return;
    const id = button.dataset.sourceId;
    const item = bloggerAccounts.find(row => row.id === id);
    if (!item) return;
    if (button.dataset.sourceAction === "edit") {
      document.getElementById("blogger-source-id").value = item.id;
      document.getElementById("blogger-source-platform").value = item.platform;
      document.getElementById("blogger-source-name").value = item.display_name;
      document.getElementById("blogger-source-url").value = item.url;
      document.getElementById("blogger-source-note").value = item.note || "";
      document.getElementById("blogger-source-cancel").hidden = false;
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (button.dataset.sourceAction === "delete" && !window.confirm(`删除“${item.display_name}”？`)) return;
    const next = button.dataset.sourceAction === "delete"
      ? bloggerAccounts.filter(row => row.id !== id)
      : bloggerAccounts.map(row => row.id === id ? { ...row, enabled: row.enabled === false } : row);
    try {
      await persistBloggerSources(next, button.dataset.sourceAction === "delete" ? "来源已删除。" : "来源状态已更新。");
    } catch (error) {
      setBloggerStatus(`保存失败：${error.message || error}`, "warning");
    }
  });
}

function renderSources(items) {
  const target = document.getElementById("source-registry");
  if (!target) return;
  target.innerHTML = `<div class="source-list">${items.map(item => `<div class="source-item"><b>${escapeHtml(sourceLabel(item.path))}</b><span>${escapeHtml(stateLabel(item.status))} · ${escapeHtml(compactTime(item.timestamp))}</span></div>`).join("")}</div>`;
}

function setText(id, value) {
  const target = document.getElementById(id);
  if (target) target.textContent = value;
}

function renderHome(data) {
  const environment = data.market_environment || {};
  const radar = radarByCurrentTime(data).current;
  const opportunityCards = radar.filter(item => item.kind !== "risk");
  const riskCards = radar.filter(item => item.kind === "risk");
  const validation = list(data.validation_queue);
  const opportunities = opportunityCards.length;
  const risks = riskCards.length;
  setText("home-market-action", environment.action || "等待确认");
  setText("home-market-copy", environment.headline || "市场环境等待生成");
  setText("home-opportunity-summary", opportunityCards[0]?.title || "当前没有确认机会");
  setText("home-risk-summary", riskCards[0]?.title || "暂无新增风险信号");
  setText("home-next-check", validation[0]?.theme || "保持等待，等条件出现");
  setText("home-opportunity-count", opportunities);
  setText("home-risk-count", risks);
  setText("home-validation-count", validation.length);
  setText("home-stock-count", data.stock_pool?.stock_count ?? 0);
  setText("home-evidence-time", compactTime(data.system?.decision_as_of));
}

function setFilter(value) {
  activeRadarFilter = value;
  document.querySelectorAll("#radar-filters button").forEach(button => button.classList.toggle("active", button.dataset.filter === value));
  document.querySelectorAll("[data-radar-kind]").forEach(card => {
    const waiting = card.dataset.radarState === "waiting" || card.dataset.radarState === "candidate";
    card.hidden = !(value === "all" || card.dataset.radarKind === value || (value === "waiting" && waiting));
  });
}

function bindFilters() {
  document.querySelectorAll("#radar-filters button").forEach(button => {
    button.addEventListener("click", () => setFilter(button.dataset.filter || "all"));
  });
}

function bindStockSearch() {
  const input = document.getElementById("stock-pool-search");
  if (!input) return;
  input.addEventListener("input", () => {
    stockPoolQuery = input.value || "";
    renderStockPool(v2State?.stock_pool || {});
  });
}

function radarByCurrentTime(data) {
  const now = Date.now();
  const current = [];
  const history = [...list(data.opportunity_history)];
  for (const card of list(data.opportunity_radar)) {
    const until = card.valid_until ? new Date(card.valid_until).getTime() : NaN;
    if (!Number.isFinite(until) || until < now) history.push({ ...card, state: "expired" });
    else current.push(card);
  }
  const seen = new Set();
  return {
    current,
    history: history.filter(card => {
      const key = card.id || `${card.title}-${card.triggered_at || card.valid_until || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
  };
}

function renderAll(data, refreshReason = "自动更新") {
  v2State = data;
  const system = data.system || {};
  const radar = radarByCurrentTime(data);
  setText("v2-mode", "AI辅助判断");
  setText("v2-updated", `信息截至 ${compactTime(system.decision_as_of)}`);
  setText("v2-refresh-status", `更新于 ${compactTimeWithSeconds(new Date().toISOString())} · ${refreshReason}`);
  const qualityState = data.data_quality_gate?.state || "blocked";
  const status = document.getElementById("v2-status");
  if (status) {
    const isDataStatusPage = document.body.classList.contains("page-governance") || window.location.pathname.endsWith("/v2-governance.html");
    if (isDataStatusPage) {
      status.hidden = false;
      status.textContent = qualityState === "usable" ? "信息已更新" : (qualityState === "blocked" ? "关键数据不足" : "部分信息待更新");
      status.className = `pill ${qualityState}`;
    } else {
      status.hidden = true;
    }
  }
  renderHome(data);
  renderQuality(data.data_quality_gate || {});
  renderEnvironment(data.market_environment || {});
  renderRadar(radar.current);
  renderRadarHistory(radar.history);
  renderStyle(data.style_map || {});
  renderValidation(list(data.validation_queue));
  renderPortfolio(data.portfolio_risk || {});
  renderResearchLibrary(data.research_library || {});
  renderStockPool(data.stock_pool || {});
  renderReview(data.signal_review || {}, data.model_evaluation || {});
  renderParallelComparison(data.parallel_comparison || {});
  renderGovernance(data.governance || {}, data.input_status || {});
  renderSources(list(data.source_registry));
  renderCockpitUserContext();
  if (v22DecisionCandidate) renderDecisionCandidateV22(v22DecisionCandidate);
  applyV22MarketPageCurrentView();
}

function renderDecisionCandidateV22(data) {
  v22DecisionCandidate = data;
  const summary = data?.summary || {};
  const clueSummary = data?.unformed_clue_summary || {};
  const currentClues = summary.unformed_clues ?? 0;
  const parkedClues = summary.parked_clues ?? clueSummary.parked_count ?? 0;
  const readyCount = summary.decision_ready ?? 0;
  const waitingCount = summary.awaiting_confirmation ?? 0;
  setText("home-v22-candidate-state", data?.availability === "可用" ? "当前判断已更新" : "当前判断待更新");
  setText("home-v22-candidate-copy", readyCount > 0 ? `${readyCount} 个方向具备完整依据，${waitingCount} 个方向仍需确认。` : `当前没有具备完整依据的机会，${waitingCount} 个方向仍在观察。`);
  setText(
    "v22-case-projection-note",
    readyCount > 0
      ? `当前有 ${readyCount} 个方向具备完整依据，另有 ${waitingCount} 个方向等待确认。`
      : `当前没有具备完整依据的机会；${waitingCount} 个方向仍在观察，保持等待。`
  );
  const clueTarget = document.getElementById("v22-clue-explanation");
  if (clueTarget) {
    clueTarget.textContent = currentClues || parkedClues
      ? "证据不足的方向只保留观察；代表股、市场环境和有效时间同时确认后，才会进入当前机会。"
      : "当前观察方向已按代表股、市场环境、行动条件和失效条件完成核对。";
  }
  if (document.getElementById("opportunity-risk-radar")) {
    renderRadar(list(data?.current_cases));
    renderValidation(list(data?.validation_cases));
    renderRadarHistory(list(data?.history_cases));
  }
  if (document.getElementById("research-themes") && v2State?.research_library) renderResearchLibrary(v2State.research_library);
}

async function loadDecisionCandidateV22() {
  if (!document.getElementById("opportunity-risk-radar") && !document.getElementById("home-v22-candidate-state") && !document.getElementById("research-themes") && !document.getElementById("cockpit-user-assets")) return;
  try {
    const response = await fetch(`${V22_DECISION_CANDIDATE_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("候选案例暂不可用");
    renderDecisionCandidateV22(await response.json());
  } catch (_error) {
    setText("home-v22-candidate-state", "暂未更新");
    setText("home-v22-candidate-copy", "当前结果暂未更新。");
    setText("v22-case-projection-note", "案例结果暂未更新，保留上次可用结果。");
  }
}

function renderV22Learning(replay, evaluation, comparison) {
  const target = document.getElementById("v22-learning-summary");
  if (!target) return;
  const baseline = comparison?.v2_baseline || {};
  const candidate = comparison?.v22_candidate || {};
  target.innerHTML = `<div class="v22-learning-grid"><article><span>已记录当时行情</span><strong>${escapeHtml(replay?.trigger_quote_snapshot_count ?? 0)} 次</strong><p>同时保留 ${escapeHtml(replay?.decision_case_snapshot_count ?? replay?.snapshot_count ?? 0)} 次当时判断，后续不会覆盖。</p></article><article><span>已有后续结果</span><strong>${escapeHtml(evaluation?.record_count ?? 0)} 例</strong><p>${escapeHtml(humanText(evaluation?.recommendation?.reason || "等待更多结果。"))}</p></article><article><span>等待确认的方向</span><strong>${escapeHtml(baseline.validation_count ?? 0)} → ${escapeHtml(candidate.validation_count ?? 0)}</strong><p>只有依据完整的方向才进入当前机会。</p></article></div><div class="v22-learning-hold"><strong>当前结论：继续观察</strong><p>${escapeHtml(humanText(comparison?.cutover?.reason || "仍需积累结果。"))}</p></div>`;
}

async function loadV22Learning() {
  const target = document.getElementById("v22-learning-summary");
  if (!target) return;
  try {
    const [replayResponse, evaluationResponse, parallelResponse] = await Promise.all([
      fetch(`${V22_REPLAY_URL}?v=${Date.now()}`, { cache: "no-store" }),
      fetch(`${V22_EVALUATION_URL}?v=${Date.now()}`, { cache: "no-store" }),
      fetch(`${V22_PARALLEL_URL}?v=${Date.now()}`, { cache: "no-store" })
    ]);
    if (!replayResponse.ok || !evaluationResponse.ok || !parallelResponse.ok) throw new Error("回溯结果暂不可用");
    renderV22Learning(await replayResponse.json(), await evaluationResponse.json(), await parallelResponse.json());
  } catch (_error) {
    target.innerHTML = '<div class="empty-state">回溯结果暂未更新，保留上次可用结果。</div>';
  }
}

async function loadV2(refreshReason = "自动更新") {
  if (v2LoadInFlight) return;
  v2LoadInFlight = true;
  try {
    const response = await fetch(`${V2_DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderAll(await response.json(), refreshReason);
    await loadCockpitPhaseView();
  } catch (_error) {
    const radar = document.getElementById("opportunity-risk-radar") || document.getElementById("page-load-error");
    if (radar && !v2State) radar.innerHTML = '<div class="empty-state error-state">数据暂时没有更新成功，请稍后重试。</div>';
    setText("v2-refresh-status", `更新失败 · ${refreshReason} · 当前信息可能已过时`);
    const status = document.getElementById("v2-status");
    if (status) {
      status.textContent = "加载失败";
      status.className = "pill blocked";
    }
  } finally {
    v2LoadInFlight = false;
  }
}

function startRadarAutoRefresh() {
  if ((!document.getElementById("opportunity-risk-radar") && !document.body.classList.contains("trading-session-page")) || radarRefreshTimer) return;
  radarRefreshTimer = setInterval(() => {
    if (document.visibilityState === "visible") loadV2("30秒自动更新");
  }, 30000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadV2("返回页面更新");
  });
  if (typeof window.addEventListener === "function") {
    window.addEventListener("focus", () => loadV2("重新聚焦更新"));
    window.addEventListener("pagehide", () => {
      if (radarRefreshTimer) clearInterval(radarRefreshTimer);
      radarRefreshTimer = null;
    });
  }
}

window.V2App = { loadV2, renderAll, setFilter, renderStockPool, renderWatchlistSyncShadow, renderStockPoolLayers, renderIndustryTracking, renderCockpitUserContext, renderCockpitPhaseView, renderEnvironmentV22, renderEnvironmentDecisionV22, renderEnvironmentGate, renderDecisionCandidateV22, escapeHtml };
bindFilters();
bindStockSearch();
bindLogicCatalog();
bindBloggerManager();
bindPortfolioManager();
if (document.getElementById("blogger-source-list")) loadBloggerSources();
if (document.getElementById("portfolio-holding-list")) loadPrivatePortfolio();
if (document.getElementById("watchlist-sync-shadow-content")) loadWatchlistSyncShadow();
loadStockPoolLayers();
loadIndustryTracking();
loadMarketEnvironmentV22();
loadEnvironmentDecisionV22();
loadDecisionCandidateV22();
loadV22Learning();
loadLogicCatalog();
startRadarAutoRefresh();
loadV2("首次加载");

#!/usr/bin/env node
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "data", "runtime-smoke-report.json");
const BAD_LITERALS = ["[object Object]", "undefined", "None%", "NaN", "Infinity"];
const MOJIBAKE_RE = /[�ÃÂ]|(?:æ|å|ç|è|é)[A-Za-z0-9_\- ]{0,8}/;
const OPTIONAL_FILES = new Set(["data/signal-review.json"]);
const REQUIRED_RENDER_TARGETS = [
  "dashboard-control",
  "data-quality-gate",
  "opportunity-risk-radar",
  "watchlist-decision",
  "portfolio-risk",
  "signal-review",
  "alerts-summary",
  "intraday-decision",
  "intraday-indices",
  "premarket",
  "midday",
  "postmarket",
  "evening",
  "topics"
];

class FakeElement {
  constructor(tagName = "div", ownerDocument = null) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.attributes = {};
    this._id = "";
    this.className = "";
    this.innerHTML = "";
    this._textContent = "";
  }

  get id() {
    return this._id;
  }

  set id(value) {
    this._id = String(value || "");
    if (this._id && this.ownerDocument) {
      this.ownerDocument.elements.set(this._id, this);
    }
  }

  get textContent() {
    return this._textContent || this.innerHTML || this.children.map(child => child.textContent).join("");
  }

  set textContent(value) {
    this._textContent = String(value ?? "");
    this.innerHTML = "";
  }

  get innerText() {
    return this.textContent;
  }

  set innerText(value) {
    this.textContent = value;
  }

  get nextSibling() {
    if (!this.parentNode) return null;
    const index = this.parentNode.children.indexOf(this);
    return index >= 0 ? this.parentNode.children[index + 1] || null : null;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  insertBefore(child, reference) {
    child.parentNode = this;
    if (!reference) {
      this.children.push(child);
      return child;
    }
    const index = this.children.indexOf(reference);
    if (index < 0) {
      this.children.push(child);
    } else {
      this.children.splice(index, 0, child);
    }
    return child;
  }

  insertAdjacentElement(position, element) {
    if (position === "afterend" && this.parentNode) {
      const index = this.parentNode.children.indexOf(this);
      element.parentNode = this.parentNode;
      this.parentNode.children.splice(index + 1, 0, element);
      return element;
    }
    return this.appendChild(element);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "id") this.id = value;
    if (name === "class") this.className = String(value);
  }

  closest(selector) {
    if (!selector.startsWith(".")) return null;
    const cls = selector.slice(1);
    let node = this;
    while (node) {
      if (node.hasClass(cls)) return node;
      node = node.parentNode;
    }
    return null;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const results = [];
    const match = node => {
      if (selector.startsWith(".")) return node.hasClass(selector.slice(1));
      if (selector.startsWith("#")) return node.id === selector.slice(1);
      return node.tagName.toLowerCase() === selector.toLowerCase();
    };
    const walk = node => {
      for (const child of node.children) {
        if (match(child)) results.push(child);
        walk(child);
      }
    };
    walk(this);
    return results;
  }

  hasClass(cls) {
    return String(this.className || "").split(/\s+/).includes(cls);
  }

  collectHtml() {
    return [
      this.innerHTML || "",
      this._textContent || "",
      ...this.children.map(child => child.collectHtml())
    ].join("");
  }
}

class FakeDocument {
  constructor(indexHtml) {
    this.elements = new Map();
    this.body = new FakeElement("body", this);
    this.buildFromIndex(indexHtml);
  }

  createElement(tagName) {
    return new FakeElement(tagName, this);
  }

  getElementById(id) {
    return this.elements.get(id) || null;
  }

  querySelectorAll(selector) {
    return this.body.querySelectorAll(selector);
  }

  buildFromIndex(indexHtml) {
    const allIds = [...indexHtml.matchAll(/id="([^"]+)"/g)].map(match => match[1]);
    for (const id of allIds) {
      if (!this.elements.has(id)) {
        const el = this.createElement("div");
        el.id = id;
        this.body.appendChild(el);
      }
    }

    const sectionRe = /<section\b([^>]*)>([\s\S]*?)<\/section>/g;
    let sectionMatch;
    while ((sectionMatch = sectionRe.exec(indexHtml))) {
      const attrs = sectionMatch[1];
      const body = sectionMatch[2];
      const sectionId = firstMatch(attrs, /id="([^"]+)"/);
      if (!sectionId) continue;
      const section = this.getElementById(sectionId) || this.createElement("section");
      section.id = sectionId;
      section.className = firstMatch(attrs, /class="([^"]+)"/) || "panel";
      section.tagName = "SECTION";

      const h2 = this.createElement("h2");
      h2.textContent = stripTags(firstMatch(body, /<h2[^>]*>([\s\S]*?)<\/h2>/) || "");
      section.appendChild(h2);

      const childIds = [...body.matchAll(/id="([^"]+)"/g)].map(match => match[1]).filter(id => id !== sectionId);
      for (const id of childIds) {
        const child = this.getElementById(id) || this.createElement("div");
        child.id = id;
        child.parentNode = null;
        section.appendChild(child);
      }
    }

    const classMatches = [...indexHtml.matchAll(/class="([^"]*\bsector-grid\b[^"]*)"/g)];
    for (const match of classMatches) {
      const el = this.createElement("div");
      el.className = match[1];
      this.body.appendChild(el);
    }
  }
}

function firstMatch(text, re) {
  const match = String(text || "").match(re);
  return match ? match[1] : "";
}

function stripTags(text) {
  return String(text || "").replace(/<[^>]+>/g, "").trim();
}

function readText(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), "utf8");
}

function readJsonIfExists(relPath) {
  try {
    return JSON.parse(readText(relPath));
  } catch {
    return {};
  }
}

function writeReport(report) {
  fs.writeFileSync(OUT, JSON.stringify(report, null, 2) + "\n", "utf8");
}

function nowIso() {
  const date = new Date();
  const offsetMs = 8 * 60 * 60 * 1000;
  return new Date(date.getTime() + offsetMs).toISOString().replace(/\.\d{3}Z$/, "+08:00");
}

function issue(severity, code, message, target = "") {
  return { severity, code, message, target };
}

async function main() {
  const issues = [];
  const consoleErrors = [];
  const indexHtml = readText("index.html");
  const appCode = readText("app.js");
  const document = new FakeDocument(indexHtml);
  const context = {
    document,
    window: {},
    navigator: { onLine: true },
    localStorage: {
      store: new Map(),
      getItem(key) {
        return this.store.has(key) ? this.store.get(key) : null;
      },
      setItem(key, value) {
        this.store.set(String(key), String(value));
      },
      removeItem(key) {
        this.store.delete(String(key));
      },
      clear() {
        this.store.clear();
      }
    },
    console: {
      log: () => {},
      warn: (...args) => consoleErrors.push(args.map(String).join(" ")),
      error: (...args) => consoleErrors.push(args.map(String).join(" "))
    },
    Date,
    JSON,
    Math,
    Number,
    String,
    Array,
    Object,
    RegExp,
    Set,
    Map,
    Promise,
    setInterval: () => 0,
    clearInterval: () => {},
    setTimeout: fn => {
      if (typeof fn === "function") fn();
      return 0;
    },
    fetch: async url => {
      const rel = String(url).split("?")[0].replace(/^\//, "");
      const abs = path.join(ROOT, rel);
      if (!fs.existsSync(abs)) {
        if (OPTIONAL_FILES.has(rel)) throw new Error(`optional missing: ${rel}`);
        throw new Error(`missing file: ${rel}`);
      }
      return {
        async json() {
          return JSON.parse(fs.readFileSync(abs, "utf8"));
        }
      };
    }
  };
  context.window = context;

  try {
    vm.runInNewContext(appCode, context, { filename: "app.js", timeout: 5000 });
    if (typeof context.updateAll === "function") {
      await context.updateAll();
      await Promise.resolve();
    } else {
      issues.push(issue("critical", "missing_update_all", "app.js 没有暴露 updateAll，无法执行运行时渲染"));
    }
  } catch (error) {
    issues.push(issue("critical", "runtime_exception", `${error.name}: ${error.message}`));
  }

  for (const errorText of consoleErrors) {
    if (/optional missing: data\/signal-review\.json/.test(errorText)) continue;
    if (/load failed:\s*data\/signal-review\.json/.test(errorText)) continue;
    issues.push(issue("critical", "console_error", errorText));
  }

  const renderedTargets = {};
  for (const id of REQUIRED_RENDER_TARGETS) {
    const el = document.getElementById(id);
    const html = el ? el.collectHtml().trim() : "";
    renderedTargets[id] = html.length;
    if (!el) {
      issues.push(issue("critical", "missing_runtime_target", `运行时缺少容器 #${id}`, id));
    } else if (!html) {
      issues.push(issue("critical", "empty_runtime_target", `运行后关键区块为空：#${id}`, id));
    }
  }

  const wholePage = document.body.collectHtml();
  const radarHtml = document.getElementById("opportunity-risk-radar")?.collectHtml() || "";
  const opportunityColumn = firstMatch(radarHtml, /<div class="radar-column">([\s\S]*?)<div class="radar-column">/) || radarHtml;
  const coverage = readJsonIfExists("data/monitoring-coverage.json");
  const themeShifts = readJsonIfExists("data/theme-shifts.json");
  const criticalBlindSpots = Array.isArray(coverage.blind_spots)
    ? coverage.blind_spots.filter(item => item && item.severity === "critical")
    : [];
  for (const item of criticalBlindSpots) {
    if (item.title && !radarHtml.includes(item.title)) {
      issues.push(issue("critical", "blind_spot_not_rendered", `核心监测盲区未进入雷达风险栏：${item.title}`, "opportunity-risk-radar"));
    }
  }
  if (Array.isArray(themeShifts.shifts) && themeShifts.shifts.length && !radarHtml.includes("主线变化")) {
    issues.push(issue("critical", "theme_shift_not_rendered", "主线变化报告未进入机会/风险雷达", "opportunity-risk-radar"));
  }
  const qualityHtml = document.getElementById("data-quality-gate")?.collectHtml() || "";
  if (!qualityHtml.includes("自动化心跳")) {
    issues.push(issue("critical", "automation_health_not_rendered", "自动化心跳未进入顶部质量卡", "data-quality-gate"));
  }
  checkQualityImpactRendering(qualityHtml, issues);
  if (/(?:C|D)级/.test(opportunityColumn)) {
    issues.push(issue("critical", "downgraded_opportunity_rendered", "C/D级降权机会进入了机会候选栏，应转入下一步验证", "opportunity-risk-radar"));
  }
  checkDecisionTriggerRendering(radarHtml, issues);
  checkDecisionNextActionRendering(radarHtml, issues);
  checkFallbackChecksRendering(radarHtml, coverage, issues);
  checkRadarGateRendering(document, radarHtml, issues);
  checkDashboardTrustGateRendering(document, issues);
  checkDashboardEffectiveTimeRendering(document, issues);
  checkInvalidatedAlertRendering(document, issues);
  checkActiveAlertAuditRendering(document, issues);
  checkPremarketJapanKoreaGuard(document, issues);
  for (const literal of BAD_LITERALS) {
    if (wholePage.includes(literal)) {
      issues.push(issue("critical", "bad_literal_rendered", `页面运行后出现异常文本：${badLiteralLabel(literal)}`));
    }
  }
  if (MOJIBAKE_RE.test(wholePage)) {
    issues.push(issue("critical", "mojibake_rendered", "页面运行后出现疑似乱码文本"));
  }
  const statusText = document.getElementById("status")?.textContent || "";
  if (/JS ERROR/.test(statusText)) {
    issues.push(issue("critical", "window_onerror", statusText, "status"));
  }
  const badges = document.body.querySelectorAll(".section-health-badge");
  if (!badges.length) {
    issues.push(issue("warning", "missing_section_badges", "运行时未生成区块健康贴条"));
  }
  checkDataRenderCoverage(document, issues);

  const status = issues.some(item => item.severity === "critical")
    ? "critical"
    : issues.some(item => item.severity === "warning") ? "warning" : "ok";
  const report = {
    timestamp: nowIso(),
    status,
    summary: status === "ok"
      ? "页面运行时渲染烟雾测试通过。"
      : `页面运行时发现 ${issues.length} 个问题。`,
    issues,
    rendered_targets: renderedTargets,
    checks: [
      "使用本地真实 JSON 执行 app.js 的 updateAll 渲染路径。",
      "关键决策区块运行后必须非空。",
      "拦截 console error、JS ERROR、对象直出、未定义值、非数字值和疑似乱码。",
      "critical 监测盲区必须进入机会/风险雷达的风险栏。",
      "C/D级降权机会不得进入机会候选栏，只能进入下一步验证。",
      "机会/风险雷达必须渲染 decision-feed 的触发原因。",
      "critical 盲区的 fallback_checks 必须渲染到机会/风险雷达。",
      "无 A/B 级可用机会时，机会/风险雷达必须显示无可用机会、风险优先和只做验证。",
      "文件可信度出现不可用或当前阶段超时时，今日总控必须显示具体文件状态。",
      "今日总控有效时间必须使用最新可信决策材料，不得使用 invalidated/missing/stale 文件时间。",
      "alert.json 撤下污染批次时，盘中异动区必须显示不可用和替代观察，不得只显示普通空状态。",
    "日韩早盘源降级时必须显示固定中文待复核提示和复核清单，不得展示原始乱码/未核实字符串。",
      "核心 JSON 字段有数据时，页面对应区块必须渲染关键结论或代表项。",
      "确认区块健康贴条能在运行时生成。"
    ]
  };
  writeReport(report);
  console.log(`${status}: ${report.summary}`);
  return status === "critical" ? 1 : 0;
}

main().then(code => process.exit(code)).catch(error => {
  writeReport({
    timestamp: nowIso(),
    status: "critical",
    summary: "页面运行时烟雾测试自身执行失败。",
    issues: [issue("critical", "runtime_smoke_failed", `${error.name}: ${error.message}`)]
  });
  console.error(error);
  process.exit(1);
});

function badLiteralLabel(literal) {
  return {
    "[object Object]": "对象被直接显示",
    "undefined": "未定义值被直接显示",
    "None%": "空值百分比被直接显示",
    "NaN": "非数字值被直接显示",
    "Infinity": "无限大数值被直接显示"
  }[literal] || "异常字面量";
}

function checkDataRenderCoverage(document, issues) {
  const checks = [];
  const intraday = readJsonIfExists("data/intraday.json");
  const premarket = readJsonIfExists("data/premarket.json");
  const midday = readJsonIfExists("data/midday.json");
  const postmarket = readJsonIfExists("data/postmarket.json");
  const topics = readJsonIfExists("data/topics.json");

  addCoverageCheck(checks, "section-intraday", intraday.summary, "盘中全景 summary 未渲染");
  addCoverageCheck(checks, "section-intraday", firstThemeName(intraday.main_trends), "盘中全景主线未渲染");
  addCoverageCheck(checks, "section-intraday", firstActionText(intraday.actions), "盘中全景行动建议未渲染");
  addCoverageCheck(checks, "section-intraday", firstIndexName(intraday), "盘中全景指数/港股快照未渲染");
  addCoverageCheck(checks, "section-premarket", premarket.summary, "早盘 summary 未渲染");
  addCoverageCheck(checks, "section-midday", midday.morning_review?.one_sentence, "午盘一句话复盘未渲染");
  addCoverageCheck(checks, "section-midday", firstActionText(midday.afternoon_watch), "午盘下午关注信号未渲染");
  addCoverageCheck(checks, "section-postmarket", postmarket.closing_auction_patch?.summary, "盘后收盘竞价补丁未渲染");
  addCoverageCheck(checks, "section-postmarket", firstThemeName(postmarket.hotspots), "盘后热点主线未渲染");
  addCoverageCheck(checks, "section-topics", firstThemeName(topics.topics), "专题首项未渲染");

  for (const check of checks) {
    const html = document.getElementById(check.target)?.collectHtml() || "";
    const rendered = normalizeRenderedText(html);
    if (check.snippet && !rendered.includes(check.snippet)) {
      issues.push(issue("critical", "key_data_not_rendered", check.message, check.target));
    }
  }
}

function checkDecisionTriggerRendering(radarHtml, issues) {
  const feed = readJsonIfExists("data/decision-feed.json");
  const items = [
    ...(Array.isArray(feed.opportunities) ? feed.opportunities : []),
    ...(Array.isArray(feed.risks) ? feed.risks : []),
    ...(Array.isArray(feed.verifications) ? feed.verifications : [])
  ].filter(item => item && item.trigger_reason);
  if (!items.length) return;
  const rendered = normalizeRenderedText(radarHtml);
  if (!rendered.includes("触发")) {
    issues.push(issue("critical", "trigger_reason_not_rendered", "机会/风险雷达未显示触发原因", "opportunity-risk-radar"));
    return;
  }
  const mustRender = items.slice(0, 3).map(item => stableSnippet(item.trigger_reason)).filter(Boolean);
  for (const snippet of mustRender) {
    if (!rendered.includes(snippet)) {
      issues.push(issue("critical", "trigger_reason_not_rendered", `触发原因未渲染：${snippet}`, "opportunity-risk-radar"));
    }
  }
}

function checkDecisionNextActionRendering(radarHtml, issues) {
  const feed = readJsonIfExists("data/decision-feed.json");
  const items = [
    ...(Array.isArray(feed.opportunities) ? feed.opportunities : []),
    ...(Array.isArray(feed.risks) ? feed.risks : []),
    ...(Array.isArray(feed.verifications) ? feed.verifications : [])
  ].filter(item => item && item.next_action);
  if (!items.length) return;
  const rendered = normalizeRenderedText(radarHtml);
  if (!rendered.includes("动作")) {
    issues.push(issue("critical", "next_action_not_rendered", "机会/风险雷达未显示下一步动作", "opportunity-risk-radar"));
    return;
  }
  const mustRender = items.slice(0, 3).map(item => stableSnippet(item.next_action)).filter(Boolean);
  for (const snippet of mustRender) {
    if (!rendered.includes(snippet)) {
      issues.push(issue("critical", "next_action_not_rendered", `下一步动作未渲染：${snippet}`, "opportunity-risk-radar"));
    }
  }
}

function checkFallbackChecksRendering(radarHtml, coverage, issues) {
  const blindSpots = Array.isArray(coverage.blind_spots) ? coverage.blind_spots : [];
  const rendered = normalizeRenderedText(radarHtml);
  for (const item of blindSpots) {
    if (!item || item.severity !== "critical") continue;
    const checks = Array.isArray(item.fallback_checks) ? item.fallback_checks : [];
    if (!checks.length) continue;
    const mustRender = checks.slice(0, 3).map(check => stableSnippet(check)).filter(Boolean);
    for (const snippet of mustRender) {
      if (!rendered.includes(snippet)) {
        issues.push(issue("critical", "fallback_checks_not_rendered", `核心盲区替代检查未渲染：${snippet}`, "opportunity-risk-radar"));
      }
    }
  }
}

function checkRadarGateRendering(document, radarHtml, issues) {
  const feed = readJsonIfExists("data/decision-feed.json");
  const opportunities = Array.isArray(feed.opportunities) ? feed.opportunities : [];
  if (!opportunities.length) return;
  const actionable = opportunities.filter(item => {
    const grade = String(item.signal_grade || "").toUpperCase();
    const action = String(item.use_action || "");
    const confidence = String(item.confidence || "");
    return ["A", "B"].includes(grade) && !/仅复核|降权|等待|低|low|不可|候选/.test(`${action} ${confidence}`);
  });
  if (actionable.length) return;
  const rendered = normalizeRenderedText(radarHtml);
  for (const snippet of ["无可用机会", "风险优先", "只做验证"]) {
    if (!rendered.includes(snippet)) {
      issues.push(issue("critical", "radar_gate_not_rendered", `无可用机会时雷达闸门缺少：${snippet}`, "opportunity-risk-radar"));
    }
  }
  const controlRendered = normalizeRenderedText(document.getElementById("dashboard-control")?.collectHtml() || "");
  for (const snippet of ["无可用机会", "风险优先", "只做验证"]) {
    if (!controlRendered.includes(snippet)) {
      issues.push(issue("critical", "dashboard_gate_not_rendered", `无可用机会时今日总控缺少：${snippet}`, "dashboard-control"));
    }
  }
}

function checkDashboardTrustGateRendering(document, issues) {
  const trust = readJsonIfExists("data/data-trust.json");
  const files = Array.isArray(trust.files) ? trust.files : [];
  if (!files.length) return;
  const expected = [];
  for (const file of files) {
    if (["invalidated", "missing"].includes(file.status)) {
      expected.push(`${file.label}不可用`);
    } else if (file.session_relevance === "current" && file.freshness_status === "stale") {
      expected.push(`${file.label}超时`);
    } else if (file.session_relevance === "current" && file.freshness_status === "aging") {
      expected.push(`${file.label}临近超时`);
    } else if (file.session_relevance === "current" && file.status === "degraded") {
      expected.push(`${file.label}降权`);
    }
  }
  if (!expected.length) return;
  const rendered = normalizeRenderedText(document.getElementById("dashboard-control")?.collectHtml() || "");
  for (const snippet of expected.slice(0, 4)) {
    if (!rendered.includes(snippet)) {
      issues.push(issue("critical", "dashboard_trust_gate_not_rendered", `今日总控缺少文件可信状态：${snippet}`, "dashboard-control"));
    }
  }
}

function checkDashboardEffectiveTimeRendering(document, issues) {
  const trust = readJsonIfExists("data/data-trust.json");
  const files = Array.isArray(trust.files) ? trust.files : [];
  if (!files.length) return;
  const eligible = files
    .filter(file => file && file.timestamp)
    .filter(file => !["invalidated", "missing", "stale"].includes(file.status))
    .filter(file => ["current", "background"].includes(file.session_relevance))
    .filter(file => !["blocked", "unknown", "phase_expired"].includes(file.freshness_status));
  if (!eligible.length) return;
  const latest = eligible
    .slice()
    .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))[0];
  const rendered = normalizeRenderedText(document.getElementById("dashboard-control")?.collectHtml() || "");
  const expectedTime = timestampHourMinute(latest.timestamp);
  if (expectedTime && !rendered.includes(expectedTime)) {
    issues.push(issue("critical", "dashboard_effective_time_not_latest", `今日总控未显示最新可信决策材料时间：${latest.label} ${expectedTime}`, "dashboard-control"));
  }
  const invalidated = files.find(file => file.status === "invalidated" && file.timestamp);
  const invalidatedTime = timestampHourMinute(invalidated?.timestamp);
  if (invalidatedTime && invalidatedTime !== expectedTime && rendered.includes(invalidatedTime)) {
    issues.push(issue("critical", "dashboard_effective_time_invalidated", `今日总控有效时间引用了无效文件时间：${invalidated.label} ${invalidatedTime}`, "dashboard-control"));
  }
}

function timestampHourMinute(value) {
  const parsed = new Date(value || "");
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(parsed);
}

function checkInvalidatedAlertRendering(document, issues) {
  const alert = readJsonIfExists("data/alert.json");
  const trust = readJsonIfExists("data/data-trust.json");
  const trustRow = Array.isArray(trust.files)
    ? trust.files.find(item => item.file === "data/alert.json")
    : null;
  const invalidated = alert.source_status === "invalidated" || trustRow?.status === "invalidated";
  if (!invalidated) return;
  const html = [
    document.getElementById("alerts-summary")?.collectHtml() || "",
    document.getElementById("alerts")?.collectHtml() || ""
  ].join("");
  const rendered = normalizeRenderedText(html);
  if (!rendered.includes("异动触发不可用") || !rendered.includes("污染批次已撤下")) {
    issues.push(issue("critical", "invalidated_alert_not_rendered", "盘中异动撤下污染批次时未显示不可用状态", "section-alerts"));
  }
  if (!rendered.includes("替代观察") || !rendered.includes("宽度替代")) {
    issues.push(issue("critical", "invalidated_alert_fallback_missing", "盘中异动撤下污染批次时未显示替代观察动作", "section-alerts"));
  }
  if (rendered.includes("暂无新异动") || rendered.includes("等待触发") || rendered.includes("暂无盘中异动")) {
    issues.push(issue("critical", "invalidated_alert_shown_as_empty", "盘中异动撤下污染批次时被渲染成普通空状态", "section-alerts"));
  }
}

function checkActiveAlertAuditRendering(document, issues) {
  const alert = readJsonIfExists("data/alert.json");
  const alerts = Array.isArray(alert.alerts) ? alert.alerts : [];
  if (!alerts.length || alert.source_status === "invalidated") return;
  const rendered = normalizeRenderedText(document.getElementById("alerts-summary")?.collectHtml() || "");
  if (!rendered.includes("行情审计")) {
    issues.push(issue("critical", "alert_quote_audit_not_rendered", "active alerts 未显示行情审计摘要", "alerts-summary"));
  }
  if (alert.quote_audit && !rendered.includes("交叉验证") && !rendered.includes("quote_audit")) {
    issues.push(issue("critical", "alert_quote_audit_status_missing", "active alerts 行情审计未显示交叉验证状态", "alerts-summary"));
  }
}

function checkPremarketJapanKoreaGuard(document, issues) {
  const premarket = readJsonIfExists("data/premarket.json");
  const jk = premarket.us_overnight?.japan_korea;
  if (!jk) return;
  const statusText = normalizeRenderedText(jk);
  const needsGuard = /降级|未核实|待确认|再确认|decode|failed|error/i.test(statusText) || MOJIBAKE_RE.test(statusText);
  if (!needsGuard) return;
  const html = document.getElementById("section-premarket")?.collectHtml() || "";
  const rendered = normalizeRenderedText(html);
  if (!rendered.includes("日韩早盘：待复核") || !rendered.includes("复核清单")) {
    issues.push(issue("critical", "japan_korea_guard_not_rendered", "日韩早盘数据源降级时未显示固定待复核提示和复核清单", "section-premarket"));
  }
  const rawSnippet = stableSnippet(jk);
  if (rawSnippet && rendered.includes(rawSnippet) && !rawSnippet.includes("日韩早盘")) {
    issues.push(issue("critical", "japan_korea_raw_text_rendered", `日韩早盘仍展示原始降级文本：${rawSnippet}`, "section-premarket"));
  }
}

function checkQualityImpactRendering(qualityHtml, issues) {
  const report = readJsonIfExists("data/quality-report.json");
  const counts = report.counts || {};
  const rendered = normalizeRenderedText(qualityHtml);
  const required = [
    ["blocking", "交易阻断"],
    ["price_review", "行情复核"],
    ["signal_review", "信号复核"],
    ["background_review", "背景复核"]
  ];
  for (const [key, label] of required) {
    if (Number(counts[key] || 0) > 0 && !rendered.includes(label)) {
      issues.push(issue("critical", "quality_impact_not_rendered", `数据质量卡未显示影响分层：${label}`, "data-quality-gate"));
    }
  }
  if ((Number(counts.blocking || 0) > 0 || Number(counts.price_review || 0) > 0) && !rendered.includes("交易影响")) {
    issues.push(issue("critical", "quality_impact_card_missing", "数据质量卡缺少交易影响卡片", "data-quality-gate"));
  }
}

function addCoverageCheck(checks, target, value, message) {
  const snippet = stableSnippet(value);
  if (snippet) checks.push({ target, snippet, message });
}

function stableSnippet(value) {
  const text = normalizeRenderedText(value);
  if (!text || text.length < 4) return "";
  return text.slice(0, Math.min(12, text.length));
}

function normalizeRenderedText(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, "")
    .trim();
}

function firstThemeName(value) {
  if (!Array.isArray(value) || !value.length) return "";
  const first = value.find(Boolean);
  if (!first) return "";
  return typeof first === "string" ? first : (first.name || first.sector || first.theme || first.title || "");
}

function firstActionText(value) {
  if (!Array.isArray(value) || !value.length) return "";
  const first = value.find(Boolean);
  if (!first) return "";
  return typeof first === "string" ? first : (first.text || first.action || first.note || first.name || "");
}

function firstIndexName(intraday) {
  if (Array.isArray(intraday.indices) && intraday.indices[0]) return intraday.indices[0].name || "";
  const snapshot = intraday.index?.HK_close_window_snapshot;
  if (Array.isArray(snapshot) && snapshot[0]) return snapshot[0].name || "";
  return "";
}

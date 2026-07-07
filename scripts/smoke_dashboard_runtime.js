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

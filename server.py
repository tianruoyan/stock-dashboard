#!/usr/bin/env python3
"""本地看板服务器 — 支持配置保存"""
import hashlib, json, os, re, socket, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from v2_platform.cockpit_phase import CockpitPhaseViewBuilder
from v2_platform.user_asset_views import build_user_asset_read_projection

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
PRIVATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".v2_private")
BLOGGER_ACCOUNTS_PATH = os.path.join(PRIVATE_DIR, "blogger-accounts.json")
PORTFOLIO_PATH = os.path.join(PRIVATE_DIR, "portfolio.json")
EASTMONEY_TOKEN = "D43BF722C8E33E1B5FBF8EF4C0C8ECBE"
MAX_CONFIG_BYTES = 2 * 1024 * 1024


def write_json_atomic(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def validate_blogger_payload(payload):
    rows = payload.get("accounts") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("accounts must be a list with at most 200 items")
    allowed = {"xiaohongshu", "weibo", "wechat", "douyin", "bilibili", "other"}
    normalized = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("account must be an object")
        platform = str(item.get("platform") or "").strip().lower()
        name = str(item.get("display_name") or "").strip()
        url = str(item.get("url") or "").strip()
        note = str(item.get("note") or "").strip()
        if platform not in allowed or not name or len(name) > 80 or len(note) > 500:
            raise ValueError("invalid platform, name or note")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(url) > 1000:
            raise ValueError("url must be an http(s) link")
        account_id = str(item.get("id") or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", account_id):
            digest = hashlib.sha256(f"{platform}|{url}".encode("utf-8")).hexdigest()[:16]
            account_id = f"source_{digest}"
        dedupe_key = (platform, url)
        if dedupe_key in seen:
            raise ValueError("duplicate platform and url")
        seen.add(dedupe_key)
        normalized.append({"id": account_id, "platform": platform, "display_name": name, "url": url, "note": note, "enabled": item.get("enabled") is not False})
    return {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "accounts": normalized,
        "privacy_note": "本文件只保存在本机，不进入V2公开发布。",
    }


def _number(value, field, *, minimum=0, maximum=None, allow_none=False):
    if value in (None, "") and allow_none:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f"{field} out of range")
    return result


def validate_portfolio_payload(payload):
    rows = payload.get("holdings") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("holdings must be a list with at most 200 items")
    holdings = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("holding must be an object")
        code = market_code(item.get("code")).lower()
        name = str(item.get("name") or "").strip()
        if not re.fullmatch(r"(?:sh|sz|bj)\d{6}|hk\d{4,5}|us[a-z0-9._-]{1,15}", code) or not name or len(name) > 80:
            raise ValueError("invalid holding code or name")
        if code in seen:
            raise ValueError("duplicate holding code")
        seen.add(code)
        holdings.append({
            "code": code,
            "name": name,
            "quantity": _number(item.get("quantity"), "quantity", minimum=0),
            "cost": _number(item.get("cost"), "cost", minimum=0),
        })
    risk = payload.get("risk_budget") if isinstance(payload, dict) else {}
    risk = risk if isinstance(risk, dict) else {}
    normalized_risk = {
        "max_single_position_pct": _number(risk.get("max_single_position_pct"), "max_single_position_pct", minimum=0, maximum=100, allow_none=True),
        "max_theme_pct": _number(risk.get("max_theme_pct"), "max_theme_pct", minimum=0, maximum=100, allow_none=True),
        "max_total_invested_pct": _number(risk.get("max_total_invested_pct"), "max_total_invested_pct", minimum=0, maximum=100, allow_none=True),
        "max_drawdown_pct": _number(risk.get("max_drawdown_pct"), "max_drawdown_pct", minimum=0, maximum=100, allow_none=True),
    }
    return {
        "schema_version": 1,
        "as_of": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": "V2本机组合风险设置",
        "holdings": holdings,
        "cash": _number(payload.get("cash"), "cash", minimum=0, allow_none=True),
        "risk_budget": normalized_risk,
        "trade_authorization": False,
        "privacy_note": "只保存在本机；不进入公开发布，不授权自动交易。",
    }

def market_code(raw):
    code = str(raw or "").strip()
    if not code:
        return ""
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith(("4", "8", "9")):
        return "bj" + code
    return code

def lookup_stock(query):
    q = str(query or "").strip()
    if not q:
        return {}
    params = urllib.parse.urlencode({
        "input": q,
        "type": "14",
        "token": EASTMONEY_TOKEN,
        "count": "5"
    })
    url = "https://searchapi.eastmoney.com/api/suggest/get?" + params
    with urllib.request.urlopen(url, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8", "ignore"))
    rows = payload.get("QuotationCodeTable", {}).get("Data", []) or []
    astock = next((r for r in rows if r.get("Classify") == "AStock"), rows[0] if rows else {})
    if not astock:
        return {}
    return {
        "code": market_code(astock.get("Code")),
        "name": astock.get("Name") or "",
        "tags": ["A股"],
        "source": "东方财富搜索"
    }

class DashboardServer(SimpleHTTPRequestHandler):
    def log_request(self, code="-", size="-"):
        """Keep routine local traffic off disk.

        launchd redirects stderr to a persistent file.  The default handler
        logs every successful static-file request and every health probe, which
        creates an unbounded access log without adding diagnostic value.
        Actual uncaught server exceptions still go to stderr via socketserver.
        """
        return

    def end_headers(self):
        if getattr(self.server, "server_port", None) == 8878 and not getattr(self, "_explicit_cache_control", False):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._explicit_cache_control = True
        self.end_headers()
        self.wfile.write(body)

    def send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self._explicit_cache_control = True
        self.end_headers()

    def do_POST(self):
        if self.path == "/_v2-user-assets":
            self.send_json(405, {"状态": "只读", "提示": "当前阶段不开放用户资产页面写入。"})
            return
        if self.path in {"/_save-config", "/_v2-blogger-accounts", "/_v2-portfolio"}:
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self.send_json(400, {"error": "invalid content length"})
                return
            if length <= 0 or length > MAX_CONFIG_BYTES:
                self.send_json(413, {"error": "config payload is empty or too large"})
                return
            try:
                data = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, socket.timeout):
                self.send_json(400, {"error": "invalid or incomplete JSON"})
                return
            if self.path == "/_v2-blogger-accounts":
                try:
                    normalized = validate_blogger_payload(data)
                    write_json_atomic(BLOGGER_ACCOUNTS_PATH, normalized)
                except ValueError as exc:
                    self.send_json(400, {"error": str(exc)})
                    return
                self.send_json(200, {"saved": True, "account_count": len(normalized["accounts"]), "payload": normalized})
                return
            if self.path == "/_v2-portfolio":
                try:
                    normalized = validate_portfolio_payload(data)
                    write_json_atomic(PORTFOLIO_PATH, normalized)
                except ValueError as exc:
                    self.send_json(400, {"error": str(exc)})
                    return
                self.send_json(200, {"saved": True, "holding_count": len(normalized["holdings"]), "payload": normalized})
                return
            results = []
            # watchlist
            if "watchlist" in data:
                p = os.path.join(CONFIG_DIR, "watchlist.json")
                write_json_atomic(p, data["watchlist"])
                results.append("watchlist.json")
            # alerts
            if "alerts" in data:
                p = os.path.join(CONFIG_DIR, "alert-config.json")
                write_json_atomic(p, data["alerts"])
                results.append("alert-config.json")
            # topics
            if "topics" in data:
                p = os.path.join(CONFIG_DIR, "topics-list.json")
                write_json_atomic(p, {"topics": data["topics"]})
                results.append("topics-list.json")
            self.send_json(200, {"saved": results})
        else:
            self.send_json(404, {"error": "not found"})

    def do_GET(self):
        requested_path = urllib.parse.urlparse(self.path).path
        if getattr(self.server, "server_port", None) == 8878 and requested_path in {"/", "/index.html"}:
            self.send_redirect("/v2.html")
            return
        if self.path == "/_health":
            port = getattr(self.server, "server_port", None)
            self.send_json(200, {
                "status": "ok",
                "service": "stock-dashboard-v2" if port == 8878 else "stock-dashboard-v1",
                "entry": "/v2.html" if port == 8878 else "/index.html",
            })
            return
        if self.path == "/_v2-blogger-accounts":
            try:
                with open(BLOGGER_ACCOUNTS_PATH, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (FileNotFoundError, json.JSONDecodeError):
                payload = {"schema_version": 1, "accounts": [], "privacy_note": "本文件只保存在本机，不进入V2公开发布。"}
            self.send_json(200, payload)
            return
        if self.path == "/_v2-portfolio":
            try:
                with open(PORTFOLIO_PATH, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (FileNotFoundError, json.JSONDecodeError):
                payload = {"schema_version": 1, "holdings": [], "cash": None, "risk_budget": {}, "trade_authorization": False, "privacy_note": "只保存在本机；不进入公开发布，不授权自动交易。"}
            self.send_json(200, payload)
            return
        if self.path == "/_v2-user-assets":
            self.send_json(200, build_user_asset_read_projection(Path(os.path.dirname(os.path.abspath(__file__)))))
            return
        if self.path.startswith("/_v2-cockpit-phase"):
            try:
                root = Path(os.path.dirname(os.path.abspath(__file__)))
                self.send_json(200, CockpitPhaseViewBuilder(root).build())
            except Exception:
                self.send_json(503, {"状态": "等待更新", "提示": "交易阶段结果暂时没有生成成功，请稍后刷新。"})
            return
        if self.path.startswith("/_stock-lookup"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
            try:
                result = lookup_stock(query)
                self.send_json(200, result)
            except Exception as e:
                self.send_json(200, {"error": str(e)})
            return
        super().do_GET()


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(15)
        return request, client_address

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8877
    server = DashboardHTTPServer(("127.0.0.1", port), DashboardServer)
    print(f"Dashboard server on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

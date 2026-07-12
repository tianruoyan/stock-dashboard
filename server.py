#!/usr/bin/env python3
"""本地看板服务器 — 支持配置保存"""
import hashlib, json, os, re, socket, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
PRIVATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".v2_private")
BLOGGER_ACCOUNTS_PATH = os.path.join(PRIVATE_DIR, "blogger-accounts.json")
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

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path in {"/_save-config", "/_v2-blogger-accounts"}:
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
        if self.path == "/_health":
            self.send_json(200, {"status": "ok", "service": "stock-dashboard-local"})
            return
        if self.path == "/_v2-blogger-accounts":
            try:
                with open(BLOGGER_ACCOUNTS_PATH, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (FileNotFoundError, json.JSONDecodeError):
                payload = {"schema_version": 1, "accounts": [], "privacy_note": "本文件只保存在本机，不进入V2公开发布。"}
            self.send_json(200, payload)
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

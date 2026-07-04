#!/usr/bin/env python3
"""本地看板服务器 — 支持配置保存"""
import json, os, sys, urllib.parse, urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
EASTMONEY_TOKEN = "D43BF722C8E33E1B5FBF8EF4C0C8ECBE"

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
    def do_POST(self):
        if self.path == "/_save-config":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            results = []
            # watchlist
            if "watchlist" in data:
                p = os.path.join(CONFIG_DIR, "watchlist.json")
                with open(p, "w") as f:
                    json.dump(data["watchlist"], f, ensure_ascii=False, indent=2)
                results.append("watchlist.json")
            # alerts
            if "alerts" in data:
                p = os.path.join(CONFIG_DIR, "alert-config.json")
                with open(p, "w") as f:
                    json.dump(data["alerts"], f, ensure_ascii=False, indent=2)
                results.append("alert-config.json")
            # topics
            if "topics" in data:
                p = os.path.join(CONFIG_DIR, "topics-list.json")
                with open(p, "w") as f:
                    json.dump({"topics": data["topics"]}, f, ensure_ascii=False, indent=2)
                results.append("topics-list.json")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"saved": results}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path.startswith("/_stock-lookup"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
            try:
                result = lookup_stock(query)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return
        super().do_GET()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8877
    server = HTTPServer(("127.0.0.1", port), DashboardServer)
    print(f"Dashboard server on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

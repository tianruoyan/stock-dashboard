#!/usr/bin/env python3
"""本地看板服务器 — 支持配置保存"""
import json, os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")

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
        super().do_GET()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8877
    server = HTTPServer(("127.0.0.1", port), DashboardServer)
    print(f"Dashboard server on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

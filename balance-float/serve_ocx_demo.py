# -*- coding: utf-8 -*-
"""
OCX 指标本地预览服务（当前目录 index.html + 后端接口）。

用法:
  python serve_ocx_demo.py
  浏览器打开: http://127.0.0.1:8799/

接口:
  GET  /api/ocx/metrics          今日合计 + 30s 输出速度曲线
  GET  /api/ocx/metrics/config   当前配置
  POST /api/ocx/metrics/config   {"interval_seconds":3,"window_seconds":30,"enabled":true}
                                 —— demo 服务本机免 token；悬浮窗同路径需 X-Api-Token
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ocx_metrics  # noqa: E402

PORT = 8799


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            fp = os.path.join(HERE, "index.html")
            with open(fp, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/ocx/metrics":
            return self._json(ocx_metrics.metrics.snapshot())
        if path == "/api/ocx/metrics/config":
            return self._json({"ok": True, "config": ocx_metrics.metrics.config()})
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = {}
        if n > 0:
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception as e:
                return self._json({"ok": False, "error": "bad json: %s" % e}, 400)
        if path == "/api/ocx/metrics/config":
            ok, info = ocx_metrics.metrics.set_config(
                interval=body.get("interval_seconds", body.get("interval")),
                window=body.get("window_seconds", body.get("window")),
                enabled=body.get("enabled"),
            )
            return self._json({"ok": ok, "config": info if ok else None,
                               "error": None if ok else info})
        self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass


def main():
    ocx_metrics.metrics.start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("OCX 指标 demo: http://127.0.0.1:%d/" % PORT)
    print("API: http://127.0.0.1:%d/api/ocx/metrics" % PORT)
    print("账本:", ocx_metrics.metrics.usage_path)
    print("Ctrl+C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()

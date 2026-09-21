
# -*- coding: utf-8 -*-
"""用无头 Chrome 连真实页面截 UI 图, 供 README 使用。数据一律为演示假数据。"""
import base64, json, os, shutil, socket, subprocess, sys, tempfile, threading, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BF = HERE          # 本脚本就在 balance-float/ 下运行
sys.path.insert(0, BF)
import float_window as fw
os.chdir(BF)   # 必须在 import 之后: pywebview 用 argv[0] 的相对路径定根目录

OUT = os.path.join(BF, "docs")
os.makedirs(OUT, exist_ok=True)

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

DEMO_STATE = {
    "loading": False, "updated": "21:40:12",
    "settings": {"refresh_seconds": 60, "timeout": 15},
    "stations": [
        {"id": "d1", "name": "DeepSeek", "ok": True, "remaining": 94.20, "used": 31.80,
         "total": 126.0, "unit": "CNY", "plan": "官方直连", "latency_ms": 18, "updated": "21:40:05"},
        {"id": "d2", "name": "河图中转", "ok": True, "remaining": 4.33, "used": 95.67,
         "total": 100.0, "unit": "CNY(估)", "estimated": True, "latency_ms": 92, "updated": "21:40:06",
         "traffic": {"cost_usd": 12.48, "tokens": 3860000, "requests": 612}},
        {"id": "d3", "name": "Kimi", "ok": True, "remaining": 42.50, "used": 7.50,
         "total": 50.0, "unit": "CNY", "plan": "官方直连", "latency_ms": 24, "updated": "21:40:04"},
        {"id": "d4", "name": "OpenRouter", "ok": True, "remaining": 18.75, "used": 21.25,
         "total": 40.0, "unit": "USD", "plan": "OpenRouter", "latency_ms": 210, "updated": "21:40:03"}
    ],
    "accounts": [
        {"id": "d1", "name": "DeepSeek", "type": "deepseek", "enabled": True},
        {"id": "d2", "name": "河图中转", "type": "newapi", "enabled": True},
        {"id": "d3", "name": "Kimi", "type": "moonshot", "enabled": True},
        {"id": "d4", "name": "OpenRouter", "type": "generic", "enabled": True}
    ],
    "traffic": {"available": True, "cost_usd": 12.48, "requests": 612, "tokens": 3860000,
                "by_name": {"河图中转": {"cost_usd": 12.48, "tokens": 3860000, "requests": 612}}}
}

DEMO_ACCOUNTS = [
    {"id": "d1", "name": "DeepSeek", "type": "deepseek", "api_key": "\u2022\u2022\u2022\u2022abcd", "enabled": True},
    {"id": "d2", "name": "河图中转", "type": "newapi", "base_url": "https://api.example.com",
     "access_token": "\u2022\u2022\u2022\u2022wxyz", "user_id": "2601", "divisor": 500000, "unit": "CNY", "enabled": True},
    {"id": "d3", "name": "Kimi", "type": "moonshot", "api_key": "\u2022\u2022\u2022\u2022kimi", "enabled": True},
    {"id": "d4", "name": "OpenRouter", "type": "generic", "url": "https://openrouter.ai/api/v1/credits", "enabled": True}
]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start_backend():
    cfg = tempfile.mkdtemp(prefix="bf_shot_")
    fw.CONFIG_DIR = cfg
    fw.DIST = os.path.join(BF, "ui")
    port = free_port()
    fw._PORT = port
    srv = fw.ThreadingHTTPServer(("127.0.0.1", port), fw.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


STUB_JS = """
(function () {
  var S = %s, A = %s, OM = %s;
  function mk(body) {
    return Promise.resolve(new Response(JSON.stringify(body),
      { status: 200, headers: { "Content-Type": "application/json" } }));
  }
  var real = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var url = String(typeof input === "string" ? input : (input && input.url) || "");
    if (url.indexOf("/api/state") >= 0) return mk(S);
    if (url.indexOf("/api/accounts") >= 0) return mk(A);
    if (url.indexOf("/api/official/models") >= 0) return mk(OM);
    if (url.indexOf("/api/ccsw/hidden") >= 0) return mk({ hidden: [] });
    if (url.indexOf("/api/generic/presets") >= 0) return mk([]);
    return real(input, init);
  };
})();
"""


def cdp_ws(port, target_url):
    for _ in range(60):
        try:
            raw = urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=1).read()
            for t in json.loads(raw):
                if t.get("type") == "page":
                    return t["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.3)
    raise SystemExit("找不到调试目标")


class CDP:
    def __init__(self, url):
        import websocket
        self.ws = websocket.create_connection(url, timeout=30)
        self.i = 0

    def call(self, method, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise SystemExit("%s -> %s" % (method, msg["error"]))
                return msg.get("result", {})

    def eval(self, expr):
        return self.call("Runtime.evaluate", expression=expr, returnByValue=True)


def shoot(cdp, name, expand):
    cdp.eval("document.getElementById('previewbg').style.display='none';"
             "document.body.style.overflow='visible';document.body.style.background='#f6f8fa';"
             "document.getElementById('stageouter').style.padding='20px';")
    cdp.eval("window.BalanceFloat.setExpanded(%s);" % ("true" if expand else "false"))
    time.sleep(1.2)
    rect = cdp.eval(
        "(function(){var w=document.getElementById(%s);var el=w.querySelector('.ios-glass-card')||w;"
        "var r=el.getBoundingClientRect();return JSON.stringify({x:r.left,y:r.top,w:r.width,h:r.height});})()"
        % ("'expandedWrap'" if expand else "'collapsedWrap'"))["result"]["value"]
    r = json.loads(rect)
    m = 26
    clip = {"x": max(0, r["x"] - m), "y": max(0, r["y"] - m),
            "width": r["w"] + m * 2, "height": r["h"] + m * 2, "scale": 1}
    res = cdp.call("Page.captureScreenshot", format="png", clip=clip, captureBeyondViewport=True)
    fp = os.path.join(OUT, name)
    with open(fp, "wb") as f:
        f.write(base64.b64decode(res["data"]))
    print("saved", fp, os.path.getsize(fp), "bytes", "card", r)


def main():
    srv, port = start_backend()
    models = json.load(open(os.path.join(BF, "configs", "official", "models.json"), encoding="utf-8"))
    stub = STUB_JS % (json.dumps(DEMO_STATE, ensure_ascii=False),
                      json.dumps(DEMO_ACCOUNTS, ensure_ascii=False),
                      json.dumps(models, ensure_ascii=False))
    s3 = dict(DEMO_STATE)
    s3["stations"] = DEMO_STATE["stations"][:3]
    s3["accounts"] = DEMO_STATE["accounts"][:3]
    s3["traffic"] = {"available": True, "cost_usd": 12.48, "requests": 612, "tokens": 3860000,
                     "by_name": {"河图中转": {"cost_usd": 12.48, "tokens": 3860000, "requests": 612}}}
    stub3 = STUB_JS % (json.dumps(s3, ensure_ascii=False),
                       json.dumps(DEMO_ACCOUNTS[:3], ensure_ascii=False),
                       json.dumps(models, ensure_ascii=False))
    user_dir = tempfile.mkdtemp(prefix="bf_chrome_")
    dbg = free_port()
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             "--no-first-run", "--no-default-browser-check",
                             "--remote-debugging-port=%d" % dbg,
                             "--remote-allow-origins=*",
                             "--user-data-dir=" + user_dir, "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = cdp_ws(dbg, None)
        cdp = CDP(ws)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", width=620, height=520,
                 deviceScaleFactor=2, mobile=False)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", source=stub)
        cdp.call("Page.navigate", url="http://127.0.0.1:%d/?rt=1" % port)
        time.sleep(3.0)
        shoot(cdp, "screenshot-collapsed.png", False)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", source=stub3)
        cdp.call("Page.navigate", url="http://127.0.0.1:%d/?rt=1" % port)
        time.sleep(3.0)
        shoot(cdp, "screenshot-expanded.png", True)
    finally:
        proc.terminate()
        srv.shutdown(); srv.server_close()
        shutil.rmtree(user_dir, ignore_errors=True)
    print("done")


if __name__ == "__main__":
    main()

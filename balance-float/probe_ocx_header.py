# -*- coding: utf-8 -*-
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:10100"
KEY = os.environ.get("OCX_API_KEY", "")
H = {
    "x-opencodex-api-key": KEY,
    "Accept": "application/json",
    "User-Agent": "balance-float/ocx",
}


def call(path, extra=None):
    headers = dict(H)
    if extra:
        headers.update(extra)
    req = urllib.request.Request(BASE + path, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t0 = time.perf_counter()
    try:
        with opener.open(req, timeout=8) as r:
            body = r.read()
            ms = int((time.perf_counter() - t0) * 1000)
            data = json.loads(body.decode("utf-8"))
            return True, getattr(r, "status", 200), ms, data
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:
            data = raw[:400]
        return False, e.code, None, data
    except Exception as e:
        return False, None, None, str(e)


def main():
    if not KEY:
        print("请先设置环境变量 OCX_API_KEY（OCX 用量接口的 x-opencodex-api-key）")
        return
    paths = [
        "/v1/usage",
        "/v1/usage?range=1d",
        "/v1/usage?range=1d&surface=all",
        "/v1/usage?range=7d",
        "/v1/usage?range=30d",
        "/v1/usage?range=1d&surface=chat",
        "/v1/usage?range=1d&surface=responses",
        "/v1/catalog",
        "/v1/hub-state",
        "/v1/models",
    ]
    print("header x-opencodex-api-key =", (KEY[:12] + "...") if KEY else "(未设置)")
    for p in paths:
        ok, st, ms, data = call(p)
        print("\n===", p, "ok" if ok else st, "ms", ms)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2500] if ok else data)


if __name__ == "__main__":
    main()

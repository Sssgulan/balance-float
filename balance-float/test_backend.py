# -*- coding: utf-8 -*-
"""后端自检：安全 / 线程 / 导入 三处非平凡逻辑的唯一可运行检查。

用法: python -X utf8 test_backend.py
只用 assert，无框架；临时目录里跑，不碰真实 configs/
"""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ocx_metrics
import providers
import float_window as fw

SECRET = "SECRET-TOKEN-MUST-NOT-LEAK"


def test_dig_cand():
    # path 未配置（None/空）不能抛异常，调用方全靠 path 可空
    assert providers._dig_cand({"a": 1}, None) is None
    assert providers._dig_cand({"a": 1}, "") is None
    assert providers._dig_cand({"a": {"b": 2}}, "a.b") == 2
    assert providers._dig_cand({"a": {"b": 2}}, ["x.y", "a.b"]) == 2
    assert providers._dig_cand({}, ["x.y", "a"]) is None


def test_import_checked_rejects_unknown(tmp):
    # 只认 /api/ocx/scan 报过的候选路径，否则这个接口就是任意文件读取器
    known = fw._checked_config_paths()
    assert known, "默认候选路径不应为空"
    r = fw.ocx_import_checked(os.path.join(tmp, "secret.json"))
    assert r["ok"] is False, r
    assert "候选" in r["error"], r
    assert r["checked"] == known


def test_load_config_merge(tmp):
    # 合并加载：settings.json 提供全局项，其余 *.json 的 accounts 全部并入，order 不丢
    fw.CONFIG_DIR = tmp
    os.makedirs(os.path.join(tmp, "official"), exist_ok=True)
    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"refresh_seconds": 60, "timeout": 20, "order": ["a"]}, f)
    with open(os.path.join(tmp, "newapi.json"), "w", encoding="utf-8") as f:
        json.dump({"accounts": [{"id": "a", "name": "N", "type": "newapi",
                                 "base_url": "https://x", "access_token": "t"}]}, f)
    with open(os.path.join(tmp, "official", "deepseek.json"), "w", encoding="utf-8") as f:
        json.dump({"accounts": [{"id": "b", "name": "D", "type": "deepseek",
                                 "api_key": "k"}]}, f)
    cfg = fw.load_config()
    assert cfg["refresh_seconds"] == 60 and cfg["timeout"] == 20 and cfg["order"] == ["a"], cfg
    assert sorted(a["id"] for a in cfg["accounts"]) == ["a", "b"], cfg
    ok, msgs = fw._check(cfg)
    assert ok, msgs
    # 缺必填字段 / 未知类型必须被 --check 拦下
    assert fw._check({"accounts": [{"name": "X", "type": "newapi"}]})[0] is False
    assert fw._check({"accounts": [{"name": "X", "type": "nope"}]})[0] is False
    assert fw._check({"refresh_seconds": 0, "accounts": []})[0] is False


def test_cred_mask_roundtrip(tmp):
    # 掩码或空凭据 = 用户没改，落盘必须沿用库里原值；填了新值才覆盖
    fw.CONFIG_DIR = tmp
    base = {"id": "a1", "name": "N", "type": "newapi", "base_url": "https://x"}
    fw.write_accounts("newapi.json", [dict(base, access_token="real-token-1234")])
    assert fw.save_account(dict(base, access_token=fw._MASK_PREFIX + "1234"))["ok"]
    assert fw.read_accounts("newapi.json")[0]["access_token"] == "real-token-1234"
    assert fw.save_account(dict(base, access_token=""))["ok"]
    assert fw.read_accounts("newapi.json")[0]["access_token"] == "real-token-1234"
    assert fw.save_account(dict(base, access_token="new-token-9999"))["ok"]
    assert fw.read_accounts("newapi.json")[0]["access_token"] == "new-token-9999"
    # 出参掩码不携带明文
    assert fw._mask_creds({"access_token": "real-token-1234"})["access_token"] == fw._MASK_PREFIX + "1234"
    # 缺必填的账户不落盘
    assert fw.save_account({"name": "N", "type": "newapi"})["ok"] is False


def test_static_path_guard(tmp):
    # 静态分支: 跨目录读取（../configs/newapi.json）必须回落到 index.html，不能把凭据交出去
    fw.CONFIG_DIR = tmp
    ui = os.path.join(tmp, "ui")
    os.makedirs(ui, exist_ok=True)
    with open(os.path.join(ui, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><html><head></head><body>UI</body></html>")
    with open(os.path.join(tmp, "secret.json"), "w", encoding="utf-8") as f:
        json.dump({"access_token": SECRET}, f)
    fw.DIST = ui
    fw._API_TOKEN = "tok-for-test"

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    fw._PORT = port
    srv = fw.ThreadingHTTPServer(("127.0.0.1", port), fw.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for p in ("/../secret.json", "/%2e%2e/secret.json", "/..%2fsecret.json",
                  "/../../configs/newapi.json", "/../secret.json?x=1"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", p)
            r = c.getresponse()
            body = r.read()
            c.close()
            assert SECRET.encode() not in body, "路径穿越泄漏: %s" % p
            assert b"UI" in body, "未回落到 index.html: %s" % p
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        assert r.status == 200 and b'name="api-token"' in r.read()
        c.close()
        # 写操作无令牌一律 403
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/api/settings", json.dumps({"timeout": 5}),
                  {"Content-Type": "application/json"})
        assert c.getresponse().status == 403
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_metrics_thread(tmp):
    # 改轮询参数不能把采样线程停死（曾用同一个 Event 既当唤醒又当停止）
    usage = os.path.join(tmp, "usage.jsonl")
    with open(usage, "w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": int(time.time()), "status": 200,
                            "usage": {"inputTokens": 10, "outputTokens": 5}}) + "\n")
    m = ocx_metrics.OcxMetrics(usage_path=usage)
    m.set_config(interval=1.0, window=20.0)
    m.start()
    time.sleep(0.4)
    n0 = m.snapshot()["poll_count"]
    m.set_config(interval=1.0)
    time.sleep(1.8)
    assert m._thread.is_alive(), "set_config 后采样线程已退出"
    assert m.snapshot()["poll_count"] > n0, "set_config 后不再采样"
    m.set_config(enabled=False)
    time.sleep(0.3)
    off = m.snapshot()["poll_count"]
    time.sleep(1.5)
    assert m.snapshot()["poll_count"] == off, "enabled=false 仍在采样"
    m.set_config(enabled=True)
    time.sleep(1.5)
    assert m.snapshot()["poll_count"] > off, "enabled=true 后未恢复采样"
    m.stop()
    m._thread.join(2.0)
    assert not m._thread.is_alive(), "stop 后线程未退出"


def test_delete_blacklist(tmp):
    # 删除即拉黑：删掉的 CC-SW/OCX 节点不能被「导入刷新」复活，也不再进展开页
    work = os.path.join(tmp, "blacklist")
    os.makedirs(work, exist_ok=True)
    fw.CONFIG_DIR = work
    with open(os.path.join(work, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"refresh_seconds": 60, "timeout": 20}, f)
    fw.write_accounts("ccsw.json", [
        {"id": "z1", "name": "A", "type": "ccsw", "provider_id": "ccapi-1", "base_url": "https://a", "enabled": True},
        {"id": "z2", "name": "B", "type": "ccsw", "provider_id": "ccapi-2", "base_url": "https://b", "enabled": True},
    ])
    fw.write_accounts("ocx.json", [{"id": "z9", "name": "OCX", "type": "ocx", "base_url": "http://127.0.0.1:10100"}])

    assert fw.delete_account("z1")["ok"]
    assert fw.read_settings().get("ccsw_ignored") == ["ccapi-1"]
    assert [a["id"] for a in fw.load_config()["accounts"]] == ["z2", "z9"], "已删除的行仍在展开页"

    def fake_scan(pids):
        ns = [{"provider_id": p, "name": p, "base_url": "https://" + p, "app_type": "claude",
               "importable": True, "is_local": False, "suggest": {"balance_kind": "none"}} for p in pids]
        return {"available": True, "nodes": ns, "all_nodes": ns, "importable_count": len(ns), "count": len(ns)}

    real_scan = fw.ccsw_scan
    fw.ccsw_scan = lambda include_local=False: fake_scan(["ccapi-1", "ccapi-2"])
    try:
        r = fw.ccsw_import()
        assert r["skipped"] == 1, r
        assert [a["id"] for a in fw.read_accounts("ccsw.json")] == ["z2"], "导入刷新把已删除的节点又拉回来了"
        assert fw.ccsw_import()["skipped"] == 1, "第二次导入又出现重复行"
        # 点名导入 = 撤销拉黑
        assert fw.ccsw_import(provider_ids=["ccapi-1"])["imported"] == 1
        assert fw.read_settings().get("ccsw_ignored") == []
    finally:
        fw.ccsw_scan = real_scan

    # OCX：删掉同一个上游地址后，再导入不能复活
    assert fw.delete_account("z9")["ok"]
    assert fw._ocx_save_node("http://127.0.0.1:10100", 5)["action"] == "ignored"
    assert fw.read_accounts("ocx.json") == [], "已删除的 OCX 节点被复活"


def test_delete_concurrent(tmp):
    # 接入页批量删除原本并发发多条 POST, 每条各自 read→pop→write, 落盘互相覆盖:
    # 都回 ok 却只删掉一条, 拉黑名单也会丢项。这里并发删 3 条, 必须三条全中。
    work = os.path.join(tmp, "concurrent")
    os.makedirs(work, exist_ok=True)
    fw.CONFIG_DIR = work
    fw.write_accounts("ccsw.json", [
        {"id": "z%d" % i, "name": "A%d" % i, "type": "ccsw",
         "provider_id": "p%d" % i, "base_url": "https://x%d" % i} for i in range(1, 6)])
    errs = []

    def d(i):
        try:
            fw.delete_account("z%d" % i)
        except Exception as e:   # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=d, args=(i,)) for i in (1, 2, 3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    left = sorted(a["id"] for a in fw.read_accounts("ccsw.json"))
    assert left == ["z4", "z5"], "并发删除互相覆盖, 没删干净: %s" % left
    assert sorted(fw.ignored_sets()["ccsw"]) == ["p1", "p2", "p3"], "拉黑名单丢项"
    # 批量接口: 一个请求删完剩下一批
    assert fw.delete_accounts(["z4", "z5"])["ok"]
    assert fw.read_accounts("ccsw.json") == []
    assert fw.load_config()["accounts"] == [], "已删除的行仍在展开页"


def test_corrupt_recovery(tmp):
    # 真实 configs/ccsw.json 被 OneDrive 补过尾块: 一个完整 JSON 后面又跟了一段旧内容。
    # 原来 json.load 报 Extra data, 整表读不出来, 删账户也跟着失败; 现在取第一个完整对象即可。
    work = os.path.join(tmp, "corrupt")
    os.makedirs(work, exist_ok=True)
    fw.CONFIG_DIR = work
    fp = os.path.join(work, "ccsw.json")
    with open(fp, "w", encoding="utf-8") as f:
        f.write('{"accounts": [{"id": "c1", "name": "C", "type": "ccsw", '
                '"provider_id": "pc1", "base_url": "https://c"}]}"generic"\n    }\n  ]\n}')
    assert [a["id"] for a in fw.read_accounts("ccsw.json")] == ["c1"], "尾部残块让整表读不出来"
    assert fw.delete_account("c1")["ok"], "账单文件被补过尾块就删不动了"
    assert fw.read_accounts("ccsw.json") == []
    with open(fp, encoding="utf-8") as f:
        assert json.load(f) == {"accounts": []}   # 写回后就是干净文件


def main():
    tmp = tempfile.mkdtemp(prefix="bf_test_")
    try:
        test_dig_cand()
        test_import_checked_rejects_unknown(tmp)
        test_load_config_merge(tmp)
        test_cred_mask_roundtrip(tmp)
        test_static_path_guard(tmp)
        test_metrics_thread(tmp)
        test_delete_blacklist(tmp)
        test_delete_concurrent(tmp)
        test_corrupt_recovery(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_backend OK")


if __name__ == "__main__":
    main()

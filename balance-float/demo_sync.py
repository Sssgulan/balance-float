# -*- coding: utf-8 -*-
"""
OCX / CC-SW 配置同步 demo（不要求 OCX 代理在线，也不依赖远程余额接口成功）

用法（在 balance-float 目录）:
  python demo_sync.py
  或  "D:\\Program Files\\Anaconda\\python.exe" -X utf8 demo_sync.py

会做四件事并打印结果:
  1. 扫描 OpenCodex/OCX 配置并导入 configs/ocx.json
  2. 扫描 CC Switch providers 并导入 configs/ccsw.json（远程中转站）
  3. 把 OCX 与 CC-SW 按 host:port 做配置匹配（linked_provider_id）
  4. 读 cc-switch.db 今日流量，把 _codex_session 归并到当前 provider，打印每行匹配结果

可选: python demo_sync.py --refresh   额外跑一轮 providers.fetch（会访问远程站）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import float_window as fw  # noqa: E402


def show(title, obj):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main():
    probe = "--probe" in sys.argv
    do_refresh = "--refresh" in sys.argv

    print("balance-float OCX / CC-SW 同步 demo")
    print("工作目录:", HERE)
    print("probe=%s (默认不探测代理) / refresh=%s" % (probe, do_refresh))

    snap = fw.sync_ocx_ccsw(probe=probe)

    show("1. OCX 扫描", snap["ocx_scan"])
    show("2. OCX 导入", snap["ocx_import"])
    show("3. CC-SW 扫描（含本机节点清单）", {
        "available": snap["ccsw_scan"].get("available"),
        "remote_count": snap["ccsw_scan"].get("remote_count"),
        "count": snap["ccsw_scan"].get("count"),
        "nodes": snap["ccsw_scan"].get("nodes"),
        "local_nodes": snap["ccsw_scan"].get("local_nodes"),
    })
    show("4. CC-SW 导入", snap["ccsw_import"])

    print("\n" + "=" * 60)
    print("5. 合并后账户 + 行级流量匹配")
    print("=" * 60)
    print("%-16s %-8s %-42s %s" % ("名称", "类型", "provider/base", "今日流量"))
    print("-" * 100)
    for row in snap["accounts"]:
        t = row.get("traffic")
        if t:
            tr = "req=%s tok=%s $%.4f" % (
                t.get("requests"), t.get("tokens"), float(t.get("cost_usd") or 0))
        else:
            tr = "(无匹配)"
        label = row.get("provider_id") or row.get("base_url") or ""
        print("%-16s %-8s %-42s %s" % (row.get("name") or "", row.get("type") or "",
                                        str(label)[:42], tr))

    show("6. CC Switch 当前 provider（流量归并目标）", snap["current"])
    show("7. 今日流量快照", {
        "available": (snap["traffic"] or {}).get("available"),
        "requests": (snap["traffic"] or {}).get("requests"),
        "tokens": (snap["traffic"] or {}).get("tokens"),
        "cost_usd": (snap["traffic"] or {}).get("cost_usd"),
        "providers": (snap["traffic"] or {}).get("providers"),
        "by_name": (snap["traffic"] or {}).get("by_name"),
        "by_host": (snap["traffic"] or {}).get("by_host"),
        "session": (snap["traffic"] or {}).get("session"),
        "message": (snap["traffic"] or {}).get("message"),
    })

    if do_refresh:
        print("\n" + "=" * 60)
        print("8. 执行一轮 refresh（远程站失败不影响本地流量同步）")
        print("=" * 60)
        try:
            interval = fw._refresh_round()
            print("refresh_seconds =", interval)
        except Exception as e:
            print("refresh 异常:", type(e).__name__, e)
        show("state.stations", fw.state.get("stations"))
        show("state.traffic", fw.state.get("traffic"))
        show("state.accounts", fw.state.get("accounts"))

    # 落盘结果提示
    print("\n配置文件:")
    for rel in ("configs/ocx.json", "configs/ccsw.json", "configs/settings.json"):
        p = os.path.join(HERE, rel)
        print(" -", rel, "存在" if os.path.isfile(p) else "缺失", os.path.getsize(p) if os.path.isfile(p) else 0, "bytes")
    print("\n完整浮窗: 双击 启动悬浮窗.vbs")
    print("HTTP 同步接口: GET/POST http://127.0.0.1:8765/api/ocx/ccsw_sync")


if __name__ == "__main__":
    main()

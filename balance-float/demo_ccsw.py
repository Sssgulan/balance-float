# -*- coding: utf-8 -*-
"""
CC-SW 功能 demo：加载参数 → 标注有用/无用 → 选择性导入 → 确认启用 → 看流量匹配。

用法（balance-float 目录）:
  python demo_ccsw.py                  # 只 review，不改配置
  python demo_ccsw.py --import         # 导入全部可导入节点（默认 features=traffic）
  python demo_ccsw.py --import --ids ccapi-1789377424476,TKEN
  python demo_ccsw.py --enable-all     # 打开全部已导入节点
  python demo_ccsw.py --balance NAME   # 给某节点开余额查询（features=traffic,balance）
  python demo_ccsw.py --disable NAME   # 关闭某节点
  python demo_ccsw.py --fetch          # 跑一轮 refresh（ccsw 余额用时从 CC Switch 只读凭据）
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


def find_ccsw(label):
    accs = fw.read_accounts(fw.account_file_for("ccsw"))
    for a in accs:
        if a.get("name") == label or a.get("id") == label or a.get("provider_id") == label:
            return a
    return None


def print_review_table(review):
    scan = review.get("scan") or {}
    print("\n%-22s %-8s %-10s %-8s %-10s %-8s %s" % (
        "名称", "app", "可导入", "已导入", "enabled", "余额", "建议/说明"))
    print("-" * 110)
    for n in scan.get("all_nodes") or []:
        sug = n.get("suggest") or {}
        print("%-22s %-8s %-10s %-8s %-10s %-8s %s" % (
            (n.get("name") or "")[:20],
            n.get("app_type") or "",
            "Y" if n.get("importable") else ("local" if n.get("is_local") else "N"),
            "Y" if n.get("imported") else "n",
            n.get("enabled"),
            (n.get("suggest") or {}).get("balance_kind") or "none",
            sug.get("note") or "",
        ))
    print("\n有用参数(落盘): provider_id/name/base_url/app_type/enabled/features[/balance_kind]")
    print("无用参数(不落盘):", ", ".join(fw._CCSW_SCAN_ONLY))
    print("已导入账户: enabled=%s disabled=%s" % (
        review.get("enabled_count"), review.get("disabled_count")))


def main():
    args = sys.argv[1:]

    if "--import" in args:
        ids = None
        if "--ids" in args:
            i = args.index("--ids")
            ids = [x for x in args[i + 1].split(",") if x]
        r = fw.ccsw_import(provider_ids=ids, enabled=True, features=["traffic"])
        show("导入", r)

    if "--enable-all" in args:
        for a in fw.read_accounts(fw.account_file_for("ccsw")):
            print(fw.ccsw_update({"id": a.get("id"), "enabled": True}))
        print("已开启全部 ccsw 账户")

    if "--balance" in args:
        label = args[args.index("--balance") + 1]
        print("开启余额:", fw.ccsw_update({
            "id": (find_ccsw(label) or {}).get("id"),
            "provider_id": (find_ccsw(label) or {}).get("provider_id"),
            "enabled": True,
            "features": ["traffic", "balance"],
        }))

    if "--disable" in args:
        label = args[args.index("--disable") + 1]
        acc = find_ccsw(label)
        print("关闭:", fw.ccsw_update({"id": (acc or {}).get("id"), "enabled": False}))

    review = fw.ccsw_review()
    print_review_table(review)

    print("\n" + "=" * 60)
    print("当前 ccsw 账户配置（configs/ccsw.json）")
    print("=" * 60)
    for a in review.get("accounts") or []:
        print(" - id=%s name=%s enabled=%s features=%s bal=%s pid=%s base=%s" % (
            a.get("id"), a.get("name"), a.get("enabled"), a.get("features"),
            a.get("balance_kind"), a.get("provider_id"), a.get("base_url")))

    traffic = fw._load_traffic()
    print("\n" + "=" * 60)
    print("今日流量 → 行匹配（仅启用中的账户）")
    print("=" * 60)
    cfg = fw.load_config()
    active = [a for a in cfg.get("accounts", []) if fw.account_is_active(a)]
    for a in active:
        t = fw._traffic_for(a, traffic)
        tr = ("req=%s tok=%s $%.4f" % (
            t.get("requests"), t.get("tokens"), float(t.get("cost_usd") or 0))) if t else "(无匹配)"
        print(" - %-18s %-8s %s" % (a.get("name"), a.get("type"), tr))

    show("howto", review.get("howto"))

    if "--fetch" in args:
        print("\n执行 refresh 一轮…")
        try:
            fw._refresh_round()
        except Exception as e:
            print("refresh error:", e)
        rows = []
        for st, acc in zip(fw.state.get("stations") or [], fw.state.get("accounts") or []):
            rows.append({
                "name": st.get("name") if st else None,
                "type": acc.get("type"),
                "ok": st.get("ok") if st else None,
                "plan": st.get("plan") if st else None,
                "remaining": st.get("remaining") if st else None,
                "unit": st.get("unit") if st else None,
                "error": st.get("error") if st else None,
                "traffic": st.get("traffic") if st else None,
            })
        show("state.stations", rows)

    print("\n浮窗: 启动悬浮窗.vbs  |  review: GET /api/ccsw/review  |  导入: POST /api/ccsw/import  |  开关: POST /api/ccsw/update")


if __name__ == "__main__":
    main()

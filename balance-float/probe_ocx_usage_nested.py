# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from datetime import date
from pathlib import Path


def walk_find(obj, names, out, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in names and not isinstance(v, (dict, list)):
                out[prefix + k] = v
            if isinstance(v, (dict, list)):
                walk_find(v, names, out, prefix + k + ".")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            walk_find(v, names, out, prefix + "[%d]." % i)


def main():
    p = Path.home() / ".opencodex" / "usage.jsonl"
    today = date.today().isoformat()
    want = {
        "inputTokens", "outputTokens", "totalTokens", "cacheReadTokens", "cacheCreationTokens",
        "promptTokens", "completionTokens", "input_tokens", "output_tokens",
        "cost", "costUsd", "totalCost", "spend", "usd", "amount",
        "firstOutputMs", "durationMs", "latencyMs", "provider", "model", "requestedModel",
        "usageStatus", "status", "timestamp", "resolvedModel", "tierOutcome",
    }
    sample_success = []
    agg = defaultdict(lambda: {
        "reqs": 0, "ok": 0, "in": 0, "out": 0, "total": 0,
        "cache_r": 0, "cache_c": 0, "cost": 0.0,
        "dur": [], "ttft": [], "models": defaultdict(lambda: {"reqs": 0, "total": 0, "in": 0, "out": 0, "cost": 0.0, "dur": [], "ttft": []})
    })

    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            ts = row.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue
            import time as _t
            sec = ts / 1000.0 if ts > 1e12 else float(ts)
            day = _t.strftime("%Y-%m-%d", _t.localtime(sec))
            hour = _t.strftime("%H", _t.localtime(sec))
            flat = {}
            walk_find(row, want, flat)
            # prefer nested usage
            usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
            spend = row.get("spend") if isinstance(row.get("spend"), (dict, int, float)) else None
            if len(sample_success) < 5 and usage:
                sample_success.append({"keys": sorted(row.keys()),
                                       "usage": usage,
                                       "spend": spend,
                                       "totalTokens": row.get("totalTokens"),
                                       "firstOutputMs": row.get("firstOutputMs"),
                                       "durationMs": row.get("durationMs"),
                                       "model": row.get("model"),
                                       "provider": row.get("provider"),
                                       "resolvedModel": row.get("resolvedModel"),
                                       "status": row.get("status")})

            def num(*vals):
                for v in vals:
                    if isinstance(v, (int, float)):
                        return float(v)
                    if isinstance(v, dict):
                        # {amount: x} or {usd: x}
                        for k in ("amount", "usd", "value", "cost"):
                            if isinstance(v.get(k), (int, float)):
                                return float(v[k])
                    if isinstance(v, str):
                        try:
                            return float(v)
                        except Exception:
                            pass
                return 0.0

            inn = num(usage.get("inputTokens"), usage.get("input_tokens"), usage.get("promptTokens"),
                      row.get("inputTokens"), flat.get("usage.inputTokens"))
            out = num(usage.get("outputTokens"), usage.get("output_tokens"), usage.get("completionTokens"),
                      row.get("outputTokens"))
            tot = num(usage.get("totalTokens"), row.get("totalTokens")) or (inn + out)
            cr = num(usage.get("cacheReadTokens"), usage.get("cache_read_tokens"), usage.get("cacheReadInputTokens"))
            cc = num(usage.get("cacheCreationTokens"), usage.get("cache_creation_tokens"))
            cost = num(spend, usage.get("cost"), usage.get("costUsd"), row.get("cost"), row.get("spend"))
            model = row.get("resolvedModel") or row.get("model") or row.get("requestedModel") or "?"
            status = row.get("status")
            ok = isinstance(status, int) and 200 <= status < 300
            b = agg[day]
            b["reqs"] += 1
            if ok:
                b["ok"] += 1
            b["in"] += inn
            b["out"] += out
            b["total"] += tot
            b["cache_r"] += cr
            b["cache_c"] += cc
            b["cost"] += cost
            if row.get("durationMs") is not None:
                try:
                    b["dur"].append(float(row["durationMs"]))
                except Exception:
                    pass
            if row.get("firstOutputMs") is not None:
                try:
                    b["ttft"].append(float(row["firstOutputMs"]))
                except Exception:
                    pass
            m = b["models"][str(model)]
            m["reqs"] += 1
            m["total"] += tot
            m["in"] += inn
            m["out"] += out
            m["cost"] += cost
            if row.get("durationMs") is not None:
                try:
                    m["dur"].append(float(row["durationMs"]))
                except Exception:
                    pass
            if row.get("firstOutputMs") is not None:
                try:
                    m["ttft"].append(float(row["firstOutputMs"]))
                except Exception:
                    pass

    print("=== 有 usage 字段的样例 ===")
    for s in sample_success:
        print(json.dumps(s, ensure_ascii=False, indent=2)[:800])
        print("---")

    print("\n=== 各日汇总（OCX usage.jsonl，不读 CC Switch）===")
    for day in sorted(agg.keys())[-7:]:
        b = agg[day]
        lat = sum(b["dur"])/len(b["dur"]) if b["dur"] else None
        ttft = sum(b["ttft"])/len(b["ttft"]) if b["ttft"] else None
        print("%s reqs=%d ok=%d tokens=%d in=%d out=%d cache_r=%d cost=%.4f lat_avg=%s ttft_avg=%s" % (
            day, b["reqs"], b["ok"], b["total"], int(b["in"]), int(b["out"]),
            int(b["cache_r"]), b["cost"],
            ("%.0f" % lat) if lat is not None else "-",
            ("%.0f" % ttft) if ttft is not None else "-"))
        if day == today:
            print("  今日按模型:")
            for model, m in sorted(b["models"].items(), key=lambda x: -x[1]["reqs"]):
                lat = sum(m["dur"])/len(m["dur"]) if m["dur"] else None
                ttft = sum(m["ttft"])/len(m["ttft"]) if m["ttft"] else None
                print("   %-36s reqs=%-4d tokens=%-10d cost=%.4f lat=%s ttft=%s" % (
                    model[:36], m["reqs"], int(m["total"]), m["cost"],
                    ("%.0f" % lat) if lat is not None else "-",
                    ("%.0f" % ttft) if ttft is not None else "-"))


if __name__ == "__main__":
    main()

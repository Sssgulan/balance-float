import json
import time
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 15


def _get(url, headers=None, timeout=None):
    # 返回 (json, 延迟毫秒)；延迟按整个请求耗时计。
    # 本地地址绕过系统代理（注册表代理会把 127.0.0.1 一并劫持），远端保持系统默认。
    req = urllib.request.Request(url, headers=headers or {})
    t0 = time.perf_counter()
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        r = opener.open(req, timeout=timeout or DEFAULT_TIMEOUT)
    else:
        r = urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT)
    with r:
        data = json.loads(r.read().decode("utf-8"))
    return data, int(round((time.perf_counter() - t0) * 1000))


def _dig(obj, path):
    # 点路径取值，支持 "data.quota" 和 "balance_infos.0.total_balance"
    for part in path.split("."):
        obj = obj[int(part)] if part.isdigit() else obj[part]
    return obj


def _dig_cand(obj, path):
    # path 可以是字符串或候选字符串列表：依次尝试，第一个取到且非 None 的值生效
    # path 缺失（未配置该字段）返回 None 而不是抛异常：调用方常见写法是 path 可空
    if not path:
        return None
    paths = path if isinstance(path, list) else [path]
    for p in paths:
        try:
            v = _dig(obj, p)
            if v is not None:
                return v
        except (KeyError, IndexError, TypeError):
            continue
    return None


def _num(v):
    # 余额字段可能是字符串（"12.34"），转不动返回 None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_kind(account):
    # newapi 两种凭据查的不是同一口径：accessToken→/api/user/self，sk→/api/usage/token/
    kind = str(account.get("credential_kind") or "").replace("_", "").replace("-", "").lower()
    if kind in ("sk", "sktoken"):
        return "sk"
    if kind in ("accesstoken", "token", "access"):
        return "accessToken"
    return "sk" if str(account.get("access_token", "")).startswith("sk-") else "accessToken"


def _newapi_divisor(account):
    # divisor 是站点级常量（默认 500000）但站点可覆盖，响应里没有字段能反推；
    # 账户未配置或非法时返回 None，调用方降级为只显示原始 quota，不猜
    div = _num(account.get("divisor"))
    return div if div and div > 0 else None


def _quota_out(out, account, rem, used, tot):
    # NEWAPI 原始 quota → 展示值的统一换算；CNY 展示还差站点级 USDExchangeRate，标为估算值
    div = _newapi_divisor(account)
    if div:
        if rem is not None:
            rem /= div
        if used is not None:
            used /= div
        if tot is not None:
            tot /= div
        unit = str(account.get("unit") or "CNY")
        if unit == "CNY":
            # 前端暂无 estimated 落点，先把估算标记并入 unit 文案（UI 显示 "25.00CNY(估)"）
            out["unit"] = unit + "(估)"
            out["estimated"] = True
        else:
            out["unit"] = unit
    else:
        # divisor 未知：不猜换算，只给原始 quota；unit 留空并打 raw_quota 标记，前端单独识别
        out["unit"] = ""
        out["raw_quota"] = True
    out.update(remaining=rem, used=used, total=tot)


def _resp_error(resp, fallback):
    # 成功判据以 body 为准（new-api 看 success，OpenAI 兼容看 error 键，HTTP 状态码不可靠）；
    # message 只是站点本地化文案，不拿它做逻辑判断
    if not isinstance(resp, dict):
        return fallback
    msg = resp.get("message")
    if not msg and isinstance(resp.get("error"), dict):
        msg = resp["error"].get("message")
    return str(msg or fallback)


def fetch(account):
    out = {"name": account.get("name", ""), "ok": False, "remaining": None,
           "used": None, "total": None, "unit": "", "plan": "", "error": "",
           "latency_ms": None, "updated": time.strftime("%H:%M:%S")}
    try:
        t = account.get("type")
        try:
            timeout = float(account.get("timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        if t == "newapi":
            base = account["base_url"].rstrip("/")
            headers = {"Authorization": "Bearer " + account.get("access_token", ""),
                       "User-Agent": "balance-float/1.0"}
            if _norm_kind(account) == "sk":
                # sk 令牌走令牌口径；结尾斜杠不能少（路由是 /token 组下的 GET /）
                resp, ms = _get(base + "/api/usage/token/", headers, timeout)
                out["latency_ms"] = ms
                d = resp.get("data") if isinstance(resp, dict) else None
                if isinstance(resp, dict) and resp.get("success") and isinstance(d, dict):
                    if d.get("unlimited_quota"):
                        # unlimited 时三个额度数字无意义，单独展示而不是打印数字
                        out.update(ok=True, plan="无限额度")
                    else:
                        _quota_out(out, account, _num(d.get("total_available")),
                                   _num(d.get("total_used")), _num(d.get("total_granted")))
                        exp = d.get("expires_at")
                        # /api/usage/token/ 的 expires_at 是秒；/api/token/status 是毫秒，勿共用解析
                        if isinstance(exp, (int, float)) and exp > 0:
                            out["expires_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))
                        out["ok"] = out["remaining"] is not None
                        if not out["ok"]:
                            out["error"] = "响应缺少 total_available"
                else:
                    out["error"] = _resp_error(resp, "响应缺少 success/data")
            else:
                headers["New-Api-User"] = str(account.get("user_id", ""))
                resp, ms = _get(base + "/api/user/self", headers, timeout)
                out["latency_ms"] = ms
                d = resp.get("data") if isinstance(resp, dict) else None
                if isinstance(resp, dict) and resp.get("success") and isinstance(d, dict):
                    quota = _num(d.get("quota"))
                    if quota is None:
                        # quota 取不到按失败处理，不能把缺字段静默当成余额 0
                        out["error"] = "响应缺少 quota"
                    else:
                        used = _num(d.get("used_quota")) or 0.0
                        _quota_out(out, account, quota, used, quota + used)
                        out["plan"] = d.get("group", "")
                        out["ok"] = True
                else:
                    out["error"] = _resp_error(resp, "响应缺少 success/data")
        elif t == "deepseek":
            base = (account.get("base_url") or "https://api.deepseek.com").rstrip("/")
            resp, ms = _get(base + "/user/balance",
                            {"Authorization": "Bearer " + account["api_key"]}, timeout)
            out["latency_ms"] = ms
            # DeepSeek 口径：balance_infos[0].total_balance 直接是货币余额
            bal = _dig_cand(resp, "balance_infos.0") or {}
            rem = _num(bal.get("total_balance"))
            out.update(ok=rem is not None, remaining=rem, unit=bal.get("currency", "CNY"))
            if resp.get("is_available") is False:
                out["plan"] = "余额不足"
            if not out["ok"]:
                out["error"] = "响应缺少 balance_infos.total_balance"
        elif t == "moonshot":
            base = (account.get("base_url") or "https://api.moonshot.cn").rstrip("/")
            resp, ms = _get(base + "/v1/users/me/balance",
                            {"Authorization": "Bearer " + account["api_key"]}, timeout)
            out["latency_ms"] = ms
            d = resp.get("data") or {}
            # Moonshot 口径：available_balance 为可用余额，字段是字符串
            rem = _num(d.get("available_balance"))
            if rem is None:
                rem = _num(d.get("total_balance"))
            out.update(ok=rem is not None, remaining=rem,
                       used=_num(d.get("voucher_balance")),
                       unit=d.get("currency", "CNY"))
            if not out["ok"]:
                out["error"] = "响应缺少 available_balance"
        elif t == "zhipu":
            base = (account.get("base_url") or "https://open.bigmodel.cn").rstrip("/")
            resp, ms = _get(base + "/api/paas/v4/users/me/balance",
                            {"Authorization": "Bearer " + account["api_key"]}, timeout)
            out["latency_ms"] = ms
            # 智谱未公开文档化该接口，按社区通用字段做候选提取，取到即用
            rem = _num(_dig_cand(resp, ["data.total_balance", "data.available_balance",
                                        "data.balance", "total_balance", "balance"]))
            out.update(ok=rem is not None, remaining=rem,
                       unit=str(_dig_cand(resp, ["data.currency", "currency"]) or "CNY"))
            if not out["ok"]:
                out["error"] = "响应中未找到余额字段"
        elif t == "ccsw":
            # 流量节点：默认只标 CC-SW；features 含 balance 且上游注入了 _balance_src 才查远程
            src = account.get("_balance_src")
            feats = account.get("features") or ["traffic"]
            if "balance" not in feats or not src:
                out.update(ok=True, plan="CC-SW", latency_ms=0)
            else:
                kind = src.get("kind")
                if kind == "newapi":
                    return fetch(dict(account, type="newapi",
                                      base_url=src.get("base_url"),
                                      access_token=src.get("access_token") or "",
                                      user_id=src.get("user_id") or "",
                                      divisor=src.get("divisor") or 500000,
                                      unit=src.get("unit") or "CNY"))
                if kind == "generic":
                    return fetch(dict(account, type="generic",
                                      url=src.get("url"),
                                      headers=src.get("headers") or {},
                                      json_paths=src.get("json_paths") or {},
                                      unit=src.get("unit") or "CNY"))
                if kind == "openrouter":
                    base = (src.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
                    if not base.endswith("/v1"):
                        base = base + "/v1"
                    resp, ms = _get(base + "/credits",
                                    {"Authorization": "Bearer " + (src.get("api_key") or "")}, timeout)
                    out["latency_ms"] = ms
                    d = resp.get("data") or {}
                    rem = _num(d.get("total_credits"))
                    used = _num(d.get("total_usage"))
                    if rem is not None and used is not None:
                        out.update(ok=True, remaining=rem - used, used=used,
                                   total=rem, unit="USD", plan="OpenRouter")
                    else:
                        out["error"] = "响应缺少 credits 字段"
                else:
                    out.update(ok=True, plan="CC-SW", latency_ms=0)
        elif t == "ocx":
            base = account["base_url"].rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            resp, ms = _get(base + "/v1/models", timeout=timeout)
            out["latency_ms"] = ms
            nodes = resp.get("data") or []
            out.update(ok=True, remaining=None, plan="%d 节点" % len(nodes))
        elif t == "generic":
            key = account.get("api_key", "")
            base = account.get("base_url", "")
            url = account["url"].replace("{base_url}", base).replace("{api_key}", key)
            headers = {"User-Agent": account.get("user_agent", "Mozilla/5.0 balance-float/1.0")}
            for h, v in account.get("headers", {}).items():
                headers[h] = str(v).replace("{api_key}", key).replace("{base_url}", base)
            resp, ms = _get(url, headers, timeout)
            out["latency_ms"] = ms
            paths = account.get("json_paths", {})
            if paths.get("remaining"):
                v = _num(_dig_cand(resp, paths["remaining"]))
                if v is not None:
                    out["remaining"] = v
            if paths.get("used"):
                v = _num(_dig_cand(resp, paths["used"]))
                if v is not None:
                    out["used"] = v
            if paths.get("total"):
                v = _num(_dig_cand(resp, paths["total"]))
                if v is not None:
                    out["total"] = v
            # unit 路径是可选字段：未配置时按 None 处理，不能按缺失键去 dig
            out["unit"] = str(_dig_cand(resp, paths.get("unit")) or account.get("unit", ""))
            out["ok"] = out["remaining"] is not None or out["total"] is not None
            if not out["ok"]:
                out["error"] = "未从响应提取到余额"
        else:
            out["error"] = "未知类型: %s" % t
    except Exception as e:  # 任何失败都进 error，不抛出
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return out


# 常见中转站非标准端点的内置模板（口径见 ADAPTERS.md 第 5 节），弹窗可直接套用，免手写 JSON 路径。
# 三者成功判据/单位/字段层级都不统一，落库前建议先在目标站实测一次。
GENERIC_PRESETS = [
    {"key": "user-balance", "name": "one-api 系 /user/balance",
     "url": "{base_url}/user/balance",
     "headers": {"Authorization": "Bearer {api_key}"},
     "json_paths": {"remaining": ["data.balance", "balance", "remaining", "quota"],
                    "unit": ["data.currency", "currency", "unit"]},
     "note": "one-api 系旧接口；个别站成功判据看 code 而非 success"},
    {"key": "v1-usage", "name": "/v1/usage",
     "url": "{base_url}/v1/usage",
     "headers": {"Authorization": "Bearer {api_key}"},
     "json_paths": {"remaining": ["remaining", "quota.remaining", "balance"],
                    "unit": ["currency", "unit"]},
     "note": "结构不统一，remaining / quota.remaining / balance 三级兜底"},
    {"key": "usage-account", "name": "/api/usage/account/",
     "url": "{base_url}/api/usage/account/",
     "headers": {"Authorization": "Bearer {api_key}"},
     "json_paths": {"remaining": ["data.balance", "balance"],
                    "unit": ["data.currency", "currency"]},
     "note": "成功判据是 code 为 true 而不是 success；判失败时行内直接显示报错"},
]

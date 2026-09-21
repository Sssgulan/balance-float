# -*- coding: utf-8 -*-
# 浮窗壳: 承载 UI(ui/), 后台余额查询 + 本机 API + 账户配置管理
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import uuid
import threading
import time
import ctypes
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import webview
except ImportError:  # 纯后端/同步脚本可无 pywebview，窗口启动路径仍需要它
    webview = None

# WebView2 默认背景是不透明白色，强制透明才能露出圆角外区域
os.environ.setdefault("WEBVIEW2_DEFAULT_BACKGROUND_COLOR", "00000000")

import providers
import ocx_metrics

try:
    import pages
except ImportError:  # 单文件/极端裁剪场景下没有组装器, 退回直接读 ui/index.html
    pages = None

# 打包后 (PyInstaller) __file__ 在解包目录里, 不能拿它当配置目录: 配置必须落在 exe 旁边,
# 才会在多次启动之间保留, 也才有写权限
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "ui")
CONFIG_DIR = os.path.join(HERE, "configs")
# 窗口/任务栏图标。打包后 assets 跟 exe 同级, 双击 vbs 时 cwd 已经在程序目录里
ICON = os.path.join(HERE, "assets", "icon.ico")

state = {"stations": [], "traffic": None, "loading": True, "updated": "",
         "accounts": [], "settings": {}}
wake = threading.Event()

# 本机 API 的防跨域令牌：随进程生成，静态返回 index.html 时注入 <meta>，前端经它或
# Bridge.get_api_token() 取得后放在 X-Api-Token 头里；浏览器里其他页面拿不到这两个通道
_API_TOKEN = uuid.uuid4().hex
_PORT = 8765
# 凭据字段发给前端时的掩码前缀；save 收到以它开头（或为空）的值视为「未改动」，沿用库里的原值
_MASK_PREFIX = "\u2022\u2022\u2022\u2022"
_CRED_FIELDS = ("access_token", "api_key")
# 上一轮查询成功的站点结果（按账户 id），失败轮回填旧值用
_last_good = {}
_settings_lock = threading.RLock()
# 账户文件的读-改-写临界区，非重入不行：save_account 会在临界区内再读一次
_ACCOUNTS_LOCK = threading.RLock()

# 常驻并发池：线程按需创建、跨轮复用，不再每轮新建；账户多于 16 个时排队，
# 单站卡顿由账户/全局 timeout 兜底
_FETCH_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="fetch")

# 各类型必填字段：/api/account/save、/api/account/test 与 --check 共用同一张表，
# 缺字段的账户不允许落盘（落盘后每轮刷新都会在列表里多一行报错）
REQUIRED_FIELDS = {"newapi": ["base_url", "access_token"], "deepseek": ["api_key"],
                   "generic": ["url"], "moonshot": ["api_key"], "zhipu": ["api_key"],
                   "ccsw": ["provider_id"], "ocx": ["base_url"]}


def load_config():
    # configs/ 下的账户文件合并成一份配置；跨文件的全局顺序另由 settings.order 表达
    cfg = _read_settings_unlocked() if os.path.isdir(CONFIG_DIR) else {"refresh_seconds": 60}
    accounts = []
    ign = ignored_sets()
    for rel in all_account_files():
        accounts.extend([a for a in read_accounts(rel) if not account_ignored(a, ign)])
    cfg["accounts"] = accounts
    return cfg


def _check(cfg):
    # --check 用：返回 (ok, 消息列表)。必填字段缺失才 fail，空 accounts 通过
    msgs = ["配置加载 OK"]
    ok = True
    try:
        if int(cfg.get("refresh_seconds")) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        msgs.append("[配置] refresh_seconds 必须是正整数")
        ok = False
    for i, acc in enumerate(cfg.get("accounts", [])):
        label = "账户%d(%s)" % (i, acc.get("name", "?"))
        if not acc.get("name") or not acc.get("type"):
            msgs.append("[账户%d] 缺 name 或 type" % i)
            ok = False
            continue
        if acc["type"] not in REQUIRED_FIELDS:
            msgs.append("[%s] 未知 type=%s" % (label, acc["type"]))
            ok = False
            continue
        missing = [k for k in REQUIRED_FIELDS[acc["type"]] if not acc.get(k)]
        if missing:
            msgs.append("[%s] 缺必填字段: %s" % (label, ", ".join(missing)))
            ok = False
        else:
            msgs.append("[%s] OK" % label)
    return ok, msgs


def _mask_creds(acc):
    # /api/accounts 的出参脱敏：凭据字段换成 "••••" + 末 4 位，明文不出进程
    out = dict(acc)
    for f in _CRED_FIELDS:
        v = out.get(f)
        if isinstance(v, str) and v:
            out[f] = _MASK_PREFIX + (v[-4:] if len(v) > 4 else "")
    return out


def _unmask_creds(acc):
    # 编辑提交的语义：凭据字段是掩码或空 = 用户没改，恢复库里的原值；输入新值则覆盖
    if not acc.get("id"):
        return acc
    _rel, _accs, _i, old = find_account(acc["id"])
    if not old:
        return acc
    for f in _CRED_FIELDS:
        v = acc.get(f)
        if (not isinstance(v, str) or not v or v.startswith(_MASK_PREFIX)) and old.get(f):
            acc[f] = old[f]
    return acc

# 各账户类型落盘的配置文件（相对 configs/）；official/ 一家一个文件
ACCOUNT_FILES = {
    "newapi": "newapi.json",
    "generic": "generic.json",
    "ccsw": "ccsw.json",
    "ocx": "ocx.json",
    "deepseek": os.path.join("official", "deepseek.json"),
    "moonshot": os.path.join("official", "moonshot.json"),
    "zhipu": os.path.join("official", "zhipu.json"),
}


def _accounts_path(rel):
    return os.path.join(CONFIG_DIR, rel)


def _ro_uri(db):
    # Windows 路径是单反斜杠，必须换成 / 再拼 file: URI；写 "\\\\" 匹配不到
    return "file:%s?mode=ro" % db.replace("\\", "/")


def _url_host(url):
    # 含端口：127.0.0.1:10100 与 127.0.0.1:18080 必须区分
    m = re.match(r"https?://([^/\s]+)", url or "")
    return m.group(1).lower() if m else ""


def _norm_ocx_base(base):
    # OCX 节点身份 = 去掉尾部 / 与 /v1 的服务器连接
    b = (base or "").rstrip("/")
    return b[:-3] if b.endswith("/v1") else b


# 删除名单（settings.json 的 ccsw_ignored / ocx_ignored）：删过的行打个标记，
# 之后的「导入刷新」不会把它再拉回来，展开页与接入页也就不再出现
_IGNORE_KINDS = ("ccsw", "ocx")


def ignored_sets():
    s = read_settings()
    out = {}
    for kind in _IGNORE_KINDS:
        v = s.get(kind + "_ignored")
        out[kind] = set(x for x in v if isinstance(x, str) and x) if isinstance(v, list) else set()
    return out


def set_ignored(kind, key, on=True):
    if kind not in _IGNORE_KINDS or not key:
        return
    # 读-改-写整段持锁: 并发删除时两个请求各自 read→改→write, 名单会互相覆盖丢项
    with _settings_lock:
        cur = ignored_sets()[kind]
        if on == (key in cur):
            return
        cur.add(key) if on else cur.discard(key)
        write_settings({kind + "_ignored": sorted(cur)})


def ignore_key_of(kind, acc):
    # 拉黑键：CC-SW 认 provider_id，OCX 认规范化后的服务器连接
    if kind == "ccsw":
        return acc.get("provider_id") or ""
    if kind == "ocx":
        return _norm_ocx_base(acc.get("base_url"))
    return ""


def account_ignored(acc, sets=None):
    kind = (acc or {}).get("type")
    key = ignore_key_of(kind, acc or {})
    if not key:
        return False
    return key in ((sets or ignored_sets()).get(kind) or set())


def _ccswitch_db():
    return os.path.join(os.path.expanduser("~"), ".cc-switch", "cc-switch.db")


def _ccswitch_settings_current():
    # CC Switch 当前激活的 provider id，用于把 _codex_session / _session 流量归到对应站点
    fp = os.path.join(os.path.expanduser("~"), ".cc-switch", "settings.json")
    out = {"codex": None, "claude": None, "gemini": None}
    if not os.path.isfile(fp):
        return out
    try:
        with open(fp, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return out
    out["codex"] = s.get("currentProviderCodex") or None
    out["claude"] = s.get("currentProviderClaude") or None
    out["gemini"] = s.get("currentProviderGemini") or None
    return out


def account_file_for(acc_type):
    rel = ACCOUNT_FILES.get(acc_type)
    if not rel:
        raise ValueError("未知账户类型: %s" % acc_type)
    return rel


def validate_account(acc, for_test=False):
    # save/test 前的必填校验（与 main.check 同一张表）；缺字段的账户落盘后
    # 刷新一轮就会在列表里出现一行报错，所以在这里挡掉。
    # for_test 放宽凭据字段：只想填地址试连通性不被拦，真实错误交给站点响应去说
    if not str(acc.get("name") or "").strip():
        return "缺少名称"
    t = acc.get("type")
    if t not in ACCOUNT_FILES:
        return "未知类型: %s" % t
    req = REQUIRED_FIELDS.get(t, [])
    if for_test:
        req = [k for k in req if k not in _CRED_FIELDS]
    missing = [k for k in req if not str(acc.get(k) or "").strip()]
    if missing:
        return "缺少必填字段: %s" % ", ".join(missing)
    if t == "newapi":
        div = acc.get("divisor")
        if div not in (None, ""):
            try:
                if float(div) <= 0:
                    return "divisor 必须为正数"
            except (TypeError, ValueError):
                return "divisor 必须是数字"
    return None


def read_accounts(rel):
    fp = _accounts_path(rel)
    if not os.path.isfile(fp):
        return []
    d = _read_json_loose(fp, {})
    return d.get("accounts", []) if isinstance(d, dict) else []


def write_accounts(rel, accounts):
    fp = _accounts_path(rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"accounts": accounts}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fp)


# 并发保护: 账户文件的读-改-写整段跑在同一临界区里。
# 接入页的批量删除会同时发多个 POST, 每个都 read→pop→write 一次 ccsw.json;
# 没有这层锁时两个请求读到同一份旧数组, 各删各的再互相覆盖 —— 两边都回 ok 却只落了一次,
# 拉黑名单也会丢项。OneDrive 在 configs/ 上做同步把窗口拉得更宽, 所以不能靠"碰巧不撞车"。
# ponytail: 一把模块级重入锁就够, 不引文件锁/数据库.
_read_accounts_io = read_accounts
_write_accounts_io = write_accounts


def _read_json_loose(fp, default):
    # OneDrive 同步 / 被强杀时可能把两个版本先后写进同一个文件, 尾部留下残块, json.load 直接
    # 报 Extra data —— 整个列表就都读不出来, 删账户也跟着失败。取第一个完整 JSON 即可恢复。
    try:
        with open(fp, encoding="utf-8") as f:
            return json.JSONDecoder().raw_decode(f.read().lstrip("\ufeff \t\r\n"))[0]
    except (OSError, ValueError):
        return default


def read_accounts(rel):
    with _ACCOUNTS_LOCK:
        return _read_accounts_io(rel)


def write_accounts(rel, accounts):
    with _ACCOUNTS_LOCK:
        _write_accounts_io(rel, accounts)


def delete_accounts(ids):
    # 一次请求删一批: 收集与落盘全程持锁, 中途不会有别的写请求插进来，也就不会互相覆盖
    out = {}
    with _ACCOUNTS_LOCK:
        for acc_id in ids:
            rel, accs, idx, acc = find_account(acc_id)
            if rel is None:
                out[acc_id] = {"ok": False, "error": "未找到该账户"}
                continue
            accs.pop(idx)
            write_accounts(rel, accs)
            # 删除即拉黑: 记进 settings.json 的忽略名单, 导入刷新不会把它复活
            kind = (acc or {}).get("type")
            set_ignored(kind, ignore_key_of(kind, acc or {}))
            out[acc_id] = {"ok": True}
        # 顺手把 settings.order 里的残 id 剔掉，否则 order 只增不减
        order = read_settings().get("order") or []
        left = [x for x in order if not (x in out and out[x].get("ok"))]
        if left != order:
            write_settings({"order": left})
    wake.set()
    return {"ok": all(v.get("ok") for v in out.values()), "results": out}


# 官方接口页"主流模型"清单: 只定义标准字段的标题与顺序, 值一律留空由你自己填。
# 加字段/改标题直接改 configs/official/models.json 里的 fields; 加模型往 models 里追加。
MODELS_FILE = os.path.join("official", "models.json")
DEFAULT_MODELS = {
    "fields": {
        "api_key":   {"title": "API Key",   "hint": "控制台生成的密钥",   "icon": "key"},
        "api_url":   {"title": "接口链接",  "hint": "接口/文档地址",      "icon": "link"},
        "base_url":  {"title": "请求地址",  "hint": "OpenAI 兼容端点根地址", "icon": "link"},
        "model_id":  {"title": "模型 ID",   "hint": "请求体里的 model 字段", "icon": "code"},
        "team_id":   {"title": "Team ID",   "hint": "团队或组织标识",     "icon": "fingerprint"},
        "team_url":  {"title": "Team 连接", "hint": "团队管理页地址",     "icon": "group"},
        "quota_url": {"title": "额度端口",  "hint": "余额/用量查询地址",  "icon": "calculate"},
        "console":   {"title": "控制台",    "hint": "后台登录地址",       "icon": "badge"}
    },
    "models": [
        {"key": "deepseek", "name": "DeepSeek", "category": "官方直连",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "moonshot", "name": "Kimi", "category": "官方直连",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "zhipu", "name": "GLM", "category": "官方直连",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "glm-team", "name": "GLM Team", "category": "团队/企业版",
         "fields": {"api_key": "", "team_id": "", "team_url": "", "base_url": "", "model_id": ""}},
        {"key": "openrouter", "name": "OpenRouter", "category": "聚合平台",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "siliconflow", "name": "硅基流动", "category": "聚合平台",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "together", "name": "Together", "category": "聚合平台",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "volcengine", "name": "火山方舟", "category": "云厂商",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "dashscope", "name": "百炼 / 通义", "category": "云厂商",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "hunyuan", "name": "腾讯混元", "category": "云厂商",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "qianfan", "name": "百度千帆", "category": "云厂商",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}},
        {"key": "spark", "name": "讯飞星火", "category": "云厂商",
         "fields": {"api_key": "", "base_url": "", "model_id": "", "api_url": "", "console": ""}}
    ]
}


def read_models():
    # 首次读到就把标准表落盘, 之后以文件为准, 你手改的标题/新模型页面直接跟着变
    fp = _accounts_path(MODELS_FILE)
    if not os.path.isfile(fp):
        write_models(DEFAULT_MODELS)
        return json.loads(json.dumps(DEFAULT_MODELS))
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_MODELS))
    if not isinstance(d, dict) or not isinstance(d.get("models"), list):
        return json.loads(json.dumps(DEFAULT_MODELS))
    if not isinstance(d.get("fields"), dict):
        d["fields"] = dict(DEFAULT_MODELS["fields"])
    return d


def write_models(data):
    fp = _accounts_path(MODELS_FILE)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fp)


def save_model_fields(key, fields):
    # 只覆盖文件里已声明的键: 你手动加的字段不会被页面抹掉
    data = read_models()
    for m in data["models"]:
        if m.get("key") != key:
            continue
        cur_f = dict(m.get("fields") or {})
        for k in cur_f:
            if k in fields:
                cur_f[k] = str(fields.get(k) or "").strip()
        m["fields"] = cur_f
        write_models(data)
        return {"ok": True, "key": key}
    return {"ok": False, "error": "未知模型: %s" % key}


def all_account_files():
    out = []
    if os.path.isdir(CONFIG_DIR):
        for root, _dirs, files in os.walk(CONFIG_DIR):
            for fn in sorted(files):
                if not fn.endswith(".json") or fn in ("settings.json", "models.json"):
                    continue
                out.append(os.path.relpath(os.path.join(root, fn), CONFIG_DIR))
    return out


def ensure_ids():
    # 给缺 id 的旧账户补上短 id 并回写，保持与 UI 的行稳定对应
    for rel in all_account_files():
        accs = read_accounts(rel)
        if any(not a.get("id") for a in accs):
            for a in accs:
                if not a.get("id"):
                    a["id"] = uuid.uuid4().hex[:8]
            write_accounts(rel, accs)


def accounts_meta():
    meta = []
    for rel in all_account_files():
        for a in read_accounts(rel):
            meta.append({"id": a.get("id", ""), "name": a.get("name", ""),
                         "type": a.get("type", ""), "file": rel})
    return meta


def find_account(acc_id):
    for rel in all_account_files():
        accs = read_accounts(rel)
        for i, a in enumerate(accs):
            if a.get("id") == acc_id:
                return rel, accs, i, a
    return None, None, -1, None


def save_account(payload):
    # payload 为完整账户对象；带 id 且已存在则原位更新，否则按类型落盘新增
    acc_type = payload.get("type")
    if acc_type not in ACCOUNT_FILES:
        return {"ok": False, "error": "未知类型: %s" % acc_type}
    acc = dict(payload)
    acc.pop("file", None)  # 前端从 /api/accounts 回填时会带 file 字段，落盘前去掉
    # 凭据字段是掩码或空 = 用户没改（/api/accounts 已脱敏），恢复库里的原值再落盘
    acc = _unmask_creds(acc)
    err = validate_account(acc)
    if err:
        return {"ok": False, "error": err}
    name = str(acc.get("name") or "").strip()
    acc["name"] = name or "未命名"
    rel = account_file_for(acc_type)
    accs = read_accounts(rel)
    idx = next((i for i, a in enumerate(accs) if a.get("id") and a.get("id") == acc.get("id")), -1)
    if idx < 0 and acc.get("id"):
        # 编辑时改了类型: 同 id 旧记录还躺在别的文件里, 先搬走, 否则列表会出现重复行
        for other in all_account_files():
            if other == rel:
                continue
            olds = read_accounts(other)
            if any(a.get("id") == acc["id"] for a in olds):
                write_accounts(other, [a for a in olds if a.get("id") != acc["id"]])
    if idx >= 0:
        accs[idx] = acc
        action = "updated"
    else:
        if not acc.get("id"):
            acc["id"] = uuid.uuid4().hex[:8]
        accs.append(acc)
        action = "created"
    write_accounts(rel, accs)
    if action == "created":
        set_ignored(acc_type, ignore_key_of(acc_type, acc), False)   # 手动重新加回 = 撤销拉黑
    wake.set()
    return {"ok": True, "action": action, "id": acc["id"], "file": rel}


def delete_account(acc_id):
    # 单条删除 = 批量的一个元素; 脚本/测试仍可直接调它
    return delete_accounts([acc_id])["results"].get(acc_id) or {"ok": False, "error": "未找到该账户"}


def reorder_accounts(ids):
    # ids 为全量账户的目标顺序。账户分散在多个文件里, 文件内数组顺序表达不了跨文件的全局顺序,
    # 因此把顺序按 id 记进 settings.json, 由 refresh_loop 统一按它排序。
    known = set()
    ign = ignored_sets()
    for rel in all_account_files():
        for a in read_accounts(rel):
            # 与列表口径一致：已删除（拉黑）的行不算在内，否则拖拽排序会误报「列表已变化」
            if a.get("id") and not account_ignored(a, ign):
                known.add(a["id"])
    if set(ids) != known:
        return {"ok": False, "error": "账户列表已变化，请刷新后重试"}
    write_settings({"order": list(ids)})
    # 立刻按新顺序重排内存快照: UI 400ms 后就会拉 /api/state,
    # 此时后台还没跑完一轮查询, 不先把快照调好就会把旧顺序又盖回界面上。
    rank = {aid: i for i, aid in enumerate(ids)}
    idx = sorted(range(len(state["accounts"])),
                 key=lambda k: rank.get(state["accounts"][k].get("id"), len(rank)))
    state["accounts"] = [state["accounts"][k] for k in idx]
    if len(state["stations"]) == len(idx):
        state["stations"] = [state["stations"][k] for k in idx]
    wake.set()
    return {"ok": True}


def read_settings():
    with _settings_lock:
        return _read_settings_unlocked()


def _read_settings_unlocked():
    fp = _accounts_path("settings.json")
    s = {"refresh_seconds": 60, "timeout": providers.DEFAULT_TIMEOUT}
    if os.path.isfile(fp):
        d = _read_json_loose(fp, None)
        if isinstance(d, dict):
            s.update(d)
    return s


def write_settings(patch):
    with _settings_lock:
        s = _read_settings_unlocked()
        s.update(patch)
        fp = _accounts_path("settings.json")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        tmp = fp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        os.replace(tmp, fp)
    return s


def public_settings(s=None):
    # 发给前端的设置白名单；弹窗按分钟显示，秒↔分钟换算收敛在这一层
    s = read_settings() if s is None else s
    try:
        rs = max(1, int(s.get("refresh_seconds") or 60))
    except (TypeError, ValueError):
        rs = 60
    try:
        to = max(1, int(s.get("timeout") or providers.DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        to = providers.DEFAULT_TIMEOUT
    return {"refresh_seconds": rs, "timeout": to, "refresh_minutes": max(1, round(rs / 60)),
            "port": _PORT}


def sanitize_settings(body):
    # /api/settings 只收白名单键；refresh_seconds 与 refresh_minutes 给一个即可，落盘统一为秒
    patch = {}
    if "refresh_seconds" in body:
        try:
            v = int(body["refresh_seconds"])
        except (TypeError, ValueError):
            return None, "refresh_seconds 必须是整数"
        if v <= 0:
            return None, "refresh_seconds 必须为正整数"
        patch["refresh_seconds"] = v
    if "refresh_minutes" in body and "refresh_seconds" not in patch:
        try:
            v = float(body["refresh_minutes"])
        except (TypeError, ValueError):
            return None, "refresh_minutes 必须是数字"
        if v <= 0:
            return None, "refresh_minutes 必须大于 0"
        patch["refresh_seconds"] = int(round(v * 60))
    if "timeout" in body:
        try:
            v = int(round(float(body["timeout"])))
        except (TypeError, ValueError):
            return None, "timeout 必须是数字"
        if v <= 0:
            return None, "timeout 必须为正数"
        patch["timeout"] = v
    return patch, None


def _apply_window_appearance(form):
    if not form:
        return
    hwnd = int(form.Handle.ToInt64())
    # WebView2 使用不透明黑底，只有最外层窗口做一次 Alpha，
    # 避免 pywebview transparent 模式在导航阶段提前显示渲染面。
    from System.Drawing import Color
    form.BackColor = Color.Black
    user32 = ctypes.windll.user32
    ex = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, ex | 0x80000)
    # 默认 Alpha 230；运行期可通过 Bridge.set_opacity() 调节
    user32.SetLayeredWindowAttributes(hwnd, 0, 230, 2)

    _apply_round_region(form)


def _apply_round_region(form, radius_css=16):
    if not form:
        return
    hwnd = int(form.Handle.ToInt64())
    user32 = ctypes.windll.user32
    # 半径须与卡片的 rounded-2xl 一致, 否则窗口裁得比卡片方, 四角露出窗口底色。
    # CreateRoundRectRgn 末两参是圆角椭圆的宽高, 即半径的两倍。
    scale = getattr(form, "_scale", 1) or 1
    d = max(0, int(round(radius_css * scale * 2)))
    # 窗口尺寸由 UI 上报的卡片尺寸决定, 裁剪区域始终对齐整个窗口。
    rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
        0, 0, int(form.Width) + 1, int(form.Height) + 1, d, d)
    user32.SetWindowRgn(hwnd, rgn, True)


def hide_initial_frame(window):
    """Keep pywebview's one required initial Show invisible until React is ready."""
    form = getattr(window, "native", None)
    if form:
        form.Opacity = 0


def apply_window_finish(window=None):
    form = getattr(window, "native", None) if window is not None else webview.windows[0].native
    if not form:
        return

    def apply():
        if getattr(form, "_float_ready", False):
            return
        # Opacity 必须先恢复，再设置最终 Alpha；反过来会把 230 覆盖成 255。
        form.Opacity = 1
        _apply_window_appearance(form)
        form.Activate()
        form._float_ready = True

    try:
        from System import Action
        if form.InvokeRequired:
            form.Invoke(Action(apply))
        else:
            apply()
    except Exception:
        pass


def ccswitch_traffic(today):
    # 只读查询 cc-switch.db 今日流量
    # 返回 (stats, names, slug_names, slug_hosts)：
    #   stats {provider_id: [次数, tokens, 费用USD]}
    #   names {精确 provider_id: 名称}；slug_names {名称小写键: 名称}；
    #   slug_hosts {名称小写键: base_url 主机}——日志里的 id 常是 "名称前缀-时间戳" 格式
    db = _ccswitch_db()
    if not os.path.isfile(db):
        return None, {}, {}, {}
    con = sqlite3.connect(_ro_uri(db), uri=True, timeout=2)
    try:
        names, slug_names, slug_hosts = {}, {}, {}
        for pid, _app_type, name, cfg in _iter_ccswitch_providers():
            names.setdefault(pid, name)
            key = _name_key(name)
            slug_names.setdefault(key, name)
            host = _url_host(_provider_base(cfg) or "")
            if host:
                slug_hosts.setdefault(key, host)
        stats = {}
        # 今日日志：created_at 是 unix 秒，按本地日期过滤
        for pid, n, tok, cost in con.execute(
                "SELECT provider_id, COUNT(*), SUM(input_tokens+output_tokens), "
                "SUM(CAST(total_cost_usd AS REAL)) FROM proxy_request_logs "
                "WHERE date(created_at,'unixepoch','localtime')=? GROUP BY provider_id", (today,)):
            stats[pid] = [n, tok or 0, cost or 0.0]
        # rollups 是"聚合后删明细"，同日同 provider 两表相加而不是覆盖
        for pid, n, tin, tout, cost in con.execute(
                "SELECT provider_id, SUM(request_count), SUM(input_tokens), SUM(output_tokens), "
                "SUM(CAST(total_cost_usd AS REAL)) FROM usage_daily_rollups WHERE date=? GROUP BY provider_id", (today,)):
            old = stats.get(pid, [0, 0, 0.0])
            stats[pid] = [old[0] + (n or 0), old[1] + (tin or 0) + (tout or 0), old[2] + (cost or 0.0)]
        return stats, names, slug_names, slug_hosts
    finally:
        con.close()


_SESSION_KIND = {
    "_codex_session": "codex",
    "_session": "claude",
}


def _session_kind_of(pid):
    if pid in _SESSION_KIND:
        return _SESSION_KIND[pid]
    if re.match(r"^_(codex|ocx|opencodex)", pid or ""):
        return "codex"
    if re.match(r"^_session|^_claude", pid or ""):
        return "claude"
    return None


def _resolve_traffic_stats(stats, names):
    # 合成会话 id（_codex_session 等）归并到 CC Switch「当前」provider，
    # 否则本机今日流量对不上任何账户行。原始会话键单独保留，供 OCX 行兜底。
    cur = _ccswitch_settings_current()
    resolved = {}
    session_raw = {}

    def add(bucket, pid, s):
        old = bucket.get(pid, [0, 0, 0.0])
        bucket[pid] = [old[0] + (s[0] or 0), old[1] + (s[1] or 0), old[2] + (s[2] or 0.0)]

    for pid, s in stats.items():
        kind = _session_kind_of(pid)
        if kind:
            session_raw[pid] = list(s)
            target = cur.get(kind)
            if target and (target in names or True):
                add(resolved, target, s)
                continue
        add(resolved, pid, s)
    return resolved, session_raw, cur


def _load_traffic():
    try:
        stats, names, slug_names, slug_hosts = ccswitch_traffic(date.today().isoformat())
        if stats is None:
            return {"available": False, "message": "未找到 cc-switch.db"}
        resolved, session_raw, cur = _resolve_traffic_stats(stats, names)
        providers_out = {}
        by_name = {}
        by_host = {}
        for pid, s in resolved.items():
            nm = names.get(pid)
            if not nm:
                key = _name_key(_slug_of(pid))
                nm = slug_names.get(key) or names.get(_slug_of(pid)) or _slug_of(pid) or pid
            host = slug_hosts.get(_name_key(nm)) or slug_hosts.get(_name_key(_slug_of(pid)))
            providers_out[pid] = {"name": nm, "requests": s[0], "tokens": s[1], "cost_usd": s[2]}
            agg = by_name.setdefault(nm, {"requests": 0, "tokens": 0, "cost_usd": 0.0})
            agg["requests"] += s[0]
            agg["tokens"] += s[1]
            agg["cost_usd"] += s[2]
            if host:
                hagg = by_host.setdefault(host, {"requests": 0, "tokens": 0, "cost_usd": 0.0})
                hagg["requests"] += s[0]
                hagg["tokens"] += s[1]
                hagg["cost_usd"] += s[2]
        return {
            "available": True,
            "requests": sum(s["requests"] for s in providers_out.values()),
            "tokens": sum(s["tokens"] for s in providers_out.values()),
            "cost_usd": sum(s["cost_usd"] for s in providers_out.values()),
            "providers": providers_out,
            "by_name": by_name,
            "by_host": by_host,
            "session": session_raw,
            "current": cur,
        }
    except Exception as e:
        return {"available": False, "message": str(e)}


def _traffic_for(acc, traffic):
    # 行级今日用量匹配：provider_id/linked → 账户名 → base_url 主机(含端口) → OCX 会话兜底
    if not traffic or not traffic.get("available"):
        return None
    prov = traffic.get("providers") or {}
    for key in (acc.get("provider_id"), acc.get("linked_provider_id")):
        if key and key in prov:
            return prov[key]
    by_name = traffic.get("by_name") or {}
    if acc.get("name") and acc["name"] in by_name:
        return by_name[acc["name"]]
    host = _url_host(acc.get("base_url") or acc.get("url"))
    by_host = traffic.get("by_host") or {}
    if host and host in by_host:
        return by_host[host]
    # OCX 行兜底：本地 OpenCodex 代理的流量常记在 _codex_session，已归并到 currentProviderCodex
    if acc.get("type") == "ocx":
        cur = traffic.get("current") or {}
        for kind in ("codex", "gemini", "claude"):
            pid = cur.get(kind)
            if pid and pid in prov:
                return prov[pid]
        sess = traffic.get("session") or {}
        for _k, v in sess.items():
            return v
        for k, v in prov.items():
            if k.startswith("_codex") or k.startswith("_ocx") or k.startswith("_opencodex"):
                return v
        for nm in ("OpenCodex", acc.get("name") or ""):
            if nm and nm in by_name:
                return by_name[nm]
    return None


# ---------------- CC-SW / OCX 扫描与导入 ----------------

def _provider_base(cfg):
    # 从 cc-switch provider 的 settings_config 提取 base_url（claude/codex/gemini 三种结构）
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    base = env.get("ANTHROPIC_BASE_URL") or env.get("GOOGLE_GEMINI_BASE_URL")
    if not base:
        conf = cfg.get("config")
        if isinstance(conf, str):
            # TOML 文本两种写法都要认：段内 base_url 与顶层 base_url（codex 配置常见后者）
            m = (re.search(r'base_url\s*[=:]\s*"([^"]+)"', conf)
                 or re.search(r"base_url\s*[=:]\s*'([^']+)'", conf)
                 or re.search(r"base_url\s*[=:]\s*([^\s\"'\n,;]+)", conf))
            base = m.group(1) if m else None
        elif isinstance(conf, dict):
            mp = conf.get("model_providers") or {}
            base = conf.get("base_url") or next(
                (v.get("base_url") for v in mp.values() if isinstance(v, dict) and v.get("base_url")), None)
    return base


def _provider_token(app_type, cfg):
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    if app_type == "claude":
        return env.get("ANTHROPIC_AUTH_TOKEN")
    if app_type == "gemini":
        return env.get("GEMINI_API_KEY")
    if app_type == "codex":
        auth = cfg.get("auth") if isinstance(cfg.get("auth"), dict) else {}
        return auth.get("OPENAI_API_KEY")
    return None


def _iter_ccswitch_providers():
    # 只读遍历 (id, app_type, name, cfg)；库不存在返回空
    for pid, app_type, name, cfg, _meta in _iter_ccswitch_full():
        yield pid, app_type, name, cfg


def _iter_ccswitch_full():
    # 只读遍历 (id, app_type, name, cfg, meta)；usage_script 在 meta 里
    db = _ccswitch_db()
    if not os.path.isfile(db):
        return
    con = sqlite3.connect(_ro_uri(db), uri=True, timeout=2)
    try:
        for pid, app_type, name, cfg_text, meta_text in con.execute(
                "SELECT id, app_type, name, settings_config, meta FROM providers"):
            try:
                cfg = json.loads(cfg_text or "{}")
            except (TypeError, ValueError):
                cfg = {}
            try:
                meta = json.loads(meta_text or "{}")
            except (TypeError, ValueError):
                meta = {}
            yield pid, app_type, name, cfg, meta if isinstance(meta, dict) else {}
    finally:
        con.close()


def _slug_of(pid):
    # provider_id 形如 "ccapi-1789377424476"（名称前缀-时间戳）→ 取 "ccapi"
    return re.sub(r"-\d+$", "", pid or "")


def _name_key(s):
    return re.sub(r"[^0-9a-z一-鿿]+", "", (s or "").lower())


# 落盘有用字段；扫描注解/脚本原文/令牌都不写进 configs
_CCSW_USEFUL = ("id", "name", "type", "provider_id", "base_url", "app_type",
                "enabled", "features", "balance_kind", "note")
_CCSW_FEATURES = ("traffic", "balance")
_CCSW_SCAN_ONLY = ("is_local", "has_token", "usage_script", "settings_config",
                   "accessToken", "userId", "script_code", "meta")


def _parse_usage_code(code):
    if not code or not isinstance(code, str):
        return {}
    url = None
    m = re.search(r"url\s*:\s*[`\"']([^`\"']+)", code)
    if m:
        url = m.group(1)
    low = code.lower()
    kind = None
    if "/api/user/self" in low:
        kind = "newapi"
    elif "/api/usage/token" in low:
        kind = "newapi_sk"
    elif "/user/balance" in low:
        kind = "generic_user_balance"
    elif "/v1/usage" in low:
        kind = "generic_v1_usage"
    elif "/api/usage/account" in low:
        kind = "generic_usage_account"
    return {"url": url, "kind": kind}


def _ccsw_usage_summary(meta, cfg, app_type):
    """usage_script 只提炼功能类别，不返回令牌明文。"""
    script = meta.get("usage_script") if isinstance(meta, dict) else None
    tmpl = None
    code = ""
    script_on = False
    if isinstance(script, dict):
        tmpl = script.get("templateType") or script.get("template_type")
        code = script.get("code") or ""
        script_on = bool(script.get("enabled", True)) and bool(code or tmpl)
    parsed = _parse_usage_code(code)
    kind = "none"
    if script_on:
        if tmpl == "newapi" or parsed.get("kind") in ("newapi", "newapi_sk"):
            kind = "newapi"
        elif tmpl == "balance":
            kind = "official_balance"
        elif tmpl == "general" or parsed.get("kind") in (
                "generic_user_balance", "generic_v1_usage", "generic_usage_account"):
            kind = "generic"
        elif parsed.get("kind"):
            kind = "generic"
    has_creds = False
    if isinstance(script, dict) and script.get("accessToken") is not None:
        has_creds = True
    if _provider_token(app_type, cfg):
        has_creds = True
    return {
        "templateType": tmpl,
        "script_enabled": script_on,
        "balance_kind": kind,
        "url": parsed.get("url"),
        "has_creds": has_creds,
        "can_balance": bool(kind != "none" and has_creds),
        "script_keys": sorted(script.keys()) if isinstance(script, dict) else [],
    }


def ccswitch_balance_source(provider_id):
    """余额开启时才调用：只读 CC Switch 取凭据，不写入浮窗配置。"""
    if not provider_id:
        return None
    for pid, app_type, _name, cfg, meta in _iter_ccswitch_full():
        if pid != provider_id:
            continue
        script = meta.get("usage_script") if isinstance(meta, dict) else None
        if not isinstance(script, dict) or not script.get("enabled", True):
            return None
        tmpl = script.get("templateType") or ""
        code = script.get("code") or ""
        parsed = _parse_usage_code(code)
        api_key = _provider_token(app_type, cfg) or ""
        access = script.get("accessToken") or ""
        user_id = script.get("userId")
        raw_base = (script.get("baseUrl") or _provider_base(cfg) or "").rstrip("/")
        if tmpl == "newapi" or parsed.get("kind") in ("newapi", "newapi_sk"):
            if not access:
                return None
            base = raw_base[:-3] if raw_base.endswith("/v1") else raw_base
            return {"kind": "newapi", "base_url": base, "access_token": access,
                    "user_id": str(user_id if user_id is not None else ""),
                    "divisor": 500000, "unit": "CNY"}
        if tmpl == "balance":
            base = raw_base or "https://openrouter.ai/api/v1"
            return {"kind": "openrouter", "api_key": api_key, "base_url": base}
        url = (parsed.get("url") or "").replace("{{baseUrl}}", raw_base)
        if not url:
            return None
        headers = {"Authorization": "Bearer " + (api_key or access)}
        if "/api/usage/account" in url:
            paths = {"remaining": ["data.balance", "balance"],
                     "unit": ["data.currency", "currency"]}
        elif "/v1/usage" in url:
            paths = {"remaining": ["remaining", "quota.remaining", "balance"],
                     "unit": ["currency", "unit"]}
        else:
            paths = {"remaining": ["data.balance", "balance", "remaining", "quota"],
                     "unit": ["data.currency", "currency", "unit"]}
        return {"kind": "generic", "url": url, "headers": headers,
                "json_paths": paths, "unit": "CNY"}
    return None


def account_is_active(acc):
    return acc.get("enabled") is not False


def ensure_ccsw_schema():
    # 补齐 enabled/features，清掉扫描期无用字段
    rel = account_file_for("ccsw")
    accs = read_accounts(rel)
    changed = False
    for a in accs:
        if "enabled" not in a:
            a["enabled"] = True
            changed = True
        if "features" not in a:
            a["features"] = ["traffic"]
            changed = True
        else:
            feats = a.get("features")
            if not isinstance(feats, list):
                feats = [feats] if feats else ["traffic"]
            cleaned = [f for f in feats if f in _CCSW_FEATURES]
            a["features"] = cleaned or ["traffic"]
            if cleaned != feats:
                changed = True
        for k in list(a.keys()):
            if k in _CCSW_SCAN_ONLY:
                a.pop(k, None)
                changed = True
        if a.get("type") != "ccsw":
            a["type"] = "ccsw"
            changed = True
    # 刷新线程可能读到删除前的旧数组: 回写前把已拉黑的行剔掉, 否则会把刚删的又写回来。
    # 用了 set_ignored 的删除在旧代码下会留下「已拉黑却还存在」的行, 这里顺手收干净。
    ign = ignored_sets().get("ccsw") or set()
    kept = [a for a in accs if (a.get("provider_id") or "") not in ign]
    if len(kept) != len(accs):
        accs = kept
        changed = True
    if changed:
        write_accounts(rel, accs)
    return changed


def prepare_account_for_fetch(acc):
    acc = dict(acc)
    if acc.get("type") == "ccsw":
        feats = acc.get("features") or ["traffic"]
        if "balance" in feats:
            acc["_balance_src"] = ccswitch_balance_source(acc.get("provider_id"))
        else:
            acc.pop("_balance_src", None)
    return acc


def ccsw_scan(include_local=False):
    """列出节点 + 有用/无用参数 + 导入/启用状态，供确认后再开。"""
    ensure_ccsw_schema()
    imported = {a.get("provider_id"): a for a in read_accounts(account_file_for("ccsw"))
                if a.get("provider_id")}
    ign = ignored_sets().get("ccsw") or set()
    importable_list, local_list, skipped_list = [], [], []
    for pid, app_type, name, cfg, meta in _iter_ccswitch_full():
        base = _provider_base(cfg)
        token = _provider_token(app_type, cfg)
        usage = _ccsw_usage_summary(meta, cfg, app_type)
        is_local = bool(base) and any(x in base for x in ("127.0.0.1", "://localhost", "://[::1]"))
        is_official = (not base) or str(pid).endswith("-official")
        ignored_now = bool(pid) and pid in ign
        can_import = bool(base) and not is_local and not is_official and not ignored_now
        useful = ["provider_id", "name", "base_url", "app_type"]
        if can_import:
            useful += ["enabled", "features"]
            if usage.get("can_balance"):
                useful.append("balance_kind")
        suggest_feats = ["traffic"]
        suggest_note = "仅流量（无可用余额脚本）"
        bkind = usage.get("balance_kind") or "none"
        if usage.get("can_balance"):
            suggest_feats = ["traffic", "balance"]
            suggest_note = "可查余额(%s)；features 含 balance 时从 CC Switch 只读凭据" % bkind
        elif bkind != "none" and not usage.get("has_creds"):
            suggest_note = "有脚本但缺凭据，建议只开流量"
        acc = imported.get(pid)
        item = {
            "provider_id": pid,
            "app_type": app_type,
            "name": name,
            "base_url": base or "",
            "has_token": bool(token),
            "is_local": is_local,
            "is_official": is_official,
            "importable": can_import,
            "skip_reason": ("ignored_by_user" if ignored_now else
                            ("local_proxy" if is_local else
                             ("official_or_no_base" if is_official else None))),
            "ignored": ignored_now,
            "useful_params": useful,
            "useless_params": list(_CCSW_SCAN_ONLY),
            "usage": {
                "templateType": usage.get("templateType"),
                "balance_kind": usage.get("balance_kind"),
                "can_balance": usage.get("can_balance"),
                "has_creds": usage.get("has_creds"),
                "url": usage.get("url"),
                "script_enabled": usage.get("script_enabled"),
            },
            "suggest": {
                "enable": can_import,
                "features": suggest_feats,
                "balance_kind": bkind if usage.get("can_balance") else "none",
                "note": suggest_note,
            },
            "imported": bool(acc),
            "account_id": (acc or {}).get("id"),
            "enabled": (acc or {}).get("enabled") if acc else None,
            "features": (acc or {}).get("features") if acc else None,
            "balance_kind": (acc or {}).get("balance_kind") if acc else None,
        }
        if can_import:
            importable_list.append(item)
        elif is_local:
            local_list.append(item)
        else:
            skipped_list.append(item)
    all_nodes = importable_list + local_list + skipped_list
    if not all_nodes and not os.path.isfile(_ccswitch_db()):
        return {"available": False, "message": "未找到 cc-switch.db", "nodes": [],
                "local_nodes": [], "skipped_nodes": [], "all_nodes": []}
    nodes = importable_list + (local_list if include_local else [])
    return {
        "available": True,
        "count": len(nodes),
        "importable_count": len(importable_list),
        "nodes": nodes,
        "all_nodes": all_nodes,
        "local_nodes": local_list,
        "skipped_nodes": skipped_list,
        "remote_count": len(importable_list),
        "ignored": sorted(ign),   # 已删除（拉黑）的 provider_id，不会再被导入
        "useful_param_note": "落盘仅 useful_params；余额凭据查询时只读 CC Switch，不进 ccsw.json",
    }


def ccsw_import(provider_ids=None, enabled=True, features=None):
    """导入 CC-SW。provider_ids=None 导入全部可导入项；否则只导指定项。
    已存在项默认保留原 enabled/features，仅刷新地址类字段。
    """
    scan = ccsw_scan(include_local=False)
    if not scan["available"]:
        return {"ok": False, "error": scan.get("message", "CC-Switch 不可用")}
    want = set(provider_ids) if provider_ids is not None else None
    ign = ignored_sets().get("ccsw") or set()
    if isinstance(features, str):
        features = [features]
    feats_in = [f for f in (features or ["traffic"]) if f in _CCSW_FEATURES] or ["traffic"]
    existing_ids, existing_names = set(), set()
    for rel in all_account_files():
        for a in read_accounts(rel):
            existing_ids.add(a.get("provider_id"))
            existing_names.add(a.get("name"))
    rel = account_file_for("ccsw")
    accs = read_accounts(rel)
    imported = updated = skipped = 0
    imported_ids = []
    source_nodes = scan.get("nodes") or []
    if want is not None:
        # 指定 id 时从 all_nodes 找，仍跳过 local
        source_nodes = [n for n in (scan.get("all_nodes") or []) if n.get("provider_id") in want]
    for node in source_nodes:
        if node.get("is_local") or not node.get("importable", True):
            skipped += 1
            continue
        if not node.get("base_url"):
            skipped += 1
            continue
        if want is not None and node["provider_id"] not in want:
            skipped += 1
            continue
        if node["provider_id"] in ign:
            if want is not None:
                set_ignored("ccsw", node["provider_id"], False)   # 点名要它 = 撤销拉黑
            else:
                skipped += 1
                continue
        hit = next((a for a in accs if a.get("provider_id") == node["provider_id"]), None)
        bkind = (node.get("suggest") or {}).get("balance_kind") or "none"
        if hit:
            hit["name"] = node["name"]
            hit["base_url"] = node["base_url"]
            hit["app_type"] = node["app_type"]
            hit["type"] = "ccsw"
            hit["balance_kind"] = bkind
            if want is not None:
                hit["enabled"] = bool(enabled)
                hit["features"] = list(feats_in)
            else:
                hit.setdefault("enabled", True)
                hit.setdefault("features", ["traffic"])
            updated += 1
            imported_ids.append(hit.get("id"))
            continue
        if node["name"] in existing_names or node["provider_id"] in existing_ids:
            skipped += 1
            continue
        acc = {
            "id": uuid.uuid4().hex[:8],
            "name": node["name"],
            "type": "ccsw",
            "provider_id": node["provider_id"],
            "base_url": node["base_url"],
            "app_type": node["app_type"],
            "enabled": bool(enabled),
            "features": list(feats_in),
            "balance_kind": bkind,
        }
        accs.append(acc)
        existing_names.add(node["name"])
        existing_ids.add(node["provider_id"])
        imported += 1
        imported_ids.append(acc["id"])
    # 落盘前再对一次名单: 扫描期间被删掉的那条不能顺着这次导入写回去
    ign = ignored_sets().get("ccsw") or set()
    accs = [a for a in accs if not ((a.get("provider_id") or "") in ign)]
    write_accounts(rel, accs)
    wake.set()
    return {"ok": True, "imported": imported, "updated": updated, "skipped": skipped,
            "imported_ids": imported_ids,
            "ignored": sorted(ign),   # 前端要区分"全被删除名单拦住"和"真没新节点"
            "total": scan.get("importable_count") or scan.get("count")}


def ccsw_update(payload):
    """确认开启/关闭：按 account id 或 provider_id 更新 enabled / features / name。"""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "请求体无效"}
    acc_id = payload.get("id") or payload.get("account_id")
    pid = payload.get("provider_id")
    if not acc_id and not pid:
        return {"ok": False, "error": "需要 id 或 provider_id"}
    ensure_ccsw_schema()
    rel = account_file_for("ccsw")
    accs = read_accounts(rel)
    hit = None
    for a in accs:
        if acc_id and a.get("id") == acc_id:
            hit = a
            break
        if pid and a.get("provider_id") == pid:
            hit = a
            break
    if not hit:
        # 隐藏项可能本来就不在 ccsw.json 里(删掉时已经落盘撤走了): 只翻隐藏名单
        if pid and "ignored" in payload:
            set_ignored("ccsw", pid, bool(payload.get("ignored")))
            wake.set()
            return {"ok": True, "account": None, "account_id": None}
        return {"ok": False, "error": "未找到 CC-SW 账户"}
    if "enabled" in payload:
        hit["enabled"] = bool(payload["enabled"])
    if "features" in payload:
        feats = payload["features"]
        if isinstance(feats, str):
            feats = [feats]
        cleaned = [f for f in (feats or []) if f in _CCSW_FEATURES]
        hit["features"] = cleaned or ["traffic"]
    if payload.get("name"):
        hit["name"] = str(payload["name"]).strip()
    if "balance_kind" in payload:
        hit["balance_kind"] = payload.get("balance_kind") or "none"
    # 隐藏名单与"启用"是两回事: 展示隐藏项时一并撤销拉黑, 否则下一轮 load_config 又把它滤掉
    if "ignored" in payload:
        # ignored=True 进隐藏名单, False 展示; on 即"是否拉黑", 别写反
        set_ignored("ccsw", hit.get("provider_id"), bool(payload.get("ignored")))
    write_accounts(rel, accs)
    wake.set()
    pub = {k: hit.get(k) for k in _CCSW_USEFUL if k in hit}
    return {"ok": True, "account": pub, "account_id": hit.get("id")}


def ccsw_hidden():
    """隐藏的 CC-SW: 被删掉的节点没有就此消失, 只是进了隐藏名单。
    这里把名单与 cc-switch 库里现存的节点对回来, 供"隐藏"页里点"展示"恢复。
    名单里已经没有对应节点的(源里被删过)也列出来, 只是没有可恢复的节点信息。
    """
    ensure_ccsw_schema()
    ign = ignored_sets().get("ccsw") or set()
    known = {}
    for pid, app_type, name, cfg, _meta in _iter_ccswitch_full():
        if pid in ign:
            known[pid] = {
                "provider_id": pid, "name": name, "app_type": app_type,
                "base_url": _provider_base(cfg) or "", "has_token": bool(_provider_token(app_type, cfg)),
                "account_id": None,
            }
    for a in read_accounts(account_file_for("ccsw")):
        pid = a.get("provider_id") or ""
        if pid in ign:
            row = known.get(pid) or {"provider_id": pid, "app_type": a.get("app_type") or "",
                                     "base_url": a.get("base_url") or "", "has_token": False}
            row["name"] = a.get("name") or row.get("name") or pid
            row["account_id"] = a.get("id")
            known[pid] = row
    return {"ok": True, "hidden": [known[k] for k in sorted(known)], "count": len(known)}


def ccsw_review():
    """加载参数清单，供确认哪些启用/开余额。"""
    ensure_ids()
    ensure_ccsw_schema()
    scan = ccsw_scan(include_local=True)
    accounts = read_accounts(account_file_for("ccsw"))
    enabled = [a for a in accounts if account_is_active(a)]
    return {
        "ok": True,
        "scan": scan,
        "accounts": accounts,
        "enabled_count": len(enabled),
        "disabled_count": len(accounts) - len(enabled),
        "howto": {
            "import_all": "POST /api/ccsw/import body:{}",
            "import_some": "POST /api/ccsw/import body:{\"provider_ids\":[\"ccapi-...\"],\"enabled\":true}",
            "toggle": "POST /api/ccsw/update body:{\"id\":\"...\",\"enabled\":true,\"features\":[\"traffic\",\"balance\"]}",
            "features": "traffic=本地流量；balance=按脚本只读查远程余额",
            "useless": "is_local/has_token/usage_script/accessToken 仅扫描展示，不落盘",
        },
    }

def _ocx_config_candidates():
    home = os.path.expanduser("~")
    return [
        os.path.join(home, ".ocx", "config.yaml"),
        os.path.join(home, ".codex", "opencodex.config.toml"),
        os.path.join(home, ".codex", "config.toml"),
    ]


def _ocx_base_from_text(text):
    # 优先 model_providers.opencodex/ocx 段，其次键名行，再次 /v1 URL
    for section in ("opencodex", "ocx"):
        m = re.search(
            r"\[model_providers\.%s\][^\[]*?base_url\s*[=:]\s*[\"']?([^\"'\n]+)" % section,
            text, re.S | re.I)
        if m:
            # 只认地址：段里若匹配到非 URL（如校验脚本里的 base_url 变量）就继续往下找，
            # 不能把变量名当地址落盘
            val = m.group(1).strip().strip("\"'").rstrip("/,;")
            if val.startswith(("http://", "https://")):
                return val
    return _pick_ocx_base(text)


def ocx_scan(probe=False):
    # 配置匹配优先：能读到 base_url 就 available=True
    # probe=True 才探测 /v1/models，失败不影响「配置可用」，只改 proxy_online/message
    checked = _checked_config_paths()
    for p in _ocx_config_candidates():
        if not os.path.isfile(p):
            continue
        base = _ocx_base_in_file(p)
        if not base:
            continue
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        result = {
            "available": True,
            "config_found": True,
            "base_url": base,
            "source": p,
            "count": 0,
            "nodes": [],
            "checked": checked,
            "proxy_online": False,
            "message": "已从配置读取地址（不要求代理在线）",
        }
        if probe:
            try:
                resp, _ms = providers._get(base + "/v1/models", timeout=4)
                data = resp.get("data") or []
                result.update(count=len(data), nodes=[d.get("id", "") for d in data][:12],
                              proxy_online=True, message="配置与代理均可用")
            except Exception:
                result["message"] = "配置存在但代理无响应: %s" % base
        return result
    return {"available": False, "config_found": False, "proxy_online": False,
            "message": "未检测到默认路径配置，请确认 OpenCodex/OCX 已安装",
            "checked": checked, "nodes": []}


def _link_ocx_to_ccsw(acc):
    # OCX ↔ CC-SW 配置匹配：host[:port] 相同则挂 provider_id，并采用 CC Switch 显示名
    oh = _url_host(acc.get("base_url"))
    if not oh:
        return acc
    for pid, app_type, name, cfg in _iter_ccswitch_providers():
        base = _provider_base(cfg)
        if base and _url_host(base) == oh:
            acc["linked_provider_id"] = pid
            acc["linked_app_type"] = app_type
            if name:
                acc["name"] = name
            break
    return acc


def _ocx_save_node(base, count, source=None, proxy_online=False):
    # base_url 相同原位更新，不同地址追加（允许多个 OCX 节点）
    if _norm_ocx_base(base) in (ignored_sets().get("ocx") or set()):
        return {"ok": True, "imported": 0, "updated": 0, "skipped": 1, "count": count,
                "base_url": base, "action": "ignored",
                "message": "该地址已删除过，跳过导入"}
    rel = account_file_for("ocx")
    accs = read_accounts(rel)
    for a in accs:
        if a.get("type") == "ocx" and (a.get("base_url") or "").rstrip("/") == base:
            a["base_url"] = base
            a["last_count"] = count
            a["proxy_online"] = bool(proxy_online)
            if source:
                a["source"] = source
            a = _link_ocx_to_ccsw(a)
            write_accounts(rel, accs)
            wake.set()
            return {"ok": True, "imported": 0, "updated": a["id"], "count": count,
                    "base_url": base, "action": "updated", "name": a.get("name"),
                    "linked_provider_id": a.get("linked_provider_id"),
                    "proxy_online": bool(proxy_online)}
    new_id = uuid.uuid4().hex[:8]
    acc = {"id": new_id, "name": "OpenCodex", "type": "ocx", "base_url": base,
           "last_count": count, "proxy_online": bool(proxy_online)}
    if source:
        acc["source"] = source
    acc = _link_ocx_to_ccsw(acc)
    accs.append(acc)
    write_accounts(rel, accs)
    wake.set()
    return {"ok": True, "imported": 1, "count": count, "base_url": base,
            "id": new_id, "action": "created", "name": acc.get("name"),
            "linked_provider_id": acc.get("linked_provider_id"),
            "proxy_online": bool(proxy_online)}


def ocx_import(probe=False):
    scan = ocx_scan(probe=probe)
    if not scan.get("config_found"):
        return {"ok": False, "error": scan.get("message", "未检测到 OCX 配置"),
                "checked": scan.get("checked", [])}
    return _ocx_save_node(scan["base_url"], scan.get("count") or 0,
                          source=scan.get("source"), proxy_online=scan.get("proxy_online"))


def _pick_ocx_base(text):
    # 优先取键名行（base_url/endpoint/url）里的地址，其次以 /v1 结尾的 URL，再次第一个 URL；
    # 配置里没写 /v1 也能认出地址
    for line in text.splitlines():
        if re.match(r"\s*(base[_-]?url|endpoint|url)\s*[=:]", line, re.I):
            m = re.search(r"https?://[^\s\"'<>]+", line)
            if m:
                return m.group(0).rstrip("/,;")
    urls = [u.rstrip("/,;") for u in re.findall(r"https?://[^\s\"'<>]+", text)]
    if not urls:
        return None
    return next((u for u in urls if u.endswith("/v1")), urls[0])


def _checked_config_paths(extra=None):
    # 前端用它显示「查过哪些路径」：默认三条 + 用户手动指定过的那条（落盘在 ocx.json）
    paths = list(_ocx_config_candidates())
    for a in read_accounts(account_file_for("ocx")):
        src = a.get("source")
        if src and src not in paths:
            paths.append(src)
    if extra and extra not in paths:
        paths.append(extra)
    return paths


def _read_config_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _ocx_base_in_file(path):
    # 单个候选文件的地址提取：段内 base_url → 键名行 → 任意 URL。
    # 兜底那步限定在候选文件自己身上，避免从别处猜出地址
    text = _read_config_text(path)
    if not text:
        return None
    return _ocx_base_from_text(text) or _pick_ocx_base(text)


def ocx_import_path(path, probe=False):
    # 手动指定配置文件：提取地址即可落盘；probe 时才要求 OCX 代理在线
    text = _read_config_text(path)
    if text is None:
        return {"ok": False, "error": "无法读取文件: %s" % path}
    base = _ocx_base_from_text(text) or _pick_ocx_base(text)
    if not base:
        return {"ok": False, "error": "文件中未找到可用的地址"}
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    count = 0
    proxy_online = False
    if probe:
        try:
            resp, _ms = providers._get(base + "/v1/models", timeout=4)
            count = len(resp.get("data") or [])
            proxy_online = True
        except Exception:
            proxy_online = False
    return _ocx_save_node(base, count, source=path, proxy_online=proxy_online)


def ocx_import_checked(path, probe=False):
    # checked 路径导入：只接受 /api/ocx/scan 报过的那几条候选（默认路径 + ocx.json 记着的手动来源），
    # 避免这个接口变成任意路径读取器；未知路径退回 ocx_import_path 的事前报错
    known = _checked_config_paths()
    if not path:
        return {"ok": False, "error": "缺少 path", "checked": known}
    if os.path.normcase(os.path.abspath(path)) not in {os.path.normcase(os.path.abspath(p)) for p in known}:
        return {"ok": False, "error": "该路径不在已探测的候选列表里", "checked": known}
    if not os.path.isfile(path):
        return {"ok": False, "error": "文件不存在: %s" % path, "checked": known}
    return ocx_import_path(path, probe=probe)


def ocx_import_configured(probe=True):
    # 手动配置的 OCX 节点（ocx.json 里没有 source 的那些）：地址是用户给的，
    # 不再去猜配置文件，直接按地址探一次，顺手把节点数写回 last_count。
    # probe=False 只做地址可用性判断，不打网络。
    rel = account_file_for("ocx")
    accs = read_accounts(rel)
    ign = ignored_sets().get("ocx") or set()
    done, failed = [], []
    for a in accs:
        if a.get("source"):
            continue   # 这条是从配置文件导进来的，交给 ocx_import_scan 那条路
        if _norm_ocx_base(a.get("base_url")) in ign:
            continue   # 已删除过的地址不再刷
        base = (a.get("base_url") or "").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        if not base:
            failed.append({"id": a.get("id"), "error": "缺少服务器连接"})
            continue
        if not probe:
            done.append({"id": a.get("id"), "base_url": base, "updated": True})
            continue
        try:
            headers = {}
            if a.get("api_key"):
                headers["x-opencodex-api-key"] = a["api_key"]
            resp, _ms = providers._get(base + "/v1/models", headers, timeout=4)
            n = len(resp.get("data") or [])
            a["base_url"] = base
            a["last_count"] = n
            a["proxy_online"] = True
            done.append({"id": a.get("id"), "base_url": base, "count": n, "updated": True})
        except Exception as e:
            a["proxy_online"] = False
            failed.append({"id": a.get("id"), "base_url": base,
                           "error": "服务器无响应: %s" % e})
    if done or failed:
        write_accounts(rel, accs)
        wake.set()
    n_done, n_fail = len(done), len(failed)
    if not probe:
        msg = "手填节点 %d 个（probe=false，只列不探）" % n_done
    elif not n_fail:
        msg = "手填节点 %d 个已刷新" % n_done
    else:
        msg = "%d 个已刷新, %d 个连不上" % (n_done, n_fail)
    return {"ok": n_fail == 0, "updated": n_done, "failed": failed,
            "nodes": done, "count": n_done, "message": msg}


def sync_ocx_ccsw(probe=False):
    """扫描并导入 OCX + CC-SW，再按 CC Switch 当前设置匹配今日流量。"""
    ensure_ids()
    ocx_s = ocx_scan(probe=probe)
    ocx_i = ocx_import(probe=probe)
    ocx_c = ocx_import_configured(probe=probe)
    ccsw_s = ccsw_scan(include_local=True)
    ccsw_i = ccsw_import()
    cfg = load_config()
    traffic = _load_traffic()
    rows = []
    for a in cfg.get("accounts", []):
        rows.append({
            "id": a.get("id"),
            "name": a.get("name"),
            "type": a.get("type"),
            "provider_id": a.get("provider_id") or a.get("linked_provider_id"),
            "base_url": a.get("base_url") or a.get("url"),
            "traffic": _traffic_for(a, traffic),
        })
    return {
        "ocx_scan": ocx_s,
        "ocx_import": ocx_i,
        "ocx_config": ocx_c,
        "ccsw_scan": ccsw_s,
        "ccsw_import": ccsw_i,
        "accounts": rows,
        "traffic": traffic,
        "current": (traffic or {}).get("current") or _ccswitch_settings_current(),
    }


# ---------------- 后台刷新 ----------------

def _refresh_round():
    cfg = load_config()
    ensure_ccsw_schema()
    all_accounts = cfg.get("accounts", [])
    # 未启用的 CC-SW/其它账户不进刷新与 /api/state
    accounts = [a for a in all_accounts if account_is_active(a)]
    try:
        gt = int(cfg.get("timeout"))  # 全局超时；账户自带 timeout 优先，注入只发生在刷新侧
    except (TypeError, ValueError):
        gt = None
    # 用户自定义顺序存在 settings.order 里(全局, 跨文件); 未记录的追加在末尾
    rank = {aid: i for i, aid in enumerate(cfg.get("order") or [])}
    if rank:
        accounts = sorted(accounts, key=lambda a: rank.get(a.get("id"), len(rank)))
    state["settings"] = public_settings(cfg)
    state["accounts"] = [{"id": a.get("id", ""), "name": a.get("name", ""),
                          "type": a.get("type", ""), "enabled": account_is_active(a)} for a in accounts]
    state["loading"] = True

    def one(acc):
        aid = acc.get("id", "")
        try:
            if gt and not acc.get("timeout"):
                acc = dict(acc, timeout=gt)
            acc = prepare_account_for_fetch(acc)
            st = providers.fetch(acc)
            # 每站带上账户 id: 前端据此把站点与账户对齐, 顺序变了也不会错位
            st["id"] = aid
            if st.get("ok"):
                if aid:
                    _last_good[aid] = st
                return st
        except Exception as e:
            st = {"name": acc.get("name", "?"), "ok": False, "remaining": None,
                  "used": None, "total": None, "unit": "", "plan": "",
                  "latency_ms": None, "error": str(e), "updated": time.strftime("%H:%M:%S")}
            st["id"] = aid
        # 失败保留上次成功值：旧值回填继续展示，stale+error 标注真实状态与出错时间
        prev = _last_good.get(aid)
        if prev is not None:
            st = dict(prev, stale=True, error=st.get("error") or "",
                      updated=time.strftime("%H:%M:%S"))
        return st

    stations = list(_FETCH_POOL.map(one, accounts))
    live = {a.get("id") for a in accounts}
    for k in [k for k in _last_good if k not in live]:
        _last_good.pop(k, None)
    traffic = _load_traffic()
    # 这一轮查询期间用户可能改了顺序: 发布前重读一次, 顺序以最新 settings.order 为准
    try:
        order = read_settings().get("order") or cfg.get("order") or []
    except Exception:
        order = cfg.get("order") or []
    if order:
        rank = {aid: i for i, aid in enumerate(order)}
        idx = sorted(range(len(accounts)),
                     key=lambda k: rank.get(accounts[k].get("id"), len(rank)))
        if idx != list(range(len(accounts))):
            accounts = [accounts[k] for k in idx]
            stations = [stations[k] for k in idx]
            state["accounts"] = [{"id": a.get("id", ""), "name": a.get("name", ""),
                                  "type": a.get("type", "")} for a in accounts]
    state["stations"] = stations
    state["traffic"] = traffic
    # 行级今日用量：按 provider_id/名称/主机把 cc-switch 流量挂到对应账户行
    for acc, st in zip(accounts, stations):
        t = _traffic_for(acc, traffic)
        if t:
            st["traffic"] = t
    state["loading"] = False
    ups = [s.get("updated") or "" for s in stations if s]
    state["updated"] = max(ups) if ups else time.strftime("%H:%M:%S")
    return cfg.get("refresh_seconds", 60)


def refresh_loop():
    while True:
        interval = 60
        try:
            interval = _refresh_round() or 60
        except Exception:
            # 配置文件损坏等意外不能让循环线程死掉, 否则 loading 永远为 true 前端一直转圈;
            # 短间隔重试, 用户修好文件后自动恢复
            state["loading"] = False
            interval = 10
        wake.wait(interval)
        wake.clear()


class Handler(BaseHTTPRequestHandler):
    def _drain(self):
        # 提前 return 的分支（来源/令牌不通过）没读请求体。带着未读数据关连接，
        # Windows 会发 RST 而不是 FIN，客户端可能直接 ConnectionAbortedError，
        # 连 403 都读不到。发响应前先把 body 读掉。
        if getattr(self, "_body_read", False):
            return
        self._body_read = True
        n = int(self.headers.get("Content-Length") or 0)
        if n > 0:
            try:
                self.rfile.read(n)
            except OSError:
                pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self._drain()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _check_origin(self):
        # 只放行本机页面；无 Origin 头视为非浏览器客户端（curl 等）照常放行。
        # 仅监听 127.0.0.1 挡不住浏览器，跨域页面会被这里拦下。
        origin = self.headers.get("Origin") or ""
        if not origin:
            return True
        return origin in ("http://127.0.0.1:%d" % _PORT, "http://localhost:%d" % _PORT)

    def _check_token(self):
        # 写操作必须带进程级令牌（静态页注入 <meta> + Bridge.get_api_token 两条通道下发），
        # 挡掉其他网页用 text/plain 简单 POST 触发的跨站写
        return self.headers.get("X-Api-Token") == _API_TOKEN

    def _read_body(self):
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise ValueError("Content-Type 必须是 application/json")
        n = int(self.headers.get("Content-Length") or 0)
        self._body_read = True
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_OPTIONS(self):
        # 预检：本机来源放行并声明允许的头，其余 403
        self.send_response(204 if self._check_origin() else 403)
        if self.headers.get("Origin"):
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:%d" % _PORT)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.end_headers()

    def do_GET(self):
        if not self._check_origin():
            return self._json({"ok": False, "error": "来源不被允许"}, 403)
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._json(state)
        if path == "/api/accounts":
            # 全量账户（含未启用）供编辑回填；凭据掩码。
            # 已删除过的（拉黑）不再出现在列表里
            out = []
            ensure_ccsw_schema()
            ign = ignored_sets()
            for rel in all_account_files():
                for a in read_accounts(rel):
                    if account_ignored(a, ign):
                        continue
                    row = _mask_creds(dict(a, file=rel))
                    row["enabled"] = account_is_active(a)
                    out.append(row)
            return self._json(out)
        if path == "/api/ccsw/scan":
            return self._json(ccsw_scan(include_local="local=1" in self.path))
        if path == "/api/ccsw/review":
            return self._json(ccsw_review())
        if path == "/api/ccsw/hidden":
            return self._json(ccsw_hidden())
        if path == "/api/ocx/scan":
            return self._json(ocx_scan(probe="probe=1" in self.path))
        if path == "/api/ocx/metrics":
            # 整端口合计：今日请求/token/延迟 + 30s 输出速度曲线（读本地账本，不打 OCX）
            return self._json(ocx_metrics.metrics.snapshot())
        if path == "/api/ocx/metrics/config":
            return self._json({"ok": True, "config": ocx_metrics.metrics.config()})
        if path == "/api/generic/presets":
            # 非标准中转站端点的内置模板（url/headers/json_paths），弹窗直接套用
            return self._json(providers.GENERIC_PRESETS)
        if path == "/api/official/models":
            # 官方接口页"主流模型"清单: 标题与字段表在后端, 值是空串等你填
            return self._json(read_models())
        # 静态文件只从 ui/ 目录里取：路径先解码再规范化，落在 ui/ 之外（../configs/newapi.json
        # 这类跨目录读取会把账户凭据明文交出去）一律回落到 index.html
        rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
        fp = os.path.normpath(os.path.join(DIST, rel.replace("/", os.sep)))
        # 页面由 ui/index.tpl.html + ui/parts/* 组装: 改一张卡片只动它自己那个片段。
        # parts/ 只是源片段, 不让浏览器直接取（拼不出完整页, 也没有 api-token 注入）
        tpl = os.path.join(DIST, os.path.basename(pages.TPL)) if pages else ""
        is_page = bool(tpl) and os.path.isfile(tpl) and (
            fp.endswith(os.sep + "index.html") or rel == os.path.basename(tpl))
        inside = fp.startswith(DIST + os.sep)
        if is_page:
            try:
                data = pages.render(DIST).encode("utf-8")
            except Exception as e:
                # 片段写坏时不能整页打不开: 退回磁盘上那份上次组装好的 index.html
                # 但要说一声 —— 改完 theme.json 刷新却没变化, 十有八九就是这里报错了
                sys.stderr.write("页面组装失败, 已退回 ui/index.html: %r\n" % (e,))
                with open(os.path.join(DIST, "index.html"), "rb") as f:
                    data = f.read()
            fp = os.path.join(DIST, "index.html")
        elif inside and os.path.isfile(fp) and not rel.replace(os.sep, "/").startswith("parts/"):
            with open(fp, "rb") as f:
                data = f.read()
        else:
            # 越界路径或 parts/ 一律回落到整页, 别把片段或 ui/ 外的东西当成静态资源发出去
            fp = os.path.join(DIST, "index.html")
            with open(fp, "rb") as f:
                data = f.read()
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".json": "application/json; charset=utf-8",
                 ".woff2": "font/woff2"}.get(os.path.splitext(fp)[1], "application/octet-stream")
        if fp.endswith("index.html"):
            # 把进程级 API 令牌注入页面，前端读 meta 后放进 X-Api-Token 头
            meta = b'<meta name="api-token" content="' + _API_TOKEN.encode() + b'">'
            marker = b"</head>"
            data = data.replace(marker, meta + marker, 1) if marker in data else data + meta
        self._send(200, data, ctype)

    def do_POST(self):
        if not self._check_origin():
            return self._json({"ok": False, "error": "来源不被允许"}, 403)
        if not self._check_token():
            return self._json({"ok": False, "error": "缺少有效的 API 令牌"}, 403)
        path = self.path.split("?")[0]
        try:
            body = self._read_body()
        except (ValueError, KeyError) as e:
            return self._json({"ok": False, "error": "请求体不是合法 JSON(%s)" % e}, 400)
        try:
            if path == "/api/account/save":
                return self._json(save_account(body.get("account") or body))
            if path == "/api/account/delete":
                ids = body.get("ids")
                if ids is None:   # 旧调用方仍可单条删
                    return self._json(delete_account(body.get("id", "")))
                return self._json(delete_accounts([str(x) for x in ids if x]))
            if path == "/api/account/reorder":
                return self._json(reorder_accounts(body.get("ids") or []))
            if path == "/api/account/test":
                acc = body.get("account") or body
                err = validate_account(acc, for_test=True)
                if err:
                    return self._json({"ok": False, "error": err})
                to = body.get("timeout") or read_settings().get("timeout")
                if to and not acc.get("timeout"):
                    acc = dict(acc, timeout=to)
                return self._json(providers.fetch(prepare_account_for_fetch(acc)))
            if path == "/api/settings":
                patch, err = sanitize_settings(body)
                if err:
                    return self._json({"ok": False, "error": err}, 400)
                s = write_settings(patch)
                wake.set()
                return self._json({"ok": True, "settings": public_settings(s)})
            if path == "/api/official/models/save":
                return self._json(save_model_fields(body.get("key", ""), body.get("fields") or {}))
            if path == "/api/ccsw/import":
                return self._json(ccsw_import(
                    provider_ids=body.get("provider_ids"),
                    enabled=body.get("enabled", True),
                    features=body.get("features"),
                ))
            if path == "/api/ccsw/update":
                return self._json(ccsw_update(body))
            if path == "/api/ccsw/review":
                return self._json(ccsw_review())
            if path == "/api/ocx/import":
                return self._json(ocx_import(probe=bool(body.get("probe"))))
            if path == "/api/ocx/import_path":
                return self._json(ocx_import_path(body.get("path", ""), probe=bool(body.get("probe"))))
            if path == "/api/ocx/import_checked":
                # 用户从 /api/ocx/scan 的 checked 列表里挑一个候选路径去试，逐个读、不过 search
                return self._json(ocx_import_checked(body.get("path", ""), probe=bool(body.get("probe"))))
            if path == "/api/ocx/ccsw_sync":
                return self._json(sync_ocx_ccsw(probe=bool(body.get("probe"))))
            if path == "/api/ocx/metrics/config":
                # {interval_seconds?, window_seconds?, enabled?} 自调节轮询，避免过频
                ok, info = ocx_metrics.metrics.set_config(
                    interval=body.get("interval_seconds", body.get("interval")),
                    window=body.get("window_seconds", body.get("window")),
                    enabled=body.get("enabled"),
                )
                return self._json({"ok": ok, "config": info if ok else None,
                                   "error": None if ok else info})
        except Exception as e:
            return self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)
        self._json({"ok": False, "error": "未知接口: %s" % path}, 404)

    def log_message(self, *a):
        pass


class Bridge:
    # JS → Python 窗口控制（无边框拖动）
    def get_api_token(self):
        # 前端取本机 API 写操作令牌的第二通道（与 index.html 注入的 meta 同值）
        return _API_TOKEN

    def get_pos(self):
        w = webview.windows[0]
        return {"x": w.x, "y": w.y}

    def move_to(self, x, y):
        webview.windows[0].move(int(x), int(y))

    def resize(self, w, h, radius=16):
        # UI 上报卡片的逻辑尺寸与圆角半径, 这里换算成物理像素同步执行。
        # js_api 从 .NET 线程池线程进入, WinForms 操作必须编组回 UI 线程。
        try:
            w = max(200, int(w))
            # 高度下限只防 0/负数这种脏值, 不能压到 100: 收起态只有一行磁贴时
            # 卡片实际约 79px 高, 窗口被卡在 100 就比卡片高出一截, 多出来的部分
            # 露出窗口黑底, 看着就是卡片下面一道黑边。窗口尺寸跟随 UI 上报值,
            # Python 不额外加下限。
            h = max(1, int(h))
            form = webview.windows[0].native
            if not form:
                return
            from System import Action
            act = Action(lambda: self._apply_resize(form, w, h, radius))
            if form.InvokeRequired:
                form.Invoke(act)
            else:
                act()
        except Exception:
            pass

    def ready(self):
        apply_window_finish(webview.windows[0])

    def minimize(self):
        # 最小化到任务栏（原生最小化，非销毁）。
        try:
            form = webview.windows[0].native
            if form:
                from System import Action
                from System.Windows.Forms import FormWindowState
                def _min():
                    form.WindowState = FormWindowState.Minimized
                act = Action(_min)
                if form.InvokeRequired:
                    form.Invoke(act)
                else:
                    _min()
        except Exception:
            pass

    def set_opacity(self, alpha):
        # 透明度调节接口：alpha 取 0-255。只重设分层 Alpha，不改 Opacity 属性。
        try:
            a = max(0, min(255, int(alpha)))
            form = webview.windows[0].native
            if not form:
                return
            hwnd = int(form.Handle.ToInt64())
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, a, 2)
        except Exception:
            pass

    def pick_file(self):
        # 打开原生文件选择框，返回所选路径或空串（OCX 手动指定路径用）
        try:
            res = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False)
            return (res[0] if res else "") or ""
        except Exception:
            return ""

    def _apply_resize(self, form, w, h, radius=16):
        size = (int(w), int(h), int(round(float(radius or 0))))
        if getattr(form, "_float_last_size", None) == size:
            return
        form._float_last_size = size
        scale = getattr(form, "_scale", 1) or 1
        hwnd = int(form.Handle.ToInt64())
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, int(w * scale), int(h * scale), 0x2 | 0x4)
        # 尺寸变化只更新裁剪区域, 不重复设置窗口 Alpha 或 WebView2 属性。
        _apply_round_region(form, radius)

    def refresh(self):
        wake.set()
        return True

    def open_configs(self):
        path = CONFIG_DIR if os.path.isdir(CONFIG_DIR) else HERE
        try:
            os.startfile(path)
            return True
        except Exception:
            return False

    def close(self):
        webview.windows[0].destroy()


def main():
    global _PORT
    if "--check" in sys.argv:
        # 跟浮窗共用一份合并配置与必填表，避免两处口径漂移
        try:
            ok, msgs = _check(load_config())
        except Exception as e:
            ok, msgs = False, ["配置加载失败: %s" % e]
        print("\n".join(msgs))
        print("CHECK %s" % ("OK" if ok else "FAIL"))
        sys.exit(0 if ok else 1)
    if webview is None:
        raise RuntimeError("未安装 pywebview（import webview），无法启动浮窗窗口")
    port = 8765
    for a in sys.argv[1:]:
        if a.isdigit():
            port = int(a)
            break
    # 重复启动检测：扫描端口区间内是否已有浮窗实例（顺延过端口的实例也能探到），
    # 否则 pythonw 下第二个实例只会无声无息地崩掉或开出两个窗口
    for q in range(port, port + 11):
        try:
            resp, _ms = providers._get("http://127.0.0.1:%d/api/state" % q, timeout=1)
            if isinstance(resp, dict) and "stations" in resp:
                ctypes.windll.user32.MessageBoxW(
                    0, "悬浮窗已在运行（端口 %d）。" % q, "Balance Float", 0x40)
                return
        except Exception:
            continue
    # 端口被其他程序占用时向后顺延尝试；全占用则弹提示，避免异常直接退出无任何痕迹
    srv = None
    for p in range(port, port + 11):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        ctypes.windll.user32.MessageBoxW(
            0, "端口 %d-%d 均被占用，无法启动本地服务。" % (port, port + 10), "Balance Float", 0x10)
        return
    # _PORT 必须在 refresh_loop / serve_forever 之前落定：_refresh_round → public_settings
    # 会把 _PORT 当端口发给前端，_check_origin 也按它放行页面请求，顺序反了两处都会错位
    _PORT = port
    ensure_ids()
    threading.Thread(target=refresh_loop, daemon=True).start()
    # OCX 指标：只读 usage.jsonl 的后台轮询（间隔可调，默认不请求 OCX HTTP）
    try:
        ocx_metrics.metrics.start()
    except Exception:
        pass
    state["settings"] = public_settings()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    win = webview.create_window(
        "Balance Float",
        f"http://127.0.0.1:{port}/",
        js_api=Bridge(),
        width=380, height=450, frameless=True, on_top=True,
        background_color="#0d0d0d",
        # shadow=False: 关掉 pywebview 默认的 DWM 窗口阴影与扩展边框。
        # 它会在窗口矩形外再画一圈系统投影, 被窗口边界硬切成四条直角边。
        shadow=False,
        # min_size 必须手动调低: pywebview 默认 (200, 100), 它会作为 WinForms 的
        # MinimumSize 写在窗口上, 窗口因此永远不可能矮于 100。收起态只剩一行磁贴时
        # 卡片只有约 78px 高, 窗口被这个下限顶在 100, 下面多出的 22px 就是露出来的
        # 窗口黑底 —— 即底边那道黑边。宽度下限 200 有意义(卡片最窄也在这个量级),
        # 高度下限只留一个防呆值, 实际高度一律跟随 UI 上报。
        min_size=(200, 60),
    )

    # hidden=True 在 pywebview 6.2.1 内部会 Show/Hide 一次。改为仅让首次 Show 全透明，
    # React 首帧完成后再恢复最终 Alpha，初始化画布因此不会出现在桌面上。
    win.events.before_show += hide_initial_frame
    webview.start(private_mode=False,
                  icon=ICON if os.path.isfile(ICON) else None)


if __name__ == "__main__":
    main()

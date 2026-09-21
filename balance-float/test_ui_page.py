# -*- coding: utf-8 -*-
"""接入页自检: 静态结构 + 可选的真浏览器端到端。

用法:
  python -X utf8 test_ui_page.py          # 静态检查(无依赖, 秒级)
  python -X utf8 test_ui_page.py --live   # 追加 Chrome headless 端到端(需要 websocket-client)
只用 assert, 无框架；临时目录里跑, 不碰真实 configs/
"""
import html.parser
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}
# 这些标签在 HTML 里可以省略闭合, 解析器补上时不当作错误
OPTIONAL_CLOSE = {"p", "li", "option", "td", "th", "tr", "thead", "tbody", "dt", "dd"}


class Nest(html.parser.HTMLParser):
    """只做一件事: 记录标签配平, 收尾时还剩没闭合的标签就报出来。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.bad = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.bad.append("多余的 </%s> 在第 %d 行" % (tag, self.getpos()[0]))
            return
        top, pos = self.stack.pop()
        if top != tag:
            self.bad.append("</%s> 在第 %d 行与 <%s>(第 %d 行)不匹配" % (tag, self.getpos()[0], top, pos[0]))


def read_html():
    # 页面现在由 ui/index.tpl.html + ui/parts/* 组装。自检必须针对组装后的整页,
    # 否则改片段忘了同步 index.html 时, 检查的还是过期的旧页。
    import pages
    return pages.render()


def dom_ids(src):
    return set(re.findall(r'\sid="([^"]+)"', src))


def js_lookup_ids(src):
    """页面 JS 会去 DOM 里找的那些 id。id 改名后忘了同步这里, 就是上一版页面渲染成空壳的原因。"""
    pats = (r'\$\("([A-Za-z][\w-]*)"\)',
            r"\$\('([A-Za-z][\w-]*)'\)",
            r'getElementById\("([A-Za-z][\w-]*)"\)',
            r'el_show\("([A-Za-z][\w-]*)"')
    out = set()
    for p in pats:
        out.update(re.findall(p, src))
    assert len(out) > 20, "没抓到页面 id 引用, 正则该更新了: %s" % sorted(out)
    return out


def test_nesting(src):
    n = Nest()
    n.feed(src)
    assert not n.bad, n.bad
    left = [t for t, _ in n.stack if t not in OPTIONAL_CLOSE]
    assert not left, "未闭合: %s" % left


def test_page_ids_exist(src):
    have, used = dom_ids(src), js_lookup_ids(src)
    # 表单/设置里的步进器是 JS 运行时才插进 DOM 的, 只能从生成它的调用里认领
    dynamic = set(re.findall(r'stepCard\("([A-Za-z][\w-]*)"', src))
    dynamic |= set(re.findall(r'blobCard\("([A-Za-z][\w-]*)"', src))
    missing = sorted(used - have - dynamic)
    assert not missing, "JS 引用了不存在的 id: %s" % missing
    # 接入页那套 page* 必须自洽: 模板里剩下的 pg* 只有动态生成按钮和设置步进器
    page_used = {i for i in used if i.startswith("page")}
    assert len(page_used) >= 8, sorted(page_used)


def test_tabs_match_parts(src):
    # 页签 data-kind 必须是 PARTS 里真的有的键, 否则点进去是空白页
    parts = set(re.findall(r'^\s{4}(\w+):\s*\{[^}]*types:', src, re.M))
    assert parts, "没解析到 PARTS"
    seg = re.search(r'id="pageTabs">(.*?)</div><div class="flex-1', src, re.S)
    assert seg, "没找到 #pageTabs"
    kinds = set(re.findall(r'data-kind="(\w+)"', seg.group(1)))
    assert kinds, kinds
    assert kinds <= parts, "页签多出 PARTS 里没有的: %s" % sorted(kinds - parts)
    forms = set(re.findall(r'^\s{4}(\w+):\s*\{ types:', src.split("var FORMS =")[1], re.M))
    assert kinds <= forms, "页签没有对应表单定义: %s" % sorted(kinds - forms)


def test_no_legacy_entry(src):
    # 后端早就并进 float_window.py, 页面不该再指向 main.py 或旧的独立入口
    for bad in ("main.py", "index_old.html"):
        assert bad not in src, "残留旧入口引用: %s" % bad


def test_template_size(src):
    # 接入页卡片沿用模板配置弹窗的 360x420 (模板实测 360x423, 高度取整); 基准值不能悄悄跑掉
    assert 'id="pageWrap"' in src
    seg = re.search(r'id="pageWrap".*?ios-glass-card[^>]*style="([^"]*)"', src, re.S)
    assert seg, "pageWrap 卡片没有内联基准尺寸"
    assert "360px" in seg.group(1) and "420px" in seg.group(1), seg.group(1)
    # fitPage 的夹紧上限必须与内联基准一致, 否则屏幕稍小就会被悄悄改小
    fit = re.search(r"function fitPage\(\).*?reportSize\(\);", src, re.S)
    assert fit, "没找到 fitPage"
    assert "Math.min(360" in fit.group(0) and "Math.min(420" in fit.group(0), fit.group(0)


def live():
    """真 Chrome headless 跑一遍: 展开 -> 加号 -> NewAPI 页 -> 新增 -> 保存 -> 退出。"""
    import shutil
    import socket
    import subprocess
    import tempfile
    import threading
    import time
    import urllib.request

    try:
        import websocket
    except ImportError:
        print("SKIP --live: 未安装 websocket-client"); return
    chrome = os.environ.get("CHROME") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.isfile(chrome):
        print("SKIP --live: 没找到 Chrome"); return

    import float_window as fw

    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

    tmp = tempfile.mkdtemp(prefix="bf_live_")
    prof = tempfile.mkdtemp(prefix="bf_prof_")   # Chrome 档案放外面, 否则它的 *.json 会被当成账户文件
    fw.CONFIG_DIR = tmp; fw.DIST = os.path.join(HERE, "ui"); fw._API_TOKEN = "tok-for-live"
    fw.write_accounts("newapi.json", [{"id": "n1", "name": "Moniker", "type": "newapi",
                                       "base_url": "https://one.example", "access_token": "sk-real-1234"}])
    fw.write_accounts("ocx.json", [{"id": "o1", "name": "OCX", "type": "ocx",
                                    "base_url": "http://127.0.0.1:1",
                                    "api_key": "ocx_data_seed"}])
    port = free_port(); fw._PORT = port
    srv = fw.ThreadingHTTPServer(("127.0.0.1", port), fw.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    dbg = free_port()
    proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                             "--no-default-browser-check", "--user-data-dir=" + prof,
                             "--remote-debugging-port=%d" % dbg, "--remote-allow-origins=*", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        ver = None
        for _ in range(150):
            try:
                ver = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json/version" % dbg, timeout=2)); break
            except Exception:
                time.sleep(0.2)
        assert ver, "devtools 未就绪"
        ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=60)
        nid = [0]

        def send(method, params=None, session=None):
            nid[0] += 1
            msg = {"id": nid[0], "method": method, "params": params or {}}
            if session:
                msg["sessionId"] = session
            ws.send(json.dumps(msg))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == nid[0]:
                    if "error" in r:
                        raise RuntimeError(method + ": " + json.dumps(r["error"]))
                    return r.get("result", {})

        tid = send("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        send("Page.enable", session=sid); send("Runtime.enable", session=sid)
        send("Page.addScriptToEvaluateOnNewDocument", {"source":
             "window.__err=[];window.addEventListener('error',function(e){window.__err.push(String(e.message))});"},
             session=sid)
        send("Page.navigate", {"url": "http://127.0.0.1:%d/?rt=1" % port}, session=sid)

        def ev(expr):
            r = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, session=sid)
            if r.get("exceptionDetails"):
                return "EXC " + str(r["exceptionDetails"].get("exception", {}).get("description", "?"))[:160]
            return r.get("result", {}).get("value")

        def wait_for(expr, want=True, timeout=90.0):
            # DOMContentLoaded 会被 Google Fonts 样式表阻塞, 不能拿固定 sleep 等启动
            t0 = time.time()
            while time.time() - t0 < timeout:
                if ev(expr) == want:
                    return True
                time.sleep(0.25)
            return False

        def ck(expr, want, why):
            got = ev(expr)
            assert got == want, "%s: got=%r want=%r" % (why, got, want)

        assert wait_for("!!document.body && document.body.className.indexOf('is-collapsed')>=0"), ev("document.body.className")
        ev("document.getElementById('btnAdd').click()")
        assert wait_for("document.body.classList.contains('is-page')"), "is-page 未生效"
        ck("getComputedStyle(document.getElementById('pageWrap')).display", "block", "接入页没显示")
        ck("[getComputedStyle(document.getElementById('collapsedWrap')).display,"
           "getComputedStyle(document.getElementById('expandedWrap')).display]", ["none", "none"], "收起/展开没让位")
        ck("(function(){var c=document.querySelector('#pageWrap .ios-glass-card');return c.offsetWidth+'x'+c.offsetHeight})()",
           "360x420", "接入页没按模板尺寸渲染")
        ck("document.getElementById('pageTitle').textContent", "官方接口配置", "标题不对")
        ck("document.getElementById('pageTabs').querySelector('.bg-white').getAttribute('data-kind')",
           "official", "默认页签不是官方接口(最上面那个)")
        # 官方接口排在 NewAPI 前面; NewAPI 仍旧照原样可进可填
        ev("document.querySelector('#pageTabs [data-kind=\"newapi\"]').click()")
        assert wait_for("document.querySelectorAll('#pageList [data-add=\"newapi\"]').length===1"), "NewAPI 页签没进去"
        ck("document.getElementById('pageTitle').textContent", "NewAPI 配置", "切页签后标题没跟上")
        ck("getComputedStyle(document.getElementById('pageBtns').querySelector('.material-symbols-outlined')).fontFamily",
           '"Material Symbols Outlined"', "图标没走字体")
        ck("document.querySelectorAll('#pageList [data-acc]').length", 1, "既有账户没进列表")
        ck("document.getElementById('pageList').textContent.indexOf('sk-real-1234')<0", True, "列表漏了明文令牌")
        ev("document.getElementById('pageList').querySelector('[data-add]').click()")
        assert wait_for("getComputedStyle(document.getElementById('pageForm')).display==='flex'"), "新增表单没展开"
        ck("[].map.call(document.querySelectorAll('#pageFields input'),function(i){return i.id}).length",
           4, "NewAPI 必填项不是 4 个")
        ck("[].map.call(document.querySelectorAll('#pageExtras input'),function(i){return i.id}).length",
           3, "高级区字段不是 3 个")
        # 表单比列表长: 尺寸必须钉死在模板尺寸上, 由表单区自己滚动, 不能把窗口撑大
        ck("(function(){var c=document.querySelector('#pageWrap .ios-glass-card');return c.offsetWidth+'x'+c.offsetHeight})()",
           "360x420", "表单态把窗口撑大了")
        # 接入页尺寸与收起/展开态无关: 卡片自带 360x420, 不受那两态影响
        ck("(function(){var c=document.querySelector('#pageWrap .ios-glass-card');"
           "var cs=getComputedStyle(c);return cs.width+'|'+cs.height})()",
           "360px|420px", "接入页尺寸跟着别的态跑了")
        ck("document.getElementById('pageForm').scrollHeight>document.getElementById('pageForm').clientHeight",
           True, "表单没溢出, 那条'内部滚动'的断言就失去意义了")
        ev("document.getElementById('pgF_name').value='只填了名称'")
        ev("document.querySelectorAll('#pageBtns button')[2].click()")
        assert wait_for("document.getElementById('pageMsg').textContent.indexOf('保存失败')===0"), "缺必填没被拦"
        names = [a.get("name") for a in fw.read_accounts("newapi.json")]
        assert names == ["Moniker"], "缺必填的账户竟然落盘了: %r" % names
        ev("document.getElementById('pgF_name').value='端到端测'")
        ev("document.getElementById('pgF_base_url').value='http://127.0.0.1:%d'" % port)
        ev("document.getElementById('pgF_access_token').value='sk-new-9999'")
        ev("document.getElementById('pgF_user_id').value='7'")
        ev("document.querySelectorAll('#pageBtns button')[2].click()")
        assert wait_for("getComputedStyle(document.getElementById('pageList')).display==='flex'"), "保存后没回列表"
        names = [a.get("name") for a in fw.read_accounts("newapi.json")]
        assert names == ["Moniker", "端到端测"], names
        assert [a.get("access_token") for a in fw.read_accounts("newapi.json") if a.get("name") == "Moniker"] == ["sk-real-1234"], "旧凭据被覆盖"
        # 官方页签: 常用服务商选块(品牌图标)直进表单
        ev("document.querySelector('#pageTabs [data-kind=\"official\"]').click()")
        assert wait_for("document.querySelectorAll('#pageList [data-add]').length===3"), "官方选块不是 3 个"
        ck("document.querySelector('#pageList [data-add=\"deepseek\"]').textContent.indexOf('DeepSeek')>=0 && !!document.querySelector('#pageList [data-add=\"deepseek\"] span[style]')", True, "官方选块缺名称或品牌图标")
        assert wait_for("document.querySelectorAll('#pageList [data-import]').length===0"), "官方页签不该有一键导入"
        ev("document.querySelector('#pageList [data-add=\"deepseek\"]').click()")
        assert wait_for("!!document.getElementById('pgF_api_key')"), "官方表单没开"
        ck("document.getElementById('pgF_name').value", "DeepSeek", "官方选块没预填名称")
        # 右上角返回: 表单态只退一层回列表, 不能直接退回展开/收起
        ev("document.getElementById('pageClose').click()")
        assert wait_for("getComputedStyle(document.getElementById('pageList')).display==='flex'"), "表单态返回没回列表"
        ck("document.body.classList.contains('is-page')", True, "表单态返回竟然退出了接入页")
        # 主流模型清单: 后端 json 定义标准字段, 页面铺成"标题行 + 输入行"
        n_models = ev("document.querySelectorAll('#pageList [data-model]').length")
        assert n_models and n_models >= 5, "模型清单没渲染: %r" % n_models
        ev("document.querySelector('#pageList [data-model=\"glm-team\"]').click()")
        assert wait_for("!!document.getElementById('pgF_team_url')"), "GLM Team 的 Team 连接字段没铺出来"
        ck("[].map.call(document.querySelectorAll('#pageFields input'),function(i){return i.id}).join(',')",
           "pgF_api_key,pgF_team_id,pgF_team_url,pgF_base_url,pgF_model_id", "模型字段顺序与后端标准表不一致")
        ck("document.querySelectorAll('#pageFields label')[2].textContent.indexOf('Team 连接')>=0",
           True, "第三行的标题行不是 Team 连接")
        ev("document.getElementById('pgF_team_url').value='https://team.example'")
        ev("document.querySelectorAll('#pageBtns button')[1].click()")
        assert wait_for("document.getElementById('pageMsg').textContent.indexOf('已保存')===0"), \
            ev("document.getElementById('pageMsg').textContent")
        saved = [m for m in fw.read_models()["models"] if m["key"] == "glm-team"][0]
        assert saved["fields"]["team_url"] == "https://team.example", saved
        assert saved["fields"]["team_id"] == "", "没填的字段被覆盖了: %r" % saved
        # 模型页也走"只退一层": 回到官方列表, 不退出接入页
        ev("document.getElementById('pageClose').click()")
        assert wait_for("getComputedStyle(document.getElementById('pageList')).display==='flex'"), "模型页返回没回列表"
        ck("document.body.classList.contains('is-page')", True, "模型页返回竟然退出了接入页")
        # 自定义页签: 一个 JSON 文本框, 解析后按后端字段落盘
        ev("document.querySelector('#pageTabs [data-kind=\"generic\"]').click()")
        ev("document.querySelector('#pageList [data-add=\"generic\"]').click()")
        assert wait_for("!!document.getElementById('pgBlob')"), "自定义文本框没开"
        ev("document.getElementById('pgBlob').value='{\"name\":\"自定义测\",\"url\":\"http://127.0.0.1:%d/api\"}'" % port)
        ev("document.querySelectorAll('#pageBtns button')[2].click()")
        assert wait_for("document.getElementById('pageMsg').textContent.indexOf('已新增')===0"), ev("document.getElementById('pageMsg').textContent")
        gnames = [a.get("name") for a in fw.read_accounts("generic.json")]
        assert gnames == ["自定义测"], gnames
        # CC-SW / OCX 列表态有"导入刷新"气泡; CC-SW 仍旧给不了"新增"
        ev("document.querySelector('#pageTabs [data-kind=\"ccsw\"]').click()")
        assert wait_for("document.querySelectorAll('#pageFoot [data-import]').length===1"), "CC-SW 没有导入刷新气泡"
        ck("document.querySelector('#pageFoot [data-import]').textContent.indexOf('导入刷新')>=0", True, "气泡文案不是导入刷新")
        ck("document.querySelectorAll('#pageList [data-add]').length", 0, "CC-SW 不该有新增入口")
        # 气泡与一键删除挂在滚动区之外的页脚, 列表滚动不影响它们
        ck("!!document.querySelector('#pageFoot #pageWipe')", True, "页脚缺一键删除")
        ck("document.querySelector('#pageFoot').parentElement === document.querySelector('#pageList').parentElement", True, "页脚没挂在列表同一层")
        ck("document.querySelectorAll('#pageList [data-import]').length", 0, "气泡还在滚动区里")
        # 删除不是把节点抹掉: 隐藏区收着它们, 展开后按项"展示"放回上面的列表
        assert wait_for("document.querySelectorAll('#pageList [data-hid-toggle]').length===1"), "CC-SW 缺隐藏区"
        ck("document.querySelector('#pageList [data-hid-toggle]').textContent.indexOf('隐藏')>=0", True, "隐藏区标题不对")
        ev("document.querySelector('#pageList [data-hid-toggle]').click()")
        assert wait_for("!!document.querySelector('#pageList [data-hid-toggle] svg, #pageList [data-hid-toggle] .material-symbols-outlined')"),             "隐藏区点了没反应"
        ck("document.querySelector('#pageList [data-hid-toggle]').textContent.indexOf('0')>=0", True,
           "空名单下隐藏区没报出 0 项")
        # 页脚气泡必须真的点得动: 委托只认删除按钮时它是个死按钮(点了毫无反应)
        ev("document.querySelector('#pageFoot [data-import]').click()")
        assert wait_for("document.getElementById('pageMsg').textContent.indexOf('扫描')>=0"), \
            "点导入刷新气泡没触发扫描: " + str(ev("document.getElementById('pageMsg').textContent"))
        assert wait_for("document.getElementById('pageMsg').textContent.indexOf('扫描')<0", timeout=60.0), \
            "扫描没有收尾: " + str(ev("document.getElementById('pageMsg').textContent"))
        ck("document.getElementById('pageMsg').textContent.indexOf('未知错误')", -1,
           "导入刷新报了未知错误: " + str(ev("document.getElementById('pageMsg').textContent")))
        # OCX 是要配置的: 除了一键导入刷新, 列表里还得能手填"服务器连接 + API"
        ev("document.querySelector('#pageTabs [data-kind=\"ocx\"]').click()")
        assert wait_for("document.querySelectorAll('#pageFoot [data-import]').length===1"), "OCX 没有导入刷新气泡"
        ck("document.querySelectorAll('#pageList [data-add=\"ocx\"]').length", 1, "OCX 缺手填新增入口")
        ev("document.querySelector('#pageList [data-add=\"ocx\"]').click()")
        assert wait_for("!!document.getElementById('pgF_base_url')"), "OCX 表单没开"
        ck("[].map.call(document.querySelectorAll('#pageFields input'),function(i){return i.id}).join(',')",
           "pgF_name,pgF_base_url,pgF_api_key", "OCX 表单不是 名称+服务器连接+API")
        ck("document.querySelectorAll('#pageFields label')[1].textContent.indexOf('服务器连接')>=0",
           True, "OCX 的地址行标题不是服务器连接")
        ck("document.querySelectorAll('#pageFields label')[2].textContent.indexOf('*')", -1, "OCX 的 API 密钥不该是必填")
        ck("document.querySelectorAll('#pageFields label')[1].textContent.indexOf('*')>=0", True, "服务器连接没标必填")
        ev("document.getElementById('pgF_api_key').value='ocx_data_live_test'")
        ev("document.querySelectorAll('#pageBtns button')[2].click()")
        assert wait_for("document.getElementById('pageMsg').textContent.indexOf('保存失败')===0"), \
            ev("document.getElementById('pageMsg').textContent")
        assert len(fw.read_accounts("ocx.json")) == 1, "缺服务器连接的 OCX 竟然落盘了"
        ev("document.getElementById('pgF_base_url').value='http://127.0.0.1:1'")
        ev("document.querySelectorAll('#pageBtns button')[2].click()")
        assert wait_for("document.getElementById('pageMsg').textContent.indexOf('已新增')===0"), \
            ev("document.getElementById('pageMsg').textContent")
        cfgd = [a for a in fw.read_accounts("ocx.json") if a.get("api_key")]
        assert [a["api_key"] for a in cfgd if a.get("name") == "OpenCodex"] == ["ocx_data_live_test"], cfgd
        ck("document.querySelectorAll('#pageList [data-acc]').length", 2, "OCX 新增后列表不是两行")
        # 列表态右上角返回: 退回展开态, 不是收起态
        ev("document.getElementById('pageClose').click()")
        assert wait_for("document.body.classList.contains('is-expanded')"), ev("document.body.className")
        ck("document.body.classList.contains('is-page')", False, "列表态返回没退出接入页")
        ck("window.__err.length", 0, "页面有未捕获报错")
        print("test_ui_page --live OK")
    finally:
        if ws is not None:
            ws.close()
        proc.terminate()
        srv.shutdown(); srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(prof, ignore_errors=True)


def main():
    src = read_html()
    test_nesting(src)
    test_page_ids_exist(src)
    test_tabs_match_parts(src)
    test_no_legacy_entry(src)
    test_template_size(src)
    print("test_ui_page OK")
    if "--live" in sys.argv:
        live()


if __name__ == "__main__":
    main()

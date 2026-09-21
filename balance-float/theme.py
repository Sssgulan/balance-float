# -*- coding: utf-8 -*-
"""主题变量: 颜色集中在 ui/theme.json; 片段里写 @color.ink / @shadow.okGlow, 组装时展开。

改一个颜色只动 ui/theme.json —— 组装时现读, 刷新页面即生效, 不用重启浮窗。
组装遇到 theme.json 里没有的变量直接报错, 不会静默拼出一个缺色的页面。

用法: python -X utf8 theme.py --check    # 反查: 颜色 -> 变量名
"""
import io
import json
import os
import re
import sys

# 打包后 __file__ 在解包目录里, 拿它当基准会去读一份只读的主题表: 和 float_window.py
# 一样按 exe 所在目录取, 用户才能改了 exe 旁边的 ui/theme.json 就生效
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "ui", "theme.json")
TOKEN = re.compile(r"@((?:color|shadow|size|motion))\.([A-Za-z0-9_]+)")
GROUPS = ("color", "shadow", "size", "motion")
# size 里只写纯数字, 想带单位就写 @size.pageWpx —— 一个源出两种写法, 免得
# HTML 要 "360px" 而 JS 里的 Math.min 要裸 360 时得维护两份数字
PX_GROUPS = ("size",)


def load(path=None):
    with io.open(path or PATH, encoding="utf-8") as f:
        return json.load(f)


def table(theme=None):
    """摊平成 {"color.ink": "#1d1d1f", "size.pageW": "360", "size.pageWpx": "360px", ...};
    下划线开头的键当注释跳过。size 的每个数字键额外派生一个 <键>px 写法。"""
    t = theme if theme is not None else load()
    out = {}
    for g in GROUPS:
        for k, v in (t.get(g) or {}).items():
            if k.startswith("_"):
                continue
            # re.sub 的回调必须还字符串: json 里的数字要在这里就转掉
            out["%s.%s" % (g, k)] = v if isinstance(v, str) else "%g" % v
            if g in PX_GROUPS and isinstance(v, (int, float)) and not isinstance(v, bool):
                out["%s.%spx" % (g, k)] = "%gpx" % v
    return out


def expand(text, tbl=None):
    # 只能整名替换: 早先按字符串 replace, "@color.ink" 会把 "@color.ink2" 咬掉半截
    tbl = tbl if tbl is not None else table()
    return _expand(text, tbl)


def _expand(text, tbl):
    def one(m):
        k = "%s.%s" % (m.group(1), m.group(2))
        if k not in tbl:
            raise KeyError("theme.json 里没有变量: @%s" % k)
        return tbl[k]

    return TOKEN.sub(one, text)


def scan(ui_dir=None, tpl=None):
    """反查每个颜色的变量名: 值后面挂个名字尾巴再展开一遍, 尾巴落在哪就说明那处写的是谁。

    拿到值的源里没写变量名(裸十六进制), 尾巴就会原样留在结果里, 不会张冠李戴。
    只反查 color: size/motion 的值是 "360"/"380ms" 这类短串, 拿去全页做子串匹配会乱认。
    两个变量同值(ink / kimi)时两边都命中, 所以给的是 "名字/名字", 不是一个名字。
    """
    import pages
    kw = {}
    if ui_dir:
        kw["ui_dir"] = ui_dir
    if tpl:
        kw["tpl"] = tpl
    src = pages.render(expand_theme=False, **kw)
    tbl = dict((k, v) for k, v in table().items() if k.startswith("color."))
    # 源里还有 @size./@motion., 得一起给值; color 那几个额外挂个名字尾巴,
    # 一次展开完, 谁的值上带了尾巴就是谁写的变量
    merged = table()
    merged.update((k, "%s<!--%s-->" % (v, k.replace(".", "-"))) for k, v in tbl.items())
    marked = _expand(src, merged)
    out = dict((v, []) for v in tbl.values())
    for k, v in tbl.items():
        if "<!--%s-->" % k.replace(".", "-") in marked:
            out[v].append(k)
    return dict((v, "/".join(sorted(n)) or None) for v, n in out.items())


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        for v, nm in sorted(scan().items()):
            print("%-9s %s" % (v, nm or "(片段里还是裸色值)"))
        print("共 %d 条变量" % len(table()))
    else:
        sys.stdout.write(json.dumps(load(), ensure_ascii=False, indent=2) + "\n")

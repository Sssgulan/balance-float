# -*- coding: utf-8 -*-
"""页面组装自检。

硬门槛只有一条: ui/index.html 必须就是片段拼出来、主题展开后的结果 ——
运行时读的是它, 改了 ui/parts/ 或 theme.json 忘了重写就会两边不一致。

另外拿 .twtest/index.orig.html (拆分前单文件) 与 .twtest/index.prehead.html
(head 本地化前) 两个历史快照做对照, 只报告偏离了多少字符, 不再断言相等:
拆分当时靠它们证明过无损, 但内容后来有意改过, 逐字节复现已不成立。

用法: python -X utf8 test_pages.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pages  # noqa: E402

ORIG = os.path.join(HERE, ".twtest", "index.orig.html")
PREHEAD = os.path.join(HERE, ".twtest", "index.prehead.html")
PART_NAMES = ("head.html", "collapsed.html", "expanded.html", "modal.html", "page.html")

# 类名里的颜色现在写成命名色(bg-ink / from-accent), 值挂在 tailwind.config 上。
# 比对老快照时要把它还原成 bg-[#1d1d1f] 那种写法。
UTIL = (r"(?:bg|text|border|from|to|via|ring|fill|stroke|divide|placeholder"
        r"|decoration|accent|caret|outline)")

# 本地化改写的一一对应关系, 用来把现在的输出还原成改动前的样子
REWRITES = (
    ("vendor/gfonts.css",
     "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600&amp;"
     "family=Plus+Jakarta+Sans:wght@400;500;600;700&amp;display=swap"),
    ("vendor/icons.css",
     "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:"
     "wght,FILL@100..700,0..1&amp;display=swap"),
    ("vendor/tailwind.js",
     "https://cdn.tailwindcss.com?plugins=forms,container-queries"),
)
DROPPED = ('<link href="https://fonts.googleapis.com" rel="preconnect">'
           '<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect">')


def _unlocalize(head):
    """把 head.html 换回本地化之前的样子: 外网 URL 复原, 两条 preconnect 放回原位。"""
    for local, remote in REWRITES:
        assert head.count(local) == 1, "head.html 里 %s 不是恰好 1 处" % local
        head = head.replace(local, remote)
    anchor = REWRITES[0][1]
    assert head.count(anchor) == 1, "还原后找不到字体 URL, 没法定位 preconnect"
    tag = '<link href="' + anchor
    assert head.count(tag) == 1, "还原后找不到字体 link 标签, 没法定位 preconnect"
    return head.replace(tag, DROPPED + tag)


def _read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def _read_part(name):
    return _read(os.path.join(HERE, "ui", "parts", name))


def _color_map():
    """命名色 -> 色值: {"ink": "#1d1d1f", ...}。值一律小写, 拼写不再重开一条。"""
    import theme
    out = {}
    for k, v in theme.table().items():
        if k.startswith("color."):
            out[k.split(".", 1)[1]] = v.lower()
    return out


# 尺寸/动效变量: 片段里是 @size.pageWpx 这类写法, 老快照里是裸字面量。
# 比对前把两边的写法归一成同一个, 才能继续用逐字节比对守"拆分没改内容"。
def _size_pairs():
    import theme
    # 表里已经同时有 size.pageW(360) 与 size.pageWpx(360px), 各自换成自己的值就行;
    # 先长后短, 免得 @size.pageWpx 被 @size.pageW 咬掉半截
    pairs = [("@%s" % k, v) for k, v in theme.table().items()
             if k.startswith("size.") or k.startswith("motion.")]
    return sorted(pairs, key=lambda p: -len(p[0]))


def _canon(html):
    """"命名色 + tailwind.config 注入"的写法还原成"任意值"的老写法。

    片段换代后 ui/parts/ 与组装结果都是新写法, 拆分前的老快照是旧写法;
    两边都过一遍这个函数, 才能继续用逐字节比对守住"拆分没改内容"。
    """
    cm = _color_map()
    for name, val in cm.items():
        # tailwind.config 里新加的命名色: 老快照里没有, 去掉后两边同构
        html = html.replace(',"%s":"#%s"' % (name, val.lstrip("#")), "")
        html = html.replace(',"%s":"@color.%s"' % (name, name), "")
    for tok, val in _size_pairs():
        html = html.replace(tok, val)
    named = re.compile(r"(?<![\w-])((?:[a-z-]+:)*" + UTIL +
                       r")-(" + "|".join(sorted(cm, key=len, reverse=True)) + r")(/[0-9]+)?")
    return named.sub(lambda m: "%s-[%s]%s" % (m.group(1), cm[m.group(2)], m.group(3) or ""), html)


def test_parts_exist():
    d = os.path.join(HERE, "ui", "parts")
    for name in PART_NAMES:
        fp = os.path.join(d, name)
        assert os.path.isfile(fp), "片段缺失: %s" % name
        assert os.path.getsize(fp) > 200, "片段太小, 多半没切对: %s" % name


def test_template_has_includes():
    tpl = _read(os.path.join(HERE, "ui", pages.TPL))
    for name in PART_NAMES:
        inc = "<!--#include:parts/%s-->" % name
        assert tpl.count(inc) == 1, "模板里 %s 不是恰好 1 处" % inc


def test_no_external_refs():
    # 离线启动是这次拆分的重点目标: 页面不许再碰 CDN
    out = pages.render()
    for bad in ("googleapis", "gstatic", "cdn.tailwindcss", "unpkg", "jsdelivr"):
        assert bad not in out, "组装结果里还有外网引用: %s" % bad
    for good in ("vendor/gfonts.css", "vendor/icons.css", "vendor/tailwind.js"):
        assert good in out, "组装结果缺本地资源: %s" % good


def test_render_no_leftover_directives():
    out = pages.render()
    assert "<!--#include:" not in out, "组装结果里还留着未展开的指令"
    assert out.lstrip().startswith("<!DOCTYPE html>")
    assert out.rstrip().endswith("</html>")
    for el in ('id="collapsedWrap"', 'id="expandedWrap"', 'id="modalWrap"', 'id="pageWrap"'):
        assert el in out, "组装结果缺 %s" % el


def test_include_escape_blocked():
    # 片段路径不许跑出 ui/: 否则 configs/ 里的凭据会被拼进页面
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="bf_pages_")
    with io.open(os.path.join(tmp, pages.TPL), "w", encoding="utf-8") as f:
        f.write("<html><!--#include:../configs/newapi.json--></html>")
    try:
        pages.render(tmp)
    except IOError:
        pass
    else:
        raise AssertionError("include 越界没被拦住")
    shutil.rmtree(tmp, ignore_errors=True)


def _drift(orig_path):
    """把现在的组装结果换个写法后跟历史快照比, 返回 (是否一致, 长度差)。

    两个快照(index.orig = 拆分前单文件, index.prehead = head 本地化前)记的是
    当年那版内容。拆分本身当时靠它们证明无损; 之后内容有意改过, 它们就不再是
    硬门槛了, 只当"偏离了多少"的对照, 免得哪天误以为还能逐字节复现。
    """
    if not os.path.isfile(orig_path):
        return None, 0
    got = _canon(pages.render())
    got = got.replace(_canon(_read_part("head.html")), _canon(_unlocalize(_read_part("head.html"))))
    want = _canon(_read(orig_path))
    return got == want, len(got) - len(want)


def test_render_matches_committed():
    """长期守卫: ui/index.html 必须就是组装结果。

    改了 ui/parts/ 或 theme.json 却忘了跑 pages.py --write, 这一步会当场拦住;
    运行时读的正是 ui/index.html, 不拦就会一边改片段一边生效旧页面。
    """
    got = pages.render()
    assert got == _read(os.path.join(HERE, "ui", "index.html")), \
        "ui/index.html 与组装结果不一致, 跑 python -X utf8 pages.py --write"


def test_no_unexpanded_theme_tokens():
    # 组装后不该再留着 @color./@shadow./@size./@motion.: 留着就是主题表缺了条目
    out = pages.render()
    left = sorted(set(re.findall(r"@(?:color|shadow|size|motion)\.[A-Za-z0-9_]+", out)))
    assert not left, "组装结果里还有没展开的主题变量: %s" % " ".join(left)


def test_theme_typo_raises():
    # 写错变量名必须当场报错, 不能静默漏色
    import theme
    try:
        theme.expand("x @color.nope y")
    except KeyError:
        pass
    else:
        raise AssertionError("未定义的主题变量没被拦住")


# tailwind 自带的调色板族名。命名色一撞上, bg-orange-50 这种就会解析成"命名色+50"而掉色
TAILWIND_STOCK = {
    "inherit", "current", "transparent", "black", "white",
    "slate", "gray", "zinc", "neutral", "stone", "red", "orange", "amber", "yellow",
    "lime", "green", "emerald", "teal", "cyan", "sky", "blue", "indigo", "violet",
    "purple", "fuchsia", "pink", "rose",
}


def test_theme_names_do_not_shadow_tailwind():
    # 踩过一次: 命名色叫 orange/cyan/violet/green/white 时, 行首品牌方块的
    # bg-orange-50/90 全变成透明, 图标后面那圈淡色底就没了
    bad = sorted(set(_color_map()) & TAILWIND_STOCK)
    assert not bad, "命名色撞了 tailwind 自带调色板: %s" % " ".join(bad)


def main():
    test_parts_exist()
    test_template_has_includes()
    test_no_external_refs()
    test_render_no_leftover_directives()
    test_no_unexpanded_theme_tokens()
    test_theme_typo_raises()
    test_theme_names_do_not_shadow_tailwind()
    test_include_escape_blocked()
    test_render_matches_committed()
    drift = []
    for label, path in (("orig", ORIG), ("prehead", PREHEAD)):
        same, delta = _drift(path)
        if same is None:
            drift.append("%s=缺快照" % label)
        elif same:
            drift.append("%s=一致" % label)
        else:
            drift.append("%s=已偏离 %+d 字符" % (label, delta))
    print("test_pages OK (" + ", ".join(drift) + ")")


if __name__ == "__main__":
    main()

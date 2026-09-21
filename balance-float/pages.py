# -*- coding: utf-8 -*-
"""页面组装: 把 ui/index.tpl.html 里的 <!--#include:parts/xxx.html--> 换成片段内容,
再把片段里的 @color.x / @shadow.x 展开成 ui/theme.json 里的值。

拆开写是为了改一个卡片只动一个文件; 组装结果和拆分前的单文件逐字节一致
(test_pages.py 用 ui/parts/ 拼回去跟 .twtest/index.orig.html 比对)。
片段里的相对路径按 ui/ 解析, 所以要能容忍 include 带子目录。
颜色统一放 ui/theme.json: 改一个色只动那一个文件, 组装时现读, 刷新页面即生效。
"""
import io
import os
import re

import theme

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
TPL = "index.tpl.html"
INC = re.compile(r"<!--#include:\s*([^\s>]+?)\s*-->")


def render(ui_dir=None, tpl=TPL, depth=8, expand_theme=True):
    """返回组装好的整页 HTML; 找不到模板、片段或主题变量就抛错, 不静默返回半成品。"""
    root = ui_dir or UI_DIR
    path = os.path.join(root, tpl)
    with io.open(path, encoding="utf-8") as f:
        html = f.read()

    def repl(m, d):
        rel = m.group(1).replace("/", os.sep)
        p = os.path.normpath(os.path.join(root, rel))
        # 片段不许跑出 ui/: 路径穿越会把 configs/ 里的凭据带进页面
        if not p.startswith(root + os.sep) or not os.path.isfile(p):
            raise IOError("片段不存在或越界: %s" % m.group(1))
        with io.open(p, encoding="utf-8") as f:
            return f.read()

    for _ in range(depth):
        if not INC.search(html):
            break
        html = INC.sub(lambda m: repl(m, depth), html)
    else:
        # ponytail: include 嵌套超过 depth 层基本就是写成了环, 直接报错而不是无限展开
        raise IOError("include 嵌套过深(可能成环): %s" % path)
    return theme.expand(html) if expand_theme else html


if __name__ == "__main__":
    import sys
    out = render()
    if "--write" in sys.argv:
        dst = os.path.join(UI_DIR, "index.html")
        with io.open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(out)
        print("写出 %s (%d 字符)" % (dst, len(out)))
    else:
        sys.stdout.write(out)

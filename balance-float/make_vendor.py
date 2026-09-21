# -*- coding: utf-8 -*-
# ponytail: 生成 ui/vendor/ 下的离线资源(字体 + 图标字体子集), 页面不再请求外网。
# 只在换字体/改图标时才需要重跑; 产物已提交, 运行浮窗不依赖这个脚本。
import hashlib
import io
import os
import re
import subprocess

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
import sys
sys.path.insert(0, HERE)
import pages  # noqa: E402

PROXY = os.environ.get("BF_PROXY", "http://127.0.0.1:7897")
VENDOR = os.path.join("ui", "vendor")
FONT_DIR = os.path.join(VENDOR, "fonts")
CSS_SRC = {
    os.path.join(".twtest", "gfonts.css"): os.path.join(VENDOR, "gfonts.css"),
    os.path.join(".twtest", "icons.css"): os.path.join(VENDOR, "icons.css"),
}
URL_RE = re.compile(r"url\((https://fonts\.gstatic\.com/[^)]+)\)")
ICON_SRC = os.path.join(".twtest", "ms-full.woff2")
ICON_DST = os.path.join(FONT_DIR, "ms-icons-subset.woff2")
LETTERS = [chr(c) for c in range(97, 123)] + ["underscore"]


def http_get(url, dst):
    if os.path.isfile(dst) and os.path.getsize(dst) > 1000:
        return
    cmd = ["curl", "-sS", "-L", "--max-time", "120", "-o", dst, url]
    if PROXY:
        cmd[1:1] = ["-x", PROXY]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0 or not os.path.isfile(dst):
        raise SystemExit("下载失败 %s: %s" % (url, p.stderr.decode("utf-8", "replace")[:300]))


def icon_names():
    """页面里真正用到的 material-symbols 图标名: 子集只收这些。"""
    html = pages.render()
    # JS 里图标名写成 \\uXXXX 转义, 先还原成字面字符才看得到
    flat = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), html)
    names = set(re.findall(r"material-symbols-outlined[^>]*>([a-z0-9_]+)<", flat))
    names |= set(re.findall(r'icon:\s*"([a-z0-9_]+)"', flat))
    names |= set(re.findall(r'"([a-z0-9_]+)"', " ".join(re.findall(r"GLYPHS = \[([^\]]*)\]", flat))))
    return sorted(names)


def fetch_fonts():
    """抓两份 Google CSS 里的 woff2, 并把 url 改写成 vendor 内的相对路径。"""
    os.makedirs(FONT_DIR, exist_ok=True)
    seen = {}
    for src, dst in CSS_SRC.items():
        css = io.open(src, encoding="utf-8").read()
        for url in URL_RE.findall(css):
            if url in seen or "materialsymbols" in url:
                continue  # 图标字体单独下载到 ICON_SRC, 它要子集化
            fam = "jb" if "jetbrainsmono" in url else "pjs" if "jakarta" in url else "f"
            name = fam + "-" + hashlib.sha1(url.encode()).hexdigest()[:8]
            local = os.path.join(FONT_DIR, name + ".woff2")
            http_get(url, local)
            seen[url] = "fonts/%s.woff2" % name
        for url, rel in seen.items():
            css = css.replace(url, rel)
        # 图标字体的 url 指向子集产物
        css = re.sub(r"url\(https://fonts\.gstatic\.com/s/materialsymbolsoutlined/[^)]+\)",
                     "url(fonts/ms-icons-subset.woff2)", css)
        with io.open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(css)
    return seen


def fetch_icon_source():
    """原始图标字体 3.8MB 只用来生成子集, 落在 .twtest/ 里不进包。"""
    os.makedirs(os.path.dirname(ICON_SRC), exist_ok=True)
    if os.path.isfile(ICON_SRC) and os.path.getsize(ICON_SRC) > 1000:
        return
    css = io.open(os.path.join(".twtest", "icons.css"), encoding="utf-8").read()
    url = URL_RE.search(css).group(1)
    http_get(url, ICON_SRC)


def has_ligature(path, name):
    """图标名 "add" 在字体里是一条 a+d+d 连字规则, 按结尾字形名找。"""
    g = TTFont(path)["GSUB"].table
    for i in range(g.LookupList.LookupCount):
        for st in g.LookupList.Lookup[i].SubTable:
            if getattr(st, "ExtensionLookupType", None) is not None:
                st = st.ExtSubTable
            if st.LookupType != 4:
                continue
            for _, ls in (getattr(st, "ligatures", {}) or {}).items():
                for l in ls:
                    if l.LigGlyph == name:
                        return True
    return False


def subset_icons():
    """图标字体原包 3.8MB → 几十个图标 ~29KB。

    图标靠 liga 连字渲染("add" → 字形 add), 所以三件事都不能少:
      1. glyphs 里一起保留 a-z + underscore —— 它们是连字规则的输入字形,
         少了规则会被剪掉, 页面退化成显示字母;
      2. layout_closure 关掉 —— 开着会把所有以这些字母打头的图标全拉进来,
         实测剩 5994 个字形 / 3.6MB;
      3. glyph_names 打开 —— 否则字形改名成 uniE5C4/A/B, 规则引用不到同样被剪。"""
    names = icon_names()
    opts = Options()
    opts.layout_features = ["*"]
    opts.layout_closure = False
    opts.glyph_names = True
    opts.notdef_outline = True
    opts.hinting = False
    opts.desubroutinize = True
    opts.recalc_bounds = True
    opts.drop_tables += ["DSIG"]
    font = TTFont(ICON_SRC)
    sub = Subsetter(options=opts)
    sub.populate(glyphs=names + LETTERS)
    sub.subset(font)
    font.flavor = "woff2"
    font.save(ICON_DST)
    # 连字规则还在页面才显示得出图标, 缺一条都是白页 —— 直接在这里断掉, 别发出去才发现
    gone = [n for n in ("add", "tune", "sync", "arrow_back", "delete_forever")
            if not has_ligature(ICON_DST, n)]
    if gone:
        raise SystemExit("子集丢了连字规则: %s" % gone)
    print("图标子集 %d 个图标: %d 字节 → %d 字节"
          % (len(names), os.path.getsize(ICON_SRC), os.path.getsize(ICON_DST)))



def prune_stale():
    """早期版本把整包图标字体也下到 vendor/ 了(3.8MB); 子集出来后它只是打包垃圾。"""
    for name in os.listdir(FONT_DIR):
        p = os.path.join(FONT_DIR, name)
        if name.startswith("ms-") and name != os.path.basename(ICON_DST):
            os.remove(p)
            print("清掉 %s" % p)


def main():
    fetch_fonts()
    fetch_icon_source()
    subset_icons()
    prune_stale()
    print("完成: ui/vendor/ 已可离线使用")


if __name__ == "__main__":
    main()

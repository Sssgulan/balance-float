# -*- coding: utf-8 -*-
"""打包成别人可直接使用的绿色版（onedir，解压即用）。

用法: python -X utf8 build_release.py
产物: dist/balance-float/  —— 整个文件夹发给别人, 双击 exe 即可

要点: 绝不打进本机 configs/（里面有真实 api_key/access_token）。
构建在 .build/release 这个干净暂存目录里做, configs/ 用空模板重建,
最后还会扫一遍产物确认没有凭据残留。
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, ".build", "release")
OUTDIR = os.path.join(HERE, "dist", "balance-float")

# 只带程序本体 + 页面 + 官方模型的空标准表; configs 里其余文件一律重新生成空模板
COPY_FILES = ["float_window.py", "providers.py", "ocx_metrics.py", "pages.py", "theme.py"]
COPY_TREES = [("ui", "ui")]
COPY_ASSETS = ["logo.png", "icon.ico"]   # 图标: exe 资源 + 运行时窗口图标
COPY_ONLY = ["configs/official/models.json"]

EMPTY_CONFIGS = {
    "configs/newapi.json": {"accounts": []},
    "configs/generic.json": {"accounts": []},
    "configs/ccsw.json": {"accounts": []},
    "configs/ocx.json": {"accounts": []},
    "configs/official/deepseek.json": {"accounts": []},
    "configs/official/moonshot.json": {"accounts": []},
    "configs/official/zhipu.json": {"accounts": []},
}
DEFAULT_SETTINGS = {"refresh_seconds": 60, "timeout": 15, "order": []}

# 系统自带的 DLL, 不该从本机第三方目录被抄进产物
_FOREIGN_DLLS = {"netapi32.dll", "setupapi.dll", "d3dcompiler_47.dll"}

LAUNCHER = (
    "' 悬浮窗启动器: 双击启动, 不带黑色控制台窗口\n"
    "' 不支持多开, 先用右上角关闭按钮退出旧实例\n"
    'Set sh = CreateObject("WScript.Shell")\n'
    'Set fso = CreateObject("Scripting.FileSystemObject")\n'
    'base = fso.GetParentFolderName(WScript.ScriptFullName)\n'
    "sh.CurrentDirectory = base\n"
    'sh.Run Chr(34) & base & "\balance-float.exe" & Chr(34), 0, False\n'
)

README_TXT = """balance-float 流量悬浮窗
================================

用法
----
双击 balance-float.exe（或“启动悬浮窗.vbs”）即可。
程序只监听 127.0.0.1:8765，不对外开端口。

第一次打开
----------
窗口右下角“添加”进入接入页，按页签填自己的中转站：
  · NewAPI   填站点地址 + 访问令牌（有些站点还要 user_id）
  · 官方接口   DeepSeek / Kimi 等，填自己的 api_key 即可
  · 自定义    直接写 JSON 配置
  · CC-SW   读取本机 CC Switch 的配置（需已装 CC Switch）
  · OCX     填服务器连接 + API
填完保存，回到主界面点刷新看余额与今日流量。

配置存在哪里
------------
就是本目录的 configs 文件夹（纯 JSON，可备份、可手改）。
换电脑把整个文件夹拷过去即可，账号配置跟着走。

依赖
----
· Windows 10/11 自带的 WebView2 运行时（Edge 的组件，绝大多数机器已有）
· 想用 CC-SW / OCX 页签，需要本机装了 CC Switch / OCX 客户端；
  没装也不影响其它页签，程序不会因为读不到它们的配置而报错。

遇到过问题
----------
· 双击没反应：多半是安全软件拦了，把整个文件夹加进白名单。
· 想重置：关掉程序，删掉 configs 里的文件，重新打开会生成空配置。
"""


def _rm(path):
    shutil.rmtree(path, ignore_errors=True)


def _write_json(fp, obj):
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


SECRET_PATTERNS = [
    # 尾巴必须带数字: tailwind.js 里的 sk-box-image-source 这类 CSS 属性名会误报,
    # 而真实密钥基本都混了数字
    re.compile(r"sk-(?=[A-Za-z0-9\-_]*\d)[A-Za-z0-9\-_]{16,}"),
    re.compile(r'"access_token"\s*:\s*"[^"]+"'),
    re.compile(r'"api_key"\s*:\s*"[^"]+"'),
]


def _scan_secrets(text):
    return [m.group(0)[:80] for p in SECRET_PATTERNS for m in p.finditer(text)]


def prune_foreign(internal):
    # 本机 PATH 里有第三方(非系统)目录时, PyInstaller 会把那里的同名 DLL 当成依赖抄进来。
    # 这些系统盘本来就有, 删掉不影响运行, 也免得把别人的 DLL 一起发出去。
    out = []
    for dp, _dn, fns in os.walk(internal):
        for fn in fns:
            if fn.lower() in _FOREIGN_DLLS:
                fp = os.path.join(dp, fn)
                os.remove(fp)
                out.append(os.path.relpath(fp, OUTDIR))
    return out


def stage():
    _rm(STAGE)
    os.makedirs(STAGE, exist_ok=True)
    for fn in COPY_FILES:
        shutil.copy2(os.path.join(HERE, fn), os.path.join(STAGE, fn))
    for src, dst in COPY_TREES:
        shutil.copytree(os.path.join(HERE, src), os.path.join(STAGE, dst))
    os.makedirs(os.path.join(STAGE, "assets"), exist_ok=True)
    for fn in COPY_ASSETS:
        shutil.copy2(os.path.join(HERE, "assets", fn), os.path.join(STAGE, "assets", fn))
    for rel in COPY_ONLY:
        d = os.path.join(STAGE, *rel.split("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(os.path.join(HERE, *rel.split("/")), d)
    for rel, obj in EMPTY_CONFIGS.items():
        _write_json(os.path.join(STAGE, *rel.split("/")), obj)
    _write_json(os.path.join(STAGE, "configs", "settings.json"), DEFAULT_SETTINGS)
    # 暂存目录里也不该出现任何真实凭据: 上面的空模板就是全部 configs 内容
    for dp, _dn, fns in os.walk(os.path.join(STAGE, "configs")):
        for fn in fns:
            fp = os.path.join(dp, fn)
            with open(fp, encoding="utf-8") as f:
                hits = _scan_secrets(f.read())
            assert not hits, "暂存 configs 里发现凭据: %s %s" % (fp, hits)
    return STAGE


SPEC_TEMPLATE = '''# -*- mode: python ; coding: utf-8 -*-
# 由 build_release.py 生成; pywebview 在 Windows 上是 pythonnet + WinForms + WebView2,
# 这几层都是运行时动态导入的, 静态分析扫不到, 必须显式声明。
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("webview",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr", "clr_loader", "pythonnet",
]

# Windows 上只用 Edge/WebView2 后端; pywebview 的 Qt 兜底会把整个 PyQt5 拖进来
# (光 QtWebEngineCore 就 100MB+), 对方机器用不到, 一并剔掉
excludes = ["PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "shiboken2",
            "shiboken6", "matplotlib", "numpy", "pandas", "scipy", "tkinter"]

a = Analysis(["float_window.py"], datas=datas, binaries=binaries,
             hiddenimports=hiddenimports, excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="balance-float",
          console=False, upx=False,
          icon=r"@ICON@")

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="balance-float")
'''


def build():
    spec = os.path.join(STAGE, "balance-float.spec")
    icon = os.path.join(STAGE, "assets", "icon.ico")
    if not os.path.isfile(icon):
        raise SystemExit("找不到 %s, 先跑 python -X utf8 make_logo.py" % icon)
    with open(spec, "w", encoding="utf-8") as f:
        # 绝对路径: PyInstaller 是 cwd=STAGE 跑 spec 的, 相对路径容易踩坑
        f.write(SPEC_TEMPLATE.replace("@ICON@", icon))
    cmd = [sys.executable, "-X", "utf8", "-m", "PyInstaller", "--noconfirm",
           "--distpath", os.path.join(HERE, "dist"),
           "--workpath", os.path.join(HERE, ".build", "pyi"),
           spec]
    print("[build] PyInstaller onedir (webview/pythonnet 已显式声明)")
    r = subprocess.run(cmd, cwd=STAGE)
    if r.returncode != 0:
        raise SystemExit("PyInstaller 失败, 退出码 %d" % r.returncode)


def finish():
    # configs 与 ui 放在 exe 旁边: float_window.py 冻结后按 exe 所在目录取配置与页面
    for src, dst in ((os.path.join(STAGE, "configs"), os.path.join(OUTDIR, "configs")),
                     (os.path.join(STAGE, "ui"), os.path.join(OUTDIR, "ui")),
                     (os.path.join(STAGE, "assets"), os.path.join(OUTDIR, "assets"))):
        _rm(dst)
        shutil.copytree(src, dst)
    removed = prune_foreign(os.path.join(OUTDIR, "_internal"))
    if removed:
        print("[prune] 剔掉本机第三方目录漏进来的 DLL: %s" % ", ".join(removed))
    with open(os.path.join(OUTDIR, "启动悬浮窗.vbs"), "w", encoding="utf-8-sig") as f:
        f.write(LAUNCHER)
    with open(os.path.join(OUTDIR, "使用说明.txt"), "w", encoding="utf-8-sig") as f:
        f.write(README_TXT)
    return OUTDIR


def audit():
    """产物里不该有任何真实凭据, 空配置必须真的是空的。"""
    bad, scanned = [], 0
    for dp, _dn, fns in os.walk(OUTDIR):
        for fn in fns:
            fp = os.path.join(dp, fn)
            if os.path.getsize(fp) > 4 * 1024 * 1024:
                continue
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
            except OSError:
                continue
            scanned += 1
            hits = _scan_secrets(txt)
            if hits:
                bad.append((os.path.relpath(fp, OUTDIR), hits[:3]))
    assert not bad, "产物中发现凭据:\n%s" % "\n".join("%s %s" % b for b in bad)
    for rel in EMPTY_CONFIGS:
        with open(os.path.join(OUTDIR, *rel.split("/")), encoding="utf-8") as f:
            assert json.load(f) == {"accounts": []}, "%s 不是空配置" % rel
    with open(os.path.join(OUTDIR, "configs", "settings.json"), encoding="utf-8") as f:
        s = json.load(f)
    assert not s.get("ccsw_ignored") and not s.get("ocx_ignored"), "settings 带上了删除名单"
    print("[audit] 扫描 %d 个文件, 未发现凭据; configs 全为空模板" % scanned)


def pack():
    """再压一个 zip: OneDrive/网盘/邮箱都只吃单个文件, 整包发 zip 最省事。"""
    zp = shutil.make_archive(os.path.join(HERE, "dist", "balance-float-portable"),
                             "zip", root_dir=os.path.dirname(OUTDIR),
                             base_dir=os.path.basename(OUTDIR))
    print("[pack] %s (%.1f MB)" % (zp, os.path.getsize(zp) / 1024.0 / 1024.0))
    return zp


def main():
    stage()
    build()
    finish()
    audit()
    pack()
    total = sum(os.path.getsize(os.path.join(dp, fn))
                for dp, _dn, fns in os.walk(OUTDIR) for fn in fns)
    n = sum(len(fns) for _dp, _dn, fns in os.walk(OUTDIR))
    print("[done] %s" % OUTDIR)
    print("[done] %d 个文件, %.1f MB" % (n, total / 1024.0 / 1024.0))
    print("[done] 发 dist\\balance-float-portable.zip 单文件即可;")
    print("       对方解压后双击 balance-float.exe, 或直接用 dist\\balance-float 整个文件夹")


if __name__ == "__main__":
    main()

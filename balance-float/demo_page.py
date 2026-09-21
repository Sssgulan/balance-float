# -*- coding: utf-8 -*-
"""接入页 demo: 起一个本机后端, 把接入页(默认官方接口)开在真实浏览器里直接点。

用法（balance-float 目录）:
  python demo_page.py          # 临时配置 + 假账户, 随便点, 不碰真实 configs/
  python demo_page.py --real   # 用真实 configs/(保存/删除会真的写盘)

打开后点窗口底部的“添加”即进入接入页(360x420), 默认停在官方接口, 页签可切
官方接口 / 自定义 / CC-SW / OCX。关掉浏览器窗口后回来 Ctrl+C。
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

import float_window as fw  # noqa: E402

BROWSERS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def find_browser():
    # Edge 在 64 位系统上常装在这两个位置; Chrome 在 Program Files (x86) 也有
    extra = (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"))
    return next((p for p in BROWSERS + extra if os.path.isfile(p)), None)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    real = "--real" in sys.argv
    if real:
        cfg = fw.CONFIG_DIR
    else:
        cfg = tempfile.mkdtemp(prefix="bf_demo_")
        fw.CONFIG_DIR = cfg
        fw.write_accounts("newapi.json", [
            {"id": "demo1", "name": "示例站点", "type": "newapi",
             "base_url": "https://example.com", "access_token": "sk-demo-not-real"},
        ])
    fw.DIST = os.path.join(HERE, "ui")
    port = free_port()
    fw._PORT = port          # Handler._check_origin 按它放行页面请求
    srv = fw.ThreadingHTTPServer(("127.0.0.1", port), fw.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    url = "http://127.0.0.1:%d/?rt=1" % port
    print("配置目录: %s%s" % (cfg, "  <- 真实配置, 保存会写盘" if real else "  <- 临时, 退出后删"))
    print("接入页  : %s" % url)
    print("点窗口底部的“添加”进入接入页(默认官方接口); 看完关掉浏览器窗口, 回来 Ctrl+C 结束。")

    exe = find_browser()
    if exe:
        subprocess.Popen([exe, "--new-window", url, "--window-size=390,480",
                          "--window-position=120,120"])
    else:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()
        if not real:
            shutil.rmtree(cfg, ignore_errors=True)
        print("\n已退出。")


if __name__ == "__main__":
    main()

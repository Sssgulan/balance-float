# balance-float 流量悬浮窗

一个 Windows 桌面小浮窗，把你在用的各个中转站和官方 API 的剩余余额聚到一张卡片上，同时显示本机 CC Switch 的今日用量。窗口无边框、置顶、半透明圆角，平时收成一条窄条贴在桌面角落。

![收起状态](balance-float/docs/screenshot-collapsed.png)

![展开状态](balance-float/docs/screenshot-expanded.png)

收起态一屏四个数值，右上角圆点变绿表示查询正常；点右上角箭头展开成列表，每行是品牌图标、余额、用量进度条与接口延迟。展开态底部的“添加”进接入页，账户的新增、编辑、导入都在那里完成。

## 功能

- **一处看全部余额**：NewAPI 系列站点、DeepSeek / Kimi / 智谱的官方接口，以及任何返回 JSON 的自定义端点都能接进来。
- **今日流量**：本机装了 CC Switch 就直接读它的数据库，按 provider 汇总今天的请求数、token 和花费。
- **三态窗口**：收起 212x114、展开 248x248、接入页 360x420，改尺寸只需动 `ui/theme.json` 里的一个数字。
- **只在本机**：HTTP 服务只监听 `127.0.0.1`，账户配置以纯 JSON 存在本目录的 `configs/` 下，不会发到任何服务器。
- **界面按片段组装**：一个列表、一个表单、一套配色各是一个文件，改哪里开哪个，再跑一次 `pages.py` 重拼出 `ui/index.html`。

## 直接使用（不用装 Python）

打包产物是一个绿色版文件夹，解压后双击 `balance-float.exe`（或 `启动悬浮窗.vbs`）即可，无需安装。

首次打开点展开态底部的“添加”进接入页，按页签填自己的账户：

| 页签 | 要填 | 说明 |
| --- | --- | --- |
| 官方接口 | API Key | DeepSeek / Kimi / GLM 点一下进表单，地址走内置默认值 |
| NewAPI | 站点地址 + 访问令牌 | 令牌是系统访问令牌或 `sk-` 令牌；站点改过倍率还要填 quota 换算除数 |
| 自定义 | 一段 JSON | 端点不标准时用它，键名以后端为准 |
| CC-SW | 不用填 | 扫描本机 CC Switch 的配置导入流量节点 |
| OCX | 服务器连接 + API 密钥 | 本地 OCX 代理节点，也可以从配置文件一键导入 |

跑在 Windows 10/11 上，依赖系统自带的 WebView2 运行时（Edge 的组件，绝大多数机器已经有了）。

## 从源码运行

需要 Python 3.10+ 和 pywebview：

```
pip install pywebview
python -X utf8 float_window.py --check   # 只校验 configs/ 的必填字段，不弹窗
python -X utf8 float_window.py           # 启动浮窗，服务在 127.0.0.1:8765
```

打包成可分发的绿色版：

```
python -X utf8 build_release.py          # 产物在 dist/balance-float/ 与 dist/balance-float-portable.zip
```

## 目录结构

```
balance-float/
  float_window.py      HTTP 服务、窗口、配置加载与校验（后端口径只此一份）
  providers.py         各账户类型查余额的适配器
  ocx_metrics.py       OCX 单端口今日合计与输出速度曲线
  ui/
    index.tpl.html     页面骨架
    parts/             片段：collapsed / expanded / page / head / modal，以及 parts/js/01..15
    theme.json         全站颜色、尺寸、动画变量表
    index.html         组装产物，不要手改；改完片段跑 pages.py --write 重新生成
  configs/             账户配置与全局设置（纯 JSON，可备份、可手改）
  docs/                README 用的截图
  assets/              图标
```

## 开发与自检

| 命令 | 作用 |
| --- | --- |
| `python -X utf8 test_backend.py` | 后端自检（安全、线程、导入；用临时目录，不碰真实配置） |
| `python -X utf8 test_ui_page.py` | 接入页静态自检 |
| `python -X utf8 test_ui_page.py --live` | 追加 Chrome 端到端：添加 → 校验 → 保存 |
| `python -X utf8 test_pages.py` | 组装自检：片段拼回来须与拆分前的快照逐字节一致 |
| `python -X utf8 theme.py --check` | 反查每个色值对应哪个变量名 |
| `python -X utf8 pages.py --write` | 改完片段或主题后重拼 `ui/index.html` |
| `python -X utf8 demo_page.py` | 只起后端，在浏览器里点“添加”进接入页 |
| `python -X utf8 make_screenshots.py` | 用无头 Chrome 截收起/展开两张图到 `docs/`（演示假数据，不读本机配置） |

## 文档

- [balance-float/README.md](balance-float/README.md)：接口契约、配置结构、账户字段说明
- [balance-float/接口说明.md](balance-float/接口说明.md)：后端接口口径
- [balance-float/ADAPTERS.md](balance-float/ADAPTERS.md)：余额查询适配器速查

## 说明

读 CC Switch 的数据时只用只读方式打开它的数据库；在浮窗或接入页里删除账户，只改本项目自己的 `configs/`，不动 CC Switch 本身的文件。

未附加开源许可证，默认保留所有权利。

# balance-float 流量悬浮窗

Windows 桌面悬浮窗（pywebview + WebView2），实时汇总多个中转站/官方 API 的余额，
并展示本机 CC Switch 的今日流量。无边框、置顶、半透明、圆角，不是网页。

## 快速开始

```
python -X utf8 float_window.py --check    # 校验 configs/ 必填字段
python -X utf8 test_backend.py            # 后端自检
python -X utf8 build_release.py           # 打包成可分发的绿色版
```

打包产物在 `dist/`，整个文件夹（或 `dist/balance-float-portable.zip`）即可分发，
对方只需机器自带 WebView2。

## 文档

- 运行与开发说明：[balance-float/README.md](balance-float/README.md)
- 后端接口口径：[balance-float/接口说明.md](balance-float/接口说明.md)
- 额度查询适配器速查：[balance-float/ADAPTERS.md](balance-float/ADAPTERS.md)

## 关于配置

`balance-float/configs/` 存放账户凭据，属于个人隐私数据，已通过 `.gitignore`
排除在版本控制之外。仓库只保留 `configs/official/models.json`（模型清单）。

首次运行会按需生成空配置模板；打包脚本也会用空模板重建 `configs/`，不会把本机凭据带进发行包。

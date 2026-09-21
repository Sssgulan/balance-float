# 额度查询适配器速查表

> 供浮窗项目（`balance-float`）后续扩展数据源时对照使用。只记录协议、字段与口径，不含任何真实密钥。
> 核对日期 2026-09-16；NEWAPI 部分逐行核对 QuantumNous/new-api `main` 分支源码，DeepSeek 部分在线核对官方文档。

## 0. 选端点

| 目标 | 方法与路径 | 凭据 | 返回单位 | 换算方 |
| --- | --- | --- | --- | --- |
| NEWAPI 账号余额 | `GET {baseUrl}/api/user/self` | 管理令牌 accessToken | 原始 quota | 客户端 |
| NEWAPI 单令牌用量 | `GET {baseUrl}/api/usage/token/` | sk 令牌 | 原始 quota | 客户端 |
| NEWAPI OpenAI 兼容 | `GET {baseUrl}/dashboard/billing/subscription`、`/usage` | sk 令牌 | 已换算金额，usage 为分 | 服务端 |
| DeepSeek 官方 | `GET https://api.deepseek.com/user/balance` | 官方 API key | 金额字符串 + currency | 无 |
| 各路中转站变体 | `/user/balance`、`/v1/usage`、`/api/usage/account/` | 多为 sk 令牌 | 因站而异 | 因站而异 |

两种凭据语义完全不同，必须先判断手里拿的是哪一种：

- **管理令牌（accessToken）**：站点后台生成的系统访问令牌，走 `middleware.UserAuth()`，只读 `Authorization` 头；对应账号级数据。
- **sk 令牌**：`sk-` 开头的模型调用令牌，走 `middleware.TokenAuth()` 系列；对应令牌级数据。

## 1. NEWAPI 用户余额：`GET /api/user/self`

### 请求

```http
GET {baseUrl}/api/user/self
Authorization: Bearer <accessToken>
New-Api-User: <userId>
Content-Type: application/json
```

- `Authorization` 用**管理令牌**，不是 sk 令牌。
- `New-Api-User: userId` 是兼容项。main 分支已不校验该头，历史版本和部分分支会校验，因此**带上无害**，建议保留。
- 该路由挂 `middleware.DisableCache()` + `middleware.UserAuth()`，是只读查询，不会扣额度。

### 响应

```json
{
  "success": true,
  "message": "",
  "data": {
    "id": 1,
    "username": "demo",
    "display_name": "demo",
    "group": "default",
    "quota": 12500000,
    "used_quota": 3750000,
    "request_count": 2143
  }
}
```

上例数值为结构示意，非真实账号数据。`data` 实际还包含 `role`、`status`、`email`、`aff_code`、`aff_count`、`aff_quota`、`setting`、`permissions` 等字段；浮窗只需要下列四个：

| 字段 | 含义 |
| --- | --- |
| `data.quota` | **剩余**额度，原始 quota 单位 |
| `data.used_quota` | 已用额度，原始 quota 单位 |
| `data.group` | 用户分组名，可直接当「套餐名」展示 |
| `data.request_count` | 累计请求数 |

站点总额度按 `data.quota + data.used_quota` 估算。若要把 quota 换成令牌数或金额，见下面的换算口径。

### 失败响应

```json
{ "success": false, "message": "..." }
```

判定成功要看 body 里的 `success`，不要只看 HTTP 状态码：NEWAPI 的业务错误会以 `success: false` + `message` 的形式返回，状态码不统一（缺 `Authorization` 头时 `/api/usage/token/` 直接返回 401 + `success: false`）。`message` 文案随版本和站点本地化变化，**不要拿文案做逻辑判断**。

### quota 换算口径

服务端常量定义在 `common/constants.go`：

```go
var QuotaPerUnit = 500 * 1000.0 // $0.002 / 1K tokens
```

也就是默认 `QuotaPerUnit = 500000`，含义是「1 美元 = 500000 quota」。

- `/api/user/self` 返回的是**原始 quota，服务端不做任何换算**。
- `QuotaPerUnit` 是站点级变量，站点可用配置覆盖。**客户端无法从响应反推真实除数** —— 响应里没有任何字段暴露这个常量。
- 所以任何硬编码 `/ 500000` 的写法，在改过配置的站点上必然算错。浮窗里应把它做成可配置项（或提供「只显示 quota，不显示金额」的降级展示）。
- 想拿到服务端已经换算好的金额，走第 3 节的 billing 接口。
- CNY 展示的站点，换算还会再乘一个站点级的 `USDExchangeRate`，客户端同样拿不到。

## 2. NEWAPI 单令牌用量：`GET /api/usage/token/`

### 请求

```http
GET {baseUrl}/api/usage/token/
Authorization: Bearer sk-<token>
```

- **结尾斜杠必须保留**。路由是 `usageRoute.Group("/token")` 加 `tokenUsageRoute.GET("/")`，少一个斜杠会 404 或被重定向。
- 走 `middleware.TokenAuthReadOnly()`，只读，不会扣额度。
- 服务端会 `strings.TrimPrefix(key, "sk-")` 再查库，带不带 `sk-` 前缀都能命中同一令牌，建议原样带前缀。

### 响应

```json
{
  "success": true,
  "message": "",
  "data": {
    "total_granted": 12500000,
    "total_used": 3750000,
    "total_available": 8750000,
    "unlimited_quota": false,
    "expires_at": 0,
    "model_limits": {},
    "model_limits_enabled": false
  }
}
```

字段来源（`controller/token.go` 的 `GetTokenUsage`）：

| 字段 | 取值 | 含义 |
| --- | --- | --- |
| `data.total_granted` | `RemainQuota + UsedQuota` | 该令牌额度上限 |
| `data.total_used` | `UsedQuota` | 该令牌已用 |
| `data.total_available` | `RemainQuota` | 该令牌剩余 |
| `data.unlimited_quota` | `UnlimitedQuota` | 为 true 时上面三个数字无意义 |
| `data.expires_at` | `ExpiredTime` | Unix **秒**；`ExpiredTime == -1`（永不过期）时置 0 |

三个额度字段都是**原始 quota 单位**，未换算成金额，换算问题同第 1 节。

一个容易踩的单位坑：同一文件里的 `/api/token/status` 返回的 `expires_at` 是毫秒（`expiredAt * 1000`），而 `/api/usage/token/` 返回的是秒。两个接口不要共用同一个时间解析函数。

## 3. NEWAPI OpenAI 兼容 billing

### 请求

```http
GET {baseUrl}/dashboard/billing/subscription
GET {baseUrl}/dashboard/billing/usage
Authorization: Bearer sk-<token>
```

路由同时挂在根和 `/v1` 下，所以 `{baseUrl}/v1/dashboard/billing/subscription` 也能用。凭据是 sk 令牌。

### 返回

`subscription`：`hard_limit_usd`、`soft_limit_usd`、`system_hard_limit_usd`、`access_until`。

`usage`：

```json
{ "object": "list", "total_usage": 1234.56 }
```

### 口径

- **`total_usage` 是金额 × 100，单位是分**，不是 token 数。不要拿它和 `/api/usage/token/` 的 `total_used` 比较。
- `hard_limit_usd` 之类带 `_usd` 后缀的字段**已经过服务端换算**，但含义是「站点展示类型对应的额度值」，不保证是美元：站点展示类型为 CNY 时按 `quota / QuotaPerUnit * USDExchangeRate` 算，为 Tokens 时直接用原始值，默认（USD）时按 `quota / QuotaPerUnit`。
- 服务端取的是令牌口径还是账号口径，由站点开关 `common.DisplayTokenStatEnabled` 决定：开启时取当前 sk 令牌的 `RemainQuota`/`UsedQuota`，关闭时取账号级的 `GetUserQuota`/`GetUserUsedQuota`。同一个站点上开关一变，数值含义就变。
- 无限额度时返回硬编码哨兵值 `100000000`，需要单独识别，不要直接显示。
- 失败响应是 OpenAI 风格，且**状态码仍是 200**：`{"error": {"message": "...", "type": "upstream_error"}}`（subscription）或 `"type": "new_api_error"`（usage）。判成功要看有没有 `error` 键，不能看状态码。

## 4. DeepSeek 官方余额

### 请求

```http
GET https://api.deepseek.com/user/balance
Authorization: Bearer <key>
```

base_url 为 `https://api.deepseek.com`（也接受 `/v1` 前缀），余额接口本身挂在根路径下。

### 响应

```json
{
  "is_available": true,
  "balance_infos": [
    {
      "currency": "CNY",
      "total_balance": "110.00",
      "granted_balance": "10.00",
      "topped_up_balance": "100.00"
    }
  ]
}
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `is_available` | boolean | 余额是否足够继续调用 |
| `balance_infos[].currency` | string | 取值 `CNY` 或 `USD` |
| `balance_infos[].total_balance` | string | 可用总余额，含赠送与充值 |
| `balance_infos[].granted_balance` | string | 未过期的赠送余额 |
| `balance_infos[].topped_up_balance` | string | 充值余额 |

三个金额字段都是**字符串**，不是数字，解析前先转数值类型。`balance_infos` 是数组，实际可能有多条不同币种的记录，按 `currency` 挑选或全部展示。

### 来源与核对结论

已在线核对官方文档，字段名、类型与上例逐字一致：

- 英文：https://api-docs.deepseek.com/api/get-user-balance
- 中文：https://api-docs.deepseek.com/zh-cn/api/get-user-balance
- 文档标题 "Get User Balance"，方法与路径为 `GET /user/balance`，响应 schema 含 `is_available`（boolean）与 `balance_infos`（object[]，属性为 `currency` / `total_balance` / `granted_balance` / `topped_up_balance`）。

该文档页的请求示例面板由 JS 动态渲染，静态抓取拿不到请求头字段，因此 `Authorization: Bearer <key>` 依据的是同站其他文档的调用示例（`curl https://api.deepseek.com/chat/completions -H "Authorization: Bearer ${DEEPSEEK_API_KEY}"`）和平台统一鉴权约定；接口、路径与响应结构本身为官方文档原文。

## 5. 常见中转站变体端点（非标准）

以下路径**都不是 NEWAPI 或 OpenAI 的规范接口**，字段名、成功判据、金额单位都因站而异，必须在目标站实测后再写适配器。三者的行为差异来自本机 CC Switch 配置里已有的自定义脚本：

| 端点 | 凭据 | 已知取法 | 备注 |
| --- | --- | --- | --- |
| `GET {baseUrl}/user/balance` | `Bearer <apiKey>` | one-api 系旧接口的常见字段是 `balance` / `quota` / `remaining` | CC Switch 的 general 模板走这条 |
| `GET {baseUrl}/v1/usage` | `Bearer <apiKey>` | 实测样本用 `remaining ?? quota.remaining ?? balance` 三级兜底 | 结构不统一，靠兜底才对得上 |
| `GET {baseUrl}/api/usage/account/` | `Bearer <apiKey>` | 实测样本先判 `code !== true` 才算失败，再取 `data.balance` | 成功判据用的是 `code`，不是 `success` |

标注为**[非标准 / 需实测]**的理由：

1. 成功判据不统一——有的看 `success`，有的看 `code`，有的只按 HTTP 状态码。
2. 金额单位不统一——出现过的单位字符串有 `USD`、`CNY`、`RMB`，个别站点还会用 `total === -1` 表示无限额度。
3. 字段层级不统一——同一语义下出现过 `remaining`、`quota.remaining`、`balance`、`data.balance` 多种位置。

因此这三条只适合作为「探测顺序的候选」，落库前要先手动打一次真实请求，把返回结构记下来，再写死到适配器里。

## 6. 落地注意

- **除数是站点级配置**，默认 500000，客户端无法反推；写成可配置项，或改用 billing 接口交给服务端换算。
- **先判断手里是哪种凭据**：accessToken 打 `/api/user/self`，sk 令牌打 `/api/usage/token/` 或 billing。两者返回的不是同一口径。
- **`total_usage` 是分**（金额 × 100），不要当 token 数。
- **识别哨兵值**：billing 的 `100000000`、`unlimited_quota: true` 都表示「无限」，应当单独显示而不是直接打印数字。
- **判成功以 body 为准**：NEWAPI 看 `success`，OpenAI 兼容看有无 `error`，部分中转站看 `code`；状态码不可靠。
- **凭据不进日志、不进错误提示**，只保留站点名与请求路径。

## 7. 来源

NEWAPI（`QuantumNous/new-api`，`main` 分支，本次逐行核对）：

| 文件 | 相关内容 |
| --- | --- |
| `router/api-router.go` | `selfRoute.GET("/self", ...)`；`usageRoute.Group("/token")` + `tokenUsageRoute.GET("/")` |
| `controller/user.go` | `GetSelf` 与 `buildSelfUserData`（`group`/`quota`/`used_quota`/`request_count` 字段清单） |
| `controller/token.go` | `GetTokenUsage`（`total_granted`/`total_used`/`total_available`/`unlimited_quota`/`expires_at`）；同文件 `GetTokenStatus` 的毫秒 `expires_at` |
| `controller/billing.go` | `GetSubscription`、`GetUsage`（展示类型换算与 `amount * 100`） |
| `common/constants.go` | `var QuotaPerUnit = 500 * 1000.0`、`DisplayInCurrencyEnabled` |

DeepSeek 官方文档：https://api-docs.deepseek.com/api/get-user-balance （中文：https://api-docs.deepseek.com/zh-cn/api/get-user-balance ）

CC Switch 侧的表结构、rollup 与裁剪行为另有本机存档，不入库。

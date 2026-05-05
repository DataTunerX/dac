---
name: web_fetch
description: 通过 HTTP(S) 抓取公开网页正文：内置 SSRF 防护、Readability 类抽取与外部内容安全包装。执行时**必须**调用 Runner 提供的 `web_fetch` 工具；返回值为 JSON 字符串——成功含页面元数据与正文，失败含 `error` 字段且不抛异常，便于继续决策。
---

## 能力边界

- **适用**：读取公开文档页、新闻、博客、产品说明等 **http/https** URL 的正文；需要可引用的标题、最终 URL、HTTP 状态与抽取模式信息时。
- **不适用**：需登录/ Cookie 的站点、需执行浏览器 JS 才能渲染的 SPA（本工具不做完整浏览器渲染）、应优先用 `plan_cmd` 调专用 CLI 或 API 客户端的场景、内网敏感地址（可能被 SSRF 策略拒绝）。

## 与 `web_fetch` 工具的固定约定

当本 skill 被选中后，在 **ReAct 工具列表里会出现名为 `web_fetch` 的工具**。必须通过它拉取网页，而不是只在对话里编造页面内容，也不要在已被 SSRF 拦截时用无意义的 `curl` 循环重试（先读错误信息与环境变量说明）。

### 参数

| 参数 | 含义 |
|------|------|
| `url` | 完整 HTTP 或 HTTPS URL（scheme 须为 `http` / `https`）。 |
| `extract_mode` | `markdown`（默认，保留结构）或 `text`（纯文本，适合搜索结果类页面）。其它值会返回 `Invalid extract_mode` 错误 JSON。 |
| `max_chars` | 返回正文的字符上限（含安全包装），默认 8000，范围 100–40000（与 Runner schema 一致）。 |

### 成功时 JSON 字段（摘要）

响应由工具序列化为 JSON 字符串，典型字段包括：`url`、`final_url`、`status`、`content_type`、`extractor`、`extract_mode`、`title`、`content`（正文）、`truncated`、`cached`、`took_ms`。请以实际返回为准。

### 失败时

- 常见形式：`{"url": "<请求的 url>", "error": "<原因>"}`。
- **SSRF 被拦截**：错误信息中可能含 `SSRF blocked`；若出现 `198.18.x` / `198.19.x` 相关说明，可能是 Clash/mihomo TUN fake-ip —— 可在运行环境中设置 `WEB_FETCH_ALLOW_RFC2544=1`（或 `true`/`yes`）后重试，并留意是否禁用了 fake-ip 自动探测（`WEB_FETCH_DISABLE_FAKEIP_AUTODETECT`）。

### 推荐工作流

1. 选用合适的 `extract_mode`（要结构用 `markdown`，只要纯文本用 `text`）。
2. 调用 `web_fetch`，解析 JSON；若 `error` 存在，向用户说明原因或调整 URL/环境，不要假装已抓取。
3. 用 `finish` 汇总引用来源（可含 `final_url` 与标题）。

### 禁止

- 不要声称已抓取网页却未在当轮产生 `web_fetch` 工具调用记录。
- 不要在明确被 SSRF 拒绝后反复用 `plan_cmd` 调用 `curl` 试图绕过同一策略（除非运维明确放行且符合安全规范）。

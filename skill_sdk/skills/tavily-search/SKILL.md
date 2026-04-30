---
name: tavily-search
description: Skill 名称为 `tavily-search`（强调联网检索入口）。使用 Tavily 按用户问题检索（`tavily_search`），并在需要时从 URL 拉取更完整正文（`tavily_extract`），适合“先查后读”。返回值为 JSON 字符串；需配置 `TAVILY_API_KEY`（或 Runner 同进程环境内已有 Tavily 凭据）。**不要**用 `plan_cmd`+`curl` 自己拼 Tavily 请求，应优先使用下方内置工具。
---

## 能力边界

- **适用**：需要实时/近期公开网页信息、多来源摘要；已知若干 URL 需要比摘要更全的正文、或 JS 渲染页。
- **不适用**：强登录站点、Tavily 未覆盖/返回空的页面；对延迟极敏感且不能接受外部 API 的场景。

## 与 Runner 工具约定

本 skill（**`tavily-search`**）被选中后，ReAct 工具列表中会包含 **`tavily_search`** 与 **`tavily_extract`**（由 Runner 实现，与 `web_fetch` 类似）。请通过它们完成检索与正文抽取，**不要**编造搜索结果或“假装已查询”。

### 推荐工作流

1. 从用户问题提炼 **1～3 个搜索查询**（可拆成子问题）。若问题涉及近期事件、新闻或时效性要求，**务必使用 `time_range`**（`day`/`week`/`month`/`year`）。调用 **`tavily_search`**，阅读返回的 `results`（含 `title` / `url` / `snippet` / `score` / `published` 等，字段以实际 JSON 为准）。  
   **回退策略**：若 `results` 为空或全部不相关，换用不同关键词/角度重新搜索（调整查询措辞、放宽范围、更换 `topic` 等），最多重试 **1 次**；仍无结果则通过 `finish` 如实告知用户“未找到相关信息”，禁止编造。

2. 若需某条结果的**更完整内容**或摘要不足，从 `results` 中**筛选**出最值得深入抓取的 URL：
   - 优先选择 `score` 较高（如有）、`snippet` 信息缺口明显的；
   - 排除 snippet 已能充分回答问题、域名不可信、或与问题明显无关的；
   - 通常保留 **2～6 个** URL 即可，避免无差别的全量抓取浪费额度。
   
   对筛选后的 **`url` 列表** 调用 **`tavily_extract`**（单次最多 20 个 URL；优先一次传入以减少请求次数，超过 20 个时再分批）。

3. `tavily_extract` 的参数选择：
   - **窄口径事实抽取**（如具体数字、日期、人名、定义）：同时传 `query`（重新提炼与当前子问题最匹配的短查询）与 `chunks_per_source`（建议 **3**，兼顾聚焦与上下文完整性）；
   - **宽口径理解抽取**（如完整原理、事件经过、多方对比）：**不传** `query` 与 `chunks_per_source`，获取较完整正文后再由模型自行总结，避免断章取义。

4. 用 **`finish`** 向用户总结，**标注引用来源**（标题与 URL）。  
   **结果复用**：同一对话中，若用户追问的内容已在当前轮次的 `extract` 结果中有覆盖，优先使用已抓取的内容作答，而非重复发起 `search` 或 `extract` 请求。


## `tavily_search`

| 参数 | 含义 |
|------|------|
| `query` | 搜索字符串（与主流搜索引擎类似，可包含关键词或简短问句） |
| `max_results` | 返回条数，1～20，可选 |
| `search_depth` | `basic` 或 `advanced`（更深、更慢），可选 |
| `topic` | `general` / `news` / `finance`，可选 |
| `include_answer` | 是否让 Tavily 返回简短综合答案，默认 false |
| `time_range` | `day` / `week` / `month` / `year`，可选 |
| `include_domains` / `exclude_domains` | 仅保留或排除的域名列表，可选 |

> 凭据与 API 基址**不在**工具参数中暴露；由 Runner 进程从环境变量读取（见下）。

## `tavily_extract`

| 参数 | 含义 |
|------|------|
| `urls` | 一个或多个要抓取的 **http(s) URL**（每次最多 20 个） |
| `query` | 可选；与 `chunks_per_source` 联用时用于按相关性选块（见 Tavily 文档） |
| `extract_depth` | `basic`（默认）或 `advanced`（复杂/JS 重页面可试） |
| `chunks_per_source` | 每 URL 返回块数 1～5；**若设置则必须同时提供 `query`** |
| `include_images` | 是否在结果中含图片 URL，默认 false |

> 同上：密钥与基址仅通过环境变量配置，**不要**让模型在工具里填写。

## 环境变量

- **`TAVILY_API_KEY`**：在 **Runner / Gateway 进程**中设置；`tavily_search` / `tavily_extract` 内部从环境读取，无对应工具参数。
- **`TAVILY_BASE_URL`**：可选；自定义 Tavily API 基址（默认 `https://api.tavily.com`），同样仅环境变量。

## 与 `web_fetch` 的取舍

- **`tavily_search` + `tavily_extract`**：从问题出发、先广搜后精读，适合开放域与多来源。
- **`web_fetch`**：已给定**单个明确 URL**、或仅需 HTTP 拉取与本地抽取时优先；两者勿重复抓取同一内容浪费额度。

## 禁止

- 在未出现工具调用记录时声称已完成 Tavily 搜索或阅读页面。
- 在缺少 `TAVILY_API_KEY` 时向用户保证可调用 Tavily；应 `finish` 说明需配置密钥。

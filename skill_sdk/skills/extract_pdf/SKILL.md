---
name: extract_pdf
description: 从本地路径或 HTTP(S) URL 等来源加载 PDF，抽取可复制文本；可选附带整页 PNG（base64）。执行时**必须**调用 Runner 提供的 `extract_pdf` 工具；返回值为 JSON 字符串——成功含 `items` 列表（每份含 `source`、`filename`、`text`、`stats` 等），失败含 `error` 字段且不抛异常，便于继续决策。依赖运行环境已安装 PyMuPDF（pymupdf）。
---

## 能力边界

- **适用**：用户给出 PDF 的本地绝对路径、`file://`、公开 **`http`/`https`** 直链、或 `data:application/pdf;base64,...`；需要文中文字内容、页码范围截取、或扫描件需要整页栅格图（配合 `include_images`）时。
- **不适用**：需复杂登录/Cookie 才能下载的 PDF、加密且无法打开的文档、应用内专有格式；应优先用 `plan_cmd` 调专用 OCR/文档流水线 CLI 的重度版面还原场景；单环境超过工具默认的「最多 PDF 份数 / 单文件大小 / 页数」时需引导用户分拆或调参而非盲目重试。

## 与 `extract_pdf` 工具的固定约定

当本 skill 被选中后，在 **ReAct 工具列表里会出现名为 `extract_pdf` 的工具**。必须通过它解析 PDF，而不是只在对话里编造正文，也不要对同一失败原因无意义地重复相同参数调用。

### 参数

| 参数 | 含义 |
|------|------|
| `pdf` | 单个 PDF 源：本地路径（建议绝对路径）、`file://`、`http(s)` URL、`data:application/pdf;base64,...`。 |
| `pdfs` | 多个 PDF 源列表；可与 `pdf` 同时提供，Runner 会去重合并。**至少**提供 `pdf` 或 `pdfs` 之一。 |
| `pages` | 可选。页码范围字符串，如 `1-3,5`；省略则按 `max_pages` 处理每份文档的前若干页。 |
| `max_bytes_mb` | 单个 PDF 最大字节数（MB），默认 `10`，范围约 `0.5`–`50`（与 schema 一致）。 |
| `max_pages` | 每个文档最多处理页数，默认 `20`，范围 `1`–`100`。 |
| `min_text_chars` | 抽取到的**文本总长度**达到该阈值则**不再**生成整页 PNG 栅格（省 token）；扫描版、正文极少时可**调小**以倾向配图。默认 `400`。 |
| `include_images` | 是否在结果中附带整页 PNG 的 base64；默认 `false`。开启会显著增大返回体，仅在确有视觉阅读需求时使用。 |
| `max_chars` | 每个 PDF 条目里 `text` 字段的最大字符数（截断），默认 `8000`，范围 `500`–`40000`。 |
| `max_json_chars` | 整段 JSON 输出字符上限，默认 `48000`；超出时 Runner 可能去掉图片或进一步截断 `text`（返回中带 `_truncated` / `_images_omitted` 等提示字段）。 |

### 成功时 JSON 字段（摘要）

响应由工具序列化为 JSON 字符串。典型成功形态：

- `items`：数组；每项含 `source`、`filename`、`text`（可能截断）、`images`（base64 列表，默认可为空）、`stats`（如 `text_chars`、`image_count`）。
- 若输出被压缩：可能出现 `_truncated`、`_truncation_note`、`_images_omitted`、`_omission_reason` 等元字段——以实际返回为准。

### 失败时

- 常见形式：`{"error": "<原因>"}`（例如未提供任何 PDF 源、文件不存在、超过大小限制、页码无效、未安装 pymupdf 等）。
- 请阅读 `error` 原文调整路径、URL、`pages` 或环境依赖，不要假装已成功抽取。

### 推荐工作流

1. 若用户给的是相对路径：按 Runner 说明以 `skill_dir` 为基准先 `read_file` 确认位置，或让用户/上文提供**绝对路径**后再传 `pdf`。
2. 默认 **`include_images=false`**，先取文本；若正文过短或明显是扫描件再考虑开启图片或调低 `min_text_chars`。
3. 调用 `extract_pdf`，解析 JSON；若存在 `error`，向用户说明原因或下一步。
4. 用 `finish` 汇总要点，可注明来源 `filename` / `source`。

### 禁止

- 不要声称已读取 PDF 却未在当轮产生 `extract_pdf` 工具调用记录。
- 不要对超大返回体反复开启 `include_images` 又抱怨上下文爆炸；应缩小 `pages`、`max_pages` 或先用纯文本。

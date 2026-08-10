---
name: read-code
description: 根据用户的自然语言描述或模糊线索，通过 grep、glob、readline_in_range、lsp 组合搜索，定位并阅读本地代码，基于真实代码实现回答问题。
---

## 核心目标

通过工具阅读真实代码实现，智能分析后回答用户问题。**结论必须来自实际读到的代码**（必要时辅以项目内文档），禁止凭空编造实现细节。

问题可以是技术实现或业务语义——按用户给出的线索去定位代码即可，不必先给问题贴「探索/定向」标签。

## 能力边界

- **适用**：需基于本地仓库真实代码作答；用户可能只给自然语言/业务说法，或已给路径/符号/报错栈。
- **不适用**：联网搜索、执行命令、修改代码；大规模重构应使用其他 skill。

## 可用工具

`read_file` **不可用**。可用：`glob`、`grep`、`lsp`、`readline_in_range`（及 `finish`）。参数以工具 schema 为准。

| 要点 | 说明 |
|------|------|
| 起步 | 问题笼统、无线索 → 先 `glob(**/*)` 摸底，再 **`grep` 关键词/协议词收敛** 后阅读（禁止默认只扫 `**/*.go`）；已有路径/符号 → **禁止**先全景 glob，直接对该文件 `documentSymbol`（优先带 `symbol_name`/`line`）或 `grep` |
| 宽问题 | 「整体原理 / HTTP·MCP 访问方式 / 怎么工作 / 如何注册发现」等：先 `glob`；**必须先 `grep` 收敛**（`MCP\|FastAPI\|@app\|/search\|--run\|resource://` 等），再对命中符号 `documentSymbol(symbol_name=...)` → `readline`。**禁止**无焦点地对入口文件 `documentSymbol` 后 `readline(1..EOF)` 整文件扫读 |
| 边界 | 源码 `readline` 的 start/end 必须来自 `documentSymbol` 的 **符号** `Lines X-Y`（优先函数/方法，不要用整文件类当「一窗」）；goToDefinition 的 range 只覆盖符号名，不能当 end |
| 大文件 | `documentSymbol`：默认先去掉噪音符号；**传了 `symbol_name`/`line` 则始终聚焦该子树**（预算内也收窄）；未传焦点且剪枝后大纲 ≤ 预算则原样返回；超预算且无焦点才截断（默认预算见 `DOC_SYMBOL_FILTER_MAX_CHARS_DEFAULT`=10000）。源码近全文件读 / 无焦点从第 1 行大窗会被工具拒绝 |
| 非源码 | md/toml/yaml/json 可直接 `readline`，无需先验 lsp（过长仍按窗翻页；勿把 README 当唯一依据） |
| 轮次 | `lsp` 与 `readline` 分两轮；优先传 `symbol_name`（SDK 算 character；对 documentSymbol 则作大纲过滤） |
| 禁止 | 对源码用 `grep(".")` 倾倒全文；禁止一次读超大窗口（默认最多约 1000 行）；**禁止把整份源码（1..EOF / ≥80% 文件）当探索手段**；**能用 `findReferences` / `incomingCalls` 取引用时，绝对禁止用 grep 猜引用清单**；宽问题禁止「glob 后无焦点扫读大半个仓库」 |
| 拆窗 | 已有 **符号** `Lines X-Y` 且 `Y-X+1 ≤ max_lines` → **第一次**就必须 `start=X, end=Y` 一次读完；**禁止**「先读开头再翻页」。该规则**不适用于**「从 1 读到文件末尾」。仅当跨度更大才拆窗，且每窗接近 max_lines（可略保守如 800～1000），禁止百行级碎拆 |

## 宽问题探索指引（按需规划）

当用户问整体架构、对外访问方式（HTTP/MCP）、工作原理、注册/发现/协作流程，或未给出具体文件/符号时，按仓库规模与线索自行规划，目标是**尽快用 grep 钉住 2～5 个符号并只读其正文**，而不是机械整文件扫读。

1. **先摸底**：`glob(**/*)` 了解语言与目录；禁止默认只扫单一后缀。
2. **再 grep（宽问题默认要做）**：
   - **必须 grep**：问协议/入口/路由/MCP/HTTP/注册发现，或文件多、入口不清。
   - **可跳过 grep**：用户已点名具体路径+符号（或明确函数名），可直接对该符号 `documentSymbol(symbol_name=...)`。
   - **不要**仅因看到 `server.py` / `main.go` 就跳过 grep 并整文件读。
3. **grep 用法**：底层是 **ripgrep 正则**；见下方「grep 与正则」；可 `files_with_matches` 再 `content`；避免无意义的 `grep(".")`。
4. **禁止批量扫读 / 整文件探索**：不得对 glob 列表里大多数源码无焦点 `documentSymbol`；不得 `readline(start=1, end=文件末尾)` 或覆盖 ≥80% 行数当探索手段（工具会拒绝）。
5. **带焦点再读**：`documentSymbol(symbol_name=命中符号)` → `readline` 只读该符号 `Lines X-Y`（一窗 = 函数/路由 handler，不是整个 `server.py`）。README/配置可少量直读作补充，不能代替核心源码。
6. **与引用约束不冲突**：探索可用 grep **定位入口**；问「谁引用了 X」时仍必须用 `findReferences` / `incomingCalls`，不得用 grep 当引用清单。

**反例（必须避免）**：
- `a2a_tasks` Lines 4676-5124（449 行 ≤ 1000）→ 正确是一次 `readline(start=4676, end=5124)`；错误是拆成 4676-4800 / …
- `server.py` 356 行 → 错误：`documentSymbol`（无过滤）后 `readline(1, 356)`；正确：`grep "mcp-server|api-server|@app|FastMCP"` → 对命中函数 `documentSymbol(symbol_name=...)` → 只读该函数边界。

- **glob**：全景用 `**/*` 或多后缀；已有精确路径时不要全景扫。
- **grep**：见下一节「grep 与正则」。`content` 每行 `路径:行号:内容`，供 lsp 取 filePath/line/symbol_name；注释/import 行不要直接喂 lsp。**不得**用 grep 命中替代 `findReferences` / `incomingCalls` 的引用结果。
- **lsp**：需 `SKILL_SDK_LSP_SERVERS`；`documentSymbol` 输出 `符号 (类型) - Lines X-Y`（已 1-based）。大文件务必传 `symbol_name` 和/或 `line` 做客户端过滤，只把命中子树返回模型。
- **readline_in_range**：默认 max≈1000 行。已知**符号**边界且跨度未超限 → 一次传满 `end=Y`；只有跨度超限才拆段。源码禁止用 1..EOF / 近全文件当探索。

## grep 与正则（请主动使用）

`grep` 的 `pattern` 是 **ripgrep 正则**，不是「只能精确匹配单词」。简单关键词、`A|B` 多选、以及带结构的正则都可以用。需要时配合：

- `case_insensitive=true`：忽略大小写（等同 `rg -i`）
- `multiline=true`：跨行匹配
- `glob` / `file_type`：`files_with_matches` 探索可省略。插件会：**归一化** `py`→`*.py`；**纠正**错误语言（Python 仓上的 `**/*.go`→`*.py`）；目录 `content` 无 filter 时**自动**用检测到的源码后缀（避开 md/yaml）。仍禁止未确认语言就手写 `**/*.go`。
- `output_mode`：宽探索**必须先** `files_with_matches`；再对 1～3 个**源码文件**做 `content`。禁止仓库根上直接 `content` + 厨房水槽 pattern。
- **`context_c` 固定为 0**（只返回命中行）。不要传 `context_c` / `context` / `context_before` / `context_after`；需要上下文用 `readline_in_range` / LSP。
- **pattern 必须窄**：`|` 交替项 **≤6**；用专有名词/复合 id/协议串。插件按**形状启发式**丢掉过宽项（短裸词、短 `/path`、短 `--flag`、常见 ops 词），**不**按各语言关键字黑名单。大纲用 `documentSymbol`。
- **禁止**把 `http|serve|run|port|host` 这类泛词和专有名词搅在一起做全仓 content。宜用少量具体词：如 `mcp-server|api-server|FastMCP|resource://|/search`
- 宽 pattern 会命中文档/脚本——先看文件列表再精读源码；确认语言后可加 `glob="*.py"`

### 通俗例子（按目的选）

| 你想找什么 | 可以怎么写 `pattern` | 说明 |
|-----------|----------------------|------|
| 几个相关词任一命中 | `register\|discover\|AgentCard` | `\|` =「或」，最常用；≤6 项 |
| 对外 HTTP/MCP 入口 | `mcp-server\|api-server\|FastMCP\|resource://\|/search` | **禁止**短裸词 / 短 `/api` / 短 `--host`；≤6 项 |
| 整词，少误伤 | `\bcleanup_expired\b` | `\b` = 单词边界 |
| 某个函数定义（任意语言） | 带**名字**的定义型正则，或直接 `documentSymbol` | **禁止**裸 `def `|`func `|`fn ` 等短词当 pattern |
| Go 方法 | `func\s+\(.*\)\s*Cleanup` | 粗匹配 `func (x *T) Cleanup` |
| 调用某函数 | `CleanupService\(` 或 `\bcleanup_expired\s*\(` | 带 `(` 更像调用 |
| 大小写不敏感 | pattern=`cleanup` + `case_insensitive=true` | |
| 配置/键名 | `expert_agents\|agent_heartbeats` | |
| 字面量花括号（Go 等） | `interface\\{\\}` | `{` `}` 常要转义 |

**建议**：

1. 宽探索：先 **不带 glob** + **`files_with_matches`**；再对命中源码 `content` 或 `documentSymbol`。
2. **禁止**未确认语言时默认 `glob="**/*.go"` / `**/*.{go,ts,js}`。
3. **禁止**全仓 `content` + `http|serve|run|port|host|…`（插件会降级为 files_with_matches 并返回 hint）。
4. **禁止** content 里塞短裸词 / 短 path / 短 flag 凑命中（插件会按形状丢掉并 hint）；已知符号优先带名字的正则或 `documentSymbol`。
5. **禁止** `pattern="."` / `".*"` 倾倒全文；引用清单仍走 LSP。
6. 若结果带 `hint`（错误 glob / 过宽 pattern 被收窄或降级）→ **按 hint 收窄后重试**，不要改去硬啃文件。

## 引用约束（必须遵守）

问「在哪里被使用 / 引用点 / references / 被哪些地方调用」时：

1. **必须**用 `lsp findReferences`（列全部引用）或 `lsp incomingCalls`（只列调用方）。
2. **绝对禁止**用 `grep` 文本命中来猜测、拼凑或当作最终引用清单（即使用户没写「不要只靠 grep」）。
3. `grep` / `workspaceSymbol` **仅允许**在尚不知定义位置时，用来拿到 `filePath + line + symbol_name`，拿到后立刻转 LSP；不得在 grep 后直接 `finish`。
4. 仅当 LSP 明确失败/不可用时，才允许降级为 grep + readline，并在答案中说明已降级。

## LSP 操作选择决策规则（必须遵守）

按用户意图选择 `operation`，禁止混淆。

### 决策表

| 用户意图 | 应使用的 LSP operation | 说明 |
|---------|----------------------|------|
| X 的定义/怎么实现/完整实现 | goToDefinition → documentSymbol(symbol_name=X) | 跨文件定位 + **过滤后**完整边界 Lines X-Y |
| 文件有哪些函数/类、文件大纲/overview | `documentSymbol`（无过滤） | 只需 filePath；**仅概览场景**才全量 |
| X 在哪里被使用、引用、references | **必须** `findReferences` | **禁止** grep 猜引用；「谁调用了 X」用 incomingCalls |
| 接口有哪些实现 | `goToImplementation` | |
| 类型/签名/文档注释 | `hover` | 无行号范围 |
| 按名搜符号、不知在哪个文件 | `workspaceSymbol` | `symbol_name`=query；`file_path` 可为仓库根目录 |
| 谁调用了 X | `prepareCallHierarchy` → `incomingCalls` | 只查找调用关系；**禁止**用 grep 猜调用方 |
| X 内部调用了谁、调用链 | `prepareCallHierarchy` → `outgoingCalls` | |

### 关键区分

- **goToDefinition vs documentSymbol**：goToDefinition 跨文件定位（range 不含函数体）；documentSymbol 取符号**完整边界**供 readline。已知符号名时 documentSymbol **必须**带 `symbol_name`（可选再加 `line`），禁止为单个符号去拉全文件大纲。
- **goToDefinition vs findReferences**：前者问 **"这个符号本身是什么"**；后者问 **"这个符号在哪些地方被提到了"**；「谁调用」用 incomingCalls。
- **findReferences vs incomingCalls**：findReferences 含赋值/类型/注释等所有引用；incomingCalls **只返回调用关系**。
- **incomingCalls vs outgoingCalls**：谁调用了它（反向） vs 它调用了谁（正向）。
- **findReferences/incomingCalls vs grep**：前两者是符号级引用；grep 是文本搜索。能走前者时**决定不能**用后者猜引用。

### 错误示例

- "ProcessData 怎么实现的" → **应该用 `goToDefinition`** + `documentSymbol`（不能只用其一）。
- "这个文件有哪些函数" → **应该用 `documentSymbol`**，不应该用 `goToDefinition`。
- "`Validate` 被哪些地方调用了 / 引用点" → **必须** `findReferences`（「哪些函数调用」用 incomingCalls）；**禁止** grep → documentSymbol → readline 当引用清单。
- "DataProcessor 接口有哪些实现" → **应该用 `goToImplementation`**。
- "`Process` 内部调用了哪些函数" → **应该用 `prepareCallHierarchy` → `outgoingCalls`**。
- "`Process` 被哪些函数调用了" → **应该用 `prepareCallHierarchy` → `incomingCalls`**，不应该用 `findReferences`，更不能只用 grep。

## 正确流程示例（可以参考）

### 示例 1：笼统类型的问题（glob → grep → documentSymbol → readline）

**适用**：问题很宽、没有具体文件路径或符号——如「这个仓库整体怎么工作」「对外提供哪些 HTTP/MCP 访问方式」「Agent 如何注册/发现」。

**规划要点**：先 glob；**宽问题默认 grep**；再只读命中符号。

```
① glob(pattern="**/*", path="<仓库根>")
   ← 禁止默认只扫 **/*.go；过窄/截断则补 glob("**/*.{py,go,ts,js}") 等
   ← 此步只摸底语言/目录；不得据此开始批量 documentSymbol / 整文件 readline

② 关键词 / 正则收敛（宽问题默认做；**第一次不要加 glob**；优先 files_with_matches）：
   grep(pattern="mcp-server|api-server|FastMCP|@app\\.|/search|resource://",
        output_mode="files_with_matches")
   ← 从命中里挑源码（如 server.py），再 content；不要一上来 content 灌 md/yaml
   ← **禁止**短裸词 / 短 `/path` / 短 `--flag` 灌进 pattern；≤6 个专有词即可
   ← 已确认是 Python 仓后再可选 glob="*.py"；禁止默认 **/*.go / *.{go,ts,js}
   ← 若返回 hint 说 filter/pattern 过宽：按 hint 丢掉泛词后重试，勿改硬读文件
   ← pattern 支持完整正则；见「grep 与正则」

③ 对 grep 命中的符号（通常 2～5 个函数/路由）：
   lsp(operation="documentSymbol", filePath="<源码>", symbol_name="<符号>")
   ← 必须带 symbol_name（或 line）；禁止无焦点全量大纲后整文件读
   ← 禁止对 glob 列表里大半文件无焦点 documentSymbol

④ readline_in_range(file_path=..., start=X, end=Y)
   ← 边界来自③的**符号** Lines；若 Y-X+1 ≤ max_lines 则一次读完
   ← 禁止 readline(1, 文件末尾) 或覆盖大半个源文件
   非源码（README.md / pyproject.toml）可直接 readline 作补充；过长同样按窗翻页

⑤ 需要时再 grep / goToDefinition / findReferences；基于源码作答
   ← 禁止只根据 README/YAML 或只根据 documentSymbol 大纲下结论
```

### 示例 2：定向路径（问题很具体，比如包含了具体文件名的某一个函数的功能分析）

**适用**："这个功能怎么实现的" / 已有路径或关键词。

```
① 仅有关键词 → grep(pattern="...", output_mode="content")
   已有路径+符号 → 跳过全景；需要跨文件时先 goToDefinition
   ← 已有路径+符号时禁止先 glob(**/*)
   ← 超大文件可传 symbol_name 作为超预算时的聚焦提示

② 需要跨文件时：
   lsp(operation="goToDefinition", filePath=..., line=..., symbol_name="...")

③ lsp(operation="documentSymbol", filePath=<定义所在文件>,
        symbol_name="<目标符号>", line=<命中行可选>)
   → 只返回命中节点(+祖先)的 Lines X-Y，不倾倒全文件大纲

④ readline_in_range(file_path=..., start=X, end=Y)
   ← 若 Y-X+1 ≤ max_lines：第一次就 start=X end=Y 读完
     （例：4676-5124=449 行 → 一次调用；禁止先读到 4800 再翻页）
   ← 若更大：按接近 max_lines 的窗口连续读（可用 next_start），禁止百行级碎拆
   ← 「方法很大」不等于要碎拆：只要 ≤ max_lines 就整段读
```

### 示例 3：概览路径

**适用**："看看这个文件的整体结构" / 文件大纲。

```
① lsp(operation="documentSymbol", filePath="main.go")
   ← 仅此场景可无过滤；若只要某个符号边界，改走示例 2 并传 symbol_name
② 按需 readline_in_range(..., start=<Lines X>, end=<Lines Y>)
   ← 边界来自①；跨度 ≤ max_lines 一次读；更大则贴近 max_lines 拆窗
```

### 示例 4：引用查找

**适用**：X 在哪里被使用 / 引用点 / references。  
**约束**：能调 `findReferences` 时，**决定不能**用 grep 猜引用清单。

```
① 若尚不知定义位置：grep / workspaceSymbol 只为拿到 filePath + line + symbol_name
   ← grep 命中 ≠ 引用清单；禁止在此 finish
② lsp(operation="findReferences", filePath=..., line=..., symbol_name="...")
   ← 引用清单以本次 LSP 结果为准
③ 需要对引用点说明场景时：documentSymbol(symbol_name=...) → readline
```

### 示例 5：调用链分析

**适用**："某个函数的调用链是什么样的" / 谁调用了它 / 它调用了谁 / 调用关系。  
**约束**：能调 `incomingCalls` / `outgoingCalls` 时，**决定不能**用 grep 猜调用关系。

```
① 若尚不知位置：grep 仅定位 filePath + line + symbol_name
② lsp(operation="prepareCallHierarchy", filePath=..., line=..., symbol_name="...")
③ 问「它调用了谁」→ lsp(operation="outgoingCalls", ...)
   问「谁调用了它」→ lsp(operation="incomingCalls", ...)
   （也可直接调 incomingCalls/outgoingCalls，插件内部会自动 prepare）
```

### 示例 6：接口实现

**适用**：谁实现了接口 X。

```
① documentSymbol 或 grep 定位接口声明行
② lsp(operation="goToImplementation", filePath=..., line=..., symbol_name="...")
③ 按返回位置 documentSymbol(symbol_name=...) → readline
```

### 示例 7：按名搜符号 / 看类型

**适用**：不知在哪个文件 → workspaceSymbol；只要签名 → hover。

```
lsp(operation="workspaceSymbol", file_path="<仓库根或任意源文件>", symbol_name="Foo")
   ← symbol_name 作为搜索 query；file_path 可为目录（仅用于选语言服务器）
lsp(operation="hover", filePath=..., line=..., symbol_name="...")  # 无 Lines，不能代替 readline
```

## 提示与注意事项

1. 回答必须基于真实代码（须有关键路径的 readline 正文，不能只靠 documentSymbol 大纲推断）。
2. 宽问题：glob → **grep** → 焦点 documentSymbol → 符号级 readline；有路径/符号不要先全景 glob。
3. 能用 `findReferences` / `incomingCalls` 时，**决定不能**用 grep 猜引用或调用方；grep 只做定位，LSP 失败才降级。
4. 源码 readline 边界来自 documentSymbol 的**符号** Lines；跨度 ≤ max_lines 则**第一次**就整段读完（不要先读开头）；**禁止**把「整段读完」理解成读整个源文件。更大才拆窗且单窗贴近上限；非源码可直接读、过长同样翻页。
5. documentSymbol：默认省略噪音；**有 `symbol_name`/`line` 时始终聚焦**；无焦点且剪枝后能放进预算才原样返回；超预算无焦点才截断（默认 10000 字符）。
6. lsp 与 readline 分两轮；源码 LSP 不可用时再降级 grep + readline。
7. 读够后调用 `finish`。

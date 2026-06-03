---
name: read-code
description: 根据用户的自然语言描述或模糊线索，通过 grep、glob、readline_in_range、lsp 四个工具组合搜索，定位并阅读本地代码。
---

## 能力边界

- **适用**：用户用自然语言描述一个代码片段、函数名、类名、报错信息、或模糊的关键词，需要在本地仓库或工作目录中找到对应的文件和实现。
- **不适用**：不需要联网搜索、不需要执行命令、不需要修改代码。如果需要大规模重构或自动化修改，应使用其他 skill。

## 可用工具

本 skill 被选中后，ReAct 工具列表中会包含以下工具（由 Runner 自动注册）。通过这些工具完成代码定位与阅读，不要在对话中编造代码。

> **代码读取（极其重要）**：本 skill 下 **`read_file` 工具不可用**。你可以使用以下工具来定位和阅读代码：
>
> - `glob` — 按路径模式匹配文件
> - `grep` — 按正则搜索文件内容（`files_with_matches` / `content` / `count`）
> - `lsp` — 代码智能分析（`goToDefinition` / `documentSymbol` / `findReferences` / `goToImplementation` / `hover` / `workspaceSymbol` / 调用层次等）
> - `readline_in_range` — 按行范围读取文件
>
> 这些工具的使用顺序和组合由你根据实际情况自主规划。
>
> **关键约束**：readline_in_range 的 start 和 end 必须来自 documentSymbol 返回的完整行号范围（Lines X-Y），禁止自己猜测或使用均匀切片。goToDefinition 返回的 range 只覆盖符号名称所在位置（start 和 end 通常在同一行），不能直接用于 readline_in_range 的 end 参数。
>
> **注意**：`lsp` 和 `readline_in_range` 需要分两轮执行——先调 `lsp` 等结果返回，下一轮再根据返回的行号调 `readline_in_range`。`end` 可以省略，此时一直读到文件末尾；如果已从 `lsp` 获得精确边界，传入 `end` 可避免读取不必要的尾部内容。
>
> **符号定位**：对于需要精确位置的 LSP 操作，推荐传入 `symbol_name` 参数（函数名/方法名/变量名），SDK 会自动在指定行中计算 `character` 偏移量，避免手动计算的偏差。

## LSP 操作选择决策规则（必须遵守）

根据用户的意图，严格按以下规则选择 `lsp` 的 `operation` 参数。**禁止混淆使用**：该走 `goToDefinition` 就必须走，该走 `documentSymbol` 就必须走，该走 `findReferences` 就必须走。

### 决策表

| 用户意图 | 应使用的 LSP operation | 说明 |
|---------|----------------------|------|
| "X 的定义在哪里" / "X 是怎么实现的" / "跳到 X 的定义处" / "看 X 的代码块" / "X 的完整实现" | goToDefinition → documentSymbol | goToDefinition 负责跨文件定位（找到定义所在文件及符号名行号），documentSymbol 负责获取该符号的完整边界（Lines X-Y）。两步配合才能拿到完整实现。 |
| "这个文件有哪些函数/类/方法" / "看看文件结构" / "文件大纲" / "文件里有什么" / "overview / 概览" / "列出所有符号" | **`documentSymbol`** | 只需要 `filePath`，不需要 `line`，返回整个文件所有符号的层级结构及其 `Lines X-Y`。适合不知道文件里有什么时的结构探索。 |
| "X 在哪里被使用了" / "X 的引用有哪些" / "查找 X 的所有使用" / "usages of X" / "references to X" | **`findReferences`** | 返回项目中所有引用该符号的位置列表（文件 + 行号）。适合了解符号在哪些地方被提及（包括变量赋值、类型引用等）。如果要问的是"哪些函数调用了 X"，请用下方的 `incomingCalls`。 |
| "X 接口有哪些实现" / "谁实现了 X" / "implementations of X" | **`goToImplementation`** | 返回所有实现该接口的位置。适合接口 → 实现的跳转。 |
| "X 的类型/签名是什么" / "X 的文档注释" / "hover X" | **`hover`** | 轻量级信息探查，不返回行号范围。 |
| "搜索名为 X 的符号" / "在整个仓库中找 X" / 不知道符号在哪个文件 | **`workspaceSymbol`** | 跨文件模糊搜索，只需要符号名。 |
| "谁调用了 X" / "X 的调用者有哪些" / "X 被谁调用" | **`prepareCallHierarchy` → `incomingCalls`** | 两步操作：先 prepareCallHierarchy 获取调用层次节点，再 incomingCalls 找到所有调用该函数的位置。与 findReferences 不同，incomingCalls 只查找函数/方法调用关系，不包含变量引用等。 |
| "X 内部调用了哪些函数" / "X 的调用链是什么样的" / "从 X 往下调用到了什么" | **`prepareCallHierarchy` → `outgoingCalls`** | 两步操作：先 prepareCallHierarchy 获取调用层次节点，再 outgoingCalls 正向展开该函数内部的调用。适合追踪一条调用链路。

### 关键区分

- **goToDefinition vs documentSymbol**：
  - `goToDefinition`：你是跨文件定位——调用点在 A 文件（从 grep content 拿到），但定义可能在 B 文件（接口实现、第三方库、父类方法等）。goToDefinition 利用 LSP 的类型解析能力找到真正的定义文件和符号名所在行号。它返回的 range 只覆盖符号名称（start 和 end 通常在同一行），不包含函数体/类体。
  - `documentSymbol`：你是获取符号完整边界——已经知道目标文件，需要拿到某个符号的精确起止行号（从函数签名到闭合花括号），以便用 readline_in_range 读取完整实现。这是完整边界的唯一可靠来源。

- **goToDefinition vs findReferences**：
  - `goToDefinition`：用户问的是 **"这个符号本身是什么"**/定义在哪。
  - `findReferences`：用户问的是 **"这个符号在哪些地方被提到了"**/在哪里被引用（包括变量赋值、类型引用、注释中的提及等）。如果要问"谁调用了它"，应使用 `incomingCalls`。

- **findReferences vs incomingCalls**：
  - `findReferences`：返回所有引用该符号的位置（包括变量赋值、类型引用、注释中的引用等）。范围广，适合了解"这个符号在整个项目中被提到的地方"。
  - `incomingCalls`：只返回函数/方法级别的调用关系，即"哪些函数直接调用了这个函数"。更精确，适合调用链追踪。

- **incomingCalls vs outgoingCalls**：
  - `incomingCalls`：**谁调用了它**——反向追溯调用者。问你"这个函数被谁调用了"。
  - `outgoingCalls`：**它调用了谁**——正向展开调用链。问你"这个函数内部调用了哪些函数"。

### 错误示例

- 用户问 "看看 ProcessData 这个函数是怎么实现的" → 应该用 goToDefinition + documentSymbol。只用 goToDefinition 只能拿到函数名所在行，读不到完整实现；只用 documentSymbol 的话，如果定义在别的文件就找不到。两者必须配合。
- 用户问 "这个文件有哪些函数" → **应该用 `documentSymbol`**，不应该用 `goToDefinition`。
- 用户问 "`Validate` 方法被哪些地方调用了" → **应该用 `findReferences`**，不应该用 `grep` 搜索。
- 用户问 "DataProcessor 接口有哪些实现" → **应该用 `goToImplementation`**，不应该用 `findReferences`。
- 用户问 "`Process` 函数内部调用了哪些函数" → **应该用 `prepareCallHierarchy` → `outgoingCalls`**，不应该直接用 `outgoingCalls` 或 `findReferences`。
- 用户问 "`Process` 函数被哪些函数调用了" → **应该用 `prepareCallHierarchy` → `incomingCalls`**，不应该用 `findReferences`（findReferences 返回所有引用，不只是函数调用）。

### 正确流程示例

**流程 A：定向路径（`grep` → `goToDefinition` → `documentSymbol` → `readline_in_range`）**
```
① grep(pattern="ProcessData", output_mode="content", path="main.go")
   → main.go:40:func TransformData(data string) string {

② 行内容 = "func TransformData(data string) string {"
   提取 symbol_name = "TransformData"

③ lsp(operation="goToDefinition", filePath="main.go", line=40, symbol_name="TransformData")
   → SDK 自动在行内容中定位 TransformData 位置（character=6），调 LSP
   → uri=main.go, range.start.line=39, range.end.line=39 (0-based)
   → 确认定义在 main.go，符号名在第 40 行（1-based）

④ lsp(operation="documentSymbol", filePath="main.go")
   → TransformData (Function) - Lines 40-42

⑤ readline_in_range(file_path="main.go", start=40, end=42)
```

**流程 B：概览路径（`documentSymbol` → `readline_in_range`）**
```
① lsp(operation="documentSymbol", filePath="main.go")
   → DataProcessor (Interface) - Lines 7-10
   → DefaultProcessor (Struct) - Lines 13-16
   → NewDefaultProcessor (Function) - Lines 19-25
   ...
② readline_in_range(file_path="main.go", start=7, end=10)
```

**流程 C：引用查找（`grep` → `findReferences`）**
```
① grep(pattern="processor.Validate", output_mode="content")
   → main.go:62:    validated := h.processor.Validate(input)
② lsp(operation="findReferences", filePath="main.go", line=62, symbol_name="Validate")
   → SDK 自动在行内容中定位 Validate 位置，调 LSP
   → Found 3 references in 2 files...
```

**流程 D：调用链分析（`grep` → `prepareCallHierarchy` → `outgoingCalls` / `incomingCalls`）**
```
① grep(pattern="ProcessData", output_mode="content")
   → main.go:42:func (d *DataProcessor) ProcessData(data string) (string, error) {

② 行内容 = "func (d *DataProcessor) ProcessData(data string) (string, error) {"
   提取 symbol_name = "ProcessData"

③ lsp(operation="prepareCallHierarchy", filePath="main.go", line=42, symbol_name="ProcessData")
   → SDK 自动在行内容中定位 ProcessData 位置，调 LSP
   → ProcessData (Method) / main.go / Lines 42-47

④ lsp(operation="outgoingCalls", filePath="main.go", line=42, symbol_name="ProcessData")
   → ProcessData 调用了:
     TransformData (Function) - Lines 39-41 [called from: 44:14]
     ValidateInput (Function) - Lines 50-55 [called from: 45:12]

⑤ 用户问"谁调用了 ProcessData" → 改为:
  lsp(operation="incomingCalls", filePath="main.go", line=42, symbol_name="ProcessData")
  → ProcessData 被调用:
    HandleRequest (Method) - Lines 62-75 [calls at: 65:10]
```

### 1. `glob` — 按路径模式匹配文件

| 参数 | 说明 |
|------|------|
| `pattern` | glob 模式，如 `**/*.ts`、`src/**/*.go`、`**/service/*.py` |
| `path` | 可选搜索根目录，省略则为当前工作目录 |

- 返回匹配的文件路径列表（按修改时间排序，最新在前）。
- 适合在不确定文件名字时先用宽模式（如 `**/*.ts`、`src/**/*.go`）做一次目录结构探测。

### 2. `grep` — 按正则搜索文件内容

| 参数 | 说明 |
|------|------|
| `pattern` | ripgrep 正则表达式（不是 grep 默认语法的 `-E` 模式） |
| `path` | 可选搜索路径，省略则为当前工作目录 |
| `glob` | 可选 glob 过滤（如 `*.py`、`**/*_test.go`），映射到多个 `rg --glob` |
| `output_mode` | `"files_with_matches"`（默认，只返回路径）、`"content"`（返回命中行及上下文）、`"count"`（返回每个文件的命中数） |
| `context` / `context_c` | 当 `output_mode="content"` 时，每条匹配前后额外显示的上下文行数 |
| `line_numbers` | 当 `output_mode="content"` 时是否显示行号（默认 true） |
| `case_insensitive` | 是否忽略大小写（默认 false） |
| `head_limit` | 返回结果条数上限（默认 250，0 为不限） |
| `offset` | 分页偏移量（默认 0） |

`grep` 是你在定向路径中的**第一步**，提供后续所有操作所需的文件路径和行号。三种 `output_mode` 各有不同的用途和产出格式，按场景选用。

#### `output_mode="files_with_matches"` — 只返回文件路径

返回 JSON：`{"mode": "files_with_matches", "filenames": ["path/file1.go", "path/file2.go"], "numFiles": N}`。

只返回**文件名列表**（按修改时间倒序），不带行号或内容。

**用途**：在不确定文件位置时快速圈定范围。产出的文件路径列表可以直接作为后续 `grep content` 的 `path` 参数，或作为 `lsp` 的 `filePath` 参数。

**示例**：
```
grep(pattern="DataProcessor", output_mode="files_with_matches")
→ {"filenames": ["main.go", "handler.go"], "numFiles": 2}
```

#### `output_mode="content"` — 返回匹配行及上下文（最常用，核心管道数据源）

返回 JSON：`{"mode": "content", "content": "file.go:49:  // comment\nfile.go:50:  func Foo(...)...", "numLines": N}`。

`content` 字段中的每一行格式为 **`{相对路径}:{行号}:{该行内容}`**，这是你和 `lsp` 之间的**核心桥梁数据**。

> **❗ 判断思维：grep 命中的行不一定是"定义行"——你需要自行判断下一步走哪条路。**
>
> | grep 匹配到的行内容 | 属于什么 | 应该做什么 |
> |---|---|---|
> | func SendMessage(ctx ... / def process_data(... / class Handler: | 定义/声明 | 如果模型判断定义和调用在同一文件，可直接对你已掌握的 filePath 调 documentSymbol 获取完整边界；如果可能在其他文件（接口实现、父类方法），仍需 goToDefinition 跨文件定位后再调 documentSymbol |
> | `result = client.SendMessage(ctx)` / `h.Process(input)` | **调用/引用** | 同样可以调 `goToDefinition`——LSP 能从这个调用处跳到定义 |
> | `// SendMessage 用于发送消息` / `# reference: ProcessData` / `import "pkg"` | **注释/导入等非代码行** | **不要使用本行调 LSP**。换一个 grep pattern 搜函数名本身，或者改用 `documentSymbol` 从文件结构中定位 |
>
> 简而言之：如果 `grep content` 命中的是一行**注释或 import**，不要用它传给 `lsp`。重新搜一个更精确的 pattern 或者走 `documentSymbol` 路径。

##### 如何从 `content` 输出中提取数据喂给 `lsp` 和 `readline_in_range`

`content` 返回的每行形如 `main.go:38:func TransformData(data string) string {`，你可以直接拆出：

| 从 content 行中提取 | 值 | 传递给 |
|---|---|---|
| `{相对路径}` | `main.go` | `lsp` 的 `filePath` / `readline_in_range` 的 `file_path` |
| `{行号}` | `38` | `lsp` 的 `line` |
| `{该行内容}` | `func Transform...` | 用来提取 `symbol_name` |

> **推荐方式：使用 `symbol_name` 参数（SDK 自动计算位置）**
>
> 对于需要精确位置的 LSP 操作（`goToDefinition`、`findReferences`、`hover`、`goToImplementation`、`prepareCallHierarchy`、`incomingCalls`、`outgoingCalls`），**强烈建议传入 `symbol_name` 而不是手动计算 `character`**。
>
> SDK 会读取文件指定行，在行内容中自动做 `indexOf` 找到符号名的精确位置，完全消除人工计算的偏差。
>
> ```
> # 推荐（使用 symbol_name，SDK 自动计算）
> lsp(operation="goToDefinition", filePath="main.go", line=38, symbol_name="TransformData")
>
> # 不推荐（手动计算 character，容易出错）
> lsp(operation="goToDefinition", filePath="main.go", line=38, character=6)
> ```
>
> **`symbol_name` 就是 `grep content` 命中的那个标识符的名字**（函数名、方法名、变量名等），从行内容中直接识别即可，无需做任何索引计算。例如：
> - 行内容 `func TransformData(data string) string {` → `symbol_name="TransformData"`
> - 行内容 `func (c *client) SendMessageStreaming(ctx context.Context, ...` → `symbol_name="SendMessageStreaming"`
> - 行内容 `result := processor.Validate(input)` → `symbol_name="Validate"`
>
> **`symbol_name` 只对需要位置的操作用效**。`documentSymbol` 和 `workspaceSymbol` 不需要此参数。

##### 各 LSP 操作如何消费 `content` 的数据

- **`goToDefinition`**：需要 `filePath` + `line` + `symbol_name`。`lsp(operation="goToDefinition", filePath="main.go", line=38, symbol_name="TransformData")`
- **`findReferences`**：同样。`lsp(operation="findReferences", filePath="main.go", line=38, symbol_name="TransformData")`
- **`hover`**：同样。`lsp(operation="hover", filePath="main.go", line=38, symbol_name="TransformData")`
- **`goToImplementation`**：同样。`lsp(operation="goToImplementation", filePath="main.go", line=7, symbol_name="DataProcessor")`
- **`prepareCallHierarchy`**：同样。`lsp(operation="prepareCallHierarchy", filePath="main.go", line=42, symbol_name="ProcessData")`
- **`documentSymbol`**：只需要 `filePath`，不需要 line/character/symbol_name。`lsp(operation="documentSymbol", filePath="main.go")`
- **`incomingCalls` / `outgoingCalls`**：需要 `filePath` + `line` + `symbol_name`。SDK 内部会自动完成两步（先 `prepareCallHierarchy` 再展开调用链）。`lsp(operation="outgoingCalls", filePath="main.go", line=42, symbol_name="ProcessData")`

##### content 模式完整示例

```
① grep(pattern="TransformData", output_mode="content", path="main.go")
   → {
       "mode": "content",
       "content": "main.go:38:func TransformData(data string) string {",
       "numLines": 1
     }

② 行内容 = "func TransformData(data string) string {"
   提取 symbol_name = "TransformData"

③ lsp(operation="goToDefinition", filePath="main.go", line=38, symbol_name="TransformData")
   → SDK 自动在行内容中定位 TransformData 位置（character=6），调 LSP
   → uri=main.go, range.start.line=37, range.end.line=37 (0-based)
   → 确认定义在 main.go，符号名在第 38 行（1-based）

④ lsp(operation="documentSymbol", filePath="main.go")
   → TransformData (Function) - Lines 38-42

⑤ readline_in_range(file_path="main.go", start=38, end=42)
```

配合 `context` 参数可获取命中行上下文的额外行（同样带路径和行号前缀），帮助理解代码段全貌。

#### `output_mode="count"` — 分布评估

返回 JSON：`{"mode": "count", "numFiles": N, "numMatches": N, "content": "file.go:12\n"}`。

每个文件的命中次数，不返回具体内容。

**用途**：快速评估某个关键词在项目中的**分散程度和分布密度**，帮助决定是否需要进一步缩小范围后再用 `content` 模式精查。如果在某个文件中命中数特别高（如 >50 次），说明该关键词太宽泛，应换更精确的 `pattern`。

**示例**：
```
grep(pattern="error", output_mode="count")
→ 显示每个文件中的 error 出现次数，判断哪些文件错误处理密集
```

- `path` 可以精确到单个文件（如 `src/foo/bar.go`）来缩小范围。

### 3. `readline_in_range` — 按行范围读取文件

| 参数 | 说明 |
|------|------|
| `file_path` | 文件路径（绝对或相对于 CWD） |
| `start` | 起始行号（1-based，默认 1） |
| `end` | 结束行号（包含，默认 None=读到末尾） |
| `include_line_numbers` | 是否显示行号前缀（默认 true） |

- 行号输出格式类似 `cat -n`，方便在最终答复中准确定位代码位置。
- 适合在通过 `grep` 确定目标的位置后，精确读取某一段代码做详细分析。
- 也适合大文件：只读目标区域而不是整个文件。
- **`end` 参数可选（默认读到末尾）**。如果通过 `lsp` 获取了行号范围，需要将 LSP 返回的 0-based 行号 +1 转为 1-based 后传入 `start`/`end`，可精确控制读取范围。`lsp` 和 `readline_in_range` 需要分两轮执行——先调 `lsp` 等结果，下一轮再调 `readline_in_range`。

### 4. `lsp` — LSP 代码智能（定义跳转、引用、符号等）

| 参数 | 说明 |
|------|------|
| `operation` | `goToDefinition`、`findReferences`、`hover`、`documentSymbol`、`workspaceSymbol`、`goToImplementation`、`prepareCallHierarchy`、`incomingCalls`、`outgoingCalls` |
| `filePath` | 操作的目标文件路径 |
| `line` | 1-based 行号（与编辑器和 grep 输出一致） |
| `symbol_name` | **[推荐]** 目标标识符名称。SDK 会自动在指定行内计算 `character` 偏移量。可用于所有 position-dependent 操作（`goToDefinition`、`findReferences`、`hover`、`goToImplementation`、`prepareCallHierarchy`、`incomingCalls`、`outgoingCalls`）。对 `documentSymbol` 和 `workspaceSymbol` 忽略。 |
| `character` | [已废弃] 1-based 列号。建议优先使用 `symbol_name`。 |

- **需要配置 `SKILL_SDK_LSP_SERVERS` 环境变量**（如 gopls、pyright 等 LSP server 的 JSON 配置），否则工具不可用。
- **`workspaceFolder` 可以通过 `WORKSPACE_FOLDER` 环境变量全局覆盖**（适用于所有 LSP server）。例如 `export WORKSPACE_FOLDER=/path/to/go/module`。
- **`documentSymbol` 返回每个符号的完整起止行号**（range.start.line、range.end.line，0-based），+1 转换后可以直接作为 `readline_in_range` 的 `start` 和 `end` 参数。格式化输出中的 `Lines X-Y` 已自动完成 +1 转换，可直接使用。
- **`goToDefinition` 返回的 `range` 只覆盖符号名称所在位置**（0-based，start 和 end 通常在同一行），不包含函数体/类体。它用于跨文件定位和确认符号名行号，不能直接为 `readline_in_range` 提供 `end` 行号。

#### 各操作详解（按使用频率排序）

##### **`goToDefinition`** — 跳转到符号定义
- **做什么**：给定光标所在位置（filePath + line + symbol_name），利用 LSP 的类型解析能力找到该符号的真正定义位置，即使定义在另一个文件、第三方库、接口背后或父类中。返回符号名称所在位置的 range（start 和 end 通常在同一行），不包含函数体/类体。
- **调用前提**：需要知道文件路径和目标行号。行号可以从 `grep content`（输出 `文件:行号:内容`）直接获得。
- **与其他 LSP 操作的区别**：`goToDefinition` 返回的是符号名称所在位置的 `range`（start 和 end 通常在同一行），核心价值是跨文件跳转能力。`documentSymbol` 返回整个符号的完整范围（含函数体/类体）。两者解决的是不同问题：前者回答"定义在哪个文件"，后者回答"这个符号从哪行到哪行"。
- **输出要点**：输出要点：返回 `location`（`uri` + `range`），其中 `range` 包含 `start.line`、`end.line`（0-based，通常为同一行）。完整的符号边界（函数体起止行）必须通过后续的 `documentSymbol` 获取。 `uri` 可能指向另一个文件，拿到后需对该文件调 `documentSymbol`。
- **注意事项**：
  - 如果符号是跨包的（比如引入了别的包的某个函数），`uri` 会是另一个文件的路径，拿到后可以继续用 `readline_in_range` 或 `glob` 定位。
  - 需要把 `uri` 从文件协议格式（`file:///path/to/file.go`）转为普通路径。
  - 推荐传入 `symbol_name`（SDK 会自动计算精确的 character）。`symbol_name` 就是目标标识符的名字，从 grep 命中的行内容中直接提取即可，无需做任何索引运算。

##### **`documentSymbol`** — 文件结构大纲
- **做什么**：传入文件名（无需行号/列号），返回该文件内所有顶层符号的层级结构：每个符号的名称、类型（Class/Function/Method/Variable/Interface/Struct 等）、精确起止行号。
- **典型用法**：这是获取符号完整边界的唯一可靠来源。无论是想了解文件整体结构，还是在定向路径中拿到某个符号的精确起止行号，最终都需要 `documentSymbol` 来提供 `Lines X-Y`。
- **输出要点**：
  - 每个符号包含 `name`、`kind`、`range`（`start.line` / `end.line`，0-based）、`selectionRange`。
  - `range` 是符号的完整范围（含函数体/类体），`selectionRange` 是符号名称本身的范围。
  - 嵌套符号（如类的方法、结构体的字段）在 `children` 字段中递归列出。
  - **格式化输出格式为 `符号名 (类型) - Lines {start_1based}-{end_1based}`**，行号已经 +1 转换过，**可以直接复制到 `readline_in_range` 的 `start` 和 `end` 参数**。
- **拿到输出后下一步做什么**：
  - 从输出中确定你要读的目标符号，复制它的 `Lines X-Y`。
  - 例如输出 `ProcessData (Method) - Lines 50-85`，就对 `readline_in_range(file_path="main.go", start=50, end=85)` 调一次，只读这一段。
  - 如果符号是文件的最后一个符号，`end` 可以省略，直接读到文件末尾。
  - **不要读完整个符号列表后跑去用 `readline(start=1, end=50)` 或 `readline(start=50, end=300)` 这类猜测的切片**。每个符号的边界已经精确给定了，直接用它。
- **注意事项**：返回的行号是 **0-based**，传给 `readline_in_range` 时需要 +1 转为 1-based。格式化输出中已做了 +1 转换。

##### **`findReferences`** — 查找所有引用
- **做什么**：给定光标位置，返回该项目中所有引用了该符号的位置（文件路径 + 行号 + 列号）。
- **典型用法**：想知道一个函数/变量/类型被哪些地方使用/调用。
- **输出要点**：返回一组 `location`，每个包含 `uri` + `range`（至少 `start.line` 和 `start.character`）。
- **注意事项**：
  - 结果通常很多，适合先确认大概范围内有哪些引用，然后选择性地用 `readline_in_range` 或 `grep` 进一步查看上下文。
  - **接口实现的方法引用可能不完整**：如果你查的是 `DefaultProcessor.Validate`（具体实现），LSP 不会返回通过 `DataProcessor` 接口类型的调用（如 `h.processor.Validate(input)` 中 `processor` 是接口类型）。这是因为 LSP 认为调用的是接口方法而非具体实现。**要拿到完整引用，必须查两次 `findReferences`**：
    1. 先查**接口声明**处的方法签名（如 `DataProcessor` 接口中 `Validate(data string) bool` 那一行）。
    2. 再查**具体实现**处的方法定义。
    3. 将两次结果合并去重，才是完整的引用集合。
  - 接口的实现引用（`implements`）在某些 LSP server 中不会被 `findReferences` 覆盖，需要配合 `goToImplementation`。
  - 推荐传入 `symbol_name`（SDK 会自动计算精确的 character），无需手动计算索引。

##### **`goToImplementation`** — 跳转到接口/抽象类的实现
- **做什么**：给定光标所在位置（接口定义或抽象方法），返回所有实现了该接口的具体类型的位置。
- **典型用法**：看到 `interface DataProcessor { ... }`，想找到所有实现了这个接口的 struct。
- **输出要点**：返回一组 `location`（每个实现的文件路径 + 行号范围）。
- **注意事项**：
  - 并非所有 LSP server 都支持此操作。如果不支持，可以降级为 `findReferences` + 手动筛选。
  - 这对于理解"依赖反转"风格的代码特别有价值——接口在 domain 层，实现在 infrastructure 层，一跳就能过去。
  - 推荐传入 `symbol_name`（SDK 会自动计算精确的 character）。例如 `type DataProcessor interface {` → `symbol_name="DataProcessor"`。

##### **`hover`** — 获取类型签名和文档
- **做什么**：给定光标位置，返回该符号的类型签名和文档注释。
- **典型用法**：想快速了解一个函数的参数/返回值类型、或者接口的文档说明，而不需要跳到定义处。
- **输出要点**：返回 `contents`（Markdown 格式的字符串），包含类型信息和 `/** */` 文档注释。
- **注意事项**：hover 不会返回行号范围，所以不能用来喂给 `readline_in_range`。它适合做轻量级探查——先 hover 看一下大概，如果不够再 `goToDefinition`。

##### **`workspaceSymbol`** — 跨文件搜索符号
- **做什么**：传入一个查询字符串（模糊匹配），返回整个工作区中匹配该名称的符号列表。
- **典型用法**：
  - 你知道符号的名字（比如 `TransformData`）但不知道它在哪个文件。
  - 或者你只记得符号名字的一部分。
- **输出要点**：返回一组 `SymbolInformation`，每个包含 `name`、`kind`、`location`（`uri` + `range`）。
- **注意事项**：
  - 不需要 `filePath` / `line` / `character` 参数，只需要知道符号名即可调用。
  - 查询字符串支持模糊匹配，输入大小写敏感（取决于具体 server）。
  - 这是最类似于 IDE "搜索符号"（Ctrl+Shift+O / Cmd+Shift+O）的功能。

##### **`prepareCallHierarchy`** — 准备调用层次数据
- **做什么**：给定光标位置，返回该符号的调用层次初始数据（包含名称、所在文件、行号范围），以供后续 `incomingCalls` / `outgoingCalls` 展开。
- **典型用法**：作为 `incomingCalls` / `outgoingCalls` 的前置步骤。先得到调用层次节点，再选择要展开哪个方向。
- **输出要点**：返回一个或多个 `CallHierarchyItem`，每个包含 `name`、`kind`、`uri`、`range`、`selectionRange`。
- **注意事项**：
  - 推荐传入 `symbol_name`（SDK 会自动计算精确的 character）。从 `grep content` 拿到的行内容中直接提取函数名即可，无需手动算索引。
  - 如果用户说"分析某某函数的调用链"，建议直接用 `incomingCalls` / `outgoingCalls`，它们内部会自动先调 `prepareCallHierarchy` 拿到节点，无需你手动分两步。

##### **`incomingCalls`** — 谁调用了它（被调用链）
- **做什么**：给定 `prepareCallHierarchy` 返回的一个节点，找到所有调用了该函数/方法的地方。
- **典型用法**：想知道"这个函数被哪些函数调用了"，适合反向追溯调用者。
- **输出要点**：返回一组调用关系，每个包含 `from`（调用者信息）和 `fromRanges`（调用点位置）。
- **注意事项**：实践中直接用 `incomingCalls` 即可，插件内部会自动完成两步（`prepareCallHierarchy` → `incomingCalls`）。推荐传入 `symbol_name`，SDK 会自动计算精确位置。

##### **`outgoingCalls`** — 它调用了谁（调用链）
- **做什么**：给定 `prepareCallHierarchy` 返回的一个节点，找到该函数内部调用了哪些其他函数/方法。
- **典型用法**：想知道"这个函数内部调用了哪些函数"，适合正向展开调用链路。
- **输出要点**：返回一组调用关系，每个包含 `to`（被调用者信息）和 `fromRanges`（调用点位置）。
- **注意事项**：实践中直接用 `outgoingCalls` 即可，插件内部会自动完成两步（`prepareCallHierarchy` → `outgoingCalls`）。推荐传入 `symbol_name`，SDK 会自动计算精确位置。

## 使用策略

这些工具的使用顺序和组合由你根据用户问题和实际执行情况自主规划。以下是三种常见的路径：

### 路径 A：定向 — 定向 — `grep content` → `goToDefinition` → `documentSymbol` → `readline_in_range`

当你需要找到特定符号或代码片段的完整实现时，这条路径最精准。

`grep content` 定位到目标代码的行号后，`goToDefinition` 利用 LSP 的类型解析跨文件找到真正的定义文件（调用点在 A 文件、定义可能在 B 文件）。然后对目标文件调 `documentSymbol` 获取该符号的完整边界（Lines X-Y），最后 `readline_in_range` 按边界精确读取。如果模型从上下文能判断定义和调用在同一文件，可以跳过 `goToDefinition`，直接用 `grep` 拿到的 filePath 调 `documentSymbol`。

### 路径 B：概览 — `documentSymbol` → `readline_in_range`

当你需要先看文件整体结构，再按需阅读时，用 `documentSymbol` 获取符号大纲。
输出中每个符号都带有 `Lines X-Y` 的精确起止行号。

**拿到 `documentSymbol` 输出后，必须从输出中提取目标符号的 `Lines X-Y` 作为 `readline_in_range` 的精确参数**，
不要自己猜测行号或用均匀切片。

### 路径 C：引用分析 — `grep` → `findReferences`

当你需要知道某个符号被哪些地方使用/引用时，先用 `grep` 拿到准确的行号，
然后用 `findReferences` 获取所有引用位置。结合结果按需用 `readline_in_range` 查看引用处的上下文。

## 常见场景示例

### 场景 1：用户问"这个功能怎么实现的"，你知道大概的关键词

```
① grep(pattern="HandleRequest", output_mode="content", path="main.go")
   → main.go:62:func (h *Helper) HandleRequest(input string) (string, error) {

② 行内容 = "func (h *Helper) HandleRequest(input string) (string, error) {"
   提取 symbol_name = "HandleRequest"

③ lsp(operation="goToDefinition", filePath="main.go", line=62, symbol_name="HandleRequest")
   → SDK 自动定位 HandleRequest 位置，调 LSP
   → uri=main.go, range.start.line=61, range.end.line=61 (0-based)
   → 确认定义在 main.go，符号名在第 62 行

④ lsp(operation="documentSymbol", filePath="main.go")
   → HandleRequest (Method) - Lines 62-72

⑤ readline_in_range(file_path="main.go", start=62, end=72)
```

### 场景 2：用户问"看看这个文件的整体结构 / 这个文件里有哪些关键函数"

```
① lsp(operation="documentSymbol", filePath="main.go")
   → 输出：
     DataProcessor (Interface) - Lines 7-10
     DefaultProcessor (Struct) - Lines 13-16
     ProcessorConfig (Struct) - Lines 19-22
     NewDefaultProcessor (Function) - Lines 25-31
     Process (Method) - Lines 34-40
     Validate (Method) - Lines 43-46
     ...

② readline_in_range(file_path="main.go", start=34, end=40)   ← 边界来自步骤①
   → 精确读取 Process
```

### 场景 3：用户问"某个符号被哪些地方使用了"

```
① grep(pattern="TransformData", output_mode="content")
   → main.go:42:func TransformData(data string) string {

② 行内容 = "func TransformData(data string) string {"
   提取 symbol_name = "TransformData"

③ lsp(operation="findReferences", filePath="main.go", line=42, symbol_name="TransformData")
   → SDK 自动定位 TransformData 位置，调 LSP
   → Found 2 references in 2 files:
     main.go: Line 38
     handler.go: Line 15
```

### 场景 4：用户问"某个接口有哪些实现"

```
① lsp(operation="documentSymbol", filePath="main.go") → 找到 DataProcessor 接口在 Lines 7-10
② lsp(operation="goToImplementation", filePath="main.go", line=7, symbol_name="DataProcessor")
   → SDK 自动定位 DataProcessor 位置，调 LSP
③ readline_in_range(...) → 逐个按实现处的行号范围读取
```

### 场景 5：信息不全，需要逐步探索

```
① glob("**/*.go") → 了解目录结构
② grep(pattern="关键词", output_mode="files_with_matches") → 圈定文件
③ grep(pattern="具体函数名", output_mode="content", path="目标文件") → 拿到行号
④ lsp(operation="goToDefinition", ...) → 跨文件定位定义文件（如需要）
⑤ lsp(operation="documentSymbol", filePath="目标文件") → 拿到完整边界
⑥ readline_in_range(file_path=..., start=..., end=...) → 按边界精确读取
```

**注意**：①② 为发现阶段可灵活组合；③④⑤ 的行号为精确传递，禁止猜测切片。

### 场景 6：用户问"某个函数的调用链是什么样的" / "谁调用了它" / "它调用了谁"

```
① grep(pattern="ProcessData", output_mode="content")
   → main.go:42:func (d *DataProcessor) ProcessData(data string) (string, error) {

② 行内容 = "func (d *DataProcessor) ProcessData(data string) (string, error) {"
   提取 symbol_name = "ProcessData"

③ lsp(operation="prepareCallHierarchy", filePath="main.go", line=42, symbol_name="ProcessData")
   → SDK 自动定位 ProcessData 位置，调 LSP
   → ProcessData (Method) / main.go / Lines 42-47

④ 用户问"它调用了谁" →
   lsp(operation="outgoingCalls", filePath="main.go", line=42, symbol_name="ProcessData")
   → ProcessData 调用了: TransformData, ValidateInput

⑤ 用户问"谁调用了它" →
   lsp(operation="incomingCalls", filePath="main.go", line=42, symbol_name="ProcessData")
   → ProcessData 被调用: HandleRequest (Method) / main.go / Lines 62-75
```

以上仅为常见模式，你可以根据实际情况灵活调整。

## 提示与注意事项

- 所有 grep 返回的路径是相对于当前工作目录的；可以使用相同的相对路径传给 `readline_in_range` 或 `lsp`。
- **`readline_in_range` 的 `start`/`end` 应来自 `lsp` 的实际输出**。已拿到 `lsp` 结果后，直接从输出中提取目标符号的 `Lines X-Y` 作为 `start`/`end`，不要猜测行号或使用均匀切片。如果符号是文件最后一个符号，省略 `end` 即可读到 EOF。
- **`lsp` 和 `readline_in_range` 需要分两轮执行**。
- **获取精确行号的方法**：
  - `lsp goToDefinition`：给定 `filePath + line + symbol_name`，返回定义所在文件和符号名称的行号。用于跨文件定位，不能单独提供完整边界。
  - `lsp documentSymbol`：返回文件的符号大纲，每个符号带 `Lines X-Y` 精确边界。这是完整边界的唯一可靠来源。拿到后直接提取目标符号的行号。
  - `grep content` + `context`：当 LSP 不可用时，用 context 参数获取目标符号附近的上下行，大致判断起止范围。
- 大文件建议先用 `grep content` 或 `lsp` 获取目标符号的精确边界，再用 `readline_in_range` 读取，而不是从头到尾或按均匀切片读取。
- 不要在同一轮中无意义地重复相同参数的 `grep` 或 `readline_in_range`。
- 当你已经定位并阅读了足够的目标代码，调用 `finish` 汇总结论。
- LSP 操作需要 LSP server 已经运行或可以启动；如果返回 "No LSP server available" 的错误，可以依赖 `grep` + `readline_in_range` 做纯文本级别分析。

# skill-hub HTTP API

`skill-hub` 是一个轻量 FastAPI 服务，将 skill zip 包索引起来，供 `skill-agent` 及各调用方按需拉取/上传/管理。

本文档描述当前已实现的所有 HTTP 接口。关于多命名空间的设计决策与未来规划，见 `docs/multi-tenant-design.md`。

---

## 基础约定

### 多命名空间模型

- 每个 `SKILLS_DIR` 的子目录是一个 **namespace**（租户空间），目录名即命名空间名。
- 内置的 **`default`** 命名空间的物理目录是 `SKILLS_DIR/default/`。官方 skill 打包在 `SKILLS_DIR/default/` 下（镜像构建时 `COPY skills/default /app/skills/default`）；**上传到 `default` 命名空间的 zip 也写入 `SKILLS_DIR/default/`**，因此新旧 skill 同属 `default`。
- 为兼容旧镜像布局，`SKILLS_DIR` **根目录**下直接放置的 `*.zip` 也归入 `default` 命名空间。
- 一个 skill 由 `(namespace, name, version)` 唯一确定。
- `name` 来自 zip 内 `SKILL.md` 的 frontmatter；`version` 来自 `_meta.json`（**不依赖文件名**）。
- 当前所有命名空间均为 `public`；`private` 已预留设计但未实现。

### 旧接口兼容（严格不变）

**所有不带 namespace 的默认 API 都走 `default` 命名空间**：`GET /skills` 只返回 `default` 的 skill；`GET /skills/{name}.zip` 与根路径 `GET /{name}.zip` 都从 `default` 下载；`POST /skills/reload` 重建后返回 `default` 的列表。旧调用方行为完全不变。要操作其他命名空间，必须显式使用 `/namespaces/{ns}/...` 路径。

### 校验规则

| 字段 | 允许字符 | 说明 |
| --- | --- | --- |
| `namespace` | `^[a-z0-9][a-z0-9._-]*$` | 小写字母/数字开头，仅含小写字母、数字、`.`、`_`、`-` |
| `name` | `^[A-Za-z0-9._-]+$` | 字母、数字、`.`、`_`、`-` |
| `version` | `^[A-Za-z0-9._+-]+$` | 字母、数字、`.`、`_`、`+`、`-` |

### 通用错误响应

所有 HTTP 异常统一返回 JSON：

```json
{
  "error": "错误描述",
  "status_code": 404
}
```

---

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 健康检查 |
| GET | `/skills` | 列出 `default` 命名空间的 skill |
| POST | `/skills/reload` | 重新扫描 `SKILLS_DIR` 重建索引 |
| GET | `/namespaces` | 列出所有命名空间 |
| GET | `/namespaces/{ns}/exists` | 查询某命名空间是否存在（返回 `{"exists": true|false}`） |
| POST | `/namespaces/{ns}` | 显式创建命名空间（已存在返回 409） |
| DELETE | `/namespaces/{ns}` | 删除**空**命名空间（非空返回 409，`default` 禁止删除） |
| GET | `/namespaces/{ns}/skills` | 列出某命名空间的 skill |
| GET | `/namespaces/{ns}/skills/{name}/detail` | 获取 skill 详情（含 detail / allowed_tools） |
| GET | `/namespaces/{ns}/skills/{name}.zip` | 从某命名空间下载 skill |
| POST | `/namespaces/{ns}/skills/create` | 用表单字段创建 skill（服务端打包 zip） |
| POST | `/namespaces/{ns}/skills` | 上传 skill 到某命名空间 |
| DELETE | `/namespaces/{ns}/skills/{name}.zip` | 删除某命名空间的 skill |
| GET | `/skills/{name}.zip` | 从 `default` 下载 skill（旧别名） |
| GET | `/{name}.zip` | 从 `default` 下载 skill（旧根路径） |

---

## GET /healthz

健康检查端点。

**响应** `200 OK`

```json
{
  "status": "ok"
}
```

---

## GET /skills

列出 `default` 命名空间下所有 skill 的最新版本信息。

**响应** `200 OK` — `SkillListResponse`

```json
{
  "count": 3,
  "skills_dir": "/app/skills/default",
  "skills": [
    {
      "name": "hashgen",
      "namespace": "default",
      "description": "Generate secure random hashes",
      "version": "2.0.0",
      "filename": "hashgen-2.0.0.zip",
      "download_url": "/hashgen.zip",
      "available_versions": ["2.0.0", "1.10.0", "1.0.0"]
    }
  ]
}
```

**字段说明**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `count` | int | 不同 skill 的数量 |
| `skills_dir` | str | `default` 命名空间的目录（即 `SKILLS_DIR/default/`） |
| `skills[].name` | str | skill 名称（来自 `SKILL.md`） |
| `skills[].namespace` | str | 所属命名空间（此处恒为 `default`） |
| `skills[].description` | str | skill 简介 |
| `skills[].version` | str | 最新版本号（来自 `_meta.json`） |
| `skills[].filename` | str | 磁盘上实际 zip 文件名 |
| `skills[].download_url` | str | 下载该 skill 最新版本的相对 URL |
| `skills[].available_versions` | array | 全部已知版本，最新在前 |

> 版本排序遵循 PEP 440（`packaging.version.Version`），无法解析的版本按字典序排在最前。

---

## POST /skills/reload

重新扫描 `SKILLS_DIR` 并重建所有命名空间的索引。返回与 `GET /skills`（default）相同的结构。

**响应** `200 OK` — `SkillListResponse`（同 `GET /skills`）

---

## GET /namespaces

列出索引中所有命名空间。

**响应** `200 OK` — `NamespaceListResponse`

```json
{
  "count": 2,
  "namespaces": [
    { "id": "default", "visibility": "public" },
    { "id": "team-a", "visibility": "public" }
  ]
}
```

**字段说明**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `count` | int | 命名空间数量 |
| `namespaces[].id` | str | 命名空间标识 |
| `namespaces[].visibility` | str | 可见性，当前恒为 `public`；`private` 预留 |

> 内置 `default` 命名空间即使还没有 skill 也会出现在列表中。磁盘上已存在（含刚创建但尚无 skill）的命名空间目录也会被列出。

---

## GET /namespaces/{namespace}/exists

查询某个命名空间是否存在。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 命名空间名（须通过校验规则） |

**行为**

- 始终返回 `200`，用响应体里的 `exists` 布尔值表示是否存在。
- 存在条件：内置 `default`、磁盘上已有该命名空间目录、或当前索引中已有该命名空间的 skill。
- 命名空间名非法时返回 `400`。

**响应** `200 OK` — `NamespaceExistsResponse`

```json
{
  "namespace": "team-a",
  "exists": true
}
```

```json
{
  "namespace": "missing-ns",
  "exists": false
}
```

**示例**

```bash
curl -sS "http://<host>:8000/namespaces/team-a/exists"
curl -sS "http://<host>:8000/namespaces/missing-ns/exists"
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | namespace 非法（如含大写字母、路径穿越字符） |

---

## POST /namespaces/{namespace}

显式创建一个命名空间。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 要创建的命名空间名（须通过校验规则） |

**行为**

- 在磁盘上创建对应的命名空间目录，并使其立即出现在 `GET /namespaces` 中。
- 若命名空间**已存在**，返回 `409 Conflict`，并记录一条 warning 日志以便排查。
- 内置的 `default` 命名空间**禁止创建**（它是系统内置的保留命名空间，由镜像构建时创建），返回 `400`。

**响应** `201 Created` — `NamespaceInfo`

```json
{
  "id": "team-b",
  "visibility": "public"
}
```

**示例**

```bash
curl -sS -X POST "http://<host>:8000/namespaces/team-b"
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | namespace 非法（如含大写字母、路径穿越字符），或尝试创建保留的 `default` |
| 409 | namespace 已存在 |

> 与上传接口的"自动创建"互补：上传到不存在的 namespace 会自动创建；若要显式创建（并在此前检测冲突），用本接口。

---

## DELETE /namespaces/{namespace}

删除一个**空**命名空间。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 要删除的命名空间名 |

**行为**

- 仅允许删除**不含任何 skill** 的命名空间（目录为空）。
- 命名空间**非空**时返回 `409 Conflict`，要求先删除其中的 skill 再删除 namespace（避免连带误删整个命名空间的 skill）。
- 内置的 `default` 命名空间**禁止删除**，返回 `400`。
- 删除成功后立即刷新索引，`GET /namespaces` 中随即消失。

**响应** `204 No Content`（无响应体）

**示例**

```bash
curl -sS -X DELETE "http://<host>:8000/namespaces/empty-ns"
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | namespace 非法，或尝试删除保留的 `default` |
| 404 | namespace 不存在 |
| 409 | namespace 非空（仍有 skill） |

---

## GET /namespaces/{namespace}/skills

列出指定命名空间下所有 skill 的最新版本信息。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 命名空间名（须通过校验规则） |

**响应** `200 OK` — `SkillListResponse`（`skills_dir` 为该命名空间目录，`skills[].namespace` 为对应命名空间）

```json
{
  "count": 2,
  "skills_dir": "/app/skills/team-a",
  "skills": [
    {
      "name": "report",
      "namespace": "team-a",
      "version": "1.1.0",
      "filename": "report-1.1.0.zip",
      "download_url": "/namespaces/team-a/skills/report.zip",
      "available_versions": ["1.1.0", "1.0.0"]
    }
  ]
}
```

> 非 `default` 命名空间的 `download_url` 带命名空间前缀，可直接用于下载。

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | namespace 非法（如含大写字母、路径穿越字符） |

---

## GET /namespaces/{namespace}/skills/{name}/detail

返回 skill 的完整元数据（从 zip 经 `SkillLoader` 解析），供 UI 详情弹窗使用。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 命名空间名 |
| `name` | skill 名 |

**查询参数**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `version` | str? | 可选；省略时为最新版本 |

**响应** `200 OK`

```json
{
  "name": "report",
  "namespace": "team-a",
  "description": "Generate report",
  "detail": "## Goal\n\n...",
  "version": "1.1.0",
  "filename": "report-1.1.0.zip",
  "download_url": "/namespaces/team-a/skills/report.zip",
  "available_versions": ["1.1.0", "1.0.0"],
  "allowed_tools": ["glob", "grep"],
  "scripts": [{"script_name": "run.py", "interpreter": "python3"}],
  "resource_dirs": ["assets"]
}
```

`allowed_tools` 为空数组表示不限制工具。

---

## GET /namespaces/{namespace}/skills/{name}.zip

从指定命名空间下载 skill 的 zip。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 命名空间名 |
| `name` | skill 名（不含 `.zip` 后缀） |

**查询参数**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `version` | str? | 可选。指定版本；省略时返回最新的已索引版本 |

**响应** `200 OK`

- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="{name}-{version}.zip"`（与磁盘命名一致，如 `discrawl-1.0.0.zip`）
- 响应头 `X-Skill-Version`：本次实际返回的版本号（便于客户端在请求 `latest` 时获知具体版本）

**示例**

```bash
curl -sS -OJ "http://<host>:8000/namespaces/team-a/skills/report.zip"
curl -sS -OJ "http://<host>:8000/namespaces/team-a/skills/report.zip?version=1.0.0"
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | namespace / name / version 非法 |
| 404 | skill 或指定版本不存在 |

---

## POST /namespaces/{namespace}/skills/create

用结构化字段创建一个 skill（无需预先打 zip）。skill-hub 会生成符合 `skill_sdk` 约定的包：

- `SKILL.md`：`name` / `description` frontmatter + `detail` 正文
- `_meta.json`：`version`、可选 `allowed_tools`；`slug` **固定等于** `name`（请求体不收该字段）

然后按与上传相同的规则写入命名空间并刷新索引。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 目标命名空间名 |

**请求体** — `application/json`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | skill 名（写入 `SKILL.md`；字符集同上传校验） |
| `description` | string | 是 | 短描述 |
| `detail` | string | 否 | Markdown 正文（技能完整说明/指令） |
| `version` | string | 否 | 默认 `1.0.0` |
| `allowed_tools` | string[] | 否 | 工具白名单；空数组表示不限制 |

**行为**

- 同命名空间 `name` + `version` 相同 → **覆盖**。
- 命名空间不存在时自动创建。
- 成功后立即刷新索引。

**响应** `201 Created` — `SkillInfo`（与上传接口相同）

**示例**

```bash
curl -sS -X POST "http://<host>:8000/namespaces/team-a/skills/create" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "my-skill",
    "description": "Does something useful",
    "detail": "## Steps\n\n1. Inspect the repo\n2. Answer the question\n",
    "version": "1.0.0",
    "allowed_tools": ["glob", "grep", "readline_in_range"]
  }'
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | 字段非法 / 空 description / 打包结果无法通过 SkillLoader 校验 |
| 413 | 生成包超过 256 MiB（极少见） |

---

## POST /namespaces/{namespace}/skills

上传一个 skill zip 到指定命名空间。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 目标命名空间名 |

**请求体** — `multipart/form-data`

| 字段 | 说明 |
| --- | --- |
| `file` | skill zip 文件（必填） |

**行为**

- skill 的 `name` / `version` 从 zip 内容解析（`SKILL.md` frontmatter + `_meta.json`），**不依赖上传文件名**。
- 同命名空间内 `name` + `version` 都相同 → **直接覆盖**（磁盘上保持单个文件，不报 409）。
- 目标命名空间目录**不存在时自动创建**（类似 Docker Hub 的 push 语义），无需提前建目录。
- 上传成功后**立即刷新索引**，随即可被列表/下载命中。
- 上传大小上限 256 MiB。

**响应** `201 Created` — `SkillInfo`

```json
{
  "name": "report",
  "namespace": "team-a",
  "description": "Generate report",
  "version": "1.1.0",
  "filename": "report-1.1.0.zip",
  "download_url": "/namespaces/team-a/skills/report.zip",
  "available_versions": ["1.1.0", "1.0.0"]
}
```

**示例**

```bash
curl -sS -X POST "http://<host>:8000/namespaces/team-a/skills" \
  -F "file=@report-1.1.0.zip"
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | namespace 非法，或 zip 无效 / `_meta.json` 缺 version / 缺 name |
| 413 | 上传超过 256 MiB |

---

## DELETE /namespaces/{namespace}/skills/{name}.zip

删除某命名空间下的 skill（或指定版本）。

**路径参数**

| 参数 | 说明 |
| --- | --- |
| `namespace` | 命名空间名 |
| `name` | skill 名 |

**查询参数**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `version` | str? | 可选。省略时删除最新版本 |

**行为**

- 删除指定版本后，其余版本仍保留，`latest` 自动回退到次新版本。
- 删除最后一个版本后，该 skill 整个消失。
- 删除成功后**立即刷新索引**。

**响应** `204 No Content`（无响应体）

**示例**

```bash
curl -sS -X DELETE "http://<host>:8000/namespaces/team-a/skills/report.zip?version=1.0.0"
curl -sS -X DELETE "http://<host>:8000/namespaces/team-a/skills/report.zip"   # 删除最新
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| 400 | namespace / name / version 非法 |
| 404 | skill 或指定版本不存在 |

---

## GET /skills/{name}.zip 与 GET /{name}.zip

从 `default` 命名空间下载 skill（两者等价）。

- `GET /skills/{name}.zip` — 当前各 agent（`skill-agent` / `code-agent` / `orchestrator-agent` 的 `skill_download.py`）统一使用的下载路径。
- `GET /{name}.zip` — 旧根路径别名，保留给历史调用方。

**路径参数 / 查询参数 / 响应** 与 `GET /namespaces/{namespace}/skills/{name}.zip` 相同，只是命名空间固定为 `default`。

**示例**

```bash
curl -sS -OJ "http://<host>:8000/hashgen.zip"
curl -sS -OJ "http://<host>:8000/hashgen.zip?version=1.10.0"
curl -sS -OJ "http://<host>:8000/skills/github.zip"
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SKILLS_DIR` | `/app/skills/` | 存放 skill `*.zip` 的目录；每个子目录是一个命名空间，其中 `default` 子目录是内置命名空间（根目录下直接放置的 `*.zip` 也归入 `default`，兼容旧布局） |
| `SKILLS_AUTO_RELOAD` | `1` | 是否自动监听 `SKILLS_DIR` 并在 `*.zip` 增删改时自动重建索引；设为 `0`/`false` 关闭 |
# Skill-Hub 多租户仓库设计

> 目标：把 `skill-hub` 从"单个本地目录扫描"升级为类似 **Docker Hub** 的多租户 skill 仓库——有内置的 `default` namespace，同时支持多租户各自的 namespace，每个 namespace 支持上传 / 下载 / 列表。
>
> **本期约束**：只出设计，不实现；**不动现有 API**（code-agent / skill-agent / orchestrator-agent 的 `skill_download.py` 仍在用）；暂不做鉴权，所有 namespace 默认 `public`。

---

## 1. 核心概念

借鉴 Docker Hub / OCI registry 的 `namespace/name` 模型。

| 概念 | 说明 | 示例 |
| --- | --- | --- |
| **namespace** | 租户空间标识 | `default`、`james`、`team-a` |
| **skill 全名** | `{namespace}/{name}` | `james/hashgen` |
| **`default` namespace** | 系统内置官方空间；向下兼容现有根路径语义 | `default/hashgen` |

### `default` namespace 的定位

- 是系统内置的官方 namespace，所有用户可见。
- 现有 `SKILLS_DIR` 镜像内置的 zip 即当归属于 `default`，保证旧调用方行为不变。
- 现有 `GET /skills`、`GET /{name}.zip` 均映射到 `default` namespace。

### version 管理现状

> **已拍板**：**不引入 tag 概念**。skill-hub 以 version 作为与 name 平行的核心维度，已具备完整版本管理，`namespace/name/version` 三元组即可唯一定位一个 skill 文件。Docker Hub 式 tag（指向某版本的别名，如 `latest`）在本场景是多余的抽象层，`latest` 语义已内建。

**version 的来源与寻址：**

- version 来自 skill zip 内的 `_meta.json` 的 `version` 字段（如 `1.0.0`），由 `SkillLoader` 解析。
- 一个 skill 可持有多个版本，存储在 `{name}-{version}.zip`（如 `hashgen-1.0.0.zip`、`hashgen-2.0.0.zip`）。
- 完整寻址单元是三元组 `(namespace, name, version)`；`namespace/name` 定位 skill，`version` 定位该 skill 的具体版本。

**版本排序（PEP 440 语义）：**

- 用 `packaging.version.Version` 做语义比较，`_version_key` 返回 `(是否可解析, 排序键)` 二元组。
- 可解析版本 > 不可解析版本；`1.10 > 1.9`、`2.0.0 > 2.0.0rc1` 等按语义正确排序。
- 排序后 `vs[0]` 即最新版本；`available_versions` 最新在前返回。

**"latest" 语义内建，无需 tag：**

- 下载不带 `?version=` → 返回最新版本（隐式 `latest`）。
- 下载带 `?version=x` → 返回指定版本。
- 响应头 `X-Skill-Version` 回传实际解析到的版本。
- 消费方（`skill_download.py`）按 name 下载最新版，不依赖 tag。

**覆盖语义（多租户）：**

- 同 namespace 内 `name` + `version` 都相同 → 直接覆盖（version 是覆盖判据的一部分）。

---

## 2. 存储布局

### 目录结构（每个子目录 = 一个 namespace）

```
SKILLS_DIR (默认 /app/skills/)
├── default/            ← 系统内置 namespace（镜像内置 zip 迁移到此）
│   ├── hashgen-1.0.0.zip
│   ├── base64tool-1.0.0.zip
│   └── ...
├── james/              ← 租户 james 的 namespace
│   ├── weather-1.0.0.zip
│   └── github-1.0.0.zip
└── team-a/             ← 租户 team-a 的 namespace
    └── semantic-grouper-0.1.0.zip
```

### 落盘规则

- 每个 namespace 一个子目录：`SKILLS_DIR/<namespace>/`。
- 上传文件放在：`SKILLS_DIR/<namespace>/<name>-<version>.zip`。
- **`default` namespace 也建成子目录 `SKILLS_DIR/default/`**，把现有镜像内置的 zip 迁移进去。
  - Dockerfile 从 `COPY skills /app/skills` 改为 `COPY skills/default /app/skills/default`
    （仓库布局为 `skills/default/*.zip`，避免嵌套成 `/app/skills/default/default/`）。
  - 这样规则统一：所有 namespace（含 default）都走"子目录 = namespace"。
- namespace 目录本身不作为 skill 被扫描（只扫描其下的 `*.zip`）。

### 与 `_meta.json` 的关系

- skill zip 内部的 `_meta.json` 已带 `ownerId` 字段（实测存在，如 `test-suite` 或租户哈希）。
- 上传时把 `ownerId` 写入 zip 内的 `_meta.json`（作为归属元数据）。
- 扫描时以**目录名（namespace）为主**，`ownerId` 为辅校验；本期无鉴权，`ownerId` 与 namespace 不一致时**仅告警、不拒绝**。
- 现有 zip 无 `ownerId` 也能运行，缺省归 `default` namespace。

---

## 3. API 设计

### 3.1 现有 API —— 全部保留，语义归为 `default` namespace

| 方法 | 路径 | 多租户语义 |
| --- | --- | --- |
| GET | `/healthz` | 不变 |
| GET | `/skills` | 列出 **default** namespace |
| GET | `/{name}.zip?version=` | 下载 **default** namespace |
| GET | `/skills/{name}.zip?version=` | 同上（别名） |
| POST | `/skills/reload` | 重扫**所有** namespace |

> **已拍板（方案 A）**：`GET /skills` 永远只返回 **default** namespace 的 skill，旧调用方行为完全不变，继续只看到官方 skill。想看其他 namespace 必须显式走 `GET /namespaces/{ns}/skills`。即便未来需要"跨 namespace 聚合浏览"，也通过新增独立端点实现，**不改 `GET /skills` 语义**。
>
> 保留根路径下载 `/{name}.zip` 与 `X-Skill-Version` 响应头，是旧调用方（`code-agent` / `skill-agent` / `orchestrator-agent` 的 `skill_download.py`）兼容的关键。

### 3.2 新增 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/namespaces` | 列出所有 namespace（含 visibility） |
| GET | `/namespaces/{ns}/skills` | 列出某 namespace 下的 skill |
| GET | `/namespaces/{ns}/skills/{name}.zip?version=` | 从某 namespace 下载 skill |
| POST | `/namespaces/{ns}/skills` | 上传 skill 到某 namespace（multipart） |
| DELETE | `/namespaces/{ns}/skills/{name}.zip?version=` | 删除某 namespace 的 skill（预留） |

#### 响应模型

`SkillInfo` 增加**可选** `namespace` 字段（默认 `"default"`），并让 `download_url` 携带 namespace：

```python
class SkillInfo(BaseModel):
    name: str
    namespace: str = "default"      # 新增，可选，保证向后兼容
    description: str
    version: str
    filename: str
    download_url: str               # default 空间: "/{name}.zip"；其他空间: "/namespaces/{ns}/skills/{name}.zip"
    available_versions: list[str]
```

- 旧调用方忽略 `namespace` 字段即可，`GET /skills` 因为只返回 default 空间，`download_url` 仍为 `/{name}.zip`，结构兼容。
- `GET /namespaces/{ns}/skills` 返回的 `download_url` 必须带 namespace，否则非 default 空间的 skill 无法用该 URL 正确下载（实际为 `/namespaces/{ns}/skills/{name}.zip`）。
- 为未来"跨 namespace 聚合浏览"预留了字段位。

#### `GET /namespaces` 响应

```python
class NamespaceInfo(BaseModel):
    id: str                       # namespace 标识
    visibility: str = "public"    # 本期恒为 "public"，预留 private
```

```python
class NamespaceListResponse(BaseModel):
    count: int
    namespaces: list[NamespaceInfo]
```

---

## 4. 上传流程

```
客户端                          skill-hub
  │  POST /namespaces/{ns}/skills      │
  │  (multipart: zip)      ──────► │
  │                                │ 1. 校验 namespace 合法（格式 + 存在性）
  │                                │ 2. 解析 zip → name / version
  │                                │ 3. 校验 name / version 格式
  │                                │ 4. 同 namespace 内 name+version 相同则直接覆盖
  │                                │     （覆盖旧文件，磁盘上同名同版本只保留一份）
  │                                │ 5. 写 SKILLS_DIR/{ns}/{name}-{version}.zip
  │                                │ 6. 主动调用 reload() 立即生效
  │                                │ 7. 返回 201 + SkillInfo
  │  ◄────── 201                   │
```

- 覆盖语义：**同 namespace 内，`name` + `version` 都相同 → 直接覆盖**（不报 409）。覆盖通过写同名文件实现（文件名 `{name}-{version}.zip` 相同，天然覆盖），旧内容被替换。
- 返回值：新建返回 `201 Created`；覆盖返回 `200 OK`（可选，二者都返回 `SkillInfo`）。
- 注意：覆盖只发生在**同 namespace** 内。不同 namespace 下同名 skill 互不影响（各自独立存放）。

### 关键决策

| 决策点 | 结论 |
| --- | --- |
| `default` namespace 落盘 | 建 `SKILLS_DIR/default/` 子目录，迁移镜像内置 zip（规则统一） |
| 同名同版本冲突 | **直接覆盖**（同 namespace 内 name+version 相同则覆盖旧文件），不返回 409 |
| reload 触发 | 上传后**主动调用 `reload()`** 立即生效，不依赖 `watchfiles` 2s debounce（避免"上传后立刻下载却 404"） |
| namespace 可见性 | 本期全部 `public`（架构上预留 `private`，见第 7 节） |
| namespace 不存在时上传 | 上传到不存在的 namespace → `404`（本期**不自动创建** namespace，见 4.1） |
| 是否允许上传到 `default` | 本期**允许**（全 public，无所有权概念）；未来引入 private 后可改为禁止非授权者写 default（见 7.3） |

### 4.1 上传校验与 namespace 存在性

- 上传前校验 namespace 格式（`^[a-z0-9][a-z0-9._-]*$`）与**存在性**。
- namespace 必须是已存在的目录；上传到不存在的 namespace → `404 Namespace Not Found`。
- 本期 namespace 目录由镜像内置（`default`）或运维预建（`SKILLS_DIR/<ns>/`）产生，**不通过上传接口隐式创建**。
- 上传到 `default` 本期允许（全 public）。

---

## 5. 内部结构改造

### 5.1 `_SkillVersion` 增加 namespace

```python
@dataclass(frozen=True)
class _SkillVersion:
    version: str
    path: Path
    description: str
    namespace: str = "default"   # 新增
```

### 5.2 索引从"按 name 分组"改为"按 (namespace, name) 分组"

- 现有：`_versions: dict[str, list[_SkillVersion]]`
- 新增（**作为唯一索引**，替换旧结构）：`_ns_versions: dict[tuple[str, str], list[_SkillVersion]]`
- `reload()` 递归扫描 `SKILLS_DIR/*/{name}-{version}.zip`，每个子目录一个 namespace。
- `list_skills(namespace: str)`：
  - `namespace="default"`：返回 default 空间（对应 `GET /skills`）
  - 其他 namespace：返回该空间下 skill（对应 `GET /namespaces/{ns}/skills`）
- `resolve_zip(namespace, name, version)`：按 `(namespace, name)` 查 `_ns_versions`。
- **现有 `GET /skills` 内部调用 `list_skills("default")`；现有 `GET /{name}.zip` 内部调用 `resolve_zip("default", name, version)`**——二者都落在 `_ns_versions` 的 `("default", ...)` 键上，与方案 A 严格一致。

> 索引**只有一份** `_ns_versions`（按下述约定），不保留旧的 `_versions`，避免两套结构不同步。`default` 空间的键即 `("default", name)`。

### 5.3 下载解析

- `resolve_zip(namespace, name, version)` / `resolved_version(...)`：按 `(namespace, name)` 查 `_ns_versions`。
- 现有根路径下载 `/{name}.zip` 内部调用 `resolve_zip("default", name, version)`（见 5.2）。

---

## 6. 向后兼容保障

| 措施 | 说明 |
| --- | --- |
| 根路径下载保留 | `GET /{name}.zip` 继续存在，内部映射到 `default` namespace |
| `X-Skill-Version` 头保留 | 新下载接口同样返回，调用方依赖它 |
| `GET /skills` 响应结构不变 | `SkillListResponse` 结构不变，默认返回 default namespace；`download_url` 仍为 `/{name}.zip` |
| `SkillInfo` 加 `namespace` 为可选字段 | 默认 `"default"`，旧调用方忽略即可 |
| 无 `ownerId` 也能跑 | 缺省归 default namespace |
| `_NAME_RE`/`_VERSION_RE` 校验 | 不含 `/`，天然支持新路径 `{ns}/{name}.zip` 分隔 |
| 新接口不动旧端点 | 新增 `/namespaces/*` 端点，旧端点与旧调用方路径完全不变 |

---

## 7. namespace 可见性（Visibility）设计与鉴权预留

> 本期所有 namespace 默认 **`public`**，代码**不实现** `private` 逻辑。但架构上为 `private` 预留位置，未来可平滑扩展。

### 7.1 namespace 可见性模型

每个 namespace 有**可见性属性**：`public`（公开，所有人可见可下载）或 `private`（私有，仅 namespace 所有者/授权者可见）。

```
namespace {
  id: string
  visibility: "public" | "private"
  owner_ids: list[string]   // private namespace 的所有者（未来）
}
```

- **本期**：所有 namespace 固定为 `public`，无 `owner_ids` 概念。
- **未来**：`private` namespace 在上传/列表/下载时校验调用方身份，非所有者不可见。

### 7.2 本期代码需要预留的"钩子"

为避免未来扩展 private 时大改，本期实现时建议（可选，不影响功能）：

- `SkillInfo` 增加 `visibility` 字段（默认 `"public"`），响应中带上，前端可显示"公开/私有"标记。
- 一个 `namespace_visibility(namespace) -> "public"` 的薄函数，作为未来鉴权判断的唯一入口（本期恒返回 `"public"`）。
- 上传/列表/下载三个入口统一走该函数，未来只需替换其实现即可加 private 校验。

### 7.3 鉴权预留（本期全部放行）

- namespace 格式校验：`^[a-z0-9][a-z0-9._-]*$`（小写字母数字开头，可含 `.` `_` `-`）。
- 上传接口预留 header 位（如 `X-Team-Id` / token），本期全部放行。
- 暂时无"所有权"概念，`ownerId` 仅作为元数据记录。
- 本期允许上传到任何 namespace（含 `default`）；未来引入 private 后，可改为"仅 namespace 所有者可写，其他人只读"，`default` 作为官方空间可限制为只读或仅管理员可写。

---

## 8. 实现阶段划分（后续实施参考）

| 阶段 | 内容 | 影响 |
| --- | --- | --- |
| **阶段 1** | 存储与索引改造：`_SkillVersion` 加 namespace；`reload()` 扫描子目录；`default` 迁入子目录 | 只改内部，不动 API |
| **阶段 2** | 新增只读 API：`GET /namespaces`、`GET /namespaces/{ns}/skills`、`GET /namespaces/{ns}/skills/{name}.zip` | 新增端点，不影响旧 |
| **阶段 3** | 上传 API：`POST /namespaces/{ns}/skills` + 立即 reload + 同名同版本覆盖 | 新增端点 |
| **阶段 4** | namespace 管理（可选）：`DELETE /namespaces/{ns}/skills/{name}.zip` | 新增端点 |

每阶段保持现有 API 不变，可独立发布。

---

## 9. 决策记录与待确认 / 后续优化点

### 已拍板决策

| 决策点 | 结论 |
| --- | --- |
| `GET /skills` 语义 | **方案 A（严格兼容）**：永远只返回 default namespace；跨 namespace 浏览走 `GET /namespaces/{ns}/skills`，不改 `GET /skills` 语义 |
| `default` namespace 落盘 | 建 `SKILLS_DIR/default/` 子目录，迁移镜像内置 zip |
| 上传同名同版本冲突 | **直接覆盖**（同 namespace 内 name+version 相同则覆盖旧文件），不返回 409 |
| 上传后 reload | 主动调用 `reload()` 立即生效 |
| namespace 可见性 | 本期全部 `public`；架构上预留 `private`（见第 7 节），本期不实现 private 逻辑 |
| 索引结构 | 唯一一份 `_ns_versions`，按 `(namespace, name)` 分组；`GET /skills` 内部走 default 键 |
| 上传到不存在的 namespace | `404`，本期不自动创建 namespace |
| 是否允许上传到 `default` | 本期允许（全 public）；未来 private 时再收紧 |
| `download_url` | default 空间 `/{name}.zip`；其他空间 `/namespaces/{ns}/skills/{name}.zip` |
| 是否引入 tag | **不引入**。以 `(namespace, name, version)` 三元组寻址，latest 语义内建（不带 version 即最新）；见"version 管理现状" |

### 待确认 / 后续优化点

- 是否提供跨 namespace 聚合浏览端点（如 `GET /namespaces/all`）——未来需求出现时再加，且不会改变 `GET /skills` 语义。
- 上传文件大小限制、zip 校验策略（是否限制 zip 内文件数量 / 路径穿越防护）——实现阶段补充。
- `private` namespace 的鉴权具体方案（token / 用户体系 / 授权模型）——未来实现 private 时再细化。
- 多副本部署下上传的并发一致性（当前单实例直接写磁盘即可，多副本需引入分布式锁或对象存储）——超出本期范围。
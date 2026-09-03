# RBAC 权限点清单（dac-apiserver）

> 本文档是 dac-apiserver 基于角色的访问控制（RBAC）框架的**权限点权威清单**。
> 权限点的唯一事实来源是代码：`pkg/rbac/seeder.go` 中的 `SeedPermissions` 目录。
> 管理界面（前端权限管理页）只将下列权限码绑定到角色，不能修改权限点本身。

---

## 1. 权限点总数

- **目录条目数**：42 行（`SeedPermissions`）
- **去重权限码数**：**40 个**（`agent:read` 出现 2 次，分别覆盖"查看全部智能体"与"查看智能体详情"，运行时合并为 1 个权限码、2 条路径规则）

> 权限码在数据库中是唯一索引（Ent schema `Permission.Code` 唯一），
> 多个 HTTP 路径可通过 `|` 合并到同一个权限码下（见 §4 的 merge 机制）。

---

## 2. 权限点全目录

路径语法：

- `*` —— 匹配**一个路径段**（段内不含 `/`）
- `**` —— 匹配**任意个路径段（含 0 个）直到路径结束**，且支持出现在路径中间
- URL 前缀一律为 `/api/v1`，会话相关接口为 `/v1`
- 实际请求路径**不含查询串**（query string 不参与匹配）

### 2.1 平台层（Platform）—— 全局权限

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 1 | `tenant:manage` | 管理租户 | `*` | `/api/v1/rbac/tenants/**` | 租户的增/删/改/查、启停用、租户绑定命名空间 |
| 2 | `platform:role:manage` | 管理平台角色 | `*` | `/api/v1/rbac/platform/**` | 平台角色 CRUD + 权限勾选、平台管理员授权/撤权、查看平台角色下的用户 |
| 3 | `permission:read` | 查看权限点 | `GET` | `/api/v1/rbac/permissions` | 权限管理页的权限点清单 |
| 4 | `rbac:me:read` | 查看我的租户 | `GET` | `/api/v1/rbac/me/tenants` | 当前用户可选租户列表（租户切换器） |

### 2.2 租户层（Tenant）—— 按 `X-Tenant-Id` 隔离

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 5 | `tenant:role:manage` | 管理租户角色 | `*` | `/api/v1/rbac/tenants/**/roles/**` | 租户内角色增删改查、角色的权限勾选 |
| 6 | `tenant:member:manage` | 管理租户成员 | `*` | `/api/v1/rbac/tenants/**/users/**` | 租户成员增删、成员角色变更 |

### 2.3 智能体（Agent）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 7 | `agent:read` | 查看智能体 | `GET` | `/api/v1/agents`、`/api/v1/namespaces/*/agents/**` | 智能体列表页（全量 + 按命名空间）、智能体详情 |
| 8 | `agent:create` | 创建智能体 | `POST` | `/api/v1/namespaces/*/agents` | 新建智能体（表单） |
| 9 | `agent:update` | 更新智能体 | `PUT` | `/api/v1/namespaces/*/agents/*` | （路由存在，前端暂未开放） |
| 10 | `agent:delete` | 删除智能体 | `DELETE` | `/api/v1/namespaces/*/agents/*` | 删除智能体 |

### 2.4 数据管理（Data）

#### 数据源（数据描述符 Descriptor）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 11 | `descriptor:read` | 查看数据描述符 | `GET` | `/api/v1/descriptors`、`/api/v1/namespaces/*/descriptors/**` | 数据源列表页（全量）、数据源详情、签名、语义域、知识分片 |
| 12 | `descriptor:graph:read` | 查看数据血缘图谱 | `POST` | `/api/v1/knowledge-graph/get-graph-by-source` | 数据源详情页"知识图谱/血缘关系"展示 |
| 13 | `descriptor:create` | 创建数据描述符 | `POST` | `/api/v1/namespaces/*/descriptors` | 新建数据源（表单）、资产探测页"创建数据源" |
| 14 | `descriptor:update` | 更新数据描述符 | `PUT,POST` | `/api/v1/namespaces/*/descriptors/*`、`/api/v1/namespaces/*/descriptors/*/resync` | 数据源详情"继续关联数据库"、触发数据重同步（resync） |
| 15 | `descriptor:delete` | 删除数据描述符 | `DELETE` | `/api/v1/namespaces/*/descriptors/*` | 删除数据源 |

> **设计约束**：`descriptor:read` 刻意**只保留 `GET` 方法**——若它带上 `POST` 并与 `/api/v1/namespaces/*/descriptors/**` 匹配，会把"创建数据源"（`POST .../descriptors`）和"触发重同步"（`POST .../descriptors/:name/resync`）一起放行给只读角色。
> 血缘图谱接口 `POST /knowledge-graph/get-graph-by-source` 虽是只读语义却用 POST 方法，抽出为独立的 `descriptor:graph:read` 码（仍然默认授予 viewer 只读角色），避免规则笛卡尔积造成的越权。

#### 模型配置（LLM ConfigMap）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 16 | `llmconfig:read` | 查看模型配置 | `GET` | `/api/v1/namespaces/*/llm-configmaps`、`/api/v1/namespaces/*/llm-configmaps/*` | 模型管理列表、查看模型配置详情 |
| 17 | `llmconfig:create` | 创建模型配置 | `POST` | `/api/v1/namespaces/*/llm-configmaps` | 新建 LLM 模型配置 |
| 18 | `llmconfig:update` | 更新模型配置 | `PUT` | `/api/v1/namespaces/*/llm-configmaps/*` | 编辑并保存 LLM 模型配置 |
| 19 | `llmconfig:delete` | 删除模型配置 | `DELETE` | `/api/v1/namespaces/*/llm-configmaps/*` | 删除 LLM 模型配置 |

#### 提示词（Prompt ConfigMap）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 20 | `promptconfig:read` | 查看提示词配置 | `GET` | `/api/v1/namespaces/*/prompt-configmaps`、`/api/v1/namespaces/*/prompt-configmaps/*` | 提示词列表、查看提示词详情 |
| 21 | `promptconfig:create` | 创建提示词配置 | `POST` | `/api/v1/namespaces/*/prompt-configmaps` | 新建提示词配置 |
| 22 | `promptconfig:update` | 更新提示词配置 | `PUT` | `/api/v1/namespaces/*/prompt-configmaps/*` | 编辑并保存提示词配置 |
| 23 | `promptconfig:delete` | 删除提示词配置 | `DELETE` | `/api/v1/namespaces/*/prompt-configmaps/*` | 删除提示词配置 |

#### 数据源探测

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 24 | `datasource:probe` | 数据源探测 | `POST` | `/api/v1/datasources/probe` | 数据源表单"探测数据库/重新探测" |
| 25 | `datasource:probe-types` | 查看探测类型 | `GET` | `/api/v1/datasources/probe/types` | 数据源表单的数据库类型下拉 |

### 2.5 语义组（Semantic Group）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 26 | `semantic-group:read` | 查看语义组 | `GET` | `/api/v1/semantic-groups/**`、`/api/v1/dd-group-relations/**`、`/api/v1/semantic-domains/*` | 语义组列表/详情/组成员、语义组关联列表、语义域详情（智能体组成图） |
| 27 | `semantic-group:manage` | 管理语义组 | `*` | `/api/v1/semantic-groups/**`、`/api/v1/dd-group-relations/**`、`/api/v1/semantic-domains/search/by-dd` | **删除语义组**、添加/移除组成员、**从语义组移除数据源**（解绑）、移除流程的语义域搜索 |

> `**` 覆盖删除：`DELETE /api/v1/semantic-groups/:id` 能被 `.../semantic-groups/**` 匹配。
> 前端目前无"创建/编辑语义组"按钮（语义组由 data-services 后台生成），故未单列 create/update 码；
> 若未来开放创建，`semantic-group:manage` 已天然覆盖 `POST /semantic-groups`。

### 2.6 资产探测（Discovery）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 28 | `discovery:read` | 查看资产探测 | `GET` | `/api/v1/discovery/scans/**` | 资产探测列表/详情 |
| 29 | `discovery:manage` | 管理资产探测 | `*` | `/api/v1/discovery/scans/**` | **新建扫描**、**删除扫描**、改扫描名称（PATCH） |

### 2.7 技能中心（Skill Hub）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 30 | `skill:read` | 查看技能 | `GET` | `/api/v1/skills/namespaces/**` | 技能市场列表/详情、技能下载、命名空间列表 |
| 31 | `skill:manage` | 管理技能 | `*` | `/api/v1/skills/namespaces/**` | **创建技能**、**上传技能包**、**编辑技能**、**删除技能**、**创建/删除命名空间** |

### 2.8 对话（Chat）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 32 | `chat:use` | 使用对话 | `POST` | `/v1/chat/completions` | **创建新对话**（发送首条消息即建会话）、对话 |
| 33 | `chat:history:read` | 查看历史会话 | `GET` | `/api/v1/chat/conversations/**` | 侧边栏历史对话列表、对话详情 |

### 2.9 模版配置 / 模型管理 / 全局管理

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 30 | `system:config:read` | 查看模版配置 | `GET` | `/api/v1/system/configurations/**` | 模版中心列表/详情/历史版本查看 |
| 31 | `system:config:manage` | 管理模版配置 | `*` | `/api/v1/system/configurations/**` | 模版中心"创建并生效"、编辑 |

> **模型管理**：前端"模型管理"菜单对应 `/llm-configmaps` 路由，其增删改查由 `llmconfig:*`（#16-19）覆盖。

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 32 | `environment:read` | 查看环境GPU | `GET` | `/api/v1/environment/gpu` | 数据源表单 GPU 可用性检查 |
| 33 | `namespace:read` | 查看 K8s 命名空间列表 | `GET` | `/api/v1/namespaces` | 各页面命名空间下拉 |
| 34 | `observability:read` | 查看注册中心 | `GET` | `/api/v1/observability/**` | 注册中心查看 |

### 2.10 用户（User）

| # | 权限码 | 名称 | 方法 | 路径模板 | 覆盖的前端功能 |
|---|--------|------|------|----------|----------------|
| 35 | `user:self:read` | 查看自己的用户信息 | `GET` | `/api/v1/users/me` | 顶栏当前用户信息 |
| 36 | `user:manage` | 管理用户 | `*` | `/api/v1/users/**` | 用户列表、用户删除（权限管理） |

---

## 3. 与前端页面功能的映射

按导航菜单整理（对应 `frontend/src/components/sidebar.tsx` 的 9 大模块）：

| 导航模块 | 前端页面操作 | 依赖的权限码 |
|----------|--------------|--------------|
| **对话**（首页） | 开启新对话 / 发送消息 | `chat:use` |
| | 历史对话列表、查看 | `chat:history:read` |
| **技能中心 → 技能市场** | 查看所有技能、详情、下载 | `skill:read` |
| **技能中心 → 命名空间** | 命名空间增/删/查 | `skill:manage` / `skill:read` |
| | 技能 CRUD + 上传 + 下载 | `skill:manage` / `skill:read` |
| **数据管理 → 数据源** | 数据源增/删/查、探测、续关联、详情（签名/语义域/知识分片）、血缘图谱、移除语义组 | `descriptor:create/delete/read`、`descriptor:graph:read`、`descriptor:update`、`datasource:probe`、`datasource:probe-types`、`semantic-group:manage`（解除关联） |
| **数据管理 → 提示词** | 提示词增/删/改/查 | `promptconfig:create/read/update/delete` |
| **语义组** | 语义组查询、删除；数据源"从语义组移除" | `semantic-group:read` / `semantic-group:manage` |
| **资产探测** | 扫描增/删/查、从详情创建数据源 | `discovery:manage` / `discovery:read`、`descriptor:create` |
| **模型管理** | LLM 模型配置增删改查 | `llmconfig:create/read/update/delete` |
| **全局管理 → 注册中心** | 注册中心查看 | `observability:read` |
| **全局管理 → 模版中心** | 模版增/查/历史/编辑 | `system:config:read` / `system:config:manage` |
| **权限管理** | 用户/租户/角色/成员的全套 CRUD | 见 §2.1、§2.2、§2.10 |

---

## 4. 规则匹配与合并机制

### 4.1 运行时匹配（`pkg/rbac/matcher.go`）

```text
方法匹配：
  "*"             → 匹配任意方法
  "GET,POST,..."  → 逗号分隔的多方法（解析时展开为多条规则）
  其它            → 与请求方法不区分大小写精确比较

路径匹配（按 "/" 分段）：
  "*"             → 精确匹配一个路径段
  "**"            → 匹配任意个路径段（含 0 个），可出现在路径中间
  字符串          → 与路径段精确匹配
```

示例：

| 规则路径 | 匹配的请求 | 不匹配的请求 |
|----------|-----------|--------------|
| `/api/v1/agents` | `GET /api/v1/agents` | `GET /api/v1/agents/1` |
| `/api/v1/namespaces/*/agents/**` | `GET /api/v1/namespaces/dev/agents`、`GET /api/v1/namespaces/dev/agents/web` | `GET /api/v1/agents`（不在 namespaces 下） |
| `/api/v1/rbac/tenants/**/roles/**` | `PUT /api/v1/rbac/tenants/t1/roles/r1/permissions` | `GET /api/v1/rbac/tenants/t1/users` |
| `/api/v1/skills/namespaces/**` | `POST /api/v1/skills/namespaces/sh/skills/create`、`DELETE /api/v1/skills/namespaces/sh/skills/s1` | `POST /api/v1/skills/reload`（不在 `namespaces` 下） |
| `/api/v1/semantic-groups/**` | `DELETE /api/v1/semantic-groups/g1`、`POST /api/v1/semantic-groups/g1/members` | `DELETE /api/v1/dd-group-relations/123` |
| `/api/v1/dd-group-relations/**` | `DELETE /api/v1/dd-group-relations/123`、`GET /api/v1/dd-group-relations/sd/sd-1` | `GET /api/v1/semantic-groups/g1` |
| `/api/v1/namespaces/*/descriptors/**` | `GET /api/v1/namespaces/dev/descriptors/orders`、`GET /api/v1/namespaces/dev/descriptors/orders/signature`、`GET /api/v1/namespaces/dev/descriptors/orders/knowledge` | `POST /api/v1/descriptors`（不在 namespaces 下） |
| `/api/v1/semantic-domains/*` | `GET /api/v1/semantic-domains/sd-1` | `GET /api/v1/semantic-domains/sd-1/exists`（`*` 只匹配一段，`exists` 多余） |

### 4.2 同码多条目合并（`internal/usecase/rbac/usecase.go` 的 `mergeSeedPermissions`）

同一 `Code` 存在多条目录记录时，入库前合并为一个权限：

- 名称/资源/动作/描述取**第一条**
- 任一方法为 `*` 时方法取 `*`
- 所有路径模板去重后以 `|` 拼接，生成多条匹配规则

当前被合并的码：

| 权限码 | 合并的路径 |
|--------|-----------|
| `agent:read` | `/api/v1/agents` \| `/api/v1/namespaces/*/agents/*` |

> 注意：`descriptor:read`、`llmconfig:read`、`promptconfig:read`、`semantic-group:read/manage` 等在同一权限码下写入了**多段 `\|` 分隔的路径**（单目录条目），
> 它们不经过 merge（只有"同名码的多条目录记录"才合并），但解析时同样会展开为多规则。

### 4.3 授权判定流程（`pkg/rbac/engine.go`）

```text
请求 (method, path) + 用户 + 租户(X-Tenant-Id)
    │
    ├─ 平台超级管理员 → 直接放行
    ├─ 平台角色命中（跨租户权限）→ 放行
    ├─ 租户角色命中（需用户属于该租户）→ 放行
    └─ 均未命中 → 403 拒绝（默认拒绝）
```

---

## 5. 默认角色与种子权限

### 5.1 默认租户角色 `viewer`（只读）

新租户初始化时，`viewer` 角色被授予以下只读权限（对应旧版 `p,user` 白名单）：

| 权限码 | 说明 |
|--------|------|
| `user:self:read` | 查看自己 |
| `rbac:me:read` | 我的租户 |
| `chat:history:read` | 历史会话 |
| `chat:use` | 使用对话 |
| `agent:read` | 查看智能体 |
| `descriptor:read` | 查看数据源 |
| `descriptor:graph:read` | 数据血缘图谱（数据源详情页知识图谱展示） |
| `environment:read` | 查看 GPU |
| `namespace:read` | 查看 K8s 命名空间列表 |
| `llmconfig:read` | 查看模型配置 |
| `promptconfig:read` | 查看提示词配置 |
| `system:config:read` | 查看模版配置 |
| `observability:read` | 查看注册中心 |
| `semantic-group:read` | 查看语义组 |
| `discovery:read` | 查看资产探测 |
| `datasource:probe` | 数据源探测 |
| `datasource:probe-types` | 查看探测类型 |
| `skill:read` | 查看技能 |

> `DefaultCodes` 仅在 `viewer` 角色**首次创建**时授予；后续对 `viewer` 的定制化修改不会被重播种覆盖（保证幂等）。

### 5.2 平台超级管理员

平台超级管理员为内置账号，跳过一切权限匹配，直接允许全部操作（见 §4.3）。

---

## 6. 前端审计缺口——已覆盖情况

以下为审计前端页面操作后发现的路径，现已全部纳入对应的权限码（按"页面直接操作才有权限点"的标准）：

| 方法 | 路径 | 前端操作 | 现状 |
|------|------|----------|------|
| `DELETE` | `/api/v1/dd-group-relations/:id` | 数据源详情/列表页"**从语义组移除**"（解绑数据源） | ✅ 已并入 `semantic-group:manage`（`/api/v1/dd-group-relations/**`） |
| `GET` | `/api/v1/dd-group-relations/sd/:sd_id` | 语义组关联/依赖查询 | ✅ 已并入 `semantic-group:read`（`/api/v1/dd-group-relations/**`） |
| `GET` | `/api/v1/namespaces/*/descriptors`、`/:name`、`/:name/signature`、`/:name/semantic-domain`、`/:name/knowledge` | 数据源详情页的详情/签名/语义域/知识分片查询 | ✅ 已并入 `descriptor:read`（`/api/v1/namespaces/*/descriptors/**`） |
| `POST` | `/api/v1/namespaces/*/descriptors/:name/resync` | "继续关联数据库"后的重同步触发 | ✅ 已并入 `descriptor:update`（`PUT,POST .../descriptors/*`、`.../resync`） |
| `GET` | `/api/v1/namespaces/*/llm-configmaps/:name` | 模型配置详情查看 | ✅ 已并入 `llmconfig:read`（`/api/v1/namespaces/*/llm-configmaps/*`） |
| `GET` | `/api/v1/namespaces/*/prompt-configmaps/:name` | 提示词配置详情查看 | ✅ 已并入 `promptconfig:read`（`/api/v1/namespaces/*/prompt-configmaps/*`） |
| `GET` | `/api/v1/namespaces/*/agents`、`/api/v1/namespaces/*/agents/:name` | 按命名空间查看智能体列表/详情 | ✅ 已并入 `agent:read`（`/api/v1/namespaces/*/agents/**`） |
| `POST` | `/api/v1/semantic-domains/search/by-dd` | "从语义组移除"流程的语义域搜索前置步骤 | ✅ 已并入 `semantic-group:manage` |
| `GET` | `/api/v1/semantic-domains/:id` | 智能体详情页语义关系组成图的语义域回退查询 | ✅ 已并入 `semantic-group:read`（`/api/v1/semantic-domains/*`） |
| `POST` | `/api/v1/knowledge-graph/get-graph-by-source` | 数据源详情页知识图谱（血缘）展示 | ✅ 独立权限码 `descriptor:graph:read`（POST 只读查询，避免与创建/重同步混淆） |

> **已确认无需权限点**（`/api/v1/semantic-domains/*` CRUD/batch/status/count、`/api/v1/knowledge-graph/*` 的 add/search/delete-with-source、`/api/v1/skills/reload`）：
> 前端**没有直接操作入口**（语义域由 data-services 后台管理；知识图谱前端只读展示）；
> 按"页面直接操作才有权限点"的标准**无需**为它们建立权限点。

---

## 7. 关键代码位置

| 关注点 | 位置 |
|--------|------|
| 权限点目录（**唯一事实来源**） | `pkg/rbac/seeder.go`（`SeedPermissions`） |
| 默认角色种子 | `pkg/rbac/seeder.go`（`DefaultCodes`） |
| 运行时匹配实现 | `pkg/rbac/matcher.go`、`pkg/rbac/model.go` |
| 授权引擎（含缓存） | `pkg/rbac/engine.go` |
| Hertz 中间件 | `pkg/rbac/middleware.go` |
| 播种/合并逻辑 | `internal/usecase/rbac/usecase.go` |
| 路由注册 | `internal/router/router.go` |
| 设计文档 | `pkg/rbac/RBAC-DESIGN.md` |
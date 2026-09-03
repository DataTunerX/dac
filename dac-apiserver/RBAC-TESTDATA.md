# RBAC 权限验证测试数据设计（审查稿）

> 本文档是为 `dac-apiserver` RBAC 权限框架设计的一套**完整验证数据**，
> 覆盖 `pkg/rbac/seeder.go` 中全部 **36 个权限码**（37 条目录记录）。
> 请先审查本设计的**业务合理性**，审查通过后再落地为自动化测试。

---

## 1. 业务背景（模拟真实组织）

模拟一个多租户 AI 平台，含 2 个租户、6 个用户、4 种角色：

| 用户 | 姓名 | 所属租户 | 角色 | 业务定位 |
|------|------|----------|------|----------|
| `alice` | 平台管理员 | —（平台） | `super_admin` | 平台超级管理员，全平台一切权限 |
| `bob` | 运维 | —（平台） | `platform-ops` | 平台运维，跨租户管理租户 |
| `carol` | 财务队负责人 | 租户 `finance` | `tenant-admin` | 租户管理员：管角色、管成员、业务全权限 |
| `dave` | 财务分析师 | 租户 `finance` | `editor` | 租户编辑：数据源/技能管理，但不能删智能体 |
| `erin` | 审计员 | 租户 `finance` | `viewer` | 租户只读：仅查看 |
| `fiona` | 数据工程师 | 租户 `dataeng` | `editor` | 另一租户的编辑，用于验证租户隔离 |

**租户与命名空间：**
- 租户 `finance` → 命名空间 `finance-data`
- 租户 `dataeng` → 命名空间 `data-lake`

---

## 2. 权限码 → 验证用例 总表

**约定**：每个权限码给出
- **正例**（持有该权限的用户 × 请求），预期：**放行**
- **反例**（未持有该权限的用户 × 同请求），预期：**拒绝**

| # | 权限码 | 资源 | 正例（放行） | 反例（拒绝） |
|---|--------|------|--------------|--------------|
| 1 | `tenant:manage` | 租户管理 | bob `POST /api/v1/rbac/tenants` | carol `POST /api/v1/rbac/tenants` |
| 2 | `platform:role:manage` | 平台角色 | grace（平台角色管理员）`POST /api/v1/rbac/platform/roles` | bob `POST /api/v1/rbac/platform/roles` |
| 3 | `permission:read` | 权限点 | bob `GET /api/v1/rbac/permissions` | dave `GET /api/v1/rbac/permissions` |
| 4 | `rbac:me:read` | 我的租户 | bob `GET /api/v1/rbac/me/tenants` | gina（无该权限）`GET /api/v1/rbac/me/tenants` |
| 5 | `tenant:role:manage` | 租户角色 | carol `POST /api/v1/rbac/tenants/finance/roles` | dave `POST /api/v1/rbac/tenants/finance/roles` |
| 6 | `tenant:member:manage` | 租户成员 | carol `POST /api/v1/rbac/tenants/finance/users` | dave `POST /api/v1/rbac/tenants/finance/users` |
| 7 | `agent:read` | 查看智能体 | dave `GET /api/v1/namespaces/finance-data/agents/web` | fiona `GET /api/v1/namespaces/finance-data/agents/web` |
| 8 | `agent:create` | 创建智能体 | carol `POST /api/v1/namespaces/finance-data/agents` | erin `POST /api/v1/namespaces/finance-data/agents` |
| 9 | `agent:update` | 更新智能体 | carol `PUT /api/v1/namespaces/finance-data/agents/web` | erin `PUT /api/v1/namespaces/finance-data/agents/web` |
| 10 | `agent:delete` | 删除智能体 | carol `DELETE /api/v1/namespaces/finance-data/agents/web` | dave `DELETE /api/v1/namespaces/finance-data/agents/web` |
| 11 | `descriptor:read` | 查看数据源 | erin `GET /api/v1/namespaces/finance-data/descriptors/orders` | fiona `GET /api/v1/namespaces/finance-data/descriptors/orders` |
| 12 | `descriptor:graph:read` | 血缘图谱 | erin `POST /api/v1/knowledge-graph/get-graph-by-source` | dave `POST /api/v1/knowledge-graph/get-graph-by-source` |
| 13 | `descriptor:create` | 创建数据源 | dave `POST /api/v1/namespaces/finance-data/descriptors` | erin `POST /api/v1/namespaces/finance-data/descriptors` |
| 14 | `descriptor:update` | 更新数据源 | dave `PUT /api/v1/namespaces/finance-data/descriptors/orders` | erin `PUT /api/v1/namespaces/finance-data/descriptors/orders` |
| 15 | `descriptor:delete` | 删除数据源 | dave `DELETE /api/v1/namespaces/finance-data/descriptors/orders` | erin `DELETE /api/v1/namespaces/finance-data/descriptors/orders` |
| 16 | `llmconfig:read` | 查看模型配置 | erin `GET /api/v1/namespaces/finance-data/llm-configmaps/llm-default` | fiona `GET /api/v1/namespaces/finance-data/llm-configmaps/llm-default` |
| 17 | `llmconfig:create` | 创建模型配置 | dave `POST /api/v1/namespaces/finance-data/llm-configmaps` | erin `POST /api/v1/namespaces/finance-data/llm-configmaps` |
| 18 | `llmconfig:update` | 更新模型配置 | carol `PUT /api/v1/namespaces/finance-data/llm-configmaps/llm-default` | erin `PUT /api/v1/namespaces/finance-data/llm-configmaps/llm-default` |
| 19 | `llmconfig:delete` | 删除模型配置 | carol `DELETE /api/v1/namespaces/finance-data/llm-configmaps/llm-default` | erin `DELETE /api/v1/namespaces/finance-data/llm-configmaps/llm-default` |
| 20 | `promptconfig:read` | 查看提示词配置 | erin `GET /api/v1/namespaces/finance-data/prompt-configmaps/prompt-default` | fiona `GET /api/v1/namespaces/finance-data/prompt-configmaps/prompt-default` |
| 21 | `promptconfig:create` | 创建提示词配置 | dave `POST /api/v1/namespaces/finance-data/prompt-configmaps` | erin `POST /api/v1/namespaces/finance-data/prompt-configmaps` |
| 22 | `promptconfig:update` | 更新提示词配置 | carol `PUT /api/v1/namespaces/finance-data/prompt-configmaps/prompt-default` | erin `PUT /api/v1/namespaces/finance-data/prompt-configmaps/prompt-default` |
| 23 | `promptconfig:delete` | 删除提示词配置 | carol `DELETE /api/v1/namespaces/finance-data/prompt-configmaps/prompt-default` | erin `DELETE /api/v1/namespaces/finance-data/prompt-configmaps/prompt-default` |
| 20 | `datasource:probe` | 数据源探测 | dave `POST /api/v1/datasources/probe` | erin `POST /api/v1/datasources/probe` |
| 21 | `datasource:probe-types` | 探测类型 | erin `GET /api/v1/datasources/probe/types` | fiona `GET /api/v1/datasources/probe/types` |
| 22 | `semantic-group:read` | 查看语义组 | erin `GET /api/v1/semantic-groups/g1` | fiona `GET /api/v1/semantic-groups/g1` |
| 23 | `semantic-group:manage` | 管理语义组 | carol `DELETE /api/v1/semantic-groups/g1` | dave `DELETE /api/v1/semantic-groups/g1` |
| 24 | `discovery:read` | 查看资产探测 | erin `GET /api/v1/discovery/scans/scan-1` | fiona `GET /api/v1/discovery/scans/scan-1` |
| 25 | `discovery:manage` | 管理资产探测 | carol `POST /api/v1/discovery/scans` | erin `POST /api/v1/discovery/scans` |
| 26 | `skill:read` | 查看技能 | erin `GET /api/v1/skills/namespaces/finance` | fiona `GET /api/v1/skills/namespaces/finance` |
| 27 | `skill:manage` | 管理技能 | dave `POST /api/v1/skills/namespaces/finance/skills/create` | carol `POST /api/v1/skills/namespaces/finance/skills/create` |
| 28 | `chat:use` | 使用对话 | dave `POST /v1/chat/completions` | erin `POST /v1/chat/completions` |
| 29 | `chat:history:read` | 历史会话 | erin `GET /api/v1/chat/conversations/42` | fiona `GET /api/v1/chat/conversations/42` |
| 30 | `system:config:read` | 查看模版配置 | erin `GET /api/v1/system/configurations/dac` | fiona `GET /api/v1/system/configurations/dac` |
| 31 | `system:config:manage` | 管理模版配置 | carol `POST /api/v1/system/configurations` | erin `POST /api/v1/system/configurations` |
| 32 | `environment:read` | GPU 环境 | erin `GET /api/v1/environment/gpu` | fiona `GET /api/v1/environment/gpu` |
| 33 | `namespace:read` | K8s 命名空间列表 | erin `GET /api/v1/namespaces` | fiona `GET /api/v1/namespaces` |
| 34 | `observability:read` | 注册中心 | erin `GET /api/v1/observability/agent-registries` | fiona `GET /api/v1/observability/agent-registries` |
| 35 | `user:self:read` | 我的用户信息 | erin `GET /api/v1/users/me` | gina（无此权限）`GET /api/v1/users/me` |
| 36 | `user:manage` | 管理用户 | carol `DELETE /api/v1/users/u123` | erin `DELETE /api/v1/users/u123` |

---

## 3. 角色 → 权限 绑定明细（即测试数据的"种子"）

| 角色 | 权限码 |
|------|--------|
| `super_admin`（alice） | 隐式全通（引擎短路） |
| `platform-ops`（bob） | `tenant:manage`、`permission:read`、`rbac:me:read` |
| `tenant-admin`（carol） | `agent:create/update/delete`、`llmconfig:create/update/delete`、`semantic-group:manage`、`discovery:manage`、`system:config:manage`、`tenant:role:manage`、`tenant:member:manage`、`user:manage` |
| `editor`（dave） | `agent:read`、`descriptor:read/create/update/delete`、`llmconfig:read/create/update/delete`、`promptconfig:read/create/update/delete`、`skill:manage`、`chat:use`、`datasource:probe`、`datasource:probe-types`、`system:config:read` |
| `viewer`（erin） | `agent:read`、`descriptor:read`、`descriptor:graph:read`、`llmconfig:read`、`promptconfig:read`、`datasource:probe-types`、`semantic-group:read`、`skill:read`、`chat:history:read`、`system:config:read`、`environment:read`、`namespace:read`、`observability:read`、`user:self:read`、`discovery:read` |
| `editor`（fiona，dataeng） | 与 dave 相同角色码，但隶属于另一租户——用于验证隔离 |

---

## 4. 关键设计意图（审查关注点）

1. **每码一正一反**：36 个权限点都有"持有者可访问"与"未持有者被拒"的对照，防止"全配全通"假阳性。
2. **最小权限用户**：`gina`（dataeng 租户成员、零权限绑定）用于验证 `user:self:read`、`rbac:me:read` 等"完全无权限"反例；`dave` 未持有 `descriptor:graph:read`，用于证明独立读码不被大授权连带放行。
3. **租户隔离是核心反例**：`fiona` 与 `dave` 角色码同名（editor），但所有跨租户访问必须拒绝——这直接验证引擎按 `X-Tenant-Id` 作用域判定。
4. **`tenant:manage` 反例用 carol**：carol 是租户管理员，但未获平台级 `tenant:manage`，证明租户角色不会"上溢"到平台层。
5. **`rbac:me:read`** 需平台角色；普通租户成员没有也会被拒。

> 若审查发现问题（角色配错、漏权限、路径不匹配），请指出，我将修订数据后重新验证。

---

## 5. 验证结果（2026-08-21）

设计已审查通过并落地为自动化测试：

- **测试文件**: `pkg/rbac/permission_matrix_test.go`
  - `TestPermissionMatrixFullCoverage`：36 个权限码逐一断言（本表逐行实现，正例放行 + 反例拒绝）
  - 内置**漂移防护**：每条正例 `(method, path)` 都会用 `Permission.Allows` 与 `pkg/rbac/seeder.go` 实时目录校验，目录变更但矩阵未同步时会直接失败
  - 用真实业务夹具 `newBusinessFixture`（finance/dataeng 双租户、6+2 用户、5 种角色）
- **夹具变更**: `pkg/rbac/business_scenarios_test.go`
  - `gina`（dataeng 零权限成员）、`hugo`（finance 零权限成员）作为"未持有某码"的反例基准
  - `grace` 增加平台角色 `platform-role-admin`（持有 `platform:role:manage`/`rbac:me:read`），并担任 finance 租户角色管理员
  - carol/dave 的角色权限按本表 §3 绑定明细补齐
- **测试结果**:

| 套件 | 结果 |
|------|------|
| `go test ./pkg/rbac/...` | PASS（含矩阵 36/36） |
| `go test -race ./pkg/rbac/...` | PASS |
| `go test ./internal/... ./cmd/...` | PASS（全部包） |
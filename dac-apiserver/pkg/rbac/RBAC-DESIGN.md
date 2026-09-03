# DAC RBAC 权限体系设计文档

> 模块路径: `pkg/rbac/`(后端核心模块) + `internal/{handler,usecase,domain}/rbac/`(管理 API) + 前端 `admin/` 页面
>
> 状态: **定稿**(2026-08-20)。本模块为「用户 - 租户 - 角色 - 权限」的独立权限治理方案,替代旧的 Casbin 文件配置体系。

---

## 1. 设计目标与原则

### 1.1 目标

1. **权限配置全部入库、全部页面化** —— 彻底去除 `configs/authz/policy.csv` / `model.conf` / Casbin 依赖;任何权限变更通过管理 API/页面完成,实时生效,无需重启。
2. **平台管理员可页面管理** —— "谁是平台管理员"由 `platform_user_role` 表表达,页面可增删;"平台管理员能做什么"由平台角色绑定权限点表达。
3. **多租户隔离** —— 租户是资源与权限的边界;每个普通用户必须先进入某个租户、获得该租户内角色,才能访问该租户的资源。
4. **用户可属于多个租户** —— 一个账号在多个租户可拥有不同角色,互不干扰。
5. **独立模块** —— 授权判定能力封装在 `pkg/rbac` 单包内,业务代码只通过中间件/注解使用,不感知内部实现。

### 1.2 原则

- **默认拒绝(deny-by-default)**:任何请求只要没有命中任何权限点,一律 403。
- **JWT 只做身份(authentication)**,**权限每次请求实时查库(authorization)**:不信任 token 里的角色快照,解决"改角色不生效必须等过期"的老问题。
- **平台链路与租户链路统一同一套判定引擎**,区别只在于"域(domain)"维度。

---

## 2. 术语与角色模型

```
用户 User ──┬─(平台)──▶ platform_user_role ──▶ platform_role ──▶ platform_role_permission ──▶ permission
            └─(租户)──▶ tenant_user ──▶ tenant_role ──▶ tenant_role_permission ──▶ permission
```

| 名词 | 英文 | 含义 |
|------|------|------|
| 平台角色 | `platform_role` | 平台级角色,如 `super_admin`(全通)/ `ops` / `auditor`,不绑定租户 |
| 租户 | `tenant` | 资源与权限的边界,映射到一组 K8s namespace |
| 租户角色 | `tenant_role` | 租户内自定义角色,如 `viewer` / `editor`,由租户管理员在页面配置 |
| 权限点 | `permission` | 最小授权单元,携带 `http_method + http_path`,运行时用它做请求匹配(见 §4.3) |
| 成员关系 | `tenant_user` | "用户在哪个租户是什么角色",一个用户在一个租户只能有一个角色 |

---

## 3. 数据模型设计(通用命名)

> 设计原则:**不携带产品名前缀(dac)**,全部使用业界通用 RBAC 命名,便于理解与复用。

### 3.1 平台层

#### `platform_role` 平台角色

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| code | string | 角色编码,全平台唯一,如 `super_admin` |
| name | string | 展示名 |
| is_super | bool | 是否超管(命中即全通,免权限点校验) |
| description | string | 描述 |
| created_at / updated_at | time | 审计 |

#### `platform_user_role` 平台用户角色(谁是平台管理员)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | UUID | FK → `users` |
| role_id | UUID | FK → `platform_role` |
| created_at | time | 审计 |

> 唯一约束 `(user_id, role_id)`。把"某用户设为平台管理员"= 在该表写入一行 `(user_id, super_admin)`。

#### `platform_role_permission` 平台角色权限

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| role_id | UUID | FK → `platform_role` |
| permission_id | UUID | FK → `permission` |
| created_at | time | 审计 |

> 唯一约束 `(role_id, permission_id)`。

### 3.2 租户层

#### `tenant` 租户

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| code | string | 租户编码,全局唯一,如 `default` / `acme` |
| name | string | 展示名 |
| status | string | `active` / `disabled`;禁用后该租户所有成员鉴权失败 |
| description | string | 描述 |
| created_at / updated_at | time | 审计 |

#### `tenant_namespace` 租户持有的 K8s namespace

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| tenant_id | UUID | FK → `tenant` |
| namespace | string | K8s namespace 名;`"*"` 表示该租户持有全部 namespace |

> 唯一约束 `(tenant_id, namespace)`。

#### `tenant_role` 租户内角色

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| tenant_id | UUID | FK → `tenant` |
| code | string | 角色编码,`(tenant_id, code)` 唯一 |
| name | string | 展示名 |
| is_default | bool | 新成员加入且未指定角色时使用 |
| description | string | 描述 |
| created_at / updated_at | time | 审计 |

#### `tenant_user` 用户租户归属

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| tenant_id | UUID | FK → `tenant` |
| user_id | UUID | FK → `users` |
| role_id | UUID | FK → `tenant_role` |
| created_at | time | 审计 |

> 唯一约束 `(tenant_id, user_id)`:一个用户在一个租户只有一个角色。

#### `tenant_role_permission` 租户角色权限

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| role_id | UUID | FK → `tenant_role` |
| permission_id | UUID | FK → `permission` |
| created_at | time | 审计 |

> 唯一约束 `(role_id, permission_id)`。

### 3.3 权限点

#### `permission` 权限点

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| code | string | 机器码,全局唯一,如 `agent:create` |
| name | string | 展示名 |
| resource | string | 资源域,如 `agent` / `descriptor` / `configmap` |
| action | string | 动作,如 `read` / `create` / `update` / `delete` / `manage` |
| http_method | string | 允许的 HTTP 方法(BigInt 位掩码或逗号串,见 §4.3) |
| http_path | string | 路径模板,支持通配,如 `/api/v1/**` |
| description | string | 描述 |

> **权限点为全局静态种子**:由 `seeder.go` 在初始化时写入,页面只能"勾选",不能新增/修改规则。规则(方法+路径)是代码常量,防止把权限配置变成任意脚本。

---

## 4. 运行期鉴权设计

### 4.1 总体流程

```
HTTP 请求
   │
   ▼
AuthMiddleware(JWT)         校验 token 有效性 → 取 user_id
   │
   ▼
RBAC Middleware             (本模块核心)
   │  · 取 X-Tenant-Id(可选;平台级操作可不带)
   │  · 查库得:
   │       platform_roles(user_id)  → is_super? 全放行:收集权限点
   │       tenant_role(user_id, tenant_id) → 收集权限点
   │  · 用 请求(method, path) × 权限点(http_method, http_path) 匹配
   │
   ├─ 命中 → 放行,注入 c.Set("perm_codes", [...]) 供 handler 使用
   └─ 未命中 → 403 {"code":"FORBIDDEN","message":"..."}
```

### 4.2 判定函数

```go
// pkg/rbac/engine.go
type Result struct {
    Allowed bool
    Codes   []string // 匹配命中的权限点码(供 handler/前端使用)
}

func (e *Engine) Authorize(ctx context.Context, userID string, tenantID string, method, path string) (Result, error)
```

判定顺序:
1. 查平台角色;若含 `is_super == true` → 直接 `Allowed`。
2. 否则收集平台角色权限点 + (若带租户)租户角色权限点。
3. 用 `matcher.Match(method, path, perm)` 逐点匹配,任一命中即允许。

### 4.3 规则匹配(matcher)

用**方法 + 路径模板**做匹配,取代 Casbin keyMatch2:

- `http_method` 支持 `*`(任意方法)或精确方法,可用逗号分隔多方法。
- `http_path` 支持通配:
  - `*` 匹配一段(不含 `/`);
  - `**` 匹配任意多段(含 `/`)。
- 匹配算法在 `matcher.go` 独立实现,便于将来增补 DSL/正则规则。

示例权限点:

| code | resource | action | http_method | http_path |
|------|----------|--------|-------------|-----------|
| `agent:read` | agent | read | GET | `/api/v1/namespaces/*/agents` |
| `agent:read` | agent | read | GET | `/api/v1/namespaces/*/agents/*` |
| `agent:create` | agent | create | POST | `/api/v1/namespaces/*/agents` |
| `agent:delete` | agent | delete | DELETE | `/api/v1/namespaces/*/agents/*` |
| `llmconfig:read` | llmconfig | read | GET | `/api/v1/namespaces/*/llm-configmaps` |
| `llmconfig:create` | llmconfig | create | POST | `/api/v1/namespaces/*/llm-configmaps` |
| `promptconfig:read` | promptconfig | read | GET | `/api/v1/namespaces/*/prompt-configmaps` |
| `promptconfig:create` | promptconfig | create | POST | `/api/v1/namespaces/*/prompt-configmaps` |
| `system:config:manage` | system_config | manage | *,* | `/api/v1/system/configurations/**` |
| `chat:use` | chat | use | POST | `/v1/chat/completions` |

### 4.4 缓存与热更新

- `Engine` 内置进程内缓存(角色→权限点,租户→namespace),按 `(user_id, tenant_id)` 异步聚合,TTL + 失效信号双通道。
- 每次**管理 API 变更角色/权限/租户态**时,调用 `Engine.Invalidate(...)` 主动失效缓存行,保证"页面点了立即生效"。
- 平台层 `super_admin` 判断不走缓存,直接查 `platform_user_role`(低频,保证即时性)。

---

## 5. 模块代码结构与文件职责

```
pkg/rbac/                     ← 独立授权模块(无业务耦合)
├── RBAC-DESIGN.md            ← 本文档
├── model.go                  ← 领域类型(PlatformRole / TenantRole / Permission / 聚合结果)
├── engine.go                 ← 核心引擎:Authorize / 缓存 / Invalidate
├── matcher.go                ← 规则匹配(方法+路径通配)
├── repository.go             ← DB 访问接口(供引擎与管理 API 共用)
├── seeder.go                 ← 权限点 / super_admin / 默认租户 初始化种子
├── middleware.go             ← hertz 鉴权中间件(挂到受保护路由)
└── middleware_test.go        ← 中间件与引擎单元测试

internal/
├── domain/rbac/              ← 领域接口(UserTenantRepo / PlatformRoleRepo …),供 usecase 编程
├── usecase/rbac/             ← 业务用例:租户/角色/成员/平台管理员管理
├── handler/rbac/             ← HTTP handler:映射 /api/v1/rbac/** 路由
├── handler/dto/rbac/         ← 请求/响应 DTO
└── infrastructure/database/rbac/ ← 仓储实现(ent client,实现 pkg/rbac.Storage 与领域接口),独立子包

前端(Next.js App Router)
├── src/lib/rbac.ts           ← 会话类型 user_tenants / permission_codes
├── src/lib/tenant.ts         ← 租户切换状态 + X-Tenant-Id 注入
├── src/components/rbac.tsx   ← RbacButton 升级:requiredPermission 按权限码渲染
└── src/app/(dashboard)/admin/
    ├── tenants/              ← 租户列表/新建/namespace关联
    ├── tenants/[tid]/roles/  ← 角色管理 + 权限勾选
    ├── tenants/[tid]/members/← 租户成员增删/改角色
    └── platform/             ← 平台角色 + 平台管理员管理
```

---

## 6. 管理 API 设计(挂 `/api/v1/rbac/`)

> 所有管理操作默认要求平台角色权限;租户级操作(roles/members)要求"该租户内拥有对应管理权限点"。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST/GET | `/api/v1/rbac/tenants` | 创建/分页查询租户 |
| GET/PUT | `/api/v1/rbac/tenants/:id` | 查看/更新租户(含启停) |
| DELETE | `/api/v1/rbac/tenants/:id` | 删除租户(校验无关联资源) |
| GET | `/api/v1/rbac/tenants/:id/namespaces` | 查看租户持有的 namespace |
| POST/DELETE | `/api/v1/rbac/tenants/:id/namespaces` | 关联/解除 namespace |
| GET | `/api/v1/rbac/tenants/:id/roles` | 角色列表(包含权限点) |
| POST/PUT/DELETE | `/api/v1/rbac/tenants/:id/roles/:rid` | 角色增删改 |
| PUT | `/api/v1/rbac/tenants/:id/roles/:rid/permissions` | 角色权限勾选(全量覆盖) |
| GET | `/api/v1/rbac/tenants/:id/users` | 租户成员列表 |
| POST | `/api/v1/rbac/tenants/:id/users` | 加入租户(绑角色) |
| PUT | `/api/v1/rbac/tenants/:id/users/:uid/role` | 变更成员角色 |
| DELETE | `/api/v1/rbac/tenants/:id/users/:uid` | 移除成员 |
| GET | `/api/v1/rbac/permissions` | 权限点清单(供页面勾选) |
| GET | `/api/v1/rbac/platform/roles` | 平台角色列表 |
| POST | `/api/v1/rbac/platform/roles` | 新建平台角色 |
| PUT | `/api/v1/rbac/platform/roles/:rid` | 更新平台角色(is_super/权限) |
| GET | `/api/v1/rbac/platform/users` | 平台管理员列表 |
| POST | `/api/v1/rbac/platform/users` | 设置平台管理员(绑定 super_admin) |
| DELETE | `/api/v1/rbac/platform/users/:uid` | 移除平台管理员 |
| GET | `/api/v1/rbac/me/tenants` | 当前用户可选的租户列表(租户切换用) |

---

## 7. 存量数据迁移与兼容

### 7.1 迁移步骤

1. `seeder.go` 初始化时:
   - upsert `permission` 种子(§4.3 全量清单);
   - upsert 平台角色 `super_admin`(`is_super=true`) 与一张"可写平台角色";
   - 创建默认租户 `default`,并为其绑定 `tenant_namespace("*")`;
   - 创建默认租户角色 `viewer`(映射旧 `p, user` 只读权限) 与 `editor`;
2. 存量用户:
   - `users.role='admin'` → 写入 `platform_user_role(user, super_admin)`;**行为完全等价于旧 `p, admin, *, *`**;
   - `users.role='user'` → 写入 `tenant_user(user, default, viewer)`;**行为等价于旧 `p, user` 只读白名单**;
3. 移除 `usecase.SeedAdmin` 调用与逻辑,替换为 `rbac.SeedDefaults`。

### 7.2 首个管理员引导

全新安装时不存在任何 `users.role='admin'` 的用户,而授予第一个平台管理员的 `GrantPlatformRole` 又受 `platform:role:manage`(仅 super_admin 可调)保护——若不引导,平台将陷入"无人能授予第一个管理员"的死锁。`SeedDefaults` 内置 `seedBootstrapAdmin` 打破该循环,且保证幂等:

1. 若 `super_admin` 平台角色已有人持有(`platform_user_role` 非空)→ **直接跳过**,重启绝不重置/覆盖既有管理员凭据;
2. 否则创建首个超级管理员并授予 `super_admin`,凭据来源优先级:
   - 配置 `bootstrap.admin` / `bootstrap.password`(生产可用 `DAC_BOOTSTRAP_ADMIN` / `DAC_BOOTSTRAP_PASSWORD` 注入密钥);
   - 未配置时使用内置默认 `admin` / `changeme`,日志以 WARN 醒目标注"请在首次登录后立即改密";
3. 同步写入 `users.role='admin'`,保证旧 JWT 消费方(前端 `isAdmin` 兜底)在 role 列退役前的过渡期行为一致;引擎鉴权仍以 `platform_user_role` 为准。

> 说明:引导账号**不自动加入 default 租户**。super_admin 是平台级隐式全通,应仅由管理员按需绑定真实租户,避免默认租户被"全员可见"的既有问题放大。

### 7.3 兼容保证

- 平台管理员(旧 admin)全权限链路完全保留,登录/JWT/前端 `isAdmin` 不受影响。
- 普通用户默认能访问原 `p,user` 白名单内的只读接口(viewer 角色携带对应权限点)。
- 旧 token 无需重签:新鉴权不再信任 JWT role,一律查库。

---

## 8. 编写规范(本项目强制)

> 以下为 `pkg/rbac` 及所有权限相关代码的强制编码约束,评审/合入必须满足。

### 8.1 命名

- **杜绝无意义命名**:不允许 `tmp` / `data` / `a` / `x` / `result1` 等;每个变量/函数/类型名必须自解释业务含义。
- 布尔尽量正向命名:`IsSuperAdmin`、`CanManage`;避免 `NotDisabled` 这类双重否定。
- 单一职责:方法名包含动作与对象,如 `AssignPlatformRole`、`RevokeTenantMembership`。

### 8.2 注释

- 注释必须可读、有信息量:写清**为什么这么做、边界条件、不变量**,不写"设置 xx 字段"这类流水账。
- 对外导出符号(类型/方法/常量)一律写 Go doc 注释(以符号名开头)。
- 非显然的业务规则(如"租户禁用后成员全部鉴权失败")必须注释说明。

### 8.3 日志

- 权限相关**关键业务操作**必须打结构化日志(`slog`),上下文包含业务标识:
  - 创建/禁用租户:`tenant_id` / `tenant_code`;
  - 绑定/变更角色:`user_id` / `tenant_id` / `role_code`;
  - 权限勾选变更:`role_id` / 变更权限点数量;
  - 鉴权拒绝:记录 `user_id` / `tenant_id` / `method` / `path` / `reason`(审计留痕;默认 warn 级)。
- 日志消息使用业务语义描述(如 `"tenant created"`、`"platform admin granted"`),不用纯调试词。
- 鉴权成功不放日志(避免噪音);鉴权失败必须打(审计)。

### 8.4 错误处理

- 使用项目既有 `internal/domain/errors.go` 的错误体系(NotFound / AlreadyExists / InvalidInput / Forbidden)。
- 鉴权失败统一 `403 Forbidden`,不得泄露"差哪个权限点"(防探测),落日志可含详情。

---

## 9. 验收清单

- [ ] `configs/authz/` 已删除,`go.mod` 无 casbin 依赖,`router.go` 无 Enforcer。
- [ ] 平台管理员(旧 admin)全权限行为与改造前一致(迁移测试覆盖)。
- [ ] 普通用户只读白名单行为与改造前一致(viewer 权限点覆盖)。
- [ ] 页面:租户 CRUD / namespace 关联 / 角色 CRUD / 权限勾选 / 成员管理 / 平台管理员管理 全部可用。
- [ ] 租户禁用后成员立即 403;权限勾选变更后立即生效(缓存失效验证)。
- [ ] 前端租户切换器可用,业务页按钮按权限码渲染。
- [ ] 权限相关业务日志落地,鉴权拒绝有审计日志。
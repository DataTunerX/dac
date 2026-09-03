package rbac

// Permission defines the static permission catalog seeded into the database.
//
// The catalog is the single source of truth for "what an action in the UI means
// on the wire". It is versioned in code (not editable from the page) so that the
// runtime rule matching stays predictable; the management UI only binds these
// codes to roles.
type SeedPermission struct {
	Code        string
	Name        string
	Resource    string
	Action      string
	HTTPMethod  string
	HTTPPath    string
	Description string
}

// SeedPermissions is the full permission catalog for the platform and tenant layers.
//
// Methods/patterns follow §4.3 of RBAC-DESIGN.md:
//   - HTTPMethod "*" means any method; "GET,POST" means both.
//   - HTTPPath "*" matches one segment; "**" matches any suffix.
//
// When adding a new capability, add its permission here (and migrate the seed),
// then reference the code from the management UI; no role data needs a code change.
var SeedPermissions = []SeedPermission{
	// ---- platform (management API) ----
	// tenant:manage covers the whole tenant subtree (list/detail/status/namespaces)
	// so every tenant management endpoint stays reachable for that single grant.
	{Code: "tenant:read", Name: "查看租户", Resource: "tenant", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/rbac/tenants/**", Description: "查看租户列表与详情"},
	{Code: "tenant:manage", Name: "管理租户", Resource: "tenant", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/rbac/tenants/**", Description: "创建/更新/删除租户"},
	{Code: "platform:role:read", Name: "查看平台角色", Resource: "platform_role", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/rbac/platform/**", Description: "查看平台角色列表与详情"},
	{Code: "platform:role:manage", Name: "管理平台角色", Resource: "platform_role", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/rbac/platform/**", Description: "平台角色与平台管理员管理"},
	{Code: "permission:read", Name: "查看权限点", Resource: "permission", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/rbac/permissions", Description: "查看权限点清单"},
	{Code: "rbac:me:read", Name: "查看我的租户", Resource: "rbac_me", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/rbac/me/tenants", Description: "当前用户可选的租户列表"},

	// ---- tenant layer (scoped to a tenant via X-Tenant-Id) ----
	// The trailing "/**" covers the sub-resources of each collection, i.e. role
	// permission assignment (.../roles/:rid/permissions) and member role changes
	// (.../users/:uid/role), which must be granted together with their parent.
	{Code: "tenant:role:read", Name: "查看租户角色", Resource: "tenant_role", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/rbac/tenants/**/roles/**", Description: "查看租户内角色列表与权限"},
	{Code: "tenant:role:manage", Name: "管理租户角色", Resource: "tenant_role", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/rbac/tenants/**/roles/**", Description: "租户内角色增删改与权限勾选"},
	{Code: "tenant:member:read", Name: "查看租户成员", Resource: "tenant_user", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/rbac/tenants/**/users/**", Description: "查看租户内成员列表"},
	{Code: "tenant:member:manage", Name: "管理租户成员", Resource: "tenant_user", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/rbac/tenants/**/users/**", Description: "租户成员增删与角色变更"},

	// ---- business resources (existing API surface) ----
	{Code: "agent:read", Name: "查看智能体", Resource: "agent", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/agents|/api/v1/namespaces/*/agents/**", Description: "查看全部智能体"},
	{Code: "agent:read", Name: "查看智能体详情", Resource: "agent", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/namespaces/*/agents/*", Description: "查看智能体详情"},
	{Code: "agent:create", Name: "创建智能体", Resource: "agent", Action: ActionWrite, HTTPMethod: "POST", HTTPPath: "/api/v1/namespaces/*/agents", Description: "创建智能体"},
	{Code: "agent:update", Name: "更新智能体", Resource: "agent", Action: ActionWrite, HTTPMethod: "PUT", HTTPPath: "/api/v1/namespaces/*/agents/*", Description: "更新智能体"},
	{Code: "agent:delete", Name: "删除智能体", Resource: "agent", Action: ActionWrite, HTTPMethod: "DELETE", HTTPPath: "/api/v1/namespaces/*/agents/*", Description: "删除智能体"},

	{Code: "descriptor:read", Name: "查看数据描述符", Resource: "descriptor", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/descriptors|/api/v1/namespaces/*/descriptors/**", Description: "查看数据描述符列表/详情/签名/语义域/知识分片"},
	{Code: "descriptor:graph:read", Name: "查看数据血缘图谱", Resource: "descriptor", Action: ActionRead, HTTPMethod: "POST", HTTPPath: "/api/v1/knowledge-graph/get-graph-by-source", Description: "数据源详情页的知识图谱/血缘关系展示"},
	{Code: "descriptor:create", Name: "创建数据描述符", Resource: "descriptor", Action: ActionWrite, HTTPMethod: "POST", HTTPPath: "/api/v1/namespaces/*/descriptors", Description: "创建数据描述符"},
	{Code: "descriptor:update", Name: "更新数据描述符", Resource: "descriptor", Action: ActionWrite, HTTPMethod: "PUT,POST", HTTPPath: "/api/v1/namespaces/*/descriptors/*|/api/v1/namespaces/*/descriptors/*/resync", Description: "更新数据描述符与触发重同步"},
	{Code: "descriptor:delete", Name: "删除数据描述符", Resource: "descriptor", Action: ActionWrite, HTTPMethod: "DELETE", HTTPPath: "/api/v1/namespaces/*/descriptors/*", Description: "删除数据描述符"},

	{Code: "llmconfig:read", Name: "查看模型配置", Resource: "llmconfig", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/namespaces/*/llm-configmaps|/api/v1/namespaces/*/llm-configmaps/*", Description: "查看模型管理列表与详情"},
	{Code: "llmconfig:create", Name: "创建模型配置", Resource: "llmconfig", Action: ActionWrite, HTTPMethod: "POST", HTTPPath: "/api/v1/namespaces/*/llm-configmaps", Description: "创建 LLM 模型配置"},
	{Code: "llmconfig:update", Name: "更新模型配置", Resource: "llmconfig", Action: ActionWrite, HTTPMethod: "PUT", HTTPPath: "/api/v1/namespaces/*/llm-configmaps/*", Description: "更新 LLM 模型配置"},
	{Code: "llmconfig:delete", Name: "删除模型配置", Resource: "llmconfig", Action: ActionWrite, HTTPMethod: "DELETE", HTTPPath: "/api/v1/namespaces/*/llm-configmaps/*", Description: "删除 LLM 模型配置"},

	{Code: "promptconfig:read", Name: "查看提示词配置", Resource: "promptconfig", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/namespaces/*/prompt-configmaps|/api/v1/namespaces/*/prompt-configmaps/*", Description: "查看提示词列表与详情"},
	{Code: "promptconfig:create", Name: "创建提示词配置", Resource: "promptconfig", Action: ActionWrite, HTTPMethod: "POST", HTTPPath: "/api/v1/namespaces/*/prompt-configmaps", Description: "创建提示词配置"},
	{Code: "promptconfig:update", Name: "更新提示词配置", Resource: "promptconfig", Action: ActionWrite, HTTPMethod: "PUT", HTTPPath: "/api/v1/namespaces/*/prompt-configmaps/*", Description: "更新提示词配置"},
	{Code: "promptconfig:delete", Name: "删除提示词配置", Resource: "promptconfig", Action: ActionWrite, HTTPMethod: "DELETE", HTTPPath: "/api/v1/namespaces/*/prompt-configmaps/*", Description: "删除提示词配置"},

	{Code: "system:config:read", Name: "查看模版配置", Resource: "system_config", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/system/configurations/**", Description: "查看模版中心列表/详情/历史版本"},
	{Code: "system:config:manage", Name: "管理模版配置", Resource: "system_config", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/system/configurations/**", Description: "创建、编辑、生效模版"},

	{Code: "environment:read", Name: "查看环境GPU", Resource: "environment", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/environment/gpu", Description: "查看GPU可用性"},
	{Code: "namespace:read", Name: "查看 K8s 命名空间列表", Resource: "namespace", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/namespaces", Description: "查看 K8s 命名空间列表"},
	{Code: "observability:read", Name: "查看注册中心", Resource: "observability", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/observability/**", Description: "查看注册中心 Agent 注册信息"},

	{Code: "semantic-group:read", Name: "查看语义组", Resource: "semantic_group", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/semantic-groups/**|/api/v1/dd-group-relations/**|/api/v1/semantic-domains/*", Description: "查看语义组与语义组关联"},
	{Code: "semantic-group:manage", Name: "管理语义组", Resource: "semantic_group", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/semantic-groups/**|/api/v1/dd-group-relations/**|/api/v1/semantic-domains/search/by-dd", Description: "管理语义组(增删改)与解除数据源关联"},

	{Code: "discovery:read", Name: "查看资产探测", Resource: "discovery", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/discovery/scans/**", Description: "查看资产探测扫描列表与详情"},
	{Code: "discovery:manage", Name: "管理资产探测", Resource: "discovery", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/discovery/scans/**", Description: "发起/删除资产探测扫描"},

	{Code: "datasource:probe", Name: "数据源探测", Resource: "datasource", Action: ActionWrite, HTTPMethod: "POST", HTTPPath: "/api/v1/datasources/probe", Description: "探测数据源连通性"},
	{Code: "datasource:probe-types", Name: "查看探测类型", Resource: "datasource", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/datasources/probe/types", Description: "查看支持的数据源类型"},

	{Code: "skill:read", Name: "查看技能", Resource: "skill", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/skills/namespaces/*/skills/**", Description: "查看技能市场列表/详情/下载"},
	{Code: "skill:manage", Name: "管理技能", Resource: "skill", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/skills/namespaces/*/skills/**", Description: "创建/上传/更新/删除技能"},
	{Code: "skill:namespace:read", Name: "查看技能命名空间", Resource: "skill_namespace", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/skills/namespaces|/api/v1/skills/namespaces/*/exists", Description: "查看技能命名空间列表"},
	{Code: "skill:namespace:manage", Name: "管理技能命名空间", Resource: "skill_namespace", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/skills/namespaces|/api/v1/skills/namespaces/*", Description: "创建/删除技能命名空间"},

	{Code: "chat:use", Name: "使用对话", Resource: "chat", Action: ActionWrite, HTTPMethod: "POST", HTTPPath: "/v1/chat/completions", Description: "发起对话"},
	{Code: "chat:history:read", Name: "查看历史会话", Resource: "chat", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/chat/conversations/**", Description: "查看最近会话"},
	{Code: "user:self:read", Name: "查看自己的用户信息", Resource: "user", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/users/me", Description: "查看当前登录用户信息"},
	{Code: "user:read", Name: "查看用户", Resource: "user", Action: ActionRead, HTTPMethod: "GET", HTTPPath: "/api/v1/users|/api/v1/users/*", Description: "查看用户列表与详情"},
	{Code: "user:manage", Name: "管理用户", Resource: "user", Action: ActionManage, HTTPMethod: "*", HTTPPath: "/api/v1/users/**", Description: "用户管理(列表/删除)"},
}

// DefaultCodes is a convenience slice of the permission codes that the legacy
// "user" role was granted (the old p,user whitelist). It is used to seed the
// default tenant role "viewer" during migration so that existing accounts keep
// their current read-only behaviour.
var DefaultCodes = []string{
	"user:self:read",
	"rbac:me:read",
	"chat:history:read",
	"chat:use",
	"agent:read",
	"descriptor:read",
	"descriptor:graph:read",
	"environment:read",
	"namespace:read",
	"llmconfig:read",
	"promptconfig:read",
	"system:config:read",
	"observability:read",
	"semantic-group:read",
	"discovery:read",
	"datasource:probe",
	"datasource:probe-types",
	"skill:read",
	"skill:namespace:read",
	"tenant:read",
	"tenant:role:read",
	"tenant:member:read",
	"user:read",
}

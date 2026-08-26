package rbac

import (
	"context"
	"strings"
	"testing"
)

// Business scenario fixture — a realistic multi-tenant organization.
//
// Organization:
//   - alice   platform super admin (bypasses every check)
//   - bob     platform "platform-ops" role   → tenant:manage across all tenants
//   - tenant A "finance"   (namespaces: finance-data)  → carol(dave)erin
//   - tenant B "dataeng"   (namespaces: data-lake)     → fiona
//
// Role → permission code matrix (mirrors what the management UI would bind):
//
//	                    tenant A         tenant B
//	                    carol  dave  erin    fiona
//	tenant:manage        —      —     —       —
//	tenant:role:manage   ✓      —     —       —
//	tenant:member:manage ✓      —     —       —
//	agent:delete         ✓      —     —       —
//	descriptor:write     ✓      ✓     —       —
//	llmconfig:read       ✓      ✓     ✓       ✓
//	skill:manage         —      ✓     —       —
//	semantic-group:read  ✓      ✓     ✓       ✓
//	chat:use             ✓      ✓     —       ✓
//
// These permissions mirror a real collaboration: erin only reads; dave manages
// skills and descriptors but cannot delete agents; carol is the tenant admin.

const (
	tenantFinance = "finance"
	tenantDataEng = "dataeng"
	nsFinance     = "finance-data"
	nsDataLake    = "data-lake"

	roleTenantAdmin = "tenant-admin"
	roleEditor      = "editor"
	roleViewer      = "viewer"
	roleOps         = "platform-ops"
	roleRoleAdmin   = "role-admin"
	roleSemantic    = "semantic-owner"

	userAlice = "alice"
	userBob   = "bob"
	userCarol = "carol"
	userDave  = "dave"
	userErin  = "erin"
	userFiona = "fiona"
	userGina  = "gina"
	userGrace = "grace"
	userHugo  = "hugo"
)

// addRolePermission binds permission codes directly to a role id, multiplexing
// multiple codes under one role id so the engine's GetRolePermissions contract
// (roleID → permissionIDs → codes) reproduces how the seeder persists roles.
func addRolePermissionCodes(store *fakeStorage, roleID string, codes ...string) {
	ids := make([]string, 0, len(codes))
	for _, c := range codes {
		id := roleID + ":perm:" + c
		ids = append(ids, id)
		method, path := ruleForCode(c)
		store.addPerm(id, c, method, path)
	}
	store.mu.Lock()
	store.rolePerms[roleID] = ids
	store.mu.Unlock()
}

// ruleForCode returns the compressed HTTP method + path template for a
// permission code, sourced directly from the merged seed catalog (the real
// production catalog). Using this instead of hand-maintained copies guarantees
// the synthetic storage rule surface can never drift from seeder.go.
func ruleForCode(code string) (method, path string) {
	merged := mergeSeedPermissions(SeedPermissions)
	sp, ok := merged[code]
	if !ok {
		return "GET", "/api/v1/**" // never reached if the catalog is complete
	}
	return sp.HTTPMethod, strings.Join(sp.PathTemplates, "|")
}

// newBusinessFixture builds the full multi-tenant storage from the scenario
// defined at the top of this file, plus a fresh engine over it.
func newBusinessFixture(t *testing.T) *Engine {
	t.Helper()
	store := newFakeStorage()

	// Tenant namespaces (what each tenant may reach).
	store.mu.Lock()
	store.tenantNamespaces[tenantFinance] = []string{nsFinance}
	store.tenantNamespaces[tenantDataEng] = []string{nsDataLake}
	store.mu.Unlock()

	// -- platform roles --
	store.platformRoles[userAlice] = []PlatformRole{{ID: "pr-super", Code: "super_admin", IsSuper: true}}
	store.platformRoles[userBob] = []PlatformRole{{ID: "pr-ops", Code: roleOps}}
	addRolePermissionCodes(store, "pr-ops",
		"tenant:manage", "user:self:read", "permission:read", "rbac:me:read",
	)

	store.platformRoles[userGrace] = []PlatformRole{{ID: "pr-role-admin", Code: "platform-role-admin"}}
	addRolePermissionCodes(store, "pr-role-admin", "platform:role:manage", "rbac:me:read")

	// -- tenant A (finance) --
	store.tenantRoles[userCarol+":"+tenantFinance] = &TenantRole{ID: "tr-a-admin", TenantID: tenantFinance, Code: roleTenantAdmin}
	addRolePermissionCodes(store, "tr-a-admin",
		"tenant:role:manage", "tenant:member:manage",
		"agent:create", "agent:update", "agent:delete",
		"descriptor:read",
		"llmconfig:read", "llmconfig:create", "llmconfig:update", "llmconfig:delete",
		"semantic-group:manage", "discovery:manage", "system:config:manage",
		"user:manage", "chat:use", "user:self:read",
	)

	store.tenantRoles[userDave+":"+tenantFinance] = &TenantRole{ID: "tr-a-editor", TenantID: tenantFinance, Code: roleEditor}
	addRolePermissionCodes(store, "tr-a-editor",
		"agent:read",
		"descriptor:read", "descriptor:create", "descriptor:update", "descriptor:delete",
		"llmconfig:read", "llmconfig:create", "llmconfig:update", "llmconfig:delete",
		"promptconfig:read", "promptconfig:create", "promptconfig:update", "promptconfig:delete",
		"semantic-group:read",
		"skill:manage", "skill:namespace:manage", "chat:use", "datasource:probe", "datasource:probe-types",
		"system:config:read", "user:self:read",
	)

	store.tenantRoles[userErin+":"+tenantFinance] = &TenantRole{ID: "tr-a-viewer", TenantID: tenantFinance, Code: roleViewer}
	addRolePermissionCodes(store, "tr-a-viewer",
		"descriptor:read", "descriptor:graph:read", "llmconfig:read", "promptconfig:read", "semantic-group:read",
		"skill:read", "skill:namespace:read", "discovery:read", "datasource:probe-types",
		"chat:history:read", "user:self:read", "namespace:read",
		"observability:read", "system:config:read", "environment:read",
	)

	// grace is a tenant-level role manager inside finance — but NOT the owner
	// of semantic groups, agent/configmap resources, etc.
	store.tenantRoles[userGrace+":"+tenantFinance] = &TenantRole{ID: "tr-a-role-admin", TenantID: tenantFinance, Code: roleRoleAdmin}
	addRolePermissionCodes(store, "tr-a-role-admin",
		"tenant:role:manage", "tenant:member:manage",
		"llmconfig:read", "semantic-group:read", "chat:history:read", "user:self:read",
	)

	// -- tenant B (dataeng) --
	store.tenantRoles[userFiona+":"+tenantDataEng] = &TenantRole{ID: "tr-b-editor", TenantID: tenantDataEng, Code: roleEditor}
	addRolePermissionCodes(store, "tr-b-editor",
		"descriptor:read", "descriptor:create", "descriptor:update", "descriptor:delete",
		"llmconfig:read", "semantic-group:read", "skill:manage",
		"chat:use", "user:self:read",
	)

	// gina belongs to dataeng as a namespace/member but holds no grants:
	// a plain member used as the deny-side of read permissions.
	store.tenantRoles[userGina+":"+tenantDataEng] = &TenantRole{ID: "tr-b-readable", TenantID: tenantDataEng, Code: roleViewer}
	store.rolePerms["tr-b-readable"] = nil

	// hugo is a finance tenant member with no grants at all: the baseline
	// deny-side user for codes that every business role in finance holds.
	store.tenantRoles[userHugo+":"+tenantFinance] = &TenantRole{ID: "tr-a-nobody", TenantID: tenantFinance, Code: roleViewer}
	store.rolePerms["tr-a-nobody"] = nil

	return NewEngine(store, nil)
}

// want is a small assertion helper for an authorize result.
func want(t *testing.T, engine *Engine, user, tenant, method, path string, allowed bool) {
	t.Helper()
	res, err := engine.Subject(context.Background(), user, tenant, method, path)
	if err != nil {
		t.Fatalf("Subject(%s,%s,%s %s): unexpected error: %v", user, tenant, method, path, err)
	}
	if res.Allowed != allowed {
		t.Errorf("want %s to be %s for %s %s (tenant=%q), got allowed=%v",
			user, boolAllowed(allowed), method, path, tenant, res.Allowed)
	}
}

func boolAllowed(allowed bool) string {
	if allowed {
		return "ALLOWED"
	}
	return "DENIED"
}

// ---------------------------------------------------------------------------
// Scenarios (each test exercises one slice of the matrix above).
// ---------------------------------------------------------------------------

// TestScenarioPlatformSuperAdminBypassesEveryone verifies the platform super
// admin is not constrained by tenant membership nor by any permission code.
func TestScenarioPlatformSuperAdminBypassesEveryone(t *testing.T) {
	e := newBusinessFixture(t)

	want(t, e, userAlice, "", "POST", "/api/v1/rbac/tenants", true)
	want(t, e, userAlice, "", "DELETE", "/api/v1/rbac/tenants/finance", true)
	want(t, e, userAlice, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/agents/web", true)
	want(t, e, userAlice, tenantDataEng, "DELETE", "/api/v1/discovery/scans/scan-1", true)
	// Even a path that is not registered anywhere is allowed for the super admin.
	want(t, e, userAlice, "", "PATCH", "/api/v1/not-registered/whatever", true)
}

// TestScenarioPlatformOpsManagesTenantsAcrossTenants verifies a platform-level
// "ops" role can manage tenants globally, without needing a tenant membership,
// but cannot manage platform roles (no matching permission code).
func TestScenarioPlatformOpsManagesTenantsAcrossTenants(t *testing.T) {
	e := newBusinessFixture(t)

	// bob holds tenant:manage → reaches tenant CRUD across every tenant.
	want(t, e, userBob, "", "POST", "/api/v1/rbac/tenants", true)
	want(t, e, userBob, "", "PUT", "/api/v1/rbac/tenants/finance", true)
	want(t, e, userBob, "", "DELETE", "/api/v1/rbac/tenants/dataeng", true)
	want(t, e, userBob, "", "POST", "/api/v1/rbac/tenants/finance/disable", true)
	want(t, e, userBob, "", "PUT", "/api/v1/rbac/tenants/finance/namespaces/extra", true)
	// ... but bob is not a tenant member, so tenant-local permissions must NOT apply.
	want(t, e, userBob, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/agents/web", false)
	want(t, e, userBob, tenantFinance, "GET", "/api/v1/namespaces/finance-data/descriptors/orders", false)
	// platform:role:manage was never granted to ops → denied.
	want(t, e, userBob, "", "POST", "/api/v1/rbac/platform/roles", false)
	want(t, e, userBob, "", "PUT", "/api/v1/rbac/platform/roles/r1/permissions", false)
	// user:self:read is granted.
	want(t, e, userBob, "", "GET", "/api/v1/users/me", true)
}

// TestScenarioTenantAdminGovernsOwnTenant verifies the tenant-admin role can
// manage roles/members and delete agents in the finance tenant, and that the
// same privileges do NOT carry over to another tenant.
func TestScenarioTenantAdminGovernsOwnTenant(t *testing.T) {
	e := newBusinessFixture(t)

	// Manage tenant-local roles + members in finance.
	want(t, e, userCarol, tenantFinance, "POST", "/api/v1/rbac/tenants/finance/roles", true)
	want(t, e, userCarol, tenantFinance, "PUT", "/api/v1/rbac/tenants/finance/roles/r1/permissions", true)
	want(t, e, userCarol, tenantFinance, "POST", "/api/v1/rbac/tenants/finance/users", true)
	want(t, e, userCarol, tenantFinance, "PUT", "/api/v1/rbac/tenants/finance/users/u9/role", true)
	want(t, e, userCarol, tenantFinance, "DELETE", "/api/v1/rbac/tenants/finance/users/u9", true)

	// Business resource rights inside the tenant.
	want(t, e, userCarol, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/agents/pay-bot", true)
	want(t, e, userCarol, tenantFinance, "POST", "/api/v1/semantic-groups/g1/members", true) // carol holds semantic-group:manage
	want(t, e, userCarol, tenantFinance, "POST", "/api/v1/skills/namespaces/finance/skills", false)

	// Isolation: carol manages dataeng?? No — she is not even a member.
	want(t, e, userCarol, tenantDataEng, "POST", "/api/v1/rbac/tenants/dataeng/roles", false)
	want(t, e, userCarol, tenantDataEng, "DELETE", "/api/v1/namespaces/data-lake/agents/dumper", false)

	// Isolation: carol's tenant rights must not leak to platform-level paths.
	want(t, e, userCarol, "", "POST", "/api/v1/rbac/tenants", false)
}

// TestScenarioEditorCannotDeleteAgents verifies the fine-grained business
// permission split: dave (editor) can do everything about descriptors,
// configmaps and skills, but has no agent:delete → agent deletion denied.
func TestScenarioEditorCannotDeleteAgents(t *testing.T) {
	e := newBusinessFixture(t)

	// Descriptor full CRUD.
	want(t, e, userDave, tenantFinance, "GET", "/api/v1/namespaces/finance-data/descriptors/orders", true)
	want(t, e, userDave, tenantFinance, "POST", "/api/v1/namespaces/finance-data/descriptors", true)
	want(t, e, userDave, tenantFinance, "PUT", "/api/v1/namespaces/finance-data/descriptors/orders", true)
	want(t, e, userDave, tenantFinance, "POST", "/api/v1/namespaces/finance-data/descriptors/orders/resync", true)
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/descriptors/orders", true)

	// Skill management (create in namespace / delete skill pack).
	want(t, e, userDave, tenantFinance, "POST", "/api/v1/skills/namespaces/finance/skills/create", true)
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/skills/namespaces/finance/skills/s1", true)
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/skills/namespaces/finance", true)

	// Configmap full CRUD for the editor role (holds all llmconfig + promptconfig codes).
	want(t, e, userDave, tenantFinance, "GET", "/api/v1/namespaces/finance-data/llm-configmaps/llm-default", true)
	want(t, e, userDave, tenantFinance, "POST", "/api/v1/namespaces/finance-data/llm-configmaps", true)
	want(t, e, userDave, tenantFinance, "PUT", "/api/v1/namespaces/finance-data/llm-configmaps/llm-default", true)
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/llm-configmaps/llm-default", true)

	want(t, e, userDave, tenantFinance, "GET", "/api/v1/namespaces/finance-data/prompt-configmaps/prompt-default", true)
	want(t, e, userDave, tenantFinance, "POST", "/api/v1/namespaces/finance-data/prompt-configmaps", true)
	want(t, e, userDave, tenantFinance, "PUT", "/api/v1/namespaces/finance-data/prompt-configmaps/prompt-default", true)
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/prompt-configmaps/prompt-default", true)

	// Semantic group read only.
	want(t, e, userDave, tenantFinance, "GET", "/api/v1/semantic-groups/g1", true)
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/semantic-groups/g1", false)

	// Agent deletion is explicitly NOT granted to editor.
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/agents/pay-bot", false)
	want(t, e, userDave, tenantFinance, "DELETE", "/api/v1/namespaces/data-lake/agents/dumper", false)
}

// TestScenarioReadOnlyUserCannotMutateAnything verifies the viewer role in the
// finance tenant is read-only on every resource class, while reads succeed.
func TestScenarioReadOnlyUserCannotMutateAnything(t *testing.T) {
	e := newBusinessFixture(t)

	// Reads allowed.
	want(t, e, userErin, tenantFinance, "GET", "/api/v1/namespaces/finance-data/descriptors/orders", true)
	want(t, e, userErin, tenantFinance, "GET", "/api/v1/namespaces/finance-data/descriptors/orders/signature", true)
	want(t, e, userErin, tenantFinance, "GET", "/api/v1/namespaces/finance-data/descriptors/orders/knowledge", true)
	want(t, e, userErin, tenantFinance, "POST", "/api/v1/knowledge-graph/get-graph-by-source", true)
	want(t, e, userErin, tenantFinance, "GET", "/api/v1/namespaces/finance-data/llm-configmaps/llm-default", true)
	want(t, e, userErin, tenantFinance, "GET", "/api/v1/semantic-groups/g1/members", true)
	want(t, e, userErin, tenantFinance, "GET", "/api/v1/chat/conversations/42", true)
	want(t, e, userErin, tenantFinance, "GET", "/api/v1/observability/agent-registries", true)

	// Every mutation denied.
	want(t, e, userErin, tenantFinance, "POST", "/api/v1/namespaces/finance-data/descriptors", false)
	want(t, e, userErin, tenantFinance, "PUT", "/api/v1/namespaces/finance-data/descriptors/orders", false)
	want(t, e, userErin, tenantFinance, "POST", "/api/v1/namespaces/finance-data/descriptors/orders/resync", false)
	want(t, e, userErin, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/descriptors/orders", false)
	want(t, e, userErin, tenantFinance, "POST", "/api/v1/namespaces/finance-data/llm-configmaps", false)
	want(t, e, userErin, tenantFinance, "DELETE", "/api/v1/semantic-groups/g1", false)
	want(t, e, userErin, tenantFinance, "POST", "/v1/chat/completions", false) // chat:use not in viewer
	want(t, e, userErin, tenantFinance, "DELETE", "/api/v1/dd-group-relations/42", false)
	want(t, e, userErin, tenantFinance, "POST", "/api/v1/discovery/scans", false)
}

// TestScenarioTenantIsolationAcrossTenants verifies that members of different
// tenants cannot use each other's permissions, even when they hold identical
// role codes (editor) — the engine must scope everything by tenant.
func TestScenarioTenantIsolationAcrossTenants(t *testing.T) {
	e := newBusinessFixture(t)

	// fiona (dataeng) can manage skills in HER tenant's namespace.
	want(t, e, userFiona, tenantDataEng, "POST", "/api/v1/skills/namespaces/dataeng/skills/create", true)
	want(t, e, userFiona, tenantDataEng, "DELETE", "/api/v1/namespaces/data-lake/descriptors/sink", true)

	// dave (finance) cannot touch dataeng resources, even with skill:manage.
	want(t, e, userDave, tenantDataEng, "POST", "/api/v1/skills/namespaces/dataeng/skills/create", false)
	want(t, e, userDave, tenantDataEng, "GET", "/api/v1/namespaces/data-lake/descriptors/sink", false)

	// fiona cannot read finance resources.
	want(t, e, userFiona, tenantFinance, "GET", "/api/v1/namespaces/finance-data/descriptors/orders", false)
	want(t, e, userFiona, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/agents/pay-bot", false)
}

// TestScenarioManagementPermissionSubResources verifies the trailing "/**" of
// the tenant role/member manage grants reaches sub-resource endpoints that the
// business editor role does not have.
func TestScenarioManagementPermissionSubResources(t *testing.T) {
	e := newBusinessFixture(t)

	// Role permission assignment and member role-change are covered by the
	// parent tenant:role:manage / tenant:member:manage codes.
	want(t, e, userCarol, tenantFinance, "PUT", "/api/v1/rbac/tenants/finance/roles/r1/permissions", true)
	want(t, e, userCarol, tenantFinance, "PUT", "/api/v1/rbac/tenants/finance/users/u9/role", true)

	// dave (editor) holds neither management code → denied.
	want(t, e, userDave, tenantFinance, "PUT", "/api/v1/rbac/tenants/finance/roles/r1/permissions", false)
	want(t, e, userDave, tenantFinance, "PUT", "/api/v1/rbac/tenants/finance/users/u9/role", false)
	want(t, e, userDave, tenantFinance, "PUT", "/api/v1/rbac/tenants/finance/roles/r1", false)
}

// TestScenarioGrantTakesEffectImmediatelyAfterInvalidate verifies that a
// permission change made through the management plane (write to storage +
// Invalidate) is honored by the very next authorization call, i.e. the engine
// never serves stale role data from its cache.
func TestScenarioGrantTakesEffectImmediatelyAfterInvalidate(t *testing.T) {
	e := newBusinessFixture(t)

	// erin (viewer, read-only) tries to delete an agent → denied.
	want(t, e, userErin, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/agents/pay-bot", false)

	// Admin grants a brand-new permission code (agent:delete) to the viewer
	// role, then invalidates — simulating the page binding a new permission
	// code followed by the management API invalidating the role cache.
	store := e.store.(*fakeStorage)
	store.mu.Lock()
	viewerRole := store.tenantRoles[userErin+":"+tenantFinance]
	store.mu.Unlock()
	addRolePermissionCodes(store, viewerRole.ID, "agent:delete")

	e.Invalidate([]string{viewerRole.ID}, nil, nil)

	want(t, e, userErin, tenantFinance, "DELETE", "/api/v1/namespaces/finance-data/agents/pay-bot", true)
	// The upgrade is additive: it does not unlock descriptor writes.
	want(t, e, userErin, tenantFinance, "POST", "/api/v1/namespaces/finance-data/descriptors", false)
}

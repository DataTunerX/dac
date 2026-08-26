package rbac

import (
	"testing"
)

// matrixRow is one row of RBAC-TESTDATA.md §2: a permission code, the exact
// request a user sends, and a pair of users — the positive holder (ALLOW) and
// a user that does NOT hold the code (DENY).
type matrixRow struct {
	code      string
	method    string
	path      string
	posUser   string
	posTenant string
	negUser   string
	negTenant string
}

// permissionMatrix is the complete, reviewable dataset from RBAC-TESTDATA.md.
// Every one of the 36 permission codes appears exactly once. The engine
// authorization result for each row is asserted in
// TestPermissionMatrixFullCoverage; additionally every positive (method,path)
// is checked against the seed catalog so the matrix can never drift from the
// real permission surface.
var permissionMatrix = []matrixRow{
	// —— platform (management API, tenant="") ——
	{code: "tenant:read", method: "GET", path: "/api/v1/rbac/tenants", posUser: userBob, posTenant: "", negUser: userGrace, negTenant: ""},
	{code: "tenant:manage", method: "POST", path: "/api/v1/rbac/tenants", posUser: userBob, posTenant: "", negUser: userDave, negTenant: ""},
	{code: "platform:role:read", method: "GET", path: "/api/v1/rbac/platform/roles", posUser: userGrace, posTenant: "", negUser: userBob, negTenant: ""},
	{code: "platform:role:manage", method: "POST", path: "/api/v1/rbac/platform/roles", posUser: userGrace, posTenant: "", negUser: userBob, negTenant: ""},
	{code: "permission:read", method: "GET", path: "/api/v1/rbac/permissions", posUser: userBob, posTenant: "", negUser: userGrace, negTenant: ""},
	{code: "rbac:me:read", method: "GET", path: "/api/v1/rbac/me/tenants", posUser: userBob, posTenant: "", negUser: userDave, negTenant: ""},

	// —— tenant layer (scoped to finance) ——
	{code: "tenant:role:read", method: "GET", path: "/api/v1/rbac/tenants/finance/roles", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},
	{code: "tenant:role:manage", method: "POST", path: "/api/v1/rbac/tenants/finance/roles", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},
	{code: "tenant:member:read", method: "GET", path: "/api/v1/rbac/tenants/finance/users", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},
	{code: "tenant:member:manage", method: "POST", path: "/api/v1/rbac/tenants/finance/users", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},

	// —— agents ——
	{code: "agent:read", method: "GET", path: "/api/v1/namespaces/finance-data/agents", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "agent:create", method: "POST", path: "/api/v1/namespaces/finance-data/agents", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},
	{code: "agent:update", method: "PUT", path: "/api/v1/namespaces/finance-data/agents/web", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},
	{code: "agent:delete", method: "DELETE", path: "/api/v1/namespaces/finance-data/agents/web", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},

	// —— descriptors / knowledge graph ——
	{code: "descriptor:read", method: "GET", path: "/api/v1/namespaces/finance-data/descriptors/orders", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "descriptor:graph:read", method: "POST", path: "/api/v1/knowledge-graph/get-graph-by-source", posUser: userErin, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},
	{code: "descriptor:create", method: "POST", path: "/api/v1/namespaces/finance-data/descriptors", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "descriptor:update", method: "PUT", path: "/api/v1/namespaces/finance-data/descriptors/orders", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "descriptor:delete", method: "DELETE", path: "/api/v1/namespaces/finance-data/descriptors/orders", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},

	// —— llm configmaps ——
	{code: "llmconfig:read", method: "GET", path: "/api/v1/namespaces/finance-data/llm-configmaps/llm", posUser: userErin, posTenant: tenantFinance, negUser: userHugo, negTenant: tenantFinance},
	{code: "llmconfig:create", method: "POST", path: "/api/v1/namespaces/finance-data/llm-configmaps", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "llmconfig:update", method: "PUT", path: "/api/v1/namespaces/finance-data/llm-configmaps/llm", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "llmconfig:delete", method: "DELETE", path: "/api/v1/namespaces/finance-data/llm-configmaps/llm", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},

	// —— prompt configmaps ——
	{code: "promptconfig:read", method: "GET", path: "/api/v1/namespaces/finance-data/prompt-configmaps/prompt", posUser: userErin, posTenant: tenantFinance, negUser: userHugo, negTenant: tenantFinance},
	{code: "promptconfig:create", method: "POST", path: "/api/v1/namespaces/finance-data/prompt-configmaps", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "promptconfig:update", method: "PUT", path: "/api/v1/namespaces/finance-data/prompt-configmaps/prompt", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "promptconfig:delete", method: "DELETE", path: "/api/v1/namespaces/finance-data/prompt-configmaps/prompt", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},

	// —— datasources ——
	{code: "datasource:probe", method: "POST", path: "/api/v1/datasources/probe", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "datasource:probe-types", method: "GET", path: "/api/v1/datasources/probe/types", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},

	// —— semantic groups ——
	{code: "semantic-group:read", method: "GET", path: "/api/v1/semantic-groups/g1", posUser: userErin, posTenant: tenantFinance, negUser: userHugo, negTenant: tenantFinance},
	{code: "semantic-group:manage", method: "DELETE", path: "/api/v1/semantic-groups/g1", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},

	// —— discovery ——
	{code: "discovery:read", method: "GET", path: "/api/v1/discovery/scans/scan-1", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "discovery:manage", method: "POST", path: "/api/v1/discovery/scans", posUser: userCarol, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},

	// —— skills ——
	{code: "skill:read", method: "GET", path: "/api/v1/skills/namespaces/finance/skills", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "skill:manage", method: "POST", path: "/api/v1/skills/namespaces/finance/skills/s1", posUser: userDave, posTenant: tenantFinance, negUser: userCarol, negTenant: tenantFinance},
	{code: "skill:namespace:read", method: "GET", path: "/api/v1/skills/namespaces", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "skill:namespace:manage", method: "DELETE", path: "/api/v1/skills/namespaces/finance", posUser: userDave, posTenant: tenantFinance, negUser: userCarol, negTenant: tenantFinance},

	// —— chat ——
	{code: "chat:use", method: "POST", path: "/v1/chat/completions", posUser: userDave, posTenant: tenantFinance, negUser: userErin, negTenant: tenantFinance},
	{code: "chat:history:read", method: "GET", path: "/api/v1/chat/conversations/c1", posUser: userErin, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},

	// —— system config / environment / namespace / observability ——
	{code: "system:config:read", method: "GET", path: "/api/v1/system/configurations/dac", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "system:config:manage", method: "POST", path: "/api/v1/system/configurations", posUser: userCarol, posTenant: tenantFinance, negUser: userDave, negTenant: tenantFinance},
	{code: "environment:read", method: "GET", path: "/api/v1/environment/gpu", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "namespace:read", method: "GET", path: "/api/v1/namespaces", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "observability:read", method: "GET", path: "/api/v1/observability/agent-registries", posUser: userErin, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},

	// —— user ——
	{code: "user:self:read", method: "GET", path: "/api/v1/users/me", posUser: userErin, posTenant: tenantFinance, negUser: userHugo, negTenant: tenantFinance},
	{code: "user:read", method: "GET", path: "/api/v1/users", posUser: userCarol, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
	{code: "user:manage", method: "DELETE", path: "/api/v1/users/u123", posUser: userCarol, posTenant: tenantFinance, negUser: userGrace, negTenant: tenantFinance},
}

// TestPermissionMatrixFullCoverage runs the full matrix from RBAC-TESTDATA.md:
// for every permission code the positive holder is ALLOWED and a user that
// lacks the code is DENIED, on the exact request the management UI would emit.
func TestPermissionMatrixFullCoverage(t *testing.T) {
	e := newBusinessFixture(t)

	// Unique codes in the live catalog — the matrix must cover all of them.
	catalog := make(map[string]Permission, len(SeedPermissions))
	for _, sp := range SeedPermissions {
		if _, ok := catalog[sp.Code]; !ok {
			catalog[sp.Code] = Permission{Code: sp.Code, HTTPMethod: sp.HTTPMethod, HTTPPath: sp.HTTPPath}
		}
	}
	if len(permissionMatrix) != len(catalog) {
		t.Fatalf("matrix covers %d rows, seed catalog has %d unique codes", len(permissionMatrix), len(catalog))
	}

	seen := make(map[string]bool, len(permissionMatrix))
	for _, row := range permissionMatrix {
		p, ok := catalog[row.code]
		if !ok {
			t.Fatalf("matrix references unknown permission code %q", row.code)
		}
		seen[row.code] = true

		// Drift guard: the positive (method,path) must be covered by the real
		// seed rules of this code, otherwise the matrix is not testing the
		// permission surface at all.
		if !p.Allows(row.method, row.path) {
			t.Errorf("positive probe %s %s is NOT covered by catalog code %s (rules %v)", row.method, row.path, row.code, p.Rules())
			continue
		}

		t.Run(row.code, func(t *testing.T) {
			want(t, e, row.posUser, row.posTenant, row.method, row.path, true)
			want(t, e, row.negUser, row.negTenant, row.method, row.path, false)
		})
	}
	if len(seen) != len(catalog) {
		for code := range catalog {
			if !seen[code] {
				t.Errorf("matrix does not cover catalog code %q", code)
			}
		}
	}
}

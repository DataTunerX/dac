package rbac

import (
	"context"
	"testing"
)

// TestEnginePlatformNonSuperContributesPermissions verifies a non-super
// platform role can authorize an otherwise denied tenant-scoped request, which
// is how cross-tenant read-only "ops" style roles are expected to work.
func TestEnginePlatformNonSuperContributesPermissions(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "observability:read", "GET", "/api/v1/observability/**")
	store.platformRoles["u-ops"] = []PlatformRole{{ID: "r-ops", Code: "ops"}}
	store.rolePerms["r-ops"] = []string{"p1"}
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u-ops", "t1", "GET", "/api/v1/observability/agent-registries")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !res.Allowed {
		t.Fatal("platform non-super role must contribute its permission codes")
	}
	if len(res.Codes) != 1 || res.Codes[0] != "observability:read" {
		t.Fatalf("codes=%v, want [observability:read]", res.Codes)
	}
}

// TestEngineEmptyTenantAppliesOnlyPlatformRoles verifies that platform-level
// operations (empty tenant) use only platform role permissions; a tenant-only
// code must not authorize them.
func TestEngineEmptyTenantAppliesOnlyPlatformRoles(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/namespaces/*/agents")
	store.rolePerms["r-viewer"] = []string{"p1"}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-viewer", TenantID: "t1", Code: "viewer"}
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u1", "", "GET", "/api/v1/namespaces/dev/agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Allowed {
		t.Fatal("tenant-role permissions must not authorize an empty-tenant request")
	}
}

// TestEngineTenantNamespacesCachedAndInvalidated checks the namespace cache is
// served after the first lookup and refreshed by Invalidate.
func TestEngineTenantNamespacesCachedAndInvalidated(t *testing.T) {
	store := newFakeStorage()
	store.tenantNamespaces["t1"] = []string{"dev"}
	e := NewEngine(store, nil)

	first, err := e.TenantNamespaces(context.Background(), "t1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(first) != 1 || first[0] != "dev" {
		t.Fatalf("first=%v, want [dev]", first)
	}

	// Change the backing data and confirm the cache still serves the old value...
	store.mu.Lock()
	store.tenantNamespaces["t1"] = []string{"prod"}
	store.mu.Unlock()

	stale, err := e.TenantNamespaces(context.Background(), "t1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(stale) != 1 || stale[0] != "dev" {
		t.Fatalf("cache should serve stale value, got %v", stale)
	}

	// ...until the cache row is invalidated.
	e.Invalidate(nil, nil, []string{"t1"})
	fresh, err := e.TenantNamespaces(context.Background(), "t1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(fresh) != 1 || fresh[0] != "prod" {
		t.Fatalf("after invalidation got %v, want [prod]", fresh)
	}
}

// TestEngineSuperCacheInvalidatedOnRevokeCheck verifies that revoking a super
// admin grant (via Invalidate with the user) stops the former admin from being
// treated as super on the very next request.
func TestEngineSuperCacheInvalidatedOnRevokeCheck(t *testing.T) {
	store := newFakeStorage()
	store.platformRoles["u1"] = []PlatformRole{{ID: "r-super", Code: "super_admin", IsSuper: true}}
	e := NewEngine(store, nil)

	if res, _ := e.Subject(context.Background(), "u1", "t9", "DELETE", "/anything"); !res.Allowed {
		t.Fatal("u1 should be treated as super initially")
	}

	store.mu.Lock()
	store.platformRoles["u1"] = []PlatformRole{{ID: "r-ops", Code: "ops", IsSuper: false}}
	store.mu.Unlock()
	e.Invalidate(nil, []string{"u1"}, nil)

	res, err := e.Subject(context.Background(), "u1", "t9", "DELETE", "/anything")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Allowed {
		t.Fatal("after revoking the super grant and invalidating, u1 must be denied")
	}
}

// TestRoleCodesMissingPermissionsYieldsNoGrant verifies that a role whose
// permission IDs resolve to zero codes grants nothing instead of failing.
func TestRoleCodesMissingPermissionsYieldsNoGrant(t *testing.T) {
	store := newFakeStorage()
	store.rolePerms["r-empty"] = []string{}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-empty", TenantID: "t1", Code: "empty"}
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u1", "t1", "GET", "/api/v1/agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Allowed {
		t.Fatal("role with no permission bindings must deny")
	}
}

// TestModelRulesAllowsPipeSeparatedPaths verifies a single permission code with
// several '|'-joined path templates covers each template when expanded.
func TestModelRulesAllowsPipeSeparatedPaths(t *testing.T) {
	p := Permission{
		Code:       "agent:read",
		HTTPMethod: "GET",
		HTTPPath:   "/api/v1/agents|/api/v1/namespaces/*/agents/*",
	}
	rules := p.Rules()
	if len(rules) != 2 {
		t.Fatalf("Rules() len=%d, want 2", len(rules))
	}
	if !RuleMatch(rules[0], "GET", "/api/v1/agents") {
		t.Error("first rule should match the list endpoint")
	}
	if !RuleMatch(rules[1], "GET", "/api/v1/namespaces/prod/agents/web") {
		t.Error("second rule should match the detail endpoint")
	}
}

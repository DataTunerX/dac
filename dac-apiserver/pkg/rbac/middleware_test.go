package rbac

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"

	"github.com/cloudwego/hertz/pkg/app"
)

// runMiddleware executes a single request through the engine middleware with
// the prepared request context and returns it so tests can inspect the response.
func runMiddleware(e *Engine, method, path, tenantID string) *app.RequestContext {
	c := app.NewContext(0)
	c.Request.Header.SetMethod(method)
	c.Request.SetRequestURI(path)
	if tenantID != "" {
		c.Request.Header.Set(TenantHeaderName, tenantID)
	}
	e.Middleware()(context.Background(), c)
	return c
}

func TestMiddlewareMissingUserDeniesWith403(t *testing.T) {
	e := NewEngine(newFakeStorage(), nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("GET")
	c.Request.SetRequestURI("/api/v1/agents")
	e.Middleware()(context.Background(), c) // no user_id in context

	if c.Response.StatusCode() != http.StatusForbidden {
		t.Fatalf("status=%d, want 403", c.Response.StatusCode())
	}
	var body map[string]interface{}
	if err := json.Unmarshal(c.Response.Body(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["code"] != "FORBIDDEN" {
		t.Fatalf("code=%v, want FORBIDDEN", body["code"])
	}
}

func TestMiddlewareInvalidUserIDDeniesWith403(t *testing.T) {
	e := NewEngine(newFakeStorage(), nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("GET")
	c.Request.SetRequestURI("/api/v1/agents")
	c.Set(ContextUserIDKey, 42) // not a string
	e.Middleware()(context.Background(), c)

	if c.Response.StatusCode() != http.StatusForbidden {
		t.Fatalf("status=%d, want 403", c.Response.StatusCode())
	}
}

func TestMiddlewareSuperAdminAllowed(t *testing.T) {
	store := newFakeStorage()
	store.platformRoles["u-admin"] = []PlatformRole{{ID: "r-super", Code: "super_admin", IsSuper: true}}
	e := NewEngine(store, nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("DELETE")
	c.Request.SetRequestURI("/api/v1/namespaces/prod/agents/web")
	c.Set(ContextUserIDKey, "u-admin")
	e.Middleware()(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s, want 200", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestMiddlewareTenantMemberAllowedSetsContext(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/namespaces/*/agents")
	store.rolePerms["r-viewer"] = []string{"p1"}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-viewer", TenantID: "t1", Code: "viewer"}
	store.tenantNamespaces["t1"] = []string{"dev", "prod"}
	e := NewEngine(store, nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("GET")
	c.Request.SetRequestURI("/api/v1/namespaces/dev/agents")
	c.Request.Header.Set(TenantHeaderName, "t1")
	c.Set(ContextUserIDKey, "u1")

	e.Middleware()(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s, want 200", c.Response.StatusCode(), c.Response.Body())
	}
	if got := c.GetString(ContextTenantIDKey); got != "t1" {
		t.Fatalf("tenant_id=%q, want t1", got)
	}
	if got := c.GetString(ContextUserIDKey); got != "u1" {
		t.Fatalf("user_id=%q, want u1", got)
	}
	codes, ok := c.Get(ContextPermCodesKey)
	if !ok {
		t.Fatal("perm_codes must be set on allowed tenant request")
	}
	if got := codes.([]string); len(got) != 1 || got[0] != "agent:read" {
		t.Fatalf("perm_codes=%v, want [agent:read]", got)
	}
	nssVal, ok := c.Get(ContextTenantNamesKey)
	if !ok {
		t.Fatal("tenant_names must be set for a tenant-scoped request")
	}
	if nss := nssVal.([]string); len(nss) != 2 {
		t.Fatalf("tenant_names=%v, want 2 namespaces", nss)
	}
}

func TestMiddlewareDeniedWithoutLeakedReason(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/agents")
	store.rolePerms["r-viewer"] = []string{"p1"}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-viewer", TenantID: "t1", Code: "viewer"}
	e := NewEngine(store, nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("POST") // viewer only holds a GET rule
	c.Request.SetRequestURI("/api/v1/agents")
	c.Set(ContextUserIDKey, "u1")

	e.Middleware()(context.Background(), c)

	if c.Response.StatusCode() != http.StatusForbidden {
		t.Fatalf("status=%d, want 403", c.Response.StatusCode())
	}
	var body map[string]interface{}
	if err := json.Unmarshal(c.Response.Body(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["message"] != "forbidden" || body["code"] != "FORBIDDEN" {
		t.Fatalf("body must not leak the missing permission, got %v", body)
	}
}

func TestMiddlewareStorageFailureReturns500(t *testing.T) {
	store := newFakeStorage()
	// A platform role whose permission code has no definition in the catalog.
	// The engine resolves the code during step 4 and treats the missing
	// definition as a data integrity failure: it must fail closed with 500.
	store.platformRoles["u2"] = []PlatformRole{{ID: "r-ops", Code: "ops"}}
	store.rolePerms["r-ops"] = []string{"ghost-perm"}
	store.permCodes["ghost-perm"] = "ghost-code" // resolves to a code...
	// ...but no perms entry exists for "ghost-code".
	e := NewEngine(store, nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("GET")
	c.Request.SetRequestURI("/api/v1/unknown")
	c.Set(ContextUserIDKey, "u2")
	e.Middleware()(context.Background(), c)

	if c.Response.StatusCode() != http.StatusInternalServerError {
		t.Fatalf("status=%d body=%s, want 500 for unresolved permission code", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestMiddlewarePlatformOnlyOperationWithoutTenant(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "tenant:manage", "*", "/api/v1/rbac/tenants/**")
	store.platformRoles["u-ops"] = []PlatformRole{{ID: "r-ops", Code: "ops"}}
	store.rolePerms["r-ops"] = []string{"p1"}
	e := NewEngine(store, nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("POST")
	c.Request.SetRequestURI("/api/v1/rbac/tenants")
	c.Set(ContextUserIDKey, "u-ops") // no X-Tenant-Id header

	e.Middleware()(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s, want 200 for platform-level op", c.Response.StatusCode(), c.Response.Body())
	}
	_, hasTenant := c.Get(ContextTenantIDKey)
	if hasTenant {
		t.Fatal("tenant_id must not be set when no X-Tenant-Id header is present")
	}
}

func TestMiddlewareDisabledTenantDeniesMember(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/namespaces/*/agents")
	store.rolePerms["r-viewer"] = []string{"p1"}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-viewer", TenantID: "t1", Code: "viewer"}
	store.disabledTenant["t1"] = true
	e := NewEngine(store, nil)

	c := app.NewContext(0)
	c.Request.Header.SetMethod("GET")
	c.Request.SetRequestURI("/api/v1/namespaces/dev/agents")
	c.Set(ContextUserIDKey, "u1")
	c.Request.Header.Set(TenantHeaderName, "t1")

	e.Middleware()(context.Background(), c)

	if c.Response.StatusCode() != http.StatusForbidden {
		t.Fatalf("status=%d, want 403 for disabled tenant member", c.Response.StatusCode())
	}
}

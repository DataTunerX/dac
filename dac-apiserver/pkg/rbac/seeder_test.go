package rbac

import (
	"strings"
	"testing"
)

// known HTTP methods is the closed set the catalog may use. Anything else is a
// typo that would silently never match a real request method.
var knownHTTPMethods = map[string]bool{
	"*": true, "GET": true, "POST": true, "PUT": true, "PATCH": true, "DELETE": true,
}

// validMethodsSet returns the set of methods the catalog actually uses, which
// tests then compare against the closed set above.
func validMethodsSet() map[string]bool {
	out := make(map[string]bool)
	for _, sp := range SeedPermissions {
		for _, m := range splitMethods(sp.HTTPMethod) {
			out[m] = true
		}
	}
	return out
}

func TestSeedCatalogMethodsAreClosedSet(t *testing.T) {
	for m := range validMethodsSet() {
		if !knownHTTPMethods[m] {
			t.Errorf("catalog uses unknown HTTP method %q", m)
		}
	}
}

func TestSeedCatalogPathsWellFormed(t *testing.T) {
	for _, sp := range SeedPermissions {
		for _, raw := range splitPaths(sp.HTTPPath) {
			if !strings.HasPrefix(raw, "/") {
				t.Errorf("permission %s path %q must start with a slash", sp.Code, raw)
			}
			if strings.ContainsAny(raw, "?#") {
				t.Errorf("permission %s path %q must not contain query/fragment", sp.Code, raw)
			}
		}
	}
}

func TestSeedCatalogEveryPathExpandsToRule(t *testing.T) {
	for _, sp := range SeedPermissions {
		p := Permission{
			Code:       sp.Code,
			HTTPMethod: sp.HTTPMethod,
			HTTPPath:   sp.HTTPPath,
		}
		if rules := p.Rules(); len(rules) == 0 {
			t.Errorf("permission %s expands to zero rules", sp.Code)
		}
	}
}

// TestDefaultCodesPresentInCatalog guarantees every code the migrated default
// viewer role receives has a matching catalog entry; otherwise seeding would
// fail with an unknown-permission-code error and block service startup.
func TestDefaultCodesPresentInCatalog(t *testing.T) {
	catalog := make(map[string]bool, len(SeedPermissions))
	for _, sp := range SeedPermissions {
		catalog[sp.Code] = true
	}
	for _, code := range DefaultCodes {
		if !catalog[code] {
			t.Errorf("DefaultCodes contains %q which has no catalog entry", code)
		}
	}
}

// TestDefaultCodesCoverReadOnlySurface verifies that the legacy "viewer" role
// (DefaultCodes) can still reach every endpoint the old p,user whitelist
// covered: reading users, agents, descriptors, configmaps, system config,
// environment checks, namespaces, observability, semantics, discovery scans,
// datasource probes, skills and chat — all with GET/POST as appropriate.
func TestDefaultCodesCoverReadOnlySurface(t *testing.T) {
	// Aggregate the catalog the same way the seeder persists it (one row per
	// code, paths joined), then verify the legacy viewer whitelist can reach
	// every endpoint of the old p,user read-only surface.
	type seedRule struct {
		methods string
		paths   []string
	}
	byCode := make(map[string]seedRule)
	for _, sp := range SeedPermissions {
		acc, ok := byCode[sp.Code]
		if !ok {
			acc = seedRule{methods: sp.HTTPMethod}
		}
		if sp.HTTPMethod == "*" {
			acc.methods = "*"
		}
		acc.paths = append(acc.paths, splitPaths(sp.HTTPPath)...)
		byCode[sp.Code] = acc
	}

	type endpoint struct {
		code   string
		method string
		path   string
	}
	cases := []endpoint{
		{"user:self:read", "GET", "/api/v1/users/me"},
		{"rbac:me:read", "GET", "/api/v1/rbac/me/tenants"},
		{"chat:history:read", "GET", "/api/v1/chat/conversations/42"},
		{"chat:use", "POST", "/v1/chat/completions"},
		{"agent:read", "GET", "/api/v1/agents"},
		{"agent:read", "GET", "/api/v1/namespaces/dev/agents/web"},
		{"descriptor:read", "GET", "/api/v1/descriptors"},
		{"environment:read", "GET", "/api/v1/environment/gpu"},
		{"namespace:read", "GET", "/api/v1/namespaces"},
		{"llmconfig:read", "GET", "/api/v1/namespaces/dev/llm-configmaps"},
		{"promptconfig:read", "GET", "/api/v1/namespaces/dev/prompt-configmaps"},
		{"system:config:read", "GET", "/api/v1/system/configurations"},
		{"system:config:read", "GET", "/api/v1/system/configurations/dac/versions"},
		{"observability:read", "GET", "/api/v1/observability/agent-registries"},
		{"semantic-group:read", "GET", "/api/v1/semantic-groups/1/members"},
		{"discovery:read", "GET", "/api/v1/discovery/scans"},
		{"discovery:read", "GET", "/api/v1/discovery/scans/scan-1"},
		{"datasource:probe", "POST", "/api/v1/datasources/probe"},
		{"datasource:probe-types", "GET", "/api/v1/datasources/probe/types"},
		{"skill:read", "GET", "/api/v1/skills/namespaces/default/skills"},
		{"skill:namespace:read", "GET", "/api/v1/skills/namespaces"},
		{"tenant:read", "GET", "/api/v1/rbac/tenants"},
		{"tenant:role:read", "GET", "/api/v1/rbac/tenants/t1/roles"},
		{"tenant:member:read", "GET", "/api/v1/rbac/tenants/t1/users"},
		{"user:read", "GET", "/api/v1/users"},
	}
	for _, tc := range cases {
		acc, ok := byCode[tc.code]
		if !ok {
			t.Errorf("%s: code not in catalog", tc.code)
			continue
		}
		// Expand comma-separated methods the same way Permission.Rules() does,
		// so a "GET,POST" entry matches both a GET and a POST request.
		methods := strings.Split(acc.methods, ",")
		match := false
		for _, tmpl := range acc.paths {
			for _, m := range methods {
				if RuleMatch(Rule{Method: strings.TrimSpace(m), Path: tmpl}, tc.method, tc.path) {
					match = true
					break
				}
			}
			if match {
				break
			}
		}
		if !match {
			t.Errorf("%s: rule (%s %v) does not match %s %s",
				tc.code, acc.methods, acc.paths, tc.method, tc.path)
		}
	}
}

// TestSeedTenantRoleManageCoversPermissionSubresource guards the fix that lets
// the tenant role manage grant reach the permission-assignment endpoint
// (.../roles/:rid/permissions), not only the roles collection.
func TestSeedTenantRoleManageCoversPermissionSubresource(t *testing.T) {
	code := "tenant:role:manage"
	var sp SeedPermission
	for _, s := range SeedPermissions {
		if s.Code == code {
			sp = s
			break
		}
	}
	if sp.Code == "" {
		t.Fatalf("%s not found in catalog", code)
	}
	p := Permission{Code: sp.Code, HTTPMethod: sp.HTTPMethod, HTTPPath: sp.HTTPPath}
	var matched bool
	for _, r := range p.Rules() {
		if RuleMatch(r, "PUT", "/api/v1/rbac/tenants/t1/roles/r1/permissions") {
			matched = true
		}
	}
	if !matched {
		t.Fatalf("%s must cover the role permission assignment endpoint, rules=%+v", code, p.Rules())
	}
}

// TestSeedTenantMemberManageCoversRoleChangeSubresource guards the analogous
// fix for the member role-change endpoint (.../users/:uid/role).
func TestSeedTenantMemberManageCoversRoleChangeSubresource(t *testing.T) {
	code := "tenant:member:manage"
	var sp SeedPermission
	for _, s := range SeedPermissions {
		if s.Code == code {
			sp = s
			break
		}
	}
	if sp.Code == "" {
		t.Fatalf("%s not found in catalog", code)
	}
	p := Permission{Code: sp.Code, HTTPMethod: sp.HTTPMethod, HTTPPath: sp.HTTPPath}
	var matched bool
	for _, r := range p.Rules() {
		if RuleMatch(r, "PUT", "/api/v1/rbac/tenants/t1/users/u1/role") {
			matched = true
		}
	}
	if !matched {
		t.Fatalf("%s must cover the member role-change endpoint, rules=%+v", code, p.Rules())
	}
}

// TestSeedTenantManageCoversTenantSubtree guards that a single tenant:manage
// grant reaches every tenant endpoint (status change, namespace binding...).
func TestSeedTenantManageCoversTenantSubtree(t *testing.T) {
	code := "tenant:manage"
	var sp SeedPermission
	for _, s := range SeedPermissions {
		if s.Code == code {
			sp = s
			break
		}
	}
	if sp.Code == "" {
		t.Fatalf("%s not found in catalog", code)
	}
	p := Permission{Code: sp.Code, HTTPMethod: sp.HTTPMethod, HTTPPath: sp.HTTPPath}
	for _, tc := range []struct {
		method, path string
	}{
		{"POST", "/api/v1/rbac/tenants"},
		{"GET", "/api/v1/rbac/tenants/t1"},
		{"DELETE", "/api/v1/rbac/tenants/t1"},
		{"POST", "/api/v1/rbac/tenants/t1/disable"},
		{"GET", "/api/v1/rbac/tenants/t1/namespaces"},
	} {
		if !p.Allows(tc.method, tc.path) {
			t.Errorf("tenant:manage must allow %s %s", tc.method, tc.path)
		}
	}
}

// Allows is a small convenience wrapper used by catalog tests: it reports
// whether any expanded rule of the permission matches the request.
func (p Permission) Allows(method, path string) bool {
	for _, r := range p.Rules() {
		if RuleMatch(r, method, path) {
			return true
		}
	}
	return false
}

func TestSeedSuperAdminCodeStable(t *testing.T) {
	found := false
	for _, sp := range SeedPermissions {
		if sp.Code == "super_admin" {
			found = true
		}
	}
	if found {
		t.Fatal("super_admin is a role code, not a permission code; it must not appear in SeedPermissions")
	}
}

// TestSeedCoversFrontendGapSurface guards the fixes that closed the gaps found
// during the frontend audit: descriptor details/signature/semantic-domain/
// knowledge reads, descriptor resync, configmap get-by-name, agent namespaced
// list/detail, dd-group-relations read + delete, and the semantic-domain
// search step used by the "remove from semantic group" flow.
func TestSeedCoversFrontendGapSurface(t *testing.T) {
	type endpoint struct {
		code   string
		method string
		path   string
	}
	cases := []endpoint{
		// descriptor read sub-resources (delete/signature/semantic-domain/knowledge)
		{"descriptor:read", "GET", "/api/v1/namespaces/dev/descriptors/orders"},
		{"descriptor:read", "GET", "/api/v1/namespaces/dev/descriptors/orders/signature"},
		{"descriptor:read", "GET", "/api/v1/namespaces/dev/descriptors/orders/semantic-domain"},
		{"descriptor:read", "GET", "/api/v1/namespaces/dev/descriptors/orders/knowledge"},
		// descriptor resync (append + resync flow)
		{"descriptor:update", "POST", "/api/v1/namespaces/dev/descriptors/orders/resync"},
		// configmap get-by-name (llm)
		{"llmconfig:read", "GET", "/api/v1/namespaces/dev/llm-configmaps/llm-default"},
		// configmap get-by-name (prompt)
		{"promptconfig:read", "GET", "/api/v1/namespaces/dev/prompt-configmaps/prompt-default"},
		// agent namespaced list + detail
		{"agent:read", "GET", "/api/v1/namespaces/dev/agents"},
		{"agent:read", "GET", "/api/v1/namespaces/dev/agents/web"},
		// dd-group-relations read + delete ("remove from semantic group")
		{"semantic-group:read", "GET", "/api/v1/dd-group-relations/sd/sd-1"},
		{"semantic-group:manage", "DELETE", "/api/v1/dd-group-relations/42"},
		// semantic-domain search used by the remove-from-group flow
		{"semantic-group:manage", "POST", "/api/v1/semantic-domains/search/by-dd"},
		// agent composition graph reads semantic-domain detail
		{"semantic-group:read", "GET", "/api/v1/semantic-domains/sd-1"},
		// data-source detail lineage graph (read-only POST query)
		{"descriptor:graph:read", "POST", "/api/v1/knowledge-graph/get-graph-by-source"},
	}
	for _, tc := range cases {
		match := false
		for _, sp := range SeedPermissions {
			if sp.Code != tc.code {
				continue
			}
			p := Permission{Code: sp.Code, HTTPMethod: sp.HTTPMethod, HTTPPath: sp.HTTPPath}
			if p.Allows(tc.method, tc.path) {
				match = true
				break
			}
		}
		if !match {
			t.Errorf("%s must allow %s %s (frontend gap surface)", tc.code, tc.method, tc.path)
		}
	}
}

// TestSeedReadCodesDoNotGrantWrites guards against the rule-matrix pitfall
// where a read permission with an overly broad HTTPMethod (e.g. "GET,POST")
// combined with a "**" path would silently also authorize the resource's write
// endpoints. A read-only role holding descriptor:read must never be able to
// create a descriptor or trigger a resync.
func TestSeedReadCodesDoNotGrantWrites(t *testing.T) {
	type ep struct {
		code   string
		method string
		path   string
	}
	deny := []ep{
		{"descriptor:read", "POST", "/api/v1/namespaces/dev/descriptors"},
		{"descriptor:read", "POST", "/api/v1/namespaces/dev/descriptors/orders/resync"},
		{"descriptor:read", "DELETE", "/api/v1/namespaces/dev/descriptors/orders"},
		{"llmconfig:read", "POST", "/api/v1/namespaces/dev/llm-configmaps"},
		{"llmconfig:read", "DELETE", "/api/v1/namespaces/dev/llm-configmaps/llm-default"},
		{"promptconfig:read", "POST", "/api/v1/namespaces/dev/prompt-configmaps"},
		{"promptconfig:read", "DELETE", "/api/v1/namespaces/dev/prompt-configmaps/prompt-default"},
		{"agent:read", "DELETE", "/api/v1/namespaces/dev/agents/web"},
		{"semantic-group:read", "DELETE", "/api/v1/semantic-groups/g1"},
	}
	for _, tc := range deny {
		allowed := false
		for _, sp := range SeedPermissions {
			if sp.Code != tc.code {
				continue
			}
			p := Permission{Code: sp.Code, HTTPMethod: sp.HTTPMethod, HTTPPath: sp.HTTPPath}
			if p.Allows(tc.method, tc.path) {
				allowed = true
				break
			}
		}
		if allowed {
			t.Errorf("%s must NOT allow %s %s (read code leaking into write path)", tc.code, tc.method, tc.path)
		}
	}
}

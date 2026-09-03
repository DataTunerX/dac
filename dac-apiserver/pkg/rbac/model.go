// Package rbac provides the unified authorization engine for the DAC platform.
//
// It replaces the previous Casbin file-based policy system with a database-backed,
// page-managed RBAC model covering both platform-level (global) and tenant-level
// (scoped) authorization. See RBAC-DESIGN.md for the full design.
package rbac

import (
	"context"
	"strings"
	"time"
)

// Resource domains and action verbs are the vocabulary used by permission rules.
// They are stable identifiers written once by the seeder and referenced by API routes.
const (
	// ActionRead / ActionWrite / ActionManage are the coarse action verbs mapped to HTTP methods.
	ActionRead   = "read"
	ActionWrite  = "write"
	ActionManage = "manage"
)

// PlatformRole represents a global role that is not scoped to any tenant.
// A role with IsSuper == true bypasses every permission check (platform-wide).
type PlatformRole struct {
	ID          string
	Code        string
	Name        string
	IsSuper     bool
	Description string
}

// TenantRole represents a role that lives inside a single tenant.
type TenantRole struct {
	ID          string
	TenantID    string
	Code        string
	Name        string
	IsDefault   bool
	Description string
}

// Permission is the smallest authorization unit. It maps a business capability
// (e.g. "agent:read") to the concrete HTTP requests that exercise it.
type Permission struct {
	ID          string
	Code        string
	Name        string
	Resource    string
	Action      string
	HTTPMethod  string // "*" matches any method; comma-separated values allowed
	HTTPPath    string // "*" matches one segment; "**" matches any suffix
	Description string
}

// Rule is one concrete HTTP pattern that a permission grants access to.
// A single permission may expand to multiple rules when it covers several endpoints.
type Rule struct {
	Method string
	Path   string
}

// Rules converts the permission's comma-separated HTTP method list plus its
// path template into one Rule per (method, path). A single permission may
// cover several endpoints: HTTPPath may contain multiple path templates joined
// by '|' (e.g. "/api/v1/agents|/api/v1/namespaces/*/agents/*"), each expanded
// against every HTTP method.
func (p Permission) Rules() []Rule {
	methods := splitMethods(p.HTTPMethod)
	paths := splitPaths(p.HTTPPath)
	if len(paths) == 0 {
		return nil
	}
	rules := make([]Rule, 0, len(methods)*len(paths))
	for _, m := range methods {
		for _, path := range paths {
			rules = append(rules, Rule{Method: m, Path: path})
		}
	}
	return rules
}

// splitPaths splits an HTTPPath template that may contain several '|'-joined
// path patterns into its distinct templates. Empty entries are dropped.
func splitPaths(s string) []string {
	var out []string
	for _, part := range strings.Split(s, "|") {
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}

// splitMethods normalizes a "GET,POST" style list into distinct uppercase tokens.
func splitMethods(s string) []string {
	if s == "" || s == "*" {
		return []string{"*"}
	}
	var out []string
	for _, part := range splitCSV(s) {
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}

func splitCSV(s string) []string {
	var out []string
	start := 0
	for i := 0; i <= len(s); i++ {
		if i == len(s) || s[i] == ',' {
			if i > start {
				out = append(out, s[start:i])
			}
			start = i + 1
		}
	}
	return out
}

// Subject represents an authenticated principal after resolving its roles and
// permissions for one tenant context. It is passed to the engine instead of
// reading roles from the token so that role changes take effect immediately.
type Subject struct {
	UserID            string
	TenantID          string
	PlatformSuper     bool
	PermissionCodes   map[string]struct{}
	PlatformRoleNames []string
}

// AuthorizeResult is the outcome of a single authorization check.
type AuthorizeResult struct {
	Allowed bool
	Codes   []string // permission codes that matched the request, empty when denied
}

// PrincipalSnapshot is the resolved permission set of a logged-in user,
// used by self-information endpoints (/users/me) and client-side UX gating.
type PrincipalSnapshot struct {
	// IsSuper reports whether the user holds the platform super-admin role.
	IsSuper bool
	// PlatformRoles lists every platform role code bound to the user (sorted).
	PlatformRoles []string
	// PermissionCodes is the de-duplicated union of every permission code the
	// user holds through platform roles and tenant memberships.
	// A super admin's set is returned empty: their effective access is implicit.
	PermissionCodes []string
}

// ResourceAccess controls whether a principal may reach a given namespace.
// The tenant-to-namespace mapping is resolved by the engine at request time.
type ResourceAccess struct {
	TenantNamespaces []string // namespaces the current tenant holds
}

// Storage is the backend contract the engine and the management API share.
//
// The concrete implementation lives in the entity/database layer; the engine only
// depends on this interface so that authorization behaviour can be unit-tested
// against an in-memory fake.
type Storage interface {
	// GetUserPlatformRoles returns every platform role bound to the user.
	GetUserPlatformRoles(ctx context.Context, userID string) ([]PlatformRole, error)

	// GetTenantRole returns the tenant-local role bound to the user in the given tenant.
	GetTenantRole(ctx context.Context, userID, tenantID string) (*TenantRole, error)

	// ListTenantRolesByUser returns every tenant-local role bound to the user
	// across all of their memberships. It is used to build the principal's
	// complete permission snapshot for the /users/me self-information endpoint.
	ListTenantRolesByUser(ctx context.Context, userID string) ([]TenantRole, error)

	// GetRolePermissions returns the permission IDs bound to a role.
	// For platform roles the role is identified by platformRoleID, for tenant roles by tenantRoleID.
	GetRolePermissions(ctx context.Context, roleID string) ([]string, error)

	// GetTenantNamespaces returns the namespaces bound to a tenant.
	GetTenantNamespaces(ctx context.Context, tenantID string) ([]string, error)

	// IsTenantActive reports whether the tenant is not disabled.
	IsTenantActive(ctx context.Context, tenantID string) (bool, error)

	// PermissionsByCode resolves a permission code to its full definitions
	// (a code maps to one permission in the current design, but the slice leaves
	// room for later expansion without a breaking interface change).
	PermissionsByCode(ctx context.Context, code string) ([]Permission, error)

	// PermissionCodesByIDs resolves a batch of permission IDs to their codes.
	PermissionCodesByIDs(ctx context.Context, ids []string) ([]string, error)

	// TimeNow allows tests to control the clock used for cache TTL marking.
	TimeNow() time.Time
}

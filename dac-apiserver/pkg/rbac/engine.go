package rbac

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"sync"
	"time"
)

// Engine is the process-wide authorization core.
//
// It resolves a principal's roles and permissions from storage, applies the
// tenant-namespace mapping, and answers "may this (user, tenant) do method path?".
// Role lookup is always done against storage (never against a token snapshot) so
// that permission changes made via the management API take effect on the next
// request; an in-memory cache only accelerates the repeated read path.
type Engine struct {
	store Storage
	log   *slog.Logger

	mu         sync.RWMutex
	auditCache map[string]RoleSnapshot // key: roleID  →  snapshot of bound permission codes
	auditTTL   time.Duration
	// superCache caches "is user a platform super admin" which is read on every
	// request and only changed through the management API.
	superCache   map[string]superEntry
	superTTL     time.Duration
	nsCache      map[string]nsEntry
	nsTTL        time.Duration
	tenantActive map[string]bool
	activeTTL    time.Duration
}

type superEntry struct {
	value   bool
	expires time.Time
}

type nsEntry struct {
	list    []string
	expires time.Time
}

// RoleSnapshot is a cached binding of a role to its permission codes.
type RoleSnapshot struct {
	Codes []string
}

// NewEngine builds an Engine with the given storage backend and logger.
// A nil logger falls back to slog.Default() so the engine never panics even
// when tests or embedders do not provide one.
func NewEngine(store Storage, logger *slog.Logger) *Engine {
	if logger == nil {
		logger = slog.Default()
	}
	return &Engine{
		store: store,
		log:   logger,
		// Small caches: the platform always re-checks storage on any change event.
		auditCache:   make(map[string]RoleSnapshot),
		auditTTL:     5 * time.Minute,
		superCache:   make(map[string]superEntry),
		superTTL:     30 * time.Second,
		nsCache:      make(map[string]nsEntry),
		nsTTL:        30 * time.Second,
		tenantActive: make(map[string]bool),
		activeTTL:    30 * time.Second,
	}
}

// Subject returns whether UserID can perform method on path, within the given
// tenant context. When TenantID is empty, only platform-level permissions apply
// (used for management API and platform admin operations that are tenant-agnostic).
func (e *Engine) Subject(ctx context.Context, userID, tenantID, method, path string) (AuthorizeResult, error) {
	// 1. Platform-wide: a super admin is allowed everywhere, no further lookups.
	super, err := e.isSuper(ctx, userID)
	if err != nil {
		return AuthorizeResult{}, fmt.Errorf("check platform super: %w", err)
	}
	if super {
		return AuthorizeResult{Allowed: true}, nil
	}

	// 2. Tenant-scoped check.
	var codes []string
	if tenantID != "" {
		active, err := e.isTenantActive(ctx, tenantID)
		if err != nil {
			return AuthorizeResult{}, fmt.Errorf("check tenant active: %w", err)
		}
		if !active {
			// Disabled tenant: deny outright without leaking why in the response.
			e.log.Warn("authorize denied: tenant disabled",
				"user_id", userID, "tenant_id", tenantID, "method", method, "path", path)
			return AuthorizeResult{}, nil
		}

		role, err := e.store.GetTenantRole(ctx, userID, tenantID)
		switch {
		case err != nil && !isNotFound(err):
			return AuthorizeResult{}, fmt.Errorf("load tenant role: %w", err)
		case err == nil && role != nil:
			// A missing membership is not fatal here: platform roles below may
			// still authorize the request (e.g. a cross-tenant read-only "ops"
			// role). Deny-by-default falls out naturally if nothing matches.
			codes, err = e.roleCodes(ctx, role.ID, role.TenantID)
			if err != nil {
				return AuthorizeResult{}, fmt.Errorf("load tenant role permissions: %w", err)
			}
		}
	}

	// 3. Platform roles (non-super) also contribute permissions, e.g. an "ops"
	// platform role with read-only access across all tenants.
	platformRoles, err := e.store.GetUserPlatformRoles(ctx, userID)
	if err != nil {
		if !isNotFound(err) {
			return AuthorizeResult{}, fmt.Errorf("load platform roles: %w", err)
		}
	}
	for _, pr := range platformRoles {
		pc, err := e.roleCodes(ctx, pr.ID, "")
		if err != nil {
			return AuthorizeResult{}, fmt.Errorf("load platform role permissions: %w", err)
		}
		codes = append(codes, pc...)
	}

	// 4. Match the resolved permission codes against the request.
	for _, code := range codes {
		perms, err := e.store.PermissionsByCode(ctx, code)
		if err != nil {
			// A missing permission definition is a data bug; fail closed.
			return AuthorizeResult{}, fmt.Errorf("resolve permission code %s: %w", code, err)
		}
		for _, p := range perms {
			for _, r := range p.Rules() {
				if RuleMatch(r, method, path) {
					return AuthorizeResult{Allowed: true, Codes: []string{code}}, nil
				}
			}
		}
	}
	return AuthorizeResult{}, nil
}

// PermissionsForUser resolves the complete permission snapshot of a user,
// regardless of any single request: platform roles plus every tenant-local
// role across their memberships. Super admins short-circuit with no codes
// because their access is implicit (callers treat IsSuper as allow-all).
func (e *Engine) PermissionsForUser(ctx context.Context, userID string) (PrincipalSnapshot, error) {
	platformRoles, err := e.store.GetUserPlatformRoles(ctx, userID)
	if err != nil {
		if isNotFound(err) {
			platformRoles = nil
		} else {
			return PrincipalSnapshot{}, fmt.Errorf("load platform roles: %w", err)
		}
	}

	roleCodes := make(map[string]struct{})
	platformCodes := make([]string, 0, len(platformRoles))
	isSuper := false
	for _, pr := range platformRoles {
		platformCodes = append(platformCodes, pr.Code)
		if pr.IsSuper {
			isSuper = true
			break
		}
	}
	if isSuper {
		return PrincipalSnapshot{IsSuper: true, PlatformRoles: sortedUnique(platformCodes)}, nil
	}

	for _, pr := range platformRoles {
		codes, err := e.roleCodes(ctx, pr.ID, "")
		if err != nil {
			return PrincipalSnapshot{}, fmt.Errorf("load platform role %s permissions: %w", pr.Code, err)
		}
		for _, c := range codes {
			roleCodes[c] = struct{}{}
		}
	}

	tenantRoles, err := e.store.ListTenantRolesByUser(ctx, userID)
	if err != nil {
		if !isNotFound(err) {
			return PrincipalSnapshot{}, fmt.Errorf("load tenant roles: %w", err)
		}
	}
	for _, tr := range tenantRoles {
		codes, err := e.roleCodes(ctx, tr.ID, tr.TenantID)
		if err != nil {
			return PrincipalSnapshot{}, fmt.Errorf("load tenant role %s permissions: %w", tr.Code, err)
		}
		for _, c := range codes {
			roleCodes[c] = struct{}{}
		}
	}

	return PrincipalSnapshot{
		IsSuper:         false,
		PlatformRoles:   sortedUnique(platformCodes),
		PermissionCodes: sortedKeys(roleCodes),
	}, nil
}

// sortedKeys returns the sorted keys of a string set.
func sortedKeys(set map[string]struct{}) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// sortedUnique returns the de-duplicated, sorted copy of a string slice.
func sortedUnique(in []string) []string {
	set := make(map[string]struct{}, len(in))
	for _, s := range in {
		set[s] = struct{}{}
	}
	return sortedKeys(set)
}

// roleCodes returns the permission codes bound to a role, using the cache and
// falling back to storage on miss. Platform roles have an empty tenant marker.
func (e *Engine) roleCodes(ctx context.Context, roleID, tenantIDMarker string) ([]string, error) {
	e.mu.RLock()
	snap, ok := e.auditCache[roleID]
	ttl := e.auditTTL
	e.mu.RUnlock()
	if ok && time.Since(e.store.TimeNow()) < ttl {
		return snap.Codes, nil
	}

	ids, err := e.store.GetRolePermissions(ctx, roleID)
	if err != nil {
		if isNotFound(err) {
			return nil, nil
		}
		return nil, err
	}
	codes, err := e.store.PermissionCodesByIDs(ctx, ids)
	if err != nil {
		return nil, err
	}
	e.mu.Lock()
	e.auditCache[roleID] = RoleSnapshot{Codes: codes}
	e.mu.Unlock()
	return codes, nil
}

func (e *Engine) isSuper(ctx context.Context, userID string) (bool, error) {
	e.mu.RLock()
	entry, ok := e.superCache[userID]
	ttl := e.superTTL
	e.mu.RUnlock()
	if ok && time.Since(e.store.TimeNow()) < ttl {
		return entry.value, nil
	}
	roles, err := e.store.GetUserPlatformRoles(ctx, userID)
	if err != nil {
		if isNotFound(err) {
			return false, nil
		}
		return false, err
	}
	isSuper := false
	for _, r := range roles {
		if r.IsSuper {
			isSuper = true
			break
		}
	}
	e.mu.Lock()
	e.superCache[userID] = superEntry{value: isSuper, expires: e.store.TimeNow().Add(ttl)}
	e.mu.Unlock()
	return isSuper, nil
}

func (e *Engine) isTenantActive(ctx context.Context, tenantID string) (bool, error) {
	e.mu.RLock()
	active, ok := e.tenantActive[tenantID]
	e.mu.RUnlock()
	if ok {
		return active, nil
	}
	active, err := e.store.IsTenantActive(ctx, tenantID)
	if err != nil {
		if isNotFound(err) {
			return false, nil
		}
		return false, err
	}
	e.mu.Lock()
	e.tenantActive[tenantID] = active
	e.mu.Unlock()
	return active, nil
}

// TenantNamespaces returns the namespaces a tenant may access, used by handlers
// to scope resource queries.
func (e *Engine) TenantNamespaces(ctx context.Context, tenantID string) ([]string, error) {
	e.mu.RLock()
	entry, ok := e.nsCache[tenantID]
	ttl := e.nsTTL
	e.mu.RUnlock()
	if ok && time.Since(e.store.TimeNow()) < ttl {
		return entry.list, nil
	}
	list, err := e.store.GetTenantNamespaces(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	e.mu.Lock()
	e.nsCache[tenantID] = nsEntry{list: list, expires: e.store.TimeNow().Add(ttl)}
	e.mu.Unlock()
	return list, nil
}

// Invalidate clears every cached entry that depends on the named role, user, or
// tenant. It is called by the management API right after any authorization-relevant
// mutation so that page changes take effect without a service restart.
func (e *Engine) Invalidate(roles, users []string, tenants []string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, r := range roles {
		delete(e.auditCache, r)
	}
	for _, u := range users {
		delete(e.superCache, u)
	}
	for _, t := range tenants {
		delete(e.tenantActive, t)
		delete(e.nsCache, t)
	}
	if len(roles) > 0 || len(users) > 0 || len(tenants) > 0 {
		e.log.Debug("rbac cache invalidated", "roles", roles, "users", users, "tenants", tenants)
	}
}

// HasAnyPlatformPermission checks whether the user holds at least one of the
// given permission codes from their platform-level roles. Super admins always
// return true. This is used by handlers that need to enforce platform-level
// access to protected resources (e.g. the "default" skill namespace).
func (e *Engine) HasAnyPlatformPermission(ctx context.Context, userID string, codes ...string) (bool, error) {
	super, err := e.isSuper(ctx, userID)
	if err != nil {
		return false, err
	}
	if super {
		return true, nil
	}

	platformRoles, err := e.store.GetUserPlatformRoles(ctx, userID)
	if err != nil {
		if isNotFound(err) {
			return false, nil
		}
		return false, err
	}

	need := make(map[string]struct{}, len(codes))
	for _, c := range codes {
		need[c] = struct{}{}
	}

	for _, pr := range platformRoles {
		pc, err := e.roleCodes(ctx, pr.ID, "")
		if err != nil {
			return false, err
		}
		for _, c := range pc {
			if _, ok := need[c]; ok {
				return true, nil
			}
		}
	}
	return false, nil
}

// HasAllPlatformPermissions checks whether the user holds every one of the
// given permission codes from their platform-level roles. Super admins always
// return true.
func (e *Engine) HasAllPlatformPermissions(ctx context.Context, userID string, codes ...string) (bool, error) {
	super, err := e.isSuper(ctx, userID)
	if err != nil {
		return false, err
	}
	if super {
		return true, nil
	}

	platformRoles, err := e.store.GetUserPlatformRoles(ctx, userID)
	if err != nil {
		if isNotFound(err) {
			return false, nil
		}
		return false, err
	}

	owned := make(map[string]struct{})
	for _, pr := range platformRoles {
		pc, err := e.roleCodes(ctx, pr.ID, "")
		if err != nil {
			return false, err
		}
		for _, c := range pc {
			owned[c] = struct{}{}
		}
	}

	for _, c := range codes {
		if _, ok := owned[c]; !ok {
			return false, nil
		}
	}
	return true, nil
}

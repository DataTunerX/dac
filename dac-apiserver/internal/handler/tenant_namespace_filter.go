package handler

import (
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	rbacengine "github.com/lvyanru/dac-apiserver/pkg/rbac"
)

// tenantNamespaces reads the allowed namespace list resolved by the RBAC
// middleware and stored under ContextTenantNamesKey. Returns nil when no
// tenant context is present (super admin / platform-level calls).
func tenantNamespaces(c *app.RequestContext) []string {
	raw, _ := c.Get(rbacengine.ContextTenantNamesKey)
	if raw == nil {
		return nil
	}
	v, ok := raw.([]string)
	if !ok {
		return nil
	}
	return v
}

// hasPlatformK8sView returns true when the caller is a super admin or holds a
// platform role with namespace:read. In those cases the caller should see all
// cluster namespaces.
func hasPlatformK8sView(c *app.RequestContext) bool {
	if isSuper, _ := c.Get(rbacengine.ContextIsSuperAdminKey); isSuper != nil {
		if v, ok := isSuper.(bool); ok && v {
			return true
		}
	}
	if hasView, _ := c.Get(rbacengine.ContextHasPlatformK8sViewKey); hasView != nil {
		if v, ok := hasView.(bool); ok && v {
			return true
		}
	}
	return false
}

// tenantAllowedNamespaceSet returns the set of namespaces the current tenant
// user is allowed to access, and a boolean indicating whether filtering should
// be applied.
//
// Returns:
//   - nil, false: no tenant context OR platform-level namespace:read → show all
//   - map[string]struct{}, true: tenant namespaces available → filter to these
//   - (empty map), true: tenant has no bound namespaces → show nothing
func tenantAllowedNamespaceSet(c *app.RequestContext) (map[string]struct{}, bool) {
	if hasPlatformK8sView(c) {
		return nil, false
	}
	nss := tenantNamespaces(c)
	if nss == nil {
		return nil, false
	}
	return namespaceSet(nss), true
}

// namespaceSet builds a set from a slice of namespace strings.
func namespaceSet(nss []string) map[string]struct{} {
	m := make(map[string]struct{}, len(nss))
	for _, ns := range nss {
		m[ns] = struct{}{}
	}
	return m
}

// verifyTenantNamespaceAccess checks whether the caller may access the given
// K8s namespace. It returns true when:
//   - The caller is a platform admin (super admin or has namespace:read)
//   - No tenant context is present
//   - The given namespace is in the tenant's allowed list
//
// On denial it logs a warning and returns false.
func verifyTenantNamespaceAccess(c *app.RequestContext, log *slog.Logger, ns string) bool {
	if hasPlatformK8sView(c) {
		return true
	}
	nss := tenantNamespaces(c)
	if nss == nil {
		return true
	}
	for _, allowed := range nss {
		if allowed == ns {
			return true
		}
	}
	tid := ""
	if v, ok := c.Get(rbacengine.ContextTenantIDKey); ok {
		if s, ok := v.(string); ok {
			tid = s
		}
	}
	log.Warn("tenant namespace access denied", "namespace", ns, "tenant", tid)
	return false
}

// filterByTenantNamespaces filters a slice of items by the tenant's allowed
// namespaces. The getNS function extracts the namespace from each item.
// When the caller has platform-level namespace:read (or no tenant context),
// no filtering is applied and the original slice is returned unchanged.
func filterByTenantNamespaces[T any](items []T, getNS func(T) string, c *app.RequestContext, log *slog.Logger) []T {
	allowed, shouldFilter := tenantAllowedNamespaceSet(c)
	if !shouldFilter {
		return items
	}
	if len(allowed) == 0 {
		return nil
	}
	out := make([]T, 0, len(items))
	for _, item := range items {
		ns := getNS(item)
		if _, ok := allowed[ns]; ok {
			out = append(out, item)
		}
	}
	if len(out) < len(items) {
		tid := ""
		if v, ok := c.Get(rbacengine.ContextTenantIDKey); ok {
			if s, ok := v.(string); ok {
				tid = s
			}
		}
		log.Debug("tenant namespace filter applied", "before", len(items), "after", len(out), "tenant", tid)
	}
	return out
}
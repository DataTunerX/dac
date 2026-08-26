package rbac

import (
	"context"
	"strings"

	"github.com/cloudwego/hertz/pkg/app"
)

// TenantHeaderName is the header carrying the active tenant on a request.
// It is set by the frontend tenant switcher and used to scope authorization.
const TenantHeaderName = "X-Tenant-Id"

// RequestContextKeys are the in-context keys shared with business handlers.
// They let a handler learn the caller's resolved identity and permissions
// without touching RBAC internals.
const (
	ContextUserIDKey              = "user_id"                 // string
	ContextTenantIDKey            = "tenant_id"               // string
	ContextPermCodesKey           = "perm_codes"              // []string
	ContextTenantNamesKey         = "tenant_names"            // []string, the allowed namespaces as resolved by the engine
	ContextIsSuperAdminKey        = "is_super_admin"          // bool, set for platform super admins
	ContextHasPlatformK8sViewKey  = "has_platform_k8s_view"  // bool, set for super admins or platform roles with namespace:read
)

// selfServicePaths is a set of method+path pairs that are always accessible
// to any authenticated user regardless of their permissions. These are
// self-referencing and core dashboard read endpoints that every user
// should be able to access.
var selfServicePaths = map[string]struct{}{
	// Self-referencing endpoints
	"GET /api/v1/users/me":        {},
	"GET /api/v1/rbac/me/tenants": {},

	// Core dashboard read endpoints — any authenticated user can view
	// these lists even if they have no permissions. The data returned
	// will naturally be scoped/empty based on the user's context.
	"GET /api/v1/agents":                {},
	"GET /api/v1/semantic-groups":       {},
	"GET /api/v1/semantic-groups/roots": {},
	"GET /api/v1/chat/conversations":    {},
	"GET /api/v1/namespaces":            {},
}

// publicSkillReadPaths are GET path prefixes for the default skill namespace
// that are accessible to any authenticated user, because skills in the
// "default" namespace are public and visible in the skill marketplace.
var publicSkillReadPaths = []string{
	"/api/v1/skills/namespaces/default/skills",
	"/api/v1/skills/namespaces/default/exists",
}

// Middleware is the hertz adapter for the RBAC engine.
//
// It assumes an earlier JWT middleware has stored the authenticated user ID in
// the request context under ContextUserIDKey. It then:
//  1. reads the active tenant from the X-Tenant-Id header;
//  2. asks the engine whether (user, tenant) may perform (method, path);
//  3. on success stores the resolved identity + allowed namespaces for handlers;
//  4. on failure aborts with 403 (deny-by-default, no reason leaked).
func (e *Engine) Middleware() app.HandlerFunc {
	return func(ctx context.Context, c *app.RequestContext) {
		userIDVal, exists := c.Get(ContextUserIDKey)
		if !exists || userIDVal == nil {
			e.log.Warn("rbac middleware: missing authenticated user", "path", c.Path())
			c.AbortWithStatusJSON(403, map[string]interface{}{"code": "FORBIDDEN", "message": "forbidden"})
			return
		}
		userID, ok := userIDVal.(string)
		if !ok || userID == "" {
			e.log.Warn("rbac middleware: invalid user id in context", "path", c.Path())
			c.AbortWithStatusJSON(403, map[string]interface{}{"code": "FORBIDDEN", "message": "forbidden"})
			return
		}

		method := string(c.Request.Method())
		path := string(c.Request.URI().Path())

		// Resolve super admin status for context-driven handlers (e.g. namespace
		// listing that must show all namespaces for platform admins).
		if super, err := e.isSuper(ctx, userID); err == nil && super {
			c.Set(ContextIsSuperAdminKey, true)
		}

		// Check if the user has platform-level namespace:read permission (super admins
		// or platform roles with namespace:read). This flag is used by the namespace
		// listing handler to decide whether to return all cluster namespaces.
		if hasPlatformK8sView, err := e.HasAnyPlatformPermission(ctx, userID, "namespace:read"); err == nil && hasPlatformK8sView {
			c.Set(ContextHasPlatformK8sViewKey, true)
		}

		// Self-service endpoints: always allow any authenticated user.
		// These are self-referencing calls (e.g. /users/me, /rbac/me/tenants)
		// that every user needs to access regardless of assigned permissions.
		key := method + " " + path
		if _, self := selfServicePaths[key]; self {
			c.Set(ContextUserIDKey, userID)
			setTenantContext(ctx, c, e)
			c.Next(ctx)
			return
		}

		// Public skill marketplace: GET requests for the default namespace's
		// skills are always allowed (list, get, download). The default namespace
		// holds public skills visible to all authenticated users.
		if method == "GET" {
			for _, prefix := range publicSkillReadPaths {
				if strings.HasPrefix(path, prefix) {
					c.Set(ContextUserIDKey, userID)
					c.Next(ctx)
					return
				}
			}
		}

		tenantID := string(c.Request.Header.Peek(TenantHeaderName))
		tenantID = strings.TrimSpace(tenantID)

		res, err := e.Subject(ctx, userID, tenantID, method, path)
		if err != nil {
			e.log.Error("rbac authorization failed",
				"user_id", userID, "tenant_id", tenantID, "method", method, "path", path, "error", err)
			c.AbortWithStatusJSON(500, map[string]interface{}{"code": "INTERNAL_ERROR", "message": "authorization service unavailable"})
			return
		}

		if !res.Allowed {
			e.log.Warn("rbac denied",
				"user_id", userID, "tenant_id", tenantID, "method", method, "path", path)
			c.AbortWithStatusJSON(403, map[string]interface{}{"code": "FORBIDDEN", "message": "forbidden"})
			return
		}

		// Success: hand resolved context down to the business handler.
		c.Set(ContextUserIDKey, userID)
		setTenantContext(ctx, c, e)
		if len(res.Codes) > 0 {
			c.Set(ContextPermCodesKey, res.Codes)
		}
		c.Next(ctx)
	}
}

// setTenantContext reads the X-Tenant-Id header and resolves the tenant's
// bound namespaces, storing them in the request context for downstream handlers.
func setTenantContext(ctx context.Context, c *app.RequestContext, e *Engine) {
	tenantID := string(c.Request.Header.Peek(TenantHeaderName))
	tenantID = strings.TrimSpace(tenantID)
	if tenantID != "" {
		c.Set(ContextTenantIDKey, tenantID)
		if nss, err := e.TenantNamespaces(ctx, tenantID); err == nil {
			c.Set(ContextTenantNamesKey, nss)
		}
	}
}

package rbac

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeStorage is an in-memory Storage implementation for engine unit tests.
type fakeStorage struct {
	mu                 sync.Mutex
	platformRoles      map[string][]PlatformRole // userID → roles
	tenantRoles        map[string]*TenantRole    // userID:tenantID → role
	rolePerms          map[string][]string       // roleID → permission IDs
	tenantNamespaces   map[string][]string       // tenantID → list
	tenantActive       map[string]bool
	disabledTenant     map[string]bool
	perms              map[string]Permission // permissionID → definition
	permCodes          map[string]string     // permissionID → code
	now                time.Time
	notFoundTenantRole bool // if set, GetTenantRole returns notFound for everyone
}

func newFakeStorage() *fakeStorage {
	return &fakeStorage{
		platformRoles:    map[string][]PlatformRole{},
		tenantRoles:      map[string]*TenantRole{},
		rolePerms:        map[string][]string{},
		tenantNamespaces: map[string][]string{},
		tenantActive:     map[string]bool{},
		disabledTenant:   map[string]bool{},
		perms:            map[string]Permission{},
		permCodes:        map[string]string{},
		now:              time.Now(),
	}
}

func (f *fakeStorage) TimeNow() time.Time {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.now
}

func (f *fakeStorage) GetUserPlatformRoles(ctx context.Context, userID string) ([]PlatformRole, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	roles, ok := f.platformRoles[userID]
	if !ok {
		return nil, errNotFound
	}
	return roles, nil
}

func (f *fakeStorage) GetTenantRole(ctx context.Context, userID, tenantID string) (*TenantRole, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.notFoundTenantRole {
		return nil, errNotFound
	}
	role, ok := f.tenantRoles[userID+":"+tenantID]
	if !ok {
		return nil, errNotFound
	}
	return role, nil
}

// ListTenantRolesByUser returns every tenant-local role bound to the user across
// all memberships, mirroring the ent-backed store used by the engine snapshot.
func (f *fakeStorage) ListTenantRolesByUser(ctx context.Context, userID string) ([]TenantRole, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []TenantRole
	for key, role := range f.tenantRoles {
		if strings.HasPrefix(key, userID+":") {
			out = append(out, *role)
		}
	}
	return out, nil
}

func (f *fakeStorage) GetRolePermissions(ctx context.Context, roleID string) ([]string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	ids, ok := f.rolePerms[roleID]
	if !ok {
		return nil, errNotFound
	}
	return ids, nil
}

func (f *fakeStorage) GetTenantNamespaces(ctx context.Context, tenantID string) ([]string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	list, ok := f.tenantNamespaces[tenantID]
	if !ok {
		return nil, errNotFound
	}
	return list, nil
}

func (f *fakeStorage) IsTenantActive(ctx context.Context, tenantID string) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return !f.disabledTenant[tenantID], nil
}

func (f *fakeStorage) PermissionsByCode(ctx context.Context, code string) ([]Permission, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, p := range f.perms {
		if p.Code == code {
			return []Permission{p}, nil
		}
	}
	return nil, errNotFound
}

func (f *fakeStorage) PermissionCodesByIDs(ctx context.Context, ids []string) ([]string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]string, 0, len(ids))
	for _, id := range ids {
		code, ok := f.permCodes[id]
		if !ok {
			return nil, errNotFound
		}
		out = append(out, code)
	}
	return out, nil
}

// addPerm registers a permission def plus its ID→code mapping.
func (f *fakeStorage) addPerm(id, code, method, path string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.perms[id] = Permission{ID: id, Code: code, HTTPMethod: method, HTTPPath: path}
	f.permCodes[id] = code
}

func TestEngineSuperAdminBypassesEverything(t *testing.T) {
	store := newFakeStorage()
	store.platformRoles["u1"] = []PlatformRole{{ID: "r-super", Code: "super_admin", IsSuper: true}}
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u1", "tenant-x", "DELETE", "/api/v1/namespaces/prod/agents/web")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !res.Allowed {
		t.Fatal("super admin should be allowed on any path/method")
	}
}

func TestEngineDeniesWhenTenantDisabled(t *testing.T) {
	store := newFakeStorage()
	store.disabledTenant["tenant-disabled"] = true
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u1", "tenant-disabled", "GET", "/api/v1/agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Allowed {
		t.Fatal("member of a disabled tenant must be denied")
	}
}

func TestEngineTenantRoleGrantsPermission(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/namespaces/*/agents")
	store.rolePerms["r-viewer"] = []string{"p1"}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-viewer", TenantID: "t1", Code: "viewer"}
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u1", "t1", "GET", "/api/v1/namespaces/dev/agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !res.Allowed {
		t.Fatal("viewer with agent:read should be allowed on GET namespaced agents")
	}
	if len(res.Codes) == 0 || res.Codes[0] != "agent:read" {
		t.Fatalf("expected matched code agent:read, got %v", res.Codes)
	}
}

func TestEngineDeniesWriteToReadOnlyRole(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/namespaces/*/agents")
	store.rolePerms["r-viewer"] = []string{"p1"}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-viewer", TenantID: "t1", Code: "viewer"}
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u1", "t1", "DELETE", "/api/v1/namespaces/dev/agents/web")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Allowed {
		t.Fatal("viewer must not be allowed to DELETE")
	}
}

func TestEngineDeniesNonMember(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/namespaces/*/agents")
	store.rolePerms["r-viewer"] = []string{"p1"}
	// u1 is not a member of t2
	e := NewEngine(store, nil)

	res, err := e.Subject(context.Background(), "u1", "t2", "GET", "/api/v1/namespaces/dev/agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Allowed {
		t.Fatal("non-member must be denied by default")
	}
}

func TestEngineInvalidateClearsRoleCache(t *testing.T) {
	store := newFakeStorage()
	store.addPerm("p1", "agent:read", "GET", "/api/v1/namespaces/*/agents")
	store.addPerm("p2", "agent:delete", "DELETE", "/api/v1/namespaces/*/agents/*")
	store.rolePerms["r-editor"] = []string{"p1"}
	store.tenantRoles["u1:t1"] = &TenantRole{ID: "r-editor", TenantID: "t1", Code: "editor"}
	e := NewEngine(store, nil)

	if res, _ := e.Subject(context.Background(), "u1", "t1", "DELETE", "/api/v1/namespaces/dev/agents/web"); res.Allowed {
		t.Fatal("editor with only read should be denied DELETE")
	}

	// Grant delete via the management API path then invalidate.
	store.mu.Lock()
	store.rolePerms["r-editor"] = []string{"p1", "p2"}
	store.mu.Unlock()
	e.Invalidate([]string{"r-editor"}, nil, nil)

	res, err := e.Subject(context.Background(), "u1", "t1", "DELETE", "/api/v1/namespaces/dev/agents/web")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !res.Allowed {
		t.Fatal("after granting delete + invalidate, editor should be allowed DELETE")
	}
}

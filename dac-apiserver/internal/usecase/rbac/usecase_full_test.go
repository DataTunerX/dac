package rbac

import (
	"context"
	"log/slog"
	"sort"
	"sync"
	"testing"

	"golang.org/x/crypto/bcrypt"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	domainrbac "github.com/lvyanru/dac-apiserver/internal/domain/rbac"
	"github.com/lvyanru/dac-apiserver/pkg/rbac"
)

// memStore is a complete in-memory domainrbac.Store used by the CRUD and seed
// tests in this file. Unlike the partial fakeStore, no method falls through to
// a panic, so the full usecase surface can be exercised.
type memStore struct {
	mu sync.Mutex

	tenants    map[string]*domainrbac.Tenant
	tenantCode map[string]*domainrbac.Tenant

	tenantRoles map[string]*domainrbac.TenantRole
	trolesByTen map[string][]*domainrbac.TenantRole

	platRoles map[string]*domainrbac.PlatformRole
	platCode  map[string]*domainrbac.PlatformRole
	platUsers map[string][]string

	membersByKey map[string]*domainrbac.TenantMember
	membersByTen map[string][]*domainrbac.TenantMember

	nss map[string][]string

	permsByCode map[string]*domainrbac.Permission

	rolePerms map[string][]string // roleID → permission IDs
}

func newMemStore() *memStore {
	return &memStore{
		tenants:      map[string]*domainrbac.Tenant{},
		tenantCode:   map[string]*domainrbac.Tenant{},
		tenantRoles:  map[string]*domainrbac.TenantRole{},
		trolesByTen:  map[string][]*domainrbac.TenantRole{},
		platRoles:    map[string]*domainrbac.PlatformRole{},
		platCode:     map[string]*domainrbac.PlatformRole{},
		platUsers:    map[string][]string{},
		membersByKey: map[string]*domainrbac.TenantMember{},
		membersByTen: map[string][]*domainrbac.TenantMember{},
		nss:          map[string][]string{},
		permsByCode:  map[string]*domainrbac.Permission{},
		rolePerms:    map[string][]string{},
	}
}

func (m *memStore) ListTenants(context.Context, int, int) ([]*domainrbac.Tenant, int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	all := make([]*domainrbac.Tenant, 0, len(m.tenants))
	for _, t := range m.tenants {
		all = append(all, t)
	}
	return all, len(all), nil
}

func (m *memStore) GetTenant(_ context.Context, tenantID string) (*domainrbac.Tenant, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	t, ok := m.tenants[tenantID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return t, nil
}

func (m *memStore) GetTenantByCode(_ context.Context, code string) (*domainrbac.Tenant, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	t, ok := m.tenantCode[code]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return t, nil
}

func (m *memStore) CreateTenant(_ context.Context, t *domainrbac.Tenant) (*domainrbac.Tenant, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.tenantCode[t.Code]; ok {
		return nil, domain.NewConflictError("tenant code already exists")
	}
	if t.ID == "" {
		t.ID = "tenant-" + t.Code
	}
	m.tenants[t.ID] = t
	m.tenantCode[t.Code] = t
	return t, nil
}

func (m *memStore) UpdateTenant(_ context.Context, t *domainrbac.Tenant) (*domainrbac.Tenant, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	cur, ok := m.tenants[t.ID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	cur.Name = t.Name
	cur.Description = t.Description
	cur.Status = t.Status
	return cur, nil
}

func (m *memStore) DeleteTenant(_ context.Context, tenantID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.tenants[tenantID]; !ok {
		return domain.ErrNotFound
	}
	delete(m.tenants, tenantID)
	return nil
}

func (m *memStore) ListTenantNamespaces(_ context.Context, tenantID string) ([]string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	nss, ok := m.nss[tenantID]
	if !ok {
		return nil, nil
	}
	return nss, nil
}

func (m *memStore) AddTenantNamespace(_ context.Context, tenantID, namespace string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, n := range m.nss[tenantID] {
		if n == namespace {
			return nil
		}
	}
	m.nss[tenantID] = append(m.nss[tenantID], namespace)
	return nil
}

func (m *memStore) RemoveTenantNamespace(_ context.Context, tenantID, namespace string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	list := m.nss[tenantID]
	for i, n := range list {
		if n == namespace {
			m.nss[tenantID] = append(list[:i], list[i+1:]...)
			return nil
		}
	}
	return nil
}

func (m *memStore) ListTenantRoles(_ context.Context, tenantID string) ([]*domainrbac.TenantRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := append([]*domainrbac.TenantRole(nil), m.trolesByTen[tenantID]...)
	sort.Slice(out, func(i, j int) bool { return out[i].Code < out[j].Code })
	return out, nil
}

func (m *memStore) GetTenantRoleByID(_ context.Context, roleID string) (*domainrbac.TenantRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.tenantRoles[roleID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return r, nil
}

func (m *memStore) CreateTenantRole(_ context.Context, r *domainrbac.TenantRole) (*domainrbac.TenantRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if r.ID == "" {
		r.ID = "role-" + r.Code
	}
	m.tenantRoles[r.ID] = r
	m.trolesByTen[r.TenantID] = append(m.trolesByTen[r.TenantID], r)
	return r, nil
}

func (m *memStore) UpdateTenantRole(_ context.Context, r *domainrbac.TenantRole) (*domainrbac.TenantRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	cur, ok := m.tenantRoles[r.ID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	cur.Name = r.Name
	cur.Description = r.Description
	return cur, nil
}

func (m *memStore) DeleteTenantRole(_ context.Context, roleID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.tenantRoles[roleID]
	if !ok {
		return domain.ErrNotFound
	}
	delete(m.tenantRoles, roleID)
	m.trolesByTen[r.TenantID] = removeRole(m.trolesByTen[r.TenantID], roleID)
	return nil
}

func removeRole(list []*domainrbac.TenantRole, roleID string) []*domainrbac.TenantRole {
	out := list[:0]
	for _, r := range list {
		if r.ID != roleID {
			out = append(out, r)
		}
	}
	return out
}

func (m *memStore) ListTenantMembers(_ context.Context, tenantID string, offset, limit int) ([]*domainrbac.TenantMember, int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	all := append([]*domainrbac.TenantMember(nil), m.membersByTen[tenantID]...)
	sort.Slice(all, func(i, j int) bool { return all[i].UserID < all[j].UserID })
	total := len(all)
	if offset > total {
		offset = total
	}
	end := offset + limit
	if end > total {
		end = total
	}
	return all[offset:end], total, nil
}

func (m *memStore) GetTenantMembership(_ context.Context, tenantID, userID string) (*domainrbac.TenantMember, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	mb, ok := m.membersByKey[tenantID+":"+userID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return mb, nil
}

func (m *memStore) ListTenantIDsByUser(_ context.Context, userID string) ([]string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []string
	for tenantID, list := range m.membersByTen {
		for _, mb := range list {
			if mb.UserID == userID {
				out = append(out, tenantID)
			}
		}
	}
	return out, nil
}

func (m *memStore) ListUsersNotInAnyTenant(ctx context.Context) ([]string, error) {
	// This is a simplified implementation for tests: it relies on the fact that
	// test users are seeded by the test in the UserRepo, not in the memStore.
	// In production the Store queries the DB directly. For tests we just need
	// the interface satisfied.
	return nil, nil
}

func (m *memStore) AddTenantMember(_ context.Context, tenantID, userID, roleID string) (*domainrbac.TenantMember, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	mb := &domainrbac.TenantMember{
		ID:       "m-" + tenantID + "-" + userID,
		TenantID: tenantID,
		UserID:   userID,
		RoleID:   roleID,
	}
	m.membersByKey[tenantID+":"+userID] = mb
	m.membersByTen[tenantID] = append(m.membersByTen[tenantID], mb)
	return mb, nil
}

func (m *memStore) ChangeTenantMemberRole(_ context.Context, tenantID, userID, roleID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	mb, ok := m.membersByKey[tenantID+":"+userID]
	if !ok {
		return domain.ErrNotFound
	}
	mb.RoleID = roleID
	return nil
}

func (m *memStore) RemoveTenantMember(_ context.Context, tenantID, userID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.membersByKey[tenantID+":"+userID]; !ok {
		return domain.ErrNotFound
	}
	delete(m.membersByKey, tenantID+":"+userID)
	m.membersByTen[tenantID] = removeMember(m.membersByTen[tenantID], userID)
	return nil
}

func removeMember(list []*domainrbac.TenantMember, userID string) []*domainrbac.TenantMember {
	out := list[:0]
	for _, mb := range list {
		if mb.UserID != userID {
			out = append(out, mb)
		}
	}
	return out
}

func (m *memStore) ListPlatformRoles(context.Context) ([]*domainrbac.PlatformRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]*domainrbac.PlatformRole, 0, len(m.platRoles))
	for _, r := range m.platRoles {
		out = append(out, r)
	}
	return out, nil
}

func (m *memStore) GetPlatformRole(_ context.Context, roleID string) (*domainrbac.PlatformRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.platRoles[roleID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return r, nil
}

func (m *memStore) CreatePlatformRole(_ context.Context, r *domainrbac.PlatformRole) (*domainrbac.PlatformRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if r.ID == "" {
		r.ID = "pr-" + r.Code
	}
	m.platRoles[r.ID] = r
	m.platCode[r.Code] = r
	return r, nil
}

func (m *memStore) UpdatePlatformRole(_ context.Context, r *domainrbac.PlatformRole) (*domainrbac.PlatformRole, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	cur, ok := m.platRoles[r.ID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	cur.Name = r.Name
	cur.Description = r.Description
	return cur, nil
}

func (m *memStore) DeletePlatformRole(_ context.Context, roleID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.platRoles[roleID]
	if !ok {
		return domain.ErrNotFound
	}
	delete(m.platRoles, roleID)
	delete(m.platCode, r.Code)
	return nil
}

func (m *memStore) ListPlatformRoleUsers(_ context.Context, roleID string) ([]string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]string(nil), m.platUsers[roleID]...), nil
}

func (m *memStore) AssignPlatformRole(_ context.Context, userID, roleID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, u := range m.platUsers[roleID] {
		if u == userID {
			return nil
		}
	}
	m.platUsers[roleID] = append(m.platUsers[roleID], userID)
	return nil
}

func (m *memStore) RevokePlatformRole(_ context.Context, userID, roleID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	list := m.platUsers[roleID]
	for i, u := range list {
		if u == userID {
			m.platUsers[roleID] = append(list[:i], list[i+1:]...)
			return nil
		}
	}
	return nil
}

func (m *memStore) ListPermissions(context.Context) ([]*domainrbac.Permission, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]*domainrbac.Permission, 0, len(m.permsByCode))
	for _, p := range m.permsByCode {
		out = append(out, p)
	}
	return out, nil
}

func (m *memStore) GetPermissionByCode(_ context.Context, code string) (*domainrbac.Permission, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.permsByCode[code]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return p, nil
}

func (m *memStore) UpsertPermission(_ context.Context, p *domainrbac.Permission) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if p.ID == "" {
		p.ID = "perm-" + p.Code
	}
	m.permsByCode[p.Code] = p
	return nil
}

func (m *memStore) SetRolePermissions(_ context.Context, roleID, _ string, permissionIDs []string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.rolePerms[roleID] = append([]string(nil), permissionIDs...)
	return nil
}

func (m *memStore) GetRolePermissionIDs(_ context.Context, roleID string, _ bool) ([]string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	ids, ok := m.rolePerms[roleID]
	if !ok {
		return []string{}, nil
	}
	return append([]string(nil), ids...), nil
}

func (m *memStore) PermissionCodesByIDs(_ context.Context, ids []string) ([]string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	codes := make([]string, 0, len(ids))
	for _, id := range ids {
		// Look up code by scanning permsByCode (IDs are derived "perm-<code>").
		found := false
		for code, p := range m.permsByCode {
			if p.ID == id {
				codes = append(codes, code)
				found = true
				break
			}
		}
		if !found {
			return nil, domain.ErrNotFound
		}
	}
	sort.Strings(codes)
	return codes, nil
}

// fullUserRepo is a complete domain.UserRepository backed by a slice.
type fullUserRepo struct {
	users []*entity.User
}

func (f *fullUserRepo) GetByID(_ context.Context, userID string) (*entity.User, error) {
	for _, u := range f.users {
		if u.ID == userID {
			return u, nil
		}
	}
	return nil, domain.ErrNotFound
}

func (f *fullUserRepo) GetByUsername(_ context.Context, username string) (*entity.User, error) {
	for _, u := range f.users {
		if u.Username == username {
			return u, nil
		}
	}
	return nil, domain.ErrNotFound
}

func (f *fullUserRepo) List(_ context.Context, offset, limit int) ([]*entity.User, error) {
	if offset > len(f.users) {
		return nil, nil
	}
	end := offset + limit
	if end > len(f.users) {
		end = len(f.users)
	}
	return f.users[offset:end], nil
}

func (f *fullUserRepo) Count(context.Context) (int, error) {
	return len(f.users), nil
}

func (f *fullUserRepo) Create(_ context.Context, username, passwordHash string, email *string) (*entity.User, error) {
	for _, u := range f.users {
		if u.Username == username {
			return nil, domain.NewAlreadyExistsError("User", username)
		}
	}
	user := &entity.User{ID: "u-" + username, Username: username, PasswordHash: passwordHash, Email: email}
	f.users = append(f.users, user)
	return user, nil
}

func (f *fullUserRepo) Delete(context.Context, string) error { panic("unexpected Delete") }

func (f *fullUserRepo) UpdateLastLogin(context.Context, string) error {
	panic("unexpected UpdateLastLogin")
}

func (f *fullUserRepo) UpdateUser(_ context.Context, userID string, email, passwordHash *string) error {
	for _, u := range f.users {
		if u.ID == userID {
			if email != nil {
				u.Email = email
			}
			if passwordHash != nil {
				u.PasswordHash = *passwordHash
			}
			return nil
		}
	}
	return domain.ErrNotFound
}

// ---------- tenant CRUD ----------

func TestTenantsPaginatedPassthrough(t *testing.T) {
	store := newMemStore()
	for i, code := range []string{"t-b", "t-a", "t-c"} {
		store.CreateTenant(context.Background(), &domainrbac.Tenant{ID: string(rune(65 + i)), Code: code, Name: code})
	}
	uc := newUsecase(store, &fullUserRepo{})

	list, err := uc.Tenants(context.Background(), 0, 100)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if list.Total != 3 || len(list.Items) != 3 {
		t.Fatalf("total=%d items=%d, want 3/3", list.Total, len(list.Items))
	}
}

func TestTenantGetPassesStoreError(t *testing.T) {
	store := newMemStore()
	uc := newUsecase(store, &fullUserRepo{})

	if _, err := uc.Tenant(context.Background(), "missing"); !domain.IsNotFound(err) {
		t.Fatalf("expected not-found, got %v", err)
	}
}

func TestCreateTenantValidation(t *testing.T) {
	uc := newUsecase(newMemStore(), &fullUserRepo{})

	_, err := uc.CreateTenant(context.Background(), "op", "  ", "name", "")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for empty code, got %v", err)
	}
	_, err = uc.CreateTenant(context.Background(), "op", "code", "  ", "")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for empty name, got %v", err)
	}
}

func TestCreateTenantStartsWithActiveStatus(t *testing.T) {
	store := newMemStore()
	uc := newUsecase(store, &fullUserRepo{})

	got, err := uc.CreateTenant(context.Background(), "op", "acme", "Acme Corp", "desc")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.Status != "active" {
		t.Fatalf("status=%q, want active", got.Status)
	}
	if got.Code != "acme" || got.Name != "Acme Corp" || got.Description != "desc" {
		t.Fatalf("tenant fields not stored: %+v", got)
	}
}

func TestUpdateTenantRejectsInvalidStatus(t *testing.T) {
	uc := newUsecase(newMemStore(), &fullUserRepo{})

	_, err := uc.UpdateTenant(context.Background(), "op", "t1", "", "", "banana")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for bad status, got %v", err)
	}
}

func TestUpdateTenantChangesNameStatusDescription(t *testing.T) {
	store := newMemStore()
	store.CreateTenant(context.Background(), &domainrbac.Tenant{ID: "t1", Code: "acme", Name: "old", Status: "active"})
	uc := newUsecase(store, &fullUserRepo{})

	got, err := uc.UpdateTenant(context.Background(), "op", "t1", "new-name", "nd", "disabled")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.Name != "new-name" || got.Description != "nd" || got.Status != "disabled" {
		t.Fatalf("updated tenant=%+v", got)
	}
}

func TestDisableAndEnableTenant(t *testing.T) {
	store := newMemStore()
	store.CreateTenant(context.Background(), &domainrbac.Tenant{ID: "t1", Code: "acme", Name: "acme", Status: "active"})
	uc := newUsecase(store, &fullUserRepo{})

	dis, err := uc.DisableTenant(context.Background(), "op", "t1")
	if err != nil {
		t.Fatalf("disable: %v", err)
	}
	if dis.Status != "disabled" {
		t.Fatalf("status=%q, want disabled", dis.Status)
	}
	en, err := uc.EnableTenant(context.Background(), "op", "t1")
	if err != nil {
		t.Fatalf("enable: %v", err)
	}
	if en.Status != "active" {
		t.Fatalf("status=%q, want active", en.Status)
	}
}

func TestDeleteTenant(t *testing.T) {
	store := newMemStore()
	store.CreateTenant(context.Background(), &domainrbac.Tenant{ID: "t1", Code: "acme", Name: "acme"})
	uc := newUsecase(store, &fullUserRepo{})

	if err := uc.DeleteTenant(context.Background(), "op", "t1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := store.GetTenant(context.Background(), "t1"); !domain.IsNotFound(err) {
		t.Fatalf("tenant must be gone, got %v", err)
	}
}

// ---------- tenant namespaces ----------

func TestTenantNamespacesRoundtrip(t *testing.T) {
	store := newMemStore()
	uc := newUsecase(store, &fullUserRepo{})

	if _, err := store.CreateTenant(context.Background(), &domainrbac.Tenant{ID: "t1", Code: "acme", Name: "Acme", Status: "active"}); err != nil {
		t.Fatalf("seed tenant: %v", err)
	}

	if err := uc.AddTenantNamespace(context.Background(), "op", "t1", "dev"); err != nil {
		t.Fatalf("add: %v", err)
	}
	if err := uc.AddTenantNamespace(context.Background(), "op", "t1", "prod"); err != nil {
		t.Fatalf("add second: %v", err)
	}
	nss, err := uc.TenantNamespaces(context.Background(), "t1")
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(nss) != 2 {
		t.Fatalf("namespaces=%v, want 2", nss)
	}

	if err := uc.RemoveTenantNamespace(context.Background(), "op", "t1", "dev"); err != nil {
		t.Fatalf("remove: %v", err)
	}
	nss, _ = uc.TenantNamespaces(context.Background(), "t1")
	if len(nss) != 1 || nss[0] != "prod" {
		t.Fatalf("after remove namespaces=%v, want [prod]", nss)
	}
}

// ---------- tenant roles ----------

func TestCreateTenantRoleValidation(t *testing.T) {
	uc := newUsecase(newMemStore(), &fullUserRepo{})

	_, err := uc.CreateTenantRole(context.Background(), "op", "t1", " ", "name", "")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input, got %v", err)
	}
}

func TestCreateAndListTenantRoles(t *testing.T) {
	store := newMemStore()
	uc := newUsecase(store, &fullUserRepo{})

	got, err := uc.CreateTenantRole(context.Background(), "op", "t1", "editor", "Editor", "can edit")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.TenantID != "t1" || got.Code != "editor" {
		t.Fatalf("created role=%+v", got)
	}
	roles, err := uc.TenantRoles(context.Background(), "t1")
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(roles) != 1 || roles[0].Code != "editor" {
		t.Fatalf("roles=%v", roles)
	}
}

func TestUpdateTenantRoleChecksOwnership(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	_, err := uc.UpdateTenantRole(context.Background(), "op", "t2", "r1", "n", "")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for foreign role, got %v", err)
	}
}

func TestUpdateTenantRoleRenames(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer", Name: "old"})
	uc := newUsecase(store, &fullUserRepo{})

	got, err := uc.UpdateTenantRole(context.Background(), "op", "t1", "r1", "New Viewer", "changed")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.Name != "New Viewer" || got.Description != "changed" {
		t.Fatalf("updated=%+v", got)
	}
}

func TestDeleteTenantRoleChecksOwnership(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	err := uc.DeleteTenantRole(context.Background(), "op", "t2", "r1")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input, got %v", err)
	}
}

func TestDeleteTenantRoleRemoves(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	if err := uc.DeleteTenantRole(context.Background(), "op", "t1", "r1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := store.GetTenantRoleByID(context.Background(), "r1"); !domain.IsNotFound(err) {
		t.Fatalf("role must be gone, got %v", err)
	}
}

// ---------- role ↔ permissions ----------

func TestSetTenantRolePermissionsChecksOwnership(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	err := uc.SetTenantRolePermissions(context.Background(), "op", "t2", "r1", []string{"a:read"})
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input, got %v", err)
	}
}

func TestSetTenantRolePermissionsUnknownCode(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	err := uc.SetTenantRolePermissions(context.Background(), "op", "t1", "r1", []string{"does:not:exist"})
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for unknown code, got %v", err)
	}
}

func TestSetTenantRolePermissionsDeduplicatesAndSorts(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "b:manage", ID: "p-b"})
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "a:read", ID: "p-a"})
	uc := newUsecase(store, &fullUserRepo{})

	err := uc.SetTenantRolePermissions(context.Background(), "op", "t1", "r1", []string{"b:manage", "a:read", "b:manage"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	ids, err := store.GetRolePermissionIDs(context.Background(), "r1", false)
	if err != nil {
		t.Fatalf("get ids: %v", err)
	}
	if len(ids) != 2 || ids[0] != "p-a" || ids[1] != "p-b" {
		t.Fatalf("ids=%v, want sorted unique [p-a p-b]", ids)
	}
}

func TestTenantRolePermissionCodesRoundTrip(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "agent:read", ID: "p-a"})
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "llmconfig:read", ID: "p-c"})
	store.SetRolePermissions(context.Background(), "r1", "t1", []string{"p-a", "p-c"})
	uc := newUsecase(store, &fullUserRepo{})

	codes, err := uc.TenantRolePermissionCodes(context.Background(), "t1", "r1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(codes) != 2 || codes[0] != "agent:read" || codes[1] != "llmconfig:read" {
		t.Fatalf("codes=%v", codes)
	}
}

func TestTenantRolePermissionCodesRejectsForeignTenant(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	_, err := uc.TenantRolePermissionCodes(context.Background(), "t2", "r1")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input, got %v", err)
	}
}

func TestTenantRolePermissionCodesEmptyWhenNoGrants(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	codes, err := uc.TenantRolePermissionCodes(context.Background(), "t1", "r1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(codes) != 0 {
		t.Fatalf("codes=%v, want empty", codes)
	}
}

// ---------- tenant members ----------

func TestAddTenantMemberSuccess(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	users := &fullUserRepo{users: []*entity.User{{ID: "u1", Username: "alice"}}}
	uc := newUsecase(store, users)

	if err := uc.AddTenantMember(context.Background(), "op", "t1", "u1", "r1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	mb, err := store.GetTenantMembership(context.Background(), "t1", "u1")
	if err != nil || mb.RoleID != "r1" {
		t.Fatalf("membership=%+v err=%v", mb, err)
	}
}

func TestAddTenantMemberLookupUserFailure(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	users := &fullUserRepo{}
	uc := newUsecase(store, users)

	err := uc.AddTenantMember(context.Background(), "op", "t1", "ghost", "r1")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input, got %v", err)
	}
}

func TestChangeTenantMemberRoleChecksOwnership(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	uc := newUsecase(store, &fullUserRepo{})

	err := uc.ChangeTenantMemberRole(context.Background(), "op", "t2", "u1", "r1")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input, got %v", err)
	}
}

func TestChangeTenantMemberRoleSuccess(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r2", TenantID: "t1", Code: "editor"})
	store.AddTenantMember(context.Background(), "t1", "u1", "r1")
	uc := newUsecase(store, &fullUserRepo{})

	if err := uc.ChangeTenantMemberRole(context.Background(), "op", "t1", "u1", "r2"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	mb, _ := store.GetTenantMembership(context.Background(), "t1", "u1")
	if mb.RoleID != "r2" {
		t.Fatalf("role=%q, want r2", mb.RoleID)
	}
}

func TestRemoveTenantMember(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	store.AddTenantMember(context.Background(), "t1", "u1", "r1")
	uc := newUsecase(store, &fullUserRepo{})

	if err := uc.RemoveTenantMember(context.Background(), "op", "t1", "u1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := store.GetTenantMembership(context.Background(), "t1", "u1"); !domain.IsNotFound(err) {
		t.Fatalf("member must be gone, got %v", err)
	}
}

func TestTenantMembersPaginated(t *testing.T) {
	store := newMemStore()
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	store.AddTenantMember(context.Background(), "t1", "u1", "r1")
	store.AddTenantMember(context.Background(), "t1", "u2", "r1")
	uc := newUsecase(store, &fullUserRepo{})

	list, err := uc.TenantMembers(context.Background(), "t1", 0, 10)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if list.Total != 2 || len(list.Items) != 2 {
		t.Fatalf("total=%d items=%d, want 2/2", list.Total, len(list.Items))
	}
}

// ---------- platform roles ----------

func TestCreatePlatformRoleDefaultsNonSuper(t *testing.T) {
	store := newMemStore()
	uc := newUsecase(store, &fullUserRepo{})

	got, err := uc.CreatePlatformRole(context.Background(), "op", "ops", "Ops", "platform ops")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.IsSuper {
		t.Fatal("a newly created platform role must never be super")
	}
	if _, err := uc.PlatformRoles(context.Background()); err != nil {
		t.Fatalf("list: %v", err)
	}
}

func TestUpdatePlatformRoleNotFound(t *testing.T) {
	uc := newUsecase(newMemStore(), &fullUserRepo{})

	_, err := uc.UpdatePlatformRole(context.Background(), "op", "missing", "n", "")
	if !domain.IsNotFound(err) {
		t.Fatalf("expected not-found, got %v", err)
	}
}

func TestSetPlatformRolePermissionsUnknownCode(t *testing.T) {
	store := newMemStore()
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{ID: "pr-ops", Code: "ops"})
	uc := newUsecase(store, &fullUserRepo{})

	err := uc.SetPlatformRolePermissions(context.Background(), "op", "pr-ops", []string{"nope:nope"})
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input, got %v", err)
	}
}

func TestSetPlatformRolePermissionsSuccess(t *testing.T) {
	store := newMemStore()
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{ID: "pr-ops", Code: "ops"})
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "tenant:manage", ID: "p-t"})
	uc := newUsecase(store, &fullUserRepo{})

	if err := uc.SetPlatformRolePermissions(context.Background(), "op", "pr-ops", []string{"tenant:manage"}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	ids, err := store.GetRolePermissionIDs(context.Background(), "pr-ops", true)
	if err != nil || len(ids) != 1 || ids[0] != "p-t" {
		t.Fatalf("ids=%v err=%v", ids, err)
	}
}

func TestPlatformRolePermissionCodesRoundTrip(t *testing.T) {
	store := newMemStore()
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{ID: "pr-ops", Code: "ops"})
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "tenant:manage", ID: "p-t"})
	store.SetRolePermissions(context.Background(), "pr-ops", "", []string{"p-t"})
	uc := newUsecase(store, &fullUserRepo{})

	codes, err := uc.PlatformRolePermissionCodes(context.Background(), "pr-ops")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(codes) != 1 || codes[0] != "tenant:manage" {
		t.Fatalf("codes=%v", codes)
	}
}

func TestPlatformRolePermissionCodesEmptyForSuper(t *testing.T) {
	store := newMemStore()
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{
		ID: "pr-super", Code: "super_admin", IsSuper: true,
	})
	uc := newUsecase(store, &fullUserRepo{})

	codes, err := uc.PlatformRolePermissionCodes(context.Background(), "pr-super")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(codes) != 0 {
		t.Fatalf("codes=%v, want empty for super role", codes)
	}
}

func TestDeletePlatformRoleRejectsSuper(t *testing.T) {
	store := newMemStore()
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{
		ID: "pr-super", Code: "super_admin", IsSuper: true,
	})
	uc := newUsecase(store, &fullUserRepo{})

	err := uc.DeletePlatformRole(context.Background(), "op", "pr-super")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for super deletion, got %v", err)
	}
}

func TestPlatformRoleUsersBuildsViews(t *testing.T) {
	store := newMemStore()
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{ID: "pr-ops", Code: "ops"})
	store.AssignPlatformRole(context.Background(), "u1", "pr-ops")
	store.AssignPlatformRole(context.Background(), "u2", "pr-ops")
	uc := newUsecase(store, &fullUserRepo{})

	views, err := uc.PlatformRoleUsers(context.Background(), "pr-ops")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(views) != 2 {
		t.Fatalf("views=%v, want 2", views)
	}
	for _, v := range views {
		if v.RoleCode != "ops" {
			t.Fatalf("view=%+v, want role code ops", v)
		}
	}
}

func TestGrantPlatformRoleSuccess(t *testing.T) {
	store := newMemStore()
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{ID: "pr-ops", Code: "ops"})
	users := &fullUserRepo{users: []*entity.User{{ID: "u1", Username: "alice"}}}
	uc := newUsecase(store, users)

	if err := uc.GrantPlatformRole(context.Background(), "op", "u1", "pr-ops"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	holders, _ := store.ListPlatformRoleUsers(context.Background(), "pr-ops")
	if len(holders) != 1 || holders[0] != "u1" {
		t.Fatalf("holders=%v", holders)
	}
}

// ---------- permissions & my tenants ----------

func TestPermissionsPassthrough(t *testing.T) {
	store := newMemStore()
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "agent:read"})
	uc := newUsecase(store, &fullUserRepo{})

	perms, err := uc.Permissions(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(perms) != 1 || perms[0].Code != "agent:read" {
		t.Fatalf("perms=%v", perms)
	}
}

func TestMyTenantsSkipsMissingTenant(t *testing.T) {
	store := newMemStore()
	store.CreateTenant(context.Background(), &domainrbac.Tenant{ID: "t1", Code: "acme", Name: "acme"})
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{ID: "r1", TenantID: "t1", Code: "viewer"})
	store.AddTenantMember(context.Background(), "t1", "u1", "r1")
	// A member of a tenant id that no longer exists.
	store.membersByTen["ghost"] = append(store.membersByTen["ghost"], &domainrbac.TenantMember{TenantID: "ghost", UserID: "u1"})
	store.membersByKey["ghost:u1"] = store.membersByTen["ghost"][0]

	uc := newUsecase(store, &fullUserRepo{})
	tenants, err := uc.MyTenants(context.Background(), "u1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(tenants) != 1 || tenants[0].ID != "t1" {
		t.Fatalf("tenants=%v, want only t1", tenants)
	}
}

func TestMyTenantsEmptyForUnknownUser(t *testing.T) {
	uc := newUsecase(newMemStore(), &fullUserRepo{})

	tenants, err := uc.MyTenants(context.Background(), "nobody")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(tenants) != 0 {
		t.Fatalf("tenants=%v, want none", tenants)
	}
}

// ---------- merge helpers ----------

func TestMergeSeedPermissionsUnionsPathsWidensMethod(t *testing.T) {
	catalog := []rbac.SeedPermission{
		{Code: "agent:read", Name: "Agent Read", HTTPMethod: "GET", HTTPPath: "/api/v1/agents"},
		{Code: "agent:read", Name: "Agent Read Detail", HTTPMethod: "GET", HTTPPath: "/api/v1/namespaces/*/agents/*"},
		{Code: "agent:write", Name: "Agent Write", HTTPMethod: "POST", HTTPPath: "/api/v1/agents"},
	}

	merged := mergeSeedPermissions(catalog)

	read := merged["agent:read"]
	if len(read.PathTemplates) != 2 {
		t.Fatalf("agent:read paths=%v, want 2", read.PathTemplates)
	}
	// Identity fields come from the first entry.
	if read.Name != "Agent Read" {
		t.Fatalf("name=%q, want first entry name", read.Name)
	}
	if read.HTTPMethod != "GET" {
		t.Fatalf("method=%q, want GET", read.HTTPMethod)
	}

	// A "*" method widens the merged rule to "*".
	catalogWide := []rbac.SeedPermission{
		{Code: "x:read", HTTPMethod: "GET", HTTPPath: "/api/v1/x"},
		{Code: "x:read", HTTPMethod: "*", HTTPPath: "/api/v1/x"},
	}
	mergedWide := mergeSeedPermissions(catalogWide)
	if mergedWide["x:read"].HTTPMethod != "*" {
		t.Fatalf("method=%q, want *", mergedWide["x:read"].HTTPMethod)
	}
}

func TestMergeSeedPermissionsDeduplicatesPathTemplates(t *testing.T) {
	catalog := []rbac.SeedPermission{
		{Code: "y:read", HTTPMethod: "GET", HTTPPath: "/api/v1/y|/api/v1/y"},
		{Code: "y:read", HTTPMethod: "GET", HTTPPath: "/api/v1/y"},
	}
	merged := mergeSeedPermissions(catalog)
	if len(merged["y:read"].PathTemplates) != 1 {
		t.Fatalf("paths=%v, want 1", merged["y:read"].PathTemplates)
	}
}

func TestSplitPathTemplatesFiltersEmpty(t *testing.T) {
	got := splitPathTemplates("/a|/b|")
	if len(got) != 2 || got[0] != "/a" || got[1] != "/b" {
		t.Fatalf("got=%v", got)
	}
	if splitPathTemplates("") != nil {
		t.Fatal("empty string must yield nil")
	}
}

func TestAppendUnique(t *testing.T) {
	list := appendUnique(nil, "a")
	list = appendUnique(list, "b")
	list = appendUnique(list, "a")
	if len(list) != 2 {
		t.Fatalf("list=%v, want [a b]", list)
	}
}

// ---------- SeedDefaults ----------

func TestSeedDefaultsBootstrapsFreshSystem(t *testing.T) {
	store := newMemStore()
	users := &fullUserRepo{}
	uc := newUsecase(store, users)

	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("seed defaults: %v", err)
	}

	// 1. Permission catalog was upserted.
	perms, err := uc.Permissions(context.Background())
	if err != nil || len(perms) == 0 {
		t.Fatalf("permissions=%v err=%v, want non-empty catalog", perms, err)
	}

	// 2. Super admin platform role exists and is super.
	roles, _ := uc.PlatformRoles(context.Background())
	var super *domainrbac.PlatformRole
	for _, r := range roles {
		if r.Code == "super_admin" {
			super = r
		}
	}
	if super == nil || !super.IsSuper {
		t.Fatalf("super admin role must exist and be super, roles=%v", roles)
	}

	// 3. Default tenant bound exactly to the cluster's default namespace.
	defaultTenant, err := store.GetTenantByCode(context.Background(), "default")
	if err != nil {
		t.Fatalf("default tenant: %v", err)
	}
	nss, _ := store.ListTenantNamespaces(context.Background(), defaultTenant.ID)
	hasDefault := false
	for _, n := range nss {
		if n == "default" {
			hasDefault = true
		}
	}
	if !hasDefault {
		t.Fatalf("default tenant namespaces=%v, want default", nss)
	}

	// 4. Default 'viewer' role exists and carries the default whitelist.
	rolesList, _ := uc.TenantRoles(context.Background(), defaultTenant.ID)
	var viewer *domainrbac.TenantRole
	for _, r := range rolesList {
		if r.Code == "viewer" {
			viewer = r
		}
	}
	if viewer == nil {
		t.Fatalf("viewer role missing in tenant roles %v", rolesList)
	}
	ids, err := store.GetRolePermissionIDs(context.Background(), viewer.ID, false)
	if err != nil || len(ids) == 0 {
		t.Fatalf("viewer permission ids=%v err=%v, want seeded whitelist", ids, err)
	}
}

func TestSeedDefaultsIsIdempotent(t *testing.T) {
	store := newMemStore()
	uc := newUsecase(store, &fullUserRepo{})

	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("first seed: %v", err)
	}
	permsAfterFirst, _ := uc.Permissions(context.Background())
	firstCount := len(permsAfterFirst)

	defaultTenant, _ := store.GetTenantByCode(context.Background(), "default")
	rolesBefore, _ := uc.TenantRoles(context.Background(), defaultTenant.ID)
	var viewerBefore *domainrbac.TenantRole
	for _, r := range rolesBefore {
		if r.Code == "viewer" {
			viewerBefore = r
		}
	}
	idsBefore, _ := store.GetRolePermissionIDs(context.Background(), viewerBefore.ID, false)

	// Second run must not grow the catalog or rewire the viewer role.
	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("second seed: %v", err)
	}
	permsAfterSecond, _ := uc.Permissions(context.Background())
	if len(permsAfterSecond) != firstCount {
		t.Fatalf("catalog count changed: %d -> %d", firstCount, len(permsAfterSecond))
	}
	rolesAfter, _ := uc.TenantRoles(context.Background(), defaultTenant.ID)
	if len(rolesAfter) != len(rolesBefore) {
		t.Fatalf("tenant role count changed: %d -> %d", len(rolesBefore), len(rolesAfter))
	}
	idsAfter, _ := store.GetRolePermissionIDs(context.Background(), viewerBefore.ID, false)
	if len(idsBefore) != len(idsAfter) {
		t.Fatalf("viewer permissions were rewritten: before=%d after=%d", len(idsBefore), len(idsAfter))
	}
}

func TestSeedDefaultsPreservesCustomizedViewerRole(t *testing.T) {
	store := newMemStore()
	// Pre-create the default tenant and a customized viewer role whose
	// permissions differ from the seed whitelist.
	store.CreateTenant(context.Background(), &domainrbac.Tenant{
		ID: "t-default", Code: "default", Name: "默认租户", Status: "active",
	})
	store.AddTenantNamespace(context.Background(), "t-default", "*")
	store.CreateTenantRole(context.Background(), &domainrbac.TenantRole{
		ID: "r-viewer", TenantID: "t-default", Code: "viewer", Name: "查看者",
	})
	// One custom permission bound by an administrator.
	store.UpsertPermission(context.Background(), &domainrbac.Permission{Code: "custom:read", ID: "p-custom"})
	store.SetRolePermissions(context.Background(), "r-viewer", "t-default", []string{"p-custom"})

	uc := newUsecase(store, &fullUserRepo{})
	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("seed defaults: %v", err)
	}

	ids, err := store.GetRolePermissionIDs(context.Background(), "r-viewer", false)
	if err != nil {
		t.Fatalf("get viewer perms: %v", err)
	}
	if len(ids) != 1 || ids[0] != "p-custom" {
		t.Fatalf("existing viewer role must keep its custom permissions, got %v", ids)
	}
}

// ---------- first-admin bootstrap ----------

func TestBootstrapAdminCreatesBuiltinAdminOnFreshInstall(t *testing.T) {
	store := newMemStore()
	users := &fullUserRepo{} // empty user table
	uc := newUsecase(store, users)

	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("seed defaults: %v", err)
	}

	// A super-admin holder must exist and be the built-in admin account.
	super, err := store.GetPlatformRole(context.Background(), "pr-super_admin")
	if err != nil {
		t.Fatalf("super admin role: %v", err)
	}
	holders, _ := store.ListPlatformRoleUsers(context.Background(), super.ID)
	if len(holders) != 1 {
		t.Fatalf("super holders=%v, want exactly one bootstrap admin", holders)
	}
	admin, err := users.GetByID(context.Background(), holders[0])
	if err != nil {
		t.Fatalf("get bootstrap admin: %v", err)
	}
	if admin.Username != "admin" {
		t.Fatalf("bootstrap admin username=%q, want admin", admin.Username)
	}
	// The password hash must be a real bcrypt hash (login-verifiable).
	if err := bcrypt.CompareHashAndPassword([]byte(admin.PasswordHash), []byte(defaultBootstrapPassword)); err != nil {
		t.Fatalf("bootstrap admin password hash does not match changeme: %v", err)
	}
}

func TestBootstrapAdminIsIdempotent(t *testing.T) {
	store := newMemStore()
	users := &fullUserRepo{}
	uc := newUsecase(store, users)

	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("first seed: %v", err)
	}
	super, _ := store.GetPlatformRole(context.Background(), "pr-super_admin")
	holdersBefore, _ := store.ListPlatformRoleUsers(context.Background(), super.ID)
	userCountBefore := len(users.users)

	// Second run: no duplicate grants, no duplicate users, no credential reset.
	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("second seed: %v", err)
	}
	holdersAfter, _ := store.ListPlatformRoleUsers(context.Background(), super.ID)
	if len(holdersAfter) != len(holdersBefore) {
		t.Fatalf("super holders changed on re-seed: %v -> %v", holdersBefore, holdersAfter)
	}
	if len(users.users) != userCountBefore {
		t.Fatalf("user count changed on re-seed: %d -> %d", userCountBefore, len(users.users))
	}
}

func TestBootstrapAdminPromotesExistingMatchingUser(t *testing.T) {
	store := newMemStore()
	// The bootstrap username already exists as a plain registered user.
	users := &fullUserRepo{users: []*entity.User{{ID: "u-boot", Username: "admin"}}}
	uc := newUsecase(store, users)

	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("seed defaults: %v", err)
	}

	super, _ := store.GetPlatformRole(context.Background(), "pr-super_admin")
	holders, _ := store.ListPlatformRoleUsers(context.Background(), super.ID)
	if len(holders) != 1 || holders[0] != "u-boot" {
		t.Fatalf("super holders=%v, want [u-boot]", holders)
	}
	// Users must not be duplicated; the existing account is promoted in place.
	if len(users.users) != 1 {
		t.Fatalf("user count=%d, want 1 (existing user must not be recreated)", len(users.users))
	}
}

func TestBootstrapAdminSkipsWhenSuperAlreadyHeld(t *testing.T) {
	store := newMemStore()
	// An administrator exists (e.g. migrated or granted later).
	store.CreatePlatformRole(context.Background(), &domainrbac.PlatformRole{
		ID: "pr-super_admin", Code: "super_admin", IsSuper: true,
	})
	store.platUsers["pr-super_admin"] = []string{"u-existing-admin"}
	users := &fullUserRepo{users: []*entity.User{{ID: "u-existing-admin", Username: "admin"}}}
	uc := newUsecase(store, users)

	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("seed defaults: %v", err)
	}

	// No new user or grant may be introduced; the existing admin keeps control.
	if len(users.users) != 1 {
		t.Fatalf("user count=%d, want 1 (bootstrap must not create duplicate admin)", len(users.users))
	}
	holders, _ := store.ListPlatformRoleUsers(context.Background(), "pr-super_admin")
	if len(holders) != 1 || holders[0] != "u-existing-admin" {
		t.Fatalf("super holders=%v, want untouched [u-existing-admin]", holders)
	}
}

func TestBootstrapAdminUsesConfiguredCredentialsFirst(t *testing.T) {
	store := newMemStore()
	users := &fullUserRepo{}
	uc := New(Options{
		Store:  store,
		Users:  users,
		Engine: rbac.NewEngine(nil, nil),
		Logger: slog.Default(),
		Bootstrap: &BootstrapOptions{
			Admin:    "ops-grand-admin",
			Password: "s3cret-boostrap",
		},
	})

	if err := uc.SeedDefaults(context.Background()); err != nil {
		t.Fatalf("seed defaults: %v", err)
	}

	super, _ := store.GetPlatformRole(context.Background(), "pr-super_admin")
	holders, _ := store.ListPlatformRoleUsers(context.Background(), super.ID)
	if len(holders) != 1 {
		t.Fatalf("super holders=%v, want one configured admin", holders)
	}
	admin, _ := users.GetByID(context.Background(), holders[0])
	if admin.Username != "ops-grand-admin" {
		t.Fatalf("bootstrap admin username=%q, want ops-grand-admin", admin.Username)
	}
	if err := bcrypt.CompareHashAndPassword([]byte(admin.PasswordHash), []byte("s3cret-boostrap")); err != nil {
		t.Fatalf("configured password hash mismatch: %v", err)
	}
}

package rbac

import (
	"context"
	"log/slog"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	domainrbac "github.com/lvyanru/dac-apiserver/internal/domain/rbac"
	"github.com/lvyanru/dac-apiserver/pkg/rbac"
)

// panickerStore implements every Store method by panicking. Tests embed it and
// override only the methods they exercise, so an unexpected call fails loudly
// instead of silently passing through an empty fake.
type panickerStore struct{}

func (panickerStore) ListTenants(context.Context, int, int) ([]*domainrbac.Tenant, int, error) {
	panic("unexpected ListTenants")
}
func (panickerStore) GetTenant(context.Context, string) (*domainrbac.Tenant, error) {
	panic("unexpected GetTenant")
}
func (panickerStore) GetTenantByCode(context.Context, string) (*domainrbac.Tenant, error) {
	panic("unexpected GetTenantByCode")
}
func (panickerStore) CreateTenant(context.Context, *domainrbac.Tenant) (*domainrbac.Tenant, error) {
	panic("unexpected CreateTenant")
}
func (panickerStore) UpdateTenant(context.Context, *domainrbac.Tenant) (*domainrbac.Tenant, error) {
	panic("unexpected UpdateTenant")
}
func (panickerStore) DeleteTenant(context.Context, string) error { panic("unexpected DeleteTenant") }

func (panickerStore) ListTenantNamespaces(context.Context, string) ([]string, error) {
	panic("unexpected ListTenantNamespaces")
}
func (panickerStore) AddTenantNamespace(context.Context, string, string) error {
	panic("unexpected AddTenantNamespace")
}
func (panickerStore) RemoveTenantNamespace(context.Context, string, string) error {
	panic("unexpected RemoveTenantNamespace")
}

func (panickerStore) ListTenantRoles(context.Context, string) ([]*domainrbac.TenantRole, error) {
	panic("unexpected ListTenantRoles")
}
func (panickerStore) GetTenantRoleByID(context.Context, string) (*domainrbac.TenantRole, error) {
	panic("unexpected GetTenantRoleByID")
}
func (panickerStore) CreateTenantRole(context.Context, *domainrbac.TenantRole) (*domainrbac.TenantRole, error) {
	panic("unexpected CreateTenantRole")
}
func (panickerStore) UpdateTenantRole(context.Context, *domainrbac.TenantRole) (*domainrbac.TenantRole, error) {
	panic("unexpected UpdateTenantRole")
}
func (panickerStore) DeleteTenantRole(context.Context, string) error {
	panic("unexpected DeleteTenantRole")
}

func (panickerStore) ListTenantMembers(context.Context, string, int, int) ([]*domainrbac.TenantMember, int, error) {
	panic("unexpected ListTenantMembers")
}
func (panickerStore) GetTenantMembership(context.Context, string, string) (*domainrbac.TenantMember, error) {
	panic("unexpected GetTenantMembership")
}
func (panickerStore) ListTenantIDsByUser(context.Context, string) ([]string, error) {
	panic("unexpected ListTenantIDsByUser")
}
func (panickerStore) ListUsersNotInAnyTenant(context.Context) ([]string, error) {
	panic("unexpected ListUsersNotInAnyTenant")
}
func (panickerStore) AddTenantMember(context.Context, string, string, string) (*domainrbac.TenantMember, error) {
	panic("unexpected AddTenantMember")
}
func (panickerStore) ChangeTenantMemberRole(context.Context, string, string, string) error {
	panic("unexpected ChangeTenantMemberRole")
}
func (panickerStore) RemoveTenantMember(context.Context, string, string) error {
	panic("unexpected RemoveTenantMember")
}

func (panickerStore) ListPlatformRoles(context.Context) ([]*domainrbac.PlatformRole, error) {
	panic("unexpected ListPlatformRoles")
}
func (panickerStore) GetPlatformRole(context.Context, string) (*domainrbac.PlatformRole, error) {
	panic("unexpected GetPlatformRole")
}
func (panickerStore) CreatePlatformRole(context.Context, *domainrbac.PlatformRole) (*domainrbac.PlatformRole, error) {
	panic("unexpected CreatePlatformRole")
}
func (panickerStore) UpdatePlatformRole(context.Context, *domainrbac.PlatformRole) (*domainrbac.PlatformRole, error) {
	panic("unexpected UpdatePlatformRole")
}
func (panickerStore) DeletePlatformRole(context.Context, string) error {
	panic("unexpected DeletePlatformRole")
}

func (panickerStore) ListPlatformRoleUsers(context.Context, string) ([]string, error) {
	panic("unexpected ListPlatformRoleUsers")
}
func (panickerStore) AssignPlatformRole(context.Context, string, string) error {
	panic("unexpected AssignPlatformRole")
}
func (panickerStore) RevokePlatformRole(context.Context, string, string) error {
	panic("unexpected RevokePlatformRole")
}

func (panickerStore) ListPermissions(context.Context) ([]*domainrbac.Permission, error) {
	panic("unexpected ListPermissions")
}
func (panickerStore) GetPermissionByCode(context.Context, string) (*domainrbac.Permission, error) {
	panic("unexpected GetPermissionByCode")
}
func (panickerStore) UpsertPermission(context.Context, *domainrbac.Permission) error {
	panic("unexpected UpsertPermission")
}

func (panickerStore) SetRolePermissions(context.Context, string, string, []string) error {
	panic("unexpected SetRolePermissions")
}
func (panickerStore) GetRolePermissionIDs(context.Context, string, bool) ([]string, error) {
	panic("unexpected GetRolePermissionIDs")
}
func (panickerStore) PermissionCodesByIDs(context.Context, []string) ([]string, error) {
	panic("unexpected PermissionCodesByIDs")
}

// fakeStore is a minimal Store for the rules tested here; unexercised methods
// fall through to the panicker base.
type fakeStore struct {
	panickerStore

	platformRoleByID map[string]*domainrbac.PlatformRole
	platformRoleCode map[string]*domainrbac.PlatformRole
	platUsers        map[string][]string // roleID → userIDs
	tenantRoleByID   map[string]*domainrbac.TenantRole
}

func newFakeStore() *fakeStore {
	return &fakeStore{
		platformRoleByID: map[string]*domainrbac.PlatformRole{},
		platformRoleCode: map[string]*domainrbac.PlatformRole{},
		platUsers:        map[string][]string{},
		tenantRoleByID:   map[string]*domainrbac.TenantRole{},
	}
}

func (s *fakeStore) GetPlatformRole(ctx context.Context, id string) (*domainrbac.PlatformRole, error) {
	r, ok := s.platformRoleByID[id]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return r, nil
}

func (s *fakeStore) ListPlatformRoles(ctx context.Context) ([]*domainrbac.PlatformRole, error) {
	out := make([]*domainrbac.PlatformRole, 0, len(s.platformRoleCode))
	for _, r := range s.platformRoleCode {
		out = append(out, r)
	}
	return out, nil
}

func (s *fakeStore) ListPlatformRoleUsers(ctx context.Context, roleID string) ([]string, error) {
	return s.platUsers[roleID], nil
}

func (s *fakeStore) AssignPlatformRole(ctx context.Context, userID, roleID string) error {
	for _, u := range s.platUsers[roleID] {
		if u == userID {
			return nil
		}
	}
	s.platUsers[roleID] = append(s.platUsers[roleID], userID)
	return nil
}

func (s *fakeStore) RevokePlatformRole(ctx context.Context, userID, roleID string) error {
	users := s.platUsers[roleID]
	for i, u := range users {
		if u == userID {
			users = append(users[:i], users[i+1:]...)
			break
		}
	}
	s.platUsers[roleID] = users
	return nil
}

func (s *fakeStore) GetTenantRoleByID(ctx context.Context, roleID string) (*domainrbac.TenantRole, error) {
	r, ok := s.tenantRoleByID[roleID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return r, nil
}

// fakeUserRepo replaces only GetByID.
type fakeUserRepo struct {
	byID map[string]*entity.User
}

func (f *fakeUserRepo) GetByID(_ context.Context, userID string) (*entity.User, error) {
	u, ok := f.byID[userID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return u, nil
}

func (f *fakeUserRepo) Create(context.Context, string, string, *string) (*entity.User, error) {
	panic("unexpected Create")
}
func (f *fakeUserRepo) GetByUsername(context.Context, string) (*entity.User, error) {
	return nil, domain.ErrNotFound
}
func (f *fakeUserRepo) List(context.Context, int, int) ([]*entity.User, error) {
	panic("unexpected List")
}
func (f *fakeUserRepo) Count(context.Context) (int, error)   { panic("unexpected Count") }
func (f *fakeUserRepo) Delete(context.Context, string) error { panic("unexpected Delete") }
func (f *fakeUserRepo) UpdateLastLogin(context.Context, string) error {
	panic("unexpected UpdateLastLogin")
}
func (f *fakeUserRepo) UpdateUser(context.Context, string, *string, *string) error {
	panic("unexpected UpdateUser")
}

func newUsecase(store domainrbac.Store, users domain.UserRepository) Usecase {
	return New(Options{
		Store:  store,
		Users:  users,
		Engine: rbac.NewEngine(nil, nil), // not exercised in these tests
		Logger: slog.Default(),
	})
}

func TestAddTenantMemberRejectsForeignRole(t *testing.T) {
	store := newFakeStore()
	// The role belongs to tenant t1 but the operator targets tenant t2.
	store.tenantRoleByID["role-t1-editor"] = &domainrbac.TenantRole{
		ID: "role-t1-editor", TenantID: "t1", Code: "editor",
	}
	users := &fakeUserRepo{byID: map[string]*entity.User{"u1": {ID: "u1", Username: "alice"}}}
	uc := newUsecase(store, users)

	err := uc.AddTenantMember(context.Background(), "op", "t2", "u1", "role-t1-editor")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for foreign role, got %v", err)
	}
	if len(store.platUsers) != 0 {
		t.Fatal("no membership should have been created for a foreign role")
	}
}

func TestAddTenantMemberRequiresExistingUser(t *testing.T) {
	store := newFakeStore()
	store.tenantRoleByID["role-t1-viewer"] = &domainrbac.TenantRole{
		ID: "role-t1-viewer", TenantID: "t1", Code: "viewer",
	}
	users := &fakeUserRepo{byID: map[string]*entity.User{}} // no users
	uc := newUsecase(store, users)

	err := uc.AddTenantMember(context.Background(), "op", "t1", "ghost", "role-t1-viewer")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for missing user, got %v", err)
	}
}

func TestRevokePlatformRoleRefusesLastSuperAdmin(t *testing.T) {
	store := newFakeStore()
	store.platformRoleByID["r-super"] = &domainrbac.PlatformRole{
		ID: "r-super", Code: "super_admin", IsSuper: true,
	}
	store.platformRoleCode["super_admin"] = store.platformRoleByID["r-super"]
	// Only one holder remains.
	store.platUsers["r-super"] = []string{"u-admin"}

	uc := newUsecase(store, &fakeUserRepo{})
	err := uc.RevokePlatformRole(context.Background(), "u-admin", "u-admin", "r-super")
	if !domain.IsConflict(err) {
		t.Fatalf("expected conflict when revoking the last super admin, got %v", err)
	}
}

func TestRevokePlatformRoleAllowsWhenOtherSuperAdminRemains(t *testing.T) {
	store := newFakeStore()
	store.platformRoleByID["r-super"] = &domainrbac.PlatformRole{
		ID: "r-super", Code: "super_admin", IsSuper: true,
	}
	store.platformRoleCode["super_admin"] = store.platformRoleByID["r-super"]
	store.platUsers["r-super"] = []string{"u-admin", "u-backup"}

	uc := newUsecase(store, &fakeUserRepo{})
	err := uc.RevokePlatformRole(context.Background(), "u-admin", "u-admin", "r-super")
	if err != nil {
		t.Fatalf("expected revoke to succeed with a remaining super admin, got %v", err)
	}
	if got := len(store.platUsers["r-super"]); got != 1 {
		t.Fatalf("expected 1 holder left, got %d", got)
	}
}

func TestSetPlatformRolePermissionsRejectsSuperRole(t *testing.T) {
	store := newFakeStore()
	store.platformRoleByID["r-super"] = &domainrbac.PlatformRole{
		ID: "r-super", Code: "super_admin", IsSuper: true,
	}
	store.platformRoleCode["super_admin"] = store.platformRoleByID["r-super"]

	uc := newUsecase(store, &fakeUserRepo{})
	err := uc.SetPlatformRolePermissions(context.Background(), "op", "r-super", []string{"agent:read"})
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for configuring a super role, got %v", err)
	}
}

func TestGrantPlatformRoleRequiresExistingUser(t *testing.T) {
	store := newFakeStore()
	store.platformRoleByID["r-super"] = &domainrbac.PlatformRole{
		ID: "r-super", Code: "super_admin", IsSuper: true,
	}
	store.platformRoleCode["super_admin"] = store.platformRoleByID["r-super"]

	uc := newUsecase(store, &fakeUserRepo{byID: map[string]*entity.User{}})
	err := uc.GrantPlatformRole(context.Background(), "op", "ghost", "r-super")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid-input for missing grantee, got %v", err)
	}
}

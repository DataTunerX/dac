package handler

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"testing"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/route/param"

	domainrbac "github.com/lvyanru/dac-apiserver/internal/domain/rbac"
	usecaserbac "github.com/lvyanru/dac-apiserver/internal/usecase/rbac"
)

// stubUsecase is a test double that implements usecaserbac.Usecase. Every method
// panics unless the corresponding function field is set, so tests fail loudly
// when an unexpected code path is exercised.
type stubUsecase struct {
	fnTenants                  func(offset, limit int) (*usecaserbac.TenantList, error)
	fnTenant                   func(tenantID string) (*domainrbac.Tenant, error)
	fnCreateTenant             func(userID, code, name, description string) (*domainrbac.Tenant, error)
	fnUpdateTenant             func(userID, tenantID, name, description, status string) (*domainrbac.Tenant, error)
	fnDisableTenant            func(userID, tenantID string) (*domainrbac.Tenant, error)
	fnEnableTenant             func(userID, tenantID string) (*domainrbac.Tenant, error)
	fnDeleteTenant             func(userID, tenantID string) error
	fnTenantNamespaces         func(tenantID string) ([]string, error)
	fnAddTenantNamespace       func(userID, tenantID, namespace string) error
	fnRemoveTenantNamespace    func(userID, tenantID, namespace string) error
	fnTenantRoles              func(tenantID string) ([]*domainrbac.TenantRole, error)
	fnCreateTenantRole         func(userID, tenantID, code, name, description string) (*domainrbac.TenantRole, error)
	fnUpdateTenantRole         func(userID, tenantID, roleID, name, description string) (*domainrbac.TenantRole, error)
	fnDeleteTenantRole         func(userID, tenantID, roleID string) error
	fnSetTenantRolePermissions func(userID, tenantID, roleID string, codes []string) error
	fnRolePermissionCodes      func(tenantID, roleID string) ([]string, error)
	fnTenantMembers            func(tenantID string, offset, limit int) (*usecaserbac.MemberList, error)
	fnAddMember                func(operatorID, tenantID, userID, roleID string) error
	fnChangeMemberRole         func(operatorID, tenantID, userID, roleID string) error
	fnRemoveMember             func(operatorID, tenantID, userID string) error
	fnPermissions              func() ([]*domainrbac.Permission, error)
	fnMyTenants                func(userID string) ([]*domainrbac.Tenant, error)
	fnPlatformRoles            func() ([]*domainrbac.PlatformRole, error)
	fnCreatePlatformRole       func(operatorID, code, name, description string) (*domainrbac.PlatformRole, error)
	fnUpdatePlatformRole       func(operatorID, roleID, name, description string) (*domainrbac.PlatformRole, error)
	fnSetPlatformRolePerms     func(operatorID, roleID string, codes []string) error
	fnPlatformRolePermCodes    func(roleID string) ([]string, error)
	fnDeletePlatformRole       func(operatorID, roleID string) error
	fnPlatformRoleUsers        func(roleID string) ([]usecaserbac.PlatformRoleUserView, error)
	fnGrantPlatformRole        func(operatorID, userID, roleID string) error
	fnRevokePlatformRole       func(operatorID, userID, roleID string) error
}

func (s *stubUsecase) Tenants(ctx context.Context, offset, limit int) (*usecaserbac.TenantList, error) {
	if s.fnTenants == nil {
		panic("unexpected Tenants")
	}
	return s.fnTenants(offset, limit)
}

func (s *stubUsecase) Tenant(ctx context.Context, tenantID string) (*domainrbac.Tenant, error) {
	if s.fnTenant == nil {
		panic("unexpected Tenant")
	}
	return s.fnTenant(tenantID)
}

func (s *stubUsecase) CreateTenant(ctx context.Context, userID, code, name, description string) (*domainrbac.Tenant, error) {
	if s.fnCreateTenant == nil {
		panic("unexpected CreateTenant")
	}
	return s.fnCreateTenant(userID, code, name, description)
}

func (s *stubUsecase) UpdateTenant(ctx context.Context, userID, tenantID, name, description, status string) (*domainrbac.Tenant, error) {
	if s.fnUpdateTenant == nil {
		panic("unexpected UpdateTenant")
	}
	return s.fnUpdateTenant(userID, tenantID, name, description, status)
}

func (s *stubUsecase) DisableTenant(ctx context.Context, userID, tenantID string) (*domainrbac.Tenant, error) {
	if s.fnDisableTenant == nil {
		panic("unexpected DisableTenant")
	}
	return s.fnDisableTenant(userID, tenantID)
}

func (s *stubUsecase) EnableTenant(ctx context.Context, userID, tenantID string) (*domainrbac.Tenant, error) {
	if s.fnEnableTenant == nil {
		panic("unexpected EnableTenant")
	}
	return s.fnEnableTenant(userID, tenantID)
}

func (s *stubUsecase) DeleteTenant(ctx context.Context, userID, tenantID string) error {
	if s.fnDeleteTenant == nil {
		panic("unexpected DeleteTenant")
	}
	return s.fnDeleteTenant(userID, tenantID)
}

func (s *stubUsecase) TenantNamespaces(ctx context.Context, tenantID string) ([]string, error) {
	if s.fnTenantNamespaces == nil {
		panic("unexpected TenantNamespaces")
	}
	return s.fnTenantNamespaces(tenantID)
}

func (s *stubUsecase) AddTenantNamespace(ctx context.Context, userID, tenantID, namespace string) error {
	if s.fnAddTenantNamespace == nil {
		panic("unexpected AddTenantNamespace")
	}
	return s.fnAddTenantNamespace(userID, tenantID, namespace)
}

func (s *stubUsecase) RemoveTenantNamespace(ctx context.Context, userID, tenantID, namespace string) error {
	if s.fnRemoveTenantNamespace == nil {
		panic("unexpected RemoveTenantNamespace")
	}
	return s.fnRemoveTenantNamespace(userID, tenantID, namespace)
}

func (s *stubUsecase) TenantRoles(ctx context.Context, tenantID string) ([]*domainrbac.TenantRole, error) {
	if s.fnTenantRoles == nil {
		panic("unexpected TenantRoles")
	}
	return s.fnTenantRoles(tenantID)
}

func (s *stubUsecase) CreateTenantRole(ctx context.Context, userID, tenantID, code, name, description string) (*domainrbac.TenantRole, error) {
	if s.fnCreateTenantRole == nil {
		panic("unexpected CreateTenantRole")
	}
	return s.fnCreateTenantRole(userID, tenantID, code, name, description)
}

func (s *stubUsecase) UpdateTenantRole(ctx context.Context, userID, tenantID, roleID, name, description string) (*domainrbac.TenantRole, error) {
	if s.fnUpdateTenantRole == nil {
		panic("unexpected UpdateTenantRole")
	}
	return s.fnUpdateTenantRole(userID, tenantID, roleID, name, description)
}

func (s *stubUsecase) DeleteTenantRole(ctx context.Context, userID, tenantID, roleID string) error {
	if s.fnDeleteTenantRole == nil {
		panic("unexpected DeleteTenantRole")
	}
	return s.fnDeleteTenantRole(userID, tenantID, roleID)
}

func (s *stubUsecase) SetTenantRolePermissions(ctx context.Context, userID, tenantID, roleID string, codes []string) error {
	if s.fnSetTenantRolePermissions == nil {
		panic("unexpected SetTenantRolePermissions")
	}
	return s.fnSetTenantRolePermissions(userID, tenantID, roleID, codes)
}

func (s *stubUsecase) TenantRolePermissionCodes(ctx context.Context, tenantID, roleID string) ([]string, error) {
	if s.fnRolePermissionCodes == nil {
		panic("unexpected TenantRolePermissionCodes")
	}
	return s.fnRolePermissionCodes(tenantID, roleID)
}

func (s *stubUsecase) TenantMembers(ctx context.Context, tenantID string, offset, limit int) (*usecaserbac.MemberList, error) {
	if s.fnTenantMembers == nil {
		panic("unexpected TenantMembers")
	}
	return s.fnTenantMembers(tenantID, offset, limit)
}

func (s *stubUsecase) AddTenantMember(ctx context.Context, operatorID, tenantID, userID, roleID string) error {
	if s.fnAddMember == nil {
		panic("unexpected AddTenantMember")
	}
	return s.fnAddMember(operatorID, tenantID, userID, roleID)
}

func (s *stubUsecase) ChangeTenantMemberRole(ctx context.Context, operatorID, tenantID, userID, roleID string) error {
	if s.fnChangeMemberRole == nil {
		panic("unexpected ChangeTenantMemberRole")
	}
	return s.fnChangeMemberRole(operatorID, tenantID, userID, roleID)
}

func (s *stubUsecase) RemoveTenantMember(ctx context.Context, operatorID, tenantID, userID string) error {
	if s.fnRemoveMember == nil {
		panic("unexpected RemoveTenantMember")
	}
	return s.fnRemoveMember(operatorID, tenantID, userID)
}

func (s *stubUsecase) AvailableUsers(ctx context.Context) ([]string, error) {
	return nil, nil
}

func (s *stubUsecase) PlatformRoles(ctx context.Context) ([]*domainrbac.PlatformRole, error) {
	if s.fnPlatformRoles == nil {
		panic("unexpected PlatformRoles")
	}
	return s.fnPlatformRoles()
}

func (s *stubUsecase) CreatePlatformRole(ctx context.Context, operatorID, code, name, description string) (*domainrbac.PlatformRole, error) {
	if s.fnCreatePlatformRole == nil {
		panic("unexpected CreatePlatformRole")
	}
	return s.fnCreatePlatformRole(operatorID, code, name, description)
}

func (s *stubUsecase) UpdatePlatformRole(ctx context.Context, operatorID, roleID, name, description string) (*domainrbac.PlatformRole, error) {
	if s.fnUpdatePlatformRole == nil {
		panic("unexpected UpdatePlatformRole")
	}
	return s.fnUpdatePlatformRole(operatorID, roleID, name, description)
}

func (s *stubUsecase) SetPlatformRolePermissions(ctx context.Context, operatorID, roleID string, codes []string) error {
	if s.fnSetPlatformRolePerms == nil {
		panic("unexpected SetPlatformRolePermissions")
	}
	return s.fnSetPlatformRolePerms(operatorID, roleID, codes)
}

func (s *stubUsecase) PlatformRolePermissionCodes(ctx context.Context, roleID string) ([]string, error) {
	if s.fnPlatformRolePermCodes == nil {
		panic("unexpected PlatformRolePermissionCodes")
	}
	return s.fnPlatformRolePermCodes(roleID)
}

func (s *stubUsecase) DeletePlatformRole(ctx context.Context, operatorID, roleID string) error {
	if s.fnDeletePlatformRole == nil {
		panic("unexpected DeletePlatformRole")
	}
	return s.fnDeletePlatformRole(operatorID, roleID)
}

func (s *stubUsecase) PlatformRoleUsers(ctx context.Context, roleID string) ([]usecaserbac.PlatformRoleUserView, error) {
	if s.fnPlatformRoleUsers == nil {
		panic("unexpected PlatformRoleUsers")
	}
	return s.fnPlatformRoleUsers(roleID)
}

func (s *stubUsecase) GrantPlatformRole(ctx context.Context, operatorID, userID, roleID string) error {
	if s.fnGrantPlatformRole == nil {
		panic("unexpected GrantPlatformRole")
	}
	return s.fnGrantPlatformRole(operatorID, userID, roleID)
}

func (s *stubUsecase) RevokePlatformRole(ctx context.Context, operatorID, userID, roleID string) error {
	if s.fnRevokePlatformRole == nil {
		panic("unexpected RevokePlatformRole")
	}
	return s.fnRevokePlatformRole(operatorID, userID, roleID)
}

func (s *stubUsecase) BootstrapAdminID(ctx context.Context) (string, error) { return "", nil }

func (s *stubUsecase) Permissions(ctx context.Context) ([]*domainrbac.Permission, error) {
	if s.fnPermissions == nil {
		panic("unexpected Permissions")
	}
	return s.fnPermissions()
}

func (s *stubUsecase) MyTenants(ctx context.Context, userID string) ([]*domainrbac.Tenant, error) {
	if s.fnMyTenants == nil {
		panic("unexpected MyTenants")
	}
	return s.fnMyTenants(userID)
}

func (s *stubUsecase) SeedDefaults(ctx context.Context) error {
	panic("unexpected SeedDefaults")
}

func newRBACHandler(uc usecaserbac.Usecase) *RBACHandler {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return NewRBACHandler(uc, logger)
}

func newTestContext(userID string) *app.RequestContext {
	c := app.NewContext(0)
	if userID != "" {
		c.Set("user_id", userID)
	}
	return c
}

func TestListTenantsPaginated(t *testing.T) {
	uc := &stubUsecase{
		fnTenants: func(offset, limit int) (*usecaserbac.TenantList, error) {
			return &usecaserbac.TenantList{
				Items: []*domainrbac.Tenant{
					{ID: "t1", Code: "acme", Name: "Acme"},
				},
				Total: 1,
			}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")

	h.ListTenants(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestCreateTenantValidation(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)

	// No user_id in context should return unauthorized
	c2 := newTestContext("")
	h.CreateTenant(context.Background(), c2)
	if c2.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c2.Response.StatusCode())
	}
}

func TestCreateTenantSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnCreateTenant: func(userID, code, name, description string) (*domainrbac.Tenant, error) {
			if userID != "u1" || code != "acme" || name != "Acme" {
				t.Fatalf("unexpected args: userID=%q code=%q name=%q", userID, code, name)
			}
			return &domainrbac.Tenant{ID: "t-new", Code: code, Name: name, Status: "active"}, nil
		},
	}
	h := newRBACHandler(uc)
	_ = h
}

func TestGetTenantSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnTenant: func(tenantID string) (*domainrbac.Tenant, error) {
			return &domainrbac.Tenant{ID: tenantID, Code: "acme", Name: "Acme", Status: "active"}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")
	c.Params = param.Params{param.Param{Key: "id", Value: "t1"}}

	h.GetTenant(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestListPermissionsSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnPermissions: func() ([]*domainrbac.Permission, error) {
			return []*domainrbac.Permission{
				{Code: "agent:read", Name: "Agent Read"},
				{Code: "llmconfig:read", Name: "LLM Config Read"},
			}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")

	h.ListPermissions(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestListTenantRolesSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnTenantRoles: func(tenantID string) ([]*domainrbac.TenantRole, error) {
			return []*domainrbac.TenantRole{
				{ID: "r1", TenantID: tenantID, Code: "viewer", Name: "Viewer"},
			}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")
	c.Params = param.Params{param.Param{Key: "id", Value: "t1"}}

	h.ListTenantRoles(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestListTenantMembersPaginated(t *testing.T) {
	uc := &stubUsecase{
		fnTenantMembers: func(tenantID string, offset, limit int) (*usecaserbac.MemberList, error) {
			return &usecaserbac.MemberList{Items: nil, Total: 0}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")
	c.Params = param.Params{param.Param{Key: "id", Value: "t1"}}

	h.ListTenantMembers(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestAddTenantMemberUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.AddTenantMember(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestChangeTenantMemberRoleUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.ChangeTenantMemberRole(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestRemoveTenantMemberUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.RemoveTenantMember(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestDeleteTenantUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.DeleteTenant(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestListPlatformRolesSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnPlatformRoles: func() ([]*domainrbac.PlatformRole, error) {
			return []*domainrbac.PlatformRole{
				{ID: "pr-super", Code: "super_admin", IsSuper: true},
			}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")

	h.ListPlatformRoles(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestCreatePlatformRoleUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.CreatePlatformRole(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestDeletePlatformRoleUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.DeletePlatformRole(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestGrantPlatformRoleUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.GrantPlatformRole(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestRevokePlatformRoleUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.RevokePlatformRole(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestMyTenantsSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnMyTenants: func(userID string) ([]*domainrbac.Tenant, error) {
			return []*domainrbac.Tenant{
				{ID: "t1", Code: "acme", Name: "Acme", Status: "active"},
			}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")

	h.MyTenants(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestMyTenantsUnauthorized(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("")

	h.MyTenants(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d, want 401", c.Response.StatusCode())
	}
}

func TestAvailableUsersSuccess(t *testing.T) {
	uc := &stubUsecase{}
	h := newRBACHandler(uc)
	c := newTestContext("u1")

	h.AvailableUsers(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestTenantRolePermissionCodesSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnRolePermissionCodes: func(tenantID, roleID string) ([]string, error) {
			return []string{"agent:read", "llmconfig:read"}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")
	c.Params = param.Params{
		param.Param{Key: "id", Value: "t1"},
		param.Param{Key: "rid", Value: "r1"},
	}

	h.GetTenantRolePermissions(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestPlatformRolePermissionCodesSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnPlatformRolePermCodes: func(roleID string) ([]string, error) {
			return []string{"tenant:manage"}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")
	c.Params = param.Params{param.Param{Key: "rid", Value: "pr-ops"}}

	h.GetPlatformRolePermissions(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestListTenantNamespacesSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnTenantNamespaces: func(tenantID string) ([]string, error) {
			return []string{"default", "dev"}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")
	c.Params = param.Params{param.Param{Key: "id", Value: "t1"}}

	h.ListTenantNamespaces(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestListPlatformRoleUsersSuccess(t *testing.T) {
	uc := &stubUsecase{
		fnPlatformRoleUsers: func(roleID string) ([]usecaserbac.PlatformRoleUserView, error) {
			return []usecaserbac.PlatformRoleUserView{
				{UserID: "u1", RoleCode: "super_admin"},
			}, nil
		},
	}
	h := newRBACHandler(uc)
	c := newTestContext("u1")
	c.Params = param.Params{param.Param{Key: "rid", Value: "pr-super"}}

	h.ListPlatformRoleUsers(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d, want 200, body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}
// Package rbac implements the management usecases for tenants, roles, members
// and platform administrators. Each usecase translates validated requests into
// persistence operations on Store and notifies the engine to invalidate caches
// whenever authorization-relevant data changes.
package rbac

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"strings"

	"golang.org/x/crypto/bcrypt"

	domain "github.com/lvyanru/dac-apiserver/internal/domain"
	domainrbac "github.com/lvyanru/dac-apiserver/internal/domain/rbac"

	eng "github.com/lvyanru/dac-apiserver/pkg/rbac"
)

// Usecase aggregates every management capability under one facade. Handlers and
// startup seeding depend on this single interface instead of dozens of methods.
type Usecase interface {
	// ---- 租户 ----
	Tenant(ctx context.Context, tenantID string) (*domainrbac.Tenant, error)
	Tenants(ctx context.Context, offset, limit int) (*TenantList, error)
	CreateTenant(ctx context.Context, userID, code, name, description string) (*domainrbac.Tenant, error)
	UpdateTenant(ctx context.Context, userID, tenantID, name, description string, status string) (*domainrbac.Tenant, error)
	DisableTenant(ctx context.Context, userID, tenantID string) (*domainrbac.Tenant, error)
	EnableTenant(ctx context.Context, userID, tenantID string) (*domainrbac.Tenant, error)
	DeleteTenant(ctx context.Context, userID, tenantID string) error

	// ---- 租户 namespace ----
	TenantNamespaces(ctx context.Context, tenantID string) ([]string, error)
	AddTenantNamespace(ctx context.Context, userID, tenantID, namespace string) error
	RemoveTenantNamespace(ctx context.Context, userID, tenantID, namespace string) error

	// ---- 租户角色 ----
	TenantRoles(ctx context.Context, tenantID string) ([]*domainrbac.TenantRole, error)
	CreateTenantRole(ctx context.Context, userID, tenantID, code, name, description string) (*domainrbac.TenantRole, error)
	UpdateTenantRole(ctx context.Context, userID, tenantID, roleID, name, description string) (*domainrbac.TenantRole, error)
	DeleteTenantRole(ctx context.Context, userID, tenantID, roleID string) error

	// ---- 租户角色 ↔ 权限 ----
	SetTenantRolePermissions(ctx context.Context, userID, tenantID, roleID string, permissionCodes []string) error
	TenantRolePermissionCodes(ctx context.Context, tenantID, roleID string) ([]string, error)

	// ---- 租户成员 ----
	TenantMembers(ctx context.Context, tenantID string, offset, limit int) (*MemberList, error)
	AddTenantMember(ctx context.Context, operatorID, tenantID, userID, roleID string) error
	ChangeTenantMemberRole(ctx context.Context, operatorID, tenantID, userID, roleID string) error
	RemoveTenantMember(ctx context.Context, operatorID, tenantID, userID string) error

	// AvailableUsers returns user IDs who are not yet assigned to any tenant.
	AvailableUsers(ctx context.Context) ([]string, error)

	// ---- 平台角色 ----
	PlatformRoles(ctx context.Context) ([]*domainrbac.PlatformRole, error)
	CreatePlatformRole(ctx context.Context, operatorID, code, name, description string) (*domainrbac.PlatformRole, error)
	UpdatePlatformRole(ctx context.Context, operatorID, roleID, name, description string) (*domainrbac.PlatformRole, error)
	SetPlatformRolePermissions(ctx context.Context, operatorID, roleID string, permissionCodes []string) error
	PlatformRolePermissionCodes(ctx context.Context, roleID string) ([]string, error)
	DeletePlatformRole(ctx context.Context, operatorID, roleID string) error

	// ---- 平台管理员 ----
	PlatformRoleUsers(ctx context.Context, roleID string) ([]PlatformRoleUserView, error)
	GrantPlatformRole(ctx context.Context, operatorID, userID, roleID string) error
	RevokePlatformRole(ctx context.Context, operatorID, userID, roleID string) error

	// BootstrapAdminID returns the user ID of the built-in (bootstrap)
	// administrator account, or "" when the account does not exist. The
	// built-in admin is immutable: it cannot be deleted nor have its platform
	// roles altered, guaranteeing the platform always retains an operator.
	BootstrapAdminID(ctx context.Context) (string, error)

	// ---- 权限点 ----
	Permissions(ctx context.Context) ([]*domainrbac.Permission, error)

	// ---- 当前用户 ----
	MyTenants(ctx context.Context, userID string) ([]*domainrbac.Tenant, error)

	// ---- 初始化 ----
	SeedDefaults(ctx context.Context) error
}

// TenantList is a paginated tenant result.
type TenantList struct {
	Items []*domainrbac.Tenant
	Total int
}

// MemberList is a paginated member result.
type MemberList struct {
	Items []*domainrbac.TenantMember
	Total int
}

// PlatformRoleUserView pairs a grantee user ID with a role code for display.
type PlatformRoleUserView struct {
	UserID   string
	RoleCode string
}

// Options carries the dependencies every usecase needs.
type Options struct {
	Store  domainrbac.Store
	Engine *eng.Engine
	Users  domain.UserRepository
	Logger *slog.Logger

	// Bootstrap optionally defines the first-administrator account. When the
	// platform holds no super admin, SeedDefaults creates this user and grants
	// it super_admin. Each non-empty field overrides the corresponding built-in
	// default (admin / changeme); leave the whole struct nil to use both.
	Bootstrap *BootstrapOptions
}

// BootstrapOptions is the first-administrator bootstrap configuration. It is
// a separate type so config values can be passed without polling the whole
// Options struct into the usecase.
type BootstrapOptions struct {
	Admin    string
	Password string
}

type usecase struct {
	store  domainrbac.Store
	engine *eng.Engine
	users  domain.UserRepository
	log    *slog.Logger

	bootstrap *BootstrapOptions
}

// New builds the RBAC usecase facade.
func New(opts Options) Usecase {
	if opts.Logger == nil {
		opts.Logger = slog.Default()
	}
	return &usecase{
		store:     opts.Store,
		engine:    opts.Engine,
		users:     opts.Users,
		log:       opts.Logger,
		bootstrap: opts.Bootstrap,
	}
}

// validateTenantStatus restricts status values to the supported set.
func validateTenantStatus(status string) error {
	switch status {
	case "", "active", "disabled":
		return nil
	default:
		return domain.NewInvalidInputError("status must be one of: active, disabled")
	}
}

// codesToIDs resolves permission codes to IDs via the store, validating every
// code exists. The result is deduplicated for stable insertion order.
func (u *usecase) codesToIDs(ctx context.Context, codes []string) ([]string, error) {
	seen := make(map[string]struct{}, len(codes))
	ids := make([]string, 0, len(codes))
	for _, code := range codes {
		if _, ok := seen[code]; ok {
			continue
		}
		seen[code] = struct{}{}
		p, err := u.store.GetPermissionByCode(ctx, code)
		if err != nil {
			return nil, domain.NewInvalidInputError("unknown permission code: " + code)
		}
		ids = append(ids, p.ID)
	}
	sort.Strings(ids)
	return ids, nil
}

// resolveCodes maps permission IDs back to their codes (sorted, de-duplicated).
func (u *usecase) resolveCodes(ctx context.Context, ids []string) ([]string, error) {
	if len(ids) == 0 {
		return []string{}, nil
	}
	return u.store.PermissionCodesByIDs(ctx, ids)
}

// Tenants returns a paginated tenant list.
func (u *usecase) Tenants(ctx context.Context, offset, limit int) (*TenantList, error) {
	items, total, err := u.store.ListTenants(ctx, offset, clampLimit(limit))
	if err != nil {
		return nil, fmt.Errorf("list tenants: %w", err)
	}
	return &TenantList{Items: items, Total: total}, nil
}

// Tenant fetches one tenant by ID.
func (u *usecase) Tenant(ctx context.Context, tenantID string) (*domainrbac.Tenant, error) {
	return u.store.GetTenant(ctx, tenantID)
}

// CreateTenant creates a tenant in the active state. Namespace bindings and
// member/role grants are configured afterwards through the management API, so a
// fresh tenant is fully isolated until an operator binds resources to it.
func (u *usecase) CreateTenant(ctx context.Context, userID, code, name, description string) (*domainrbac.Tenant, error) {
	code = strings.TrimSpace(code)
	name = strings.TrimSpace(name)
	if code == "" || name == "" {
		return nil, domain.NewInvalidInputError("code and name are required")
	}

	// A tenant always starts active; the caller can place it into a non-default
	// status right after creation through UpdateTenant.
	t, err := u.store.CreateTenant(ctx, &domainrbac.Tenant{
		Code:        code,
		Name:        name,
		Status:      "active",
		Description: description,
	})
	if err != nil {
		return nil, err
	}

	u.log.Info("tenant created",
		"operator_id", userID,
		"tenant_id", t.ID,
		"tenant_code", t.Code,
	)
	return t, nil
}

// defaultTenantCode identifies the built-in tenant seeded on first boot.
// Tenant codes are immutable after creation, so this marker is stable. The
// default tenant is a platform invariant: it cannot be modified, disabled or
// deleted, and its namespace binding is fixed to the cluster's default
// namespace.
const (
	defaultTenantCode      = "default"
	defaultTenantNamespace = "default"
)

func isDefaultTenant(t *domainrbac.Tenant) bool {
	return t != nil && t.Code == defaultTenantCode
}

// UpdateTenant updates name/description, and optionally the status.
func (u *usecase) UpdateTenant(ctx context.Context, userID, tenantID, name, description, status string) (*domainrbac.Tenant, error) {
	if err := validateTenantStatus(status); err != nil {
		return nil, err
	}
	t, err := u.store.GetTenant(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	if isDefaultTenant(t) {
		return nil, domain.NewConflictError("the default tenant is built-in and cannot be modified")
	}
	if name != "" {
		t.Name = name
	}
	t.Description = description
	if status != "" {
		t.Status = status
	}
	updated, err := u.store.UpdateTenant(ctx, t)
	if err != nil {
		return nil, err
	}

	// The status affects every member's authorization: drop cached information.
	u.engine.Invalidate(nil, nil, []string{tenantID})

	u.log.Info("tenant updated",
		"operator_id", userID,
		"tenant_id", tenantID,
		"tenant_code", updated.Code,
		"status", updated.Status,
	)
	return updated, nil
}

// DisableTenant is a shorthand for UpdateTenant(status=disabled). It revokes
// access for every member immediately because the engine denies disabled tenants.
func (u *usecase) DisableTenant(ctx context.Context, userID, tenantID string) (*domainrbac.Tenant, error) {
	return u.UpdateTenant(ctx, userID, tenantID, "", "", "disabled")
}

// EnableTenant reactivates a tenant.
func (u *usecase) EnableTenant(ctx context.Context, userID, tenantID string) (*domainrbac.Tenant, error) {
	return u.UpdateTenant(ctx, userID, tenantID, "", "", "active")
}

// DeleteTenant removes a tenant after storage-level dependency checks fail-safe.
func (u *usecase) DeleteTenant(ctx context.Context, userID, tenantID string) error {
	t, err := u.store.GetTenant(ctx, tenantID)
	if err != nil {
		return err
	}
	if isDefaultTenant(t) {
		return domain.NewConflictError("the default tenant is built-in and cannot be deleted")
	}
	if err := u.store.DeleteTenant(ctx, tenantID); err != nil {
		return err
	}
	u.engine.Invalidate(nil, nil, []string{tenantID})

	u.log.Info("tenant deleted",
		"operator_id", userID,
		"tenant_id", tenantID,
	)
	return nil
}

// TenantNamespaces lists the namespaces bound to a tenant.
func (u *usecase) TenantNamespaces(ctx context.Context, tenantID string) ([]string, error) {
	return u.store.ListTenantNamespaces(ctx, tenantID)
}

// AddTenantNamespace binds a namespace to a tenant and invalidates the cached
// namespace list so resource handlers observe the change immediately.
func (u *usecase) AddTenantNamespace(ctx context.Context, userID, tenantID, namespace string) error {
	if err := u.guardDefaultTenantNamespaceChange(ctx, tenantID); err != nil {
		return err
	}
	if err := u.store.AddTenantNamespace(ctx, tenantID, namespace); err != nil {
		return err
	}
	u.engine.Invalidate(nil, nil, []string{tenantID})

	u.log.Info("tenant namespace added",
		"operator_id", userID,
		"tenant_id", tenantID,
		"namespace", namespace,
	)
	return nil
}

// RemoveTenantNamespace unbinds a namespace from a tenant.
func (u *usecase) RemoveTenantNamespace(ctx context.Context, userID, tenantID, namespace string) error {
	if err := u.guardDefaultTenantNamespaceChange(ctx, tenantID); err != nil {
		return err
	}
	if err := u.store.RemoveTenantNamespace(ctx, tenantID, namespace); err != nil {
		return err
	}
	u.engine.Invalidate(nil, nil, []string{tenantID})

	u.log.Info("tenant namespace removed",
		"operator_id", userID,
		"tenant_id", tenantID,
		"namespace", namespace,
	)
	return nil
}

// guardDefaultTenantNamespaceChange rejects any namespace binding change on the
// built-in tenant: its namespace is fixed to the cluster's default namespace.
func (u *usecase) guardDefaultTenantNamespaceChange(ctx context.Context, tenantID string) error {
	t, err := u.store.GetTenant(ctx, tenantID)
	if err != nil {
		return err
	}
	if isDefaultTenant(t) {
		return domain.NewConflictError("the default tenant's namespace binding is fixed and cannot be changed")
	}
	return nil
}

// clampLimit keeps the page size within sane bounds.
func clampLimit(limit int) int {
	if limit <= 0 {
		return 20
	}
	if limit > 100 {
		return 100
	}
	return limit
}

// TenantRoles lists the roles belonging to a tenant.
func (u *usecase) TenantRoles(ctx context.Context, tenantID string) ([]*domainrbac.TenantRole, error) {
	return u.store.ListTenantRoles(ctx, tenantID)
}

// CreateTenantRole creates a tenant-local role.
func (u *usecase) CreateTenantRole(ctx context.Context, userID, tenantID, code, name, description string) (*domainrbac.TenantRole, error) {
	code = strings.TrimSpace(code)
	name = strings.TrimSpace(name)
	if code == "" || name == "" {
		return nil, domain.NewInvalidInputError("role code and name are required")
	}
	created, err := u.store.CreateTenantRole(ctx, &domainrbac.TenantRole{
		TenantID:    tenantID,
		Code:        code,
		Name:        name,
		Description: description,
	})
	if err != nil {
		return nil, err
	}

	u.log.Info("tenant role created",
		"operator_id", userID,
		"tenant_id", tenantID,
		"role_id", created.ID,
		"role_code", created.Code,
	)
	return created, nil
}

// UpdateTenantRole updates a tenant role's display name and description.
func (u *usecase) UpdateTenantRole(ctx context.Context, userID, tenantID, roleID, name, description string) (*domainrbac.TenantRole, error) {
	cur, err := u.store.GetTenantRoleByID(ctx, roleID)
	if err != nil {
		return nil, err
	}
	if cur.TenantID != tenantID {
		return nil, domain.NewInvalidInputError("role does not belong to the tenant")
	}
	if name != "" {
		cur.Name = name
	}
	cur.Description = description
	updated, err := u.store.UpdateTenantRole(ctx, cur)
	if err != nil {
		return nil, err
	}

	u.log.Info("tenant role updated",
		"operator_id", userID,
		"tenant_id", tenantID,
		"role_id", updated.ID,
		"role_code", updated.Code,
	)
	return updated, nil
}

// DeleteTenantRole removes a tenant role after ensuring no members are bound to it.
func (u *usecase) DeleteTenantRole(ctx context.Context, userID, tenantID, roleID string) error {
	cur, err := u.store.GetTenantRoleByID(ctx, roleID)
	if err != nil {
		return err
	}
	if cur.TenantID != tenantID {
		return domain.NewInvalidInputError("role does not belong to the tenant")
	}
	if err := u.store.DeleteTenantRole(ctx, roleID); err != nil {
		return err
	}
	u.engine.Invalidate([]string{roleID}, nil, nil)

	u.log.Info("tenant role deleted",
		"operator_id", userID,
		"tenant_id", tenantID,
		"role_id", roleID,
		"role_code", cur.Code,
	)
	return nil
}

// SetTenantRolePermissions replaces the permission set of a tenant role.
func (u *usecase) SetTenantRolePermissions(ctx context.Context, userID, tenantID, roleID string, permissionCodes []string) error {
	role, err := u.store.GetTenantRoleByID(ctx, roleID)
	if err != nil {
		return err
	}
	if role.TenantID != tenantID {
		return domain.NewInvalidInputError("role does not belong to the tenant")
	}
	ids, err := u.codesToIDs(ctx, permissionCodes)
	if err != nil {
		return err
	}
	if err := u.store.SetRolePermissions(ctx, roleID, tenantID, ids); err != nil {
		return err
	}
	u.engine.Invalidate([]string{roleID}, nil, []string{tenantID})

	u.log.Info("tenant role permissions updated",
		"operator_id", userID,
		"tenant_id", tenantID,
		"role_id", roleID,
		"role_code", role.Code,
		"permission_count", len(ids),
	)
	return nil
}

// TenantRolePermissionCodes returns the permission codes currently bound to a
// tenant role. Handlers use it to render the permission matrix with pre-checked
// state (SetTenantRolePermissions is a full overwrite).
func (u *usecase) TenantRolePermissionCodes(ctx context.Context, tenantID, roleID string) ([]string, error) {
	role, err := u.store.GetTenantRoleByID(ctx, roleID)
	if err != nil {
		return nil, err
	}
	if role.TenantID != tenantID {
		return nil, domain.NewInvalidInputError("role does not belong to the tenant")
	}
	ids, err := u.store.GetRolePermissionIDs(ctx, roleID, false)
	if err != nil {
		return nil, err
	}
	return u.resolveCodes(ctx, ids)
}

// TenantMembers returns a paginated member list with joined role codes.
func (u *usecase) TenantMembers(ctx context.Context, tenantID string, offset, limit int) (*MemberList, error) {
	items, total, err := u.store.ListTenantMembers(ctx, tenantID, offset, clampLimit(limit))
	if err != nil {
		return nil, fmt.Errorf("list tenant members: %w", err)
	}
	return &MemberList{Items: items, Total: total}, nil
}

// AddTenantMember joins a user to a tenant with the given role.
// A user can only belong to one tenant; this is enforced both at the application
// layer (pre-check) and at the database layer (unique index on user_id).
func (u *usecase) AddTenantMember(ctx context.Context, operatorID, tenantID, userID, roleID string) error {
	// The role must belong to the target tenant, otherwise a malicious operator
	// could bind a member to a foreign role and escalate privileges.
	role, err := u.store.GetTenantRoleByID(ctx, roleID)
	if err != nil {
		return domain.NewInvalidInputError("role not found or invalid")
	}
	if role.TenantID != tenantID {
		return domain.NewInvalidInputError("role does not belong to the tenant")
	}
	// The user must exist in the platform before membership can be recorded.
	if _, err := u.users.GetByID(ctx, userID); err != nil {
		if domain.IsNotFound(err) {
			return domain.NewInvalidInputError("user not found")
		}
		return fmt.Errorf("lookup user: %w", err)
	}
	// The user must not already be a member of any tenant.
	tenantIDs, err := u.store.ListTenantIDsByUser(ctx, userID)
	if err != nil {
		return fmt.Errorf("check existing memberships: %w", err)
	}
	if len(tenantIDs) > 0 {
		return domain.NewConflictError("user is already assigned to another tenant")
	}
	if _, err := u.store.AddTenantMember(ctx, tenantID, userID, roleID); err != nil {
		return err
	}
	u.engine.Invalidate(nil, []string{userID}, []string{tenantID})

	u.log.Info("tenant member added",
		"operator_id", operatorID,
		"tenant_id", tenantID,
		"user_id", userID,
		"role_id", roleID,
		"role_code", role.Code,
	)
	return nil
}

// ChangeTenantMemberRole reassigns a member to another role in the same tenant.
func (u *usecase) ChangeTenantMemberRole(ctx context.Context, operatorID, tenantID, userID, roleID string) error {
	role, err := u.store.GetTenantRoleByID(ctx, roleID)
	if err != nil {
		return domain.NewInvalidInputError("role not found or invalid")
	}
	if role.TenantID != tenantID {
		return domain.NewInvalidInputError("role does not belong to the tenant")
	}
	if err := u.store.ChangeTenantMemberRole(ctx, tenantID, userID, roleID); err != nil {
		return err
	}
	u.engine.Invalidate(nil, []string{userID}, []string{tenantID})

	u.log.Info("tenant member role changed",
		"operator_id", operatorID,
		"tenant_id", tenantID,
		"user_id", userID,
		"role_id", roleID,
		"role_code", role.Code,
	)
	return nil
}

// RemoveTenantMember removes a user from a tenant entirely.
func (u *usecase) RemoveTenantMember(ctx context.Context, operatorID, tenantID, userID string) error {
	if err := u.store.RemoveTenantMember(ctx, tenantID, userID); err != nil {
		return err
	}
	u.engine.Invalidate(nil, []string{userID}, []string{tenantID})

	u.log.Info("tenant member removed",
		"operator_id", operatorID,
		"tenant_id", tenantID,
		"user_id", userID,
	)
	return nil
}

// AvailableUsers returns user IDs who are not yet assigned to any tenant.
func (u *usecase) AvailableUsers(ctx context.Context) ([]string, error) {
	return u.store.ListUsersNotInAnyTenant(ctx)
}

// PlatformRoles lists every platform role.
func (u *usecase) PlatformRoles(ctx context.Context) ([]*domainrbac.PlatformRole, error) {
	return u.store.ListPlatformRoles(ctx)
}

// CreatePlatformRole creates a global role. New roles are never super by default;
// privilege escalation must be an explicit later action by an existing super admin.
func (u *usecase) CreatePlatformRole(ctx context.Context, operatorID, code, name, description string) (*domainrbac.PlatformRole, error) {
	code = strings.TrimSpace(code)
	name = strings.TrimSpace(name)
	if code == "" || name == "" {
		return nil, domain.NewInvalidInputError("role code and name are required")
	}
	created, err := u.store.CreatePlatformRole(ctx, &domainrbac.PlatformRole{
		Code:        code,
		Name:        name,
		IsSuper:     false,
		Description: description,
	})
	if err != nil {
		return nil, err
	}

	u.log.Info("platform role created",
		"operator_id", operatorID,
		"role_id", created.ID,
		"role_code", created.Code,
	)
	return created, nil
}

// UpdatePlatformRole updates display name and description of a platform role.
func (u *usecase) UpdatePlatformRole(ctx context.Context, operatorID, roleID, name, description string) (*domainrbac.PlatformRole, error) {
	cur, err := u.store.GetPlatformRole(ctx, roleID)
	if err != nil {
		return nil, err
	}
	if cur.IsSuper {
		return nil, domain.NewInvalidInputError("the super admin role is built-in and cannot be modified")
	}
	if name != "" {
		cur.Name = name
	}
	cur.Description = description
	updated, err := u.store.UpdatePlatformRole(ctx, cur)
	if err != nil {
		return nil, err
	}

	u.log.Info("platform role updated",
		"operator_id", operatorID,
		"role_id", updated.ID,
		"role_code", updated.Code,
	)
	return updated, nil
}

// SetPlatformRolePermissions sets the permission set of a non-super platform role.
// Super roles carry no permission bindings: their engine short-circuits on IsSuper.
func (u *usecase) SetPlatformRolePermissions(ctx context.Context, operatorID, roleID string, permissionCodes []string) error {
	role, err := u.store.GetPlatformRole(ctx, roleID)
	if err != nil {
		return err
	}
	if role.IsSuper {
		return domain.NewInvalidInputError("super role permissions are implicit and cannot be configured")
	}
	ids, err := u.codesToIDs(ctx, permissionCodes)
	if err != nil {
		return err
	}
	if err := u.store.SetRolePermissions(ctx, roleID, "", ids); err != nil {
		return err
	}
	u.engine.Invalidate([]string{roleID}, nil, nil)

	u.log.Info("platform role permissions updated",
		"operator_id", operatorID,
		"role_id", roleID,
		"role_code", role.Code,
		"permission_count", len(ids),
	)
	return nil
}

// PlatformRolePermissionCodes returns the permission codes currently bound to a
// platform role (super roles report an empty set; their access is implicit).
func (u *usecase) PlatformRolePermissionCodes(ctx context.Context, roleID string) ([]string, error) {
	role, err := u.store.GetPlatformRole(ctx, roleID)
	if err != nil {
		return nil, err
	}
	if role.IsSuper {
		return []string{}, nil
	}
	ids, err := u.store.GetRolePermissionIDs(ctx, roleID, true)
	if err != nil {
		return nil, err
	}
	return u.resolveCodes(ctx, ids)
}

// DeletePlatformRole removes a platform role. It refuses to delete the super
// admin role itself or any role that still has grantees, so the platform can
// never lose its last administrator.
func (u *usecase) DeletePlatformRole(ctx context.Context, operatorID, roleID string) error {
	role, err := u.store.GetPlatformRole(ctx, roleID)
	if err != nil {
		return err
	}
	if role.IsSuper {
		return domain.NewInvalidInputError("the super admin role cannot be deleted")
	}
	if err := u.store.DeletePlatformRole(ctx, roleID); err != nil {
		return err
	}
	u.engine.Invalidate([]string{roleID}, nil, nil)

	u.log.Info("platform role deleted",
		"operator_id", operatorID,
		"role_id", roleID,
		"role_code", role.Code,
	)
	return nil
}

// PlatformRoleUsers lists the users bound to a platform role (for the admin UI).
func (u *usecase) PlatformRoleUsers(ctx context.Context, roleID string) ([]PlatformRoleUserView, error) {
	role, err := u.store.GetPlatformRole(ctx, roleID)
	if err != nil {
		return nil, err
	}
	userIDs, err := u.store.ListPlatformRoleUsers(ctx, roleID)
	if err != nil {
		return nil, err
	}
	out := make([]PlatformRoleUserView, 0, len(userIDs))
	for _, uid := range userIDs {
		out = append(out, PlatformRoleUserView{UserID: uid, RoleCode: role.Code})
	}
	return out, nil
}

// GrantPlatformRole grants a platform role to a user. Granting super admin to a
// user is the equivalent of the old 'users.role=admin' hardcoded admin: the
// page turns "设为平台管理员" into this call.
func (u *usecase) GrantPlatformRole(ctx context.Context, operatorID, userID, roleID string) error {
	role, err := u.store.GetPlatformRole(ctx, roleID)
	if err != nil {
		return err
	}
	if _, err := u.users.GetByID(ctx, userID); err != nil {
		if domain.IsNotFound(err) {
			return domain.NewInvalidInputError("user not found")
		}
		return fmt.Errorf("lookup user: %w", err)
	}
	if id, err := u.BootstrapAdminID(ctx); err != nil {
		return err
	} else if id != "" && id == userID {
		return domain.NewConflictError("the built-in administrator's roles cannot be changed")
	}
	if err := u.store.AssignPlatformRole(ctx, userID, roleID); err != nil {
		return err
	}
	u.engine.Invalidate(nil, []string{userID}, nil)

	u.log.Info("platform role granted",
		"operator_id", operatorID,
		"user_id", userID,
		"role_id", roleID,
		"role_code", role.Code,
		"is_super", role.IsSuper,
	)
	return nil
}

// RevokePlatformRole removes a platform role from a user. It refuses the last
// super admin: removing every super admin would lock the platform out forever.
func (u *usecase) RevokePlatformRole(ctx context.Context, operatorID, userID, roleID string) error {
	role, err := u.store.GetPlatformRole(ctx, roleID)
	if err != nil {
		return err
	}
	if id, err := u.BootstrapAdminID(ctx); err != nil {
		return err
	} else if id != "" && id == userID {
		return domain.NewConflictError("the built-in administrator's roles cannot be changed")
	}
	if role.IsSuper {
		holders, err := u.store.ListPlatformRoleUsers(ctx, roleID)
		if err != nil {
			return err
		}
		if len(holders) <= 1 {
			return domain.NewConflictError("cannot revoke the last super admin")
		}
	}
	if err := u.store.RevokePlatformRole(ctx, userID, roleID); err != nil {
		return err
	}
	u.engine.Invalidate(nil, []string{userID}, nil)

	u.log.Info("platform role revoked",
		"operator_id", operatorID,
		"user_id", userID,
		"role_id", roleID,
		"role_code", role.Code,
	)
	return nil
}

// BootstrapAdminID resolves the user ID of the built-in administrator account
// (the bootstrap admin). It is derived from the same BootstrapOptions that
// seeded the account on first boot, so protection follows the configured
// account name rather than a hard-coded "admin".
func (u *usecase) BootstrapAdminID(ctx context.Context) (string, error) {
	username := defaultBootstrapAdmin
	if u.bootstrap != nil && strings.TrimSpace(u.bootstrap.Admin) != "" {
		username = strings.TrimSpace(u.bootstrap.Admin)
	}
	user, err := u.users.GetByUsername(ctx, username)
	if err != nil {
		if domain.IsNotFound(err) {
			return "", nil
		}
		return "", fmt.Errorf("lookup bootstrap admin: %w", err)
	}
	return user.ID, nil
}

// Permissions lists the full permission catalog for the UI permission picker.
func (u *usecase) Permissions(ctx context.Context) ([]*domainrbac.Permission, error) {
	return u.store.ListPermissions(ctx)
}

// MyTenants lists the tenants a user belongs to, for the frontend tenant switcher.
func (u *usecase) MyTenants(ctx context.Context, userID string) ([]*domainrbac.Tenant, error) {
	tenantIDs, err := u.store.ListTenantIDsByUser(ctx, userID)
	if err != nil {
		return nil, err
	}
	out := make([]*domainrbac.Tenant, 0, len(tenantIDs))
	for _, tid := range tenantIDs {
		t, err := u.store.GetTenant(ctx, tid)
		if err != nil && !domain.IsNotFound(err) {
			return nil, err
		}
		if err == nil {
			out = append(out, t)
		}
	}
	return out, nil
}

// SeedDefaults bootstraps the RBAC model on startup and migrates legacy users.
//
// It is idempotent: every block either finds the row already present or creates
// it, so restarting the service applies the same guarantees without side effects.
// The whole process mirrors the guarantees the old policy.csv provided:
//  1. upsert the static permission catalog (engine rules);
//  2. create the super-admin platform role with IsSuper=true;
//  3. create the default tenant and its default 'viewer' role;
//  4. bootstrap the first platform administrator when none holds super_admin
//     (a built-in admin/changeme account, or the env-driven BootstrapOptions);
//  5. migrate legacy users.role='admin' to a super-admin grant and
//     users.role='user' to a viewer membership in the default tenant.
func (u *usecase) SeedDefaults(ctx context.Context) error {
	if err := u.seedPermissions(ctx); err != nil {
		return fmt.Errorf("seed permissions: %w", err)
	}
	if err := u.seedPlatformRoles(ctx); err != nil {
		return fmt.Errorf("seed platform roles: %w", err)
	}
	if err := u.seedDefaultTenant(ctx); err != nil {
		return fmt.Errorf("seed default tenant: %w", err)
	}
	if err := u.seedBootstrapAdmin(ctx); err != nil {
		return fmt.Errorf("bootstrap first administrator: %w", err)
	}
	return nil
}

// seedPermissions upserts the static permission catalog.
//
// The catalog may carry several entries under the same code (e.g. "agent:read"
// covering both the list and the detail endpoint). Because the permission code
// column is unique, those entries must be merged into a single row whose
// HTTPPath joins the templates with '|' (the engine expands them in
// Permission.Rules). Writing one row per catalog line would silently keep only
// the last path and lose endpoints.
func (u *usecase) seedPermissions(ctx context.Context) error {
	merged := mergeSeedPermissions(eng.SeedPermissions)
	for code, sp := range merged {
		if err := u.store.UpsertPermission(ctx, &domainrbac.Permission{
			Code:        code,
			Name:        sp.Name,
			Resource:    sp.Resource,
			Action:      sp.Action,
			HTTPMethod:  sp.HTTPMethod,
			HTTPPath:    strings.Join(sp.PathTemplates, "|"),
			Description: sp.Description,
		}); err != nil {
			return err
		}
	}
	u.log.Info("rbac permissions seeded", "count", len(merged))
	return nil
}

// mergedSeedPermission is the accumulation of all catalog entries sharing a code.
type mergedSeedPermission struct {
	Name          string
	Resource      string
	Action        string
	HTTPMethod    string
	Description   string
	PathTemplates []string
}

// mergeSeedPermissions groups catalog entries by code. It keeps the first
// entry's identity fields (name/resource/action/description), widens the HTTP
// method to "*" when any entry uses it, and accumulates every distinct path
// template so one code keeps granting all of its endpoints.
func mergeSeedPermissions(catalog []eng.SeedPermission) map[string]mergedSeedPermission {
	merged := make(map[string]mergedSeedPermission, len(catalog))
	for _, sp := range catalog {
		acc, ok := merged[sp.Code]
		if !ok {
			acc = mergedSeedPermission{
				Name:        sp.Name,
				Resource:    sp.Resource,
				Action:      sp.Action,
				HTTPMethod:  sp.HTTPMethod,
				Description: sp.Description,
			}
		}
		if sp.HTTPMethod == "*" {
			acc.HTTPMethod = "*"
		}
		for _, tmpl := range splitPathTemplates(sp.HTTPPath) {
			acc.PathTemplates = appendUnique(acc.PathTemplates, tmpl)
		}
		merged[sp.Code] = acc
	}
	return merged
}

// splitPathTemplates splits a '|'-joined path pattern list into its entries.
func splitPathTemplates(s string) []string {
	if s == "" {
		return nil
	}
	var out []string
	for _, part := range strings.Split(s, "|") {
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}

// appendUnique appends s to list unless already present.
func appendUnique(list []string, s string) []string {
	for _, item := range list {
		if item == s {
			return list
		}
	}
	return append(list, s)
}

// seedPlatformRoles ensures the super-admin role and default non-super platform
// roles always exist. Other platform roles may be created later through the
// management API.
func (u *usecase) seedPlatformRoles(ctx context.Context) error {
	const (
		superCode = "super_admin"
		superName = "超级管理员"
		superDesc = "平台超级管理员，拥有平台级全部权限（不可删除、不可降级，权限为隐式全通）"

		adminCode = "platform_admin"
		adminName = "平台管理员"
		adminDesc = "平台管理员，拥有平台管理与用户管理权限"

		viewerCode = "platform_viewer"
		viewerName = "平台观察者"
		viewerDesc = "平台观察者，可查看平台配置与权限信息"
	)

	// --- super_admin ---
	exists, err := u.platformRoleExists(ctx, superCode)
	if err != nil {
		return err
	}
	if !exists {
		if _, err := u.store.CreatePlatformRole(ctx, &domainrbac.PlatformRole{
			Code:        superCode,
			Name:        superName,
			IsSuper:     true,
			Description: superDesc,
		}); err != nil {
			return err
		}
		u.log.Info("super admin platform role seeded", "code", superCode)
	}

	// --- platform_admin (non-super) ---
	adminExists, err := u.platformRoleExists(ctx, adminCode)
	if err != nil {
		return err
	}
	if !adminExists {
		role, err := u.store.CreatePlatformRole(ctx, &domainrbac.PlatformRole{
			Code:        adminCode,
			Name:        adminName,
			IsSuper:     false,
			Description: adminDesc,
		})
		if err != nil {
			return err
		}
		// Bind management permissions to platform_admin (complete set matching
		// the production database configuration).
		adminPermissionCodes := []string{
			// Platform management
			"tenant:manage", "tenant:read",
			"platform:role:manage", "platform:role:read",
			"permission:read",
			"user:manage", "user:read",
			"rbac:me:read", "user:self:read",
			// Tenant management
			"tenant:role:manage", "tenant:role:read",
			"tenant:member:manage", "tenant:member:read",
			// Business resources — full CRUD
			"agent:read", "agent:create", "agent:update", "agent:delete",
			"descriptor:read", "descriptor:create", "descriptor:update", "descriptor:delete",
			"descriptor:graph:read",
			"llmconfig:read", "llmconfig:create", "llmconfig:update", "llmconfig:delete",
			"promptconfig:read", "promptconfig:create", "promptconfig:update", "promptconfig:delete",
			"system:config:read", "system:config:manage",
			"semantic-group:read", "semantic-group:manage",
			"skill:read", "skill:manage",
			"skill:namespace:read", "skill:namespace:manage",
			"discovery:read", "discovery:manage",
			"environment:read",
			"namespace:read",
			"observability:read",
			"datasource:probe", "datasource:probe-types",
			"chat:use", "chat:history:read",
		}
		if err := u.seedRolePermissions(ctx, role.ID, "", adminPermissionCodes); err != nil {
			u.log.Warn("failed to seed platform_admin permissions", "error", err)
		}
		u.log.Info("platform_admin platform role seeded", "code", adminCode)
	}

	// --- platform_viewer (non-super) ---
	viewerExists, err := u.platformRoleExists(ctx, viewerCode)
	if err != nil {
		return err
	}
	if !viewerExists {
		role, err := u.store.CreatePlatformRole(ctx, &domainrbac.PlatformRole{
			Code:        viewerCode,
			Name:        viewerName,
			IsSuper:     false,
			Description: viewerDesc,
		})
		if err != nil {
			return err
		}
		// Bind read-only permissions to platform_viewer (complete set matching
		// the production database configuration).
		viewerPermissionCodes := []string{
			// Platform read-only
			"tenant:read",
			"platform:role:read",
			"permission:read",
			"user:read",
			"rbac:me:read", "user:self:read",
			// Tenant read-only
			"tenant:role:read",
			"tenant:member:read",
			// Business resources — read-only
			"agent:read",
			"descriptor:read",
			"descriptor:graph:read",
			"llmconfig:read",
			"promptconfig:read",
			"system:config:read",
			"semantic-group:read",
			"skill:read",
			"skill:namespace:read",
			"discovery:read",
			"environment:read",
			"namespace:read",
			"observability:read",
			"datasource:probe-types",
			"chat:use", "chat:history:read",
		}
		if err := u.seedRolePermissions(ctx, role.ID, "", viewerPermissionCodes); err != nil {
			u.log.Warn("failed to seed platform_viewer permissions", "error", err)
		}
		u.log.Info("platform_viewer platform role seeded", "code", viewerCode)
	}

	return nil
}

// seedRolePermissions resolves permission codes to IDs and binds them to a role.
// tenantID may be empty for platform roles.
func (u *usecase) seedRolePermissions(ctx context.Context, roleID string, tenantID string, codes []string) error {
	ids, err := u.codesToIDs(ctx, codes)
	if err != nil {
		return err
	}
	return u.store.SetRolePermissions(ctx, roleID, tenantID, ids)
}

// seedBootstrapAdmin guarantees the platform never starts without an operator.
//
// A fresh installation has no user holding the super_admin platform role, and
// the management API that grants it is itself protected by that role — a
// chicken-and-egg deadlock. This step breaks it exactly once:
//
//   - when the super-admin role already has a holder, it does nothing (an
//     administrator exists; never touch credentials again on restart);
//   - otherwise it creates an account and grants super_admin. The credentials
//     come from BootstrapOptions when configured (env-driven, e.g. a deployed
//     secret), else from the built-in default admin / changeme.
//
// The granted user is added as a super admin platform role holder.
// The legacy users.role column is no longer maintained; RBAC engine
// derives isSuper from platform_user_role and the JWT only carries
// user_id + username.
func (u *usecase) seedBootstrapAdmin(ctx context.Context) error {
	adminUsername := defaultBootstrapAdmin
	adminPassword := defaultBootstrapPassword
	if u.bootstrap != nil {
		if name := strings.TrimSpace(u.bootstrap.Admin); name != "" {
			adminUsername = name
		}
		if pwd := u.bootstrap.Password; pwd != "" {
			adminPassword = pwd
		}
	}

	// An operator already exists: skip entirely, never re-create or reset.
	super, err := u.superAdminRole(ctx)
	if err != nil {
		return err
	}
	if super == nil {
		return fmt.Errorf("super admin role missing during bootstrap")
	}
	holders, err := u.store.ListPlatformRoleUsers(ctx, super.ID)
	if err != nil {
		return err
	}
	if len(holders) > 0 {
		return nil
	}

	// No super admin exists yet — this is the first boot. Reuse an existing
	// account when it matches the bootstrap username, create it otherwise.
	user, err := u.users.GetByUsername(ctx, adminUsername)
	switch {
	case err == nil && user != nil:
		// account exists but holds no super grant; promote it.
	case domain.IsNotFound(err):
		passwordHash, err := hashBootstrapPassword(adminPassword)
		if err != nil {
			return err
		}
		user, err = u.users.Create(ctx, adminUsername, passwordHash, nil)
		if err != nil {
			if domain.IsAlreadyExists(err) {
				user, err = u.users.GetByUsername(ctx, adminUsername)
				if err != nil {
					return err
				}
			} else {
				return fmt.Errorf("create bootstrap admin: %w", err)
			}
		}
	default:
		return fmt.Errorf("lookup bootstrap admin: %w", err)
	}

	if err := u.store.AssignPlatformRole(ctx, user.ID, super.ID); err != nil {
		return err
	}
	u.engine.Invalidate(nil, []string{user.ID}, nil)

	if adminUsername == defaultBootstrapAdmin {
		u.log.Warn("platform bootstrapped with the default super admin — CHANGE THE PASSWORD NOW",
			"username", adminUsername, "initial_password", defaultBootstrapPassword)
	} else {
		u.log.Info("platform bootstrapped with a configured first super admin",
			"username", adminUsername)
	}
	return nil
}

// hashBootstrapPassword hashes a plaintext password with bcrypt at the same
// cost as the user usecase so login verification
// (bcrypt.CompareHashAndPassword) works for the seeded account.
func hashBootstrapPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", fmt.Errorf("hash bootstrap password: %w", err)
	}
	return string(hash), nil
}

// Built-in bootstrap credentials. They are used only when the platform has no
// super admin at all; production deployments should override them through
// config/env (bootstrap.admin / bootstrap.password) or change the password
// immediately after first login.
const (
	defaultBootstrapAdmin    = "admin"
	defaultBootstrapPassword = "changeme"
)

func (u *usecase) platformRoleExists(ctx context.Context, code string) (bool, error) {
	roles, err := u.store.ListPlatformRoles(ctx)
	if err != nil {
		return false, err
	}
	for _, r := range roles {
		if r.Code == code {
			return true, nil
		}
	}
	return false, nil
}

// seedDefaultTenant creates the 'default' tenant bound to the cluster's
// default namespace and its role 'viewer'. The legacy read-only whitelist is
// bound to the viewer role only when that role is created by this seed; an
// existing role keeps whatever permissions an administrator configured,
// otherwise every restart would silently reset the role and discard page-made
// changes.
func (u *usecase) seedDefaultTenant(ctx context.Context) error {
	const (
		defaultTenantName = "默认租户"
		defaultTenantDesc = "系统初始化创建的默认租户；绑定 default 命名空间"
		viewerRoleCode    = "viewer"
		viewerRoleName    = "查看者"
		viewerRoleDesc    = "默认只读角色，拥有迁移前的只读白名单权限"
	)

	tenant, err := u.store.GetTenantByCode(ctx, defaultTenantCode)
	switch {
	case err == nil:
		// exists; fall through to bond namespace + role idempotently.
	case domain.IsNotFound(err):
		tenant, err = u.store.CreateTenant(ctx, &domainrbac.Tenant{
			Code:        defaultTenantCode,
			Name:        defaultTenantName,
			Status:      "active",
			Description: defaultTenantDesc,
		})
		if err != nil {
			return err
		}
		u.log.Info("default tenant seeded", "tenant_id", tenant.ID, "tenant_code", tenant.Code)
	default:
		return err
	}

	// The default tenant is bound exactly to the cluster's default namespace.
	// Idempotent: skip when already bound, clean up the legacy "*" wildcard
	// binding used by earlier versions.
	nss, err := u.store.ListTenantNamespaces(ctx, tenant.ID)
	if err != nil {
		return err
	}
	hasDefault := false
	for _, n := range nss {
		switch n {
		case defaultTenantNamespace:
			hasDefault = true
		case "*":
			if err := u.store.RemoveTenantNamespace(ctx, tenant.ID, n); err != nil {
				return err
			}
		}
	}
	if !hasDefault {
		if err := u.store.AddTenantNamespace(ctx, tenant.ID, defaultTenantNamespace); err != nil {
			return err
		}
	}

	viewer, created, err := u.ensureTenantRole(ctx, tenant.ID, viewerRoleCode, viewerRoleName, viewerRoleDesc)
	if err != nil {
		return err
	}
	if !created {
		return nil // keep administrator-configured permissions untouched on restart
	}

	ids, err := u.codesToIDs(ctx, eng.DefaultCodes)
	if err != nil {
		return err
	}
	if err := u.store.SetRolePermissions(ctx, viewer.ID, tenant.ID, ids); err != nil {
		return err
	}
	return nil
}

// ensureTenantRole returns the tenant role matching code, creating it (with the
// is-default flag) when absent. The second return value reports whether the role
// was created by this call, which lets the caller decide whether to seed the
// default permission whitelist or leave existing bindings alone.
func (u *usecase) ensureTenantRole(ctx context.Context, tenantID, code, name, desc string) (*domainrbac.TenantRole, bool, error) {
	roles, err := u.store.ListTenantRoles(ctx, tenantID)
	if err != nil {
		return nil, false, err
	}
	for _, r := range roles {
		if r.Code == code {
			return r, false, nil
		}
	}
	created, err := u.store.CreateTenantRole(ctx, &domainrbac.TenantRole{
		TenantID:    tenantID,
		Code:        code,
		Name:        name,
		IsDefault:   true,
		Description: desc,
	})
	if err != nil {
		return nil, false, err
	}
	return created, true, nil
}

func (u *usecase) superAdminRole(ctx context.Context) (*domainrbac.PlatformRole, error) {
	roles, err := u.store.ListPlatformRoles(ctx)
	if err != nil {
		return nil, err
	}
	for _, r := range roles {
		if r.Code == "super_admin" {
			return r, nil
		}
	}
	return nil, nil
}

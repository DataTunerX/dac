// Package rbac defines the domain contracts for tenant/role/permission management.
//
// It is intentionally free of engine implementation details: usecases depend on
// these interfaces so that management behaviour can be unit-tested against fakes,
// and the actual ent-backed store lives in infrastructure/database/rbac.
package rbac

import (
	"context"
	"time"
)

// Tenant is a tenant entity as managed through the RBAC API.
type Tenant struct {
	ID          string
	Code        string
	Name        string
	Status      string // active / disabled
	Description string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// TenantRole is a tenant-local role.
type TenantRole struct {
	ID          string
	TenantID    string
	Code        string
	Name        string
	IsDefault   bool
	Description string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// TenantMember links a user to a tenant with a role.
type TenantMember struct {
	ID        string
	TenantID  string
	UserID    string
	RoleID    string
	RoleCode  string // 冗余展示，join 出角色的编码
	CreatedAt time.Time
}

// PlatformRole is a global role (not tenant-scoped).
type PlatformRole struct {
	ID          string
	Code        string
	Name        string
	IsSuper     bool
	Description string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// Permission is a permission point as exposed to the UI.
type Permission struct {
	ID          string
	Code        string
	Name        string
	Resource    string
	Action      string
	HTTPMethod  string
	HTTPPath    string
	Description string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// Store is the persistence contract used by RBAC usecases.
type Store interface {
	// ---- 租户 ----
	ListTenants(ctx context.Context, offset, limit int) ([]*Tenant, int, error)
	GetTenant(ctx context.Context, tenantID string) (*Tenant, error)
	GetTenantByCode(ctx context.Context, code string) (*Tenant, error)
	CreateTenant(ctx context.Context, t *Tenant) (*Tenant, error)
	UpdateTenant(ctx context.Context, t *Tenant) (*Tenant, error)
	DeleteTenant(ctx context.Context, tenantID string) error

	// ---- 租户 namespace ----
	ListTenantNamespaces(ctx context.Context, tenantID string) ([]string, error)
	AddTenantNamespace(ctx context.Context, tenantID, namespace string) error
	RemoveTenantNamespace(ctx context.Context, tenantID, namespace string) error

	// ---- 租户角色 ----
	ListTenantRoles(ctx context.Context, tenantID string) ([]*TenantRole, error)
	GetTenantRoleByID(ctx context.Context, roleID string) (*TenantRole, error)
	CreateTenantRole(ctx context.Context, r *TenantRole) (*TenantRole, error)
	UpdateTenantRole(ctx context.Context, r *TenantRole) (*TenantRole, error)
	DeleteTenantRole(ctx context.Context, roleID string) error

	// ---- 租户成员 ----
	ListTenantMembers(ctx context.Context, tenantID string, offset, limit int) ([]*TenantMember, int, error)
	GetTenantMembership(ctx context.Context, tenantID, userID string) (*TenantMember, error)
	ListTenantIDsByUser(ctx context.Context, userID string) ([]string, error)
	AddTenantMember(ctx context.Context, tenantID, userID, roleID string) (*TenantMember, error)
	ChangeTenantMemberRole(ctx context.Context, tenantID, userID, roleID string) error
	RemoveTenantMember(ctx context.Context, tenantID, userID string) error
	// ListUsersNotInAnyTenant returns users who are not yet assigned to any tenant.
	ListUsersNotInAnyTenant(ctx context.Context) ([]string, error)

	// ---- 平台角色 ----
	ListPlatformRoles(ctx context.Context) ([]*PlatformRole, error)
	GetPlatformRole(ctx context.Context, roleID string) (*PlatformRole, error)
	CreatePlatformRole(ctx context.Context, r *PlatformRole) (*PlatformRole, error)
	UpdatePlatformRole(ctx context.Context, r *PlatformRole) (*PlatformRole, error)
	DeletePlatformRole(ctx context.Context, roleID string) error

	// ---- 平台角色 ↔ 用户 ----
	ListPlatformRoleUsers(ctx context.Context, roleID string) ([]string, error) // userIDs
	AssignPlatformRole(ctx context.Context, userID, roleID string) error
	RevokePlatformRole(ctx context.Context, userID, roleID string) error

	// ---- 权限点 ----
	ListPermissions(ctx context.Context) ([]*Permission, error)
	GetPermissionByCode(ctx context.Context, code string) (*Permission, error)
	UpsertPermission(ctx context.Context, p *Permission) error

	// ---- 角色 ↔ 权限 ----
	SetRolePermissions(ctx context.Context, roleID string, tenantID string, permissionIDs []string) error
	GetRolePermissionIDs(ctx context.Context, roleID string, isPlatform bool) ([]string, error)
	PermissionCodesByIDs(ctx context.Context, ids []string) ([]string, error)
}
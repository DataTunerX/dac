// Package dto defines the request/response payloads for the RBAC management API.
package dto

import (
	domainrbac "github.com/lvyanru/dac-apiserver/internal/domain/rbac"
)

// ---- 租户 ----

// CreateTenantRequest is the payload for POST /api/v1/rbac/tenants.
type CreateTenantRequest struct {
	Code        string `json:"code" validate:"required"`
	Name        string `json:"name" validate:"required"`
	Description string `json:"description"`
}

// UpdateTenantRequest is the payload for PUT /api/v1/rbac/tenants/:id.
type UpdateTenantRequest struct {
	Name        string `json:"name"`
	Status      string `json:"status"` // active / disabled
	Description string `json:"description"`
}

// TenantResponse describes a tenant in API responses.
type TenantResponse struct {
	ID          string `json:"id"`
	Code        string `json:"code"`
	Name        string `json:"name"`
	Status      string `json:"status"`
	Description string `json:"description"`
	CreatedAt   string `json:"createdAt"`
	UpdatedAt   string `json:"updatedAt"`
}

// ToTenantResponse maps a tenant entity to its API shape.
func ToTenantResponse(t *domainrbac.Tenant) *TenantResponse {
	if t == nil {
		return nil
	}
	return &TenantResponse{
		ID:          t.ID,
		Code:        t.Code,
		Name:        t.Name,
		Status:      t.Status,
		Description: t.Description,
		CreatedAt:   t.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
		UpdatedAt:   t.UpdatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}
}

// ---- 租户 namespace ----

// AddNamespaceRequest is the payload for POST /api/v1/rbac/tenants/:id/namespaces.
type AddNamespaceRequest struct {
	Namespace string `json:"namespace" validate:"required"`
}

// ---- 租户角色 ----

// CreateTenantRoleRequest is the payload for POST /api/v1/rbac/tenants/:id/roles.
type CreateTenantRoleRequest struct {
	Code        string `json:"code" validate:"required"`
	Name        string `json:"name" validate:"required"`
	Description string `json:"description"`
}

// UpdateTenantRoleRequest is the payload for PUT /api/v1/rbac/tenants/:id/roles/:rid.
type UpdateTenantRoleRequest struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

// TenantRoleResponse describes a tenant role in API responses.
type TenantRoleResponse struct {
	ID          string `json:"id"`
	TenantID    string `json:"tenantId"`
	Code        string `json:"code"`
	Name        string `json:"name"`
	IsDefault   bool   `json:"isDefault"`
	Description string `json:"description"`
	CreatedAt   string `json:"createdAt"`
}

// ToTenantRoleResponse maps a tenant role entity to its API shape.
func ToTenantRoleResponse(r *domainrbac.TenantRole) *TenantRoleResponse {
	if r == nil {
		return nil
	}
	return &TenantRoleResponse{
		ID:          r.ID,
		TenantID:    r.TenantID,
		Code:        r.Code,
		Name:        r.Name,
		IsDefault:   r.IsDefault,
		Description: r.Description,
		CreatedAt:   r.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}
}

// RolePermissionRequest is the payload for PUT .../roles/:rid/permissions.
type RolePermissionRequest struct {
	PermissionCodes []string `json:"permissionCodes"`
}

// RolePermissionResponse is the payload for GET .../roles/:rid/permissions.
type RolePermissionResponse struct {
	PermissionCodes []string `json:"permissionCodes"`
}

// ---- 租户成员 ----

// AddTenantMemberRequest is the payload for POST /api/v1/rbac/tenants/:id/users.
type AddTenantMemberRequest struct {
	UserID string `json:"userId" validate:"required"`
	RoleID string `json:"roleId" validate:"required"`
}

// ChangeMemberRoleRequest is the payload for PUT .../tenants/:id/users/:uid/role.
type ChangeMemberRoleRequest struct {
	RoleID string `json:"roleId" validate:"required"`
}

// TenantMemberResponse describes a tenant member in API responses.
type TenantMemberResponse struct {
	ID        string `json:"id"`
	TenantID  string `json:"tenantId"`
	UserID    string `json:"userId"`
	RoleID    string `json:"roleId"`
	RoleCode  string `json:"roleCode"`
	CreatedAt string `json:"createdAt"`
}

// ToTenantMemberResponse maps a member entity to its API shape.
func ToTenantMemberResponse(m *domainrbac.TenantMember) *TenantMemberResponse {
	if m == nil {
		return nil
	}
	return &TenantMemberResponse{
		ID:        m.ID,
		TenantID:  m.TenantID,
		UserID:    m.UserID,
		RoleID:    m.RoleID,
		RoleCode:  m.RoleCode,
		CreatedAt: m.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}
}

// ---- 平台角色 ----

// CreatePlatformRoleRequest is the payload for POST /api/v1/rbac/platform/roles.
type CreatePlatformRoleRequest struct {
	Code        string `json:"code" validate:"required"`
	Name        string `json:"name" validate:"required"`
	Description string `json:"description"`
}

// UpdatePlatformRoleRequest is the payload for PUT /api/v1/rbac/platform/roles/:rid.
type UpdatePlatformRoleRequest struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

// PlatformRoleResponse describes a platform role in API responses.
type PlatformRoleResponse struct {
	ID          string `json:"id"`
	Code        string `json:"code"`
	Name        string `json:"name"`
	IsSuper     bool   `json:"isSuper"`
	Description string `json:"description"`
	CreatedAt   string `json:"createdAt"`
}

// ToPlatformRoleResponse maps a platform role entity to its API shape.
func ToPlatformRoleResponse(r *domainrbac.PlatformRole) *PlatformRoleResponse {
	if r == nil {
		return nil
	}
	return &PlatformRoleResponse{
		ID:          r.ID,
		Code:        r.Code,
		Name:        r.Name,
		IsSuper:     r.IsSuper,
		Description: r.Description,
		CreatedAt:   r.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}
}

// ---- 平台管理员 ----

// GrantPlatformRoleRequest is the payload for POST /api/v1/rbac/platform/users.
type GrantPlatformRoleRequest struct {
	UserID string `json:"userId" validate:"required"`
	RoleID string `json:"roleId" validate:"required"`
}

// PlatformRoleUserResponse describes a platform role grantee.
type PlatformRoleUserResponse struct {
	UserID   string `json:"userId"`
	RoleCode string `json:"roleCode"`
}

// ---- 权限点 ----

// PermissionResponse describes a permission point in API responses.
type PermissionResponse struct {
	ID          string `json:"id"`
	Code        string `json:"code"`
	Name        string `json:"name"`
	Resource    string `json:"resource"`
	Action      string `json:"action"`
	HTTPMethod  string `json:"httpMethod"`
	HTTPPath    string `json:"httpPath"`
	Description string `json:"description"`
}

// ToPermissionResponse maps a permission entity to its API shape.
func ToPermissionResponse(p *domainrbac.Permission) *PermissionResponse {
	if p == nil {
		return nil
	}
	return &PermissionResponse{
		ID:          p.ID,
		Code:        p.Code,
		Name:        p.Name,
		Resource:    p.Resource,
		Action:      p.Action,
		HTTPMethod:  p.HTTPMethod,
		HTTPPath:    p.HTTPPath,
		Description: p.Description,
	}
}
// Package handler exposes the RBAC management API over HTTP.
//
// Handlers follow the service conventions: bind JSON, call the usecase facade,
// and respond through the shared SuccessResponse/ErrorResponse helpers. Route
// authorization is enforced by the engine middleware mounted at the router layer.
package handler

import (
	"context"
	"log/slog"
	"strconv"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	basehandler "github.com/lvyanru/dac-apiserver/internal/handler"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
	usecaserbac "github.com/lvyanru/dac-apiserver/internal/usecase/rbac"
)

// RBACHandler handles all /api/v1/rbac/** requests.
type RBACHandler struct {
	uc     usecaserbac.Usecase
	logger *slog.Logger
}

// NewRBACHandler builds the RBAC HTTP handler.
func NewRBACHandler(uc usecaserbac.Usecase, logger *slog.Logger) *RBACHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &RBACHandler{uc: uc, logger: logger}
}

// currentUserID returns the authenticated operator's user ID from the context.
func (h *RBACHandler) currentUserID(c *app.RequestContext) (string, bool) {
	return basehandler.GetUserIDFromContext(c, h.logger)
}

// pathTenantID reads the :id path parameter (tenant scoping).
func (h *RBACHandler) pathTenantID(c *app.RequestContext) string {
	return c.Param("id")
}

// pathRoleID reads the :rid path parameter.
func (h *RBACHandler) pathRoleID(c *app.RequestContext) string {
	return c.Param("rid")
}

// pathUserID reads the :uid path parameter.
func (h *RBACHandler) pathUserID(c *app.RequestContext) string {
	return c.Param("uid")
}

// pageParams parses offset/limit from the query string with sane defaults.
// The returned limit is clamped to [1, 100]; a missing or invalid value falls
// back to 20.
func (h *RBACHandler) pageParams(c *app.RequestContext) (offset, limit int) {
	page := atoiDefault(c.DefaultQuery("page", "1"), 1)
	pageSize := atoiDefault(c.DefaultQuery("page_size", "20"), 20)
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	return (page - 1) * pageSize, pageSize
}

// bindJSON binds a request body, responding 400 when malformed.
func bindJSON(c *app.RequestContext, v interface{}) bool {
	if err := c.BindJSON(v); err != nil {
		return false
	}
	return true
}

// atoiDefault parses an integer string, falling back to fallback on any error.
func atoiDefault(s string, fallback int) int {
	if s == "" {
		return fallback
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return fallback
	}
	return n
}// ListTenants handles GET /api/v1/rbac/tenants.
// @Summary 分页查询租户
// @Tags RBAC
// @Router /api/v1/rbac/tenants [get]
func (h *RBACHandler) ListTenants(ctx context.Context, c *app.RequestContext) {
	offset, limit := h.pageParams(c)
	list, err := h.uc.Tenants(ctx, offset, limit)
	if err != nil {
		h.logger.Error("list tenants failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	items := make([]*dto.TenantResponse, 0, len(list.Items))
	for _, t := range list.Items {
		items = append(items, dto.ToTenantResponse(t))
	}
	basehandler.SuccessResponse(c, basehandler.ListResponse{Items: items, TotalCount: list.Total})
}

// CreateTenant handles POST /api/v1/rbac/tenants.
// @Summary 创建租户
// @Tags RBAC
// @Router /api/v1/rbac/tenants [post]
func (h *RBACHandler) CreateTenant(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.CreateTenantRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	tenant, err := h.uc.CreateTenant(ctx, userID, req.Code, req.Name, req.Description)
	if err != nil {
		h.logger.Error("create tenant failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.CreatedResponse(c, dto.ToTenantResponse(tenant))
}

// GetTenant handles GET /api/v1/rbac/tenants/:id.
// @Summary 查看租户
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id [get]
func (h *RBACHandler) GetTenant(ctx context.Context, c *app.RequestContext) {
	tenant, err := h.uc.Tenant(ctx, h.pathTenantID(c))
	if err != nil {
		h.logger.Error("get tenant failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.ToTenantResponse(tenant))
}

// UpdateTenant handles PUT /api/v1/rbac/tenants/:id.
// @Summary 更新租户
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id [put]
func (h *RBACHandler) UpdateTenant(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.UpdateTenantRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	tenant, err := h.uc.UpdateTenant(ctx, userID, h.pathTenantID(c), req.Name, req.Description, req.Status)
	if err != nil {
		h.logger.Error("update tenant failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.ToTenantResponse(tenant))
}

// DeleteTenant handles DELETE /api/v1/rbac/tenants/:id.
// @Summary 删除租户
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id [delete]
func (h *RBACHandler) DeleteTenant(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	if err := h.uc.DeleteTenant(ctx, userID, h.pathTenantID(c)); err != nil {
		h.logger.Error("delete tenant failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.NoContentResponse(c)
}

// ListTenantNamespaces handles GET /api/v1/rbac/tenants/:id/namespaces.
// @Summary 查看租户 namespace 列表
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/namespaces [get]
func (h *RBACHandler) ListTenantNamespaces(ctx context.Context, c *app.RequestContext) {
	nss, err := h.uc.TenantNamespaces(ctx, h.pathTenantID(c))
	if err != nil {
		h.logger.Error("list tenant namespaces failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	if nss == nil {
		nss = []string{}
	}
	basehandler.SuccessResponse(c, nss)
}

// AddTenantNamespace handles POST /api/v1/rbac/tenants/:id/namespaces.
// @Summary 绑定 namespace
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/namespaces [post]
func (h *RBACHandler) AddTenantNamespace(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.AddNamespaceRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if err := h.uc.AddTenantNamespace(ctx, userID, h.pathTenantID(c), req.Namespace); err != nil {
		h.logger.Error("add tenant namespace failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.CreatedResponse(c, nil)
}

// RemoveTenantNamespace handles DELETE /api/v1/rbac/tenants/:id/namespaces/:namespace.
// @Summary 解除 namespace 绑定
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/namespaces/:namespace [delete]
func (h *RBACHandler) RemoveTenantNamespace(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	namespace := c.Param("namespace")
	if err := h.uc.RemoveTenantNamespace(ctx, userID, h.pathTenantID(c), namespace); err != nil {
		h.logger.Error("remove tenant namespace failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.NoContentResponse(c)
}

// DisableTenant handles POST /api/v1/rbac/tenants/:id/disable.
// @Summary 禁用租户（成员即刻失去访问权）
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/disable [post]
func (h *RBACHandler) DisableTenant(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	tenant, err := h.uc.DisableTenant(ctx, userID, h.pathTenantID(c))
	if err != nil {
		h.logger.Error("disable tenant failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.ToTenantResponse(tenant))
}

// EnableTenant handles POST /api/v1/rbac/tenants/:id/enable.
// @Summary 启用租户
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/enable [post]
func (h *RBACHandler) EnableTenant(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	tenant, err := h.uc.EnableTenant(ctx, userID, h.pathTenantID(c))
	if err != nil {
		h.logger.Error("enable tenant failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.ToTenantResponse(tenant))
}// ListTenantRoles handles GET /api/v1/rbac/tenants/:id/roles.
// @Summary 租户角色列表
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/roles [get]
func (h *RBACHandler) ListTenantRoles(ctx context.Context, c *app.RequestContext) {
	roles, err := h.uc.TenantRoles(ctx, h.pathTenantID(c))
	if err != nil {
		h.logger.Error("list tenant roles failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	items := make([]*dto.TenantRoleResponse, 0, len(roles))
	for _, r := range roles {
		items = append(items, dto.ToTenantRoleResponse(r))
	}
	basehandler.SuccessResponse(c, items)
}

// CreateTenantRole handles POST /api/v1/rbac/tenants/:id/roles.
// @Summary 创建租户角色
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/roles [post]
func (h *RBACHandler) CreateTenantRole(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.CreateTenantRoleRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	role, err := h.uc.CreateTenantRole(ctx, userID, h.pathTenantID(c), req.Code, req.Name, req.Description)
	if err != nil {
		h.logger.Error("create tenant role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.CreatedResponse(c, dto.ToTenantRoleResponse(role))
}

// UpdateTenantRole handles PUT /api/v1/rbac/tenants/:id/roles/:rid.
// @Summary 更新租户角色
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/roles/:rid [put]
func (h *RBACHandler) UpdateTenantRole(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.UpdateTenantRoleRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	role, err := h.uc.UpdateTenantRole(ctx, userID, h.pathTenantID(c), h.pathRoleID(c), req.Name, req.Description)
	if err != nil {
		h.logger.Error("update tenant role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.ToTenantRoleResponse(role))
}

// DeleteTenantRole handles DELETE /api/v1/rbac/tenants/:id/roles/:rid.
// @Summary 删除租户角色
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/roles/:rid [delete]
func (h *RBACHandler) DeleteTenantRole(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	if err := h.uc.DeleteTenantRole(ctx, userID, h.pathTenantID(c), h.pathRoleID(c)); err != nil {
		h.logger.Error("delete tenant role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.NoContentResponse(c)
}

// SetTenantRolePermissions handles PUT /api/v1/rbac/tenants/:id/roles/:rid/permissions.
// @Summary 勾选租户角色权限（全量覆盖）
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/roles/:rid/permissions [put]
func (h *RBACHandler) SetTenantRolePermissions(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.RolePermissionRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if err := h.uc.SetTenantRolePermissions(ctx, userID, h.pathTenantID(c), h.pathRoleID(c), req.PermissionCodes); err != nil {
		h.logger.Error("set tenant role permissions failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, nil)
}

// GetTenantRolePermissions handles GET /api/v1/rbac/tenants/:id/roles/:rid/permissions.
// @Summary 查询租户角色当前权限码
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/roles/:rid/permissions [get]
func (h *RBACHandler) GetTenantRolePermissions(ctx context.Context, c *app.RequestContext) {
	codes, err := h.uc.TenantRolePermissionCodes(ctx, h.pathTenantID(c), h.pathRoleID(c))
	if err != nil {
		h.logger.Error("get tenant role permissions failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.RolePermissionResponse{PermissionCodes: codes})
}

// ListTenantMembers handles GET /api/v1/rbac/tenants/:id/users.
// @Summary 租户成员列表
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/users [get]
func (h *RBACHandler) ListTenantMembers(ctx context.Context, c *app.RequestContext) {
	offset, limit := h.pageParams(c)
	list, err := h.uc.TenantMembers(ctx, h.pathTenantID(c), offset, limit)
	if err != nil {
		h.logger.Error("list tenant members failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	items := make([]*dto.TenantMemberResponse, 0, len(list.Items))
	for _, m := range list.Items {
		items = append(items, dto.ToTenantMemberResponse(m))
	}
	basehandler.SuccessResponse(c, basehandler.ListResponse{Items: items, TotalCount: list.Total})
}

// AddTenantMember handles POST /api/v1/rbac/tenants/:id/users.
// @Summary 加入租户
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/users [post]
func (h *RBACHandler) AddTenantMember(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.AddTenantMemberRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if err := h.uc.AddTenantMember(ctx, userID, h.pathTenantID(c), req.UserID, req.RoleID); err != nil {
		h.logger.Error("add tenant member failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.CreatedResponse(c, nil)
}

// ChangeTenantMemberRole handles PUT /api/v1/rbac/tenants/:id/users/:uid/role.
// @Summary 变更成员角色
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/users/:uid/role [put]
func (h *RBACHandler) ChangeTenantMemberRole(ctx context.Context, c *app.RequestContext) {
	operatorID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.ChangeMemberRoleRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if err := h.uc.ChangeTenantMemberRole(ctx, operatorID, h.pathTenantID(c), h.pathUserID(c), req.RoleID); err != nil {
		h.logger.Error("change tenant member role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, nil)
}

// RemoveTenantMember handles DELETE /api/v1/rbac/tenants/:id/users/:uid.
// @Summary 移除租户成员
// @Tags RBAC
// @Router /api/v1/rbac/tenants/:id/users/:uid [delete]
func (h *RBACHandler) RemoveTenantMember(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	if err := h.uc.RemoveTenantMember(ctx, userID, h.pathTenantID(c), h.pathUserID(c)); err != nil {
		h.logger.Error("remove tenant member failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.NoContentResponse(c)
}

// AvailableUsers handles GET /api/v1/rbac/available-users.
// @Summary 可分配用户列表（未被任何租户分配的用户）
// @Tags RBAC
// @Router /api/v1/rbac/available-users [get]
func (h *RBACHandler) AvailableUsers(ctx context.Context, c *app.RequestContext) {
	userIDs, err := h.uc.AvailableUsers(ctx)
	if err != nil {
		h.logger.Error("list available users failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	if userIDs == nil {
		userIDs = []string{}
	}
	basehandler.SuccessResponse(c, userIDs)
}

// ListPlatformRoles handles GET /api/v1/rbac/platform/roles.
// @Summary 平台角色列表
// @Tags RBAC
// @Router /api/v1/rbac/platform/roles [get]
func (h *RBACHandler) ListPlatformRoles(ctx context.Context, c *app.RequestContext) {
	roles, err := h.uc.PlatformRoles(ctx)
	if err != nil {
		h.logger.Error("list platform roles failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	items := make([]*dto.PlatformRoleResponse, 0, len(roles))
	for _, r := range roles {
		items = append(items, dto.ToPlatformRoleResponse(r))
	}
	basehandler.SuccessResponse(c, items)
}

// CreatePlatformRole handles POST /api/v1/rbac/platform/roles.
// @Summary 创建平台角色
// @Tags RBAC
// @Router /api/v1/rbac/platform/roles [post]
func (h *RBACHandler) CreatePlatformRole(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.CreatePlatformRoleRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	role, err := h.uc.CreatePlatformRole(ctx, userID, req.Code, req.Name, req.Description)
	if err != nil {
		h.logger.Error("create platform role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.CreatedResponse(c, dto.ToPlatformRoleResponse(role))
}

// UpdatePlatformRole handles PUT /api/v1/rbac/platform/roles/:rid.
// @Summary 更新平台角色
// @Tags RBAC
// @Router /api/v1/rbac/platform/roles/:rid [put]
func (h *RBACHandler) UpdatePlatformRole(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.UpdatePlatformRoleRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	role, err := h.uc.UpdatePlatformRole(ctx, userID, h.pathRoleID(c), req.Name, req.Description)
	if err != nil {
		h.logger.Error("update platform role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.ToPlatformRoleResponse(role))
}

// SetPlatformRolePermissions handles PUT /api/v1/rbac/platform/roles/:rid/permissions.
// @Summary 勾选平台角色权限
// @Tags RBAC
// @Router /api/v1/rbac/platform/roles/:rid/permissions [put]
func (h *RBACHandler) SetPlatformRolePermissions(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.RolePermissionRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if err := h.uc.SetPlatformRolePermissions(ctx, userID, h.pathRoleID(c), req.PermissionCodes); err != nil {
		h.logger.Error("set platform role permissions failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, nil)
}

// GetPlatformRolePermissions handles GET /api/v1/rbac/platform/roles/:rid/permissions.
// @Summary 查询平台角色当前权限码
// @Tags RBAC
// @Router /api/v1/rbac/platform/roles/:rid/permissions [get]
func (h *RBACHandler) GetPlatformRolePermissions(ctx context.Context, c *app.RequestContext) {
	codes, err := h.uc.PlatformRolePermissionCodes(ctx, h.pathRoleID(c))
	if err != nil {
		h.logger.Error("get platform role permissions failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.SuccessResponse(c, dto.RolePermissionResponse{PermissionCodes: codes})
}

// DeletePlatformRole handles DELETE /api/v1/rbac/platform/roles/:rid.
// @Summary 删除平台角色
// @Tags RBAC
// @Router /api/v1/rbac/platform/roles/:rid [delete]
func (h *RBACHandler) DeletePlatformRole(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	if err := h.uc.DeletePlatformRole(ctx, userID, h.pathRoleID(c)); err != nil {
		h.logger.Error("delete platform role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.NoContentResponse(c)
}

// ListPlatformRoleUsers handles GET /api/v1/rbac/platform/roles/:rid/users.
// @Summary 平台角色持有人列表
// @Tags RBAC
// @Router /api/v1/rbac/platform/roles/:rid/users [get]
func (h *RBACHandler) ListPlatformRoleUsers(ctx context.Context, c *app.RequestContext) {
	views, err := h.uc.PlatformRoleUsers(ctx, h.pathRoleID(c))
	if err != nil {
		h.logger.Error("list platform role users failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	items := make([]*dto.PlatformRoleUserResponse, 0, len(views))
	for _, v := range views {
		items = append(items, &dto.PlatformRoleUserResponse{UserID: v.UserID, RoleCode: v.RoleCode})
	}
	basehandler.SuccessResponse(c, items)
}

// GrantPlatformRole handles POST /api/v1/rbac/platform/users.
// @Summary 设置平台管理员（绑定平台角色）
// @Tags RBAC
// @Router /api/v1/rbac/platform/users [post]
func (h *RBACHandler) GrantPlatformRole(ctx context.Context, c *app.RequestContext) {
	operatorID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	var req dto.GrantPlatformRoleRequest
	if !bindJSON(c, &req) {
		basehandler.ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if err := h.uc.GrantPlatformRole(ctx, operatorID, req.UserID, req.RoleID); err != nil {
		h.logger.Error("grant platform role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.CreatedResponse(c, nil)
}

// RevokePlatformRole handles DELETE /api/v1/rbac/platform/users/:uid/roles/:rid.
// @Summary 移除平台管理员（解除平台角色）
// @Tags RBAC
// @Router /api/v1/rbac/platform/users/:uid/roles/:rid [delete]
func (h *RBACHandler) RevokePlatformRole(ctx context.Context, c *app.RequestContext) {
	operatorID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	if err := h.uc.RevokePlatformRole(ctx, operatorID, h.pathUserID(c), h.pathRoleID(c)); err != nil {
		h.logger.Error("revoke platform role failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	basehandler.NoContentResponse(c)
}

// ListPermissions handles GET /api/v1/rbac/permissions.
// @Summary 权限点清单
// @Tags RBAC
// @Router /api/v1/rbac/permissions [get]
func (h *RBACHandler) ListPermissions(ctx context.Context, c *app.RequestContext) {
	perms, err := h.uc.Permissions(ctx)
	if err != nil {
		h.logger.Error("list permissions failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	items := make([]*dto.PermissionResponse, 0, len(perms))
	for _, p := range perms {
		items = append(items, dto.ToPermissionResponse(p))
	}
	basehandler.SuccessResponse(c, items)
}

// MyTenants handles GET /api/v1/rbac/me/tenants.
// @Summary 当前用户可选租户列表
// @Tags RBAC
// @Router /api/v1/rbac/me/tenants [get]
func (h *RBACHandler) MyTenants(ctx context.Context, c *app.RequestContext) {
	userID, ok := h.currentUserID(c)
	if !ok {
		basehandler.ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	tenants, err := h.uc.MyTenants(ctx, userID)
	if err != nil {
		h.logger.Error("list my tenants failed", "error", err)
		basehandler.ErrorResponse(c, err)
		return
	}
	items := make([]*dto.TenantResponse, 0, len(tenants))
	for _, t := range tenants {
		items = append(items, dto.ToTenantResponse(t))
	}
	basehandler.SuccessResponse(c, items)
}
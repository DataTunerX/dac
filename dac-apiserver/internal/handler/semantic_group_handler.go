package handler

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type SemanticGroupHandler struct {
	usecase domain.SemanticGroupUsecase
	logger  *slog.Logger
}

// isSemanticGroupVisibleToTenant checks whether the given members slice contains
// at least one member whose DDNamespace belongs to the current tenant's bound
// namespaces. Platform admins always see everything; tenants with no bound
// namespaces see nothing.
func (h *SemanticGroupHandler) isSemanticGroupVisibleToTenant(c *app.RequestContext, members []domain.SemanticGroupMemberDetail) bool {
	if hasPlatformK8sView(c) {
		return true
	}
	allowed, shouldFilter := tenantAllowedNamespaceSet(c)
	if !shouldFilter {
		return true
	}
	if len(allowed) == 0 {
		return false
	}
	for _, member := range members {
		if member.SemanticDomain != nil {
			if _, ok := allowed[member.SemanticDomain.DDNamespace]; ok {
				return true
			}
		}
	}
	return false
}

// filterSemanticGroups fetches members for each group and retains only those
// visible to the current tenant. Platform admins receive the original list
// unchanged.
func (h *SemanticGroupHandler) filterSemanticGroups(ctx context.Context, c *app.RequestContext, groups []domain.SemanticGroup) []domain.SemanticGroup {
	if hasPlatformK8sView(c) {
		return groups
	}
	allowed, shouldFilter := tenantAllowedNamespaceSet(c)
	if !shouldFilter {
		return groups
	}
	if len(allowed) == 0 {
		return nil
	}
	out := make([]domain.SemanticGroup, 0, len(groups))
	for _, g := range groups {
		wm, err := h.usecase.GetWithMembers(ctx, g.ID)
		if err != nil {
			h.logger.Warn("semantic group visibility check: get members failed", "group_id", g.ID, "error", err)
			continue
		}
		if h.isSemanticGroupVisibleToTenant(c, wm.Members) {
			out = append(out, g)
		}
	}
	return out
}

func NewSemanticGroupHandler(uc domain.SemanticGroupUsecase, logger *slog.Logger) *SemanticGroupHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &SemanticGroupHandler{usecase: uc, logger: logger}
}

func (h *SemanticGroupHandler) Create(ctx context.Context, c *app.RequestContext) {
	var req dto.CreateSemanticGroupRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	created, err := h.usecase.Create(ctx, &domain.CreateSemanticGroupRequest{
		GroupName:   req.GroupName,
		Description: req.Description,
		AgentCard:   req.AgentCard,
		Version:     req.Version,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	CreatedResponse(c, dto.ToSemanticGroupResponse(created))
}

func (h *SemanticGroupHandler) BatchCreate(ctx context.Context, c *app.RequestContext) {
	var req []dto.CreateSemanticGroupRequest
	if err := c.BindJSON(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	domainReq := make([]domain.CreateSemanticGroupRequest, 0, len(req))
	for _, r := range req {
		domainReq = append(domainReq, domain.CreateSemanticGroupRequest{
			GroupName:   r.GroupName,
			Description: r.Description,
			AgentCard:   r.AgentCard,
			Version:     r.Version,
		})
	}
	n, err := h.usecase.BatchCreate(ctx, domainReq)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"count": n})
}

func (h *SemanticGroupHandler) Get(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	wm, err := h.usecase.GetWithMembers(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	if !h.isSemanticGroupVisibleToTenant(c, wm.Members) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}
	SuccessResponse(c, dto.ToSemanticGroupResponse(&wm.Group))
}

func (h *SemanticGroupHandler) GetWithMembers(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	w, err := h.usecase.GetWithMembers(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	if !h.isSemanticGroupVisibleToTenant(c, w.Members) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}
	SuccessResponse(c, dto.ToSemanticGroupWithMembersResponse(w))
}

func (h *SemanticGroupHandler) ListRoots(ctx context.Context, c *app.RequestContext) {
	items, _, err := h.usecase.ListRoots(ctx)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	items = h.filterSemanticGroups(ctx, c, items)
	out := make([]*dto.SemanticGroupResponse, 0, len(items))
	for i := range items {
		out = append(out, dto.ToSemanticGroupResponse(&items[i]))
	}
	SuccessResponse(c, map[string]any{
		"items":      out,
		"totalCount": len(out),
	})
}

func (h *SemanticGroupHandler) List(ctx context.Context, c *app.RequestContext) {
	lo := parseLimitOffset(c, 50, 200)
	items, _, err := h.usecase.List(ctx, lo.Limit, lo.Offset)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	items = h.filterSemanticGroups(ctx, c, items)
	out := make([]*dto.SemanticGroupResponse, 0, len(items))
	for i := range items {
		g := items[i]
		out = append(out, dto.ToSemanticGroupResponse(&g))
	}
	SuccessResponse(c, map[string]any{
		"items":      out,
		"totalCount": len(out),
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

func (h *SemanticGroupHandler) Update(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	var req dto.UpdateSemanticGroupRequest
	if err := c.BindJSON(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	updated, err := h.usecase.Update(ctx, id, &domain.UpdateSemanticGroupRequest{
		GroupName:   req.GroupName,
		Description: req.Description,
		AgentCard:   req.AgentCard,
		Version:     req.Version,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSemanticGroupResponse(updated))
}

func (h *SemanticGroupHandler) Delete(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")

	// Block deletion when the semantic group still has members.
	// Members must be removed first (via RemoveMember API) before the group
	// can be deleted. This is a business rule enforced at the application
	// layer rather than at the data-services layer, because other consumers
	// of data-services may have different deletion semantics.
	wm, err := h.usecase.GetWithMembers(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	if len(wm.Members) > 0 {
		ErrorResponse(c, domain.NewInvalidInputError(
			fmt.Sprintf("语义组尚有 %d 个成员，请先移除所有成员后再删除", len(wm.Members)),
		))
		return
	}

	if err := h.usecase.Delete(ctx, id); err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"message": "semantic group deleted successfully"})
}

func (h *SemanticGroupHandler) Exists(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	ok, err := h.usecase.Exists(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"exists": ok})
}

func (h *SemanticGroupHandler) Count(ctx context.Context, c *app.RequestContext) {
	n, err := h.usecase.Count(ctx)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"totalCount": n})
}

func (h *SemanticGroupHandler) AddMember(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	var req dto.AddSemanticGroupMemberRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	result, err := h.usecase.AddMember(ctx, id, &domain.AddSemanticGroupMemberRequest{
		DDNamespace:       req.DDNamespace,
		DDName:            req.DDName,
		AssociationReason: req.AssociationReason,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	AcceptedResponse(c, dto.SemanticGroupMemberTaskSubmitResponse{TaskID: result.TaskID})
}

func (h *SemanticGroupHandler) RemoveMember(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	var req dto.RemoveSemanticGroupMemberRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	result, err := h.usecase.RemoveMember(ctx, id, &domain.RemoveSemanticGroupMemberRequest{
		SemanticDomainID: req.SemanticDomainID,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	AcceptedResponse(c, dto.SemanticGroupMemberTaskSubmitResponse{TaskID: result.TaskID})
}

func (h *SemanticGroupHandler) GetMemberTask(ctx context.Context, c *app.RequestContext) {
	taskID := c.Param("taskId")
	status, err := h.usecase.GetMemberTask(ctx, taskID)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSemanticGroupMemberTaskStatusResponse(status))
}

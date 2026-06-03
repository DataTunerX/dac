package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type SemanticGroupHandler struct {
	usecase domain.SemanticGroupUsecase
	logger  *slog.Logger
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
	g, err := h.usecase.Get(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSemanticGroupResponse(g))
}

func (h *SemanticGroupHandler) GetWithMembers(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	w, err := h.usecase.GetWithMembers(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSemanticGroupWithMembersResponse(w))
}

func (h *SemanticGroupHandler) ListRoots(ctx context.Context, c *app.RequestContext) {
	items, total, err := h.usecase.ListRoots(ctx)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	out := make([]*dto.SemanticGroupResponse, 0, len(items))
	for i := range items {
		out = append(out, dto.ToSemanticGroupResponse(&items[i]))
	}
	SuccessResponse(c, map[string]any{
		"items":      out,
		"totalCount": total,
	})
}

func (h *SemanticGroupHandler) List(ctx context.Context, c *app.RequestContext) {
	lo := parseLimitOffset(c, 50, 200)
	items, total, err := h.usecase.List(ctx, lo.Limit, lo.Offset)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	out := make([]*dto.SemanticGroupResponse, 0, len(items))
	for i := range items {
		g := items[i]
		out = append(out, dto.ToSemanticGroupResponse(&g))
	}
	SuccessResponse(c, map[string]any{
		"items":      out,
		"totalCount": total,
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

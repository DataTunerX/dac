package handler

import (
	"context"
	"log/slog"
	"strconv"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type DDGroupRelationHandler struct {
	usecase domain.DDGroupRelationUsecase
	logger  *slog.Logger
}

func NewDDGroupRelationHandler(uc domain.DDGroupRelationUsecase, logger *slog.Logger) *DDGroupRelationHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &DDGroupRelationHandler{usecase: uc, logger: logger}
}

func (h *DDGroupRelationHandler) Create(ctx context.Context, c *app.RequestContext) {
	var req dto.CreateDDGroupRelationRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	created, err := h.usecase.Create(ctx, &domain.CreateDDGroupRelationRequest{
		SemanticDomainID:  req.SemanticDomainID,
		GroupID:           req.GroupID,
		AssociationReason: req.AssociationReason,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	CreatedResponse(c, dto.ToDDGroupRelationResponse(created))
}

func (h *DDGroupRelationHandler) BatchCreate(ctx context.Context, c *app.RequestContext) {
	var req []dto.CreateDDGroupRelationRequest
	if err := c.BindJSON(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	domainReq := make([]domain.CreateDDGroupRelationRequest, 0, len(req))
	for _, r := range req {
		domainReq = append(domainReq, domain.CreateDDGroupRelationRequest{
			SemanticDomainID:  r.SemanticDomainID,
			GroupID:           r.GroupID,
			AssociationReason: r.AssociationReason,
		})
	}
	n, err := h.usecase.BatchCreate(ctx, domainReq)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"count": n})
}

func (h *DDGroupRelationHandler) ListByGroup(ctx context.Context, c *app.RequestContext) {
	groupID := c.Param("group_id")
	items, total, err := h.usecase.ListByGroup(ctx, groupID)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	out := make([]*dto.DDGroupRelationResponse, 0, len(items))
	for i := range items {
		r := items[i]
		out = append(out, dto.ToDDGroupRelationResponse(&r))
	}
	SuccessResponse(c, map[string]any{"items": out, "totalCount": total})
}

func (h *DDGroupRelationHandler) ListBySD(ctx context.Context, c *app.RequestContext) {
	sdID := c.Param("sd_id")
	items, total, err := h.usecase.ListBySemanticDomain(ctx, sdID)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	out := make([]*dto.DDGroupRelationResponse, 0, len(items))
	for i := range items {
		r := items[i]
		out = append(out, dto.ToDDGroupRelationResponse(&r))
	}
	SuccessResponse(c, map[string]any{"items": out, "totalCount": total})
}

func (h *DDGroupRelationHandler) DeleteByID(ctx context.Context, c *app.RequestContext) {
	idStr := c.Param("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if err := h.usecase.DeleteByID(ctx, id); err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"message": "dd group relation deleted successfully"})
}

func (h *DDGroupRelationHandler) DeleteByGroup(ctx context.Context, c *app.RequestContext) {
	groupID := c.Param("group_id")
	if err := h.usecase.DeleteByGroup(ctx, groupID); err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"message": "dd group relations deleted successfully"})
}

func (h *DDGroupRelationHandler) DeleteBySD(ctx context.Context, c *app.RequestContext) {
	sdID := c.Param("sd_id")
	if err := h.usecase.DeleteBySemanticDomain(ctx, sdID); err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"message": "dd group relations deleted successfully"})
}

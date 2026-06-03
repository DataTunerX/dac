package handler

import (
	"context"
	"log/slog"

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

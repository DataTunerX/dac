package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// NamespaceHandler handles namespace listing for UI selections.
type NamespaceHandler struct {
	usecase domain.NamespaceUsecase
	logger  *slog.Logger
}

func NewNamespaceHandler(uc domain.NamespaceUsecase, logger *slog.Logger) *NamespaceHandler {
	return &NamespaceHandler{
		usecase: uc,
		logger:  logger,
	}
}

// List lists namespaces (cluster-scoped)
//
//	@Summary		List Namespaces
//	@Description	List Kubernetes namespaces
//	@Tags			Namespace
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200	{object}	map[string]interface{}
//	@Router			/namespaces [get]
func (h *NamespaceHandler) List(ctx context.Context, c *app.RequestContext) {
	items, err := h.usecase.List(ctx)
	if err != nil {
		h.logger.Error("failed to list namespaces", "error", err)
		ErrorResponse(c, err)
		return
	}

	resp := make([]dto.NamespaceResponse, 0, len(items))
	for _, ns := range items {
		resp = append(resp, dto.ToNamespaceResponse(ns))
	}

	SuccessResponse(c, map[string]interface{}{"items": resp})
}



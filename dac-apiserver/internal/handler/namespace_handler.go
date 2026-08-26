package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
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

// List lists namespaces (tenant-scoped when the request carries an X-Tenant-Id).
//
// Users with platform-level namespace:read permission (including super admins)
// always see all cluster namespaces. For tenant users without that platform
// privilege, only namespaces bound to the active tenant are returned.
func (h *NamespaceHandler) List(ctx context.Context, c *app.RequestContext) {
	items, err := h.usecase.List(ctx)
	if err != nil {
		h.logger.Error("failed to list namespaces", "error", err)
		ErrorResponse(c, err)
		return
	}

	// Platform admins or no tenant context: return all.
	if hasPlatformK8sView(c) {
		writeAllNamespaces(items, c)
		return
	}

	allowed := tenantNamespaces(c)
	if allowed == nil {
		writeAllNamespaces(items, c)
		return
	}

	resp := make([]dto.NamespaceResponse, 0, len(items))
	for _, ns := range items {
		if contains(allowed, ns.Name) {
			resp = append(resp, dto.ToNamespaceResponse(ns))
		}
	}

	SuccessResponse(c, map[string]any{"items": resp})
}

func writeAllNamespaces(items []*entity.Namespace, c *app.RequestContext) {
	resp := make([]dto.NamespaceResponse, 0, len(items))
	for _, ns := range items {
		resp = append(resp, dto.ToNamespaceResponse(ns))
	}
	SuccessResponse(c, map[string]any{"items": resp})
}

func contains(slice []string, target string) bool {
	for _, s := range slice {
		if s == target {
			return true
		}
	}
	return false
}
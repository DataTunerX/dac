package handler

import (
	"context"
	"log/slog"
	"sort"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// ConfigMapHandler handles DAC configmap management.
type ConfigMapHandler struct {
	usecase domain.ConfigMapUsecase
	logger  *slog.Logger
}

func NewConfigMapHandler(uc domain.ConfigMapUsecase, logger *slog.Logger) *ConfigMapHandler {
	return &ConfigMapHandler{
		usecase: uc,
		logger:  logger,
	}
}

// ------- LLM ConfigMap (model management) -------

func (h *ConfigMapHandler) CreateLLM(ctx context.Context, c *app.RequestContext) {
	h.create(ctx, c, domain.ConfigMapTypeLLM)
}

func (h *ConfigMapHandler) GetLLM(ctx context.Context, c *app.RequestContext) {
	h.get(ctx, c)
}

func (h *ConfigMapHandler) ListLLM(ctx context.Context, c *app.RequestContext) {
	h.list(ctx, c, domain.ConfigMapTypeLLM)
}

func (h *ConfigMapHandler) UpdateLLM(ctx context.Context, c *app.RequestContext) {
	h.update(ctx, c)
}

func (h *ConfigMapHandler) DeleteLLM(ctx context.Context, c *app.RequestContext) {
	h.remove(ctx, c)
}

// ------- Prompt ConfigMap (prompt management) -------

func (h *ConfigMapHandler) CreatePrompt(ctx context.Context, c *app.RequestContext) {
	h.create(ctx, c, domain.ConfigMapTypePrompts)
}

func (h *ConfigMapHandler) GetPrompt(ctx context.Context, c *app.RequestContext) {
	h.get(ctx, c)
}

func (h *ConfigMapHandler) ListPrompt(ctx context.Context, c *app.RequestContext) {
	h.list(ctx, c, domain.ConfigMapTypePrompts)
}

func (h *ConfigMapHandler) UpdatePrompt(ctx context.Context, c *app.RequestContext) {
	h.update(ctx, c)
}

func (h *ConfigMapHandler) DeletePrompt(ctx context.Context, c *app.RequestContext) {
	h.remove(ctx, c)
}

// create is an internal helper for creating a configmap of the given type.
func (h *ConfigMapHandler) create(ctx context.Context, c *app.RequestContext, t domain.ConfigMapType) {
	namespace := c.Param("namespace")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

	var req dto.CreateConfigMapRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	created, err := h.usecase.Create(ctx, &domain.CreateConfigMapRequest{
		Namespace: namespace,
		Name:      req.Name,
		Type:      t,
		Labels:    req.Labels,
		Data:      req.Data,
	})
	if err != nil {
		h.logger.Error("failed to create configmap", "error", err)
		ErrorResponse(c, err)
		return
	}
	CreatedResponse(c, dto.ToConfigMapResponse(created))
}

// get is an internal helper for getting a configmap by name.
func (h *ConfigMapHandler) get(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

	cm, err := h.usecase.Get(ctx, namespace, name)
	if err != nil {
		h.logger.Error("failed to get configmap", "error", err, "namespace", namespace, "name", name)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToConfigMapResponse(cm))
}

// list is an internal helper for listing configmaps of the given type.
func (h *ConfigMapHandler) list(ctx context.Context, c *app.RequestContext, t domain.ConfigMapType) {
	namespace := c.Param("namespace")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

	labelSelector := c.Query("labelSelector")
	lo := parseLimitOffset(c, 50, 200)

	opts := domain.ConfigMapListOptions{LabelSelector: labelSelector, Type: t}

	items, err := h.usecase.List(ctx, namespace, opts)
	if err != nil {
		h.logger.Error("failed to list configmaps", "error", err)
		ErrorResponse(c, err)
		return
	}

	sort.Slice(items, func(i, j int) bool {
		return items[i].Name < items[j].Name
	})
	totalCount := len(items)
	items = paginateSlice(items, lo.Offset, lo.Limit)

	resp := make([]dto.ConfigMapResponse, 0, len(items))
	for _, cm := range items {
		resp = append(resp, dto.ToConfigMapResponse(cm))
	}

	SuccessResponse(c, map[string]any{
		"items":      resp,
		"totalCount": totalCount,
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

// update is an internal helper for updating a configmap.
func (h *ConfigMapHandler) update(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

	var req dto.UpdateConfigMapRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	var tPtr *domain.ConfigMapType
	if req.Type != nil && *req.Type != "" {
		t, err := dto.ParseConfigMapType(*req.Type)
		if err != nil {
			ErrorResponse(c, err)
			return
		}
		tPtr = &t
	}

	updated, err := h.usecase.Update(ctx, namespace, name, &domain.UpdateConfigMapRequest{
		Type:   tPtr,
		Labels: req.Labels,
		Data:   req.Data,
	})
	if err != nil {
		h.logger.Error("failed to update configmap", "error", err)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToConfigMapResponse(updated))
}

// remove is an internal helper for deleting a configmap.
func (h *ConfigMapHandler) remove(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

	if err := h.usecase.Delete(ctx, namespace, name); err != nil {
		h.logger.Error("failed to delete configmap", "error", err)
		ErrorResponse(c, err)
		return
	}
	NoContentResponse(c)
}

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

// Create creates a new configmap
//
//	@Summary		Create ConfigMap
//	@Description	Create a DAC configmap (llm/prompts) in the specified namespace
//	@Tags			ConfigMap Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string					true	"namespace"
//	@Param			request		body		dto.CreateConfigMapRequest	true	"configmap"
//	@Success		201			{object}	dto.ConfigMapResponse
//	@Failure		400			{object}	map[string]string
//	@Router			/namespaces/{namespace}/configmaps [post]
func (h *ConfigMapHandler) Create(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")

	var req dto.CreateConfigMapRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	t, err := dto.ParseConfigMapType(req.Type)
	if err != nil {
		ErrorResponse(c, err)
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

// Get gets a configmap
//
//	@Summary		Get ConfigMap
//	@Description	Get a configmap in the specified namespace
//	@Tags			ConfigMap Management
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string	true	"namespace"
//	@Param			name		path		string	true	"configmap name"
//	@Success		200			{object}	dto.ConfigMapResponse
//	@Router			/namespaces/{namespace}/configmaps/{name} [get]
func (h *ConfigMapHandler) Get(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	cm, err := h.usecase.Get(ctx, namespace, name)
	if err != nil {
		h.logger.Error("failed to get configmap", "error", err, "namespace", namespace, "name", name)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToConfigMapResponse(cm))
}

// List lists configmaps
//
//	@Summary		List ConfigMaps
//	@Description	List configmaps in the specified namespace, optionally filtered by type
//	@Tags			ConfigMap Management
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string	true	"namespace"
//	@Param			type		query		string	false	"llm|prompts"
//	@Param			labelSelector	query		string	false	"extra label selector"
//	@Success		200			{object}	map[string]any
//	@Router			/namespaces/{namespace}/configmaps [get]
func (h *ConfigMapHandler) List(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	typeStr := c.Query("type")
	labelSelector := c.Query("labelSelector")
	lo := parseLimitOffset(c, 50, 200)

	opts := domain.ConfigMapListOptions{LabelSelector: labelSelector}
	if typeStr != "" {
		t, err := dto.ParseConfigMapType(typeStr)
		if err != nil {
			ErrorResponse(c, err)
			return
		}
		opts.Type = t
	}

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

// Update updates a configmap
//
//	@Summary		Update ConfigMap
//	@Description	Update a configmap in the specified namespace
//	@Tags			ConfigMap Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string	true	"namespace"
//	@Param			name		path		string	true	"configmap name"
//	@Param			request		body		dto.UpdateConfigMapRequest	true	"configmap"
//	@Success		200			{object}	dto.ConfigMapResponse
//	@Router			/namespaces/{namespace}/configmaps/{name} [put]
func (h *ConfigMapHandler) Update(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

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

// Delete deletes a configmap
//
//	@Summary		Delete ConfigMap
//	@Description	Delete a configmap in the specified namespace
//	@Tags			ConfigMap Management
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string	true	"namespace"
//	@Param			name		path		string	true	"configmap name"
//	@Success		204
//	@Router			/namespaces/{namespace}/configmaps/{name} [delete]
func (h *ConfigMapHandler) Delete(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if err := h.usecase.Delete(ctx, namespace, name); err != nil {
		h.logger.Error("failed to delete configmap", "error", err)
		ErrorResponse(c, err)
		return
	}
	NoContentResponse(c)
}

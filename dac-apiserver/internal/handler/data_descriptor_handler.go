package handler

import (
	"context"
	"log/slog"
	"strconv"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
	"github.com/lvyanru/dac-apiserver/internal/usecase"
)

// DataDescriptorHandler handles data descriptor requests
type DataDescriptorHandler struct {
	usecase usecase.DataDescriptorUsecase
	logger  *slog.Logger
}

// NewDataDescriptorHandler creates a new data descriptor handler
func NewDataDescriptorHandler(uc usecase.DataDescriptorUsecase) *DataDescriptorHandler {
	return &DataDescriptorHandler{
		usecase: uc,
		logger:  slog.Default(),
	}
}

// Create creates a new data descriptor
//
//	@Summary		create数据描述符
//	@Description	在指定命名空间createnewof数据描述符
//	@Tags			数据描述符
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string							true	"Kubernetes namespace"
//	@Param			request		body		dto.CreateDataDescriptorRequest		true	"数据描述符配置"
//	@Success		200			{object}	dto.DataDescriptorResponse			"Created successfully"
//	@Failure		400			{object}	map[string]string				"Invalid request parameters"
//	@Failure		401			{object}	map[string]string				"Unauthorized"
//	@Router			/namespaces/{namespace}/descriptors [post]
func (h *DataDescriptorHandler) Create(ctx context.Context, c *app.RequestContext) {
	var req dto.CreateDataDescriptorRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// Convert to domain request
	domainReq := &domain.CreateDataDescriptorRequest{
		Name:           req.Name,
		Namespace:      req.Namespace,
		Labels:         req.Labels,
		DescriptorType: req.DescriptorType,
		Sources:        req.Sources,
	}

	descriptor, err := h.usecase.Create(ctx, domainReq)
	if err != nil {
		h.logger.Error("failed to create data descriptor", "error", err)
		ErrorResponse(c, err)
		return
	}

	CreatedResponse(c, dto.ToDataDescriptorResponse(descriptor))
}

// Get retrieves a data descriptor
//
//	@Summary		get数据描述符详情
//	@Description	based on名称get指定数据描述符of详细信息
//	@Tags			数据描述符
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string					true	"Kubernetes namespace"
//	@Param			name		path		string					true	"数据描述符名称"
//	@Success		200			{object}	dto.DataDescriptorResponse	"数据描述符详情"
//	@Failure		404			{object}	map[string]string		"数据描述符不exists"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/namespaces/{namespace}/descriptors/{name} [get]
func (h *DataDescriptorHandler) Get(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	descriptor, err := h.usecase.Get(ctx, namespace, name)
	if err != nil {
		h.logger.Error("failed to get data descriptor",
			"namespace", namespace,
			"name", name,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ToDataDescriptorResponse(descriptor))
}

// ListAll lists data descriptors across all namespaces
//
//	@Summary		所有命名空间of数据描述符列表
//	@Description	get所有命名空间下of数据描述符
//	@Tags			数据描述符
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200			{object}	map[string]interface{}	"数据描述符列表"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/descriptors [get]
func (h *DataDescriptorHandler) ListAll(ctx context.Context, c *app.RequestContext) {
	opts := domain.ListOptions{
		AllNamespaces: true,
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	if limit := c.Query("limit"); limit != "" {
		if l, err := strconv.ParseInt(limit, 10, 64); err == nil {
			opts.Limit = l
		}
	}

	opts.Continue = c.Query("continue")

	// namespace parameter is ignored when AllNamespaces is true
	descriptors, err := h.usecase.List(ctx, "", opts)
	if err != nil {
		h.logger.Error("failed to list data descriptors (all namespaces)",
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	// Convert to response DTOs
	items := make([]dto.DataDescriptorResponse, len(descriptors))
	for i, descriptor := range descriptors {
		items[i] = dto.ToDataDescriptorResponse(descriptor)
	}

	SuccessResponse(c, map[string]interface{}{
		"items": items,
		"total": len(items),
	})
}

// List lists data descriptors
//
//	@Summary		数据描述符列表
//	@Description	get指定命名空间下of所有数据描述符
//	@Tags			数据描述符
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string					true	"Kubernetes namespace"
//	@Success		200			{object}	map[string]interface{}	"数据描述符列表"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/namespaces/{namespace}/descriptors [get]
func (h *DataDescriptorHandler) List(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")

	opts := domain.ListOptions{
		AllNamespaces: false, // Explicit: list single namespace
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	if limit := c.Query("limit"); limit != "" {
		if l, err := strconv.ParseInt(limit, 10, 64); err == nil {
			opts.Limit = l
		}
	}

	opts.Continue = c.Query("continue")

	descriptors, err := h.usecase.List(ctx, namespace, opts)
	if err != nil {
		h.logger.Error("failed to list data descriptors",
			"namespace", namespace,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	// Convert to response DTOs
	items := make([]dto.DataDescriptorResponse, len(descriptors))
	for i, descriptor := range descriptors {
		items[i] = dto.ToDataDescriptorResponse(descriptor)
	}

	SuccessResponse(c, map[string]interface{}{
		"items": items,
		"total": len(items),
	})
}

// Update updates a data descriptor
//
//	@Summary		更new数据描述符
//	@Description	更new指定数据描述符of配置
//	@Tags			数据描述符
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string							true	"Kubernetes namespace"
//	@Param			name		path		string							true	"数据描述符名称"
//	@Param			request		body		dto.UpdateDataDescriptorRequest		true	"更new内容"
//	@Success		200			{object}	dto.DataDescriptorResponse			"Updated successfully"
//	@Failure		400			{object}	map[string]string				"Invalid request parameters"
//	@Failure		404			{object}	map[string]string				"数据描述符不exists"
//	@Failure		401			{object}	map[string]string				"Unauthorized"
//	@Router			/namespaces/{namespace}/descriptors/{name} [put]
func (h *DataDescriptorHandler) Update(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	var req dto.UpdateDataDescriptorRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// Convert to domain request
	domainReq := &domain.UpdateDataDescriptorRequest{
		Labels:         req.Labels,
		DescriptorType: req.DescriptorType,
		Sources:        req.Sources,
	}

	descriptor, err := h.usecase.Update(ctx, namespace, name, domainReq)
	if err != nil {
		h.logger.Error("failed to update data descriptor",
			"namespace", namespace,
			"name", name,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ToDataDescriptorResponse(descriptor))
}

// Delete deletes a data descriptor
//
//	@Summary		删除数据描述符
//	@Description	删除指定of数据描述符
//	@Tags			数据描述符
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string				true	"Kubernetes namespace"
//	@Param			name		path		string				true	"数据描述符名称"
//	@Success		200			{object}	map[string]string	"Deleted successfully"
//	@Failure		404			{object}	map[string]string	"数据描述符不exists"
//	@Failure		401			{object}	map[string]string	"Unauthorized"
//	@Router			/namespaces/{namespace}/descriptors/{name} [delete]
func (h *DataDescriptorHandler) Delete(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if err := h.usecase.Delete(ctx, namespace, name); err != nil {
		h.logger.Error("failed to delete data descriptor",
			"namespace", namespace,
			"name", name,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, map[string]string{
		"message": "data descriptor deleted successfully",
	})
}

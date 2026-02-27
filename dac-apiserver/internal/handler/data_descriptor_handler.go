package handler

import (
	"context"
	"log/slog"
	"sort"
	"strings"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// Allowed descriptorType values; aligned with execution-engine (structured-mysql, structured-postgres, unstructured, code).
var allowedDescriptorTypes = map[string]struct{}{
	"structured-mysql":    {},
	"structured-postgres": {},
	"unstructured":        {},
	"code":                {},
}

func isValidDescriptorType(t string) bool {
	t = strings.TrimSpace(t)
	_, ok := allowedDescriptorTypes[t]
	return ok
}

func normalizeDataSourceType(t string) string {
	v := strings.TrimSpace(strings.ToLower(t))
	// Align with execution-engine samples: use "gitee" (not "gitea").
	if v == "gitea" {
		return "gitee"
	}
	return t
}

// DataDescriptorHandler handles data descriptor requests
type DataDescriptorHandler struct {
	usecase domain.DataDescriptorUsecase // Changed from usecase.DataDescriptorUsecase to domain interface
	logger  *slog.Logger
}

// NewDataDescriptorHandler creates a new data descriptor handler
func NewDataDescriptorHandler(uc domain.DataDescriptorUsecase, logger *slog.Logger) *DataDescriptorHandler {
	return &DataDescriptorHandler{
		usecase: uc,
		logger:  logger,
	}
}

// Create creates a new data descriptor
func (h *DataDescriptorHandler) Create(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")

	var req dto.CreateDataDescriptorRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if !isValidDescriptorType(req.DescriptorType) {
		h.logger.Error("invalid descriptorType", "descriptorType", req.DescriptorType)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// Normalize source types to match execution-engine conventions.
	for i := range req.Sources {
		req.Sources[i].Type = normalizeDataSourceType(req.Sources[i].Type)
	}

	// Convert to domain request
	domainReq := &domain.CreateDataDescriptorRequest{
		Name:           req.Name,
		Namespace:      namespace,
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

	resp := dto.ToDataDescriptorResponse(descriptor)
	
	SuccessResponse(c, resp)
}

// GetSignature retrieves signature info (metadata hash, location, etc.) for a data descriptor.
func (h *DataDescriptorHandler) GetSignature(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	// Ensure DD exists
	if _, err := h.usecase.Get(ctx, namespace, name); err != nil {
		ErrorResponse(c, err)
		return
	}

	sig, err := h.usecase.GetSignatureByDD(ctx, namespace, name)
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	// Return nil data when not found, wrapped by standard response
	SuccessResponse(c, dto.ToDataDescriptorSignatureResponse(sig))
}

// GetSemanticDomain retrieves semantic domain + agent_card for a data descriptor.
func (h *DataDescriptorHandler) GetSemanticDomain(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	// Ensure DD exists
	if _, err := h.usecase.Get(ctx, namespace, name); err != nil {
		ErrorResponse(c, err)
		return
	}

	sd, err := h.usecase.GetSemanticDomainByDD(ctx, namespace, name)
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ToDataDescriptorSemanticDomainResponse(sd))
}

// ListAll lists data descriptors across all namespaces
func (h *DataDescriptorHandler) ListAll(ctx context.Context, c *app.RequestContext) {
	lo := parseLimitOffset(c, 50, 200)
	opts := domain.ListOptions{
		AllNamespaces: true,
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	opts.Limit = 0
	opts.Continue = ""

	// namespace parameter is ignored when AllNamespaces is true
	descriptors, err := h.usecase.List(ctx, "", opts)
	if err != nil {
		h.logger.Error("failed to list data descriptors (all namespaces)",
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	sort.Slice(descriptors, func(i, j int) bool {
		if descriptors[i].Namespace != descriptors[j].Namespace {
			return descriptors[i].Namespace < descriptors[j].Namespace
		}
		return descriptors[i].Name < descriptors[j].Name
	})
	totalCount := len(descriptors)
	descriptors = paginateSlice(descriptors, lo.Offset, lo.Limit)

	items := make([]dto.DataDescriptorResponse, len(descriptors))
	for i, descriptor := range descriptors {
		items[i] = dto.ToDataDescriptorResponse(descriptor)
	}
	SuccessResponse(c, map[string]interface{}{
		"items":      items,
		"totalCount": totalCount,
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

// List lists data descriptors
func (h *DataDescriptorHandler) List(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	lo := parseLimitOffset(c, 50, 200)

	opts := domain.ListOptions{
		AllNamespaces: false, // Explicit: list single namespace
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	opts.Limit = 0
	opts.Continue = ""

	descriptors, err := h.usecase.List(ctx, namespace, opts)
	if err != nil {
		h.logger.Error("failed to list data descriptors",
			"namespace", namespace,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	sort.Slice(descriptors, func(i, j int) bool {
		return descriptors[i].Name < descriptors[j].Name
	})
	totalCount := len(descriptors)
	descriptors = paginateSlice(descriptors, lo.Offset, lo.Limit)

	items := make([]dto.DataDescriptorResponse, len(descriptors))
	for i, descriptor := range descriptors {
		items[i] = dto.ToDataDescriptorResponse(descriptor)
	}

	SuccessResponse(c, map[string]interface{}{
		"items":      items,
		"totalCount": totalCount,
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

// Update updates a data descriptor
func (h *DataDescriptorHandler) Update(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	var req dto.UpdateDataDescriptorRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if req.DescriptorType != "" && !isValidDescriptorType(req.DescriptorType) {
		h.logger.Error("invalid descriptorType", "descriptorType", req.DescriptorType)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	for i := range req.Sources {
		req.Sources[i].Type = normalizeDataSourceType(req.Sources[i].Type)
	}

	// Convert to domain request
	var descriptorType *string
	if req.DescriptorType != "" {
		descriptorType = &req.DescriptorType
	}

	domainReq := &domain.UpdateDataDescriptorRequest{
		Labels:         req.Labels,
		DescriptorType: descriptorType,
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

// SearchKnowledge searches for knowledge fragments
func (h *DataDescriptorHandler) SearchKnowledge(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")
	
	type searchReq struct {
		Query string `json:"query" query:"query"`
	}
	var req searchReq
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid search request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if req.Query == "" {
		req.Query = c.Query("query") // Try query param if body is empty
	}

	results, err := h.usecase.SearchKnowledge(ctx, namespace, name, req.Query)
	if err != nil {
		h.logger.Error("failed to search knowledge", "error", err)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, map[string]interface{}{
		"results": results,
		"total": len(results),
	})
}

// GetKnowledge retrieves all knowledge fragments
func (h *DataDescriptorHandler) GetKnowledge(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	results, err := h.usecase.GetAllKnowledge(ctx, namespace, name)
	if err != nil {
		h.logger.Error("failed to get all knowledge", "error", err)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, map[string]interface{}{
		"results": results,
		"total":   len(results),
	})
}

// DeleteKnowledge deletes knowledge fragments
func (h *DataDescriptorHandler) DeleteKnowledge(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	type deleteReq struct {
		DocumentIDs []string `json:"documents"`
	}
	var req deleteReq
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid delete knowledge request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	if err := h.usecase.DeleteKnowledge(ctx, namespace, name, req.DocumentIDs); err != nil {
		h.logger.Error("failed to delete knowledge", "error", err)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, map[string]string{
		"message": "knowledge fragments deleted successfully",
	})
}

package handler

import (
	"context"
	"log/slog"
	"sort"
	"strings"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
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

func isValidGPUEnabled(v string) bool {
	v = strings.TrimSpace(v)
	return v == "" || v == "yes" || v == "no"
}

func normalizeGPUEnabled(v string) string {
	return entity.NormalizeGPUEnabled(strings.TrimSpace(v))
}

func isValidPDFLoader(v string) bool {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "", "auto", "ocr", "text":
		return true
	default:
		return false
	}
}

func normalizePDFLoader(v string) string {
	return entity.NormalizePDFLoader(strings.TrimSpace(v))
}

func normalizeDataSourceType(t string) string {
	// No type aliasing today; kept as a single chokepoint so future
	// renames (e.g. legacy → canonical) don't have to chase callers.
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

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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
	if !isValidGPUEnabled(req.GPUEnabled) {
		h.logger.Error("invalid gpuEnabled", "gpuEnabled", req.GPUEnabled)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if !isValidPDFLoader(req.PDFLoader) {
		h.logger.Error("invalid pdfLoader", "pdfLoader", req.PDFLoader)
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
		GPUEnabled:     normalizeGPUEnabled(req.GPUEnabled),
		PDFLoader:      normalizePDFLoader(req.PDFLoader),
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

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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

	// Tenant namespace isolation: filter to only the namespaces bound to the
	// active tenant. Platform admins and super admins see all.
	descriptors = filterByTenantNamespaces(descriptors, func(d *entity.DataDescriptor) string { return d.Namespace }, c, h.logger)

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
	SuccessResponse(c, map[string]any{
		"items":      items,
		"totalCount": totalCount,
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

// List lists data descriptors
func (h *DataDescriptorHandler) List(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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

	SuccessResponse(c, map[string]any{
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

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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
	if !isValidGPUEnabled(req.GPUEnabled) {
		h.logger.Error("invalid gpuEnabled", "gpuEnabled", req.GPUEnabled)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	if !isValidPDFLoader(req.PDFLoader) {
		h.logger.Error("invalid pdfLoader", "pdfLoader", req.PDFLoader)
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
	var gpuEnabled *string
	if req.GPUEnabled != "" {
		normalized := normalizeGPUEnabled(req.GPUEnabled)
		gpuEnabled = &normalized
	}
	var pdfLoader *string
	if req.PDFLoader != "" {
		normalized := normalizePDFLoader(req.PDFLoader)
		pdfLoader = &normalized
	}

	domainReq := &domain.UpdateDataDescriptorRequest{
		Labels:         req.Labels,
		DescriptorType: descriptorType,
		GPUEnabled:     gpuEnabled,
		PDFLoader:      pdfLoader,
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

// RequestResync sets the sync-requested-at annotation so Ready DDs re-run ingestion.
func (h *DataDescriptorHandler) RequestResync(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

	if err := h.usecase.RequestResync(ctx, namespace, name); err != nil {
		h.logger.Error("failed to request data descriptor resync",
			"namespace", namespace,
			"name", name,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	AcceptedResponse(c, map[string]string{
		"namespace": namespace,
		"name":      name,
		"status":    "resync_requested",
	})
}

// Delete deletes a data descriptor
func (h *DataDescriptorHandler) Delete(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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

	SuccessResponse(c, map[string]any{
		"results": results,
		"total":   len(results),
	})
}

// GetKnowledge retrieves all knowledge fragments
func (h *DataDescriptorHandler) GetKnowledge(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

	results, err := h.usecase.GetAllKnowledge(ctx, namespace, name)
	if err != nil {
		h.logger.Error("failed to get all knowledge", "error", err)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, map[string]any{
		"results": results,
		"total":   len(results),
	})
}

// DeleteKnowledge deletes knowledge fragments
func (h *DataDescriptorHandler) DeleteKnowledge(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}

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

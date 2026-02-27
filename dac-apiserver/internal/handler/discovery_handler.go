package handler

import (
	"context"
	"log/slog"
	"strconv"
	"time"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type DiscoveryHandler struct {
	usecase domain.DiscoveryUsecase
	logger  *slog.Logger
}

func NewDiscoveryHandler(uc domain.DiscoveryUsecase, logger *slog.Logger) *DiscoveryHandler {
	return &DiscoveryHandler{usecase: uc, logger: logger}
}

// StartScan starts an async discovery scan job.
func (h *DiscoveryHandler) StartScan(ctx context.Context, c *app.RequestContext) {
	var req dto.StartDiscoveryScanRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid discovery scan request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	timeout := 30 * time.Second
	if req.TimeoutMs > 0 {
		timeout = time.Duration(req.TimeoutMs) * time.Millisecond
	}

	job, err := h.usecase.StartScan(ctx, &domain.StartDiscoveryScanRequest{
		Target:      req.Target,
		PortsSpec:   req.PortsSpec,
		Timeout:     timeout,
		Concurrency: req.Concurrency,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	CreatedResponse(c, dto.StartDiscoveryScanResponse{ID: job.ID, Status: job.Status})
}

// GetScan returns current job status/results.
func (h *DiscoveryHandler) GetScan(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	job, err := h.usecase.GetScan(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	resp := dto.DiscoveryJobResponse{
		ID:        job.ID,
		Name:      job.Name,
		Target:    job.Target,
		PortsSpec: job.PortsSpec,
		Status:    job.Status,
		Error:     job.Error,
		Services:  job.Services,
	}
	if job.StartedAt != nil {
		v := job.StartedAt.Unix()
		resp.StartedAt = &v
	}
	if job.FinishedAt != nil {
		v := job.FinishedAt.Unix()
		resp.FinishedAt = &v
	}

	SuccessResponse(c, resp)
}

// ListScans lists discovery scan jobs (history).
func (h *DiscoveryHandler) ListScans(ctx context.Context, c *app.RequestContext) {
	target := c.Query("target")
	statusStr := c.Query("status")
	limitStr := c.Query("limit")
	offsetStr := c.Query("offset")

	limit := 50
	if limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 {
			limit = v
		}
	}
	offset := 0
	if offsetStr != "" {
		if v, err := strconv.Atoi(offsetStr); err == nil && v >= 0 {
			offset = v
		}
	}

	var status domain.DiscoveryJobStatus
	if statusStr != "" {
		status = domain.DiscoveryJobStatus(statusStr)
	}

	res, err := h.usecase.ListScans(ctx, &domain.ListDiscoveryScansRequest{
		Target: target,
		Status: status,
		Limit:  limit,
		Offset: offset,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	items := make([]dto.DiscoveryJobResponse, 0, len(res.Items))
	for _, job := range res.Items {
		r := dto.DiscoveryJobResponse{
			ID:        job.ID,
			Name:      job.Name,
			Target:    job.Target,
			PortsSpec: job.PortsSpec,
			Status:    job.Status,
			Error:     job.Error,
			Services:  job.Services,
		}
		if job.StartedAt != nil {
			v := job.StartedAt.Unix()
			r.StartedAt = &v
		}
		if job.FinishedAt != nil {
			v := job.FinishedAt.Unix()
			r.FinishedAt = &v
		}
		items = append(items, r)
	}

	SuccessResponse(c, dto.ListDiscoveryScansResponse{Items: items, TotalCount: res.Total})
}

// UpdateScan updates user metadata of a scan (e.g. name).
func (h *DiscoveryHandler) UpdateScan(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	var req dto.UpdateDiscoveryScanRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid discovery scan update request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	job, err := h.usecase.UpdateScan(ctx, id, &domain.UpdateDiscoveryScanRequest{Name: req.Name})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	resp := dto.DiscoveryJobResponse{
		ID:        job.ID,
		Name:      job.Name,
		Target:    job.Target,
		PortsSpec: job.PortsSpec,
		Status:    job.Status,
		Error:     job.Error,
		Services:  job.Services,
	}
	SuccessResponse(c, resp)
}

// DeleteScan deletes a scan job.
func (h *DiscoveryHandler) DeleteScan(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	if err := h.usecase.DeleteScan(ctx, id); err != nil {
		ErrorResponse(c, err)
		return
	}
	NoContentResponse(c)
}

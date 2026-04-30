package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// DataSourceProbeHandler exposes the DataSource Probe bounded context
// over HTTP. It owns request parsing and response shaping; all business
// rules (validation, prober resolution, error classification) live in
// the use case and the domain.
type DataSourceProbeHandler struct {
	usecase domain.DataSourceProbeUseCase
	logger  *slog.Logger
}

func NewDataSourceProbeHandler(uc domain.DataSourceProbeUseCase, logger *slog.Logger) *DataSourceProbeHandler {
	return &DataSourceProbeHandler{usecase: uc, logger: logger}
}

// Probe handles POST /api/v1/datasources/probe.
//
// The endpoint is synchronous on purpose: probes are short, the user is
// waiting on the UI, and an async job model would just add ceremony.
// Per-request timeout is delegated to the prober via context.
func (h *DataSourceProbeHandler) Probe(ctx context.Context, c *app.RequestContext) {
	var req dto.ProbeDataSourceRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Warn("invalid probe request", "error", err)
		ErrorResponse(c, domain.NewInvalidInputError("invalid probe request"))
		return
	}

	res, err := h.usecase.Probe(ctx, &domain.ProbeDataSourceRequest{
		Type:     req.Type,
		Host:     req.Host,
		Port:     req.Port,
		User:     req.User,
		Password: req.Password,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ProbeDataSourceResponse{
		Databases: res.Databases,
		Version:   res.Version,
		LatencyMs: res.LatencyMs,
	})
}

// SupportedTypes handles GET /api/v1/datasources/probe/types.
// Lets the UI render the right dropdown without hard-coding the list.
func (h *DataSourceProbeHandler) SupportedTypes(ctx context.Context, c *app.RequestContext) {
	SuccessResponse(c, dto.SupportedProbeTypesResponse{
		Types: h.usecase.SupportedTypes(ctx),
	})
}

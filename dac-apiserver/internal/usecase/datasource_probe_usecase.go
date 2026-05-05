package usecase

import (
	"context"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// dataSourceProbeUsecase coordinates the DataSource Probe bounded
// context. It is intentionally thin: validate input, route to a Prober
// via the Registry, and translate cross-cutting concerns (logging,
// error wrapping) — no direct I/O happens here.
type dataSourceProbeUsecase struct {
	registry domain.ProberRegistry
	logger   *slog.Logger
}

// NewDataSourceProbeUsecase wires a use case with its required ports.
func NewDataSourceProbeUsecase(registry domain.ProberRegistry, logger *slog.Logger) domain.DataSourceProbeUseCase {
	return &dataSourceProbeUsecase{registry: registry, logger: logger}
}

// Probe validates the request, resolves a Prober, and returns the
// observation. All errors returned are domain errors so the handler
// can map them to HTTP statuses uniformly.
func (u *dataSourceProbeUsecase) Probe(ctx context.Context, req *domain.ProbeDataSourceRequest) (*domain.ProbeResult, error) {
	if err := req.Validate(); err != nil {
		return nil, err
	}

	prober, ok := u.registry.Get(req.Type)
	if !ok {
		return nil, domain.NewInvalidInputError("unsupported data source type: " + req.Type)
	}

	target := domain.ConnectionTarget{
		Type:     req.Type,
		Host:     req.Host,
		Port:     req.Port,
		User:     req.User,
		Password: req.Password,
	}

	res, err := prober.Probe(ctx, target)
	if err != nil {
		// Log full detail server-side; the domain error already carries
		// a safe user-facing message via UserMessage().
		u.logger.Warn("datasource probe failed",
			"type", req.Type,
			"host", req.Host,
			"port", req.Port,
			"error", err,
		)
		return nil, err
	}

	u.logger.Info("datasource probe succeeded",
		"type", req.Type,
		"host", req.Host,
		"port", req.Port,
		"databases", len(res.Databases),
		"latency_ms", res.LatencyMs,
	)
	return res, nil
}

// SupportedTypes returns the registered prober types.
func (u *dataSourceProbeUsecase) SupportedTypes(_ context.Context) []string {
	return u.registry.Supported()
}

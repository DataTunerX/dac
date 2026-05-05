package domain

import (
	"context"
	"strings"
)

// DataSource Probe Bounded Context
//
// Ubiquitous language:
//   - ConnectionTarget: where to connect (host/port/credentials).
//   - Prober:           a port that knows how to probe one kind of data source
//                       (mysql, postgres, ...) and report its catalogs.
//   - ProberRegistry:   resolves a Prober for a given normalized source type.
//   - ProbeResult:      what we observed (databases, version, latency).
//
// Boundary: this context is read-only and side-effect free for the platform.
// It never persists state; results are returned synchronously to the caller.
// It is intentionally separate from the Discovery context (port-scan based
// service discovery), because the business rules differ:
//   * Discovery answers "what is listening on this IP?".
//   * Probe answers     "given a known endpoint, what catalogs can we reach?".

// ConnectionTarget is a value object describing how to reach a data source.
// All fields are immutable from the caller's perspective.
type ConnectionTarget struct {
	Type     string // normalized source type, e.g. "mysql", "postgres"
	Host     string
	Port     int
	User     string
	Password string
}

// ProbeResult is a value object describing what we observed.
type ProbeResult struct {
	Databases []string // user-visible catalog names (system schemas filtered out)
	Version   string   // server version banner, best-effort, may be empty
	LatencyMs int64    // wall-clock duration of the probe round trip
}

// Prober is a domain port. One implementation per data source type.
// Implementations MUST:
//   - respect ctx cancellation and deadlines,
//   - never panic on bad credentials; return a wrapped error instead,
//   - filter out system / internal catalogs from Databases.
type Prober interface {
	Type() string
	Probe(ctx context.Context, target ConnectionTarget) (*ProbeResult, error)
}

// ProberRegistry resolves a Prober by normalized source type.
type ProberRegistry interface {
	Get(sourceType string) (Prober, bool)
	Supported() []string
}

// ProbeDataSourceRequest is the use case input.
type ProbeDataSourceRequest struct {
	Type     string
	Host     string
	Port     int
	User     string
	Password string
}

// Validate enforces the invariants of a probe request at the boundary
// of the use case (Tell, don't ask). It returns a domain error so the
// handler can map it to an HTTP status without leaking internals.
func (r *ProbeDataSourceRequest) Validate() error {
	if r == nil {
		return NewInvalidInputError("probe request is required")
	}
	if strings.TrimSpace(r.Type) == "" {
		return NewInvalidInputError("type is required")
	}
	if strings.TrimSpace(r.Host) == "" {
		return NewInvalidInputError("host is required")
	}
	if r.Port <= 0 || r.Port > 65535 {
		return NewInvalidInputError("port must be in [1, 65535]")
	}
	return nil
}

// DataSourceProbeUseCase is the application service for the probe context.
type DataSourceProbeUseCase interface {
	Probe(ctx context.Context, req *ProbeDataSourceRequest) (*ProbeResult, error)
	SupportedTypes(ctx context.Context) []string
}

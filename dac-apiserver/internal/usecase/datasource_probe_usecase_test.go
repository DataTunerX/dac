package usecase

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"reflect"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// stubProber returns predetermined results to drive the usecase under test.
type stubProber struct {
	t      string
	result *domain.ProbeResult
	err    error
}

func (s *stubProber) Type() string { return s.t }
func (s *stubProber) Probe(context.Context, domain.ConnectionTarget) (*domain.ProbeResult, error) {
	return s.result, s.err
}

// stubRegistry resolves probers by exact type for deterministic routing.
type stubRegistry struct{ probers map[string]domain.Prober }

func newStubRegistry(ps ...domain.Prober) *stubRegistry {
	m := make(map[string]domain.Prober, len(ps))
	for _, p := range ps {
		m[p.Type()] = p
	}
	return &stubRegistry{probers: m}
}

func (r *stubRegistry) Get(t string) (domain.Prober, bool) {
	p, ok := r.probers[t]
	return p, ok
}

func (r *stubRegistry) Supported() []string {
	out := make([]string, 0, len(r.probers))
	for k := range r.probers {
		out = append(out, k)
	}
	return out
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func validRequest() *domain.ProbeDataSourceRequest {
	return &domain.ProbeDataSourceRequest{
		Type: "mysql", Host: "127.0.0.1", Port: 3306, User: "u", Password: "p",
	}
}

func TestProbeUsecase_Probe(t *testing.T) {
	want := &domain.ProbeResult{Databases: []string{"a", "b"}, Version: "8.0", LatencyMs: 7}

	tests := []struct {
		name      string
		req       *domain.ProbeDataSourceRequest
		registry  domain.ProberRegistry
		wantErrIs error
		wantRes   *domain.ProbeResult
	}{
		{
			name:      "nil request fails validation",
			req:       nil,
			registry:  newStubRegistry(&stubProber{t: "mysql", result: want}),
			wantErrIs: domain.ErrInvalidInput,
		},
		{
			name:      "blank type fails validation",
			req:       &domain.ProbeDataSourceRequest{Type: "  ", Host: "h", Port: 1},
			registry:  newStubRegistry(&stubProber{t: "mysql", result: want}),
			wantErrIs: domain.ErrInvalidInput,
		},
		{
			name:      "invalid port fails validation",
			req:       &domain.ProbeDataSourceRequest{Type: "mysql", Host: "h", Port: 0},
			registry:  newStubRegistry(&stubProber{t: "mysql", result: want}),
			wantErrIs: domain.ErrInvalidInput,
		},
		{
			name:      "unsupported type returns invalid input",
			req:       &domain.ProbeDataSourceRequest{Type: "oracle", Host: "h", Port: 1},
			registry:  newStubRegistry(&stubProber{t: "mysql", result: want}),
			wantErrIs: domain.ErrInvalidInput,
		},
		{
			name:      "prober error is propagated unchanged",
			req:       validRequest(),
			registry:  newStubRegistry(&stubProber{t: "mysql", err: domain.NewInvalidInputError("bad creds")}),
			wantErrIs: domain.ErrInvalidInput,
		},
		{
			name:     "happy path returns prober result",
			req:      validRequest(),
			registry: newStubRegistry(&stubProber{t: "mysql", result: want}),
			wantRes:  want,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			uc := NewDataSourceProbeUsecase(tc.registry, discardLogger())
			res, err := uc.Probe(context.Background(), tc.req)

			switch {
			case tc.wantErrIs != nil:
				if !errors.Is(err, tc.wantErrIs) {
					t.Fatalf("err=%v want errors.Is(_, %v)", err, tc.wantErrIs)
				}
				if res != nil {
					t.Fatalf("res=%v want nil on error", res)
				}
			default:
				if err != nil {
					t.Fatalf("unexpected err: %v", err)
				}
				if !reflect.DeepEqual(res, tc.wantRes) {
					t.Fatalf("res=%v want %v", res, tc.wantRes)
				}
			}
		})
	}
}

func TestProbeUsecase_SupportedTypesDelegatesToRegistry(t *testing.T) {
	reg := newStubRegistry(&stubProber{t: "mysql"}, &stubProber{t: "postgres"})
	uc := NewDataSourceProbeUsecase(reg, discardLogger())

	got := uc.SupportedTypes(context.Background())
	if len(got) != 2 {
		t.Fatalf("supported len=%d want 2: %v", len(got), got)
	}
}

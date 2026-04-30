// Package probe contains adapters that implement the domain.Prober port
// for concrete data source technologies (MySQL, Postgres, ...).
//
// The registry is the only place that knows the full set of supported types.
// Adding a new technology means: write a Prober, register it here, done.
package probe

import (
	"sort"
	"strings"
	"sync"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// Registry is a concurrency-safe domain.ProberRegistry implementation.
// It is meant to be built once at startup and treated as effectively
// immutable thereafter; concurrent reads are cheap.
type Registry struct {
	mu      sync.RWMutex
	probers map[string]domain.Prober
}

// NewRegistry builds a registry from the supplied probers.
// Source type keys are normalized (lower-case, trimmed) to make the
// registry caller-friendly. Duplicate types are rejected by panic
// because they indicate a programmer error at wire-up time.
func NewRegistry(probers ...domain.Prober) *Registry {
	r := &Registry{probers: make(map[string]domain.Prober, len(probers))}
	for _, p := range probers {
		key := normalizeType(p.Type())
		if key == "" {
			panic("probe: refusing to register prober with empty type")
		}
		if _, dup := r.probers[key]; dup {
			panic("probe: duplicate prober registration for type " + key)
		}
		r.probers[key] = p
	}
	return r
}

// Get resolves a prober by source type. The lookup is case-insensitive.
func (r *Registry) Get(sourceType string) (domain.Prober, bool) {
	key := normalizeType(sourceType)
	if key == "" {
		return nil, false
	}
	r.mu.RLock()
	p, ok := r.probers[key]
	r.mu.RUnlock()
	return p, ok
}

// Supported returns the sorted list of registered source types.
func (r *Registry) Supported() []string {
	r.mu.RLock()
	out := make([]string, 0, len(r.probers))
	for k := range r.probers {
		out = append(out, k)
	}
	r.mu.RUnlock()
	sort.Strings(out)
	return out
}

func normalizeType(s string) string {
	return strings.ToLower(strings.TrimSpace(s))
}

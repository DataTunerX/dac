package discovery

import (
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"net/http"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// Scanner orchestrates a fixed-order list of Probes against a target port.
//
// The scanner itself owns no protocol knowledge: it dials once for liveness,
// then dispatches to each registered Probe in order. The first probe that
// returns a Match wins. Adding a new protocol means implementing Probe and
// appending to the list in NewScanner; ScanPort never needs to change.
type Scanner struct {
	dialer  *net.Dialer
	timeout time.Duration
	probes  []Probe
}

// NewScanner returns a Scanner with the default probe stack:
//
//	mysql → postgres → redis → http (with HTTP fingerprinters)
//
// Probes are ordered cheapest-first within each protocol family, and
// active-talk protocols (mysql sends a banner, postgres replies to
// SSLRequest) are tried before HTTP so we don't waste a full round-trip
// on text/html for a database port.
func NewScanner(timeout time.Duration) *Scanner {
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	dialer := &net.Dialer{Timeout: timeout}
	httpClient := newHTTPClient(timeout)

	return &Scanner{
		dialer:  dialer,
		timeout: timeout,
		probes: []Probe{
			&mysqlProbe{dialer: dialer, timeout: timeout},
			&postgresProbe{dialer: dialer, timeout: timeout},
			&redisProbe{dialer: dialer, timeout: timeout},
			&httpProbe{
				client:    httpClient,
				timeout:   timeout,
				detectors: defaultHTTPDetectors(),
				fallbacks: defaultHTTPFallbacks(),
			},
		},
	}
}

// ScanPort runs the registered probes against host:port. A reachable port
// always produces a DiscoveredService (with ServiceType="unknown" if no
// probe matched) so the caller can distinguish "open but unidentified"
// from "closed/filtered".
func (s *Scanner) ScanPort(ctx context.Context, host string, port int) (*domain.DiscoveredService, bool) {
	target := Target{Host: host, Port: port}

	// Liveness check. Without this, every closed port would burn
	// timeout × len(probes) waiting for handshakes that never come.
	conn, err := s.dialer.DialContext(ctx, "tcp", target.Addr())
	if err != nil {
		return nil, false
	}
	_ = conn.Close()

	svc := &domain.DiscoveredService{
		Host:        host,
		Port:        port,
		Protocol:    "tcp",
		ServiceType: "unknown",
		Metadata:    map[string]string{},
	}

	for _, p := range s.probes {
		if ctx.Err() != nil {
			break
		}
		m := p.Probe(ctx, target)
		if m == nil {
			continue
		}
		applyMatch(svc, m)
		return svc, true
	}
	return svc, true
}

// applyMatch merges a Probe's result into the destination service.
// Empty fields on the match leave the corresponding service field
// untouched, so probes can return partial information without clobbering
// defaults.
func applyMatch(svc *domain.DiscoveredService, m *Match) {
	if m.ServiceType != "" {
		svc.ServiceType = m.ServiceType
	}
	if m.Product != "" {
		svc.Product = m.Product
	}
	if m.Version != "" {
		svc.Version = m.Version
	}
	if m.TLS {
		svc.TLS = true
	}
	for k, v := range m.Metadata {
		svc.Metadata[k] = v
	}
}

// newHTTPClient builds the HTTP client shared by httpProbe and all
// HTTPFingerprinters. Keep-alives are disabled because each port-scan
// produces at most a handful of requests and we never reuse the same
// host between targets.
func newHTTPClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
		// Don't follow redirects: a redirect from / to /login would
		// hide the original Server header and confuse fingerprinters.
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
		Transport: &http.Transport{
			Proxy:               http.ProxyFromEnvironment,
			DialContext:         (&net.Dialer{Timeout: timeout}).DialContext,
			TLSHandshakeTimeout: timeout,
			DisableKeepAlives:   true,
			TLSClientConfig:     &tls.Config{InsecureSkipVerify: true},
		},
	}
}

// Probe identifies a service speaking a particular protocol on a TCP port.
//
// Implementations must:
//   - return promptly when ctx is cancelled
//   - never panic
//   - return nil to mean "this is not my protocol", a non-nil *Match
//     to mean "I identified the service"
type Probe interface {
	// Name returns a stable identifier for logs and tests (e.g. "mysql").
	Name() string

	// Probe runs the protocol-specific identification dance against
	// target. A non-nil return short-circuits the rest of the probe stack.
	Probe(ctx context.Context, target Target) *Match
}

// Target is the (host, port) pair under inspection.
type Target struct {
	Host string
	Port int
}

// Addr returns host:port suitable for net.Dial.
func (t Target) Addr() string {
	return net.JoinHostPort(t.Host, fmt.Sprintf("%d", t.Port))
}

// Match is the positive identification a Probe returns.
//
// Fields are additive: empty values let the scanner keep whatever a
// later probe (or the unknown default) provides.
type Match struct {
	ServiceType string            // "http", "mysql", "postgres", "redis"
	Product     string            // "gitlab", "minio", "nginx", ...
	Version     string            // free-form version string when known
	TLS         bool              // true if the probe spoke (or detected) TLS
	Metadata    map[string]string // small, opaque key/value pairs for the UI
}

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

// Scanner orchestrates service identification against a target port.
//
// Order of operations:
//  1. TCP liveness dial (closed ports are omitted)
//  2. Cheap local DB probes (mysql / postgres / redis) — fast + deterministic
//  3. Nerva (Praetorian) — 170+ protocol plugins for the long tail
//  4. Local HTTP product enrichers (GitLab/Odoo/Saleor/Boutique/fileserver/…)
//     when Nerva returns nothing or only generic http/nginx
type Scanner struct {
	dialer    *net.Dialer
	timeout   time.Duration
	dbProbes  []Probe
	nerva     *nervaProbe
	httpProbe *httpProbe
}

// NewScanner returns a production Scanner with Nerva enabled.
func NewScanner(timeout time.Duration) *Scanner {
	return newScanner(timeout, true)
}

func newScanner(timeout time.Duration, withNerva bool) *Scanner {
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	dialer := &net.Dialer{Timeout: timeout}
	httpClient := newHTTPClient(timeout)

	s := &Scanner{
		dialer:  dialer,
		timeout: timeout,
		dbProbes: []Probe{
			&mysqlProbe{dialer: dialer, timeout: timeout},
			&postgresProbe{dialer: dialer, timeout: timeout},
			&redisProbe{dialer: dialer, timeout: timeout},
		},
		httpProbe: &httpProbe{
			client:    httpClient,
			timeout:   timeout,
			detectors: defaultHTTPDetectors(),
			fallbacks: defaultHTTPFallbacks(),
		},
	}
	if withNerva {
		s.nerva = &nervaProbe{timeout: timeout}
	}
	return s
}

// ScanPort runs identification against host:port. A reachable port always
// produces a DiscoveredService (ServiceType="unknown" if nothing matched).
func (s *Scanner) ScanPort(ctx context.Context, host string, port int) (*domain.DiscoveredService, bool) {
	target := Target{Host: host, Port: port}

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

	for _, p := range s.dbProbes {
		if ctx.Err() != nil {
			break
		}
		if m := p.Probe(ctx, target); m != nil {
			applyMatch(svc, m)
			return svc, true
		}
	}

	var nervaMatch *Match
	if s.nerva != nil && ctx.Err() == nil {
		nervaCtx, cancel := context.WithTimeout(ctx, s.timeout)
		nervaMatch = s.nerva.Probe(nervaCtx, target)
		cancel()
		if nervaMatch != nil && !isGenericHTTP(nervaMatch) {
			applyMatch(svc, nervaMatch)
			return svc, true
		}
	}

	if s.httpProbe != nil && ctx.Err() == nil {
		if m := s.httpProbe.Probe(ctx, target); m != nil {
			if nervaMatch != nil {
				applyMatch(svc, nervaMatch)
			}
			applyMatch(svc, m)
			return svc, true
		}
	}

	if nervaMatch != nil {
		applyMatch(svc, nervaMatch)
	}
	return svc, true
}

func isGenericHTTP(m *Match) bool {
	if m == nil {
		return false
	}
	if m.ServiceType != "http" {
		return false
	}
	return m.Product == "" || m.Product == "http" || m.Product == "https" || m.Product == "nginx"
}

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

func newHTTPClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
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
type Probe interface {
	Name() string
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
type Match struct {
	ServiceType string
	Product     string
	Version     string
	TLS         bool
	Metadata    map[string]string
}

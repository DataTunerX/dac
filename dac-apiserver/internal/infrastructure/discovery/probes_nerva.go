package discovery

import (
	"context"
	"encoding/json"
	"net/netip"
	"strconv"
	"strings"
	"time"

	"github.com/praetorian-inc/nerva/pkg/plugins"
	"github.com/praetorian-inc/nerva/pkg/scan"
)

// nervaProbe wraps Praetorian Nerva (successor to fingerprintx) for
// protocol-level service identification across 170+ TCP services.
//
// This is the primary "what is listening?" engine. DAC-specific HTTP
// product enrichers (Saleor, Boutique, fileserver autoindex, …) still
// run after Nerva returns a generic http/https result.
type nervaProbe struct {
	timeout time.Duration
}

func (p *nervaProbe) Name() string { return "nerva" }

func (p *nervaProbe) Probe(ctx context.Context, t Target) *Match {
	if ctx.Err() != nil {
		return nil
	}
	target, ok := nervaTarget(t)
	if !ok {
		return nil
	}

	timeout := p.timeout
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	cfg := scan.Config{
		DefaultTimeout: timeout,
		Workers:        1,
		Verbose:        false,
	}

	results, err := scan.ScanTargets(ctx, []plugins.Target{target}, cfg)
	if err != nil || len(results) == 0 {
		return nil
	}
	return matchFromNerva(results[0])
}

func nervaTarget(t Target) (plugins.Target, bool) {
	port := uint16(t.Port)
	if t.Port <= 0 || t.Port > 65535 {
		return plugins.Target{}, false
	}

	if addr, err := netip.ParseAddr(t.Host); err == nil {
		return plugins.Target{
			Host:    t.Host,
			Address: netip.AddrPortFrom(addr, port),
		}, true
	}

	// Hostname: leave address unspecified so Nerva ResolveTargets does DNS.
	return plugins.Target{
		Host:    t.Host,
		Address: netip.AddrPortFrom(netip.IPv4Unspecified(), port),
	}, true
}

func matchFromNerva(svc plugins.Service) *Match {
	proto := strings.ToLower(strings.TrimSpace(svc.Protocol))
	if proto == "" {
		return nil
	}

	m := &Match{
		TLS:      svc.TLS,
		Version:  strings.TrimSpace(svc.Version),
		Metadata: map[string]string{"fingerprinter": "nerva"},
	}
	if svc.Transport != "" {
		m.Metadata["transport"] = svc.Transport
	}

	switch proto {
	case "mysql", "mysqlx":
		m.ServiceType = "mysql"
		m.Product = "mysql"
	case "postgres", "postgresql":
		m.ServiceType = "postgres"
		m.Product = "postgresql"
	case "redis":
		m.ServiceType = "redis"
		m.Product = "redis"
	case "http", "https":
		m.ServiceType = "http"
		m.TLS = m.TLS || proto == "https"
		applyHTTPNervaMeta(m, svc.Raw)
	default:
		// Generic protocol name (ssh, mongodb, kafka, …).
		m.ServiceType = proto
		m.Product = proto
	}

	return m
}

type nervaHTTPMeta struct {
	StatusCode          int                       `json:"status_code"`
	Title               string                    `json:"title"`
	Technologies        []string                  `json:"technologies"`
	FingerprintMetadata map[string]map[string]any `json:"fingerprint_metadata"`
	ResponseHeaders     map[string][]string       `json:"response_headers"`
}

func applyHTTPNervaMeta(m *Match, raw json.RawMessage) {
	if len(raw) == 0 {
		return
	}
	var meta nervaHTTPMeta
	if err := json.Unmarshal(raw, &meta); err != nil {
		return
	}
	if meta.StatusCode > 0 {
		m.Metadata["http.status"] = strconv.Itoa(meta.StatusCode)
	}
	if meta.Title != "" {
		m.Metadata["http.title"] = meta.Title
	}
	if servers := meta.ResponseHeaders["Server"]; len(servers) > 0 && servers[0] != "" {
		m.Metadata["http.server"] = servers[0]
	}
	if len(meta.Technologies) > 0 {
		m.Metadata["http.technologies"] = strings.Join(meta.Technologies, ",")
	}

	// Prefer named product fingerprinters (GitLab/MinIO/…) over generic Wappalyzer tags.
	if product, version := pickHTTPProduct(meta); product != "" {
		m.Product = product
		if version != "" && m.Version == "" {
			m.Version = version
		}
	}
}

func pickHTTPProduct(meta nervaHTTPMeta) (product, version string) {
	for name, fp := range meta.FingerprintMetadata {
		key := strings.ToLower(strings.TrimSpace(name))
		if mapped := mapKnownProduct(key); mapped != "" {
			if v, ok := fp["version"].(string); ok {
				version = v
			}
			return mapped, version
		}
	}
	for _, tech := range meta.Technologies {
		if mapped := mapKnownProduct(tech); mapped != "" {
			return mapped, ""
		}
	}
	return "", ""
}

func mapKnownProduct(name string) string {
	n := strings.ToLower(strings.TrimSpace(name))
	switch {
	case strings.Contains(n, "gitlab"):
		return "gitlab"
	case strings.Contains(n, "minio"):
		return "minio"
	case strings.Contains(n, "odoo"):
		return "odoo"
	case strings.Contains(n, "nextcloud"):
		return "nextcloud"
	case strings.Contains(n, "trino"):
		return "trino"
	case strings.Contains(n, "saleor"):
		return "saleor"
	case n == "nginx":
		return "nginx"
	default:
		return ""
	}
}

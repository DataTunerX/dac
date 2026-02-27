package discovery

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type Scanner struct {
	dialer  net.Dialer
	timeout time.Duration
	client  *http.Client
}

func NewScanner(timeout time.Duration) *Scanner {
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	return &Scanner{
		dialer:  net.Dialer{Timeout: timeout},
		timeout: timeout,
		client: &http.Client{
			Timeout: timeout,
			Transport: &http.Transport{
				Proxy:               http.ProxyFromEnvironment,
				DialContext:         (&net.Dialer{Timeout: timeout}).DialContext,
				TLSHandshakeTimeout: timeout,
				DisableKeepAlives:   true,
			},
		},
	}
}

func (s *Scanner) ScanPort(ctx context.Context, host string, port int) (*domain.DiscoveredService, bool) {
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	conn, err := s.dialer.DialContext(ctx, "tcp", addr)
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

	// Protocol probes (cheap, best-effort)
	if ok, meta := s.probeMySQL(ctx, host, port); ok {
		svc.ServiceType = "mysql"
		for k, v := range meta {
			svc.Metadata[k] = v
		}
		return svc, true
	}
	if ok := s.probePostgres(ctx, host, port); ok {
		svc.ServiceType = "postgres"
		return svc, true
	}
	if ok := s.probeRedis(ctx, host, port); ok {
		svc.ServiceType = "redis"
		return svc, true
	}

	// HTTP/TLS probes (also used to derive product)
	if ok, tlsOK := s.probeHTTP(ctx, svc); ok {
		svc.ServiceType = "http"
		svc.TLS = tlsOK
		return svc, true
	}

	return svc, true
}

func (s *Scanner) probeRedis(ctx context.Context, host string, port int) bool {
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	conn, err := s.dialer.DialContext(ctx, "tcp", addr)
	if err != nil {
		return false
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(s.timeout))
	if _, err := conn.Write([]byte("PING\r\n")); err != nil {
		return false
	}
	buf := make([]byte, 16)
	n, _ := conn.Read(buf)
	return bytes.HasPrefix(buf[:n], []byte("+PONG"))
}

func (s *Scanner) probeMySQL(ctx context.Context, host string, port int) (bool, map[string]string) {
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	conn, err := s.dialer.DialContext(ctx, "tcp", addr)
	if err != nil {
		return false, nil
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(s.timeout))

	// MySQL sends a handshake packet immediately.
	r := bufio.NewReader(conn)
	header := make([]byte, 4)
	if _, err := io.ReadFull(r, header); err != nil {
		return false, nil
	}
	payloadLen := int(uint32(header[0]) | uint32(header[1])<<8 | uint32(header[2])<<16)
	if payloadLen <= 0 || payloadLen > 4096 {
		return false, nil
	}
	payload := make([]byte, payloadLen)
	if _, err := io.ReadFull(r, payload); err != nil {
		return false, nil
	}
	// payload[0] is protocol version (0x0a for modern MySQL)
	if len(payload) < 2 || payload[0] != 0x0a {
		return false, nil
	}
	// server version is NUL-terminated string starting at payload[1]
	nul := bytes.IndexByte(payload[1:], 0x00)
	if nul <= 0 {
		return true, map[string]string{}
	}
	version := string(payload[1 : 1+nul])
	return true, map[string]string{"version": version}
}

func (s *Scanner) probePostgres(ctx context.Context, host string, port int) bool {
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	conn, err := s.dialer.DialContext(ctx, "tcp", addr)
	if err != nil {
		return false
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(s.timeout))

	// Send SSLRequest: int32 len=8, int32 code=80877103.
	var buf [8]byte
	binary.BigEndian.PutUint32(buf[0:4], 8)
	binary.BigEndian.PutUint32(buf[4:8], 80877103)
	if _, err := conn.Write(buf[:]); err != nil {
		return false
	}
	resp := make([]byte, 1)
	if _, err := io.ReadFull(conn, resp); err != nil {
		return false
	}
	// 'S' or 'N' means it's a Postgres server.
	return resp[0] == 'S' || resp[0] == 'N'
}

func (s *Scanner) probeHTTP(ctx context.Context, svc *domain.DiscoveredService) (bool, bool) {
	host := svc.Host
	port := svc.Port

	// Try plain HTTP first
	if ok := s.httpProbe(ctx, svc, "http", host, port); ok {
		return true, false
	}

	// Try TLS handshake quickly
	if s.tlsHandshake(ctx, host, port) {
		if ok := s.httpProbe(ctx, svc, "https", host, port); ok {
			return true, true
		}
	}
	return false, false
}

func (s *Scanner) tlsHandshake(ctx context.Context, host string, port int) bool {
	addr := net.JoinHostPort(host, fmt.Sprintf("%d", port))
	d := &net.Dialer{Timeout: s.timeout}
	conn, err := tls.DialWithDialer(d, "tcp", addr, &tls.Config{
		InsecureSkipVerify: true,
		ServerName:         host,
	})
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

func (s *Scanner) httpProbe(ctx context.Context, svc *domain.DiscoveredService, scheme, host string, port int) bool {
	base := fmt.Sprintf("%s://%s:%d", scheme, host, port)

	// Ordered, cheap identification paths
	paths := []string{
		"/minio/health/ready", // MinIO
		"/api/v1/version",     // Gitea
		"/status.php",         // Nextcloud
		"/v1/info",            // Trino
		"/web/login",          // Odoo
		"/",                   // fallback
	}

	for _, p := range paths {
		u := base + p
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
		req.Header.Set("User-Agent", "dac-discovery/0.1")
		resp, err := s.client.Do(req)
		if err != nil {
			continue
		}
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
		_ = resp.Body.Close()

		// Any HTTP response means it's HTTP-ish.
		svc.Metadata["http.status"] = fmt.Sprintf("%d", resp.StatusCode)
		if ct := resp.Header.Get("Content-Type"); ct != "" {
			svc.Metadata["http.contentType"] = ct
		}
		if server := resp.Header.Get("Server"); server != "" {
			svc.Metadata["http.server"] = server
		}

		// Product heuristics
		if strings.Contains(strings.ToLower(resp.Header.Get("Server")), "minio") || bytes.Contains(body, []byte("MinIO")) {
			svc.Product = "minio"
			return true
		}
		if p == "/api/v1/version" && resp.StatusCode == 200 && bytes.Contains(body, []byte("version")) {
			svc.Product = "gitea"
			var v struct{ Version string `json:"version"` }
			_ = json.Unmarshal(body, &v)
			if v.Version != "" {
				svc.Version = v.Version
			}
			return true
		}
		if p == "/status.php" && resp.StatusCode == 200 && bytes.Contains(body, []byte("Nextcloud")) {
			svc.Product = "nextcloud"
			return true
		}
		if p == "/v1/info" && resp.StatusCode == 200 && bytes.Contains(body, []byte("nodeVersion")) {
			svc.Product = "trino"
			return true
		}
		if p == "/web/login" && resp.StatusCode >= 200 && resp.StatusCode < 500 && bytes.Contains(bytes.ToLower(body), []byte("odoo")) {
			svc.Product = "odoo"
			return true
		}

		// Generic HTTP
		if resp.StatusCode > 0 {
			return true
		}
	}
	return false
}


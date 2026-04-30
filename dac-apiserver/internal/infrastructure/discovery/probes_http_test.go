package discovery

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"testing"
	"time"
)

// newHTTPProbe builds an httpProbe wired to the production fingerprinter
// stack with timeouts short enough that a probe of a non-listening port
// fails in milliseconds, not seconds.
func newHTTPProbe(t *testing.T) *httpProbe {
	t.Helper()
	timeout := 500 * time.Millisecond
	return &httpProbe{
		client:    newHTTPClient(timeout),
		timeout:   timeout,
		detectors: defaultHTTPDetectors(),
		fallbacks: defaultHTTPFallbacks(),
	}
}

// startServer spins up an httptest server with the given handler and
// returns the host/port the probe should use. The server is torn down
// automatically at the end of the test.
func startServer(t *testing.T, h http.Handler) (host string, port int) {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)

	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatalf("parse url: %v", err)
	}
	hostStr, portStr, err := net.SplitHostPort(u.Host)
	if err != nil {
		t.Fatalf("split host port: %v", err)
	}
	p, err := strconv.Atoi(portStr)
	if err != nil {
		t.Fatalf("atoi port: %v", err)
	}
	return hostStr, p
}

// pathRouter dispatches by exact path. Unmatched paths return 404 so
// fingerprinters that key off "/" don't accidentally see install pages
// from sibling tests.
type pathRouter map[string]http.HandlerFunc

func (r pathRouter) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	if h, ok := r[req.URL.Path]; ok {
		h(w, req)
		return
	}
	http.NotFound(w, req)
}

func TestHTTPProbe_Identifies(t *testing.T) {
	cases := []struct {
		name        string
		handler     http.Handler
		wantProduct string
		wantVersion string
	}{
		{
			name: "minio via server header",
			handler: pathRouter{
				"/": func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Server", "MinIO")
					w.WriteHeader(http.StatusForbidden)
				},
				"/minio/health/ready": func(w http.ResponseWriter, _ *http.Request) {
					w.WriteHeader(http.StatusOK)
				},
			},
			wantProduct: "minio",
		},
		{
			name: "minio via health endpoint when root is silent",
			handler: pathRouter{
				"/": func(w http.ResponseWriter, _ *http.Request) {
					w.WriteHeader(http.StatusForbidden)
				},
				"/minio/health/ready": func(w http.ResponseWriter, _ *http.Request) {
					w.WriteHeader(http.StatusOK)
				},
			},
			wantProduct: "minio",
		},
		{
			name: "gitlab via health endpoint",
			handler: pathRouter{
				"/-/health": func(w http.ResponseWriter, _ *http.Request) {
					w.WriteHeader(http.StatusOK)
					_, _ = w.Write([]byte("GitLab OK"))
				},
			},
			wantProduct: "gitlab",
		},
		{
			name: "gitlab via api version (authed)",
			handler: pathRouter{
				"/api/v4/version": func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					w.WriteHeader(http.StatusOK)
					_, _ = w.Write([]byte(`{"version":"17.5.0","revision":"abc"}`))
				},
			},
			wantProduct: "gitlab",
			wantVersion: "17.5.0",
		},
		{
			name: "gitlab via api version (unauthed 401)",
			handler: pathRouter{
				"/api/v4/version": func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					w.WriteHeader(http.StatusUnauthorized)
					_, _ = w.Write([]byte(`{"message":"401 Unauthorized"}`))
				},
			},
			wantProduct: "gitlab",
		},
		{
			name: "gitlab via session cookie on /",
			handler: pathRouter{
				"/": func(w http.ResponseWriter, _ *http.Request) {
					http.SetCookie(w, &http.Cookie{Name: "_gitlab_session", Value: "x"})
					w.WriteHeader(http.StatusOK)
					_, _ = w.Write([]byte("<html>sign in</html>"))
				},
			},
			wantProduct: "gitlab",
		},
		{
			name: "nextcloud status",
			handler: pathRouter{
				"/status.php": func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					_, _ = w.Write([]byte(`{"installed":true,"productname":"Nextcloud","version":"28.0.1"}`))
				},
			},
			wantProduct: "nextcloud",
			wantVersion: "28.0.1",
		},
		{
			name: "trino info",
			handler: pathRouter{
				"/v1/info": func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					_, _ = w.Write([]byte(`{"nodeVersion":{"version":"450"},"environment":"test"}`))
				},
			},
			wantProduct: "trino",
			wantVersion: "450",
		},
		{
			name: "odoo login page",
			handler: pathRouter{
				"/web/login": func(w http.ResponseWriter, _ *http.Request) {
					w.WriteHeader(http.StatusOK)
					_, _ = w.Write([]byte("<html>Powered by Odoo</html>"))
				},
			},
			wantProduct: "odoo",
		},
		{
			name: "nginx fileserver via autoindex",
			handler: pathRouter{
				"/": func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Server", "nginx/1.25.3")
					_, _ = w.Write([]byte("<html><head><title>Index of /</title></head></html>"))
				},
			},
			wantProduct: "fileserver",
			wantVersion: "1.25.3",
		},
		{
			name: "plain nginx without autoindex",
			handler: pathRouter{
				"/": func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Server", "nginx/1.27.0")
					_, _ = w.Write([]byte("<html>hi</html>"))
				},
			},
			wantProduct: "nginx",
			wantVersion: "1.27.0",
		},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			host, port := startServer(t, tc.handler)
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()

			m := newHTTPProbe(t).Probe(ctx, Target{Host: host, Port: port})
			if m == nil {
				t.Fatalf("probe returned nil; expected product=%q", tc.wantProduct)
			}
			if m.Product != tc.wantProduct {
				t.Errorf("product = %q, want %q", m.Product, tc.wantProduct)
			}
			if tc.wantVersion != "" && m.Version != tc.wantVersion {
				t.Errorf("version = %q, want %q", m.Version, tc.wantVersion)
			}
			if m.ServiceType != "http" {
				t.Errorf("serviceType = %q, want %q", m.ServiceType, "http")
			}
		})
	}
}

// TestHTTPProbe_GenericFallback ensures a server we can't fingerprint
// still produces a generic "http" match rather than nil. That distinction
// matters: nil means "not HTTP", while a generic match means "HTTP, but
// product unknown" — the UI shows them differently.
//
// We serve only "/" and let everything else 404. A blanket 200 would
// trip MinIO's soft signal on /minio/health/ready, which is exactly the
// kind of false positive this test is supposed to guard against.
func TestHTTPProbe_GenericFallback(t *testing.T) {
	host, port := startServer(t, pathRouter{
		"/": func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Content-Type", "text/plain")
			_, _ = w.Write([]byte("ok"))
		},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	m := newHTTPProbe(t).Probe(ctx, Target{Host: host, Port: port})
	if m == nil {
		t.Fatal("expected generic http match, got nil")
	}
	if m.ServiceType != "http" {
		t.Errorf("serviceType = %q, want %q", m.ServiceType, "http")
	}
	if m.Product != "" {
		t.Errorf("product = %q, want empty (generic http)", m.Product)
	}
	if got := m.Metadata["http.contentType"]; !strings.HasPrefix(got, "text/plain") {
		t.Errorf("http.contentType = %q, want text/plain*", got)
	}
}

// TestHTTPProbe_NotListening verifies that probing a closed port returns
// nil quickly. Without this check the probe would keep trying TLS after
// the plain-HTTP dial fails, which used to add seconds to scans of
// non-HTTP ports like raw MySQL.
func TestHTTPProbe_NotListening(t *testing.T) {
	// Bind to an ephemeral port, then close it. The OS won't immediately
	// reuse it, so dials reliably fail with "connection refused".
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr := l.Addr().(*net.TCPAddr)
	_ = l.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	start := time.Now()
	m := newHTTPProbe(t).Probe(ctx, Target{Host: "127.0.0.1", Port: addr.Port})
	if m != nil {
		t.Fatalf("expected nil for closed port, got %+v", m)
	}
	if elapsed := time.Since(start); elapsed > 1500*time.Millisecond {
		t.Errorf("probe took %v, expected < 1.5s for refused connections", elapsed)
	}
}

// TestHTTPProbe_GitlabBehindNginx is the regression test for the
// "sandbox 中没有识别到 gitlab" bug. GitLab CE always fronts itself with
// nginx, so "/" returns "Server: nginx/...". Before the detectors/
// fallbacks split, nginxFingerprinter matched on "/" first and the
// scanner short-circuited, so /api/v4/version was never inspected and
// the service was reported as plain nginx. With the split, the GitLab
// detector wins on /api/v4/version and nginx never gets a turn.
func TestHTTPProbe_GitlabBehindNginx(t *testing.T) {
	host, port := startServer(t, pathRouter{
		"/": func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Server", "nginx/1.25.3")
			// 302 to /users/sign_in is what real GitLab returns
			// for an unauth root request.
			w.Header().Set("Location", "/users/sign_in")
			w.WriteHeader(http.StatusFound)
		},
		"/api/v4/version": func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Server", "nginx/1.25.3")
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"message":"401 Unauthorized"}`))
		},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	m := newHTTPProbe(t).Probe(ctx, Target{Host: host, Port: port})
	if m == nil {
		t.Fatal("probe returned nil; expected gitlab")
	}
	if m.Product != "gitlab" {
		t.Fatalf("product = %q, want %q (nginx must not shadow gitlab)", m.Product, "gitlab")
	}
}

// TestHTTPProbe_GitlabRedirectOnRoot covers the worst-case scan: only
// "/" is reachable in time, GitLab redirects to /users/sign_in with no
// _gitlab_session cookie and no body. Header-based heuristics
// (Location, Server: gitlab-workhorse, X-Gitlab-*) are the only signal,
// and at least one of them must fire.
func TestHTTPProbe_GitlabRedirectOnRoot(t *testing.T) {
	cases := []struct {
		name    string
		handler http.HandlerFunc
	}{
		{
			name: "x-gitlab-meta header",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("X-Gitlab-Meta", `{"correlation_id":"abc"}`)
				w.Header().Set("Server", "nginx")
				w.WriteHeader(http.StatusOK)
			},
		},
		{
			name: "gitlab-workhorse server header",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Server", "gitlab-workhorse")
				w.WriteHeader(http.StatusOK)
			},
		},
		{
			name: "redirect to users sign in",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Server", "nginx/1.25.3")
				w.Header().Set("Location", "/users/sign_in")
				w.WriteHeader(http.StatusFound)
			},
		},
	}
	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			host, port := startServer(t, pathRouter{"/": tc.handler})
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()

			m := newHTTPProbe(t).Probe(ctx, Target{Host: host, Port: port})
			if m == nil {
				t.Fatal("probe returned nil; expected gitlab")
			}
			if m.Product != "gitlab" {
				t.Fatalf("product = %q, want %q", m.Product, "gitlab")
			}
		})
	}
}

// TestFingerprinter_Wants pins down the path-routing contract every
// fingerprinter declares. Catching a typo here is cheaper than chasing
// "why doesn't gitlab show up anymore" in production.
func TestFingerprinter_Wants(t *testing.T) {
	cases := []struct {
		fp    HTTPFingerprinter
		wants []string
		skips []string
	}{
		{minioFingerprinter{}, []string{"/", "/minio/health/ready"}, []string{"/-/health", "/web/login"}},
		{gitlabFingerprinter{}, []string{"/", "/-/health", "/api/v4/version"}, []string{"/status.php", "/web/login"}},
		{nextcloudFingerprinter{}, []string{"/status.php"}, []string{"/", "/-/health"}},
		{trinoFingerprinter{}, []string{"/v1/info"}, []string{"/", "/web/login"}},
		{odooFingerprinter{}, []string{"/web/login"}, []string{"/", "/v1/info"}},
		{nginxFingerprinter{}, []string{"/"}, []string{"/-/health", "/v1/info", "/web/login"}},
	}
	for _, tc := range cases {
		t.Run(tc.fp.Name(), func(t *testing.T) {
			for _, p := range tc.wants {
				if !tc.fp.Wants(p) {
					t.Errorf("Wants(%q) = false, want true", p)
				}
			}
			for _, p := range tc.skips {
				if tc.fp.Wants(p) {
					t.Errorf("Wants(%q) = true, want false", p)
				}
			}
		})
	}
}

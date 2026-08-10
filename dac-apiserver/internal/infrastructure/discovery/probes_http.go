package discovery

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

// httpProbe identifies HTTP(S) services and runs registered
// HTTPFingerprinters against the responses it gathers.
//
// It first tries plain HTTP. If that fails, it tries TLS — but only
// after a cheap handshake check, because attempting HTTPS against a
// service that doesn't speak TLS produces ugly multi-second errors.
//
// Fingerprinters are split into two lists so that a generic detector
// (e.g. "Server: nginx") can never shadow a specific one whose stronger
// signal lives on a later path. GitLab CE used to be misidentified as
// nginx because nginxFingerprinter matched on "/" before
// gitlabFingerprinter ever saw "/api/v4/version"; that's exactly what
// the detectors/fallbacks split prevents.
type httpProbe struct {
	client    *http.Client
	timeout   time.Duration
	detectors []HTTPFingerprinter // specific product detectors
	fallbacks []HTTPFingerprinter // generic, consulted only if no detector matched
}

// fingerprinters returns the union of specific detectors and generic
// fallbacks. Tests use it to assert the full registered surface.
func (p *httpProbe) fingerprinters() []HTTPFingerprinter {
	all := make([]HTTPFingerprinter, 0, len(p.detectors)+len(p.fallbacks))
	all = append(all, p.detectors...)
	all = append(all, p.fallbacks...)
	return all
}

func (p *httpProbe) Name() string { return "http" }

func (p *httpProbe) Probe(ctx context.Context, t Target) *Match {
	if m := p.probeScheme(ctx, t, "http"); m != nil {
		return m
	}
	if !p.tlsHandshake(ctx, t) {
		return nil
	}
	if m := p.probeScheme(ctx, t, "https"); m != nil {
		m.TLS = true
		return m
	}
	return nil
}

// probeScheme fetches a small set of known fingerprinting paths and
// asks every registered HTTPFingerprinter to look at each response.
//
// Specific detectors run first across all paths. Only if none of them
// match does the generic fallback list (e.g. nginx) get a chance.
// Skipping that two-pass split is what made GitLab look like nginx
// in production — a regression test pins the new behaviour.
//
// If none of the fingerprinters match but at least one path returned
// an HTTP response, we still return a generic http Match so the caller
// records "open HTTP service" rather than "unknown".
func (p *httpProbe) probeScheme(ctx context.Context, t Target, scheme string) *Match {
	base := fmt.Sprintf("%s://%s:%d", scheme, t.Host, t.Port)

	// Paths are ordered cheapest-first, with "/" as the universal
	// fallback. Each fingerprinter declares which paths it cares
	// about; unrelated fingerprinters don't even peek at the response.
	paths := []string{
		"/",                   // Server header, generic banners
		"/minio/health/ready", // MinIO
		"/-/health",           // GitLab CE (Omnibus health endpoint)
		"/-/liveness",         // GitLab CE (workhorse; 200 once Puma is up)
		"/api/v4/version",     // GitLab CE (returns 401 even unauth)
		"/status.php",         // Nextcloud
		"/v1/info",            // Trino
		"/web/login",          // Odoo
		"/graphql/",           // Saleor API
		"/dashboard/",         // Saleor Dashboard
	}

	type cachedResp struct {
		path string
		resp *http.Response
		body []byte
	}

	var (
		matched     *Match
		sawResponse bool
		generic     = map[string]string{}
		// Cap is paths × 64 KiB body each ≈ 0.5 MiB; bounded and freed
		// when probeScheme returns. Caching lets fallbacks see every
		// response without re-fetching.
		responses = make([]cachedResp, 0, len(paths))
	)

	for _, path := range paths {
		resp, body, err := p.fetch(ctx, base+path)
		if err != nil {
			continue
		}
		sawResponse = true

		// Capture metadata from the root path only, so the UI sees
		// the most representative status/server, not whatever the
		// last fingerprinting probe happened to return.
		if path == "/" {
			generic["http.status"] = fmt.Sprintf("%d", resp.StatusCode)
			if v := resp.Header.Get("Server"); v != "" {
				generic["http.server"] = v
			}
			if v := resp.Header.Get("Content-Type"); v != "" {
				generic["http.contentType"] = v
			}
		}

		responses = append(responses, cachedResp{path: path, resp: resp, body: body})

		if matched != nil {
			continue
		}
		ev := httpEvidence{path: path, resp: resp, body: body}
		for _, fp := range p.detectors {
			if !fp.Wants(path) {
				continue
			}
			if m := fp.Identify(ev); m != nil {
				if m.Metadata == nil {
					m.Metadata = map[string]string{}
				}
				matched = m
				break
			}
		}
	}

	// Fallbacks (e.g. nginx) only get a turn when no specific detector
	// claimed the target. Replay every cached response against them so
	// generic signals on later paths still land.
	if matched == nil {
		for _, r := range responses {
			ev := httpEvidence{path: r.path, resp: r.resp, body: r.body}
			for _, fp := range p.fallbacks {
				if !fp.Wants(r.path) {
					continue
				}
				if m := fp.Identify(ev); m != nil {
					if m.Metadata == nil {
						m.Metadata = map[string]string{}
					}
					matched = m
					break
				}
			}
			if matched != nil {
				break
			}
		}
	}

	if matched != nil {
		for k, v := range generic {
			if _, ok := matched.Metadata[k]; !ok {
				matched.Metadata[k] = v
			}
		}
		if matched.ServiceType == "" {
			matched.ServiceType = "http"
		}
		return matched
	}
	if sawResponse {
		return &Match{ServiceType: "http", Metadata: generic}
	}
	return nil
}

func (p *httpProbe) fetch(ctx context.Context, url string) (*http.Response, []byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("User-Agent", "dac-discovery/0.1")
	resp, err := p.client.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	// Cap at 64 KiB: fingerprinters only need banners and headers,
	// and a misbehaving target shouldn't be able to OOM the scanner.
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	return resp, body, nil
}

func (p *httpProbe) tlsHandshake(ctx context.Context, t Target) bool {
	d := &net.Dialer{Timeout: p.timeout}
	conn, err := tls.DialWithDialer(d, "tcp", t.Addr(), &tls.Config{
		InsecureSkipVerify: true,
		ServerName:         t.Host,
	})
	if err != nil {
		return false
	}
	_ = conn.SetDeadline(time.Now().Add(p.timeout))
	_ = conn.Close()
	return true
}

// HTTPFingerprinter is the small interface every product detector
// implements. New products mean a new file with a new fingerprinter
// and one append in defaultHTTPFingerprinters — no existing detector
// gets touched.
type HTTPFingerprinter interface {
	// Name is used in tests/logs.
	Name() string

	// Wants reports whether this fingerprinter cares about the
	// given path. It lets us skip irrelevant probes early instead
	// of having every detector inspect every response.
	Wants(path string) bool

	// Identify inspects an HTTP response. Returning nil means
	// "this is not my product"; a non-nil Match short-circuits
	// the rest of the fingerprinter list.
	Identify(ev httpEvidence) *Match
}

// httpEvidence is the bundle of facts an HTTPFingerprinter sees.
// Keeping the struct small (no maps to mutate) makes table tests trivial.
type httpEvidence struct {
	path string
	resp *http.Response
	body []byte
}

// defaultHTTPDetectors is the ordered list of product-specific
// detectors. They run first against every fetched path; only if they
// all miss do we fall back to defaultHTTPFallbacks.
func defaultHTTPDetectors() []HTTPFingerprinter {
	return []HTTPFingerprinter{
		minioFingerprinter{},
		gitlabFingerprinter{},
		nextcloudFingerprinter{},
		trinoFingerprinter{},
		odooFingerprinter{},
		saleorFingerprinter{},
		boutiqueFingerprinter{},
	}
}

// defaultHTTPFallbacks holds generic detectors that should never
// shadow a specific one. nginx in particular fronts GitLab, MinIO,
// Nextcloud and others — matching it before a product detector
// finishes scanning all paths is exactly the bug the split fixes.
func defaultHTTPFallbacks() []HTTPFingerprinter {
	return []HTTPFingerprinter{
		nginxFingerprinter{},
	}
}

// --- product fingerprinters ------------------------------------------------

type minioFingerprinter struct{}

func (minioFingerprinter) Name() string             { return "minio" }
func (minioFingerprinter) Wants(p string) bool      { return p == "/" || p == "/minio/health/ready" }
func (minioFingerprinter) Identify(e httpEvidence) *Match {
	server := strings.ToLower(e.resp.Header.Get("Server"))
	if strings.Contains(server, "minio") || bytes.Contains(e.body, []byte("MinIO")) {
		return &Match{ServiceType: "http", Product: "minio"}
	}
	// /minio/health/ready returns 200 with empty body when the cluster
	// is up. Not everyone serves it, so this is a soft signal.
	if e.path == "/minio/health/ready" && e.resp.StatusCode == http.StatusOK {
		return &Match{ServiceType: "http", Product: "minio"}
	}
	return nil
}

// gitlabFingerprinter detects GitLab CE / EE.
//
// Strong signals (in order of confidence):
//   - GET /-/health returns 200 with body "GitLab OK" once the
//     instance has finished reconfigure.
//   - GET /api/v4/version returns 401 Unauthorized even without a
//     token (the endpoint exists but requires auth); the JSON body
//     and "WWW-Authenticate" header confirm it's GitLab.
//   - Root path sets a "_gitlab_session" cookie and embeds GitLab
//     branding/asset URLs in the HTML.
type gitlabFingerprinter struct{}

func (gitlabFingerprinter) Name() string { return "gitlab" }
func (gitlabFingerprinter) Wants(p string) bool {
	return p == "/" || p == "/-/health" || p == "/-/liveness" || p == "/api/v4/version"
}
func (gitlabFingerprinter) Identify(e httpEvidence) *Match {
	switch e.path {
	case "/-/health":
		if e.resp.StatusCode == http.StatusOK && bytes.Contains(e.body, []byte("GitLab OK")) {
			return &Match{ServiceType: "http", Product: "gitlab"}
		}
	case "/-/liveness":
		// Omnibus workhorse serves this once Rails is up. Body is typically "GitLab OK"
		// or empty 200; 502 during first boot must not count.
		if e.resp.StatusCode == http.StatusOK {
			if len(e.body) == 0 || bytes.Contains(e.body, []byte("GitLab")) || bytes.Contains(e.body, []byte("OK")) {
				return &Match{ServiceType: "http", Product: "gitlab"}
			}
		}
	case "/api/v4/version":
		// 200 (with token) or 401 (without) both prove the endpoint
		// exists. Match if either status code is paired with GitLab
		// markers.
		if e.resp.StatusCode == http.StatusOK || e.resp.StatusCode == http.StatusUnauthorized {
			if bytes.Contains(e.body, []byte("version")) || bytes.Contains(e.body, []byte("401 Unauthorized")) {
				m := &Match{ServiceType: "http", Product: "gitlab"}
				var v struct {
					Version string `json:"version"`
				}
				if err := json.Unmarshal(e.body, &v); err == nil && v.Version != "" {
					m.Version = v.Version
				}
				return m
			}
		}
	case "/":
		// Header-based signals first: they survive when the response
		// is a 302 to /users/sign_in (no body, no _gitlab_session
		// cookie yet, no "GitLab" string). The sandbox hits this
		// path on every scan, which is why we can't rely on body
		// scraping alone.
		for k := range e.resp.Header {
			if strings.HasPrefix(k, "X-Gitlab-") {
				return &Match{ServiceType: "http", Product: "gitlab"}
			}
		}
		if v := e.resp.Header.Get("Server"); v != "" {
			low := strings.ToLower(v)
			if strings.Contains(low, "gitlab") || strings.Contains(low, "workhorse") {
				return &Match{ServiceType: "http", Product: "gitlab"}
			}
		}
		if loc := e.resp.Header.Get("Location"); loc != "" {
			low := strings.ToLower(loc)
			if strings.Contains(low, "/users/sign_in") || strings.Contains(low, "gitlab") {
				return &Match{ServiceType: "http", Product: "gitlab"}
			}
		}
		for _, c := range e.resp.Cookies() {
			if c.Name == "_gitlab_session" {
				return &Match{ServiceType: "http", Product: "gitlab"}
			}
		}
		if bytes.Contains(e.body, []byte("GitLab")) || bytes.Contains(e.body, []byte("gitlab")) {
			return &Match{ServiceType: "http", Product: "gitlab"}
		}
	}
	return nil
}

type nextcloudFingerprinter struct{}

func (nextcloudFingerprinter) Name() string        { return "nextcloud" }
func (nextcloudFingerprinter) Wants(p string) bool { return p == "/status.php" }
func (nextcloudFingerprinter) Identify(e httpEvidence) *Match {
	if e.resp.StatusCode != http.StatusOK || !bytes.Contains(e.body, []byte("Nextcloud")) {
		return nil
	}
	m := &Match{ServiceType: "http", Product: "nextcloud"}
	var s struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(e.body, &s); err == nil && s.Version != "" {
		m.Version = s.Version
	}
	return m
}

type trinoFingerprinter struct{}

func (trinoFingerprinter) Name() string        { return "trino" }
func (trinoFingerprinter) Wants(p string) bool { return p == "/v1/info" }
func (trinoFingerprinter) Identify(e httpEvidence) *Match {
	if e.resp.StatusCode != http.StatusOK || !bytes.Contains(e.body, []byte("nodeVersion")) {
		return nil
	}
	m := &Match{ServiceType: "http", Product: "trino"}
	var info struct {
		NodeVersion struct {
			Version string `json:"version"`
		} `json:"nodeVersion"`
	}
	if err := json.Unmarshal(e.body, &info); err == nil {
		m.Version = info.NodeVersion.Version
	}
	return m
}

type odooFingerprinter struct{}

func (odooFingerprinter) Name() string        { return "odoo" }
func (odooFingerprinter) Wants(p string) bool { return p == "/" || p == "/web/login" }
func (odooFingerprinter) Identify(e httpEvidence) *Match {
	// Allow redirects to the login form; reject hard 5xx (DB not ready).
	if e.resp.StatusCode >= 500 {
		return nil
	}
	lowBody := bytes.ToLower(e.body)
	if bytes.Contains(lowBody, []byte("odoo")) {
		return &Match{ServiceType: "http", Product: "odoo"}
	}
	if loc := strings.ToLower(e.resp.Header.Get("Location")); strings.Contains(loc, "/web") {
		return &Match{ServiceType: "http", Product: "odoo"}
	}
	if e.path == "/web/login" && e.resp.StatusCode >= 200 && e.resp.StatusCode < 400 {
		// Login route exists even when the body is a minimal shell.
		if v := strings.ToLower(e.resp.Header.Get("Set-Cookie")); strings.Contains(v, "session_id") {
			return &Match{ServiceType: "http", Product: "odoo"}
		}
	}
	return nil
}

// saleorFingerprinter detects Saleor GraphQL API and Dashboard.
type saleorFingerprinter struct{}

func (saleorFingerprinter) Name() string { return "saleor" }
func (saleorFingerprinter) Wants(p string) bool {
	return p == "/" || p == "/graphql/" || p == "/dashboard/"
}
func (saleorFingerprinter) Identify(e httpEvidence) *Match {
	if e.resp.StatusCode >= 500 {
		return nil
	}
	server := strings.ToLower(e.resp.Header.Get("Server"))
	ct := strings.ToLower(e.resp.Header.Get("Content-Type"))
	lowBody := bytes.ToLower(e.body)

	switch e.path {
	case "/graphql/":
		// Unauthenticated GET often 405/400 with GraphQL hints; POST playground may 200.
		if e.resp.StatusCode == http.StatusOK || e.resp.StatusCode == http.StatusMethodNotAllowed ||
			e.resp.StatusCode == http.StatusBadRequest {
			if bytes.Contains(lowBody, []byte("saleor")) ||
				bytes.Contains(lowBody, []byte("graphql")) ||
				strings.Contains(ct, "json") {
				// Prefer positive Saleor markers; plain GraphQL alone is weak.
				if bytes.Contains(lowBody, []byte("saleor")) ||
					bytes.Contains(lowBody, []byte("csrf")) ||
					e.resp.Header.Get("X-Saleor-Version") != "" {
					return &Match{ServiceType: "http", Product: "saleor"}
				}
			}
		}
		if e.resp.Header.Get("X-Saleor-Version") != "" {
			return &Match{
				ServiceType: "http",
				Product:     "saleor",
				Version:     e.resp.Header.Get("X-Saleor-Version"),
			}
		}
	case "/dashboard/":
		if e.resp.StatusCode < 400 && (bytes.Contains(lowBody, []byte("saleor")) ||
			bytes.Contains(lowBody, []byte("dashboard"))) {
			return &Match{ServiceType: "http", Product: "saleor-dashboard"}
		}
	case "/":
		if bytes.Contains(lowBody, []byte("saleor")) || strings.Contains(server, "saleor") {
			return &Match{ServiceType: "http", Product: "saleor"}
		}
	}
	return nil
}

// boutiqueFingerprinter detects Google Online Boutique (Hipster Shop) frontend.
type boutiqueFingerprinter struct{}

func (boutiqueFingerprinter) Name() string        { return "boutique" }
func (boutiqueFingerprinter) Wants(p string) bool { return p == "/" }
func (boutiqueFingerprinter) Identify(e httpEvidence) *Match {
	if e.resp.StatusCode >= 500 {
		return nil
	}
	lowBody := bytes.ToLower(e.body)
	// Upstream demo branding + cart/product markers.
	if bytes.Contains(lowBody, []byte("online boutique")) ||
		bytes.Contains(lowBody, []byte("hipster shop")) ||
		bytes.Contains(lowBody, []byte("hot products")) ||
		(bytes.Contains(lowBody, []byte("cart")) && bytes.Contains(lowBody, []byte("currency"))) {
		return &Match{ServiceType: "http", Product: "boutique"}
	}
	return nil
}

// nginxFingerprinter is the generic fallback for plain nginx-served
// content (e.g. our sandbox fileserver). It only fires when no more
// specific detector claimed the response, because it sits last in
// defaultHTTPFingerprinters.
type nginxFingerprinter struct{}

func (nginxFingerprinter) Name() string        { return "nginx" }
func (nginxFingerprinter) Wants(p string) bool { return p == "/" }
func (nginxFingerprinter) Identify(e httpEvidence) *Match {
	server := e.resp.Header.Get("Server")
	if server == "" {
		return nil
	}
	low := strings.ToLower(server)
	if !strings.Contains(low, "nginx") {
		return nil
	}
	m := &Match{ServiceType: "http", Product: "nginx"}
	// "Server: nginx/1.25.3" → "1.25.3".
	if i := strings.Index(server, "/"); i >= 0 && i+1 < len(server) {
		m.Version = strings.TrimSpace(server[i+1:])
	}
	// Autoindex pages are an obvious hint that this is a fileserver,
	// which is exactly how the sandbox uses nginx.
	if bytes.Contains(e.body, []byte("Index of /")) {
		m.Product = "fileserver"
		m.Metadata = map[string]string{"engine": "nginx"}
	}
	return m
}

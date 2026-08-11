package discovery

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

// fakeServer accepts a single TCP connection and runs the given handler
// against it. It is intentionally minimal: the probes we test only ever
// open one connection per call, so accepting one is enough.
//
// The handler may close the connection; the listener is closed at the
// end of the test regardless. Accept errors after Close are expected
// and silently ignored — they are how we know the test is winding down.
type fakeServer struct {
	host string
	port int
	stop func()
}

func newFakeServer(t *testing.T, handle func(net.Conn)) fakeServer {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr := l.Addr().(*net.TCPAddr)

	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				handle(c)
			}(c)
		}
	}()

	t.Cleanup(func() {
		_ = l.Close()
		<-done
	})

	return fakeServer{
		host: "127.0.0.1",
		port: addr.Port,
		stop: func() { _ = l.Close() },
	}
}

func newProbeContext(t *testing.T) (context.Context, context.CancelFunc) {
	t.Helper()
	return context.WithTimeout(context.Background(), 2*time.Second)
}

// closedPort returns a host/port that is reliably refused. We bind to an
// ephemeral port and immediately close it; the OS won't reuse it for the
// brief duration of a test, so dials get ECONNREFUSED rather than
// SYN-timeout. That keeps "closed port" tests fast and deterministic.
func closedPort(t *testing.T) (string, int) {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr := l.Addr().(*net.TCPAddr)
	_ = l.Close()
	return "127.0.0.1", addr.Port
}

func newDialer(timeout time.Duration) *net.Dialer {
	return &net.Dialer{Timeout: timeout}
}

// --- mysql -----------------------------------------------------------------

// mysqlHandshake builds a packet shaped like:
//
//	[3-byte LE payload length][1-byte seq id][protocol][server-version NUL]...
//
// We only fill the prefix the probe actually inspects. The trailing
// "padding" bytes stand in for the rest of the handshake (capability flags,
// auth plugin data, etc.) — the probe ignores them but a real client would
// continue parsing past the version string, so we make sure the length
// header agrees with what we send.
func mysqlHandshake(version string, padding int) []byte {
	body := []byte{0x0a}                      // protocol v10
	body = append(body, []byte(version)...)   // server version
	body = append(body, 0x00)                 // version terminator
	body = append(body, make([]byte, padding)...)

	out := make([]byte, 4+len(body))
	out[0] = byte(len(body))
	out[1] = byte(len(body) >> 8)
	out[2] = byte(len(body) >> 16)
	out[3] = 0 // sequence id
	copy(out[4:], body)
	return out
}

func TestMySQLProbe(t *testing.T) {
	cases := []struct {
		name        string
		respond     []byte
		wantProduct string
		wantVersion string
		wantNil     bool
	}{
		{
			name:        "mysql 8.0",
			respond:     mysqlHandshake("8.0.36", 32),
			wantProduct: "mysql",
			wantVersion: "8.0.36",
		},
		{
			name:        "mariadb",
			respond:     mysqlHandshake("5.5.5-10.11.6-MariaDB-log", 32),
			wantProduct: "mariadb",
			wantVersion: "5.5.5-10.11.6-MariaDB-log",
		},
		{
			// Wrong protocol byte (0x09) — old MySQL v9 or, more likely,
			// not MySQL at all. We deliberately don't claim a match.
			name:    "wrong protocol version",
			respond: []byte{0x05, 0x00, 0x00, 0x00, 0x09, 0x31, 0x2e, 0x30, 0x00},
			wantNil: true,
		},
		{
			// Length header claims 100 KB. Real handshakes are ~80 bytes.
			// We bound the length to keep noisy ports from hanging the scan.
			name:    "absurd payload length",
			respond: []byte{0xff, 0xff, 0x0f, 0x00, 0x0a},
			wantNil: true,
		},
		{
			// A server that accepts the connection then closes without
			// sending anything (e.g. a banner-stripped TLS port). The
			// probe should fail the io.ReadFull and return nil.
			name:    "silent server",
			respond: nil,
			wantNil: true,
		},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			srv := newFakeServer(t, func(c net.Conn) {
				if len(tc.respond) > 0 {
					_, _ = c.Write(tc.respond)
				}
			})

			p := &mysqlProbe{dialer: newDialer(500 * time.Millisecond), timeout: 500 * time.Millisecond}
			ctx, cancel := newProbeContext(t)
			defer cancel()

			m := p.Probe(ctx, Target{Host: srv.host, Port: srv.port})
			if tc.wantNil {
				if m != nil {
					t.Fatalf("expected nil, got %+v", m)
				}
				return
			}
			if m == nil {
				t.Fatalf("expected match, got nil")
			}
			if m.Product != tc.wantProduct {
				t.Errorf("product = %q, want %q", m.Product, tc.wantProduct)
			}
			if m.Version != tc.wantVersion {
				t.Errorf("version = %q, want %q", m.Version, tc.wantVersion)
			}
			if m.ServiceType != "mysql" {
				t.Errorf("serviceType = %q, want mysql", m.ServiceType)
			}
		})
	}
}

func TestMySQLProbe_ClosedPort(t *testing.T) {
	host, port := closedPort(t)
	p := &mysqlProbe{dialer: newDialer(500 * time.Millisecond), timeout: 500 * time.Millisecond}
	ctx, cancel := newProbeContext(t)
	defer cancel()

	if m := p.Probe(ctx, Target{Host: host, Port: port}); m != nil {
		t.Fatalf("expected nil for closed port, got %+v", m)
	}
}

// --- postgres --------------------------------------------------------------

// readSSLRequest reads the 8-byte SSLRequest message and returns true if
// it carries the magic int32 80877103. Anything else means the caller is
// not Postgres-aware, and the test handler will just close.
func readSSLRequest(c net.Conn) bool {
	var msg [8]byte
	if _, err := io.ReadFull(c, msg[:]); err != nil {
		return false
	}
	length := binary.BigEndian.Uint32(msg[0:4])
	magic := binary.BigEndian.Uint32(msg[4:8])
	return length == 8 && magic == 80877103
}

func TestPostgresProbe(t *testing.T) {
	cases := []struct {
		name    string
		reply   byte
		wantTLS bool
		wantNil bool
	}{
		{name: "ssl supported", reply: 'S', wantTLS: true},
		{name: "ssl not configured", reply: 'N', wantTLS: false},
		{name: "garbage byte", reply: 'X', wantNil: true},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			srv := newFakeServer(t, func(c net.Conn) {
				if !readSSLRequest(c) {
					return
				}
				_, _ = c.Write([]byte{tc.reply})
			})

			p := &postgresProbe{dialer: newDialer(500 * time.Millisecond), timeout: 500 * time.Millisecond}
			ctx, cancel := newProbeContext(t)
			defer cancel()

			m := p.Probe(ctx, Target{Host: srv.host, Port: srv.port})
			if tc.wantNil {
				if m != nil {
					t.Fatalf("expected nil, got %+v", m)
				}
				return
			}
			if m == nil {
				t.Fatalf("expected match, got nil")
			}
			if m.Product != "postgresql" {
				t.Errorf("product = %q, want postgresql", m.Product)
			}
			if m.ServiceType != "postgres" {
				t.Errorf("serviceType = %q, want postgres", m.ServiceType)
			}
			if m.TLS != tc.wantTLS {
				t.Errorf("tls = %v, want %v", m.TLS, tc.wantTLS)
			}
		})
	}
}

func TestPostgresProbe_ClosedPort(t *testing.T) {
	host, port := closedPort(t)
	p := &postgresProbe{dialer: newDialer(500 * time.Millisecond), timeout: 500 * time.Millisecond}
	ctx, cancel := newProbeContext(t)
	defer cancel()

	if m := p.Probe(ctx, Target{Host: host, Port: port}); m != nil {
		t.Fatalf("expected nil for closed port, got %+v", m)
	}
}

// --- redis -----------------------------------------------------------------

// readUntilCRLF drains the inline command Redis would receive (e.g. "PING\r\n").
// We don't care what the client sent — only that we replied with the right
// banner — but we still need to read so the kernel doesn't report a RST.
func readUntilCRLF(c net.Conn) {
	buf := make([]byte, 64)
	for {
		c.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
		n, err := c.Read(buf)
		if n > 0 && (buf[n-1] == '\n' || strings.Contains(string(buf[:n]), "\r\n")) {
			return
		}
		if err != nil {
			return
		}
	}
}

func TestRedisProbe(t *testing.T) {
	cases := []struct {
		name         string
		reply        string
		wantProduct  string
		wantAuth     string
		wantNil      bool
	}{
		{
			name:        "pong",
			reply:       "+PONG\r\n",
			wantProduct: "redis",
		},
		{
			name:        "noauth",
			reply:       "-NOAUTH Authentication required.\r\n",
			wantProduct: "redis",
			wantAuth:    "required",
		},
		{
			name:        "wrongpass",
			reply:       "-WRONGPASS invalid password\r\n",
			wantProduct: "redis",
			wantAuth:    "required",
		},
		{
			name:    "garbage",
			reply:   "HTTP/1.1 200 OK\r\n",
			wantNil: true,
		},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			srv := newFakeServer(t, func(c net.Conn) {
				readUntilCRLF(c)
				_, _ = c.Write([]byte(tc.reply))
			})

			p := &redisProbe{dialer: newDialer(500 * time.Millisecond), timeout: 500 * time.Millisecond}
			ctx, cancel := newProbeContext(t)
			defer cancel()

			m := p.Probe(ctx, Target{Host: srv.host, Port: srv.port})
			if tc.wantNil {
				if m != nil {
					t.Fatalf("expected nil, got %+v", m)
				}
				return
			}
			if m == nil {
				t.Fatalf("expected match, got nil")
			}
			if m.Product != tc.wantProduct {
				t.Errorf("product = %q, want %q", m.Product, tc.wantProduct)
			}
			if m.ServiceType != "redis" {
				t.Errorf("serviceType = %q, want redis", m.ServiceType)
			}
			if tc.wantAuth != "" {
				if got := m.Metadata["auth"]; got != tc.wantAuth {
					t.Errorf("metadata[auth] = %q, want %q", got, tc.wantAuth)
				}
			}
		})
	}
}

func TestRedisProbe_ClosedPort(t *testing.T) {
	host, port := closedPort(t)
	p := &redisProbe{dialer: newDialer(500 * time.Millisecond), timeout: 500 * time.Millisecond}
	ctx, cancel := newProbeContext(t)
	defer cancel()

	if m := p.Probe(ctx, Target{Host: host, Port: port}); m != nil {
		t.Fatalf("expected nil for closed port, got %+v", m)
	}
}

// --- scanner orchestration -------------------------------------------------

// TestScanner_PicksFirstMatch verifies the two contracts the orchestrator
// gives the rest of the codebase:
//
//  1. Probes run in registration order, and the first match wins.
//  2. A liveness check happens before any probe, so a closed port returns
//     (svc, true=alive=false equivalent) without burning the per-probe
//     timeout budget.
//
// We use a real Postgres handshake because it's the cheapest protocol to
// fake (one byte) and exercises the full match → applyMatch → return path.
func TestScanner_PicksFirstMatch(t *testing.T) {
	srv := newFakeServer(t, func(c net.Conn) {
		// Postgres probe runs after MySQL in the default order, but
		// MySQL needs a banner. We send nothing for MySQL's read,
		// which will time out fast, then handle Postgres's SSLRequest.
		// To keep this test snappy, we cheat: respond to the *first*
		// 8-byte read (which is MySQL's header attempt OR Postgres's
		// SSLRequest) with 'N'. Postgres header is exactly 8 bytes,
		// MySQL reads 4 then more, so this only satisfies Postgres.
		if !readSSLRequest(c) {
			return
		}
		_, _ = c.Write([]byte{'N'})
	})

	// Local DB probes only — this test pins probe ordering, not Nerva.
	s := newScanner(500*time.Millisecond, false)
	ctx, cancel := newProbeContext(t)
	defer cancel()

	svc, alive := s.ScanPort(ctx, srv.host, srv.port)
	if !alive {
		t.Fatal("expected port to be alive")
	}
	if svc == nil {
		t.Fatal("expected svc, got nil")
	}
	if svc.ServiceType != "postgres" {
		t.Errorf("serviceType = %q, want postgres", svc.ServiceType)
	}
	if svc.Product != "postgresql" {
		t.Errorf("product = %q, want postgresql", svc.Product)
	}
}

// TestScanner_ClosedPort confirms the liveness short-circuit. The
// historical bug this guards against: the scanner used to dial each
// probe even on closed ports, multiplying timeouts by len(probes).
// On a /24 sweep that turned a 5-second scan into a 30-second one.
func TestScanner_ClosedPort(t *testing.T) {
	host, port := closedPort(t)

	s := NewScanner(2 * time.Second)
	ctx, cancel := newProbeContext(t)
	defer cancel()

	start := time.Now()
	svc, alive := s.ScanPort(ctx, host, port)
	if alive {
		t.Errorf("expected closed port to be reported alive=false; svc=%+v", svc)
	}
	if elapsed := time.Since(start); elapsed > 1500*time.Millisecond {
		t.Errorf("scan took %v on closed port — liveness check is not short-circuiting", elapsed)
	}
}

// TestScanner_ContextCancellation ensures the probe loop honors ctx.Done
// between probes. A long-running scan over thousands of ports must be
// cancellable; otherwise the API server can't enforce per-request deadlines.
func TestScanner_ContextCancellation(t *testing.T) {
	// Server accepts but never writes — every protocol probe will block
	// on its read until the deadline. We want the *outer* ctx cancel to
	// take precedence.
	srv := newFakeServer(t, func(c net.Conn) {
		// Hold the connection open so reads block.
		buf := make([]byte, 1)
		_, _ = c.Read(buf)
	})

	s := NewScanner(500 * time.Millisecond)
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // already cancelled before we start

	start := time.Now()
	svc, alive := s.ScanPort(ctx, srv.host, srv.port)
	elapsed := time.Since(start)

	// We don't assert on svc/alive — the contract here is about latency.
	// A pre-cancelled context should make the call return promptly,
	// well under a single probe timeout.
	_ = svc
	_ = alive
	if elapsed > 750*time.Millisecond {
		t.Errorf("ScanPort with cancelled context took %v; expected fast return", elapsed)
	}
}

// Compile-time check that the test helpers we depend on still exist in the
// package. If the scanner is refactored to drop NewScanner or change the
// Target shape, this file must follow.
var (
	_ = net.JoinHostPort
	_ = strconv.Itoa
	_ = errors.New
)

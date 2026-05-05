package discovery

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"io"
	"net"
	"time"
)

// mysqlProbe identifies a MySQL/MariaDB server by its initial handshake
// packet. A real MySQL server starts talking the moment the TCP connection
// is established, sending:
//
//	[3 bytes payload length][1 byte sequence id][payload...]
//
// where the first payload byte is the protocol version (0x0a for v10),
// followed by a NUL-terminated server version string. We rely on that
// shape — it's stable across MySQL 5.x/8.x and MariaDB.
type mysqlProbe struct {
	dialer  *net.Dialer
	timeout time.Duration
}

func (p *mysqlProbe) Name() string { return "mysql" }

func (p *mysqlProbe) Probe(ctx context.Context, t Target) *Match {
	conn, err := p.dialer.DialContext(ctx, "tcp", t.Addr())
	if err != nil {
		return nil
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(p.timeout))

	r := bufio.NewReader(conn)

	var header [4]byte
	if _, err := io.ReadFull(r, header[:]); err != nil {
		return nil
	}
	// Little-endian 24-bit payload length, then 1 byte sequence id.
	payloadLen := int(uint32(header[0]) | uint32(header[1])<<8 | uint32(header[2])<<16)
	// Sanity-bound the length: MySQL handshakes are ~80 bytes; anything
	// over 4 KiB is almost certainly not MySQL and probably an attempt
	// to read random binary data as a length prefix.
	if payloadLen <= 0 || payloadLen > 4096 {
		return nil
	}

	payload := make([]byte, payloadLen)
	if _, err := io.ReadFull(r, payload); err != nil {
		return nil
	}
	// Modern MySQL uses protocol version 10 (0x0a). Older v9 servers
	// (MySQL 3.21 and earlier) would hit this branch, but we don't
	// claim to support them.
	if len(payload) < 2 || payload[0] != 0x0a {
		return nil
	}

	m := &Match{ServiceType: "mysql", Product: "mysql"}

	// Server version is a NUL-terminated string starting at payload[1].
	// MariaDB encodes itself as e.g. "5.5.5-10.11.6-MariaDB"; the prefix
	// "5.5.5-" is a legacy compatibility hack we leave in place.
	if nul := bytes.IndexByte(payload[1:], 0x00); nul > 0 {
		version := string(payload[1 : 1+nul])
		m.Version = version
		if bytes.Contains([]byte(version), []byte("MariaDB")) {
			m.Product = "mariadb"
		}
	}
	return m
}

// postgresProbe identifies a PostgreSQL server using the SSLRequest
// startup message. Postgres replies with a single byte:
//
//	'S' → SSL supported, may proceed with TLS
//	'N' → SSL not configured, plain TCP only
//
// Any other byte is not Postgres. We don't actually upgrade to TLS;
// the byte alone is enough to identify the service.
//
// Version detection from a startup message would require completing
// the auth handshake (parsing ParameterStatus messages), which means
// dealing with credentials. For a passive scanner that's not worth it.
type postgresProbe struct {
	dialer  *net.Dialer
	timeout time.Duration
}

func (p *postgresProbe) Name() string { return "postgres" }

func (p *postgresProbe) Probe(ctx context.Context, t Target) *Match {
	conn, err := p.dialer.DialContext(ctx, "tcp", t.Addr())
	if err != nil {
		return nil
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(p.timeout))

	// SSLRequest message: int32 length=8, int32 magic=80877103.
	var msg [8]byte
	binary.BigEndian.PutUint32(msg[0:4], 8)
	binary.BigEndian.PutUint32(msg[4:8], 80877103)
	if _, err := conn.Write(msg[:]); err != nil {
		return nil
	}

	var resp [1]byte
	if _, err := io.ReadFull(conn, resp[:]); err != nil {
		return nil
	}
	if resp[0] != 'S' && resp[0] != 'N' {
		return nil
	}
	return &Match{
		ServiceType: "postgres",
		Product:     "postgresql",
		TLS:         resp[0] == 'S',
	}
}

// redisProbe identifies a Redis server by sending an inline PING.
// Redis (and several Redis-compatible servers like KeyDB and Dragonfly)
// reply with "+PONG\r\n" using the RESP protocol's simple-string form.
//
// We loop the read because some servers split the reply across packets,
// and a single Read may return only "+PO" before the rest arrives.
type redisProbe struct {
	dialer  *net.Dialer
	timeout time.Duration
}

func (p *redisProbe) Name() string { return "redis" }

func (p *redisProbe) Probe(ctx context.Context, t Target) *Match {
	conn, err := p.dialer.DialContext(ctx, "tcp", t.Addr())
	if err != nil {
		return nil
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(p.timeout))

	if _, err := conn.Write([]byte("PING\r\n")); err != nil {
		return nil
	}

	// "+PONG\r\n" is 7 bytes. Read up to 32 to also catch
	// auth-required errors like "-NOAUTH ...", which still
	// confirm we're talking to Redis.
	buf := make([]byte, 32)
	var n int
	for n < len(buf) {
		conn.SetReadDeadline(time.Now().Add(p.timeout))
		k, err := conn.Read(buf[n:])
		if k > 0 {
			n += k
			if bytes.Contains(buf[:n], []byte("\r\n")) {
				break
			}
		}
		if err != nil {
			break
		}
	}
	resp := buf[:n]

	switch {
	case bytes.HasPrefix(resp, []byte("+PONG")):
		return &Match{ServiceType: "redis", Product: "redis"}
	case bytes.HasPrefix(resp, []byte("-NOAUTH")), bytes.HasPrefix(resp, []byte("-WRONGPASS")):
		// Auth-protected Redis still announces itself.
		return &Match{
			ServiceType: "redis",
			Product:     "redis",
			Metadata:    map[string]string{"auth": "required"},
		}
	default:
		return nil
	}
}

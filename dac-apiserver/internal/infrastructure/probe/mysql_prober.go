package probe

import (
	"context"
	"database/sql"
	"fmt"
	"net"
	"strconv"
	"time"

	"github.com/go-sql-driver/mysql"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// SQLOpener abstracts sql.Open so probers can be unit tested without
// requiring a real driver to be available. In production we always use
// stdSQLOpener which delegates to database/sql.
type SQLOpener interface {
	Open(driverName, dataSourceName string) (*sql.DB, error)
}

type stdSQLOpener struct{}

func (stdSQLOpener) Open(driverName, dataSourceName string) (*sql.DB, error) {
	return sql.Open(driverName, dataSourceName)
}

// MySQLProber implements domain.Prober for MySQL / MariaDB.
//
// We deliberately keep the connection lifetime as short as possible:
// open -> query -> close. The probe is a synchronous, request-scoped
// operation; pooling buys us nothing here and would only leak file
// descriptors against unfamiliar endpoints.
type MySQLProber struct {
	opener  SQLOpener
	timeout time.Duration
}

// NewMySQLProber returns a MySQLProber. The timeout is applied to every
// network operation (dial, read, write) AND used as an upper bound on
// the overall probe via context derivation.
func NewMySQLProber(timeout time.Duration) *MySQLProber {
	return &MySQLProber{opener: stdSQLOpener{}, timeout: timeout}
}

// Type returns the canonical source type this prober handles.
func (*MySQLProber) Type() string { return "mysql" }

// Probe opens a short-lived connection, asks the server for its version
// and the list of user-visible schemas, and returns them.
func (p *MySQLProber) Probe(ctx context.Context, t domain.ConnectionTarget) (*domain.ProbeResult, error) {
	cfg := mysql.NewConfig()
	cfg.Net = "tcp"
	cfg.Addr = net.JoinHostPort(t.Host, strconv.Itoa(t.Port))
	cfg.User = t.User
	cfg.Passwd = t.Password
	cfg.AllowNativePasswords = true
	cfg.Timeout = p.timeout
	cfg.ReadTimeout = p.timeout
	cfg.WriteTimeout = p.timeout
	// Query INFORMATION_SCHEMA only; no schema is selected on purpose.

	db, err := p.opener.Open("mysql", cfg.FormatDSN())
	if err != nil {
		return nil, mapMySQLError(err)
	}
	defer db.Close()

	// One connection is enough.
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(p.timeout)

	probeCtx, cancel := context.WithTimeout(ctx, p.timeout)
	defer cancel()

	start := time.Now()
	if err := db.PingContext(probeCtx); err != nil {
		return nil, mapMySQLError(err)
	}

	version, _ := queryScalar(probeCtx, db, "SELECT VERSION()")
	dbs, err := mysqlListDatabases(probeCtx, db)
	if err != nil {
		return nil, mapMySQLError(err)
	}

	return &domain.ProbeResult{
		Databases: dbs,
		Version:   version,
		LatencyMs: time.Since(start).Milliseconds(),
	}, nil
}

// mysqlListDatabases returns user-visible schemas, excluding well-known
// system schemas to keep the UI signal-to-noise high.
func mysqlListDatabases(ctx context.Context, db *sql.DB) ([]string, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT SCHEMA_NAME
		FROM INFORMATION_SCHEMA.SCHEMATA
		WHERE SCHEMA_NAME NOT IN ('information_schema','performance_schema','mysql','sys')
		ORDER BY SCHEMA_NAME
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		out = append(out, name)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

// mapMySQLError converts driver-level errors into domain errors.
// Authentication / access failures are user-visible mistakes, so we
// surface them as InvalidInput. Everything else is opaque "internal".
func mapMySQLError(err error) error {
	if err == nil {
		return nil
	}
	if mErr, ok := err.(*mysql.MySQLError); ok {
		switch mErr.Number {
		case 1045, 1044, 1142: // access denied / no privilege
			return domain.NewInvalidInputError("authentication failed: check user / password / privileges")
		case 1049: // unknown database (we don't select one, but be safe)
			return domain.NewInvalidInputError("database does not exist")
		}
	}
	return domain.NewInternalError(fmt.Errorf("mysql probe failed: %w", err))
}

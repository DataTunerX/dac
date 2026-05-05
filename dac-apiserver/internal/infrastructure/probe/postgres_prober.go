package probe

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"strconv"
	"time"

	"github.com/lib/pq"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// PostgresProber implements domain.Prober for PostgreSQL.
//
// We connect to the well-known "postgres" maintenance database, then
// list user databases via pg_database. The maintenance DB is guaranteed
// to exist on a stock cluster and lets us probe credentials without
// the caller having to know any specific database name in advance.
type PostgresProber struct {
	opener  SQLOpener
	timeout time.Duration
}

func NewPostgresProber(timeout time.Duration) *PostgresProber {
	return &PostgresProber{opener: stdSQLOpener{}, timeout: timeout}
}

func (*PostgresProber) Type() string { return "postgres" }

func (p *PostgresProber) Probe(ctx context.Context, t domain.ConnectionTarget) (*domain.ProbeResult, error) {
	dsn := buildPostgresDSN(t, p.timeout)

	db, err := p.opener.Open("postgres", dsn)
	if err != nil {
		return nil, mapPostgresError(err)
	}
	defer db.Close()

	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(p.timeout)

	probeCtx, cancel := context.WithTimeout(ctx, p.timeout)
	defer cancel()

	start := time.Now()
	if err := db.PingContext(probeCtx); err != nil {
		return nil, mapPostgresError(err)
	}

	version, _ := queryScalar(probeCtx, db, "SHOW server_version")
	dbs, err := postgresListDatabases(probeCtx, db)
	if err != nil {
		return nil, mapPostgresError(err)
	}

	return &domain.ProbeResult{
		Databases: dbs,
		Version:   version,
		LatencyMs: time.Since(start).Milliseconds(),
	}, nil
}

// buildPostgresDSN returns a libpq URI. We force sslmode=disable for
// sandbox usability; production-grade work should layer mTLS at the
// network boundary or extend the ConnectionTarget value object.
func buildPostgresDSN(t domain.ConnectionTarget, timeout time.Duration) string {
	u := url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(t.User, t.Password),
		Host:   t.Host + ":" + strconv.Itoa(t.Port),
		Path:   "/postgres",
	}
	q := u.Query()
	q.Set("sslmode", "disable")
	q.Set("connect_timeout", strconv.Itoa(int(timeout/time.Second)+1))
	u.RawQuery = q.Encode()
	return u.String()
}

func postgresListDatabases(ctx context.Context, db *sql.DB) ([]string, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT datname
		FROM pg_database
		WHERE datistemplate = false
		  AND datname NOT IN ('postgres')
		ORDER BY datname
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
	return out, rows.Err()
}

// mapPostgresError narrows the wide pq error space to the few codes we
// can act on; everything else is returned as an opaque internal error.
//
// SQLSTATE reference:
//   28P01 invalid_password
//   28000 invalid_authorization_specification
//   3D000 invalid_catalog_name
func mapPostgresError(err error) error {
	if err == nil {
		return nil
	}
	if pqErr, ok := err.(*pq.Error); ok {
		switch pqErr.Code {
		case "28P01", "28000":
			return domain.NewInvalidInputError("authentication failed: check user / password")
		case "3D000":
			return domain.NewInvalidInputError("database does not exist")
		}
	}
	return domain.NewInternalError(fmt.Errorf("postgres probe failed: %w", err))
}

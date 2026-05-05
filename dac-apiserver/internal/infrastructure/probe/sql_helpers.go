package probe

import (
	"context"
	"database/sql"
)

// queryScalar runs a query expected to return a single string and returns it.
// On any error or zero rows it returns "" and the error so callers may
// silently ignore it (version banners are best-effort metadata).
func queryScalar(ctx context.Context, db *sql.DB, query string) (string, error) {
	row := db.QueryRowContext(ctx, query)
	var v sql.NullString
	if err := row.Scan(&v); err != nil {
		return "", err
	}
	return v.String, nil
}

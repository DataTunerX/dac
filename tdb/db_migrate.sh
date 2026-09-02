#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DATABASE_URL="${DATABASE_URL:-postgres://tdb:tdb@localhost:5432/tdb}"
MIGRATIONS_DIR="${TDB_MIGRATIONS_DIR:-$ROOT_DIR/db/migrations_v2}"
MIGRATION_PROFILE="${TDB_MIGRATION_PROFILE:-full}"

shopt -s nullglob
migrations=("$MIGRATIONS_DIR"/*.sql)
if [[ ${#migrations[@]} -eq 0 ]]; then
  echo "No migration files found under $MIGRATIONS_DIR"
  exit 0
fi

filtered_migrations=()
for file in "${migrations[@]}"; do
  base="$(basename "$file")"
  case "$MIGRATION_PROFILE" in
    full)
      filtered_migrations+=("$file")
      ;;
    core)
      if [[ "$base" != *_extension.sql ]]; then
        filtered_migrations+=("$file")
      fi
      ;;
    *)
      echo "Unsupported TDB_MIGRATION_PROFILE: $MIGRATION_PROFILE"
      echo "Expected one of: full, core"
      exit 1
      ;;
  esac
done

if [[ ${#filtered_migrations[@]} -eq 0 ]]; then
  echo "No migration files selected under $MIGRATIONS_DIR for profile=$MIGRATION_PROFILE"
  exit 0
fi

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS tdb_schema_migrations (
  filename TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

echo "Applying migrations from: $MIGRATIONS_DIR (profile=$MIGRATION_PROFILE)"
for file in "${filtered_migrations[@]}"; do
  base="$(basename "$file")"
  if [[ ! "$base" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Unsafe migration filename: $base"
    exit 1
  fi
  if psql "$DATABASE_URL" -Atqc \
    "SELECT 1 FROM tdb_schema_migrations WHERE filename = '$base'" | grep -qx 1; then
    echo "Skipping applied migration: $file"
    continue
  fi

  echo "Applying migration: $file"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$file"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO tdb_schema_migrations (filename) VALUES ('$base')"
done

echo "Migrations completed."

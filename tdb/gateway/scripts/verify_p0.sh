#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATEWAY_DIR="$ROOT_DIR/gateway"

export DATABASE_URL="${DATABASE_URL:-postgres://tdb:tdb@localhost:5432/DataV2}"
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-}"

if [[ -z "$TEST_DATABASE_URL" ]]; then
  echo "[verify_p0] TEST_DATABASE_URL is required."
  echo "[verify_p0] acceptance tests drop and recreate the public schema; point TEST_DATABASE_URL at a disposable database."
  exit 1
fi

if [[ "$TEST_DATABASE_URL" == "$DATABASE_URL" && "${ALLOW_DESTRUCTIVE_TEST_DB:-0}" != "1" ]]; then
  echo "[verify_p0] refusing to run because TEST_DATABASE_URL matches DATABASE_URL."
  echo "[verify_p0] acceptance tests run 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' in beforeAll."
  echo "[verify_p0] use a disposable TEST_DATABASE_URL, or set ALLOW_DESTRUCTIVE_TEST_DB=1 only if you intentionally want schema reset on DATABASE_URL."
  exit 1
fi

echo "[verify_p0] DATABASE_URL=$DATABASE_URL"
echo "[verify_p0] TEST_DATABASE_URL=$TEST_DATABASE_URL"

echo "[verify_p0] applying migrations"
"$ROOT_DIR/scripts/db_migrate.sh"

echo "[verify_p0] running gateway typecheck"
(cd "$GATEWAY_DIR" && npm run typecheck)

echo "[verify_p0] running acceptance tests"
(cd "$GATEWAY_DIR" && TEST_DATABASE_URL="$TEST_DATABASE_URL" npm run test:acceptance)

echo "[verify_p0] done"

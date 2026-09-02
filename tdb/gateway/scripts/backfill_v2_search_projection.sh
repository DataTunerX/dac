#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgres://tdb:tdb@localhost:5432/DataV2}"
STREAM_ID_FILTER="${STREAM_ID_FILTER:-}"
CASE_ID_FILTER="${CASE_ID_FILTER:-}"

if command -v psql >/dev/null 2>&1; then
  PSQL_BIN="$(command -v psql)"
elif [[ -x /opt/homebrew/opt/libpq/bin/psql ]]; then
  PSQL_BIN="/opt/homebrew/opt/libpq/bin/psql"
else
  echo "psql not found. Install libpq/PostgreSQL client first."
  exit 1
fi

echo "[backfill_v2_search_projection] DATABASE_URL=$DATABASE_URL"
echo "[backfill_v2_search_projection] STREAM_ID_FILTER=${STREAM_ID_FILTER:-<none>}"
echo "[backfill_v2_search_projection] CASE_ID_FILTER=${CASE_ID_FILTER:-<none>}"

"$PSQL_BIN" "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -v stream_filter="$STREAM_ID_FILTER" \
  -v case_filter="$CASE_ID_FILTER" <<'SQL'
WITH source_events AS (
  SELECT
    cel.event_id,
    cel.case_id,
    cel.event_seq,
    cc.stream_id,
    COALESCE(cel.payload->>'text', cel.payload->>'event_text') AS content,
    cel.payload AS metadata
  FROM case_event_ledger cel
  LEFT JOIN case_context cc
    ON cc.case_id = cel.case_id
  WHERE COALESCE(cel.payload->>'text', cel.payload->>'event_text') IS NOT NULL
    AND (NULLIF(:'stream_filter', '') IS NULL OR cc.stream_id = NULLIF(:'stream_filter', ''))
    AND (NULLIF(:'case_filter', '') IS NULL OR cel.case_id::text = NULLIF(:'case_filter', ''))
)
INSERT INTO search_document (
  case_id,
  stream_id,
  event_id,
  event_seq,
  content,
  metadata,
  created_at,
  updated_at
)
SELECT
  se.case_id,
  se.stream_id,
  se.event_id,
  se.event_seq,
  se.content,
  se.metadata,
  NOW(),
  NOW()
FROM source_events se
ON CONFLICT (event_id) DO UPDATE SET
  stream_id = EXCLUDED.stream_id,
  event_seq = EXCLUDED.event_seq,
  content = EXCLUDED.content,
  metadata = EXCLUDED.metadata,
  updated_at = NOW();
SQL

echo "[backfill_v2_search_projection] projection backfill complete"

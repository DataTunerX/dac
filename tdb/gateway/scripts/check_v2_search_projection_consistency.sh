#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgres://tdb:tdb@localhost:5432/DataV2}"
STREAM_ID_FILTER="${STREAM_ID_FILTER:-}"
CASE_ID_FILTER="${CASE_ID_FILTER:-}"
STRICT="${STRICT:-0}"

if command -v psql >/dev/null 2>&1; then
  PSQL_BIN="$(command -v psql)"
elif [[ -x /opt/homebrew/opt/libpq/bin/psql ]]; then
  PSQL_BIN="/opt/homebrew/opt/libpq/bin/psql"
else
  echo "psql not found. Install libpq/PostgreSQL client first."
  exit 1
fi

echo "[check_v2_search_projection_consistency] DATABASE_URL=$DATABASE_URL"

missing_projection="$("$PSQL_BIN" "$DATABASE_URL" -At -v ON_ERROR_STOP=1 \
  -v stream_filter="$STREAM_ID_FILTER" \
  -v case_filter="$CASE_ID_FILTER" -c "
WITH source_events AS (
  SELECT cel.event_id
  FROM case_event_ledger cel
  LEFT JOIN case_context cc ON cc.case_id = cel.case_id
  WHERE COALESCE(cel.payload->>'text', cel.payload->>'event_text') IS NOT NULL
    AND (NULLIF(:'stream_filter', '') IS NULL OR cc.stream_id = NULLIF(:'stream_filter', ''))
    AND (NULLIF(:'case_filter', '') IS NULL OR cel.case_id::text = NULLIF(:'case_filter', ''))
)
SELECT COUNT(*)
FROM source_events se
LEFT JOIN search_document sd ON sd.event_id = se.event_id
WHERE sd.event_id IS NULL;
")"

orphan_projection="$("$PSQL_BIN" "$DATABASE_URL" -At -v ON_ERROR_STOP=1 \
  -v stream_filter="$STREAM_ID_FILTER" \
  -v case_filter="$CASE_ID_FILTER" -c "
SELECT COUNT(*)
FROM search_document sd
LEFT JOIN case_event_ledger cel ON cel.event_id = sd.event_id
LEFT JOIN case_context cc ON cc.case_id = sd.case_id
WHERE cel.event_id IS NULL
  AND (NULLIF(:'stream_filter', '') IS NULL OR cc.stream_id = NULLIF(:'stream_filter', ''))
  AND (NULLIF(:'case_filter', '') IS NULL OR sd.case_id::text = NULLIF(:'case_filter', ''));
")"

bad_content="$("$PSQL_BIN" "$DATABASE_URL" -At -v ON_ERROR_STOP=1 \
  -v stream_filter="$STREAM_ID_FILTER" \
  -v case_filter="$CASE_ID_FILTER" -c "
SELECT COUNT(*)
FROM search_document sd
JOIN case_event_ledger cel ON cel.event_id = sd.event_id
LEFT JOIN case_context cc ON cc.case_id = cel.case_id
WHERE sd.content <> COALESCE(cel.payload->>'text', cel.payload->>'event_text')
  AND (NULLIF(:'stream_filter', '') IS NULL OR cc.stream_id = NULLIF(:'stream_filter', ''))
  AND (NULLIF(:'case_filter', '') IS NULL OR cel.case_id::text = NULLIF(:'case_filter', ''));
")"

echo "V2 search projection consistency:"
echo "  missing_projection: ${missing_projection}"
echo "  orphan_projection: ${orphan_projection}"
echo "  bad_content: ${bad_content}"

if [[ "$orphan_projection" -gt 0 || "$bad_content" -gt 0 ]]; then
  echo "Consistency check failed."
  exit 1
fi

if [[ "$STRICT" == "1" && "$missing_projection" -gt 0 ]]; then
  echo "Consistency check failed: missing_projection in strict mode."
  exit 1
fi

echo "Consistency check passed."

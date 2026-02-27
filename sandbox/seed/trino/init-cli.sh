#!/bin/sh
set -eu

TRINO_SERVER="http://trino:8080"

echo "[trino-init] waiting for Trino to accept queries..."
for i in $(seq 1 240); do
  if trino --server "$TRINO_SERVER" --user sandbox --execute "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[trino-init] running /seed/init.sql"
trino --server "$TRINO_SERVER" --user sandbox --catalog hive -f /seed/init.sql
echo "[trino-init] done"


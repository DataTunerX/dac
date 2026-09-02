#!/usr/bin/env bash
set -euo pipefail

if [[ -f /app/.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source /app/.env
  set +a
fi

export DATABASE_URL="${DATABASE_URL:-postgres://tdb:tdb@localhost:5432/DataV2}"
export TDB_GATEWAY_BACKEND_ADDR="${TDB_GATEWAY_BACKEND_ADDR:-127.0.0.1:50051}"
export TDB_GATEWAY_PORT="${TDB_GATEWAY_PORT:-8080}"
export TDB_GATEWAY_HOST="${TDB_GATEWAY_HOST:-0.0.0.0}"
export TDB_GATEWAY_NODE_ENV="${TDB_GATEWAY_NODE_ENV:-production}"
export NODE_ENV="${NODE_ENV:-production}"
export RUST_BACKTRACE="${RUST_BACKTRACE:-1}"

if [[ "${TDB_DOCKER_REWRITE_LOCALHOST_DATABASE_URL:-true}" == "true" ]]; then
  export DATABASE_URL="${DATABASE_URL//@localhost:/@${TDB_DOCKER_HOST_GATEWAY:-host.docker.internal}:}"
  export DATABASE_URL="${DATABASE_URL//@127.0.0.1:/@${TDB_DOCKER_HOST_GATEWAY:-host.docker.internal}:}"
fi

backend_pid=""
gateway_pid=""

shutdown() {
  if [[ -n "$gateway_pid" ]] && kill -0 "$gateway_pid" 2>/dev/null; then
    kill "$gateway_pid" 2>/dev/null || true
  fi
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap shutdown SIGINT SIGTERM EXIT

echo "Starting tdb_gateway_backend on ${TDB_GATEWAY_BACKEND_ADDR}"
echo "Using configured PostgreSQL database"
tdb_gateway_backend &
backend_pid="$!"

echo "Starting tdb-gateway on ${TDB_GATEWAY_HOST}:${TDB_GATEWAY_PORT}"
cd /app/gateway
node dist/src/index.js &
gateway_pid="$!"

while true; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    echo "tdb_gateway_backend exited"
    wait "$backend_pid"
    exit $?
  fi
  if ! kill -0 "$gateway_pid" 2>/dev/null; then
    echo "tdb-gateway exited"
    wait "$gateway_pid"
    exit $?
  fi
  sleep 2
done

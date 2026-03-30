#!/bin/sh
set -eu

log() {
  printf '[entrypoint] %s\n' "$*"
}

shutdown() {
  log "received termination signal, shutting down"

  if [ -n "${nginx_pid:-}" ] && kill -0 "$nginx_pid" 2>/dev/null; then
    kill "$nginx_pid" 2>/dev/null || true
  fi

  if [ -n "${node_pid:-}" ] && kill -0 "$node_pid" 2>/dev/null; then
    kill "$node_pid" 2>/dev/null || true
  fi

  wait "${nginx_pid:-}" 2>/dev/null || true
  wait "${node_pid:-}" 2>/dev/null || true
}

if [ -z "${BACKEND_URL:-}" ]; then
  log "ERROR: BACKEND_URL is not set"
  log "Hint: set BACKEND_URL like: http://dac-apiserver:80"
  exit 1
fi

BACKEND_UPSTREAM="$(printf '%s' "$BACKEND_URL" | sed 's:/*$::')"
if [ -z "$BACKEND_UPSTREAM" ]; then
  log "ERROR: normalized BACKEND_URL is empty"
  exit 1
fi
export BACKEND_UPSTREAM

# Render nginx config from template using runtime env.
out_dir="/etc/nginx/http.d"
if [ ! -d "$out_dir" ]; then
  out_dir="/etc/nginx/conf.d"
fi
mkdir -p "$out_dir"
envsubst '${BACKEND_UPSTREAM}' < /etc/nginx/templates/default.conf.template > "$out_dir/default.conf"

# Next.js listens internally; nginx is the public listener.
export PORT=3001
export HOSTNAME=127.0.0.1

log "validating nginx configuration"
nginx -t

trap shutdown INT TERM

log "starting Next.js on ${HOSTNAME}:${PORT}"
node /app/server.js &
node_pid=$!

log "starting nginx on 0.0.0.0:3000"
nginx -g 'daemon off;' &
nginx_pid=$!

while :; do
  if ! kill -0 "$node_pid" 2>/dev/null; then
    log "Next.js exited unexpectedly"
    kill "$nginx_pid" 2>/dev/null || true
    wait "$nginx_pid" 2>/dev/null || true
    wait "$node_pid" 2>/dev/null || true
    exit 1
  fi

  if ! kill -0 "$nginx_pid" 2>/dev/null; then
    log "nginx exited unexpectedly"
    wait "$nginx_pid" 2>/dev/null || true
    wait "$node_pid" 2>/dev/null || true
    exit 1
  fi

  sleep 1
done


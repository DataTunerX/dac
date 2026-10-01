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

wait_for_backend() {
  wait_timeout="${BACKEND_WAIT_TIMEOUT_SECONDS:-120}"
  wait_interval="${BACKEND_WAIT_INTERVAL_SECONDS:-2}"

  case "$wait_timeout" in
    ''|*[!0-9]*)
      log "ERROR: BACKEND_WAIT_TIMEOUT_SECONDS must be a non-negative integer"
      exit 1
      ;;
  esac
  case "$wait_interval" in
    ''|*[!0-9]*|0)
      log "ERROR: BACKEND_WAIT_INTERVAL_SECONDS must be a positive integer"
      exit 1
      ;;
  esac

  if ! backend_target="$(node -e '
    const target = new URL(process.env.BACKEND_UPSTREAM);
    if (target.protocol !== "http:" && target.protocol !== "https:") {
      throw new Error(`unsupported protocol: ${target.protocol}`);
    }
    const port = target.port || (target.protocol === "https:" ? "443" : "80");
    process.stdout.write(`${target.hostname}\n${port}\n`);
  ')"; then
    log "ERROR: BACKEND_URL is not a valid HTTP(S) URL: ${BACKEND_URL}"
    exit 1
  fi

  backend_host="$(printf '%s\n' "$backend_target" | sed -n '1p')"
  backend_port="$(printf '%s\n' "$backend_target" | sed -n '2p')"
  waited=0

  log "waiting for backend at ${backend_host}:${backend_port}"
  while ! nc -z -w 1 "$backend_host" "$backend_port" >/dev/null 2>&1; do
    if [ "$waited" -ge "$wait_timeout" ]; then
      log "ERROR: backend did not become reachable within ${wait_timeout}s"
      exit 1
    fi
    sleep "$wait_interval"
    waited=$((waited + wait_interval))
  done
  log "backend is reachable"
}

wait_for_backend

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
    kill "$node_pid" 2>/dev/null || true
    wait "$nginx_pid" 2>/dev/null || true
    wait "$node_pid" 2>/dev/null || true
    exit 1
  fi

  sleep 1
done

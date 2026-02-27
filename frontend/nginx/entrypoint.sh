#!/bin/sh
set -eu

if [ -z "${BACKEND_URL:-}" ]; then
  echo "[entrypoint] ERROR: BACKEND_URL is not set"
  echo "[entrypoint] Hint: set BACKEND_URL like: http://dac-apiserver:80"
  exit 1
fi

# Render nginx config from template using runtime env
out_dir="/etc/nginx/http.d"
if [ ! -d "$out_dir" ]; then
  out_dir="/etc/nginx/conf.d"
fi
mkdir -p "$out_dir"
envsubst '${BACKEND_URL}' < /etc/nginx/templates/default.conf.template > "$out_dir/default.conf"

# Start Next.js standalone server on an internal port, nginx is the external listener (3000)
export PORT=3001
export HOSTNAME=127.0.0.1

node /app/server.js &
# Run nginx without writing PID to /var/run (non-root friendly)
exec nginx -g 'pid /tmp/nginx.pid; daemon off;'


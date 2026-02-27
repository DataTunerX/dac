#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

docker compose --env-file env.example up -d --build

echo "[sandbox] started. Use ./bin/verify.sh to validate."


#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
docker compose --env-file env.example down -v


#!/usr/bin/env bash
# 有网构建机执行一次：vendor SQL → mirror 外部镜像 → build/push sandbox 镜像
# 离线集群只需: make apply && make verify
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REGISTRY="${REGISTRY:-release.daocloud.io/dac}"
TAG="${TAG:-v0.11.0}"
PLATFORM="${PLATFORM:-linux/amd64}"

export REGISTRY TAG PLATFORM

log() { printf '\033[36m[offline-prep] %s\033[0m\n' "$*"; }

log "Step 1/3: vendor SQL + datasets"
make vendor

log "Step 2/3: mirror external images -> ${REGISTRY}"
bash scripts/mirror-images.sh

log "Step 3/3: build + push sandbox images"
make build push

printf '\n\033[32m[offline-prep] COMPLETE\033[0m\n'
echo "Offline cluster:"
echo "  cd sandbox && make apply && make verify && make scan-targets"
echo "Registry: ${REGISTRY}  Tag: ${TAG}"

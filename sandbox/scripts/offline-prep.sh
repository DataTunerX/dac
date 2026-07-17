#!/usr/bin/env bash
# 离线演示一站式准备（在有网构建机执行一次）:
#   1. vendor      — 下载全部 SQL / dump / MovieLens / manifest 到 seed/ 与缓存
#   2. mirror      — 外部镜像同步到私有 registry
#   3. build+push  — 将 vendor SQL 打入 sandbox-mysql/postgres 等镜像并推送
#
# 离线集群只需: make apply apply-apps（不再访问外网）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REGISTRY="${REGISTRY:-release.daocloud.io/dac}"
TAG="${TAG:-v0.11.0}"
PLATFORM="${PLATFORM:-linux/amd64}"

export REGISTRY TAG PLATFORM

log() { printf '\033[36m[offline-prep] %s\033[0m\n' "$*"; }

log "Step 1/3: vendor SQL + datasets + boutique manifest"
make vendor
REGISTRY="$REGISTRY" make vendor-apps

log "Step 2/3: mirror external images -> ${REGISTRY}"
bash scripts/mirror-images.sh

log "Step 3/3: build + push sandbox images (SQL baked into mysql/postgres)"
make build push

printf '\n\033[32m[offline-prep] COMPLETE\033[0m\n'
echo "离线集群部署（集群内无需外网）:"
echo "  cd sandbox && make apply-all && make verify"
echo "  Odoo:  kubectl -n dac-sandbox logs deploy/odoo -c init-demo -f   # 等 init 完成"
echo "  Saleor: kubectl -n dac-sandbox get job saleor-populatedb            # 等 1/1"
echo "镜像仓库: ${REGISTRY}"
echo "标签: ${TAG}"

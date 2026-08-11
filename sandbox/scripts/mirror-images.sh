#!/usr/bin/env bash
# 将 sandbox 依赖的全部外部镜像 pull → tag → push 到私有 registry，供离线集群使用。
# 用法（有网构建机）:
#   docker login release.daocloud.io
#   REGISTRY=release.daocloud.io/dac PLATFORM=linux/amd64 bash scripts/mirror-images.sh
set -euo pipefail

REGISTRY="${REGISTRY:-release.daocloud.io/dac}"
PLATFORM="${PLATFORM:-linux/amd64}"
BOUTIQUE_TAG="${BOUTIQUE_TAG:-v0.10.5}"
SALEOR_TAG="${SALEOR_TAG:-3.23}"

log() { printf '\033[36m[mirror] %s\033[0m\n' "$*"; }
ok()  { printf '\033[32m[mirror] %s\033[0m\n' "$*"; }

mirror_one() {
  local src="$1" dst="$2"
  log "$src  ->  $dst"
  docker pull --platform "$PLATFORM" "$src"
  docker tag "$src" "$dst"
  docker push "$dst"
}

# ---------- Docker Hub（与 k8s 中 release.daocloud.io/dac/<short> 对齐）----------
DOCKERHUB_IMAGES=(
  "docker.io/library/mysql:8.0|${REGISTRY}/mysql:8.0"
  "docker.io/library/postgres:16|${REGISTRY}/postgres:16"
  "docker.io/library/nginx:1.27-alpine|${REGISTRY}/nginx:1.27-alpine"
  "docker.io/library/alpine:3.20|${REGISTRY}/alpine:3.20"
  "docker.io/minio/mc:latest|${REGISTRY}/mc:latest"
  "docker.io/minio/minio:latest|${REGISTRY}/minio:latest"
  "docker.io/gitlab/gitlab-ce:17.5.0-ce.0|${REGISTRY}/gitlab-ce:17.5.0-ce.0"
  "docker.io/odoo:17.0|${REGISTRY}/odoo:17.0"
  "docker.io/valkey/valkey:8.1-alpine|${REGISTRY}/valkey:8.1-alpine"
  "docker.io/library/redis:alpine|${REGISTRY}/redis:alpine"
)

log "=== Docker Hub (${#DOCKERHUB_IMAGES[@]} images) ==="
for pair in "${DOCKERHUB_IMAGES[@]}"; do
  src="${pair%%|*}"
  dst="${pair##*|}"
  mirror_one "$src" "$dst"
done

# ---------- GHCR: Saleor ----------
log "=== GHCR: Saleor ==="
mirror_one "ghcr.io/saleor/saleor:${SALEOR_TAG}" "${REGISTRY}/saleor:${SALEOR_TAG}"
mirror_one "ghcr.io/saleor/saleor-dashboard:${SALEOR_TAG}" "${REGISTRY}/saleor-dashboard:${SALEOR_TAG}"

# ---------- Google Artifact Registry: Online Boutique ----------
BOUTIQUE_SERVICES=(
  currencyservice
  productcatalogservice
  checkoutservice
  shippingservice
  cartservice
  emailservice
  paymentservice
  frontend
  recommendationservice
  adservice
)

log "=== Online Boutique (${#BOUTIQUE_SERVICES[@]} services @ ${BOUTIQUE_TAG}) ==="
for svc in "${BOUTIQUE_SERVICES[@]}"; do
  src="us-central1-docker.pkg.dev/google-samples/microservices-demo/${svc}:${BOUTIQUE_TAG}"
  dst="${REGISTRY}/boutique-${svc}:${BOUTIQUE_TAG}"
  mirror_one "$src" "$dst"
done

ok "DONE — all sandbox external images synced to ${REGISTRY}"

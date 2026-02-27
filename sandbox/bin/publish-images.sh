#!/usr/bin/env bash
set -euo pipefail

# Publish sandbox images into a private registry namespace.
#
# Requirements:
# - docker installed
# - you are logged in: `docker login release.daocloud.io`
#
# Usage:
#   REGISTRY_NS=release.daocloud.io/dac \
#   LOCAL_REPO_PATH=/absolute/path/to/zeysi-apiserver \
#   bash sandbox/bin/publish-images.sh
#
# Notes:
# - Pulls source images from Docker Hub (docker.io) directly (no prefix).
# - Tags and pushes them to ${REGISTRY_NS}.
# - Builds & pushes the seeded Gitea image which bakes LOCAL_REPO_PATH into the image.

REGISTRY_NS="${REGISTRY_NS:-release.daocloud.io/dac}"
LOCAL_REPO_PATH="${LOCAL_REPO_PATH:-}"

if [[ -z "${LOCAL_REPO_PATH}" ]]; then
  echo "ERROR: LOCAL_REPO_PATH is required (path to your local git repo)."
  echo "Example: LOCAL_REPO_PATH=~/go/src/zeysi-apiserver"
  exit 1
fi

if [[ ! -d "${LOCAL_REPO_PATH}/.git" ]]; then
  echo "ERROR: LOCAL_REPO_PATH is not a git repo: ${LOCAL_REPO_PATH}"
  exit 1
fi

echo "[publish] target registry namespace: ${REGISTRY_NS}"

function pull_tag_push() {
  local src="$1"
  local dst="$2"
  echo "[publish] pull ${src}"
  docker pull "${src}"
  echo "[publish] tag ${src} -> ${dst}"
  docker tag "${src}" "${dst}"
  echo "[publish] push ${dst}"
  docker push "${dst}"
}

# Core services
pull_tag_push "postgres:16" "${REGISTRY_NS}/postgres:16"
pull_tag_push "mariadb:11" "${REGISTRY_NS}/mariadb:11"
pull_tag_push "minio/minio:latest" "${REGISTRY_NS}/minio:latest"
pull_tag_push "minio/mc:latest" "${REGISTRY_NS}/minio-mc:latest"
pull_tag_push "trinodb/trino:latest" "${REGISTRY_NS}/trino:latest"
pull_tag_push "starburstdata/hive:3.1.2-e.15" "${REGISTRY_NS}/starburst-hive:3.1.2-e.15"
pull_tag_push "nextcloud:29-apache" "${REGISTRY_NS}/nextcloud:29-apache"
pull_tag_push "odoo:17" "${REGISTRY_NS}/odoo:17"
pull_tag_push "gitea/gitea:1.21.11" "${REGISTRY_NS}/gitea:1.21.11"

echo "[publish] build & push seeded gitea image (bake LOCAL_REPO_PATH into /seed/src)"
docker build \
  -t "${REGISTRY_NS}/sandbox-gitea:seed" \
  -f "sandbox/apps/gitea/Dockerfile" \
  "${LOCAL_REPO_PATH}"

docker push "${REGISTRY_NS}/sandbox-gitea:seed"

echo "[publish] done"


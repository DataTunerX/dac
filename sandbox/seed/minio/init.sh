#!/bin/sh
set -eu

echo "[minio-init] waiting for minio..."
for i in $(seq 1 60); do
  if mc alias set minio http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

mc alias set minio http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

echo "[minio-init] ensure buckets..."
mc mb -p minio/objects || true
mc mb -p minio/lake || true

echo "[minio-init] upload seeded objects..."
mc cp --recursive /seed/objects/ minio/objects/ || true
mc cp --recursive /seed/lake/ minio/lake/ || true

echo "[minio-init] done"


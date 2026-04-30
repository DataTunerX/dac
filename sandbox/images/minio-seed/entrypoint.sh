#!/bin/sh
# 等 MinIO 起来 → 配 alias → 建 bucket → 灌入种子文件
# 通过环境变量配置:
#   MINIO_ENDPOINT (默认 http://localhost:9000)
#   MINIO_ROOT_USER / MINIO_ROOT_PASSWORD (默认 dac/dacpassword；MinIO 强制要求 secret >= 8 字符)

set -eu

ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
USER="${MINIO_ROOT_USER:-dac}"
PASS="${MINIO_ROOT_PASSWORD:-dacpassword}"

echo "[minio-seed] target: $ENDPOINT"

# 等 MinIO 就绪 (最多 60s)
i=0
until mc alias set local "$ENDPOINT" "$USER" "$PASS" >/dev/null 2>&1; do
  i=$((i+1))
  if [ "$i" -gt 60 ]; then
    echo "[minio-seed] FATAL: MinIO not ready after 60s"
    exit 1
  fi
  echo "[minio-seed] waiting for MinIO... ($i)"
  sleep 1
done
echo "[minio-seed] MinIO ready"

# 建 bucket (幂等)
mc mb --ignore-existing local/dac-files
mc mb --ignore-existing local/dac-datasets

# 灌入文件
if [ -d /seed/files ] && [ -n "$(ls -A /seed/files 2>/dev/null)" ]; then
  echo "[minio-seed] uploading /seed/files → s3://dac-files/"
  mc cp --recursive /seed/files/ local/dac-files/
fi

if [ -d /seed/datasets ] && [ -n "$(ls -A /seed/datasets 2>/dev/null)" ]; then
  echo "[minio-seed] uploading /seed/datasets → s3://dac-datasets/"
  mc cp --recursive /seed/datasets/ local/dac-datasets/
fi

echo "[minio-seed] inventory:"
mc ls --recursive local/dac-files     | head -50
mc ls --recursive local/dac-datasets  | head -50

echo "[minio-seed] DONE"

#!/bin/sh
# 等 MinIO 起来 → 配 alias → 建 bucket → 灌入种子文件
# 通过环境变量配置:
#   MINIO_ENDPOINT (默认 http://localhost:9000)
#   MINIO_ROOT_USER / MINIO_ROOT_PASSWORD (默认 dac/dacpassword；MinIO 强制要求 secret >= 8 字符)
#   MINIO_WAIT_SECONDS (默认 300)

set -eu

ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
USER="${MINIO_ROOT_USER:-dac}"
PASS="${MINIO_ROOT_PASSWORD:-dacpassword}"
WAIT_SECONDS="${MINIO_WAIT_SECONDS:-300}"

echo "[minio-seed] target: $ENDPOINT (wait up to ${WAIT_SECONDS}s)"

# 等 MinIO 就绪（STS 可能因 GitLab 未 Ready 导致 ClusterIP 短暂无端点）
i=0
until mc alias set local "$ENDPOINT" "$USER" "$PASS" >/tmp/mc-alias.err 2>&1; do
  i=$((i+1))
  if [ "$i" -gt "$WAIT_SECONDS" ]; then
    echo "[minio-seed] FATAL: MinIO not ready after ${WAIT_SECONDS}s"
    echo "[minio-seed] last mc error:"
    cat /tmp/mc-alias.err || true
    exit 1
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "[minio-seed] waiting for MinIO... ($i/${WAIT_SECONDS})"
    cat /tmp/mc-alias.err || true
  else
    echo "[minio-seed] waiting for MinIO... ($i)"
  fi
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

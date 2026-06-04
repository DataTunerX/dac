# DAC sandbox MinIO seeder — 一次性 Job 镜像
# 等 MinIO 起来后，把 seed/files 灌入 bucket dac-files，
# 把 seed/datasets 灌入 bucket dac-datasets。
#
# 构建上下文必须是 sandbox/ 根目录:
#   docker build -t release.daocloud.io/dac/sandbox-minio-seed:v0.10.0 -f images/minio-seed/Dockerfile .

FROM minio/mc:latest

# mc 镜像基于 distroless，没法 apt，所以直接 COPY 进去
COPY seed/files     /seed/files
COPY seed/datasets  /seed/datasets
COPY images/minio-seed/entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

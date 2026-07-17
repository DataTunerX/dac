# DAC sandbox PostgreSQL — 启动即包含演示用 database
#   手工库: dac_sandbox / relationship
#   开源库: pagila / chinook / northwind
#
# 构建上下文必须是 sandbox/ 根目录:
#   docker build -t release.daocloud.io/dac/sandbox-postgres:v0.11.0 -f images/postgres/Dockerfile .
#
# 运行:
#   docker run -d -p 5432:5432 release.daocloud.io/dac/sandbox-postgres:v0.11.0

FROM release.daocloud.io/dac/postgres:16

# 默认账号 + 默认 db (entrypoint 会自动建; postgres/dacpass，业务账号 dac/dacpass 在 00-create-databases.sql)
ENV POSTGRES_PASSWORD=dacpass \
    POSTGRES_DB=dac_sandbox

# 把全部 SQL 灌进 entrypoint 自动执行目录，按文件名字典序运行
COPY seed/postgres/*.sql /docker-entrypoint-initdb.d/

EXPOSE 5432
HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=20 \
  CMD pg_isready -U postgres -h 127.0.0.1 || exit 1

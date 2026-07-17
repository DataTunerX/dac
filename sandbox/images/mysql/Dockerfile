# DAC sandbox MySQL — 启动即包含演示用 database
#   手工库: dac_sandbox / dactest / test1 / corporate_hr / online_edu_bi_test
#   开源库: sakila / northwind / classicmodels / chinook / employees / world
#
# 构建上下文必须是 sandbox/ 根目录:
#   docker build -t release.daocloud.io/dac/sandbox-mysql:v0.11.0 -f images/mysql/Dockerfile .

FROM release.daocloud.io/dac/mysql:8.0

ENV MYSQL_ROOT_PASSWORD=dacpass \
    MYSQL_DATABASE=dac_sandbox

COPY seed/mysql/*.sql /docker-entrypoint-initdb.d/
COPY seed/mysql/*.sh /docker-entrypoint-initdb.d/
COPY seed/mysql/employees-dumps/ /docker-entrypoint-initdb.d/employees-dumps/

EXPOSE 3306
HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=20 \
  CMD mysqladmin ping -h 127.0.0.1 -uroot -p"${MYSQL_ROOT_PASSWORD}" || exit 1

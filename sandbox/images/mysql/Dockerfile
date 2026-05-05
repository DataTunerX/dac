# DAC sandbox MySQL — 启动即包含演示用 6 个 database
#   dac_sandbox / dactest / test1 / corporate_hr / online_edu_bi_test / sakila
#
# 构建上下文必须是 sandbox/ 根目录:
#   docker build -t release.daocloud.io/dac/sandbox-mysql:v0.10.0 -f images/mysql/Dockerfile .
#
# 运行:
#   docker run -d -p 3306:3306 release.daocloud.io/dac/sandbox-mysql:v0.10.0

FROM release.daocloud.io/dac/mysql:8.0

# 默认账号: root/dacpass (超级用户), dac/dacpass (业务账号在 00-create-databases.sql 里创建)
# sandbox 内所有服务统一使用 dacpass 作为业务密码，方便记忆
ENV MYSQL_ROOT_PASSWORD=dacpass \
    MYSQL_DATABASE=dac_sandbox

# 把全部 SQL 灌进 entrypoint 自动执行目录，按文件名字典序运行
COPY seed/mysql/*.sql /docker-entrypoint-initdb.d/

EXPOSE 3306
HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=20 \
  CMD mysqladmin ping -h 127.0.0.1 -uroot -p"${MYSQL_ROOT_PASSWORD}" || exit 1

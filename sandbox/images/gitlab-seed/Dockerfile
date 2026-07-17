# DAC sandbox gitlab seeder — 一次性 Job 镜像
# 等 GitLab ready 后，把 /seed/code/ 下所有仓库依次 push 到 root/<project>
#   - test-code  (原有 DAC 演示代码)
#   - saleor     (开源电商后端，企业业务代码样本)
#
# 构建上下文必须是 sandbox/ 根目录:
#   docker build -t release.daocloud.io/dac/sandbox-gitlab-seed:v0.11.0 -f images/gitlab-seed/Dockerfile .

FROM release.daocloud.io/dac/alpine:3.20

RUN apk add --no-cache git curl jq bash ca-certificates

ARG TEST_CODE_REPO_URL=https://gitee.com/jamesxiong888/test-code.git
ARG TEST_CODE_REPO_REF=master
ARG SALEOR_REPO_URL=https://github.com/saleor/saleor.git
ARG SALEOR_REPO_REF=main

RUN git clone --depth 1 --branch "$TEST_CODE_REPO_REF" "$TEST_CODE_REPO_URL" /seed/code/test-code \
    || git clone --depth 1 "$TEST_CODE_REPO_URL" /seed/code/test-code

RUN git clone --depth 1 --branch "$SALEOR_REPO_REF" "$SALEOR_REPO_URL" /seed/code/saleor \
    || git clone --depth 1 "$SALEOR_REPO_URL" /seed/code/saleor

COPY images/gitlab-seed/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

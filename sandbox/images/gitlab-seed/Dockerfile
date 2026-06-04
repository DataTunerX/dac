# DAC sandbox gitlab seeder — 一次性 Job 镜像
# 等 GitLab ready 后:
#   1. 用 root + GITLAB_ROOT_PASSWORD 走 OAuth password grant (ROPC) 拿 access token
#   2. 在 root 命名空间下创建 project: test-code
#   3. 把镜像里 /seed/code/test-code 推到该 project (作为 DAC code descriptor 演示语料)
#
# 种子内容来源：构建期从 https://gitee.com/jamesxiong888/test-code.git clone，
# 这样运行时无需访问公网，并且镜像内容确定可复现。
#
# 构建上下文必须是 sandbox/ 根目录:
#   docker build -t release.daocloud.io/dac/sandbox-gitlab-seed:v0.10.0 -f images/gitlab-seed/Dockerfile .

FROM alpine:3.20

RUN apk add --no-cache git curl jq bash ca-certificates

# 构建期把外部示例仓库克隆到镜像里 (--depth 1 减小体积；保留 .git 由 entrypoint 处理)
ARG SEED_REPO_URL=https://gitee.com/jamesxiong888/test-code.git
ARG SEED_REPO_REF=master
RUN git clone --depth 1 --branch "$SEED_REPO_REF" "$SEED_REPO_URL" /seed/code/test-code \
    || git clone --depth 1 "$SEED_REPO_URL" /seed/code/test-code

COPY images/gitlab-seed/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

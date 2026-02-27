uv:python3.13-alpine


# amd64

docker pull --platform linux/amd64 ghcr.io/astral-sh/uv:python3.13-alpine

docker tag ghcr.io/astral-sh/uv:python3.13-alpine registry.cn-shanghai.aliyuncs.com/jamesxiong/uv:python3.13-alpine-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/uv:python3.13-alpine-amd64



# arm64

docker pull --platform linux/arm64 ghcr.io/astral-sh/uv:python3.13-alpine

docker tag ghcr.io/astral-sh/uv:python3.13-alpine registry.cn-shanghai.aliyuncs.com/jamesxiong/uv:python3.13-alpine-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/uv:python3.13-alpine-arm64

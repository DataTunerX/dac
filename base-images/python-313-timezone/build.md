
# amd64-alpine:

docker buildx build --platform linux/amd64 -t python:3.13-alpine-timezone-amd64 -f Dockerfile-amd64 .

docker tag python:3.13-alpine-timezone-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-alpine-timezone-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-alpine-timezone-amd64


# amd64-debian:

docker buildx build --platform linux/amd64 -t python:3.13-ubuntu-timezone-amd64 -f Dockerfile-amd64-debian .

docker tag python:3.13-ubuntu-timezone-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-ubuntu-timezone-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-ubuntu-timezone-amd64


# arm64-alpine:

docker buildx build --platform linux/arm64 -t python:3.13-alpine-timezone-arm64 -f Dockerfile-arm64 .

docker tag python:3.13-alpine-timezone-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-alpine-timezone-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-alpine-timezone-arm64

# arm64-debian:

docker buildx build --platform linux/arm64 -t python:3.13-ubuntu-timezone-arm64 -f Dockerfile-arm64-debian .

docker tag python:3.13-ubuntu-timezone-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-ubuntu-timezone-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/python:3.13-ubuntu-timezone-arm64

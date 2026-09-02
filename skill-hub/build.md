# build skill-hub

amd64:

docker buildx build --platform linux/amd64 -t skill-hub:v0.12.0-amd64 -f Dockerfile-amd64 .

docker tag skill-hub:v0.12.0-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-hub:v0.12.0-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-hub:v0.12.0-amd64


arm64:

docker buildx build --platform linux/arm64 -t skill-hub:v0.12.0-arm64 -f Dockerfile-arm64 .

docker tag skill-hub:v0.12.0-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-hub:v0.12.0-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-hub:v0.12.0-arm64





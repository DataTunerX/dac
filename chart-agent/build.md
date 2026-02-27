
# build chart-agent

amd64:

docker buildx build --platform linux/amd64 -t chart-agent:v0.7.0-amd64 -f Dockerfile-amd64 .

docker tag chart-agent:v0.7.0-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/chart-agent:v0.7.0-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/chart-agent:v0.7.0-amd64


arm64:

docker buildx build --platform linux/arm64 -t chart-agent:v0.7.0-arm64 -f Dockerfile-arm64 .

docker tag chart-agent:v0.7.0-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/chart-agent:v0.7.0-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/chart-agent:v0.7.0-arm64

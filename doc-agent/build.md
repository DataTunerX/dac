
# build doc-agent

amd64:

docker buildx build --platform linux/amd64 -t doc-agent:v0.12.0-amd64 -f Dockerfile-amd64 .

docker tag doc-agent:v0.12.0-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/doc-agent:v0.12.0-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/doc-agent:v0.12.0-amd64


arm64:

docker buildx build --platform linux/arm64 -t doc-agent:v0.12.0-arm64 -f Dockerfile-arm64 .

docker tag doc-agent:v0.12.0-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/doc-agent:v0.12.0-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/doc-agent:v0.12.0-arm64

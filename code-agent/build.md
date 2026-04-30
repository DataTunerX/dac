
# build code-agent

amd64:

docker buildx build --platform linux/amd64 -t code-agent:v0.10.0-amd64 -f Dockerfile-amd64 .

docker tag code-agent:v0.10.0-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/code-agent:v0.10.0-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/code-agent:v0.10.0-amd64


arm64:

docker buildx build --platform linux/arm64 -t code-agent:v0.10.0-arm64 -f Dockerfile-arm64 .

docker tag code-agent:v0.10.0-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/code-agent:v0.10.0-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/code-agent:v0.10.0-arm64

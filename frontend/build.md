
# build frontend

amd64 (build + push):

docker buildx build --platform linux/amd64 -t registry.cn-shanghai.aliyuncs.com/jamesxiong/frontend:v0.12.0-amd64 -f Dockerfile-amd64 --push .

arm64:

docker buildx build --platform linux/arm64 -t registry.cn-shanghai.aliyuncs.com/jamesxiong/frontend:v0.12.0-arm64 -f Dockerfile-arm64 --push .
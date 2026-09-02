# build data-sinkers

## job

amd64:

docker buildx build --platform linux/amd64 -t data-sinkers-job:v0.12.0-amd64 -f Dockerfile-job-amd64 .

docker tag data-sinkers-job:v0.12.0-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-job:v0.12.0-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-job:v0.12.0-amd64

arm64:

docker buildx build --platform linux/arm64 -t data-sinkers-job:v0.12.0-arm64 -f Dockerfile-job-arm64 .

docker tag data-sinkers-job:v0.12.0-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-job:v0.12.0-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-job:v0.12.0-arm64


## status

amd64:

docker buildx build --platform linux/amd64 -t data-sinkers-status:v0.12.0-amd64 -f Dockerfile-status-amd64 .

docker tag data-sinkers-status:v0.12.0-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-status:v0.12.0-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-status:v0.12.0-amd64

arm64:

docker buildx build --platform linux/arm64 -t data-sinkers-status:v0.12.0-arm64 -f Dockerfile-status-arm64 .

docker tag data-sinkers-status:v0.12.0-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-status:v0.12.0-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-status:v0.12.0-arm64



## observer

amd64:

docker buildx build --platform linux/amd64 -t data-sinkers-observer:v0.12.0-amd64 -f Dockerfile-observer-amd64 .

docker tag data-sinkers-observer:v0.12.0-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-observer:v0.12.0-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-observer:v0.12.0-amd64

arm64:

docker buildx build --platform linux/arm64 -t data-sinkers-observer:v0.12.0-arm64 -f Dockerfile-observer-arm64 .

docker tag data-sinkers-observer:v0.12.0-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-observer:v0.12.0-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-observer:v0.12.0-arm64



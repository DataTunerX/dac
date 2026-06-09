# build data-sinkers

## job

amd64:

docker buildx build --platform linux/amd64 -t data-sinkers-job:12-amd64 -f Dockerfile-job-amd64 .



arm64:

docker buildx build --platform linux/arm64 -t data-sinkers-job:12-arm64 -f Dockerfile-job-arm64 .




## status

amd64:

docker buildx build --platform linux/amd64 -t data-sinkers-status:12-amd64 -f Dockerfile-status-amd64 .



arm64:

docker buildx build --platform linux/arm64 -t data-sinkers-status:12-arm64 -f Dockerfile-status-arm64 .





## observer

amd64:

docker buildx build --platform linux/amd64 -t data-sinkers-observer:12-amd64 -f Dockerfile-observer-amd64 .



arm64:

docker buildx build --platform linux/arm64 -t data-sinkers-observer:12-arm64 -f Dockerfile-observer-arm64 .





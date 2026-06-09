# build dac-data-services

amd64:

docker buildx build --platform linux/amd64 -t dac-data-services:12-amd64 -f Dockerfile-amd64 .




arm64:

docker buildx build --platform linux/arm64 -t dac-data-services:12-arm64 -f Dockerfile-arm64 .







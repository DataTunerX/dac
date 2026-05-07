
# build frontend

amd64:

docker buildx build --platform linux/amd64 -t frontend:v0.11.0-amd64 -f Dockerfile-amd64 .



docker buildx build --platform linux/amd64 \
  -t release.daocloud.io/dac/frontend:v0.11.0 \
  -f Dockerfile-amd64 --push .

arm64:

docker buildx build --platform linux/arm64 -t frontend:v0.11.0-arm64 -f Dockerfile-arm64 .



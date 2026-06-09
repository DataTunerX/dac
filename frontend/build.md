
# build frontend

amd64:

docker buildx build --platform linux/amd64 -t frontend:12-amd64 -f Dockerfile-amd64 .



docker buildx build --platform linux/amd64 \
  -t release.daocloud.io/dac/frontend:12 \
  -f Dockerfile-amd64 --push .

arm64:

docker buildx build --platform linux/arm64 -t frontend:12-arm64 -f Dockerfile-arm64 .



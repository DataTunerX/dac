
# build frontend

amd64 (build + push):

docker buildx build --platform linux/amd64 \
  -t release.daocloud.io/dac/frontend:v0.11.0 \
  -f Dockerfile-amd64 --push .

arm64:

docker buildx build --platform linux/arm64 \
  -t release.daocloud.io/dac/frontend:v0.11.0-arm64 \
  -f Dockerfile-arm64 --push .

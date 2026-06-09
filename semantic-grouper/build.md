
# build semantic-grouper

amd64:

docker buildx build --platform linux/amd64 -t semantic-grouper:12-amd64 -f Dockerfile-amd64 .




arm64:

docker buildx build --platform linux/arm64 -t semantic-grouper:12-arm64 -f Dockerfile-arm64 .




# build expert-agent

amd64:

docker buildx build --platform linux/amd64 -t expert-agent:12-amd64 -f Dockerfile-amd64 .




arm64:

docker buildx build --platform linux/arm64 -t expert-agent:12-arm64 -f Dockerfile-arm64 .



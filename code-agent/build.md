
# build code-agent

amd64:

docker buildx build --platform linux/amd64 -t code-agent:v0.11.0-amd64 -f Dockerfile-amd64 .




arm64:

docker buildx build --platform linux/arm64 -t code-agent:v0.11.0-arm64 -f Dockerfile-arm64 .



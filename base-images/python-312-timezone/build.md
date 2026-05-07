
# amd64-debian:

docker buildx build --platform linux/amd64 -t python:3.12-ubuntu-timezone-amd64 -f Dockerfile-312-amd64-debian .




# arm64-debian:

docker buildx build --platform linux/arm64 -t python:3.12-ubuntu-timezone-arm64 -f Dockerfile-312-arm64-debian .



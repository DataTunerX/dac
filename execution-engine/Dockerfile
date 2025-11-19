# Build the manager binary
FROM docker.m.daocloud.io/golang:1.24 AS builder
ARG TARGETOS
ARG TARGETARCH

RUN go env -w GOPROXY=https://mirrors.aliyun.com/goproxy/,direct

WORKDIR /workspace
# Copy the Go Modules manifests
COPY go.mod go.mod
COPY go.sum go.sum
# cache deps before building and copying source so that we don't need to re-download as much
# and so that source changes don't invalidate our downloaded layer
RUN go mod download

# Copy the go source
COPY cmd/main.go cmd/main.go
COPY api/ api/
COPY internal/ internal/
COPY client/ client/

# Build
# the GOARCH has not a default value to allow the binary be built according to the host where the command
# was called. For example, if we call make docker-build in a local env which has the Apple Silicon M1 SO
# the docker BUILDPLATFORM arg will be linux/arm64 when for Apple x86 it will be linux/amd64. Therefore,
# by leaving it empty we can ensure that the container and binary shipped on it will have the same platform.
RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -a -o manager cmd/main.go


# for timezone
FROM docker.m.daocloud.io/alpine:latest AS timezone
RUN apk add --no-cache tzdata


# Use distroless as minimal base image to package the manager binary
# Refer to https://github.com/GoogleContainerTools/distroless for more details
#FROM gcr.io/distroless/static:nonroot
FROM registry.cn-shanghai.aliyuncs.com/jamesxiong/static:nonroot-amd64
WORKDIR /
COPY --from=builder /workspace/manager .

COPY --from=timezone /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
ENV TZ=Asia/Shanghai

USER 65532:65532

ENTRYPOINT ["/manager"]

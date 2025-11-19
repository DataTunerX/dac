# 多阶段构建 Dockerfile

# 构建阶段
FROM golang:1.25-alpine AS builder

# 设置工作目录
WORKDIR /app

# 安装构建依赖
RUN apk add --no-cache git make

# 复制 go mod 文件
COPY go.mod go.sum ./

# 下载依赖
RUN go mod download

# 复制源代码
COPY . .

# 编译应用（添加编译优化参数）
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-w -s" -o bin/dac-apiserver ./cmd/server

# 运行阶段
FROM alpine:latest

# 安装运行时依赖
RUN apk --no-cache add ca-certificates tzdata

# 设置时区
ENV TZ=Asia/Shanghai

# 创建非 root 用户
RUN addgroup -g 1000 app && \
    adduser -D -u 1000 -G app app

# 设置工作目录
WORKDIR /app

# 从构建阶段复制二进制文件和默认配置（直接指定所有者）
COPY --from=builder --chown=app:app /app/bin/dac-apiserver .

# 切换到非 root 用户
USER app

# 暴露端口
EXPOSE 8080 9090

# 启动应用（使用生产配置）
CMD ["./dac-apiserver", "-c", "configs/config.yaml"]


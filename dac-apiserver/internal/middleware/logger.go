package middleware

import (
	"context"
	"log/slog"
	"time"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/google/uuid"
)

// RequestIDKey 请求 ID of上下文键
const RequestIDKey = "X-Request-ID"

// Logger 日志中间件
func Logger() app.HandlerFunc {
	return func(ctx context.Context, c *app.RequestContext) {
		start := time.Now()
		path := string(c.Path())

		// 跳过健康检查路径of日志记录
		skipLogging := path == "/health/live" || path == "/health/ready"

		// 生成orget请求 ID
		requestID := string(c.Request.Header.Peek(RequestIDKey))
		if requestID == "" {
			requestID = uuid.New().String()
		}
		c.Response.Header.Set(RequestIDKey, requestID)

		// 记录请求信息（跳过健康检查）
		var logger *slog.Logger
		if !skipLogging {
			logger = slog.Default().With(
				"request_id", requestID,
				"method", string(c.Method()),
				"path", path,
				"client_ip", c.ClientIP(),
			)
			logger.Info("request started")
		}

		// 处理请求
		c.Next(ctx)

		// 记录响应信息（跳过健康检查）
		if !skipLogging {
			latency := time.Since(start)
			statusCode := c.Response.StatusCode()

			logger = logger.With(
				"status", statusCode,
				"latency", latency.String(),
				"latency_ms", latency.Milliseconds(),
			)

			if statusCode >= 500 {
				logger.Error("request completed with server error")
			} else if statusCode >= 400 {
				logger.Warn("request completed with client error")
			} else {
				logger.Info("request completed successfully")
			}
		}
	}
}

// GetRequestID 从上下文中get请求 ID
func GetRequestID(c *app.RequestContext) string {
	return string(c.Response.Header.Peek(RequestIDKey))
}

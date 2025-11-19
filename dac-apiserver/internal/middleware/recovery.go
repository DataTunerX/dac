package middleware

import (
	"context"
	"fmt"
	"log/slog"
	"runtime/debug"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/common/utils"
	"github.com/cloudwego/hertz/pkg/protocol/consts"
)

// Recovery 恢复中间件，用于捕获 panic
func Recovery() app.HandlerFunc {
	return func(ctx context.Context, c *app.RequestContext) {
		defer func() {
			if err := recover(); err != nil {
				// get堆栈信息
				stack := string(debug.Stack())

				// Log panic information
				logger := slog.Default().With(
					"request_id", GetRequestID(c),
					"method", string(c.Method()),
					"path", string(c.Path()),
					"panic", fmt.Sprintf("%v", err),
				)

				logger.Error("panic recovered",
					"stack", stack,
				)

				// Return error response
				c.JSON(consts.StatusInternalServerError, utils.H{
					"code":    "INTERNAL_ERROR",
					"message": "Internal server error",
				})

				// Abort request chain
				c.Abort()
			}
		}()

		c.Next(ctx)
	}
}

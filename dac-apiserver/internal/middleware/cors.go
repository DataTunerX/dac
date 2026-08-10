package middleware

import (
	"context"

	"github.com/cloudwego/hertz/pkg/app"
)

// CORS middleware for cross-origin resource sharing
func CORS() app.HandlerFunc {
	return func(ctx context.Context, c *app.RequestContext) {
		origin := string(c.Request.Header.Peek("Origin"))
		if origin != "" {
			c.Response.Header.Set("Access-Control-Allow-Origin", origin)
			c.Response.Header.Set("Access-Control-Allow-Credentials", "true")
			c.Response.Header.Set("Vary", "Origin")
		} else {
			c.Response.Header.Set("Access-Control-Allow-Origin", "*")
		}
		c.Response.Header.Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
		c.Response.Header.Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID")
		c.Response.Header.Set("Access-Control-Expose-Headers", "X-Request-ID")
		c.Response.Header.Set("Access-Control-Max-Age", "86400")

		// Handle OPTIONS preflight request
		if string(c.Method()) == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}

		c.Next(ctx)
	}
}

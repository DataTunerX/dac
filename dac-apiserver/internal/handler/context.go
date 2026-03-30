package handler

import (
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"
)

// GetUserIDFromContext reads the authenticated user ID from the request context.
// It is set by JWT middleware. Returns (userID, true) when present and valid, ("", false) otherwise.
// When ok is false, the caller should respond with ErrorResponse(c, domain.ErrUnauthorized) and return.
func GetUserIDFromContext(c *app.RequestContext, logger *slog.Logger) (userID string, ok bool) {
	userIDVal, exists := c.Get("user_id")
	if !exists {
		if logger != nil {
			logger.Error("user_id not found in context")
		}
		return "", false
	}
	userID, ok = userIDVal.(string)
	if !ok || userID == "" {
		if logger != nil {
			logger.Error("invalid user_id in context")
		}
		return "", false
	}
	return userID, true
}

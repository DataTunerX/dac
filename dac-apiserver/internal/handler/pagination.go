package handler

import (
	"strconv"

	"github.com/cloudwego/hertz/pkg/app"
)

type limitOffset struct {
	Limit  int
	Offset int
}

// parseLimitOffset reads limit and offset from query (e.g. ?limit=20&offset=0),
// applying defaultLimit and maxLimit when given.
func parseLimitOffset(c *app.RequestContext, defaultLimit, maxLimit int) limitOffset {
	var out limitOffset

	// offset
	if v, err := strconv.Atoi(c.DefaultQuery("offset", "0")); err == nil && v >= 0 {
		out.Offset = v
	}

	// limit
	limit := defaultLimit
	if v, err := strconv.Atoi(c.DefaultQuery("limit", strconv.Itoa(defaultLimit))); err == nil && v > 0 {
		limit = v
	}
	if limit <= 0 {
		limit = defaultLimit
	}
	if maxLimit > 0 && limit > maxLimit {
		limit = maxLimit
	}
	out.Limit = limit
	return out
}

// paginateSlice returns the sub-slice of items for the given offset and limit.
func paginateSlice[T any](items []T, offset, limit int) []T {
	if offset < 0 {
		offset = 0
	}
	if limit <= 0 {
		return []T{}
	}
	if offset >= len(items) {
		return []T{}
	}
	end := offset + limit
	if end > len(items) {
		end = len(items)
	}
	return items[offset:end]
}


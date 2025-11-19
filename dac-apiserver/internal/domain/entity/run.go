package entity

import "time"

// Run runentity（一个连续of多轮对话，Domain 层纯粹对象）
type Run struct {
	ID        string
	UserID    string
	AgentID   string
	CreatedAt time.Time
	UpdatedAt time.Time
}

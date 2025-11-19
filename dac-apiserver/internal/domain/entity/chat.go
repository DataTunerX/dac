package entity

import "time"

// ChatMessage Chat消息（Domain 层纯粹对象）
type ChatMessage struct {
	Role      string        // user, assistant, system
	Parts     []MessagePart // 消息内容部分
	MessageID string        // 消息 ID
	Timestamp time.Time     // 消息时间戳
}

// MessagePart 消息内容部分
type MessagePart struct {
	Type string // text, image, etc.
	Text string
}

// ChatSession Chat会话
type ChatSession struct {
	SessionID string            // 会话 ID
	Messages  []ChatMessage     // 消息历史
	CreatedAt time.Time         // create时间
	UpdatedAt time.Time         // 更new时间
	ExpiresAt time.Time         // 过期时间
	Metadata  map[string]string // 元数据
}

// StreamChunk 流式响应块
type StreamChunk struct {
	Text      string
	IsEnd     bool
	Error     string
	MessageID string
}

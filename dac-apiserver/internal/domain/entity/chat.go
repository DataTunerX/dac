package entity

type ChatMessage struct {
	Role      string
	Content   string
	Parts     []MessagePart
	MessageID string
	Timestamp int64
}

type MessagePart struct {
	Type string
	Text string
}

// 内部流式响应块
type StreamChunk struct {
	Text    string
	Error   string
	IsEnd   bool
}


type ChatCompletion struct {
	ID      string
	Object  string
	Created int64
	Model   string
	Choices []Choice
}

type Choice struct {
	Index        int
	Message      ChatMessage
	FinishReason string
}

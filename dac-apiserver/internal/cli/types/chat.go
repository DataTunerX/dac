package types

// ChatMessage represents a chat message
type ChatMessage struct {
	Role    string `json:"role"`    // user, assistant, system
	Content string `json:"content"` // Message content
}

// ChatRequest represents a chat request
type ChatRequest struct {
	Messages []ChatMessage `json:"messages"`
	Stream   bool          `json:"stream"` // Always true for streaming
	UserID   string        `json:"user_id,omitempty"`
	RunID    string        `json:"run_id,omitempty"`
}

// ChatStreamChunk represents a streaming chat response chunk
type ChatStreamChunk struct {
	ID      string                  `json:"id"`
	Object  string                  `json:"object"`
	Created int64                   `json:"created"`
	Model   string                  `json:"model"`
	Choices []ChatStreamChunkChoice `json:"choices"`
	UserID  string                  `json:"user_id,omitempty"`
	RunID   string                  `json:"run_id,omitempty"`
}

// ChatStreamChunkChoice represents a choice in stream chunk
type ChatStreamChunkChoice struct {
	Index        int                  `json:"index"`
	Delta        ChatStreamChunkDelta `json:"delta"`
	FinishReason *string              `json:"finish_reason"`
}

// ChatStreamChunkDelta represents delta content
type ChatStreamChunkDelta struct {
	Role    string `json:"role,omitempty"`
	Content string `json:"content,omitempty"`
}

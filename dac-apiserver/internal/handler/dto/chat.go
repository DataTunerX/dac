package dto

// ============ OpenAI 兼容 API 格式（HTTP 层使用）============

// ChatCompletionMessage OpenAI 消息格式
type ChatCompletionMessage struct {
	Role    string `json:"role"`    // user, assistant, system
	Content string `json:"content"` // 消息内容
}

// ChatCompletionRequest OpenAI Chat请求（HTTP）
type ChatCompletionRequest struct {
	Messages []ChatCompletionMessage `json:"messages"`          // 消息列表
	Stream   bool                    `json:"stream"`            // is否流式
	Model    string                  `json:"model,omitempty"`   // 模型
	UserID   string                  `json:"user_id,omitempty"` // 扩展：userID
	RunID    string                  `json:"run_id,omitempty"`  // 扩展：runID
}

// ChatCompletionResponse OpenAI 响应（非流式，HTTP）
type ChatCompletionResponse struct {
	ID      string                 `json:"id"`
	Object  string                 `json:"object"` // "chat.completion"
	Created int64                  `json:"created"`
	Model   string                 `json:"model"`
	Choices []ChatCompletionChoice `json:"choices"`
	Usage   ChatCompletionUsage    `json:"usage"`

	// 扩展字段
	UserID string `json:"user_id,omitempty"`
	RunID  string `json:"run_id,omitempty"`
}

// ChatCompletionChoice 选项
type ChatCompletionChoice struct {
	Index        int                   `json:"index"`
	Message      ChatCompletionMessage `json:"message"`
	FinishReason string                `json:"finish_reason"`
}

// ChatCompletionUsage Token 用量
type ChatCompletionUsage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// ChatCompletionChunk 流式响应块（HTTP）
type ChatCompletionChunk struct {
	ID      string                       `json:"id"`
	Object  string                       `json:"object"` // "chat.completion.chunk"
	Created int64                        `json:"created"`
	Model   string                       `json:"model"`
	Choices []ChatCompletionStreamChoice `json:"choices"`

	// 扩展字段（只在第一个 chunk）
	UserID string `json:"user_id,omitempty"`
	RunID  string `json:"run_id,omitempty"`
}

// ChatCompletionStreamChoice 流式选项
type ChatCompletionStreamChoice struct {
	Index        int                 `json:"index"`
	Delta        ChatCompletionDelta `json:"delta"`
	FinishReason *string             `json:"finish_reason"`
}

// ChatCompletionDelta 增量内容
type ChatCompletionDelta struct {
	Role    string `json:"role,omitempty"`
	Content string `json:"content,omitempty"`
}

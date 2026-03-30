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

// StreamChunk is a single item in the chat streaming response.
// Progress, when non-empty, holds a JSON payload from [[DAC_PROGRESS]] or [[DAC_ANSWER]]; Python
// build_progress_frame and build_answer_frame both put the event name in payload["event"], which
// the handler uses as the SSE event name. EventType, when set by an adapter, overrides that.
//
// When upstream (e.g. data-service) sends explicit reasoning/content, set ReasoningContent and/or
// Content so the handler does not need to guess from raw Text.
type StreamChunk struct {
	Text      string
	Error     string
	IsEnd     bool
	Progress  string // JSON payload; forward as-is to SSE data line
	EventType string // optional SSE event name; empty => use default or "progress" when Progress is set

	// Explicit from upstream; when set, handler uses these instead of parsing Text.
	ReasoningContent string
	Content          string
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

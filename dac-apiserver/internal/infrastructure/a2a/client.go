package a2a

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/bytedance/sonic"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	a2aclient "trpc.group/trpc-go/trpc-a2a-go/client"
	"trpc.group/trpc-go/trpc-a2a-go/protocol"
)

// DAC frame markers (aligned with Python is_internal_dac_frame): any line starting with dacFramePrefix
// is a structured frame; payload is the substring after dacFrameSuffix.
const (
	dacFramePrefix = "[[DAC_"
	dacFrameSuffix = "]]"
)

// client implements domain.A2AClient by delegating to the trpc A2A client.
type client struct {
	a2aClient *a2aclient.A2AClient
	logger    *slog.Logger
}

// NewClient creates an A2A client that forwards stream messages and parses DAC frames.
func NewClient(baseURL string, timeout time.Duration, logger *slog.Logger) domain.A2AClient {
	a2aClient, err := a2aclient.NewA2AClient(
		baseURL,
		a2aclient.WithTimeout(timeout),
	)
	if err != nil {
		logger.Error("failed to create a2a client", "error", err)
		return nil
	}

	logger.Info("a2a client created", "base_url", baseURL, "timeout", timeout)

	return &client{
		a2aClient: a2aClient,
		logger:    logger,
	}
}

// SendMessageStreaming sends a message and returns a channel of stream chunks (DAC frames as Progress, rest as Text).
func (c *client) SendMessageStreaming(ctx context.Context, message *entity.ChatMessage, userID, runID string) (<-chan entity.StreamChunk, error) {
	parts := make([]protocol.Part, len(message.Parts))
	for i, part := range message.Parts {
		parts[i] = protocol.NewTextPart(part.Text)
	}

	a2aMessage := protocol.NewMessage(
		protocol.MessageRole(message.Role),
		parts,
	)

	a2aMessage.MessageID = message.MessageID
	metadata := map[string]interface{}{
		"user_id": userID,
		"run_id":  runID,
	}

	// 构造发送参数
	params := protocol.SendMessageParams{
		Message:  a2aMessage,
		Metadata: metadata,
	}
	c.logger.Debug("sending message with metadata",
		"user_id", userID,
		"run_id", runID,
		"message_id", message.MessageID,
	)
	streamCh, err := c.a2aClient.StreamMessage(ctx, params)
	if err != nil {
		return nil, fmt.Errorf("send streaming message: %w", err)
	}
	outputCh := make(chan entity.StreamChunk, 100)
	go c.convertStreamResponse(streamCh, outputCh)

	return outputCh, nil
}

// lineBuffer buffers incomplete lines and classifies complete lines as DAC frames or content.
type lineBuffer struct {
	buf string
}

type answerFrame struct {
	Event   string `json:"event"`
	Payload struct {
		Text string `json:"text"`
	} `json:"payload"`
}

type answerFrameState struct {
	sawChunk bool
}

// feed appends text and returns structured-frame JSON payloads (all [[DAC_*]] lines) and content lines.
// Frame payloads are later sent as StreamChunk.Progress so the handler can use payload["event"] as SSE event name.
func (b *lineBuffer) feed(text string) (framePayloads []string, content []string) {
	s := b.buf + text
	b.buf = ""
	parts := strings.Split(s, "\n")
	for i := 0; i < len(parts)-1; i++ {
		line := strings.TrimSpace(parts[i])
		if line == "" {
			continue
		}
		if payload, ok := extractDACFramePayload(line); ok {
			if payload != "" {
				framePayloads = append(framePayloads, payload)
			}
		} else {
			content = append(content, parts[i])
		}
	}
	b.buf = parts[len(parts)-1]
	return framePayloads, content
}

// extractDACFramePayload returns the JSON payload after the first "]]" for a line starting with dacFramePrefix.
func extractDACFramePayload(line string) (string, bool) {
	if !strings.HasPrefix(line, dacFramePrefix) {
		return "", false
	}
	idx := strings.Index(line, dacFrameSuffix)
	if idx == -1 {
		return "", false
	}
	payload := strings.TrimSpace(line[idx+len(dacFrameSuffix):])
	return payload, true
}

// flush returns any remaining buffer as a single content part (may be empty).
func (b *lineBuffer) flush() string {
	s := b.buf
	b.buf = ""
	return s
}

// convertStreamResponse maps upstream A2A stream events to domain StreamChunk.
// DAC answer frames are converted into explicit Content chunks here so downstream
// handlers/frontend can render them with normal token streaming behavior.
func (c *client) convertStreamResponse(inputCh <-chan protocol.StreamingMessageEvent, outputCh chan<- entity.StreamChunk) {
	defer close(outputCh)
	var lineBuf lineBuffer
	var answerState answerFrameState

	for event := range inputCh {
		result := event.Result
		if result == nil {
			continue
		}

		switch v := result.(type) {
		case *protocol.TaskArtifactUpdateEvent:
			c.handleArtifactUpdate(v, outputCh, &lineBuf, &answerState)
			if v.LastChunk != nil && *v.LastChunk {
				if remainder := lineBuf.flush(); remainder != "" {
					outputCh <- entity.StreamChunk{Text: remainder}
				}
				outputCh <- entity.StreamChunk{IsEnd: true}
				return
			}

		case *protocol.TaskStatusUpdateEvent:
			if remainder := lineBuf.flush(); remainder != "" {
				outputCh <- entity.StreamChunk{Text: remainder}
			}
			if c.handleStatusUpdate(v, outputCh) {
				return
			}

		// Add new upstream event types here when the protocol adds them, e.g.:
		// case *protocol.SomeNewEvent: c.handleSomeNewEvent(v, outputCh, &lineBuf)
		default:
			c.logger.Debug("received unhandled event type",
				"type", fmt.Sprintf("%T", result),
				"kind", result.GetKind())
		}
	}

	if remainder := lineBuf.flush(); remainder != "" {
		outputCh <- entity.StreamChunk{Text: remainder}
	}
	outputCh <- entity.StreamChunk{IsEnd: true}
}

// parseAnswerFramePayload extracts DAC answer frame event/text from JSON payload.
func parseAnswerFramePayload(payload string) (eventName string, text string, ok bool) {
	var frame answerFrame
	if err := sonic.Unmarshal([]byte(payload), &frame); err != nil {
		return "", "", false
	}
	eventName = strings.TrimSpace(frame.Event)
	if eventName == "" {
		return "", "", false
	}
	return eventName, frame.Payload.Text, true
}

// handleFramePayload converts DAC_ANSWER final output into explicit content chunks and keeps
// non-answer DAC frames as progress JSON payloads.
func (c *client) handleFramePayload(payload string, outputCh chan<- entity.StreamChunk, state *answerFrameState) {
	eventName, text, ok := parseAnswerFramePayload(payload)
	if !ok {
		outputCh <- entity.StreamChunk{Progress: payload}
		c.logger.Debug("sent progress chunk")
		return
	}

	switch eventName {
	case "final_answer_chunk":
		text = stripSuccessMarker(text)
		if text == "" {
			return
		}
		state.sawChunk = true
		outputCh <- entity.StreamChunk{Content: text}
		c.logger.Debug("sent answer content chunk", "length", len(text))
	case "final_answer":
		text = stripSuccessMarker(text)
		if text == "" || state.sawChunk {
			return
		}
		outputCh <- entity.StreamChunk{Content: text}
		c.logger.Debug("sent final answer fallback chunk", "length", len(text))
	default:
		outputCh <- entity.StreamChunk{Progress: payload}
		c.logger.Debug("sent progress chunk")
	}
}

// handleArtifactUpdate parses artifact text into DAC frame payloads and content lines, sends StreamChunks.
func (c *client) handleArtifactUpdate(
	event *protocol.TaskArtifactUpdateEvent,
	outputCh chan<- entity.StreamChunk,
	lineBuf *lineBuffer,
	answerState *answerFrameState,
) {
	text := c.extractTextFromArtifact(&event.Artifact)
	if text == "" {
		return
	}
	framePayloads, contentLines := lineBuf.feed(text)
	for _, payload := range framePayloads {
		c.handleFramePayload(payload, outputCh, answerState)
	}
	for _, line := range contentLines {
		cleaned := stripSuccessMarker(line)
		if cleaned == "" {
			continue
		}
		outputCh <- entity.StreamChunk{Text: cleaned + "\n"}
		c.logger.Debug("sent content chunk", "length", len(cleaned)+1)
	}
}

// handleStatusUpdate processes status events; returns true if the stream should end.
func (c *client) handleStatusUpdate(event *protocol.TaskStatusUpdateEvent, outputCh chan<- entity.StreamChunk) bool {
	state := event.Status.State

	switch state {
	case protocol.TaskStateCompleted:
		outputCh <- entity.StreamChunk{IsEnd: true}
		c.logger.Debug("task completed")
		return true

	case protocol.TaskStateFailed:
		outputCh <- entity.StreamChunk{IsEnd: true, Error: "task failed"}
		c.logger.Warn("task failed")
		return true
	}

	return false
}

// extractTextFromArtifact returns the first TextPart text from the artifact, or empty string.
func (c *client) extractTextFromArtifact(artifact *protocol.Artifact) string {
	if artifact == nil || artifact.Parts == nil {
		return ""
	}

	for _, part := range artifact.Parts {
		if textPart, ok := part.(*protocol.TextPart); ok {
			return textPart.Text
		}
	}

	return ""
}

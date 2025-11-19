package a2a

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	a2aclient "trpc.group/trpc-go/trpc-a2a-go/client"
	"trpc.group/trpc-go/trpc-a2a-go/protocol"
)

// client A2A clientimplementation
type client struct {
	a2aClient *a2aclient.A2AClient
	logger    *slog.Logger
}

// NewClient create A2A client
func NewClient(baseURL string, timeout time.Duration, logger *slog.Logger) domain.A2AClient {
	// create官方 A2A client
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

// SendMessageStreaming 发送消息并接收流式响应（带 metadata）
func (c *client) SendMessageStreaming(ctx context.Context, message *entity.ChatMessage, userID, runID string) (<-chan entity.StreamChunk, error) {
	// 转换为官方库of Message 格式
	parts := make([]protocol.Part, len(message.Parts))
	for i, part := range message.Parts {
		parts[i] = protocol.NewTextPart(part.Text)
	}

	a2aMessage := protocol.NewMessage(
		protocol.MessageRole(message.Role),
		parts,
	)

	// 设置 message ID
	a2aMessage.MessageID = message.MessageID

	// 构造 metadata（传递给 routing-agent）
	metadata := map[string]interface{}{
		"user_id": userID,
		"run_id":  runID,
	}

	// 构造发送参数
	params := protocol.SendMessageParams{
		Message:  a2aMessage,
		Metadata: metadata, // 添加 metadata
	}

	c.logger.Debug("sending message with metadata",
		"user_id", userID,
		"run_id", runID,
		"message_id", message.MessageID,
	)

	// 发送流式消息
	streamCh, err := c.a2aClient.StreamMessage(ctx, params)
	if err != nil {
		return nil, fmt.Errorf("failed to send streaming message: %w", err)
	}

	// create输出 channel
	outputCh := make(chan entity.StreamChunk, 100)

	// 在后台转换流式响应
	go c.convertStreamResponse(streamCh, outputCh)

	return outputCh, nil
}

// convertStreamResponse 转换官方库of流式响应为我们of格式
func (c *client) convertStreamResponse(inputCh <-chan protocol.StreamingMessageEvent, outputCh chan<- entity.StreamChunk) {
	defer close(outputCh)

	for event := range inputCh {
		result := event.Result
		if result == nil {
			continue
		}

		// 优先使用类型断言（Go 惯用方式），避免依赖string kind
		switch v := result.(type) {
		case *protocol.TaskArtifactUpdateEvent:
			// Artifact 更new事件 - 包含实际响应内容
			c.handleArtifactUpdate(v, outputCh)
			if v.LastChunk != nil && *v.LastChunk {
				return // 最后一块，结束
			}

		case *protocol.TaskStatusUpdateEvent:
			// 状态更new事件 - 任务完成/failure
			if c.handleStatusUpdate(v, outputCh) {
				return // 任务结束
			}

		default:
			// 未知事件类型 - 只记录，不阻塞
			c.logger.Debug("received unhandled event type",
				"type", fmt.Sprintf("%T", result),
				"kind", result.GetKind())
		}
	}

	// 正常结束：channel 关闭
	outputCh <- entity.StreamChunk{IsEnd: true}
}

// handleArtifactUpdate 处理 Artifact 更new事件
func (c *client) handleArtifactUpdate(event *protocol.TaskArtifactUpdateEvent, outputCh chan<- entity.StreamChunk) {
	text := c.extractTextFromArtifact(&event.Artifact)
	if text != "" {
		outputCh <- entity.StreamChunk{Text: text}
		c.logger.Debug("sent text chunk", "length", len(text))
	}

	if event.LastChunk != nil && *event.LastChunk {
		outputCh <- entity.StreamChunk{IsEnd: true}
	}
}

// handleStatusUpdate 处理状态更new事件，返回 true indicates应结束流
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

// extractTextFromArtifact 从 Artifact 中提取文本
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

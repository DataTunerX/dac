package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/protocol/consts"
	"github.com/cloudwego/hertz/pkg/protocol/sse"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// ChatHandler Chat 请求处理器（OpenAI 格式）
type ChatHandler struct {
	usecase domain.ChatUsecase
	logger  *slog.Logger
}

// NewChatHandler create Chat 处理器
func NewChatHandler(usecase domain.ChatUsecase, logger *slog.Logger) *ChatHandler {
	return &ChatHandler{
		usecase: usecase,
		logger:  logger,
	}
}

// CreateChatCompletion 处理Chat请求（OpenAI 格式）
//
//	@Summary		Chat对话interface
//	@Description	OpenAI 兼容ofChatinterface，支持流式and非流式响应
//	@Tags			Chat
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			request	body		dto.ChatCompletionRequest	true	"Chat请求"
//	@Success		200		{object}	dto.ChatCompletionResponse	"Chat响应"
//	@Failure		400		{object}	map[string]string				"Invalid request parameters"
//	@Failure		401		{object}	map[string]string				"Unauthorized"
//	@Router			/chat/completions [post]
func (h *ChatHandler) CreateChatCompletion(ctx context.Context, c *app.RequestContext) {
	var req dto.ChatCompletionRequest
	if err := c.BindJSON(&req); err != nil {
		h.logger.Error("failed to bind request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// 验证请求
	if len(req.Messages) == 0 {
		h.logger.Error("messages is required")
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// 提取最后一条user消息
	lastMessage := req.Messages[len(req.Messages)-1]
	if lastMessage.Role != "user" {
		h.logger.Error("last message must be from user")
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// 从 RequestContext 中get user_id（由 JWT middleware 设置）
	userIDVal, exists := c.Get("user_id")
	if !exists {
		h.logger.Error("user_id not found in context")
		ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	userID, ok := userIDVal.(string)
	if !ok || userID == "" {
		h.logger.Error("invalid user_id in context")
		ErrorResponse(c, domain.ErrUnauthorized)
		return
	}

	// 转换为内部格式
	chatReq := &domain.ChatRequest{
		UserID:  userID,
		RunID:   req.RunID,
		Message: lastMessage.Content,
	}

	// 添加日志上下文
	h.logger.Info("chat request received",
		"user_id", userID,
		"run_id", req.RunID,
		"stream", req.Stream)

	// based on stream 参数决定返回方式
	if req.Stream {
		h.handleStreaming(ctx, c, chatReq, req.Model)
	} else {
		h.handleNonStreaming(ctx, c, chatReq, req.Model)
	}
}

// handleNonStreaming 处理非流式请求
func (h *ChatHandler) handleNonStreaming(ctx context.Context, c *app.RequestContext, chatReq *domain.ChatRequest, model string) {
	resp, err := h.usecase.Chat(ctx, chatReq)
	if err != nil {
		h.logger.Error("chat failed", "error", err)
		ErrorResponse(c, err)
		return
	}

	// 转换为 OpenAI 格式
	openaiResp := dto.ChatCompletionResponse{
		ID:      fmt.Sprintf("chatcmpl-%d", time.Now().Unix()),
		Object:  "chat.completion",
		Created: time.Now().Unix(),
		Model:   h.getModel(model),
		Choices: []dto.ChatCompletionChoice{
			{
				Index: 0,
				Message: dto.ChatCompletionMessage{
					Role:    "assistant",
					Content: resp.Response,
				},
				FinishReason: "stop",
			},
		},
		Usage: dto.ChatCompletionUsage{
			PromptTokens:     0,
			CompletionTokens: 0,
			TotalTokens:      0,
		},
		UserID: resp.UserID,
		RunID:  resp.RunID,
	}

	c.JSON(consts.StatusOK, openaiResp)
}

// handleStreaming 处理流式请求（SSE）
func (h *ChatHandler) handleStreaming(ctx context.Context, c *app.RequestContext, chatReq *domain.ChatRequest, model string) {
	streamCh, err := h.usecase.ChatStreaming(ctx, chatReq)
	if err != nil {
		h.logger.Error("streaming chat failed", "error", err)
		ErrorResponse(c, err)
		return
	}

	// 设置状态码（必须在 SSE Writer 之前）
	c.SetStatusCode(consts.StatusOK)

	// 使用 Hertz 官方 SSE Writer（自动处理响应头and格式）
	writer := sse.NewWriter(c)
	defer writer.Close()

	chatID := fmt.Sprintf("chatcmpl-%d", time.Now().Unix())
	created := time.Now().Unix()
	modelName := h.getModel(model)

	firstChunk := true

	for chunk := range streamCh {
		if chunk.Error != "" {
			h.logger.Error("stream error", "error", chunk.Error)
			break
		}

		if chunk.Text != "" || firstChunk {
			// 构造 OpenAI 格式of流式响应
			openaiChunk := dto.ChatCompletionChunk{
				ID:      chatID,
				Object:  "chat.completion.chunk",
				Created: created,
				Model:   modelName,
				Choices: []dto.ChatCompletionStreamChoice{
					{
						Index: 0,
						Delta: dto.ChatCompletionDelta{
							Content: chunk.Text,
						},
						FinishReason: nil,
					},
				},
			}

			// 第一个 chunk 包含扩展信息and role
			if firstChunk {
				openaiChunk.UserID = chatReq.UserID
				openaiChunk.RunID = chatReq.RunID
				openaiChunk.Choices[0].Delta.Role = "assistant"
				firstChunk = false
			}

			// 使用 SSE Writer 发送（自动 Flush）
			if err := h.writeSSEJSON(writer, openaiChunk); err != nil {
				h.logger.Error("failed to write sse event", "error", err)
				break
			}
		}

		if chunk.IsEnd {
			// 发送最后一个 chunk，标记结束
			finishReason := "stop"
			finalChunk := dto.ChatCompletionChunk{
				ID:      chatID,
				Object:  "chat.completion.chunk",
				Created: created,
				Model:   modelName,
				Choices: []dto.ChatCompletionStreamChoice{
					{
						Index:        0,
						Delta:        dto.ChatCompletionDelta{},
						FinishReason: &finishReason,
					},
				},
			}
			if err := h.writeSSEJSON(writer, finalChunk); err != nil {
				h.logger.Error("failed to write final event", "error", err)
				break
			}

			// OpenAI 标准：发送 [DONE] 标记（自动 Flush）
			if err := writer.WriteEvent("", "", []byte("[DONE]")); err != nil {
				h.logger.Error("failed to write done event", "error", err)
			}
			break
		}
	}
}

// writeSSEJSON 使用 Hertz SSE Writer 发送 JSON 数据
// 注意：Hertz of Writer.WriteEvent() 内部已自动调用 Flush，无需手动 Flush
func (h *ChatHandler) writeSSEJSON(writer *sse.Writer, data interface{}) error {
	jsonData, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal json: %w", err)
	}

	// WriteEvent 自动：
	// 1. 添加 "data: " 前缀and "\n\n" 后缀
	// 2. 自动 Flush 到client（见 sse/writer.go:157）
	return writer.WriteEvent("", "", jsonData)
}

// getModel get模型名称
func (h *ChatHandler) getModel(model string) string {
	if model == "" {
		return "dac-routing-agent"
	}
	return model
}

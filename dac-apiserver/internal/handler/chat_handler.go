package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/protocol/consts"
	"github.com/cloudwego/hertz/pkg/protocol/sse"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
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

// ListConversations 列出最近会话
//
//	@Summary		列出最近会话
//	@Description	获取当前用户的最近对话列表
//	@Tags			Chat
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200		{object}	dto.ListConversationsResponse
//	@Failure		401		{object}	map[string]string				"Unauthorized"
//	@Router			/chat/conversations [get]
func (h *ChatHandler) ListConversations(ctx context.Context, c *app.RequestContext) {
	userID, ok := GetUserIDFromContext(c, h.logger)
	if !ok {
		ErrorResponse(c, domain.ErrUnauthorized)
		return
	}

	filter := domain.ConversationListFilter{}
	if daysRaw := strings.TrimSpace(c.Query("days")); daysRaw != "" {
		days, err := strconv.Atoi(daysRaw)
		if err != nil || days < 0 {
			h.logger.Error("invalid days query parameter", "days", daysRaw, "error", err)
			ErrorResponse(c, domain.ErrInvalidInput)
			return
		}
		filter.Days = days
	}

	summaries, err := h.usecase.ListConversations(ctx, userID, filter)
	if err != nil {
		h.logger.Error("failed to list conversations", "error", err)
		ErrorResponse(c, err)
		return
	}

	// 转换为 DTO
	conversations := make([]dto.Conversation, len(summaries))
	for i, s := range summaries {
		conversations[i] = dto.Conversation{
			ID:        s.ID,
			Title:     s.Title,
			CreatedAt: s.CreatedAt,
			UpdatedAt: s.UpdatedAt,
		}
	}

	c.JSON(consts.StatusOK, dto.ListConversationsResponse{
		Items: conversations,
		Total: len(conversations),
	})
}

// GetConversation 获取指定会话详情（历史记录）
//
//	@Summary		获取指定会话详情
//	@Description	根据 run_id 获取会话历史记录
//	@Tags			Chat
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			run_id	path		string						true	"Run ID"
//	@Success		200		{object}	domain.ConversationHistory
//	@Failure		401		{object}	map[string]string				"Unauthorized"
//	@Failure		404		{object}	map[string]string				"Not Found"
//	@Router			/chat/conversations/{run_id} [get]
func (h *ChatHandler) GetConversation(ctx context.Context, c *app.RequestContext) {
	userID, ok := GetUserIDFromContext(c, h.logger)
	if !ok {
		ErrorResponse(c, domain.ErrUnauthorized)
		return
	}

	runID := c.Param("run_id")
	if runID == "" {
		h.logger.Error("run_id is required")
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// 3. Call Usecase
	history, err := h.usecase.GetConversation(ctx, userID, runID)
	if err != nil {
		h.logger.Error("failed to get conversation", "error", err)
		ErrorResponse(c, err)
		return
	}

	c.JSON(consts.StatusOK, history)
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

	userID, ok := GetUserIDFromContext(c, h.logger)
	if !ok {
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

	// Return run_id for frontend to persist the conversation.
	c.Header("X-Run-Id", resp.RunID)

	// 转换为 OpenAI 格式
	openaiResp := dto.ChatCompletionResponse{
		ID:      fmt.Sprintf("chatcmpl-%d", time.Now().Unix()),
		Object:  "chat.completion",
		Created: time.Now().Unix(),
		Model:   h.getModel(model),
		Choices: []dto.Choice{
			{
				Index: 0,
				Message: dto.Message{
					Role:    "assistant",
					Content: resp.Response,
				},
				FinishReason: "stop",
			},
		},
	}

	c.JSON(consts.StatusOK, openaiResp)
}

// buildStreamDelta builds OpenAI delta from a stream chunk.
// When upstream (e.g. data-service) sends explicit ReasoningContent/Content, use them and do not guess.
// Otherwise fall back to legacy marker-based split for backward compatibility.
func buildStreamDelta(chunk entity.StreamChunk, contentPhase bool) (delta dto.ChatCompletionDelta, nextContentPhase bool) {
	if chunk.ReasoningContent != "" || chunk.Content != "" {
		delta.ReasoningContent = chunk.ReasoningContent
		delta.Content = chunk.Content
		return delta, contentPhase
	}
	return computeStreamDeltaLegacy(chunk.Text, contentPhase)
}

// computeStreamDeltaLegacy infers reasoning vs content from raw text using completion markers.
// Used only when upstream does not send explicit ReasoningContent/Content (e.g. older A2A stream).
func computeStreamDeltaLegacy(chunkText string, contentPhase bool) (delta dto.ChatCompletionDelta, nextContentPhase bool) {
	if r, a, ok := splitByCompletionMarker(chunkText); ok {
		if strings.TrimSpace(r) != "" {
			delta.ReasoningContent = r
		}
		if strings.TrimSpace(a) != "" {
			delta.Content = a
		}
		return delta, true
	}
	if contentPhase {
		delta.Content = chunkText
	} else {
		delta.ReasoningContent = chunkText
	}
	return delta, contentPhase
}

// splitByCompletionMarker splits text at the last completion marker into (reasoningPart, contentPart).
func splitByCompletionMarker(text string) (string, string, bool) {
	markers := []string{
		"✅ 所有任务执行成功完成",
		"所有任务执行成功完成",
		"✅ All tasks executed successfully",
		"All tasks executed successfully",
	}
	for _, m := range markers {
		if idx := strings.LastIndex(text, m); idx != -1 {
			return text[:idx+len(m)], text[idx+len(m):], true
		}
	}
	return "", "", false
}

// handleStreaming 处理流式请求（SSE）
//
// SSE 约定（与前端 parse-chat-sse 一致）：
//   - 进度/答案等：event 名来自 payload["event"]，data 为 [[DAC_PROGRESS]] 或 [[DAC_ANSWER]] 的原始 JSON（上游约定）
//   - 正文：无 event 或 event 非 progress 的 data: 行按 OpenAI chunk 解析（choices[0].delta.content / reasoning_content）
//   - 结束：data: [DONE]
// Hertz WriteEvent 签名为 (id, eventType, data)，故 progress 用 WriteEvent("", "progress", data) 以发出 event: progress。
func (h *ChatHandler) handleStreaming(ctx context.Context, c *app.RequestContext, chatReq *domain.ChatRequest, model string) {
	streamCh, runID, err := h.usecase.ChatStreaming(ctx, chatReq)
	if err != nil {
		h.logger.Error("streaming chat failed", "error", err)
		ErrorResponse(c, err)
		return
	}

	// 设置状态码（必须在 SSE Writer 之前）
	c.SetStatusCode(consts.StatusOK)
	// Return run_id for frontend to persist the conversation.
	if runID != "" {
		c.Header("X-Run-Id", runID)
	}

	// 使用 Hertz 官方 SSE Writer（自动处理响应头and格式）
	writer := sse.NewWriter(c)
	defer writer.Close()

	chatID := fmt.Sprintf("chatcmpl-%d", time.Now().Unix())
	created := time.Now().Unix()
	modelName := h.getModel(model)

	firstChunk := true
	// 一旦某 chunk 按完成标记拆出过 content，后续无标记的 chunk 视为正文（上游在标记之后才逐 chunk 发最终回答）
	contentPhase := false

	for chunk := range streamCh {
		if chunk.Error != "" {
			h.logger.Error("stream error", "error", chunk.Error)
			break
		}

		// Progress or custom event: emit SSE so frontend can show progress / handle event.
		if chunk.Progress != "" {
			eventType := sseEventTypeForChunk(chunk)
			if err := writer.WriteEvent("", eventType, []byte(chunk.Progress)); err != nil {
				h.logger.Error("failed to write progress event", "error", err)
				break
			}
		}

		// Content: use explicit ReasoningContent/Content when set; else legacy text parsing
		hasContent := chunk.Text != "" || chunk.ReasoningContent != "" || chunk.Content != ""
		if hasContent || firstChunk {
			var delta dto.ChatCompletionDelta
			delta, contentPhase = buildStreamDelta(chunk, contentPhase)
			if firstChunk {
				delta.Role = "assistant"
			}

			openaiChunk := dto.ChatCompletionChunk{
				ID:      chatID,
				Object:  "chat.completion.chunk",
				Created: created,
				Model:   modelName,
				Choices: []dto.ChunkChoice{
					{
						Index:        0,
						Delta:        delta,
						FinishReason: "",
					},
				},
			}
			if firstChunk {
				firstChunk = false
			}
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
				Choices: []dto.ChunkChoice{
					{
						Index:        0,
						Delta:        dto.ChatCompletionDelta{},
						FinishReason: finishReason,
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

// sseEventTypeForChunk returns the SSE event name for a progress chunk.
//
// Contract (aligned with Python): upstream sends [[DAC_PROGRESS]] and [[DAC_ANSWER]] <JSON>; both
// have an "event" field (build_progress_frame / build_answer_frame in orchestrator, routing, expert).
// Our A2A client only sets chunk.Progress to that JSON and never sets chunk.EventType, so
// the authoritative source for the SSE event name is the "event" field inside Progress JSON.
// EventType on the chunk is only used when explicitly set by a different adapter (e.g. future
// data-service stream); then it overrides the payload.
func sseEventTypeForChunk(chunk entity.StreamChunk) string {
	if chunk.EventType != "" {
		return chunk.EventType
	}
	// Progress JSON is the only source of event name from current A2A pipeline.
	if chunk.Progress != "" {
		if name := eventNameFromProgressJSON(chunk.Progress); name != "" {
			return name
		}
	}
	return "progress"
}

// eventNameFromProgressJSON extracts the "event" field from a progress JSON payload.
// Python build_progress_frame always includes "event"; this is the canonical event name.
func eventNameFromProgressJSON(payload string) string {
	var m struct {
		Event string `json:"event"`
	}
	if err := json.Unmarshal([]byte(payload), &m); err != nil {
		return ""
	}
	s := strings.TrimSpace(m.Event)
	if s == "" {
		return ""
	}
	if len(s) > 128 || strings.ContainsAny(s, "\r\n") {
		return ""
	}
	return s
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

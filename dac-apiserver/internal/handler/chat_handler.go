package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
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

	summaries, err := h.usecase.ListConversations(ctx, userID)
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
	// 1. Get UserID
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

	// 2. Get RunID
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

// isReasoning 判断文本是否属于思考过程（ReasoningContent）
// 根据 OrchestratorAgent 和 ExpertAgent 的输出特征进行匹配
func isReasoning(text string) bool {
	t := strings.TrimSpace(text)

	// Chart/tool intermediate notes (should be shown in Thought Process, not final answer).
	// These are often emitted before a later successful ```chart block.
	if strings.Contains(t, "无法生成图表") || strings.Contains(t, "无法直接生成图表") {
		return true
	}

	// Replan / retry logs emitted by orchestrator (should be shown in Thought Process).
	// Examples:
	// - "=== 计划执行遇到问题，正在进行第 1 次重试 ==="
	// - "=== 第 1 次重新规划成功，新计划如下 ==="
	// - "失败分析:"
	// - "新计划如下"
	if strings.Contains(t, "重新规划") || strings.Contains(t, "新计划如下") {
		return true
	}
	if strings.Contains(t, "计划执行遇到问题") || strings.Contains(t, "正在进行第") || strings.Contains(t, "次重试") {
		return true
	}
	if strings.Contains(t, "失败分析") {
		return true
	}
	if strings.HasPrefix(t, "===") {
		return true
	}

	// Completion markers (should be shown in Thought Process, not in final answer)
	// Examples:
	// - "✅ 所有任务执行成功完成"
	// - "✅ All tasks executed successfully"
	if strings.Contains(t, "所有任务执行成功完成") || strings.Contains(t, "All tasks executed successfully") {
		return true
	}
	if strings.HasPrefix(t, "✅") || strings.HasPrefix(t, "✔") {
		return true
	}

	// SQL intermediate results / evaluator notes
	if strings.Contains(text, "sql query result:") || strings.Contains(text, "SQL query result:") {
		return true
	}
	if strings.HasPrefix(t, "reason:") || strings.HasPrefix(t, "Reason:") || strings.HasPrefix(t, "reason：") || strings.HasPrefix(t, "Reason：") {
		return true
	}

	// Planner / Orchestrator planning logs (should be shown in Thought Process, not in final answer)
	// Examples:
	// - "All Tasks: ..."
	// - "Task [1]: ..."
	// - "[1]: ..."
	if strings.HasPrefix(t, "All Tasks:") || strings.HasPrefix(t, "All Tasks：") {
		return true
	}
	if strings.HasPrefix(t, "Task [") || strings.HasPrefix(t, "Task[") {
		return true
	}
	if strings.HasPrefix(t, "[") && strings.Contains(t, "]:") {
		return true
	}

	// Expert Agent 步骤特征
	if strings.Contains(text, "step ") && strings.Contains(text, "query:") {
		return true
	}
	if strings.HasPrefix(text, "step ") {
		return true
	}
	if strings.Contains(text, "conditions:") {
		return true
	}
	if strings.Contains(text, "query:") {
		return true
	}
	if strings.Contains(text, "answer:") && strings.Contains(text, "query:") { // 中间步骤的 answer
		return true
	}

	// Orchestrator Agent 任务列表特征
	if strings.Contains(text, "Task [") && strings.Contains(text, "description:") {
		return true
	}
	// Orchestrator Agent 任务状态特征
	if strings.Contains(text, "Executing step") {
		return true
	}
	
	// 错误或未找到 Agent 信息
	if strings.Contains(text, "Not found agent") || strings.Contains(text, "Error occurred") {
		return true
	}

	return false
}

// splitByCompletionMarker splits a chunk into (reasoningPart, contentPart) at the completion marker.
// Uses the **last** occurrence so that all sub-agent blocks (【智能体 N】... step ... ✅) stay in 思考过程,
// and only the text after the final marker goes to 正文.
func splitByCompletionMarker(text string) (string, string, bool) {
	markers := []string{
		"✅ 所有任务执行成功完成",
		"所有任务执行成功完成",
		"✅ All tasks executed successfully",
		"All tasks executed successfully",
	}
	for _, m := range markers {
		if idx := strings.LastIndex(text, m); idx != -1 {
			r := text[:idx+len(m)]
			a := text[idx+len(m):]
			return r, a, true
		}
	}
	return "", "", false
}

// handleStreaming 处理流式请求（SSE）
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

		if chunk.Text != "" || firstChunk {
			delta := dto.ChatCompletionDelta{}

			// 只按完成标记拆分：有标记则前半 reasoning、后半 content；无标记时，若已进入正文阶段则归 content，否则归 reasoning。
			if r, a, ok := splitByCompletionMarker(chunk.Text); ok {
				if strings.TrimSpace(r) != "" {
					delta.ReasoningContent = r
				}
				if strings.TrimSpace(a) != "" {
					delta.Content = a
				}
				// 本 chunk 已出现完成标记，后续无标记 chunk 视为正文（上游在标记之后才逐 chunk 发最终回答）
				contentPhase = true
			} else {
				if contentPhase {
					delta.Content = chunk.Text
				} else {
					delta.ReasoningContent = chunk.Text
				}
			}

			if firstChunk {
				delta.Role = "assistant"
			}

			// 构造 OpenAI 格式of流式响应
			openaiChunk := dto.ChatCompletionChunk{
				ID:      chatID,
				Object:  "chat.completion.chunk",
				Created: created,
				Model:   modelName,
				Choices: []dto.ChunkChoice{
					{
						Index:        0,
						Delta:        delta,
						FinishReason: "", // Empty string for active stream
					},
				},
			}
			
			// 如果是第一个chunk，FirstChunk 逻辑已在上面处理
			if firstChunk {
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

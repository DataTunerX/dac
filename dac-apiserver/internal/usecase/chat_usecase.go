package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"strings"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/dataservices"
)

type chatUsecase struct {
	chatRepo  domain.ChatRepository
	a2aClient domain.A2AClient
	dsClient  *dataservices.Client // Inject DataServices client
	logger    *slog.Logger
}

// NewChatUsecase create Chat 用例
func NewChatUsecase(chatRepo domain.ChatRepository, a2aClient domain.A2AClient, dsClient *dataservices.Client, logger *slog.Logger) domain.ChatUsecase {
	return &chatUsecase{
		chatRepo:  chatRepo,
		a2aClient: a2aClient,
		dsClient:  dsClient,
		logger:    logger,
	}
}

// Chat 发送Chat消息（非流式）
func (u *chatUsecase) Chat(ctx context.Context, req *domain.ChatRequest) (*domain.ChatResponse, error) {
	// 1. 获取或创建 Run
	run, err := u.chatRepo.GetOrCreateRun(ctx, req.UserID, req.RunID, "routing-agent") // 默认 routing-agent
	if err != nil {
		return nil, fmt.Errorf("failed to get or create run: %w", err)
	}

	// 2. 构造消息
	msg := &entity.ChatMessage{
		Role:      "user",
		Content:   req.Message,
		Parts:     []entity.MessagePart{{Type: "text", Text: req.Message}},
		MessageID: fmt.Sprintf("%d", time.Now().UnixNano()), // 简单 ID
		Timestamp: time.Now().Unix(),
	}

	// 3. 调用 A2A Client (非流式暂时复用流式接口，取最后结果)
	streamCh, err := u.a2aClient.SendMessageStreaming(ctx, msg, req.UserID, run.ID)
	if err != nil {
		return nil, fmt.Errorf("failed to send message: %w", err)
	}

	var finalResponse string
	for chunk := range streamCh {
		if chunk.Error != "" {
			return nil, fmt.Errorf("a2a error: %s", chunk.Error)
		}
		if chunk.Text != "" {
			finalResponse += chunk.Text
		}
	}

	return &domain.ChatResponse{
		UserID:   req.UserID,
		RunID:    run.ID,
		Response: finalResponse,
	}, nil
}

// ChatStreaming 发送Chat消息（流式）
func (u *chatUsecase) ChatStreaming(ctx context.Context, req *domain.ChatRequest) (<-chan entity.StreamChunk, string, error) {
	// 1. 获取或创建 Run
	run, err := u.chatRepo.GetOrCreateRun(ctx, req.UserID, req.RunID, "routing-agent") // 默认 routing-agent
	if err != nil {
		return nil, "", fmt.Errorf("failed to get or create run: %w", err)
	}

	// 2. 构造消息
	msg := &entity.ChatMessage{
		Role:      "user",
		Content:   req.Message,
		Parts:     []entity.MessagePart{{Type: "text", Text: req.Message}},
		MessageID: fmt.Sprintf("%d", time.Now().UnixNano()),
		Timestamp: time.Now().Unix(),
	}

	// 3. 调用 A2A Client
	ch, err := u.a2aClient.SendMessageStreaming(ctx, msg, req.UserID, run.ID)
	if err != nil {
		return nil, "", err
	}
	return ch, run.ID, nil
}

func parseHistoryTime(s string) time.Time {
	if s == "" {
		return time.Time{}
	}
	// data-services usually returns RFC3339 timestamps.
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t
	}
	// Some drivers may include timezone-less formats; best-effort.
	if t, err := time.Parse("2006-01-02 15:04:05", s); err == nil {
		return t
	}
	return time.Time{}
}

// conversationTitleFromHistory returns the first user question as title (earliest user message).
func conversationTitleFromHistory(records []dataservices.HistoryRecord) string {
	if len(records) == 0 {
		return ""
	}

	// Ensure we pick the earliest record to approximate "first question".
	sorted := append([]dataservices.HistoryRecord(nil), records...)
	sort.SliceStable(sorted, func(i, j int) bool {
		ti := parseHistoryTime(sorted[i].CreatedAt)
		tj := parseHistoryTime(sorted[j].CreatedAt)
		if ti.IsZero() || tj.IsZero() {
			// Fall back to original order if timestamps are not parseable.
			return i < j
		}
		return ti.Before(tj)
	})

	for _, record := range sorted {
		for _, msg := range record.Messages {
			role, _ := msg["role"].(string)
			content, _ := msg["content"].(string)
			if role != "user" {
				continue
			}
			clean := strings.TrimSpace(content)
			clean = strings.ReplaceAll(clean, "\n", " ")
			clean = strings.Join(strings.Fields(clean), " ")
			if clean == "" {
				continue
			}
			const maxRunes = 32
			r := []rune(clean)
			if len(r) <= maxRunes {
				return clean
			}
			return string(r[:maxRunes]) + "…"
		}
	}
	return ""
}

// ListConversations 列出用户的最近会话
func (u *chatUsecase) ListConversations(ctx context.Context, userID string) ([]domain.ConversationSummary, error) {
	runs, err := u.chatRepo.ListUserRuns(ctx, userID)
	if err != nil {
		return nil, err
	}

	summaries := make([]domain.ConversationSummary, 0, len(runs))
	for _, run := range runs {
		title := ""
		if u.dsClient != nil {
			records, err := u.dsClient.GetRunHistory(ctx, userID, run.ID)
			if err != nil {
				u.logger.Warn("failed to load run history for conversation title", "run_id", run.ID, "error", err)
			} else {
				title = conversationTitleFromHistory(records)
			}
		}

		summaries = append(summaries, domain.ConversationSummary{
			ID:        run.ID,
			Title:     title,
			CreatedAt: run.CreatedAt,
			UpdatedAt: run.UpdatedAt,
		})
	}

	return summaries, nil
}

// GetConversation 获取指定会话的历史记录
func (u *chatUsecase) GetConversation(ctx context.Context, userID, runID string) (*domain.ConversationHistory, error) {
	// 1. 验证 Run 是否属于用户
	run, err := u.chatRepo.GetRun(ctx, runID)
	if err != nil {
		return nil, fmt.Errorf("failed to get run: %w", err)
	}
	if run.UserID != userID {
		return nil, domain.ErrUnauthorized // 借用 ErrUnauthorized 表示无权访问
	}

	// 2. 从 Data Services 获取历史记录
	historyRecords, err := u.dsClient.GetRunHistory(ctx, userID, runID)
	if err != nil {
		return nil, fmt.Errorf("failed to get history from data services: %w", err)
	}

	// 3. 转换格式
	var messages []domain.MessageItem

	// 遍历记录并展平消息
	for _, record := range historyRecords {
		for _, msg := range record.Messages {
			role, _ := msg["role"].(string)
			content, _ := msg["content"].(string)
			think, _ := msg["think"].(string)
			if role == "" || content == "" {
				continue
			}
			messages = append(messages, domain.MessageItem{
				Role:    role,
				Content: content,
				Think:   think,
			})
		}
	}

	return &domain.ConversationHistory{
		RunID:    runID,
		Messages: messages,
	}, nil
}

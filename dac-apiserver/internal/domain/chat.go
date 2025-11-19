package domain

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// ============ Usecase 层内部使用of DTO ============

// ChatRequest 内部Chat请求（usecase 使用）
type ChatRequest struct {
	UserID  string
	RunID   string
	Message string
}

// ChatResponse 内部Chat响应
type ChatResponse struct {
	UserID   string
	RunID    string
	Response string
}

// ChatRepository Chat 数据存储interface（只负责 Run 相关数据）
type ChatRepository interface {
	// GetOrCreateRun getorcreaterun
	GetOrCreateRun(ctx context.Context, userID, runID, agentID string) (*entity.Run, error)

	// GetRun getrun
	GetRun(ctx context.Context, runID string) (*entity.Run, error)

	// ListUserRuns getuserof所有run
	ListUserRuns(ctx context.Context, userID string) ([]*entity.Run, error)

	// DeleteRun 删除run
	DeleteRun(ctx context.Context, runID string) error
}

// A2AClient A2A clientinterface
type A2AClient interface {
	// SendMessageStreaming 发送消息并接收流式响应（带 metadata）
	SendMessageStreaming(ctx context.Context, message *entity.ChatMessage, userID, runID string) (<-chan entity.StreamChunk, error)
}

// ChatUsecase Chat用例interface
type ChatUsecase interface {
	// Chat 发送Chat消息（非流式）
	Chat(ctx context.Context, req *ChatRequest) (*ChatResponse, error)

	// ChatStreaming 发送Chat消息（流式）
	ChatStreaming(ctx context.Context, req *ChatRequest) (<-chan entity.StreamChunk, error)
}

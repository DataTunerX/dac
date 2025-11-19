package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// chatUsecase is ChatUsecase interfaceofimplementation。
// 它协调 A2A clientanddatabase存储，处理userandrunof生命周期manage。
type chatUsecase struct {
	a2aClient domain.A2AClient
	chatRepo  domain.ChatRepository
	userRepo  domain.UserRepository // new增：用于验证user
	logger    *slog.Logger
}

// NewChatUsecase create一个newof Chat 用例实例。
//
// Parameters:
//   - a2aClient: A2A 协议client，用于with routing-agent 通信
//   - chatRepo: Chat 数据存储，用于managerun
//   - userRepo: User 数据存储，用于验证user
//   - logger: 结构化日志记录器
//
// Returns:
//   - domain.ChatUsecase interfaceimplementation
func NewChatUsecase(
	a2aClient domain.A2AClient,
	chatRepo domain.ChatRepository,
	userRepo domain.UserRepository,
	logger *slog.Logger,
) domain.ChatUsecase {
	return &chatUsecase{
		a2aClient: a2aClient,
		chatRepo:  chatRepo,
		userRepo:  userRepo,
		logger:    logger,
	}
}

// Chat 发送Chat消息并等待完整响应（非流式）。
//
// 该方法会：
//  1. 验证请求参数（UserID、RunID、Message）
//  2. getorcreateuserandrun
//  3. 通过 A2A client发送消息到 routing-agent
//  4. 收集所有流式响应块并返回完整响应
//
// Parameters:
//   - ctx: request context，用于超时控制and取消信号
//   - req: Chat请求，包含 UserID、Message and可选of RunID
//
// Returns:
//   - *domain.ChatResponse: 包含完整响应ofChat响应
//   - error: 验证failure、database错误or A2A 通信错误
func (u *chatUsecase) Chat(ctx context.Context, req *domain.ChatRequest) (*domain.ChatResponse, error) {
	// 验证输入
	if err := u.validateChatRequest(req); err != nil {
		return nil, err
	}

	// 1. 验证useris否exists（user必须先注册）
	_, err := u.userRepo.GetByID(ctx, req.UserID)
	if err != nil {
		return nil, fmt.Errorf("user not found or invalid: %w", err)
	}

	// 2. getorcreate Run
	// 注意：If req.RunID is empty，会createnew Run（newconversation）
	run, err := u.chatRepo.GetOrCreateRun(ctx, req.UserID, req.RunID, "")
	if err != nil {
		return nil, fmt.Errorf("failed to get or create run: %w", err)
	}

	// Ifisnewcreateof Run，记录日志（关键业务指标）
	if req.RunID == "" {
		u.logger.Info("new conversation topic started", "run_id", run.ID)
	}

	// 3. createuser消息
	userMessage := &entity.ChatMessage{
		Role:      "user",
		Parts:     []entity.MessagePart{{Type: "text", Text: req.Message}},
		MessageID: uuid.New().String(),
		Timestamp: time.Now(),
	}

	// 4. 调用 A2A client（传递 metadata）
	streamCh, err := u.a2aClient.SendMessageStreaming(ctx, userMessage, req.UserID, run.ID)
	if err != nil {
		return nil, fmt.Errorf("failed to send message: %w", err)
	}

	// 5. 收集所有流式响应
	var fullResponse string
	for chunk := range streamCh {
		if chunk.Error != "" {
			return nil, fmt.Errorf("streaming error: %s", chunk.Error)
		}
		fullResponse += chunk.Text
	}

	return &domain.ChatResponse{
		UserID:   req.UserID,
		RunID:    run.ID,
		Response: fullResponse,
	}, nil
}

// ChatStreaming 发送Chat消息并返回流式响应通道（SSE）。
//
// 该方法会：
//  1. 验证请求参数
//  2. getorcreateuserandrun
//  3. 通过 A2A client发送消息并返回流式响应通道
//
// Parameters:
//   - ctx: request context
//   - req: Chat请求
//
// Returns:
//   - <-chan entity.StreamChunk: 流式响应通道
//   - error: 验证failureor初始化错误
func (u *chatUsecase) ChatStreaming(ctx context.Context, req *domain.ChatRequest) (<-chan entity.StreamChunk, error) {
	// 验证输入
	if err := u.validateChatRequest(req); err != nil {
		return nil, err
	}

	// 1. 验证useris否exists（user必须先注册）
	_, err := u.userRepo.GetByID(ctx, req.UserID)
	if err != nil {
		return nil, fmt.Errorf("user not found or invalid: %w", err)
	}

	// 2. getorcreate Run
	// 注意：If req.RunID is empty，会createnew Run（newconversation）
	run, err := u.chatRepo.GetOrCreateRun(ctx, req.UserID, req.RunID, "")
	if err != nil {
		return nil, fmt.Errorf("failed to get or create run: %w", err)
	}

	// Ifisnewcreateof Run，记录日志（关键业务指标）
	if req.RunID == "" {
		u.logger.Info("new conversation topic started", "run_id", run.ID)
	}

	// 3. createuser消息
	userMessage := &entity.ChatMessage{
		Role:      "user",
		Parts:     []entity.MessagePart{{Type: "text", Text: req.Message}},
		MessageID: uuid.New().String(),
		Timestamp: time.Now(),
	}

	// 4. 调用 A2A client（传递 metadata）
	streamCh, err := u.a2aClient.SendMessageStreaming(ctx, userMessage, req.UserID, run.ID)
	if err != nil {
		return nil, fmt.Errorf("failed to send message: %w", err)
	}

	return streamCh, nil
}

// validateChatRequest 验证Chat请求并规范化
func (u *chatUsecase) validateChatRequest(req *domain.ChatRequest) error {
	if req == nil {
		return domain.ErrInvalidInput
	}

	// If没有 UserID，自动生成（匿名user）
	if req.UserID == "" {
		req.UserID = uuid.New().String()
		u.logger.Info("anonymous user created", "user_id", req.UserID)
	} else {
		// If提供了 UserID，验证格式
		if _, err := uuid.Parse(req.UserID); err != nil {
			return fmt.Errorf("%w: invalid user_id format (must be UUID)", domain.ErrInvalidInput)
		}
	}

	// 验证 RunID（If提供，必须is有效of UUID）
	if req.RunID != "" {
		if _, err := uuid.Parse(req.RunID); err != nil {
			return fmt.Errorf("%w: invalid run_id format (must be UUID)", domain.ErrInvalidInput)
		}
	}

	// 验证消息内容
	if req.Message == "" {
		return fmt.Errorf("%w: message is required", domain.ErrInvalidInput)
	}
	if len(req.Message) > 10000 { // 限制消息长度
		return fmt.Errorf("%w: message too long (max 10000 characters)", domain.ErrInvalidInput)
	}

	return nil
}

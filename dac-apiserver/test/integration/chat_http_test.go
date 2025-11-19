//go:build integration
// +build integration

package integration

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/cloudwego/hertz/pkg/app/server"
	"github.com/cloudwego/hertz/pkg/network/netpoll"
	"github.com/lvyanru/dac-apiserver/internal/config"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/a2a"
	infradb "github.com/lvyanru/dac-apiserver/internal/infrastructure/database"
	"github.com/lvyanru/dac-apiserver/internal/usecase"
	dbpkg "github.com/lvyanru/dac-apiserver/pkg/database"
)

// TestChatHTTP_SSE 完整的 HTTP SSE 集成测试
// 运行方式：make test-integration
// 需要：MySQL (localhost:3306) + Routing Agent (10.17.0.41:30100)
func TestChatHTTP_SSE(t *testing.T) {
	// 配置
	cfg := &config.Config{
		Server: config.ServerConfig{
			Host:               "127.0.0.1",
			Port:               18080, // 测试端口
			Mode:               "test",
			ReadTimeout:        30,
			WriteTimeout:       30,
			MaxRequestBodySize: 4,
		},
		RoutingAgent: config.RoutingAgentConfig{
			BaseURL:        getEnvOrDefault("ROUTING_AGENT_URL", "http://10.17.0.41:30100"),
			Timeout:        30 * time.Second,
			SessionTimeout: 30 * time.Minute,
		},
		Database: config.DatabaseConfig{
			Driver:          "mysql",
			Host:            getEnvOrDefault("DB_HOST", "127.0.0.1"),
			Port:            3306,
			User:            getEnvOrDefault("DB_USER", "dac_user"),
			Password:        getEnvOrDefault("DB_PASSWORD", "dac_pass"),
			Database:        getEnvOrDefault("DB_NAME", "dac_db"),
			MaxOpenConns:    25,
			MaxIdleConns:    5,
			ConnMaxLifetime: 5 * time.Minute,
		},
	}

	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

	// 初始化数据库
	dbClient, err := dbpkg.NewClient(cfg.Database, logger)
	if err != nil {
		t.Fatalf("failed to connect to database: %v", err)
	}
	defer dbClient.Close()

	// 初始化组件
	a2aClient := a2a.NewClient(cfg.RoutingAgent.BaseURL, cfg.RoutingAgent.Timeout, logger)
	chatRepo := infradb.NewChatRepository(dbClient)
	chatUC := usecase.NewChatUsecase(a2aClient, chatRepo, cfg.RoutingAgent.SessionTimeout, logger)
	chatHandler := handler.NewChatHandler(chatUC, logger)

	// 创建 Hertz 服务器（带性能优化）
	h := server.New(
		server.WithHostPorts(fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port)),
		server.WithTransport(netpoll.NewTransporter),
		server.WithH2C(true),
	)

	// 设置路由（只需要 chat 相关）
	v1 := h.Group("/v1")
	v1.POST("/chat/completions", chatHandler.CreateChatCompletion)

	// 启动服务器
	go func() {
		if err := h.Run(); err != nil {
			logger.Error("server failed", "error", err)
		}
	}()

	// 等待服务器启动
	time.Sleep(2 * time.Second)
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		h.Shutdown(ctx)
	}()

	baseURL := fmt.Sprintf("http://%s:%d", cfg.Server.Host, cfg.Server.Port)

	t.Run("SSE streaming chat", func(t *testing.T) {
		reqBody := domain.ChatCompletionRequest{
			Messages: []domain.ChatCompletionMessage{
				{Role: "user", Content: "你好"},
			},
			Stream: true,
		}

		bodyBytes, _ := json.Marshal(reqBody)
		req, err := http.NewRequest("POST", baseURL+"/v1/chat/completions", bytes.NewReader(bodyBytes))
		if err != nil {
			t.Fatalf("failed to create request: %v", err)
		}
		req.Header.Set("Content-Type", "application/json")

		client := &http.Client{Timeout: 60 * time.Second}
		resp, err := client.Do(req)
		if err != nil {
			t.Fatalf("request failed: %v", err)
		}
		defer resp.Body.Close()

		// 验证 SSE 响应头
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("expected status 200, got %d", resp.StatusCode)
		}

		contentType := resp.Header.Get("Content-Type")
		if !strings.Contains(contentType, "text/event-stream") {
			t.Errorf("expected Content-Type to contain 'text/event-stream', got '%s'", contentType)
		}

		// 读取 SSE 流
		reader := bufio.NewReader(resp.Body)
		chunkCount := 0
		receivedDone := false
		var firstChunk domain.ChatCompletionChunk

		for {
			line, err := reader.ReadString('\n')
			if err != nil {
				if err == io.EOF {
					break
				}
				t.Fatalf("failed to read stream: %v", err)
			}

			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}

			// 解析 SSE 格式：data: {...}
			if strings.HasPrefix(line, "data: ") {
				data := strings.TrimPrefix(line, "data: ")

				if data == "[DONE]" {
					receivedDone = true
					t.Logf("✅ Received [DONE] marker")
					break
				}

				// 解析 JSON
				var chunk domain.ChatCompletionChunk
				if err := json.Unmarshal([]byte(data), &chunk); err != nil {
					t.Errorf("failed to unmarshal chunk: %v, data: %s", err, data)
					continue
				}

				chunkCount++
				t.Logf("✅ Chunk %d: ID=%s, Object=%s, Content=%q",
					chunkCount, chunk.ID, chunk.Object, chunk.Choices[0].Delta.Content)

				// 验证第一个 chunk
				if chunkCount == 1 {
					firstChunk = chunk
					if chunk.Object != "chat.completion.chunk" {
						t.Errorf("expected object 'chat.completion.chunk', got '%s'", chunk.Object)
					}
					if chunk.ID == "" {
						t.Error("chunk ID should not be empty")
					}
					if chunk.Model == "" {
						t.Error("chunk model should not be empty")
					}
					if len(chunk.Choices) == 0 {
						t.Error("choices should not be empty")
					}
					if chunk.Choices[0].Delta.Role != "assistant" {
						t.Errorf("expected role 'assistant', got '%s'", chunk.Choices[0].Delta.Role)
					}
				}

				// 验证后续 chunk 的 ID 一致性
				if chunkCount > 1 && chunk.ID != firstChunk.ID {
					t.Errorf("chunk ID should be consistent, expected '%s', got '%s'", firstChunk.ID, chunk.ID)
				}
			}
		}

		// 最终验证
		if chunkCount == 0 {
			t.Error("expected to receive at least one chunk")
		}
		if !receivedDone {
			t.Error("expected to receive [DONE] marker")
		}

		t.Logf("✅ SSE streaming test completed: received %d chunks", chunkCount)
	})

	t.Run("non-streaming chat", func(t *testing.T) {
		reqBody := domain.ChatCompletionRequest{
			Messages: []domain.ChatCompletionMessage{
				{Role: "user", Content: "你好"},
			},
			Stream: false,
		}

		bodyBytes, _ := json.Marshal(reqBody)
		req, err := http.NewRequest("POST", baseURL+"/v1/chat/completions", bytes.NewReader(bodyBytes))
		if err != nil {
			t.Fatalf("failed to create request: %v", err)
		}
		req.Header.Set("Content-Type", "application/json")

		client := &http.Client{Timeout: 60 * time.Second}
		resp, err := client.Do(req)
		if err != nil {
			t.Fatalf("request failed: %v", err)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			t.Fatalf("expected status 200, got %d", resp.StatusCode)
		}

		var chatResp domain.ChatCompletionResponse
		if err := json.NewDecoder(resp.Body).Decode(&chatResp); err != nil {
			t.Fatalf("failed to decode response: %v", err)
		}

		// 验证响应
		if chatResp.Object != "chat.completion" {
			t.Errorf("expected object 'chat.completion', got '%s'", chatResp.Object)
		}
		if len(chatResp.Choices) == 0 {
			t.Error("expected at least one choice")
		}
		if chatResp.Choices[0].Message.Role != "assistant" {
			t.Errorf("expected role 'assistant', got '%s'", chatResp.Choices[0].Message.Role)
		}
		if chatResp.Choices[0].Message.Content == "" {
			t.Error("expected non-empty content")
		}

		t.Logf("✅ Non-streaming response: %q", chatResp.Choices[0].Message.Content)
	})

	t.Run("multi-turn conversation", func(t *testing.T) {
		client := &http.Client{Timeout: 60 * time.Second}

		// 第一条消息 - 生成新 UserID, SessionID, RunID
		reqBody1 := domain.ChatCompletionRequest{
			Messages: []domain.ChatCompletionMessage{
				{Role: "user", Content: "你好"},
			},
			Stream: false,
		}
		resp1 := sendChatRequest(t, client, baseURL, reqBody1)
		if resp1.UserID == "" || resp1.SessionID == "" || resp1.RunID == "" {
			t.Fatal("expected non-empty IDs in first response")
		}
		t.Logf("✅ Turn 1: UserID=%s, SessionID=%s, RunID=%s", 
			resp1.UserID, resp1.SessionID, resp1.RunID)

		// 第二条消息 - 继续同一话题（RunID 应保持一致）
		time.Sleep(time.Second)
		reqBody2 := domain.ChatCompletionRequest{
			Messages: []domain.ChatCompletionMessage{
				{Role: "user", Content: "继续"},
			},
			Stream:    false,
			UserID:    resp1.UserID,
			SessionID: resp1.SessionID,
			RunID:     resp1.RunID, // 传递 RunID，表示继续同一话题
		}
		resp2 := sendChatRequest(t, client, baseURL, reqBody2)
		if resp2.UserID != resp1.UserID {
			t.Errorf("UserID should be consistent, expected %s, got %s", resp1.UserID, resp2.UserID)
		}
		if resp2.SessionID != resp1.SessionID {
			t.Errorf("SessionID should be consistent, expected %s, got %s", resp1.SessionID, resp2.SessionID)
		}
		if resp2.RunID != resp1.RunID {
			t.Errorf("RunID should be consistent (same topic), expected %s, got %s", resp1.RunID, resp2.RunID)
		}
		t.Logf("✅ Turn 2 (same topic): RunID=%s (consistent)", resp2.RunID)

		// 第三条消息 - 开启新话题（不传 RunID，应生成新的）
		time.Sleep(time.Second)
		reqBody3 := domain.ChatCompletionRequest{
			Messages: []domain.ChatCompletionMessage{
				{Role: "user", Content: "新问题"},
			},
			Stream:    false,
			UserID:    resp1.UserID,
			SessionID: resp1.SessionID,
			// 不传 RunID，表示新话题
		}
		resp3 := sendChatRequest(t, client, baseURL, reqBody3)
		if resp3.UserID != resp1.UserID {
			t.Errorf("UserID should be consistent, expected %s, got %s", resp1.UserID, resp3.UserID)
		}
		if resp3.SessionID != resp1.SessionID {
			t.Errorf("SessionID should be consistent, expected %s, got %s", resp1.SessionID, resp3.SessionID)
		}
		if resp3.RunID == resp1.RunID {
			t.Errorf("RunID should be different (new topic), got %s, want != %s", resp3.RunID, resp1.RunID)
		}
		t.Logf("✅ Turn 3 (new topic): RunID=%s (different)", resp3.RunID)
	})
}

// sendChatRequest 发送聊天请求并返回响应
func sendChatRequest(t *testing.T, client *http.Client, baseURL string, reqBody domain.ChatCompletionRequest) *domain.ChatCompletionResponse {
	bodyBytes, _ := json.Marshal(reqBody)
	req, err := http.NewRequest("POST", baseURL+"/v1/chat/completions", bytes.NewReader(bodyBytes))
	if err != nil {
		t.Fatalf("failed to create request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("expected status 200, got %d, body: %s", resp.StatusCode, string(body))
	}

	var chatResp domain.ChatCompletionResponse
	if err := json.NewDecoder(resp.Body).Decode(&chatResp); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	if len(chatResp.Choices) == 0 {
		t.Fatal("expected at least one choice")
	}

	return &chatResp
}

func getEnvOrDefault(key, defaultValue string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultValue
}


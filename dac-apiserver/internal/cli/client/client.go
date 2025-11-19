package client

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net/url"
	"strings"
	"time"

	"github.com/bytedance/sonic"
	"github.com/cloudwego/hertz/pkg/app/client"
	"github.com/cloudwego/hertz/pkg/network/standard"
	"github.com/cloudwego/hertz/pkg/protocol"
	"github.com/cloudwego/hertz/pkg/protocol/consts"

	"github.com/lvyanru/dac-apiserver/internal/cli/types"
)

// APIClient wraps Hertz Client for HTTP communication with API Server
type APIClient struct {
	client *client.Client
	server string
	token  string
}

// NewAPIClient creates a new API client
func NewAPIClient(server, token string) (*APIClient, error) {
	// Normalize server URL
	normalizedServer, err := normalizeServerURL(server)
	if err != nil {
		return nil, fmt.Errorf("invalid server URL: %w", err)
	}

	// Use standard library dialer for streaming support
	// netpoll doesn't support streaming well, causing panics
	c, err := client.NewClient(
		client.WithDialTimeout(10*time.Second),
		client.WithMaxIdleConnDuration(60*time.Second),
		client.WithResponseBodyStream(true),     // Enable streaming response support
		client.WithDialer(standard.NewDialer()), // Use standard library for streaming
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create HTTP client: %w", err)
	}

	return &APIClient{
		client: c,
		server: normalizedServer,
		token:  token,
	}, nil
}

// normalizeServerURL normalizes server URL to ensure it has a scheme and no trailing slash
func normalizeServerURL(server string) (string, error) {
	// Add scheme if missing
	if !strings.Contains(server, "://") {
		server = "http://" + server
	}

	// Parse and validate
	u, err := url.Parse(server)
	if err != nil || u.Host == "" {
		return "", fmt.Errorf("invalid server URL")
	}

	// Return scheme://host (no path, no trailing slash)
	return fmt.Sprintf("%s://%s", u.Scheme, u.Host), nil
}

// Login performs user login
func (c *APIClient) Login(ctx context.Context, username, password string) (*types.APIResponse[types.LoginData], error) {
	// Build request body
	reqBody := types.LoginRequest{
		Username: username,
		Password: password,
	}
	bodyBytes, err := sonic.Marshal(reqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Create request
	req := protocol.AcquireRequest()
	resp := protocol.AcquireResponse()
	defer func() {
		protocol.ReleaseRequest(req)
		protocol.ReleaseResponse(resp)
	}()

	req.SetMethod(consts.MethodPost)
	req.SetRequestURI(c.server + endpointLogin)
	req.Header.SetContentTypeBytes([]byte("application/json"))
	req.SetBody(bodyBytes)

	// Send request
	if err := c.client.Do(ctx, req, resp); err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}

	// Check HTTP status code first
	if resp.StatusCode() != 200 {
		return nil, fmt.Errorf("login failed with HTTP status: %d", resp.StatusCode())
	}

	// Parse response
	var loginResp types.APIResponse[types.LoginData]
	if err := sonic.Unmarshal(resp.Body(), &loginResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return &loginResp, nil
}

// ListAgentContainers lists agent containers in a namespace
// If namespace is empty, lists across all namespaces
func (c *APIClient) ListAgentContainers(ctx context.Context, namespace string) ([]types.AgentContainer, error) {
	req := protocol.AcquireRequest()
	resp := protocol.AcquireResponse()
	defer func() {
		protocol.ReleaseRequest(req)
		protocol.ReleaseResponse(resp)
	}()

	var url string
	if namespace == "" {
		url = c.server + endpointAgentsAll
	} else {
		url = fmt.Sprintf("%s"+endpointAgentsNamespaced, c.server, namespace)
	}

	req.SetMethod(consts.MethodGet)
	req.SetRequestURI(url)
	req.Header.Set("Authorization", "Bearer "+c.token)

	if err := c.client.Do(ctx, req, resp); err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}

	if resp.StatusCode() != 200 {
		return nil, fmt.Errorf("failed to list agents (HTTP %d)", resp.StatusCode())
	}

	var listResp types.APIResponse[types.ListData[types.AgentContainer]]
	if err := sonic.Unmarshal(resp.Body(), &listResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return listResp.Data.Items, nil
}

// ListDataDescriptors lists data descriptors in a namespace
// If namespace is empty, lists across all namespaces
func (c *APIClient) ListDataDescriptors(ctx context.Context, namespace string) ([]types.DataDescriptor, error) {
	req := protocol.AcquireRequest()
	resp := protocol.AcquireResponse()
	defer func() {
		protocol.ReleaseRequest(req)
		protocol.ReleaseResponse(resp)
	}()

	var url string
	if namespace == "" {
		url = c.server + endpointDescriptorsAll
	} else {
		url = fmt.Sprintf("%s"+endpointDescriptorsNamespaced, c.server, namespace)
	}

	req.SetMethod(consts.MethodGet)
	req.SetRequestURI(url)
	req.Header.Set("Authorization", "Bearer "+c.token)

	if err := c.client.Do(ctx, req, resp); err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}

	if resp.StatusCode() != 200 {
		return nil, fmt.Errorf("failed to list descriptors (HTTP %d)", resp.StatusCode())
	}

	var listResp types.APIResponse[types.ListData[types.DataDescriptor]]
	if err := sonic.Unmarshal(resp.Body(), &listResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return listResp.Data.Items, nil
}

// DeleteAgentContainer deletes a DataAgentContainer
func (c *APIClient) DeleteAgentContainer(ctx context.Context, namespace, name string) error {
	url := fmt.Sprintf("%s"+endpointAgentsNamespacedByName, c.server, namespace, name)

	req := &protocol.Request{}
	req.SetMethod("DELETE")
	req.SetRequestURI(url)
	req.Header.Set("Authorization", "Bearer "+c.token)

	resp := &protocol.Response{}
	if err := c.client.Do(ctx, req, resp); err != nil {
		return fmt.Errorf("request failed: %w", err)
	}

	statusCode := resp.StatusCode()
	if statusCode < 200 || statusCode >= 300 {
		body := resp.Body()
		return fmt.Errorf("delete failed with HTTP status: %d, body: %s", statusCode, string(body))
	}

	return nil
}

// DeleteDataDescriptor deletes a DataDescriptor
func (c *APIClient) DeleteDataDescriptor(ctx context.Context, namespace, name string) error {
	url := fmt.Sprintf("%s"+endpointDescriptorsNamespacedByName, c.server, namespace, name)

	req := &protocol.Request{}
	req.SetMethod("DELETE")
	req.SetRequestURI(url)
	req.Header.Set("Authorization", "Bearer "+c.token)

	resp := &protocol.Response{}
	if err := c.client.Do(ctx, req, resp); err != nil {
		return fmt.Errorf("request failed: %w", err)
	}

	statusCode := resp.StatusCode()
	if statusCode < 200 || statusCode >= 300 {
		body := resp.Body()
		return fmt.Errorf("delete failed with HTTP status: %d, body: %s", statusCode, string(body))
	}

	return nil
}

// CreateAgentContainer creates a new DataAgentContainer
func (c *APIClient) CreateAgentContainer(ctx context.Context, req *types.CreateDACRequest) error {
	url := fmt.Sprintf("%s"+endpointAgentsNamespaced, c.server, req.Namespace)

	bodyBytes, err := sonic.Marshal(req)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq := &protocol.Request{}
	httpReq.SetMethod("POST")
	httpReq.SetRequestURI(url)
	httpReq.Header.Set("Authorization", "Bearer "+c.token)
	httpReq.Header.SetContentTypeBytes([]byte("application/json"))
	httpReq.SetBody(bodyBytes)

	resp := &protocol.Response{}
	if err := c.client.Do(ctx, httpReq, resp); err != nil {
		return fmt.Errorf("request failed: %w", err)
	}

	statusCode := resp.StatusCode()
	if statusCode < 200 || statusCode >= 300 {
		body := resp.Body()
		return fmt.Errorf("create failed with HTTP status: %d, body: %s", statusCode, string(body))
	}

	return nil
}

// CreateDataDescriptor creates a new DataDescriptor
func (c *APIClient) CreateDataDescriptor(ctx context.Context, req *types.CreateDDRequest) error {
	url := fmt.Sprintf("%s"+endpointDescriptorsNamespaced, c.server, req.Namespace)

	bodyBytes, err := sonic.Marshal(req)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq := &protocol.Request{}
	httpReq.SetMethod("POST")
	httpReq.SetRequestURI(url)
	httpReq.Header.Set("Authorization", "Bearer "+c.token)
	httpReq.Header.SetContentTypeBytes([]byte("application/json"))
	httpReq.SetBody(bodyBytes)

	resp := &protocol.Response{}
	if err := c.client.Do(ctx, httpReq, resp); err != nil {
		return fmt.Errorf("request failed: %w", err)
	}

	statusCode := resp.StatusCode()
	if statusCode < 200 || statusCode >= 300 {
		body := resp.Body()
		return fmt.Errorf("create failed with HTTP status: %d, body: %s", statusCode, string(body))
	}

	return nil
}

// ChatStreaming sends chat messages and returns streaming response using Hertz's Stream API
func (c *APIClient) ChatStreaming(ctx context.Context, messages []types.ChatMessage, runID string) (<-chan types.ChatStreamChunk, <-chan error, error) {
	if len(messages) == 0 {
		return nil, nil, fmt.Errorf("chat request requires at least one message")
	}

	// Copy messages to avoid data races when caller mutates the slice while streaming
	safeMessages := make([]types.ChatMessage, len(messages))
	copy(safeMessages, messages)

	// Build request body
	reqBody := types.ChatRequest{
		Messages: safeMessages,
		Stream:   true,
		// UserID is not passed here - server extracts it from JWT token
		RunID: runID,
	}

	bodyBytes, err := sonic.Marshal(reqBody)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Create request
	req := protocol.AcquireRequest()
	resp := protocol.AcquireResponse()

	req.SetMethod(consts.MethodPost)
	req.SetRequestURI(c.server + endpointChatCompletions)
	req.Header.SetContentTypeBytes([]byte("application/json"))
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept", "text/event-stream")
	req.SetBody(bodyBytes)

	// Use Do() - Hertz will handle streaming response through BodyStream()
	if err := c.client.Do(ctx, req, resp); err != nil {
		protocol.ReleaseRequest(req)
		protocol.ReleaseResponse(resp)
		return nil, nil, fmt.Errorf("request failed: %w", err)
	}

	// Check status code
	if resp.StatusCode() != 200 {
		statusCode := resp.StatusCode()
		body := resp.Body()
		protocol.ReleaseRequest(req)
		protocol.ReleaseResponse(resp)
		return nil, nil, fmt.Errorf("chat failed with HTTP status: %d, body: %s", statusCode, string(body))
	}

	// Create channels for streaming
	chunkCh := make(chan types.ChatStreamChunk, 10)
	errCh := make(chan error, 1)

	// Start goroutine to read SSE stream in real-time
	go func() {
		defer func() {
			close(chunkCh)
			close(errCh)
			protocol.ReleaseRequest(req)
			protocol.ReleaseResponse(resp)
		}()

		// Use BodyStream() for streaming read
		bodyStream := resp.BodyStream()
		if bodyStream == nil {
			errCh <- fmt.Errorf("body stream is nil")
			return
		}

		// Parse SSE stream line by line as data arrives
		c.parseSSEStreamRealtime(bodyStream, chunkCh, errCh)
	}()

	return chunkCh, errCh, nil
}

// parseSSEStreamRealtime reads SSE stream line by line in real-time using Hertz's BodyStream()
func (c *APIClient) parseSSEStreamRealtime(reader io.Reader, chunkCh chan<- types.ChatStreamChunk, errCh chan<- error) {
	scanner := bufio.NewScanner(reader)

	// Increase buffer size for large SSE messages
	const maxScanTokenSize = 1024 * 1024 // 1MB
	buf := make([]byte, maxScanTokenSize)
	scanner.Buffer(buf, maxScanTokenSize)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		// Skip empty lines or comments
		if line == "" || strings.HasPrefix(line, ":") {
			continue
		}

		// Parse SSE data line
		if strings.HasPrefix(line, "data: ") {
			dataStr := strings.TrimPrefix(line, "data: ")

			// Check for [DONE] marker
			if dataStr == "[DONE]" {
				return
			}

			// Parse JSON chunk
			var chunk types.ChatStreamChunk
			if err := sonic.Unmarshal([]byte(dataStr), &chunk); err != nil {
				errCh <- fmt.Errorf("failed to parse chunk: %w", err)
				return
			}

			// Send chunk immediately (true streaming!)
			select {
			case chunkCh <- chunk:
				// Successfully sent, continue reading next line
			case <-time.After(5 * time.Second):
				errCh <- fmt.Errorf("timeout sending chunk to channel")
				return
			}
		}
	}

	// Check for scanner errors
	if err := scanner.Err(); err != nil {
		// Don't report EOF as error
		if err != io.EOF {
			errCh <- fmt.Errorf("scanner error: %w", err)
		}
	}
}

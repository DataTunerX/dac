package http

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"time"
)

// 配置常量（可从环境变量覆盖）
const (
	defaultCeleryHttpserverBaseURL = "http://celery-httpserver.dac.svc.cluster.local:8000"
	defaultDataServicesBaseURL     = "http://data-services.dac.svc.cluster.local:8000"
	defaultHTTPTimeout             = 30 * time.Second
	defaultMaxRetries              = 3
	defaultRetryDelay              = 1 * time.Second
	envVarCeleryHttpserverBaseURL  = "CELERY_HTTPSERVER_API_BASE_URL"
	envVarDataServiceBaseURL       = "DATA_SERVICES_API_BASE_URL"
	envVarHTTPTimeout              = "API_HTTP_TIMEOUT"
	envVarMaxRetries               = "API_MAX_RETRIES"
	envVarRetryDelay               = "API_RETRY_DELAY"
	triggerPath                    = "/trigger_task"
	statusPathFmt                  = "/task_status/%s"
	createCollection               = "/knowledge_pyramid/create_collection"
	deleteCollection               = "/knowledge_pyramid/delete_collection"
)

// Config 从环境变量读取配置
type Config struct {
	CeleryHttpserverBaseURL string
	DataServicesBaseURL     string
	HTTPTimeout             time.Duration
	MaxRetries              int
	RetryDelay              time.Duration
}

func LoadConfig() Config {
	cfg := Config{
		CeleryHttpserverBaseURL: defaultCeleryHttpserverBaseURL,
		DataServicesBaseURL:     defaultDataServicesBaseURL,
		HTTPTimeout:             defaultHTTPTimeout,
		MaxRetries:              defaultMaxRetries,
		RetryDelay:              defaultRetryDelay,
	}

	if celeryHttpserverURL := os.Getenv(envVarCeleryHttpserverBaseURL); celeryHttpserverURL != "" {
		cfg.CeleryHttpserverBaseURL = celeryHttpserverURL
	}

	if dataServicesURL := os.Getenv(envVarDataServiceBaseURL); dataServicesURL != "" {
		cfg.DataServicesBaseURL = dataServicesURL
	}

	if timeout := os.Getenv(envVarHTTPTimeout); timeout != "" {
		if d, err := time.ParseDuration(timeout); err == nil {
			cfg.HTTPTimeout = d
		}
	}

	if retries := os.Getenv(envVarMaxRetries); retries != "" {
		if n, err := fmt.Sscanf(retries, "%d", &cfg.MaxRetries); n == 1 && err == nil {
			// 解析成功
		}
	}

	if delay := os.Getenv(envVarRetryDelay); delay != "" {
		if d, err := time.ParseDuration(delay); err == nil {
			cfg.RetryDelay = d
		}
	}

	return cfg
}

// API客户端结构体
type APIClient struct {
	cfg    Config
	client *http.Client
}

func NewAPIClient(cfg Config) *APIClient {
	return &APIClient{
		cfg: cfg,
		client: &http.Client{
			Timeout: cfg.HTTPTimeout,
		},
	}
}

// TriggerTaskResponse 触发任务的响应结构
type TriggerTaskResponse struct {
	TaskID string `json:"task_id"`
}

// TaskStatusResponse 查询任务状态的响应结构
type TaskStatusResponse struct {
	TaskID string      `json:"task_id"`
	Status string      `json:"status"`
	Result interface{} `json:"result"` // 使用 interface{} 接收任意类型结果
}

// 在 http/client.go 中修改 doRequestWithRetry 方法
func (c *APIClient) doRequestWithRetry(req *http.Request) (*http.Response, error) {
	var lastErr error
	var body []byte

	// 如果是POST/PUT等有body的请求，先读取body内容
	if req.Method == "POST" || req.Method == "PUT" {
		var err error
		if req.Body != nil {
			body, err = io.ReadAll(req.Body)
			if err != nil {
				return nil, fmt.Errorf("read request body failed: %v", err)
			}
			req.Body.Close()
		}
	}

	for i := 0; i < c.cfg.MaxRetries; i++ {
		if i > 0 {
			time.Sleep(c.cfg.RetryDelay)
		}

		// 对于有body的请求，每次重试都需要重新设置body
		if len(body) > 0 {
			req.Body = io.NopCloser(bytes.NewBuffer(body))
		}

		resp, err := c.client.Do(req)
		if err == nil {
			return resp, nil
		}

		lastErr = err
		if isTimeoutError(err) || isTemporaryError(err) {
			continue
		}
		break
	}

	return nil, fmt.Errorf("after %d retries, last error: %v", c.cfg.MaxRetries, lastErr)
}

func isTimeoutError(err error) bool {
	if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
		return true
	}
	return false
}

func isTemporaryError(err error) bool {
	if netErr, ok := err.(net.Error); ok && netErr.Temporary() {
		return true
	}
	return false
}

// TriggerTask 触发任务（支持任意JSON数据）
func (c *APIClient) TriggerTask(ctx context.Context, data interface{}) (string, error) {
	// 编码任意JSON数据
	jsonData, err := json.Marshal(data)
	if err != nil {
		return "", fmt.Errorf("marshal request data failed: %v", err)
	}

	req, err := http.NewRequestWithContext(
		ctx,
		"POST",
		c.cfg.CeleryHttpserverBaseURL+triggerPath,
		bytes.NewBuffer(jsonData),
	)
	if err != nil {
		return "", fmt.Errorf("create request failed: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.doRequestWithRetry(req)
	if err != nil {
		return "", fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body) // 尝试读取错误响应体
		return "", fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read response failed: %v", err)
	}

	var response TriggerTaskResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return "", fmt.Errorf("unmarshal response failed: %v", err)
	}

	return response.TaskID, nil
}

// GetTaskStatus 查询任务状态（支持任意结果类型）
func (c *APIClient) GetTaskStatus(ctx context.Context, taskID string) (*TaskStatusResponse, error) {
	req, err := http.NewRequestWithContext(
		ctx,
		"GET",
		c.cfg.CeleryHttpserverBaseURL+fmt.Sprintf(statusPathFmt, taskID),
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("create request failed: %v", err)
	}

	resp, err := c.doRequestWithRetry(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body) // 尝试读取错误响应体
		return nil, fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response failed: %v", err)
	}

	var response TaskStatusResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %v", err)
	}

	return &response, nil
}

func main() {
	// 加载配置
	cfg := LoadConfig()
	client := NewAPIClient(cfg)

	// 创建带超时的上下文
	ctx, cancel := context.WithTimeout(context.Background(), cfg.HTTPTimeout)
	defer cancel()

	// 示例1: 发送符合服务端要求的数据结构
	requestData := map[string]interface{}{
		"data": map[string]interface{}{ // 注意这里嵌套了data字段
			"sample": 123,
			"name":   "test",
		},
	}
	taskID, err := client.TriggerTask(ctx, requestData)
	if err != nil {
		fmt.Printf("Failed to trigger task: %v\n", err)
		return
	}

	fmt.Printf("Triggered task with ID: %s\n", taskID)

	// 查询任务状态
	status, err := client.GetTaskStatus(ctx, taskID)
	if err != nil {
		fmt.Printf("Failed to get task status: %v\n", err)
		return
	}
	fmt.Printf("Task status: %+v\n", status)
}

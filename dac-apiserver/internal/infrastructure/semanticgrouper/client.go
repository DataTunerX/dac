package semanticgrouper

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/bytedance/sonic"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type Client struct {
	baseURL string
	http    *http.Client
	logger  *slog.Logger
}

func NewClient(baseURL string, timeout time.Duration, logger *slog.Logger) *Client {
	if logger == nil {
		logger = slog.Default()
	}
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	return &Client{
		baseURL: strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		http:    &http.Client{Timeout: timeout},
		logger:  logger,
	}
}

func (c *Client) AddMember(ctx context.Context, groupID string, req *domain.AddSemanticGroupMemberRequest) (string, error) {
	if groupID == "" {
		return "", domain.NewInvalidInputError("group id is required")
	}
	if req == nil || req.DDNamespace == "" || req.DDName == "" {
		return "", domain.NewInvalidInputError("dd_namespace and dd_name are required")
	}
	payload := map[string]any{
		"group_id": groupID,
		"descriptor": map[string]string{
			"namespace": req.DDNamespace,
			"name":      req.DDName,
		},
	}
	if req.AssociationReason != "" {
		payload["association_reason"] = req.AssociationReason
	}
	return c.submitTask(ctx, "/api/v1/group/members/add", payload)
}

func (c *Client) RemoveMember(ctx context.Context, groupID string, req *domain.RemoveSemanticGroupMemberRequest) (string, error) {
	if groupID == "" {
		return "", domain.NewInvalidInputError("group id is required")
	}
	if req == nil || req.SemanticDomainID == "" {
		return "", domain.NewInvalidInputError("sd_id is required")
	}
	payload := map[string]any{
		"group_id": groupID,
		"sd_id":    req.SemanticDomainID,
	}
	return c.submitTask(ctx, "/api/v1/group/members/remove", payload)
}

func (c *Client) GetTaskStatus(ctx context.Context, taskID string) (*domain.SemanticGrouperTaskStatus, error) {
	if strings.TrimSpace(taskID) == "" {
		return nil, domain.NewInvalidInputError("task_id is required")
	}
	if c.baseURL == "" {
		return nil, domain.NewInternalError(fmt.Errorf("semantic grouper base URL is empty"))
	}

	resp, err := c.getJSON(ctx, fmt.Sprintf("/api/v1/task_status/%s", taskID))
	if err != nil {
		return nil, err
	}

	status, _ := resp["status"].(string)
	out := &domain.SemanticGrouperTaskStatus{
		TaskID: taskID,
		Status: status,
	}

	switch status {
	case "SUCCESS":
		result, err := normalizeTaskResult(resp["result"])
		if err != nil {
			return nil, err
		}
		out.Result = result
	case "FAILURE":
		out.Error = extractTaskError(resp["result"])
		if out.Error == "" {
			out.Error = "semantic grouper task failed"
		}
	}
	return out, nil
}

func (c *Client) submitTask(ctx context.Context, path string, payload map[string]any) (string, error) {
	if c.baseURL == "" {
		return "", domain.NewInternalError(fmt.Errorf("semantic grouper base URL is empty"))
	}
	submit, err := c.postJSON(ctx, path, payload)
	if err != nil {
		return "", err
	}
	taskID, _ := submit["task_id"].(string)
	if taskID == "" {
		return "", domain.NewInternalError(fmt.Errorf("semantic grouper returned no task_id"))
	}
	return taskID, nil
}

func (c *Client) postJSON(ctx context.Context, path string, payload map[string]any) (map[string]any, error) {
	body, err := sonic.Marshal(payload)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, strings.NewReader(string(body)))
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	req.Header.Set("Content-Type", "application/json")
	return c.doJSON(req)
}

func (c *Client) getJSON(ctx context.Context, path string) (map[string]any, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	return c.doJSON(req)
}

func (c *Client) doJSON(req *http.Request) (map[string]any, error) {
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, domain.NewInternalError(fmt.Errorf("semantic grouper HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(raw))))
	}

	var out map[string]any
	if err := sonic.Unmarshal(raw, &out); err != nil {
		return nil, domain.NewInternalError(err)
	}
	return out, nil
}

func normalizeTaskResult(result any) (map[string]any, error) {
	switch v := result.(type) {
	case map[string]any:
		if status, _ := v["status"].(string); status == "error" {
			msg, _ := v["message"].(string)
			if msg == "" {
				msg = "semantic grouper task failed"
			}
			return nil, domain.NewInvalidInputError(msg)
		}
		return v, nil
	case string:
		return map[string]any{"message": v}, nil
	default:
		return map[string]any{"result": result}, nil
	}
}

func extractTaskError(result any) string {
	switch v := result.(type) {
	case map[string]any:
		if msg, ok := v["error"].(string); ok && msg != "" {
			return msg
		}
		if msg, ok := v["message"].(string); ok && msg != "" {
			return msg
		}
	case string:
		return v
	}
	return ""
}

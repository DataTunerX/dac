package agentregistry

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

type RegistryEndpoint struct {
	Name    string
	BaseURL string
}

type Client struct {
	endpoints []RegistryEndpoint
	http      *http.Client
	logger    *slog.Logger
}

func NewClient(endpoints []RegistryEndpoint, timeout time.Duration, logger *slog.Logger) *Client {
	if logger == nil {
		logger = slog.Default()
	}
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &Client{
		endpoints: endpoints,
		http:      &http.Client{Timeout: timeout},
		logger:    logger,
	}
}

type Repository struct {
	client *Client
}

func NewRepository(client *Client) *Repository {
	return &Repository{client: client}
}

func (r *Repository) ListSummaries(ctx context.Context) ([]domain.AgentRegistrySummary, error) {
	out := make([]domain.AgentRegistrySummary, 0, len(r.client.endpoints))
	for _, ep := range r.client.endpoints {
		out = append(out, r.client.summarize(ctx, ep))
	}
	return out, nil
}

func (r *Repository) ListAgents(ctx context.Context, registry string) ([]domain.RegisteredAgentCard, error) {
	ep, ok := r.client.endpointByName(registry)
	if !ok {
		return nil, domain.NewInvalidInputError("registry must be orchestrator-registry or biz-orchestrator-registry")
	}
	agents, err := r.client.fetchAgents(ctx, ep)
	if err != nil {
		return nil, err
	}
	return agents, nil
}

func (c *Client) endpointByName(name string) (RegistryEndpoint, bool) {
	for _, ep := range c.endpoints {
		if ep.Name == name {
			return ep, true
		}
	}
	return RegistryEndpoint{}, false
}

func (c *Client) summarize(ctx context.Context, ep RegistryEndpoint) domain.AgentRegistrySummary {
	summary := domain.AgentRegistrySummary{
		Name:    ep.Name,
		BaseURL: ep.BaseURL,
	}
	agents, err := c.fetchAgents(ctx, ep)
	if err != nil {
		summary.Reachable = false
		summary.Error = err.Error()
		return summary
	}
	summary.Reachable = true
	summary.AgentCount = len(agents)
	return summary
}

func (c *Client) fetchAgents(ctx context.Context, ep RegistryEndpoint) ([]domain.RegisteredAgentCard, error) {
	baseURL := strings.TrimRight(strings.TrimSpace(ep.BaseURL), "/")
	if baseURL == "" {
		return nil, fmt.Errorf("registry base URL is empty for %s", ep.Name)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, baseURL+"/agents", nil)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		msg := strings.TrimSpace(string(body))
		if msg == "" {
			msg = resp.Status
		}
		return nil, fmt.Errorf("registry returned %d: %s", resp.StatusCode, msg)
	}

	var payload struct {
		AgentCards []map[string]any `json:"agent_cards"`
	}
	if err := sonic.Unmarshal(body, &payload); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}

	agents := make([]domain.RegisteredAgentCard, 0, len(payload.AgentCards))
	for _, card := range payload.AgentCards {
		if card == nil {
			continue
		}
		agents = append(agents, domain.RegisteredAgentCard{
			Registry: ep.Name,
			Raw:      card,
		})
	}
	return agents, nil
}

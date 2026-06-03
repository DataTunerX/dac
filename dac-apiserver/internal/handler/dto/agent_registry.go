package dto

import "github.com/lvyanru/dac-apiserver/internal/domain"

type AgentRegistrySummaryResponse struct {
	Name       string `json:"name"`
	BaseURL    string `json:"base_url"`
	AgentCount int    `json:"agent_count"`
	Reachable  bool   `json:"reachable"`
	Error      string `json:"error,omitempty"`
}

type RegisteredAgentCardResponse struct {
	Registry string         `json:"registry"`
	Card     map[string]any `json:"card"`
}

func ToAgentRegistrySummaryResponse(item domain.AgentRegistrySummary) AgentRegistrySummaryResponse {
	return AgentRegistrySummaryResponse{
		Name:       item.Name,
		BaseURL:    item.BaseURL,
		AgentCount: item.AgentCount,
		Reachable:  item.Reachable,
		Error:      item.Error,
	}
}

func ToRegisteredAgentCardResponse(item domain.RegisteredAgentCard) RegisteredAgentCardResponse {
	return RegisteredAgentCardResponse{
		Registry: item.Registry,
		Card:     item.Raw,
	}
}

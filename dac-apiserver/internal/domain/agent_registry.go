package domain

import "context"

const (
	AgentRegistryOrchestrator    = "orchestrator-registry"
	AgentRegistryBizOrchestrator = "biz-orchestrator-registry"
)

var ValidAgentRegistryNames = map[string]struct{}{
	AgentRegistryOrchestrator:    {},
	AgentRegistryBizOrchestrator: {},
}

// AgentRegistrySummary describes one agent registry backend.
type AgentRegistrySummary struct {
	Name       string
	BaseURL    string
	AgentCount int
	Reachable  bool
	Error      string
}

// RegisteredAgentCard is a registered A2A agent card from agent-registry.
type RegisteredAgentCard struct {
	Registry string
	Raw      map[string]any
}

// AgentRegistryRepository reads registered agents from agent-registry services.
type AgentRegistryRepository interface {
	ListSummaries(ctx context.Context) ([]AgentRegistrySummary, error)
	ListAgents(ctx context.Context, registry string) ([]RegisteredAgentCard, error)
}

// AgentRegistryUsecase exposes registered agent cards for observability UI.
type AgentRegistryUsecase interface {
	ListRegistries(ctx context.Context) ([]AgentRegistrySummary, error)
	ListAgents(ctx context.Context, registry string) ([]RegisteredAgentCard, error)
}

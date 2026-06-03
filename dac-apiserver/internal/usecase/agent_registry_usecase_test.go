package usecase_test

import (
	"context"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/usecase"
)

type stubAgentRegistryRepo struct {
	summaries []domain.AgentRegistrySummary
	agents    map[string][]domain.RegisteredAgentCard
}

func (s *stubAgentRegistryRepo) ListSummaries(ctx context.Context) ([]domain.AgentRegistrySummary, error) {
	return s.summaries, nil
}

func (s *stubAgentRegistryRepo) ListAgents(ctx context.Context, registry string) ([]domain.RegisteredAgentCard, error) {
	if _, ok := domain.ValidAgentRegistryNames[registry]; !ok {
		return nil, domain.NewInvalidInputError("invalid registry")
	}
	return s.agents[registry], nil
}

func TestAgentRegistryUsecase_ListAgentsInvalidRegistry(t *testing.T) {
	uc := usecase.NewAgentRegistryUsecase(&stubAgentRegistryRepo{}, nil)
	_, err := uc.ListAgents(context.Background(), "unknown")
	if err == nil {
		t.Fatal("expected error for invalid registry")
	}
}

func TestAgentRegistryUsecase_ListAgents(t *testing.T) {
	repo := &stubAgentRegistryRepo{
		agents: map[string][]domain.RegisteredAgentCard{
			domain.AgentRegistryOrchestrator: {
				{Registry: domain.AgentRegistryOrchestrator, Raw: map[string]any{"name": "DemoAgent"}},
			},
		},
	}
	uc := usecase.NewAgentRegistryUsecase(repo, nil)
	items, err := uc.ListAgents(context.Background(), domain.AgentRegistryOrchestrator)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(items) != 1 || items[0].Raw["name"] != "DemoAgent" {
		t.Fatalf("unexpected items: %#v", items)
	}
}

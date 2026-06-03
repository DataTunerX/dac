package usecase

import (
	"context"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type agentRegistryUsecase struct {
	repo   domain.AgentRegistryRepository
	logger *slog.Logger
}

func NewAgentRegistryUsecase(repo domain.AgentRegistryRepository, logger *slog.Logger) domain.AgentRegistryUsecase {
	return &agentRegistryUsecase{repo: repo, logger: logger}
}

func (u *agentRegistryUsecase) ListRegistries(ctx context.Context) ([]domain.AgentRegistrySummary, error) {
	return u.repo.ListSummaries(ctx)
}

func (u *agentRegistryUsecase) ListAgents(ctx context.Context, registry string) ([]domain.RegisteredAgentCard, error) {
	if _, ok := domain.ValidAgentRegistryNames[registry]; !ok {
		return nil, domain.NewInvalidInputError("registry must be orchestrator-registry or biz-orchestrator-registry")
	}
	return u.repo.ListAgents(ctx, registry)
}

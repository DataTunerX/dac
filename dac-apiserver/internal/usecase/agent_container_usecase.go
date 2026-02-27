package usecase

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// AgentContainerUsecase defines the interface for agent container business logic
type AgentContainerUsecase interface {
	Create(ctx context.Context, req *domain.CreateAgentContainerRequest) (*entity.AgentContainer, error)
	Get(ctx context.Context, namespace, name string) (*entity.AgentContainer, error)
	List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.AgentContainer, error)
	Update(ctx context.Context, namespace, name string, req *domain.UpdateAgentContainerRequest) (*entity.AgentContainer, error)
	Delete(ctx context.Context, namespace, name string) error
}

type agentContainerUsecase struct {
	repo   domain.AgentContainerRepository
	logger *slog.Logger
}

// NewAgentContainerUsecase creates a new agent container usecase
func NewAgentContainerUsecase(repo domain.AgentContainerRepository, logger *slog.Logger) AgentContainerUsecase {
	return &agentContainerUsecase{
		repo:   repo,
		logger: logger,
	}
}

// Create creates a new agent container
func (u *agentContainerUsecase) Create(ctx context.Context, req *domain.CreateAgentContainerRequest) (*entity.AgentContainer, error) {
	// Validate request
	if err := u.validateCreateRequest(req); err != nil {
		return nil, fmt.Errorf("invalid request: %w", err)
	}

	// Default dacType to keep CRD validation happy.
	// execution-engine CRD spec defines `dacType` as required (no omitempty).
	if req.DACType == "" {
		req.DACType = "ds"
	}

	if req.OrchestratorAgentMaxLoops == "" {
		req.OrchestratorAgentMaxLoops = "5" // Default value
	}

	// Build entity
	container := &entity.AgentContainer{
		Name:                      req.Name,
		Namespace:                 req.Namespace,
		Labels:                    req.Labels,
		DACType:                   req.DACType,
		DataPolicy:                req.DataPolicy,
		AgentCard:                 req.AgentCard,
		Model:                     req.Model,
		ExpertAgentMaxSteps:       req.ExpertAgentMaxSteps,
		OrchestratorAgentMaxLoops: req.OrchestratorAgentMaxLoops,
	}

	// Create in repository
	created, err := u.repo.Create(ctx, container)
	if err != nil {
		return nil, fmt.Errorf("failed to create agent container: %w", err)
	}

	return created, nil
}

// Get retrieves an agent container
func (u *agentContainerUsecase) Get(ctx context.Context, namespace, name string) (*entity.AgentContainer, error) {
	container, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get agent container: %w", err)
	}

	return container, nil
}

// List lists agent containers
func (u *agentContainerUsecase) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.AgentContainer, error) {
	containers, err := u.repo.List(ctx, namespace, opts)
	if err != nil {
		return nil, fmt.Errorf("failed to list agent containers: %w", err)
	}

	return containers, nil
}

// Update updates an agent container
func (u *agentContainerUsecase) Update(ctx context.Context, namespace, name string, req *domain.UpdateAgentContainerRequest) (*entity.AgentContainer, error) {
	// Get existing container
	existing, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get existing agent container: %w", err)
	}

	// Update fields
	if req.Labels != nil {
		existing.Labels = req.Labels
	}
	if req.DACType != nil {
		existing.DACType = *req.DACType
	}
	if req.DataPolicy != nil {
		existing.DataPolicy = *req.DataPolicy
	}
	if req.AgentCard != nil {
		existing.AgentCard = *req.AgentCard
	}
	if req.Model != nil {
		existing.Model = *req.Model
	}
	if req.ExpertAgentMaxSteps != nil {
		existing.ExpertAgentMaxSteps = *req.ExpertAgentMaxSteps
	}
	if req.OrchestratorAgentMaxLoops != nil {
		existing.OrchestratorAgentMaxLoops = *req.OrchestratorAgentMaxLoops
	}

	// Update in repository
	updated, err := u.repo.Update(ctx, existing)
	if err != nil {
		return nil, fmt.Errorf("failed to update agent container: %w", err)
	}

	return updated, nil
}

// Delete deletes an agent container
func (u *agentContainerUsecase) Delete(ctx context.Context, namespace, name string) error {
	// Check if exists
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return fmt.Errorf("agent container not found: %w", err)
	}

	// Delete from repository
	if err := u.repo.Delete(ctx, namespace, name); err != nil {
		return fmt.Errorf("failed to delete agent container: %w", err)
	}

	return nil
}

// validateCreateRequest validates the create request
func (u *agentContainerUsecase) validateCreateRequest(req *domain.CreateAgentContainerRequest) error {
	if req.Name == "" {
		return domain.ErrInvalidInput
	}
	if req.Namespace == "" {
		return domain.ErrInvalidInput
	}
	return nil
}

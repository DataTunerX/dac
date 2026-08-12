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
		SkillPolicy:               req.SkillPolicy,
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
	if req.SkillPolicy != nil {
		existing.SkillPolicy = *req.SkillPolicy
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

	// skillPolicy / agentCard constraints by dacType
	if existing.DACType == "skill" {
		if err := validateSkillPolicy(existing.SkillPolicy, existing.AgentCard); err != nil {
			u.logger.Error("skill DAC update validation failed",
				"namespace", namespace,
				"name", name,
				"error", err,
			)
			return nil, fmt.Errorf("invalid request: %w", err)
		}
	} else if existing.DACType == "normal" {
		if err := validateOptionalSkillPolicyRefs(existing.SkillPolicy); err != nil {
			u.logger.Error("normal DAC skillPolicy update validation failed",
				"namespace", namespace,
				"name", name,
				"error", err,
			)
			return nil, fmt.Errorf("invalid request: %w", err)
		}
	} else if existing.DACType == "ds" {
		if err := rejectSkillPolicyForDS(existing.SkillPolicy); err != nil {
			return nil, fmt.Errorf("invalid request: %w", err)
		}
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

	switch req.DACType {
	case "skill":
		if err := validateSkillPolicy(req.SkillPolicy, req.AgentCard); err != nil {
			u.logger.Error("skill DAC create validation failed",
				"name", req.Name,
				"namespace", req.Namespace,
				"error", err,
			)
			return err
		}
	case "normal":
		if err := validateOptionalSkillPolicyRefs(req.SkillPolicy); err != nil {
			u.logger.Error("normal DAC skillPolicy create validation failed",
				"name", req.Name,
				"namespace", req.Namespace,
				"error", err,
			)
			return err
		}
	case "ds", "":
		if err := rejectSkillPolicyForDS(req.SkillPolicy); err != nil {
			return err
		}
	}
	return nil
}

// validateSkillPolicy enforces skillPolicy rules for skill DACs:
// - at least one SkillRef with namespace+name
// - SkillRef.Name unique within the DAC (even across skill-hub namespaces)
// - agentCard.skills must be non-empty and match skillPolicy name set (detail-derived projection)
func validateSkillPolicy(policy entity.SkillPolicy, card entity.AgentCard) error {
	if len(policy.Skills) == 0 {
		return domain.NewInvalidInputError("skillPolicy.skills must not be empty for dacType=skill")
	}
	if err := validateSkillPolicyRefs(policy); err != nil {
		return err
	}
	policyNames := make(map[string]struct{}, len(policy.Skills))
	for _, s := range policy.Skills {
		policyNames[s.Name] = struct{}{}
	}
	if len(card.Skills) == 0 {
		return domain.NewInvalidInputError("agentCard.skills must be derived from skillPolicy (non-empty) for dacType=skill")
	}
	cardNames := make(map[string]struct{}, len(card.Skills))
	for _, s := range card.Skills {
		if s.Name == "" {
			return domain.NewInvalidInputError("agentCard.skills entry requires name")
		}
		cardNames[s.Name] = struct{}{}
	}
	if len(cardNames) != len(policyNames) {
		return domain.NewInvalidInputError("agentCard.skills name set must match skillPolicy.skills")
	}
	for n := range policyNames {
		if _, ok := cardNames[n]; !ok {
			return domain.NewInvalidInputError(fmt.Sprintf("agentCard.skills missing skill %q from skillPolicy", n))
		}
	}
	return nil
}

// validateOptionalSkillPolicyRefs validates skillPolicy for dacType=normal (Semantic Group).
// Empty policy is allowed (image-baked LocalSkill only). Non-empty requires namespace+name and unique names.
// Does not require agentCard.skills alignment (Expert card stays fingerprint-derived).
func validateOptionalSkillPolicyRefs(policy entity.SkillPolicy) error {
	if len(policy.Skills) == 0 {
		return nil
	}
	return validateSkillPolicyRefs(policy)
}

// rejectSkillPolicyForDS rejects non-empty skillPolicy on dacType=ds.
func rejectSkillPolicyForDS(policy entity.SkillPolicy) error {
	if len(policy.Skills) == 0 {
		return nil
	}
	return domain.NewInvalidInputError("skillPolicy must be empty for dacType=ds")
}

// validateSkillPolicyRefs checks namespace+name presence and unique skill names within a DAC.
func validateSkillPolicyRefs(policy entity.SkillPolicy) error {
	seen := make(map[string]struct{}, len(policy.Skills))
	for _, s := range policy.Skills {
		if s.Namespace == "" || s.Name == "" {
			return domain.NewInvalidInputError("skillPolicy skill requires namespace and name")
		}
		if _, ok := seen[s.Name]; ok {
			return domain.NewInvalidInputError(fmt.Sprintf("duplicate skillPolicy skill name %q (must be unique within a DAC)", s.Name))
		}
		seen[s.Name] = struct{}{}
	}
	return nil
}

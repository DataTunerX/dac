package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

type dataDescriptorUsecase struct {
	repo     domain.DataDescriptorRepository
	dsClient domain.DataServicesClient
	logger   *slog.Logger
}

// NewDataDescriptorUsecase creates a new DataDescriptorUsecase
func NewDataDescriptorUsecase(repo domain.DataDescriptorRepository, dsClient domain.DataServicesClient, logger *slog.Logger) domain.DataDescriptorUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &dataDescriptorUsecase{
		repo:     repo,
		dsClient: dsClient,
		logger:   logger,
	}
}

// Create creates a new data descriptor
func (u *dataDescriptorUsecase) Create(ctx context.Context, req *domain.CreateDataDescriptorRequest) (*entity.DataDescriptor, error) {
	// Business logic validation
	if req.Name == "" || req.Namespace == "" {
		return nil, domain.NewInvalidInputError("name and namespace are required")
	}

	// Create entity
	descriptor := &entity.DataDescriptor{
		Name:           req.Name,
		Namespace:      req.Namespace,
		Labels:         req.Labels,
		DescriptorType: req.DescriptorType,
		GPUEnabled:     req.GPUEnabled,
		PDFLoader:      entity.NormalizePDFLoader(req.PDFLoader),
		Sources:        req.Sources,
		CreatedAt:      time.Now(),
		UpdatedAt:      time.Now(),
	}

	return u.repo.Create(ctx, descriptor)
}

// Get gets a data descriptor
func (u *dataDescriptorUsecase) Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error) {
	return u.repo.Get(ctx, namespace, name)
}

// List lists data descriptors
func (u *dataDescriptorUsecase) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error) {
	return u.repo.List(ctx, namespace, opts)
}

// Update updates a data descriptor
func (u *dataDescriptorUsecase) Update(ctx context.Context, namespace, name string, req *domain.UpdateDataDescriptorRequest) (*entity.DataDescriptor, error) {
	// Get existing
	existing, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, err
	}

	// Update fields
	if req.Labels != nil {
		existing.Labels = req.Labels
	}
	if req.DescriptorType != nil && *req.DescriptorType != "" {
		existing.DescriptorType = *req.DescriptorType
	}
	if req.GPUEnabled != nil {
		existing.GPUEnabled = *req.GPUEnabled
	}
	if req.PDFLoader != nil {
		existing.PDFLoader = *req.PDFLoader
	}
	if req.Sources != nil {
		existing.Sources = req.Sources
	}
	existing.UpdatedAt = time.Now()

	return u.repo.Update(ctx, existing)
}

// Delete deletes a data descriptor
func (u *dataDescriptorUsecase) Delete(ctx context.Context, namespace, name string) error {
	return u.repo.Delete(ctx, namespace, name)
}

const annotationSyncRequestedAt = "dac.dac.io/sync-requested-at"

// RequestResync asks execution-engine to re-process a Ready DataDescriptor
// (e.g. after appending mysql/postgres database sources).
func (u *dataDescriptorUsecase) RequestResync(ctx context.Context, namespace, name string) error {
	if _, err := u.repo.Get(ctx, namespace, name); err != nil {
		return err
	}
	return u.repo.PatchAnnotation(ctx, namespace, name, annotationSyncRequestedAt, time.Now().UTC().Format(time.RFC3339))
}

// GetSignatureByDD retrieves the newest signature record for a given data descriptor (if any).
func (u *dataDescriptorUsecase) GetSignatureByDD(ctx context.Context, namespace, name string) (*domain.Signature, error) {
	return u.dsClient.GetSignatureByDD(ctx, namespace, name)
}

// GetSemanticDomainByDD retrieves the newest semantic domain record for a given data descriptor (if any).
func (u *dataDescriptorUsecase) GetSemanticDomainByDD(ctx context.Context, namespace, name string) (*domain.SemanticDomain, error) {
	return u.dsClient.GetSemanticDomainByDD(ctx, namespace, name)
}

// UpdateSemanticDomainAgentCard writes a new agent_card onto the DD's existing semantic domain.
// Other SD fields (semantic_domain text, dd binding, version) are left unchanged.
func (u *dataDescriptorUsecase) UpdateSemanticDomainAgentCard(ctx context.Context, namespace, name, agentCard string) (*domain.SemanticDomain, error) {
	card := strings.TrimSpace(agentCard)
	if card == "" {
		return nil, domain.NewInvalidInputError("agent_card is required")
	}
	var obj map[string]any
	if err := json.Unmarshal([]byte(card), &obj); err != nil || obj == nil {
		return nil, domain.NewInvalidInputError("agent_card 不是合法 JSON")
	}

	sd, err := u.dsClient.GetSemanticDomainByDD(ctx, namespace, name)
	if err != nil {
		return nil, err
	}
	if sd == nil || strings.TrimSpace(sd.SemanticDomainID) == "" {
		return nil, domain.NewNotFoundError("semantic_domain", namespace+"/"+name)
	}

	return u.dsClient.UpdateSemanticDomain(ctx, sd.SemanticDomainID, map[string]any{
		"agent_card": card,
	})
}

// SearchKnowledge searches for knowledge fragments associated with the descriptor.
func (u *dataDescriptorUsecase) SearchKnowledge(ctx context.Context, namespace, name, query string) ([]domain.KnowledgeSearchResult, error) {
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, err
	}
	results, err := u.dsClient.SearchKnowledge(ctx, namespace, name, query)
	if err != nil {
		return nil, fmt.Errorf("failed to search knowledge: %w", err)
	}
	return results, nil
}

// GetAllKnowledge retrieves all knowledge fragments associated with the descriptor.
func (u *dataDescriptorUsecase) GetAllKnowledge(ctx context.Context, namespace, name string) ([]domain.KnowledgeDocument, error) {
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, err
	}
	results, err := u.dsClient.GetAllKnowledge(ctx, namespace, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get all knowledge: %w", err)
	}
	return results, nil
}

// DeleteKnowledge deletes knowledge fragments.
func (u *dataDescriptorUsecase) DeleteKnowledge(ctx context.Context, namespace, name string, docIDs []string) error {
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return err
	}
	if err := u.dsClient.DeleteKnowledge(ctx, namespace, name, docIDs); err != nil {
		return fmt.Errorf("failed to delete knowledge: %w", err)
	}
	return nil
}

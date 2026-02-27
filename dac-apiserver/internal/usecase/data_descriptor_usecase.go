package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/dataservices"
)

type dataDescriptorUsecase struct {
	repo       domain.DataDescriptorRepository
	dsClient   *dataservices.Client // Inject DataServices Client
	logger     *slog.Logger
}

// generateCollectionName matches Python's generate_collection_name(descriptor)
// Format: namespace_name, then replace '-' with '_'
func generateCollectionName(namespace, name string) string {
	collectionName := fmt.Sprintf("%s_%s", namespace, name)
	return strings.ReplaceAll(collectionName, "-", "_")
}

// NewDataDescriptorUsecase creates a new DataDescriptorUsecase
func NewDataDescriptorUsecase(repo domain.DataDescriptorRepository, dsClient *dataservices.Client, logger *slog.Logger) domain.DataDescriptorUsecase {
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

// GetSignatureByDD retrieves the newest signature record for a given data descriptor (if any).
func (u *dataDescriptorUsecase) GetSignatureByDD(ctx context.Context, namespace, name string) (*dataservices.Signature, error) {
	return u.dsClient.GetSignatureByDD(ctx, namespace, name)
}

// GetSemanticDomainByDD retrieves the newest semantic domain record for a given data descriptor (if any).
func (u *dataDescriptorUsecase) GetSemanticDomainByDD(ctx context.Context, namespace, name string) (*dataservices.SemanticDomain, error) {
	return u.dsClient.GetSemanticDomainByDD(ctx, namespace, name)
}

// SearchKnowledge searches for knowledge fragments associated with the descriptor
// Uses the descriptor name as the collection name (convention)
func (u *dataDescriptorUsecase) SearchKnowledge(ctx context.Context, namespace, name, query string) ([]dataservices.KnowledgeSearchResult, error) {
	// 1. Check if descriptor exists (ensure user has access)
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, err
	}

	// 2. Call Data Services
	// Python contract: collection_name = f"{namespace}_{name}".replace("-", "_")
	collectionName := generateCollectionName(namespace, name)
	results, err := u.dsClient.SearchKnowledge(ctx, collectionName, query, 10)
	if err != nil {
		return nil, fmt.Errorf("failed to search knowledge: %w", err)
	}
	
	return results, nil
}

// GetAllKnowledge retrieves all knowledge fragments associated with the descriptor
func (u *dataDescriptorUsecase) GetAllKnowledge(ctx context.Context, namespace, name string) ([]dataservices.KnowledgeDocument, error) {
	// 1. Check if descriptor exists
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, err
	}

	// 2. Call Data Services
	collectionName := generateCollectionName(namespace, name)
	results, err := u.dsClient.GetAllKnowledge(ctx, collectionName)
	if err != nil {
		return nil, fmt.Errorf("failed to get all knowledge: %w", err)
	}
	
	return results, nil
}

// DeleteKnowledge deletes knowledge fragments
func (u *dataDescriptorUsecase) DeleteKnowledge(ctx context.Context, namespace, name string, docIDs []string) error {
	// 1. Check if descriptor exists
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return err
	}

	// 2. Call Data Services
	collectionName := generateCollectionName(namespace, name)
	err = u.dsClient.DeleteKnowledge(ctx, collectionName, docIDs)
	if err != nil {
		return fmt.Errorf("failed to delete knowledge: %w", err)
	}
	
	return nil
}

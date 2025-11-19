package usecase

import (
	"context"
	"fmt"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// DataDescriptorUsecase defines the interface for data descriptor business logic
type DataDescriptorUsecase interface {
	Create(ctx context.Context, req *domain.CreateDataDescriptorRequest) (*entity.DataDescriptor, error)
	Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error)
	List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error)
	Update(ctx context.Context, namespace, name string, req *domain.UpdateDataDescriptorRequest) (*entity.DataDescriptor, error)
	Delete(ctx context.Context, namespace, name string) error
}

type dataDescriptorUsecase struct {
	repo domain.DataDescriptorRepository
}

// NewDataDescriptorUsecase creates a new data descriptor usecase
func NewDataDescriptorUsecase(repo domain.DataDescriptorRepository) DataDescriptorUsecase {
	return &dataDescriptorUsecase{
		repo: repo,
	}
}

// Create creates a new data descriptor
func (u *dataDescriptorUsecase) Create(ctx context.Context, req *domain.CreateDataDescriptorRequest) (*entity.DataDescriptor, error) {
	// Validate request
	if err := u.validateCreateRequest(req); err != nil {
		return nil, fmt.Errorf("invalid request: %w", err)
	}

	// Build entity
	descriptor := &entity.DataDescriptor{
		Name:           req.Name,
		Namespace:      req.Namespace,
		Labels:         req.Labels,
		DescriptorType: req.DescriptorType,
		Sources:        req.Sources,
	}

	// Create in repository
	created, err := u.repo.Create(ctx, descriptor)
	if err != nil {
		return nil, fmt.Errorf("failed to create data descriptor: %w", err)
	}

	return created, nil
}

// Get retrieves a data descriptor
func (u *dataDescriptorUsecase) Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error) {
	descriptor, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get data descriptor: %w", err)
	}

	return descriptor, nil
}

// List lists data descriptors
func (u *dataDescriptorUsecase) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error) {
	descriptors, err := u.repo.List(ctx, namespace, opts)
	if err != nil {
		return nil, fmt.Errorf("failed to list data descriptors: %w", err)
	}

	return descriptors, nil
}

// Update updates a data descriptor
func (u *dataDescriptorUsecase) Update(ctx context.Context, namespace, name string, req *domain.UpdateDataDescriptorRequest) (*entity.DataDescriptor, error) {
	// Get existing descriptor
	existing, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get existing data descriptor: %w", err)
	}

	// Update fields
	if req.Labels != nil {
		existing.Labels = req.Labels
	}
	if req.DescriptorType != nil {
		existing.DescriptorType = *req.DescriptorType
	}
	if req.Sources != nil {
		existing.Sources = req.Sources
	}

	// Update in repository
	updated, err := u.repo.Update(ctx, existing)
	if err != nil {
		return nil, fmt.Errorf("failed to update data descriptor: %w", err)
	}

	return updated, nil
}

// Delete deletes a data descriptor
func (u *dataDescriptorUsecase) Delete(ctx context.Context, namespace, name string) error {
	// Check if exists
	_, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return fmt.Errorf("data descriptor not found: %w", err)
	}

	// Delete from repository
	if err := u.repo.Delete(ctx, namespace, name); err != nil {
		return fmt.Errorf("failed to delete data descriptor: %w", err)
	}

	return nil
}

// validateCreateRequest validates the create request
func (u *dataDescriptorUsecase) validateCreateRequest(req *domain.CreateDataDescriptorRequest) error {
	if req.Name == "" {
		return domain.ErrInvalidInput
	}
	if req.Namespace == "" {
		return domain.ErrInvalidInput
	}
	if req.DescriptorType == "" {
		return domain.ErrInvalidInput
	}
	return nil
}

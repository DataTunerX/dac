package mocks

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// MockDataDescriptorRepository is a mock implementation of domain.DataDescriptorRepository
type MockDataDescriptorRepository struct {
	CreateFunc       func(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error)
	GetFunc          func(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error)
	ListFunc         func(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error)
	UpdateFunc       func(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error)
	UpdateStatusFunc func(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error)
	DeleteFunc       func(ctx context.Context, namespace, name string) error
}

// Create mocks the Create method
func (m *MockDataDescriptorRepository) Create(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error) {
	if m.CreateFunc != nil {
		return m.CreateFunc(ctx, descriptor)
	}
	return descriptor, nil
}

// Get mocks the Get method
func (m *MockDataDescriptorRepository) Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error) {
	if m.GetFunc != nil {
		return m.GetFunc(ctx, namespace, name)
	}
	return &entity.DataDescriptor{
		Name:      name,
		Namespace: namespace,
	}, nil
}

// List mocks the List method
func (m *MockDataDescriptorRepository) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error) {
	if m.ListFunc != nil {
		return m.ListFunc(ctx, namespace, opts)
	}
	return []*entity.DataDescriptor{}, nil
}

// Update mocks the Update method
func (m *MockDataDescriptorRepository) Update(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error) {
	if m.UpdateFunc != nil {
		return m.UpdateFunc(ctx, descriptor)
	}
	return descriptor, nil
}

// UpdateStatus mocks the UpdateStatus method
func (m *MockDataDescriptorRepository) UpdateStatus(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error) {
	if m.UpdateStatusFunc != nil {
		return m.UpdateStatusFunc(ctx, descriptor)
	}
	return descriptor, nil
}

// Delete mocks the Delete method
func (m *MockDataDescriptorRepository) Delete(ctx context.Context, namespace, name string) error {
	if m.DeleteFunc != nil {
		return m.DeleteFunc(ctx, namespace, name)
	}
	return nil
}

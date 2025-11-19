package mocks

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// MockDataDescriptorUsecase is a mock implementation of usecase.DataDescriptorUsecase
type MockDataDescriptorUsecase struct {
	CreateFunc func(ctx context.Context, req *domain.CreateDataDescriptorRequest) (*entity.DataDescriptor, error)
	GetFunc    func(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error)
	ListFunc   func(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error)
	UpdateFunc func(ctx context.Context, namespace, name string, req *domain.UpdateDataDescriptorRequest) (*entity.DataDescriptor, error)
	DeleteFunc func(ctx context.Context, namespace, name string) error
}

// Create mocks the Create method
func (m *MockDataDescriptorUsecase) Create(ctx context.Context, req *domain.CreateDataDescriptorRequest) (*entity.DataDescriptor, error) {
	if m.CreateFunc != nil {
		return m.CreateFunc(ctx, req)
	}
	return &entity.DataDescriptor{
		Name:      req.Name,
		Namespace: req.Namespace,
	}, nil
}

// Get mocks the Get method
func (m *MockDataDescriptorUsecase) Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error) {
	if m.GetFunc != nil {
		return m.GetFunc(ctx, namespace, name)
	}
	return &entity.DataDescriptor{
		Name:      name,
		Namespace: namespace,
	}, nil
}

// List mocks the List method
func (m *MockDataDescriptorUsecase) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error) {
	if m.ListFunc != nil {
		return m.ListFunc(ctx, namespace, opts)
	}
	return []*entity.DataDescriptor{}, nil
}

// Update mocks the Update method
func (m *MockDataDescriptorUsecase) Update(ctx context.Context, namespace, name string, req *domain.UpdateDataDescriptorRequest) (*entity.DataDescriptor, error) {
	if m.UpdateFunc != nil {
		return m.UpdateFunc(ctx, namespace, name, req)
	}
	return &entity.DataDescriptor{
		Name:      name,
		Namespace: namespace,
	}, nil
}

// Delete mocks the Delete method
func (m *MockDataDescriptorUsecase) Delete(ctx context.Context, namespace, name string) error {
	if m.DeleteFunc != nil {
		return m.DeleteFunc(ctx, namespace, name)
	}
	return nil
}

package mocks

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// MockAgentContainerRepository is a mock implementation of domain.AgentContainerRepository
type MockAgentContainerRepository struct {
	CreateFunc       func(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error)
	GetFunc          func(ctx context.Context, namespace, name string) (*entity.AgentContainer, error)
	ListFunc         func(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.AgentContainer, error)
	UpdateFunc       func(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error)
	UpdateStatusFunc func(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error)
	DeleteFunc       func(ctx context.Context, namespace, name string) error
}

// Create mocks the Create method
func (m *MockAgentContainerRepository) Create(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error) {
	if m.CreateFunc != nil {
		return m.CreateFunc(ctx, container)
	}
	return container, nil
}

// Get mocks the Get method
func (m *MockAgentContainerRepository) Get(ctx context.Context, namespace, name string) (*entity.AgentContainer, error) {
	if m.GetFunc != nil {
		return m.GetFunc(ctx, namespace, name)
	}
	return &entity.AgentContainer{
		Name:      name,
		Namespace: namespace,
	}, nil
}

// List mocks the List method
func (m *MockAgentContainerRepository) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.AgentContainer, error) {
	if m.ListFunc != nil {
		return m.ListFunc(ctx, namespace, opts)
	}
	return []*entity.AgentContainer{}, nil
}

// Update mocks the Update method
func (m *MockAgentContainerRepository) Update(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error) {
	if m.UpdateFunc != nil {
		return m.UpdateFunc(ctx, container)
	}
	return container, nil
}

// UpdateStatus mocks the UpdateStatus method
func (m *MockAgentContainerRepository) UpdateStatus(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error) {
	if m.UpdateStatusFunc != nil {
		return m.UpdateStatusFunc(ctx, container)
	}
	return container, nil
}

// Delete mocks the Delete method
func (m *MockAgentContainerRepository) Delete(ctx context.Context, namespace, name string) error {
	if m.DeleteFunc != nil {
		return m.DeleteFunc(ctx, namespace, name)
	}
	return nil
}

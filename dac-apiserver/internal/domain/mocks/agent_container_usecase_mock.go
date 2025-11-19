package mocks

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// MockAgentContainerUsecase is a mock implementation of usecase.AgentContainerUsecase
type MockAgentContainerUsecase struct {
	CreateFunc func(ctx context.Context, req *domain.CreateAgentContainerRequest) (*entity.AgentContainer, error)
	GetFunc    func(ctx context.Context, namespace, name string) (*entity.AgentContainer, error)
	ListFunc   func(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.AgentContainer, error)
	UpdateFunc func(ctx context.Context, namespace, name string, req *domain.UpdateAgentContainerRequest) (*entity.AgentContainer, error)
	DeleteFunc func(ctx context.Context, namespace, name string) error
}

// Create mocks the Create method
func (m *MockAgentContainerUsecase) Create(ctx context.Context, req *domain.CreateAgentContainerRequest) (*entity.AgentContainer, error) {
	if m.CreateFunc != nil {
		return m.CreateFunc(ctx, req)
	}
	return &entity.AgentContainer{
		Name:      req.Name,
		Namespace: req.Namespace,
	}, nil
}

// Get mocks the Get method
func (m *MockAgentContainerUsecase) Get(ctx context.Context, namespace, name string) (*entity.AgentContainer, error) {
	if m.GetFunc != nil {
		return m.GetFunc(ctx, namespace, name)
	}
	return &entity.AgentContainer{
		Name:      name,
		Namespace: namespace,
	}, nil
}

// List mocks the List method
func (m *MockAgentContainerUsecase) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.AgentContainer, error) {
	if m.ListFunc != nil {
		return m.ListFunc(ctx, namespace, opts)
	}
	return []*entity.AgentContainer{}, nil
}

// Update mocks the Update method
func (m *MockAgentContainerUsecase) Update(ctx context.Context, namespace, name string, req *domain.UpdateAgentContainerRequest) (*entity.AgentContainer, error) {
	if m.UpdateFunc != nil {
		return m.UpdateFunc(ctx, namespace, name, req)
	}
	return &entity.AgentContainer{
		Name:      name,
		Namespace: namespace,
	}, nil
}

// Delete mocks the Delete method
func (m *MockAgentContainerUsecase) Delete(ctx context.Context, namespace, name string) error {
	if m.DeleteFunc != nil {
		return m.DeleteFunc(ctx, namespace, name)
	}
	return nil
}

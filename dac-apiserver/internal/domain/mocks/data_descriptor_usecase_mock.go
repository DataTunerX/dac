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
	UpdateFunc        func(ctx context.Context, namespace, name string, req *domain.UpdateDataDescriptorRequest) (*entity.DataDescriptor, error)
	DeleteFunc        func(ctx context.Context, namespace, name string) error
	RequestResyncFunc func(ctx context.Context, namespace, name string) error

	GetSignatureByDDFunc      func(ctx context.Context, namespace, name string) (*domain.Signature, error)
	GetSemanticDomainByDDFunc func(ctx context.Context, namespace, name string) (*domain.SemanticDomain, error)
	SearchKnowledgeFunc       func(ctx context.Context, namespace, name, query string) ([]domain.KnowledgeSearchResult, error)
	GetAllKnowledgeFunc       func(ctx context.Context, namespace, name string) ([]domain.KnowledgeDocument, error)
	DeleteKnowledgeFunc       func(ctx context.Context, namespace, name string, docIDs []string) error
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

// RequestResync mocks the RequestResync method
func (m *MockDataDescriptorUsecase) RequestResync(ctx context.Context, namespace, name string) error {
	if m.RequestResyncFunc != nil {
		return m.RequestResyncFunc(ctx, namespace, name)
	}
	return nil
}

// GetSignatureByDD mocks the GetSignatureByDD method
func (m *MockDataDescriptorUsecase) GetSignatureByDD(ctx context.Context, namespace, name string) (*domain.Signature, error) {
	if m.GetSignatureByDDFunc != nil {
		return m.GetSignatureByDDFunc(ctx, namespace, name)
	}
	return nil, nil
}

// GetSemanticDomainByDD mocks the GetSemanticDomainByDD method
func (m *MockDataDescriptorUsecase) GetSemanticDomainByDD(ctx context.Context, namespace, name string) (*domain.SemanticDomain, error) {
	if m.GetSemanticDomainByDDFunc != nil {
		return m.GetSemanticDomainByDDFunc(ctx, namespace, name)
	}
	return nil, nil
}

// SearchKnowledge mocks the SearchKnowledge method
func (m *MockDataDescriptorUsecase) SearchKnowledge(ctx context.Context, namespace, name, query string) ([]domain.KnowledgeSearchResult, error) {
	if m.SearchKnowledgeFunc != nil {
		return m.SearchKnowledgeFunc(ctx, namespace, name, query)
	}
	return nil, nil
}

// GetAllKnowledge mocks the GetAllKnowledge method
func (m *MockDataDescriptorUsecase) GetAllKnowledge(ctx context.Context, namespace, name string) ([]domain.KnowledgeDocument, error) {
	if m.GetAllKnowledgeFunc != nil {
		return m.GetAllKnowledgeFunc(ctx, namespace, name)
	}
	return nil, nil
}

// DeleteKnowledge mocks the DeleteKnowledge method
func (m *MockDataDescriptorUsecase) DeleteKnowledge(ctx context.Context, namespace, name string, docIDs []string) error {
	if m.DeleteKnowledgeFunc != nil {
		return m.DeleteKnowledgeFunc(ctx, namespace, name, docIDs)
	}
	return nil
}

// Ensure MockDataDescriptorUsecase implements domain.DataDescriptorUsecase.
var _ domain.DataDescriptorUsecase = (*MockDataDescriptorUsecase)(nil)

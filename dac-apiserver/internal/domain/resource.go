package domain

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// ResourceType represents the type of custom resource
type ResourceType string

const (
	ResourceTypeAgentContainer ResourceType = "dataagentcontainer"
	ResourceTypeDescriptor     ResourceType = "datadescriptor"
)

// AgentContainerRepository defines the interface for agent container data access
type AgentContainerRepository interface {
	Create(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error)
	Get(ctx context.Context, namespace, name string) (*entity.AgentContainer, error)
	List(ctx context.Context, namespace string, opts ListOptions) ([]*entity.AgentContainer, error)
	Update(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error)
	UpdateStatus(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error)
	Delete(ctx context.Context, namespace, name string) error
}

// DataDescriptorRepository defines the interface for data descriptor data access
type DataDescriptorRepository interface {
	Create(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error)
	Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error)
	List(ctx context.Context, namespace string, opts ListOptions) ([]*entity.DataDescriptor, error)
	Update(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error)
	UpdateStatus(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error)
	Delete(ctx context.Context, namespace, name string) error
}

// ListOptions defines options for listing resources
type ListOptions struct {
	AllNamespaces bool // List resources across all namespaces (ignore namespace parameter)
	LabelSelector string
	FieldSelector string
	Limit         int64
	Continue      string
}

// CreateAgentContainerRequest represents a request to create an agent container
type CreateAgentContainerRequest struct {
	Namespace           string
	Name                string
	Labels              map[string]string
	DataPolicy          entity.DataPolicy
	AgentCard           entity.AgentCard
	Model               entity.ModelSpec
	ExpertAgentMaxSteps string
}

// UpdateAgentContainerRequest represents a request to update an agent container
type UpdateAgentContainerRequest struct {
	Labels              map[string]string
	DataPolicy          *entity.DataPolicy
	AgentCard           *entity.AgentCard
	Model               *entity.ModelSpec
	ExpertAgentMaxSteps *string
}

// CreateDataDescriptorRequest represents a request to create a data descriptor
type CreateDataDescriptorRequest struct {
	Namespace      string
	Name           string
	Labels         map[string]string
	DescriptorType string
	Sources        []entity.DataSource
}

// UpdateDataDescriptorRequest represents a request to update a data descriptor
type UpdateDataDescriptorRequest struct {
	Labels         map[string]string
	DescriptorType *string
	Sources        []entity.DataSource
}

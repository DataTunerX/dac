package domain

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/dataservices"
)

// AgentContainerUsecase defines agent container operations.
type AgentContainerUsecase interface {
	Create(ctx context.Context, req *CreateAgentContainerRequest) (*entity.AgentContainer, error)
	Get(ctx context.Context, namespace, name string) (*entity.AgentContainer, error)
	List(ctx context.Context, namespace string, opts ListOptions) ([]*entity.AgentContainer, error)
	Update(ctx context.Context, namespace, name string, req *UpdateAgentContainerRequest) (*entity.AgentContainer, error)
	Delete(ctx context.Context, namespace, name string) error
}

// DataDescriptorUsecase defines data descriptor operations.
type DataDescriptorUsecase interface {
	Create(ctx context.Context, req *CreateDataDescriptorRequest) (*entity.DataDescriptor, error)
	Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error)
	List(ctx context.Context, namespace string, opts ListOptions) ([]*entity.DataDescriptor, error)
	Update(ctx context.Context, namespace, name string, req *UpdateDataDescriptorRequest) (*entity.DataDescriptor, error)
	Delete(ctx context.Context, namespace, name string) error

	// Data Services integrations
	GetSignatureByDD(ctx context.Context, namespace, name string) (*dataservices.Signature, error)
	GetSemanticDomainByDD(ctx context.Context, namespace, name string) (*dataservices.SemanticDomain, error)
	SearchKnowledge(ctx context.Context, namespace, name, query string) ([]dataservices.KnowledgeSearchResult, error)
	GetAllKnowledge(ctx context.Context, namespace, name string) ([]dataservices.KnowledgeDocument, error)
	DeleteKnowledge(ctx context.Context, namespace, name string, docIDs []string) error
}

// SemanticGroupUsecase defines semantic group operations backed by data-services.
type SemanticGroupUsecase interface {
	Create(ctx context.Context, req *CreateSemanticGroupRequest) (*dataservices.SemanticGroup, error)
	BatchCreate(ctx context.Context, req []CreateSemanticGroupRequest) (int, error)
	Get(ctx context.Context, id string) (*dataservices.SemanticGroup, error)
	List(ctx context.Context, limit, offset int) ([]dataservices.SemanticGroup, int, error)
	Update(ctx context.Context, id string, req *UpdateSemanticGroupRequest) (*dataservices.SemanticGroup, error)
	Delete(ctx context.Context, id string) error
	Exists(ctx context.Context, id string) (bool, error)
	Count(ctx context.Context) (int, error)
}

// DDGroupRelationUsecase defines DD<->semantic-group relation operations backed by data-services.
type DDGroupRelationUsecase interface {
	Create(ctx context.Context, req *CreateDDGroupRelationRequest) (*dataservices.DDGroupRelation, error)
	BatchCreate(ctx context.Context, req []CreateDDGroupRelationRequest) (int, error)
	ListByGroup(ctx context.Context, groupID string) ([]dataservices.DDGroupRelation, int, error)
	ListBySemanticDomain(ctx context.Context, semanticDomainID string) ([]dataservices.DDGroupRelation, int, error)
	DeleteByID(ctx context.Context, id int64) error
	DeleteByGroup(ctx context.Context, groupID string) error
	DeleteBySemanticDomain(ctx context.Context, semanticDomainID string) error
}

// SemanticDomainUsecase provides semantic domain read operations backed by data-services.
type SemanticDomainUsecase interface {
	Create(ctx context.Context, req *CreateSemanticDomainRequest) (*dataservices.SemanticDomain, error)
	BatchCreate(ctx context.Context, req []CreateSemanticDomainRequest) (int, error)
	Get(ctx context.Context, id string) (*dataservices.SemanticDomain, error)
	SearchByDD(ctx context.Context, req *SearchSemanticDomainByDDRequest) ([]dataservices.SemanticDomain, int, error)
	Update(ctx context.Context, id string, req *UpdateSemanticDomainRequest) (*dataservices.SemanticDomain, error)
	Delete(ctx context.Context, id string) error
	DeleteByDDInfo(ctx context.Context, ddNamespace, ddName string) error
	Exists(ctx context.Context, id string) (bool, error)
	ExistsByDDInfo(ctx context.Context, ddNamespace, ddName string) (bool, error)
	Count(ctx context.Context) (int, error)
}

// KnowledgeGraphUsecase defines knowledge graph operations backed by data-services.
// The response shape varies by query type, so we return a generic map.
type KnowledgeGraphUsecase interface {
	AddWithSource(ctx context.Context, req *AddKnowledgeGraphWithSourceRequest) (map[string]any, error)
	SearchWithSource(ctx context.Context, req *SearchKnowledgeGraphWithSourceRequest) (map[string]any, error)
	GetGraphBySource(ctx context.Context, req *GetKnowledgeGraphBySourceRequest) (map[string]any, error)
	DeleteWithSource(ctx context.Context, req *DeleteKnowledgeGraphWithSourceRequest) (map[string]any, error)
}

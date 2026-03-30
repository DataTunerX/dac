package domain

import "context"

// DataServicesClient is the domain interface for data-services backend.
// Implemented by infrastructure (e.g. HTTP client adapter); usecases depend only on this interface.
type DataServicesClient interface {
	// Run history (chat)
	GetRunHistory(ctx context.Context, userID, runID string) ([]HistoryRecord, error)

	// Signature & semantic domain (data descriptor)
	GetSignatureByDD(ctx context.Context, namespace, name string) (*Signature, error)
	GetSemanticDomainByDD(ctx context.Context, namespace, name string) (*SemanticDomain, error)
	SearchKnowledge(ctx context.Context, namespace, name, query string) ([]KnowledgeSearchResult, error)
	GetAllKnowledge(ctx context.Context, namespace, name string) ([]KnowledgeDocument, error)
	DeleteKnowledge(ctx context.Context, namespace, name string, docIDs []string) error

	// Semantic group
	CreateSemanticGroup(ctx context.Context, req map[string]any) (*SemanticGroup, error)
	BatchCreateSemanticGroups(ctx context.Context, req []map[string]any) (int, error)
	GetSemanticGroup(ctx context.Context, id string) (*SemanticGroup, error)
	GetSemanticGroupWithMembers(ctx context.Context, id string) (*SemanticGroupWithMembers, error)
	ListSemanticGroups(ctx context.Context, page, pageSize int) ([]SemanticGroup, int, error)
	ListSemanticGroupRoots(ctx context.Context) ([]SemanticGroup, int, error)
	UpdateSemanticGroup(ctx context.Context, id string, req map[string]any) (*SemanticGroup, error)
	DeleteSemanticGroup(ctx context.Context, id string) error
	SemanticGroupExists(ctx context.Context, id string) (bool, error)
	SemanticGroupCount(ctx context.Context) (int, error)

	// DD group relation
	CreateDDGroupRelation(ctx context.Context, req map[string]any) (*DDGroupRelation, error)
	BatchCreateDDGroupRelations(ctx context.Context, req []map[string]any) (int, error)
	ListDDGroupRelationsByGroup(ctx context.Context, groupID string) ([]DDGroupRelation, int, error)
	ListDDGroupRelationsBySD(ctx context.Context, sdID string) ([]DDGroupRelation, int, error)
	DeleteDDGroupRelationByID(ctx context.Context, id int64) error
	DeleteDDGroupRelationsByGroup(ctx context.Context, groupID string) error
	DeleteDDGroupRelationsBySD(ctx context.Context, sdID string) error

	// Semantic domain
	GetSemanticDomain(ctx context.Context, id string) (*SemanticDomain, error)
	CreateSemanticDomain(ctx context.Context, req map[string]any) (*SemanticDomain, error)
	BatchCreateSemanticDomains(ctx context.Context, req []map[string]any) (int, error)
	SearchSemanticDomainsByDD(ctx context.Context, namespace, name string) ([]SemanticDomain, int, error)
	UpdateSemanticDomain(ctx context.Context, id string, req map[string]any) (*SemanticDomain, error)
	DeleteSemanticDomain(ctx context.Context, id string) error
	DeleteSemanticDomainByDDInfo(ctx context.Context, ddNamespace, ddName string) error
	SemanticDomainExists(ctx context.Context, id string) (bool, error)
	SemanticDomainExistsByDDInfo(ctx context.Context, ddNamespace, ddName string) (bool, error)
	SemanticDomainCount(ctx context.Context) (int, error)

	// Knowledge graph (passthrough map)
	KnowledgeGraphAddWithSource(ctx context.Context, req map[string]any) (map[string]any, error)
	KnowledgeGraphSearchWithSource(ctx context.Context, req map[string]any) (map[string]any, error)
	KnowledgeGraphGetGraphBySource(ctx context.Context, req map[string]any) (map[string]any, error)
	KnowledgeGraphDeleteWithSource(ctx context.Context, req map[string]any) (map[string]any, error)
}

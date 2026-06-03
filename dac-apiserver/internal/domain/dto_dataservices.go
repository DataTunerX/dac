package domain

// Data-services response DTOs (domain-owned; infrastructure adapters convert to/from these).
// Keeps domain layer independent of internal/infrastructure/dataservices.

// Signature is the signature record for a data descriptor (data-services response shape).
// JSON tags match data-services API for handler passthrough.
type Signature struct {
	SigID         string                 `json:"sig_id"`
	SigType       string                 `json:"sig_type"`
	DiscoveryMode string                 `json:"discovery_mode"`
	Fingerprint   string                 `json:"fingerprint"`
	LocationInfo  map[string]interface{} `json:"location_info"`
	Metadata      map[string]interface{} `json:"metadata_content"`
	DDNamespace   string                 `json:"dd_namespace"`
	DDName        string                 `json:"dd_name"`
	CreatedAt     string                 `json:"created_at"`
	UpdatedAt     string                 `json:"updated_at"`
}

// SemanticDomain is a semantic domain record (data-services response shape).
type SemanticDomain struct {
	SemanticDomainID string `json:"semantic_domain_id"`
	SemanticDomain   string `json:"semantic_domain"`
	AgentCard        string `json:"agent_card"`
	DDNamespace      string `json:"dd_namespace"`
	DDName           string `json:"dd_name"`
	CreatedAt        string `json:"created_at"`
	UpdatedAt        string `json:"updated_at"`
}

// SemanticGroup is a semantic group record (data-services response shape).
type SemanticGroup struct {
	ID          string  `json:"id"`
	GroupName   string  `json:"group_name"`
	Description string  `json:"description"`
	AgentCard   string  `json:"agent_card"`
	Version     string  `json:"version"`
	ParentID    *string `json:"parent_id,omitempty"`
	CreatedAt   string  `json:"created_at"`
}

// SemanticGroupMemberDetail is one member: relation + full semantic domain (from with_members).
type SemanticGroupMemberDetail struct {
	Relation       DDGroupRelation `json:"relation"`
	SemanticDomain *SemanticDomain `json:"semantic_domain"`
}

// SemanticGroupInfo is summary of a child group (from with_members child_groups).
type SemanticGroupInfo struct {
	ID          string  `json:"id"`
	GroupName   string  `json:"group_name"`
	Description string  `json:"description"`
	AgentCard   string  `json:"agent_card"`
}

// SemanticGroupWithMembers is the full response of GetSemanticGroupWithMembers.
type SemanticGroupWithMembers struct {
	Group       SemanticGroup                `json:"group"`
	Members     []SemanticGroupMemberDetail  `json:"members"`
	ChildGroups []SemanticGroupInfo          `json:"child_groups"`
}

// DDGroupRelation is a DD–semantic-group relation (data-services response shape).
type DDGroupRelation struct {
	ID                int64  `json:"id"`
	SemanticDomainID  string `json:"sd_id"`
	GroupID           string `json:"group_id"`
	AssociationReason string `json:"association_reason"`
}

// KnowledgeSearchResult is a single knowledge search hit (data-services response shape).
type KnowledgeSearchResult struct {
	Content     string                 `json:"content"`
	Metadata    map[string]interface{} `json:"metadata"`
	Score       float64                `json:"score"`
	SearchType  string                 `json:"search_type"`
	HybridScore float64                `json:"hybrid_score,omitempty"`
}

// KnowledgeDocument is a knowledge document (data-services response shape).
type KnowledgeDocument struct {
	PageContent string                 `json:"page_content"`
	Vector      []float64              `json:"vector,omitempty"`
	Metadata    map[string]interface{} `json:"metadata"`
	Provider    string                 `json:"provider,omitempty"`
	Children    any                    `json:"children,omitempty"`
}

// VectorDocumentInput is a document payload for data-services vector add_documents.
type VectorDocumentInput struct {
	PageContent string
	Metadata    map[string]any
}

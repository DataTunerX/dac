package dataservices

import "fmt"

// HistoryRecord matches data-services history record response.
// (Separate from domain.HistoryRecord to keep this package self-contained.)
type HistoryRecord struct {
	HID       string                   `json:"hid"`
	UserID    string                   `json:"user_id"`
	AgentID   string                   `json:"agent_id"`
	RunID     string                   `json:"run_id"`
	Messages  []map[string]interface{} `json:"messages"`
	CreatedAt string                   `json:"created_at"`
	UpdatedAt string                   `json:"updated_at"`
}

// Signature matches data-services signature record response.
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

// SemanticDomain matches data-services semantic domain record response.
// agent_card is stored as a string (often JSON string) by convention.
type SemanticDomain struct {
	SemanticDomainID string `json:"semantic_domain_id"`
	SemanticDomain   string `json:"semantic_domain"`
	AgentCard        string `json:"agent_card"`
	DDNamespace      string `json:"dd_namespace"`
	DDName           string `json:"dd_name"`
	CreatedAt        string `json:"created_at"`
	UpdatedAt        string `json:"updated_at"`
}

// SemanticGroup matches data-services semantic group record response.
type SemanticGroup struct {
	ID          string `json:"id"`
	GroupName   string `json:"group_name"`
	Description string `json:"description"`
	AgentCard   string `json:"agent_card"`
	Version     string `json:"version"`
	CreatedAt   string `json:"created_at"`
}

// DDGroupRelation matches data-services dd_group_relations response.
type DDGroupRelation struct {
	ID                int64  `json:"id"`
	SemanticDomainID  string `json:"sd_id"`
	GroupID           string `json:"group_id"`
	AssociationReason string `json:"association_reason"`
}

// KnowledgeSearchResult matches knowledge_pyramid vector_results entries.
type KnowledgeSearchResult struct {
	Content    string                 `json:"content"`
	Metadata   map[string]interface{} `json:"metadata"`
	Score      float64                `json:"score"`
	SearchType string                 `json:"search_type"`
	HybridScore float64               `json:"hybrid_score,omitempty"`
}

// KnowledgeDocument matches knowledge_pyramid get_all vector_result entries.
// It is a direct mapping of data-services vector_sdk.Document schema.
type KnowledgeDocument struct {
	PageContent string                 `json:"page_content"`
	Vector      []float64              `json:"vector,omitempty"`
	Metadata    map[string]interface{} `json:"metadata"`
	Provider    string                 `json:"provider,omitempty"`
	Children    any                    `json:"children,omitempty"`
}

// HTTPError represents a non-2xx response from data-services.
type HTTPError struct {
	StatusCode int
	Body       string
}

func (e *HTTPError) Error() string {
	return fmt.Sprintf("data services http %d: %s", e.StatusCode, e.Body)
}

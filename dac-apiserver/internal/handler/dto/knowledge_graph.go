package dto

// DTOs for knowledge_graph endpoints (data-services).

type KnowledgeGraphNode struct {
	ID         string         `json:"id" validate:"required"`
	Name       string         `json:"name,omitempty"`
	Labels     []string       `json:"labels,omitempty"`
	Properties map[string]any `json:"properties,omitempty"`
}

type KnowledgeGraphRelationship struct {
	Start      string         `json:"start" validate:"required"`
	End        string         `json:"end" validate:"required"`
	Type       string         `json:"type" validate:"required"`
	Properties map[string]any `json:"properties,omitempty"`
}

type AddKnowledgeGraphWithSourceRequest struct {
	Source        string                       `json:"source" validate:"required"`
	ClearExisting bool                         `json:"clear_existing,omitempty"`
	Nodes         []KnowledgeGraphNode         `json:"nodes,omitempty"`
	Relationships []KnowledgeGraphRelationship `json:"relationships,omitempty"`
}

type SearchKnowledgeGraphWithSourceRequest struct {
	Source           string `json:"source" validate:"required"`
	NodeID           string `json:"node_id,omitempty"`
	Label            string `json:"label,omitempty"`
	PropertyName     string `json:"property_name,omitempty"`
	PropertyValue    string `json:"property_value,omitempty"`
	RelationshipType string `json:"relationship_type,omitempty"`

	QueryText            string `json:"query_text,omitempty"`
	TopK                 int    `json:"top_k,omitempty"`
	IncludeRelationships bool   `json:"include_relationships,omitempty"`
	RelationshipDepth    int    `json:"relationship_depth,omitempty"`
	ReturnSVOOnly        bool   `json:"return_svo_only,omitempty"`

	Limit int `json:"limit,omitempty"`
}

type DeleteKnowledgeGraphWithSourceRequest struct {
	Source string `json:"source" validate:"required"`
}

type GetKnowledgeGraphBySourceRequest struct {
	Source    string `json:"source" validate:"required"`
	NodeLimit int    `json:"node_limit,omitempty"`
	RelLimit  int    `json:"rel_limit,omitempty"`
}

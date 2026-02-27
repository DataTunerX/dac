package domain

// KnowledgeGraphNode represents a node payload for data-services knowledge_graph.
// Keep it in domain to avoid leaking transport-layer tags into usecases.
type KnowledgeGraphNode struct {
	ID         string
	Name       string
	Labels     []string
	Properties map[string]any
}

// KnowledgeGraphRelationship represents an edge payload for data-services knowledge_graph.
type KnowledgeGraphRelationship struct {
	Start      string
	End        string
	Type       string
	Properties map[string]any
}

type AddKnowledgeGraphWithSourceRequest struct {
	Source        string
	ClearExisting bool
	Nodes         []KnowledgeGraphNode
	Relationships []KnowledgeGraphRelationship
}

type SearchKnowledgeGraphWithSourceRequest struct {
	Source string
	// filters
	NodeID           string
	Label            string
	PropertyName     string
	PropertyValue    string
	RelationshipType string
	// vector search
	QueryText            string
	TopK                 int
	IncludeRelationships bool
	RelationshipDepth    int
	ReturnSVOOnly        bool
	// paging
	Limit int
}

type DeleteKnowledgeGraphWithSourceRequest struct {
	Source string
}

type GetKnowledgeGraphBySourceRequest struct {
	Source    string
	NodeLimit int
	RelLimit  int
}

package domain

// CreateSemanticGroupRequest is the apiserver request to create a semantic group.
type CreateSemanticGroupRequest struct {
	GroupName   string
	Description string
	AgentCard   string
	Version     string
}

// UpdateSemanticGroupRequest is the apiserver request to update a semantic group.
// All fields are optional; when nil, the field is not updated.
type UpdateSemanticGroupRequest struct {
	GroupName   *string
	Description *string
	AgentCard   *string
	Version     *string
}

// CreateDDGroupRelationRequest creates a relation between semantic domain and group.
type CreateDDGroupRelationRequest struct {
	SemanticDomainID  string
	GroupID           string
	AssociationReason string
}


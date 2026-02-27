package domain

// CreateSemanticDomainRequest is the apiserver request to create a semantic domain.
type CreateSemanticDomainRequest struct {
	SemanticDomain string
	AgentCard      string
	DDNamespace    string
	DDName         string
}

// UpdateSemanticDomainRequest is the apiserver request to update a semantic domain.
// All fields are optional; when nil, the field is not updated.
type UpdateSemanticDomainRequest struct {
	SemanticDomain *string
	AgentCard      *string
	DDNamespace    *string
	DDName         *string
}

type SearchSemanticDomainByDDRequest struct {
	DDNamespace string
	DDName      string
}

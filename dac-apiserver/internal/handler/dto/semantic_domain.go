package dto

type CreateSemanticDomainRequest struct {
	SemanticDomain string `json:"semantic_domain" validate:"required"`
	AgentCard      string `json:"agent_card"`
	DDNamespace    string `json:"dd_namespace" validate:"required"`
	DDName         string `json:"dd_name" validate:"required"`
}

type UpdateSemanticDomainRequest struct {
	SemanticDomain *string `json:"semantic_domain"`
	AgentCard      *string `json:"agent_card"`
	DDNamespace    *string `json:"dd_namespace"`
	DDName         *string `json:"dd_name"`
}

type SearchSemanticDomainByDDRequest struct {
	DDNamespace string `json:"dd_namespace" validate:"required"`
	DDName      string `json:"dd_name" validate:"required"`
}

package dto

import "github.com/lvyanru/dac-apiserver/internal/infrastructure/dataservices"

type CreateSemanticGroupRequest struct {
	GroupName   string `json:"group_name" validate:"required"`
	Description string `json:"description"`
	AgentCard   string `json:"agent_card"`
	Version     string `json:"version"`
}

type UpdateSemanticGroupRequest struct {
	GroupName   *string `json:"group_name"`
	Description *string `json:"description"`
	AgentCard   *string `json:"agent_card"`
	Version     *string `json:"version"`
}

type SemanticGroupResponse struct {
	ID          string `json:"id"`
	GroupName   string `json:"group_name"`
	Description string `json:"description"`
	AgentCard   string `json:"agent_card"`
	Version     string `json:"version"`
	CreatedAt   string `json:"created_at"`
}

func ToSemanticGroupResponse(g *dataservices.SemanticGroup) *SemanticGroupResponse {
	if g == nil {
		return nil
	}
	return &SemanticGroupResponse{
		ID:          g.ID,
		GroupName:   g.GroupName,
		Description: g.Description,
		AgentCard:   g.AgentCard,
		Version:     g.Version,
		CreatedAt:   g.CreatedAt,
	}
}

type CreateDDGroupRelationRequest struct {
	SemanticDomainID  string `json:"sd_id" validate:"required"`
	GroupID           string `json:"group_id" validate:"required"`
	AssociationReason string `json:"association_reason"`
}

type DDGroupRelationResponse struct {
	ID                int64  `json:"id"`
	SemanticDomainID  string `json:"sd_id"`
	GroupID           string `json:"group_id"`
	AssociationReason string `json:"association_reason"`
}

func ToDDGroupRelationResponse(r *dataservices.DDGroupRelation) *DDGroupRelationResponse {
	if r == nil {
		return nil
	}
	return &DDGroupRelationResponse{
		ID:                r.ID,
		SemanticDomainID:  r.SemanticDomainID,
		GroupID:           r.GroupID,
		AssociationReason: r.AssociationReason,
	}
}

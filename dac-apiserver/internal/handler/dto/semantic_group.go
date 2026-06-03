package dto

import "github.com/lvyanru/dac-apiserver/internal/domain"

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

type AddSemanticGroupMemberRequest struct {
	DDNamespace       string `json:"dd_namespace" validate:"required"`
	DDName            string `json:"dd_name" validate:"required"`
	AssociationReason string `json:"association_reason"`
}

type RemoveSemanticGroupMemberRequest struct {
	SemanticDomainID string `json:"sd_id" validate:"required"`
}

type SemanticGroupMemberTaskSubmitResponse struct {
	TaskID string `json:"task_id"`
}

type SemanticGroupMemberTaskStatusResponse struct {
	TaskID string         `json:"task_id"`
	Status string         `json:"status"`
	Result map[string]any `json:"result,omitempty"`
	Error  string         `json:"error,omitempty"`
}

func ToSemanticGroupMemberTaskStatusResponse(s *domain.SemanticGrouperTaskStatus) *SemanticGroupMemberTaskStatusResponse {
	if s == nil {
		return nil
	}
	return &SemanticGroupMemberTaskStatusResponse{
		TaskID: s.TaskID,
		Status: s.Status,
		Result: s.Result,
		Error:  s.Error,
	}
}

type SemanticGroupResponse struct {
	ID          string  `json:"id"`
	GroupName   string  `json:"group_name"`
	Description string  `json:"description"`
	AgentCard   string  `json:"agent_card"`
	Version     string  `json:"version"`
	ParentID    *string `json:"parent_id,omitempty"`
	CreatedAt   string  `json:"created_at"`
}

// SemanticGroupMemberDetailResponse is one member (relation + semantic domain) for with-members API.
type SemanticGroupMemberDetailResponse struct {
	Relation       DDGroupRelationResponse  `json:"relation"`
	SemanticDomain *SemanticDomainResponse  `json:"semantic_domain"`
}

// SemanticGroupInfoResponse is child group summary for with-members API.
type SemanticGroupInfoResponse struct {
	ID          string `json:"id"`
	GroupName   string `json:"group_name"`
	Description string `json:"description"`
	AgentCard   string `json:"agent_card"`
}

// SemanticDomainResponse is minimal semantic domain for API response (dd_namespace, dd_name, etc.).
type SemanticDomainResponse struct {
	SemanticDomainID string `json:"semantic_domain_id"`
	SemanticDomain   string `json:"semantic_domain"`
	AgentCard        string `json:"agent_card"`
	DDNamespace      string `json:"dd_namespace"`
	DDName           string `json:"dd_name"`
	CreatedAt        string `json:"created_at"`
	UpdatedAt        string `json:"updated_at"`
}

// SemanticGroupWithMembersResponse is the response of GET /semantic-groups/:id/with-members.
type SemanticGroupWithMembersResponse struct {
	Group       SemanticGroupResponse              `json:"group"`
	Members     []SemanticGroupMemberDetailResponse `json:"members"`
	ChildGroups []SemanticGroupInfoResponse        `json:"child_groups"`
}

func ToSemanticGroupResponse(g *domain.SemanticGroup) *SemanticGroupResponse {
	if g == nil {
		return nil
	}
	resp := &SemanticGroupResponse{
		ID:          g.ID,
		GroupName:   g.GroupName,
		Description: g.Description,
		AgentCard:   g.AgentCard,
		Version:     g.Version,
		CreatedAt:   g.CreatedAt,
	}
	if g.ParentID != nil {
		resp.ParentID = g.ParentID
	}
	return resp
}

func ToSemanticGroupWithMembersResponse(w *domain.SemanticGroupWithMembers) *SemanticGroupWithMembersResponse {
	if w == nil {
		return nil
	}
	resp := &SemanticGroupWithMembersResponse{
		Group:       *ToSemanticGroupResponse(&w.Group),
		Members:     make([]SemanticGroupMemberDetailResponse, len(w.Members)),
		ChildGroups: make([]SemanticGroupInfoResponse, len(w.ChildGroups)),
	}
	for i := range w.Members {
		m := &w.Members[i]
		resp.Members[i] = SemanticGroupMemberDetailResponse{
			Relation:       *ToDDGroupRelationResponse(&m.Relation),
			SemanticDomain: toSemanticDomainResponse(m.SemanticDomain),
		}
	}
	for i := range w.ChildGroups {
		c := &w.ChildGroups[i]
		resp.ChildGroups[i] = SemanticGroupInfoResponse{
			ID:          c.ID,
			GroupName:   c.GroupName,
			Description: c.Description,
			AgentCard:   c.AgentCard,
		}
	}
	return resp
}

func toSemanticDomainResponse(s *domain.SemanticDomain) *SemanticDomainResponse {
	if s == nil {
		return nil
	}
	return &SemanticDomainResponse{
		SemanticDomainID: s.SemanticDomainID,
		SemanticDomain:   s.SemanticDomain,
		AgentCard:        s.AgentCard,
		DDNamespace:      s.DDNamespace,
		DDName:           s.DDName,
		CreatedAt:        s.CreatedAt,
		UpdatedAt:        s.UpdatedAt,
	}
}

type DDGroupRelationResponse struct {
	ID                int64  `json:"id"`
	SemanticDomainID  string `json:"sd_id"`
	GroupID           string `json:"group_id"`
	AssociationReason string `json:"association_reason"`
}

func ToDDGroupRelationResponse(r *domain.DDGroupRelation) *DDGroupRelationResponse {
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

package dto

import (
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// CreateAgentContainerRequest represents the HTTP request for creating agent container
type CreateAgentContainerRequest struct {
	Name                string            `json:"name" binding:"required"`
	Namespace           string            `json:"namespace" binding:"required"`
	Labels              map[string]string `json:"labels,omitempty"`
	DataPolicy          entity.DataPolicy `json:"dataPolicy" binding:"required"`
	AgentCard           entity.AgentCard  `json:"agentCard" binding:"required"`
	Model               entity.ModelSpec  `json:"model" binding:"required"`
	ExpertAgentMaxSteps string            `json:"expertAgentMaxSteps,omitempty"`
}

// UpdateAgentContainerRequest represents the HTTP update request
type UpdateAgentContainerRequest struct {
	Labels              map[string]string  `json:"labels,omitempty"`
	DataPolicy          *entity.DataPolicy `json:"dataPolicy,omitempty"`
	AgentCard           *entity.AgentCard  `json:"agentCard,omitempty"`
	Model               *entity.ModelSpec  `json:"model,omitempty"`
	ExpertAgentMaxSteps *string            `json:"expertAgentMaxSteps,omitempty"`
}

// AgentContainerResponse represents the HTTP response for agent container
type AgentContainerResponse struct {
	Name                  string                         `json:"name"`
	Namespace             string                         `json:"namespace"`
	Labels                map[string]string              `json:"labels,omitempty"`
	DataPolicy            DataPolicyResponse             `json:"data_policy"`
	AgentCard             AgentCardResponse              `json:"agent_card"`
	Model                 ModelSpecResponse              `json:"model"`
	ExpertAgentMaxSteps   string                         `json:"expert_agent_max_steps,omitempty"`
	ActiveDataDescriptors []ActiveDataDescriptorResponse `json:"active_data_descriptors,omitempty"`
	Endpoint              *EndpointResponse              `json:"endpoint,omitempty"`
	Conditions            []ConditionResponse            `json:"conditions,omitempty"`
	CreatedAt             string                         `json:"created_at"`
	UpdatedAt             string                         `json:"updated_at"`
}

type DataPolicyResponse struct {
	SourceNameSelector []string `json:"source_name_selector"`
}

type AgentCardResponse struct {
	Name        string               `json:"name"`
	Description string               `json:"description"`
	Skills      []AgentSkillResponse `json:"skills"`
}

type AgentSkillResponse struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Tags        []string `json:"tags"`
	Examples    []string `json:"examples"`
}

type ModelSpecResponse struct {
	Embedding  string `json:"embedding"`
	ExpertLLM  string `json:"expert_llm"`
	PlannerLLM string `json:"planner_llm"`
}

type ActiveDataDescriptorResponse struct {
	Name       string `json:"name"`
	Namespace  string `json:"namespace"`
	LastSynced string `json:"last_synced"`
}

type EndpointResponse struct {
	Address  string `json:"address"`
	Port     int32  `json:"port"`
	Protocol string `json:"protocol"`
}

type ConditionResponse struct {
	Type               string `json:"type"`
	Status             string `json:"status"`
	LastTransitionTime string `json:"last_transition_time"`
	Reason             string `json:"reason"`
	Message            string `json:"message"`
}

// ToAgentContainerResponse converts entity to response DTO
func ToAgentContainerResponse(container *entity.AgentContainer) AgentContainerResponse {
	resp := AgentContainerResponse{
		Name:                container.Name,
		Namespace:           container.Namespace,
		Labels:              container.Labels,
		ExpertAgentMaxSteps: container.ExpertAgentMaxSteps,
		CreatedAt:           container.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
		UpdatedAt:           container.UpdatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}

	// DataPolicy
	resp.DataPolicy = DataPolicyResponse{
		SourceNameSelector: container.DataPolicy.SourceNameSelector,
	}

	// AgentCard
	skills := make([]AgentSkillResponse, len(container.AgentCard.Skills))
	for i, skill := range container.AgentCard.Skills {
		skills[i] = AgentSkillResponse{
			ID:          skill.ID,
			Name:        skill.Name,
			Description: skill.Description,
			Tags:        skill.Tags,
			Examples:    skill.Examples,
		}
	}
	resp.AgentCard = AgentCardResponse{
		Name:        container.AgentCard.Name,
		Description: container.AgentCard.Description,
		Skills:      skills,
	}

	// Model
	resp.Model = ModelSpecResponse{
		Embedding:  container.Model.Embedding,
		ExpertLLM:  container.Model.ExpertLLM,
		PlannerLLM: container.Model.PlannerLLM,
	}

	// ActiveDataDescriptors
	if len(container.ActiveDataDescriptors) > 0 {
		resp.ActiveDataDescriptors = make([]ActiveDataDescriptorResponse, len(container.ActiveDataDescriptors))
		for i, dd := range container.ActiveDataDescriptors {
			resp.ActiveDataDescriptors[i] = ActiveDataDescriptorResponse{
				Name:       dd.Name,
				Namespace:  dd.Namespace,
				LastSynced: dd.LastSynced,
			}
		}
	}

	// Endpoint
	if container.Endpoint != nil {
		resp.Endpoint = &EndpointResponse{
			Address:  container.Endpoint.Address,
			Port:     container.Endpoint.Port,
			Protocol: container.Endpoint.Protocol,
		}
	}

	// Conditions
	if len(container.Conditions) > 0 {
		resp.Conditions = make([]ConditionResponse, len(container.Conditions))
		for i, cond := range container.Conditions {
			resp.Conditions[i] = ConditionResponse{
				Type:               cond.Type,
				Status:             cond.Status,
				LastTransitionTime: cond.LastTransitionTime.Format("2006-01-02T15:04:05Z07:00"),
				Reason:             cond.Reason,
				Message:            cond.Message,
			}
		}
	}

	return resp
}

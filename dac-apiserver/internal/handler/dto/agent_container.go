package dto

import (
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

type DataPolicyDTO struct {
	DataSourceType     string   `json:"dataSourceType,omitempty"`
	SemanticGroupID    string   `json:"semanticGroupID,omitempty"`
	SourceNameSelector []string `json:"sourceNameSelector,omitempty"`
}

type AgentSkillDTO struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Tags        []string `json:"tags,omitempty"`
	Examples    []string `json:"examples,omitempty"`
}

type AgentCardDTO struct {
	Name        string          `json:"name" binding:"required"`
	Description string          `json:"description" binding:"required"`
	Skills      []AgentSkillDTO `json:"skills,omitempty"`
}

type ModelSpecDTO struct {
	Embedding  string `json:"embedding,omitempty"`
	ExpertLLM  string `json:"expertLLM" binding:"required"`
	PlannerLLM string `json:"plannerLLM" binding:"required"`
}

// CreateAgentContainerRequest represents the HTTP request for creating agent container
type CreateAgentContainerRequest struct {
	Name                string            `json:"name" binding:"required"`
	Labels              map[string]string `json:"labels,omitempty"`
	DACType             string            `json:"dacType,omitempty"`
	DataPolicy          DataPolicyDTO     `json:"dataPolicy" binding:"required"`
	AgentCard           AgentCardDTO      `json:"agentCard" binding:"required"`
	Model               ModelSpecDTO      `json:"model" binding:"required"`
	ExpertAgentMaxSteps       string            `json:"expertAgentMaxSteps,omitempty"`
	OrchestratorAgentMaxLoops string            `json:"orchestratorAgentMaxLoops,omitempty"`
}

// UpdateAgentContainerRequest represents the HTTP update request
type UpdateAgentContainerRequest struct {
	Labels                    map[string]string  `json:"labels,omitempty"`
	DACType                   *string            `json:"dacType,omitempty"`
	DataPolicy                *DataPolicyDTO     `json:"dataPolicy,omitempty"`
	AgentCard                 *AgentCardDTO      `json:"agentCard,omitempty"`
	Model                     *ModelSpecDTO      `json:"model,omitempty"`
	ExpertAgentMaxSteps       *string            `json:"expertAgentMaxSteps,omitempty"`
	OrchestratorAgentMaxLoops *string            `json:"orchestratorAgentMaxLoops,omitempty"`
}

// AgentContainerResponse represents the HTTP response for agent container
type AgentContainerResponse struct {
	Name                      string                         `json:"name"`
	Namespace                 string                         `json:"namespace"`
	Labels                    map[string]string              `json:"labels,omitempty"`
	DACType                   string                         `json:"dacType,omitempty"`
	DataPolicy                DataPolicyResponse             `json:"dataPolicy"`
	AgentCard                 AgentCardResponse              `json:"agentCard"`
	Model                     ModelSpecResponse              `json:"model"`
	ExpertAgentMaxSteps       string                         `json:"expertAgentMaxSteps,omitempty"`
	OrchestratorAgentMaxLoops string                         `json:"orchestratorAgentMaxLoops,omitempty"`
	ActiveDataDescriptors     []ActiveDataDescriptorResponse `json:"activeDataDescriptors,omitempty"`
	Endpoint                  *EndpointResponse              `json:"endpoint,omitempty"`
	Conditions                []ConditionResponse            `json:"conditions,omitempty"`
	CreatedAt                 string                         `json:"createdAt"`
	UpdatedAt                 string                         `json:"updatedAt"`
}

type DataPolicyResponse struct {
	DataSourceType     string   `json:"dataSourceType,omitempty"`
	SemanticGroupID    string   `json:"semanticGroupID,omitempty"`
	SourceNameSelector []string `json:"sourceNameSelector,omitempty"`
}

type AgentCardResponse struct {
	Name        string               `json:"name"`
	Description string               `json:"description"`
	Skills      []AgentSkillResponse `json:"skills,omitempty"`
}

type AgentSkillResponse struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Tags        []string `json:"tags,omitempty"`
	Examples    []string `json:"examples,omitempty"`
}

type ModelSpecResponse struct {
	Embedding  string `json:"embedding,omitempty"`
	ExpertLLM  string `json:"expertLLM"`
	PlannerLLM string `json:"plannerLLM"`
}

type ActiveDataDescriptorResponse struct {
	Name       string `json:"name"`
	Namespace  string `json:"namespace"`
	LastSynced string `json:"lastSynced"`
}

type EndpointResponse struct {
	Address  string `json:"address"`
	Port     int32  `json:"port"`
	Protocol string `json:"protocol"`
}

type ConditionResponse struct {
	Type               string `json:"type"`
	Status             string `json:"status"`
	LastTransitionTime string `json:"lastTransitionTime"`
	Reason             string `json:"reason,omitempty"`
	Message            string `json:"message,omitempty"`
}

// ToAgentContainerResponse converts entity to response DTO
func ToAgentContainerResponse(container *entity.AgentContainer) AgentContainerResponse {
	resp := AgentContainerResponse{
		Name:                container.Name,
		Namespace:           container.Namespace,
		Labels:                    container.Labels,
		DACType:                   container.DACType,
		ExpertAgentMaxSteps:       container.ExpertAgentMaxSteps,
		OrchestratorAgentMaxLoops: container.OrchestratorAgentMaxLoops,
		CreatedAt:                 container.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
		UpdatedAt:           container.UpdatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}

	// DataPolicy
	resp.DataPolicy = DataPolicyResponse{
		DataSourceType:     container.DataPolicy.DataSourceType,
		SemanticGroupID:    container.DataPolicy.SemanticGroupID,
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
			lastTransition := ""
			if !cond.LastTransitionTime.IsZero() {
				lastTransition = cond.LastTransitionTime.Format(time.RFC3339)
			}
			resp.Conditions[i] = ConditionResponse{
				Type:               cond.Type,
				Status:             cond.Status,
				LastTransitionTime: lastTransition,
				Reason:             cond.Reason,
				Message:            cond.Message,
			}
		}
	}

	return resp
}

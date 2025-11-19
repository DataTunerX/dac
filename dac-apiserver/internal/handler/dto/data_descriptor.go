package dto

import (
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// CreateDataDescriptorRequest represents the HTTP request for creating data descriptor
type CreateDataDescriptorRequest struct {
	Name           string              `json:"name" binding:"required"`
	Namespace      string              `json:"namespace" binding:"required"`
	Labels         map[string]string   `json:"labels,omitempty"`
	DescriptorType string              `json:"descriptorType" binding:"required"`
	Sources        []entity.DataSource `json:"sources" binding:"required"`
}

// UpdateDataDescriptorRequest represents the HTTP update request
type UpdateDataDescriptorRequest struct {
	Labels         map[string]string   `json:"labels,omitempty"`
	DescriptorType *string             `json:"descriptorType,omitempty"`
	Sources        []entity.DataSource `json:"sources,omitempty"`
}

// DataDescriptorResponse represents the HTTP response for data descriptor
type DataDescriptorResponse struct {
	Name           string                    `json:"name"`
	Namespace      string                    `json:"namespace"`
	Labels         map[string]string         `json:"labels,omitempty"`
	DescriptorType string                    `json:"descriptor_type"`
	Sources        []DataSourceResponse      `json:"sources"`
	SourceStatuses []SourceStatusResponse    `json:"source_statuses,omitempty"`
	ConsumedBy     []ObjectReferenceResponse `json:"consumed_by,omitempty"`
	OverallPhase   string                    `json:"overall_phase,omitempty"`
	Conditions     []ConditionResponse       `json:"conditions,omitempty"`
	CreatedAt      string                    `json:"created_at"`
	UpdatedAt      string                    `json:"updated_at"`
}

type DataSourceResponse struct {
	Type           string                   `json:"type"`
	Name           string                   `json:"name"`
	Metadata       map[string]string        `json:"metadata,omitempty"`
	Extract        *ExtractConfigResponse   `json:"extract,omitempty"`
	Prompts        *PromptsConfigResponse   `json:"prompts,omitempty"`
	Processing     ProcessingConfigResponse `json:"processing"`
	Classification []ClassificationResponse `json:"classification,omitempty"`
}

type ExtractConfigResponse struct {
	Tables []string `json:"tables,omitempty"`
	Querys []string `json:"querys,omitempty"`
}

type PromptsConfigResponse struct {
	ConfigMapName string `json:"config_map_name"`
}

type ProcessingConfigResponse struct {
	Cleaning []CleaningRuleResponse `json:"cleaning,omitempty"`
}

type CleaningRuleResponse struct {
	Rule   string            `json:"rule"`
	Params map[string]string `json:"params,omitempty"`
}

type ClassificationResponse struct {
	Domain      string                `json:"domain"`
	Category    string                `json:"category"`
	Subcategory string                `json:"subcategory"`
	Tags        []map[string][]string `json:"tags,omitempty"`
}

type SourceStatusResponse struct {
	Name         string `json:"name"`
	Phase        string `json:"phase"`
	LastSyncTime string `json:"last_sync_time"`
	Records      int64  `json:"records"`
	TaskID       string `json:"task_id"`
}

type ObjectReferenceResponse struct {
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
}

// ToDataDescriptorResponse converts entity to response DTO
func ToDataDescriptorResponse(descriptor *entity.DataDescriptor) DataDescriptorResponse {
	resp := DataDescriptorResponse{
		Name:           descriptor.Name,
		Namespace:      descriptor.Namespace,
		Labels:         descriptor.Labels,
		DescriptorType: descriptor.DescriptorType,
		OverallPhase:   descriptor.OverallPhase,
		CreatedAt:      descriptor.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
		UpdatedAt:      descriptor.UpdatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}

	// Sources
	resp.Sources = make([]DataSourceResponse, len(descriptor.Sources))
	for i, src := range descriptor.Sources {
		srcResp := DataSourceResponse{
			Type:     src.Type,
			Name:     src.Name,
			Metadata: src.Metadata,
		}

		if src.Extract != nil {
			srcResp.Extract = &ExtractConfigResponse{
				Tables: src.Extract.Tables,
				Querys: src.Extract.Querys,
			}
		}

		if src.Prompts != nil {
			srcResp.Prompts = &PromptsConfigResponse{
				ConfigMapName: src.Prompts.ConfigMapName,
			}
		}

		srcResp.Processing = ProcessingConfigResponse{
			Cleaning: make([]CleaningRuleResponse, len(src.Processing.Cleaning)),
		}
		for j, rule := range src.Processing.Cleaning {
			srcResp.Processing.Cleaning[j] = CleaningRuleResponse{
				Rule:   rule.Rule,
				Params: rule.Params,
			}
		}

		srcResp.Classification = make([]ClassificationResponse, len(src.Classification))
		for j, cls := range src.Classification {
			srcResp.Classification[j] = ClassificationResponse{
				Domain:      cls.Domain,
				Category:    cls.Category,
				Subcategory: cls.Subcategory,
				Tags:        cls.Tags,
			}
		}

		resp.Sources[i] = srcResp
	}

	// SourceStatuses
	if len(descriptor.SourceStatuses) > 0 {
		resp.SourceStatuses = make([]SourceStatusResponse, len(descriptor.SourceStatuses))
		for i, status := range descriptor.SourceStatuses {
			resp.SourceStatuses[i] = SourceStatusResponse{
				Name:         status.Name,
				Phase:        status.Phase,
				LastSyncTime: status.LastSyncTime.Format("2006-01-02T15:04:05Z07:00"),
				Records:      status.Records,
				TaskID:       status.TaskID,
			}
		}
	}

	// ConsumedBy
	if len(descriptor.ConsumedBy) > 0 {
		resp.ConsumedBy = make([]ObjectReferenceResponse, len(descriptor.ConsumedBy))
		for i, ref := range descriptor.ConsumedBy {
			resp.ConsumedBy[i] = ObjectReferenceResponse{
				Name:      ref.Name,
				Namespace: ref.Namespace,
			}
		}
	}

	// Conditions
	if len(descriptor.Conditions) > 0 {
		resp.Conditions = make([]ConditionResponse, len(descriptor.Conditions))
		for i, cond := range descriptor.Conditions {
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

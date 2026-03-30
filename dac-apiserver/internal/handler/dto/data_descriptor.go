package dto

import (
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// CreateDataDescriptorRequest defines the request to create a data descriptor.
// DescriptorType must be one of: structured-mysql, structured-postgres, unstructured, code (aligned with execution-engine).
type CreateDataDescriptorRequest struct {
	Name           string              `json:"name" validate:"required"`
	Labels         map[string]string   `json:"labels"`
	DescriptorType string              `json:"descriptorType" validate:"required"`
	Sources        []entity.DataSource `json:"sources" validate:"required"`
}

// UpdateDataDescriptorRequest defines the request to update a data descriptor.
// DescriptorType if set must be one of: structured-mysql, structured-postgres, unstructured, code.
type UpdateDataDescriptorRequest struct {
	Labels         map[string]string   `json:"labels"`
	DescriptorType string              `json:"descriptorType"`
	Sources        []entity.DataSource `json:"sources"`
}

// --- Response DTOs ---

// DataDescriptorResponse defines the response for data descriptor
type DataDescriptorResponse struct {
	Name           string                  `json:"name"`
	Namespace      string                  `json:"namespace"`
	Labels         map[string]string       `json:"labels,omitempty"`
	DescriptorType string                  `json:"descriptor_type"`
	Sources        []DataSourceResponse    `json:"sources"`
	OverallPhase   string                  `json:"overall_phase"`
	SourceStatuses []SourceStatusResponse  `json:"source_statuses,omitempty"`
	ConsumedBy     []ObjectReferenceResponse `json:"consumed_by,omitempty"`
	CreatedAt      time.Time               `json:"created_at"`
	UpdatedAt      time.Time               `json:"updated_at"`
	Deleting       bool                    `json:"deleting,omitempty"`
	DeletionTimestamp *time.Time           `json:"deletion_timestamp,omitempty"`
}

type DataSourceResponse struct {
	Type           string                  `json:"type"`
	Name           string                  `json:"name"`
	Metadata       map[string]string       `json:"metadata"`
	Extract        *ExtractConfigResponse  `json:"extract,omitempty"`
	Prompts        *PromptsConfigResponse  `json:"prompts,omitempty"`
	CodeRepo       *CodeRepoConfigResponse `json:"codeRepo,omitempty"`
	Processing     ProcessingConfigResponse `json:"processing,omitempty"`
	Classification []ClassificationResponse `json:"classification,omitempty"`
}

type ExtractConfigResponse struct {
	Tables []string `json:"tables"`
	Querys []string `json:"querys"`
	Files  []string `json:"files"`
}

type PromptsConfigResponse struct {
	ConfigMapName string `json:"configMapName"`
}

type CodeRepoConfigResponse struct {
	CodeRepoType   string `json:"codeRepoType"`
	CodeRepoPath   string `json:"codeRepoPath"`
	CodeRepoBranch string `json:"codeRepoBranch"`
	CodeRepoToken  string `json:"codeRepoToken"`
}

type ProcessingConfigResponse struct {
	Cleaning []CleaningRuleResponse `json:"cleaning"`
}

type CleaningRuleResponse struct {
	Rule   string            `json:"rule"`
	Params map[string]string `json:"params"`
}

type ClassificationResponse struct {
	Domain      string              `json:"domain"`
	Category    string              `json:"category"`
	Subcategory string              `json:"subcategory"`
	Tags        []map[string][]string `json:"tags"`
}

type SourceStatusResponse struct {
	Name         string    `json:"name"`
	Phase        string    `json:"phase"`
	LastSyncTime time.Time `json:"last_sync_time"`
	Records      int64     `json:"records"`
	TaskID       string    `json:"task_id"`
}

type ObjectReferenceResponse struct {
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
}

// ToDataDescriptorResponse converts entity to DTO
func ToDataDescriptorResponse(d *entity.DataDescriptor) DataDescriptorResponse {
	sources := make([]DataSourceResponse, len(d.Sources))
	for i, s := range d.Sources {
		sources[i] = toDataSourceResponse(s)
	}

	statuses := make([]SourceStatusResponse, len(d.SourceStatuses))
	for i, s := range d.SourceStatuses {
		statuses[i] = SourceStatusResponse{
			Name:         s.Name,
			Phase:        s.Phase,
			LastSyncTime: s.LastSyncTime,
			Records:      s.Records,
			TaskID:       s.TaskID,
		}
	}

	consumedBy := make([]ObjectReferenceResponse, len(d.ConsumedBy))
	for i, c := range d.ConsumedBy {
		consumedBy[i] = ObjectReferenceResponse{
			Name:      c.Name,
			Namespace: c.Namespace,
		}
	}

	return DataDescriptorResponse{
		Name:           d.Name,
		Namespace:      d.Namespace,
		Labels:         d.Labels,
		DescriptorType: d.DescriptorType,
		Sources:        sources,
		OverallPhase:   d.OverallPhase,
		SourceStatuses: statuses,
		ConsumedBy:     consumedBy,
		CreatedAt:      d.CreatedAt,
		UpdatedAt:      d.UpdatedAt,
		Deleting:       d.Deleting,
		DeletionTimestamp: d.DeletionTimestamp,
	}
}

func toDataSourceResponse(s entity.DataSource) DataSourceResponse {
	resp := DataSourceResponse{
		Type:     s.Type,
		Name:     s.Name,
		Metadata: s.Metadata,
	}

	if s.Extract != nil {
		resp.Extract = &ExtractConfigResponse{
			Tables: s.Extract.Tables,
			Querys: s.Extract.Querys,
			Files:  s.Extract.Files,
		}
	}

	if s.Prompts != nil {
		resp.Prompts = &PromptsConfigResponse{
			ConfigMapName: s.Prompts.ConfigMapName,
		}
	}

	// Execution-engine CRD supports BOTH:
	// - spec.sources[].codeRepo (used by structured sources attaching a repo)
	// - spec.sources[].metadata.codeRepoPath/codeRepoBranch/codeRepoToken (used by pure git sources: type=github/gitee/gitlab)
	//
	// For a stable frontend contract, always expose repo info via `codeRepo` if present in either place.
	if s.CodeRepo != nil {
		resp.CodeRepo = &CodeRepoConfigResponse{
			CodeRepoType:   s.CodeRepo.CodeRepoType,
			CodeRepoPath:   s.CodeRepo.CodeRepoPath,
			CodeRepoBranch: s.CodeRepo.CodeRepoBranch,
			CodeRepoToken:  s.CodeRepo.CodeRepoToken,
		}
	} else {
		// Deterministic mapping from metadata keys used by execution-engine samples.
		path := ""
		branch := ""
		token := ""
		if s.Metadata != nil {
			path = s.Metadata["codeRepoPath"]
			branch = s.Metadata["codeRepoBranch"]
			token = s.Metadata["codeRepoToken"]
		}
		if path != "" || branch != "" || token != "" {
			resp.CodeRepo = &CodeRepoConfigResponse{
				// For git sources, provider is the source type (github/gitee/gitea/gitlab/git).
				CodeRepoType:   s.Type,
				CodeRepoPath:   path,
				CodeRepoBranch: branch,
				CodeRepoToken:  token,
			}
		}
	}

	cleaning := make([]CleaningRuleResponse, len(s.Processing.Cleaning))
	for i, c := range s.Processing.Cleaning {
		cleaning[i] = CleaningRuleResponse{
			Rule:   c.Rule,
			Params: c.Params,
		}
	}
	resp.Processing = ProcessingConfigResponse{Cleaning: cleaning}

	classification := make([]ClassificationResponse, len(s.Classification))
	for i, c := range s.Classification {
		classification[i] = ClassificationResponse{
			Domain:      c.Domain,
			Category:    c.Category,
			Subcategory: c.Subcategory,
			Tags:        c.Tags,
		}
	}
	resp.Classification = classification

	return resp
}

// DataDescriptorSignatureResponse is the signature payload for a data descriptor (domain type).
type DataDescriptorSignatureResponse struct {
	Data *domain.Signature `json:"data"`
}

func ToDataDescriptorSignatureResponse(sig *domain.Signature) DataDescriptorSignatureResponse {
	return DataDescriptorSignatureResponse{Data: sig}
}

// DataDescriptorSemanticDomainResponse is the semantic_domain payload for a data descriptor (domain type).
type DataDescriptorSemanticDomainResponse struct {
	Data *domain.SemanticDomain `json:"data"`
}

func ToDataDescriptorSemanticDomainResponse(sd *domain.SemanticDomain) DataDescriptorSemanticDomainResponse {
	return DataDescriptorSemanticDomainResponse{Data: sd}
}
